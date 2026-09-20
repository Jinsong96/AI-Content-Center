#!/usr/bin/env python3
"""从 345 篇合格范文里抽「可接受用词基线」，供产出侧的词汇回灌过滤使用。

为什么需要它：
    EVP 词表（backend/evp_wordlist.json，9751 词头）**覆盖不全** —— 实测 become / depend /
    accord / amplify / planner / canopy / galaxy / utility 等常见词的词根都不在表内。
    这些词会掉进 check_vocab 的 unknown（表外）列表，而 unknown 又完全不进分子分母。
    若不加辨别地把 unknown 当「生僻词」回灌给 LLM，就会产出
    「请避免使用 becoming」这类荒谬指令。

判据：
    **本档（或更低档）合格范文里出现过的词 = 教研认可的用词**。
    一个表外词若在本档范文里出现过，它就不是「超纲生僻词」，只是 EVP 表缺漏或
    词形还原没覆盖 —— 不该回灌。反之（长度够长 + 本档范文里从没出现）才当作真生僻词。

    ⚠️ 必须**分档**存，不能合成一份全局词表：合起来的话 B2 范文里的难词
    （habitat / evaporation / canopy）会给 A2 也豁免掉，回灌就失效了。
    低档用过的词高档当然也能用 → 消费侧（evp_vocab_check._BASELINE_SRC）做累积并集。

产出：
    backend/vocab_baseline.json
      {source, n_docs, levels: {A2:[...], B1:[...], B2:[...]}, n_words, words:[...]}
    `levels` 是运行时真正用的；`words`（并集）只为兼容旧格式与人工查阅。
    放在 backend/ 而不是 calibration/ —— 它是运行时依赖，必须跟 evp_wordlist.json
    同级才能被线上部署一起带上去。本脚本负责生成它。

输入依赖：
    calibration/text/<A2|B1|B2>/*.txt（由 build_corpus.py 产出）
    分词复用 backend/evp_vocab_check.py，保证与校验器同一口径。

用法：
    python3 calibration/build_vocab_baseline.py
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "backend"))

import evp_vocab_check as E  # noqa: E402


def words_of(files):
    """一批文本里出现过的词。同时收**原形**与**还原形** ——
    消费侧用 _stem_variants 双侧降词干比对，多收不会误伤，少收才会漏判。"""
    vocab = set()
    for f in files:
        for tok, _is_cap in E.tokenize(f.read_text(encoding="utf-8")):
            vocab.add(tok)
            base, _hit = E.lemmatize(tok)
            vocab.add(base)
    return vocab


def main():
    text_dir = ROOT / "text"
    files = sorted(text_dir.rglob("*.txt"))
    if not files:
        print(f"✗ 找不到语料：{text_dir}（先跑 build_corpus.py）")
        return 1

    by_level = {}
    for f in files:
        by_level.setdefault(f.parent.name, []).append(f)

    levels = {lv: sorted(words_of(fs)) for lv, fs in sorted(by_level.items())}
    union = sorted(set().union(*levels.values())) if levels else []
    for lv, ws in levels.items():
        print(f"   {lv}: {len(by_level[lv]):3d} 篇 → {len(ws):5d} 词")

    out = ROOT.parent / "backend" / "vocab_baseline.json"
    out.write_text(json.dumps({
        "source": "calibration/text —— 教研认可的分级读物范文（初级→A2 / 中级→B1 / 高级→B2）",
        "n_docs": len(files),
        "levels": levels,
        "n_words": len(union),
        "words": union,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"✓ {len(files)} 篇范文 · {len(levels)} 档 → 并集 {len(union)} 词 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
