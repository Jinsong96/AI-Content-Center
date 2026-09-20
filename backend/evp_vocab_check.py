#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ReadPal · 词汇分级校验原型（EVP 词表）

依据 English Vocabulary Profile (EVP) 对一篇英文文章做「词汇超纲」判定。
口径：对每个 Base Word 取「最低等级」；文章里的实词经词形还原后，若其
最低等级 > 目标档位，记为「超纲词」。

词表来源：wordlist.xlsx（EVP，15696 词条 → 9751 去重词头）
用法：
    python3 evp_vocab_check.py --file=文章.md --level=A1
    python3 evp_vocab_check.py --text="..." --level=B1
"""

import json
import os
import re
import sys

# 等级顺序（A1 最简单，C2 最难）
LV_ORDER = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}
# 目标档允许的累计词表边界：A1 档只允许 ≤A1，B2+ 档允许 ≤B2（可配少量 C1）
# 这里 B2 档默认允许到 B2（不含 C1/C2）。
LEVEL_CAP = {"A1": "A1", "A2": "A2", "B1": "B1", "B2": "B2"}
# 超纲率阈值（超了判 exceed，前端据此重试）。
# 2026-09-20 改为**范文标定实测值**（P75 口径，见 calibration/report.md 与 docs/local-notes/34）：
#   教研认可的合格范文（345 篇分级读物）超纲率中位 5.2% / 2.1% / 0.8%，
#   P75 = 8.1% / 3.6% / 1.6% —— 建议值取 P75：允许比中位松一点，但明显超标的仍会被拦。
# 为什么必须改：原值 4%/3%/2% 中 A2 的 4% **低于范文自身中位 5.2%**，等于
#   「教研点头的文章一半以上过不了自家闸门」；B2 的 2% 又比范文 P75 还松。
# ⚠️ A1- 无范文可标定（范文标注只到大档 A2/B1/B2），沿用 5% 并保留「未标定」标记。
#
# 2026-09-20 二次调整（产品侧拍板「优先自然，超纲率可放宽」）：
#   A1 5% → 7% · A2 8.1% → 10% · B1/B2+ 不动。
#   原因：生成文章「不够 natural」的根因之一是低档约束过紧 —— 提示词原本写
#   「禁用习语/隐喻」+「实词重复鼓励」，把母语者最自然的固定搭配（live longer /
#   sleep well / eat well）全堵死，只剩教科书式的直陈句。拆掉这些约束、改为
#   「鼓励高频固定搭配」之后，**地道搭配几乎必然带超纲词**，故同步放宽上限。
#   代价已知情：A1/A2 的超纲率容忍度上升，教研侧的难度一致性会略微变松。
# ⚠️ 改这里必须同步改前端 frontend/index.html 的 offCap() 与 GEN 图提示词
#    （tools/patch_gen_naturalness.py），三处口径必须同值。
VOCAB_THRESHOLD = {"A1": 0.07, "A2": 0.10, "B1": 0.036, "B2": 0.016}

# ---------- 回灌用的功能词表（2026-09-20 新增）----------
# 背景：EVP 把大量语法功能词标在 A2（by / over / around / another / several / should / far / away …），
# 于是它们在 A1- 档全部被算成「超纲」。但这类词是句子的骨架，**LLM 无法「避免使用」**——
# 把它们塞进「禁用词」清单，只会让模型写出不通顺的英文，反而更糟。
# 所以：回灌禁用词时把功能词剔掉，只留**可以替换的实词**。
_FUNCTION_WORDS = frozenset("""
a an the this that these those another other some any no every each either neither both all
most many much more less few several enough such same own else
i you he she it we they me him her us them my your his its our their mine yours hers ours theirs
myself yourself himself herself itself ourselves themselves
who whom whose which what where when why how
be am is are was were been being have has had having do does did done doing
will would shall should can could may might must
and but or so because if while than whether although though unless until since once
not very too also just only even still yet already always never often sometimes usually again
here there now then soon later almost quite rather really perhaps maybe well far away ago back together
by over around about above across after against along among at before behind below beneath beside
between beyond down during except for from in inside into near of off on onto out outside past
through throughout till to toward under up upon with within without
""".split())

# 表外词里只有长度 ≥ 此值的才算「真生僻」，值得回灌。
# 为什么：EVP 表本身有缺漏（实测 become / according 都不在表内），而 lemmatize 也漏了
# 部分规则（larger 还原不出 large）→ 这些**基础词**会掉进 unknown 列表。
# 若不设阈值，回灌会给出「请避免使用 become」这种荒谬指令。
_UNKNOWN_AVOID_MIN_LEN = 8

# 范文用词基线（由 calibration/build_vocab_baseline.py 从 345 篇合格范文抽取）
_BASELINE_PATH = os.path.join(os.path.dirname(__file__), "vocab_baseline.json")
_baseline = None          # {范文档: set(词)}  惰性加载
_baseline_stems = {}      # {本档: frozenset(词干)}  惰性缓存

# 本档 → 范文源档（**累积**）：低档用过的词，高档当然也可以用。
# `A1` 没有对应范文（我们最低档低于 CEFR A2），退用 A2 基线 —— 这是外推，不是实测。
_BASELINE_SRC = {
    "A1": ("A2",),
    "A2": ("A2",),
    "B1": ("A2", "B1"),
    "B2": ("A2", "B1", "B2"),
}


def _stem_variants(word):
    """一个词所有可能的词干变体（**不要求命中 EVP 词表**）。

    为什么不直接用 lemmatize()：它只在「还原结果恰好命中 EVP 词表」时才返回词根，
    而 depend / canopy / accord / amplify 这些词根本身就不在表里（EVP 覆盖不全），
    于是 lemmatize('depending') 原样返回 'depending' —— 基线比对形同失效。
    这里只做形态剥离，且**候选词与基线词用同一套规则**，两侧都降成词干再比。
    """
    w = word.lower()
    out = {w}

    def add(x):
        if not x or len(x) < 3:
            return
        out.add(x)
        out.add(_dedouble(x))
        out.add(x + "e")
        if x.endswith("y"):
            out.add(x[:-1] + "i")

    if w.endswith("ies") and len(w) > 4:
        add(w[:-3] + "y")
    if w.endswith("ied") and len(w) > 4:
        add(w[:-3] + "y")
    if w.endswith("es") and len(w) > 3:
        add(w[:-2])
    if w.endswith("s") and len(w) > 2 and not w.endswith("ss"):
        add(w[:-1])
    if w.endswith("ing") and len(w) > 4:
        add(w[:-3])
    if w.endswith("ed") and len(w) > 3:
        add(w[:-2])
    if w.endswith("ly") and len(w) > 3:
        add(w[:-2])
        out.add(w[:-2][:-1] + "y")
    if w.endswith("er") and len(w) > 3:
        add(w[:-2])
    if w.endswith("est") and len(w) > 4:
        add(w[:-3])
    if w.endswith("able") and len(w) > 5:
        add(w[:-4])
    if w.endswith("tion") and len(w) > 5:
        add(w[:-4])
        out.add(w[:-4] + "t")
    if w.endswith("ment") and len(w) > 5:
        add(w[:-4])
    return out


def _load_baseline():
    """教研认可的范文里，各档分别出现过哪些词。

    用途：EVP 表覆盖不全（实测 become / depend / accord / amplify / planner 等常见词的
    词根都不在表内），这些词会掉进 unknown 列表。若不加辨别地当「生僻词」回灌，
    就会给出「请避免使用 becoming」这种错误指令。
    判据：**本档（或更低档）范文里用过的词 = 教研认可的词**，不该要求 LLM 规避。
    文件缺失时静默降级为空 dict（退回只靠长度判据），不阻塞校验。
    """
    global _baseline
    if _baseline is None:
        try:
            with open(_BASELINE_PATH, encoding="utf-8") as f:
                doc = json.load(f)
            levels = doc.get("levels")
            if isinstance(levels, dict) and levels:
                _baseline = {k: set(v or []) for k, v in levels.items()}
            else:                                   # 旧格式（单份全局词表）兼容
                _baseline = {"A2": set(doc.get("words") or [])}
        except Exception:
            _baseline = {}
    return _baseline


def _load_baseline_stems(level):
    """本档基线所有词的词干集合（只算一次）。"""
    if level not in _baseline_stems:
        bl = _load_baseline()
        stems = set()
        for src in _BASELINE_SRC.get(level, ("A2",)):
            for w in bl.get(src, ()):
                stems |= _stem_variants(w)
        _baseline_stems[level] = frozenset(stems)
    return _baseline_stems[level]

# ---------- 词表 ----------
_WORDLIST_PATH = os.path.join(os.path.dirname(__file__), "evp_wordlist.json")
_wordlist = None


def load_wordlist():
    global _wordlist
    if _wordlist is None:
        with open(_WORDLIST_PATH, encoding="utf-8") as f:
            _wordlist = json.load(f)
    return _wordlist


# ---------- 不规则变化表（词形 -> 词头）----------
# 覆盖高频不规则动词与不规则名词复数
_IRREGULAR = {
    # be 族
    "am": "be", "is": "be", "are": "be", "was": "be", "were": "be",
    "been": "be", "being": "be",
    # have 族
    "has": "have", "had": "have", "having": "have",
    # do 族
    "does": "do", "did": "do", "done": "do", "doing": "do",
    # go 族
    "went": "go", "gone": "go", "going": "go", "goes": "go",
    # 其他高频不规则动词
    "made": "make", "making": "make", "makes": "make",
    "took": "take", "taken": "take", "taking": "take", "takes": "take",
    "saw": "see", "seen": "see", "seeing": "see", "sees": "see",
    "came": "come", "coming": "come", "comes": "come",
    "knew": "know", "known": "know", "knowing": "know", "knows": "know",
    "got": "get", "gotten": "get", "getting": "get", "gets": "get",
    "gave": "give", "given": "give", "giving": "give", "gives": "give",
    "found": "find", "finding": "find", "finds": "find",
    "thought": "think", "thinking": "think", "thinks": "think",
    "told": "tell", "telling": "tell", "tells": "tell",
    "became": "become", "becoming": "become", "becomes": "become",
    "showed": "show", "shown": "show", "showing": "show", "shows": "show",
    "left": "leave", "leaving": "leave", "leaves": "leave",
    "felt": "feel", "feeling": "feel", "feels": "feel",
    "put": "put", "putting": "put", "puts": "put",
    "brought": "bring", "bringing": "bring", "brings": "bring",
    "began": "begin", "begun": "begin", "beginning": "begin", "begins": "begin",
    "kept": "keep", "keeping": "keep", "keeps": "keep",
    "held": "hold", "holding": "hold", "holds": "hold",
    "wrote": "write", "written": "write", "writing": "write", "writes": "write",
    "stood": "stand", "standing": "stand", "stands": "stand",
    "heard": "hear", "hearing": "hear", "hears": "hear",
    "meant": "mean", "meaning": "mean", "means": "mean",
    "met": "meet", "meeting": "meet", "meets": "meet",
    "ran": "run", "run": "run", "running": "run", "runs": "run",
    "paid": "pay", "paying": "pay", "pays": "pay",
    "sat": "sit", "sitting": "sit", "sits": "sit",
    "spoke": "speak", "spoken": "speak", "speaking": "speak", "speaks": "speak",
    "led": "lead", "leading": "lead", "leads": "lead",
    "grew": "grow", "grown": "grow", "growing": "grow", "grows": "grow",
    "lost": "lose", "losing": "lose", "loses": "lose",
    "fell": "fall", "fallen": "fall", "falling": "fall", "falls": "fall",
    "sent": "send", "sending": "send", "sends": "send",
    "built": "build", "building": "build", "builds": "build",
    "understood": "understand", "understanding": "understand", "understands": "understand",
    "drew": "draw", "drawn": "draw", "drawing": "draw", "draws": "draw",
    "broke": "break", "broken": "break", "breaking": "break", "breaks": "break",
    "spent": "spend", "spending": "spend", "spends": "spend",
    "rose": "rise", "risen": "rise", "rising": "rise", "rises": "rise",
    "drove": "drive", "driven": "drive", "driving": "drive", "drives": "drive",
    "bought": "buy", "buying": "buy", "buys": "buy",
    "wore": "wear", "worn": "wear", "wearing": "wear", "wears": "wear",
    "chose": "choose", "chosen": "choose", "choosing": "choose", "chooses": "choose",
    "taught": "teach", "teaching": "teach", "teaches": "teach",
    "caught": "catch", "catching": "catch", "catches": "catch",
    "fought": "fight", "fighting": "fight", "fights": "fight",
    "sold": "sell", "selling": "sell", "sells": "sell",
    "won": "win", "winning": "win", "wins": "win",
    "threw": "throw", "thrown": "throw", "throwing": "throw", "throws": "throw",
    "wore": "wear", "worn": "wear", "wearing": "wear", "wears": "wear",
    "flew": "fly", "flown": "fly", "flying": "fly", "flies": "fly",
    "swam": "swim", "swum": "swim", "swimming": "swim", "swims": "swim",
    "sang": "sing", "sung": "sing", "singing": "sing", "sings": "sing",
    "rang": "ring", "rung": "ring", "ringing": "ring", "rings": "ring",
    "ate": "eat", "eaten": "eat", "eating": "eat", "eats": "eat",
    "drank": "drink", "drunk": "drink", "drinking": "drink", "drinks": "drink",
    "slept": "sleep", "sleeping": "sleep", "sleeps": "sleep",
    "forgot": "forget", "forgotten": "forget", "forgetting": "forget", "forgets": "forget",
    # 不规则名词复数
    "children": "child", "men": "man", "women": "woman", "people": "person",
    "feet": "foot", "teeth": "tooth", "mice": "mouse",
    # 其他高频
    "said": "say", "saying": "say", "says": "say",
    "read": "read", "reading": "read", "reads": "read",
}


def _dedouble(w):
    """双写辅音还原：running->runn->run；stopped->stopp->stop"""
    if len(w) >= 3 and w[-1] == w[-2]:
        return w[:-1]
    return w


def lemmatize(word):
    """词形 -> 词头（还原优先：ing/ed/s 先还原，learning->learn 而非 learning(B2 名词)）。"""
    w = word.lower()
    wl = load_wordlist()
    # 1. 不规则表优先
    if w in _IRREGULAR:
        base = _IRREGULAR[w]
        return base, base in wl
    # 规则后缀剥离（逐个尝试，命中即止）
    candidates = []
    if w.endswith("ies") and len(w) > 4:
        candidates.append(w[:-3] + "y")           # studies -> study
    if w.endswith("ied") and len(w) > 4:
        candidates.append(w[:-3] + "y")           # studied -> study
    if w.endswith("es") and len(w) > 3:
        candidates.append(w[:-2])                 # boxes -> box
    if w.endswith("s") and len(w) > 2 and not w.endswith("ss"):
        candidates.append(w[:-1])                 # cats -> cat
    if w.endswith("ing") and len(w) > 4:
        candidates.append(w[:-3])                 # playing -> play
        candidates.append(_dedouble(w[:-3]))      # running -> run
        candidates.append(w[:-3] + "e")           # changing -> change / making -> make
    if w.endswith("ed") and len(w) > 3:
        candidates.append(w[:-2])                 # played -> play
        candidates.append(_dedouble(w[:-2]))      # stopped -> stop
        candidates.append(w[:-2] + "e")           # liked -> like
    if w.endswith("d") and len(w) > 2:
        candidates.append(w[:-1])                 # loved -> love
    if w.endswith("ly") and len(w) > 3:
        candidates.append(w[:-2])                 # quickly -> quick
        candidates.append(w[:-2][:-1] + "y")      # happily -> happy
    if w.endswith("er") and len(w) > 3:
        candidates.append(w[:-2])                 # bigger -> bigg
        candidates.append(_dedouble(w[:-2]))      # bigger -> big
        candidates.append(w[:-2][:-1] + "y")      # easier -> easy (easi -> easy)
    if w.endswith("est") and len(w) > 4:
        candidates.append(w[:-3])                 # biggest -> bigg
        candidates.append(_dedouble(w[:-3]))      # biggest -> big
        candidates.append(w[:-3][:-1] + "y")      # easiest -> easy (easi -> easy)
    for c in candidates:
        if c in wl:
            return c, True
    # 3. 原词兜底
    if w in wl:
        return w, True
    return w, False


# ---------- 校验 ----------
def tokenize(text):
    """提取英文单词 token（去标点、去数字）。返回 list[(token, is_capitalized)]"""
    toks = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)
    out = []
    for t in toks:
        low = t.lower()
        if low in ("s", "t", "re", "ll", "ve", "d", "m"):  # 缩写残留
            continue
        out.append((low, t[0].isupper()))
    return out


def pick_avoid_words(over, unknown, level, limit=20):
    """从校验结果里挑出「值得让 LLM 规避」的词（供下一轮生成回灌）。

    判据（2026-09-20 定）：
    · over（EVP 表内、等级高于本档 cap）—— 剔除功能词、剔除本档范文基线里的词后保留。
      为什么也要过基线：`A1` 的 cap 是 EVP A1（仅 643 词族），**比教研的 A2 范文还低**，
      于是 top / win / fan / side / care / heavy / race 这些基础词全被算成「超纲」。
      要求 LLM 规避它们会写出别扭的英文 —— 而范文里明明在用。
      （对 A2/B1/B2 几乎无影响：它们的超纲词本就在本档范文基线之外。）
    · unknown（表外词）—— 三道过滤后才保留：
      ① 长度 >= _UNKNOWN_AVOID_MIN_LEN 且不含撇号：短词 / 所有格多半是 EVP 缺漏或
         词形还原没覆盖（become / larger / planners），不是真生僻词；
      ② 词干不在**本档范文基线**里：范文用过的词 = 教研认可的词，不该要求规避。
         ⚠️ 必须比词干（`_stem_variants` 双侧降词干），只比原 token 会漏判 ——
         unknown 存的是 `depending`、基线存的是 `depends`，直接比必然不等。
      ③ 本档基线只取**本档及更低档**，不是全部范文：否则 B2 范文里的难词
         （habitat / evaporation）会给 A2 也豁免掉。
    排序：over 按等级从高到低 —— 先让 LLM 干掉最难的词。
    """
    base_stems = _load_baseline_stems(level)
    out = []
    for base, lv in sorted(over or [], key=lambda x: -LV_ORDER.get(x[1], 0)):
        if base in _FUNCTION_WORDS or base in out:
            continue
        if _stem_variants(base) & base_stems:
            continue
        out.append(base)
        if len(out) >= limit:
            return out
    for w in sorted(set(unknown or [])):
        if len(w) < _UNKNOWN_AVOID_MIN_LEN or "'" in w or w in out:
            continue
        if _stem_variants(w) & base_stems:
            continue
        out.append(w)
        if len(out) >= limit:
            return out
    return out


def check_vocab(text, level, topic_words=None):
    """
    校验一篇文章的词汇超纲情况。
    返回 dict: {over: [...], unknown: [...], over_rate, total_content_words}
    """
    cap_lv = LEVEL_CAP.get(level, "B2")
    wl = load_wordlist()
    toks = tokenize(text)
    # 首字母大写且不在句首的词，视为专名（人名/地名），排除
    # 简化处理：收集所有大写开头的词，若它们不在句首，当作专名
    over = []       # 超纲词
    unknown = []    # 表外词（不在词表，可能是专名/罕见词）
    seen = set()
    content_total = 0
    over_total = 0

    topic_set = set(t.lower() for t in (topic_words or []))

    # 句子切分，用于判断"句首词"（句首大写不算专名）
    sentences = re.split(r'(?<=[.!?])\s+', text)
    for si, sent in enumerate(sentences):
        stoks = tokenize(sent)
        for ti, (tok, is_cap) in enumerate(stoks):
            if tok in topic_set:
                continue  # topic words 豁免
            # 专名判定：大写开头 + 非句首 + 不在词表（专名通常不在 EVP）
            if is_cap and ti > 0 and tok not in wl:
                continue  # 视为专名，排除
            base, hit = lemmatize(tok)
            if not hit:
                unknown.append(tok)
                continue
            content_total += 1
            base_lv = wl[base]
            if LV_ORDER[base_lv] > LV_ORDER[cap_lv]:
                over_total += 1
                if base not in seen:
                    seen.add(base)
                    over.append((base, base_lv))

    over_rate = (over_total / content_total) if content_total else 0.0
    thr = VOCAB_THRESHOLD.get(level, 0.03)
    return {
        "level": level, "cap": cap_lv,
        "content_words": content_total,
        "over_count": over_total,
        "over_rate": round(over_rate, 4),
        "threshold": thr,
        "exceed": over_rate > thr,
        "over_words": over,
        "unknown_words": sorted(set(unknown)),
        # 供「生成 → 校验 → 回灌重写」闭环使用：下一轮生成该规避的具体词。
        # 前端按档打包送进 GEN 的 avoid_words 入参（见 index.html 的 runGeneration）。
        "avoid_words": pick_avoid_words(over, unknown, level),
    }


def check_vocab_batch(articles, words_map=None):
    """批量校验：articles = {level: text}，返回 {level: result}。
    words_map 可选，{level: [topic_words]}，用于豁免生词表（不计超纲）。"""
    out = {}
    for lv, text in (articles or {}).items():
        if lv not in LEVEL_CAP or not text:
            continue
        tw = (words_map or {}).get(lv)
        out[lv] = check_vocab(text, lv, topic_words=tw)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--text")
    ap.add_argument("--level", default="B1", choices=list(LV_ORDER.keys()))
    args = ap.parse_args()

    if args.file:
        text = open(args.file, encoding="utf-8").read()
    elif args.text:
        text = args.text
    else:
        ap.print_help()
        sys.exit(1)

    r = check_vocab(text, args.level)
    print(f"目标档位 {args.level}（允许 ≤{r['cap']}）")
    print(f"实词数 {r['content_words']} / 超纲 {r['over_count']} / 超纲率 {r['over_rate']*100:.1f}%")
    print(f"超纲词（top 30）: {[w for w, l in r['over_words'][:30]]}")
    print(f"表外词（top 20）: {r['unknown_words'][:20]}")
