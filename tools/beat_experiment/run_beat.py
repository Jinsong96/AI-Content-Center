#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最小验证：节拍（beat）驱动的分级文章生成 —— 只跑 draft 级验证，不动线上工作流。

目的（只回答两个问题）：
  Q1 节拍到底能不能量化？ → 量化单位 = 「语义要点清单」+「事实锚点清单」，两者都可枚举、可判定
  Q2 生成会不会改变素材原意？ → 用「锚点命中 + 反向幻觉核查 + 语义方向核查」三重判定

做法：与线上 GEN 同源（同模型 deepseek-ai/DeepSeek-V4-Flash、同温度 0.45），
      但把 fact_map 换成 beat_map，并强制「全部节拍必须覆盖」。
"""
import json, os, sys, argparse, urllib.request, urllib.error, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "/Users/jinsongli/WorkBuddy/2026-09-10-10-51-04/readpal"

# ── 12 档规格（与 tools/dify_build_graphs.py 的 LEVELS 一致，只取本实验需要的字段）──
SPEC = {
    "A1_1": dict(d="A1.1", wc=(60, 90),    msl=(5, 7),   paras=4,
                 vocab="只用最高频 600–800 词，几乎不出现派生词与抽象名词",
                 grammar="一般现在时、be 动词、there be；连接词只用 and / but",
                 topic="读者五米之内的世界；一个场景一件事，不设转折"),
    "A2_1": dict(d="A2.1", wc=(160, 200),  msl=(10, 12), paras=5,
                 vocab="最高频 1000–1200 词，只用具象名词",
                 grammar="比较级、be going to / will、基础定语从句（who / which）",
                 topic="兴趣爱好、旅行出行、朋友与情绪；有开头—发展—结尾或总分关系"),
    "B1_1": dict(d="B1.1", wc=(300, 380),  msl=(13, 15), paras=6,
                 vocab="最高频 2000–2500 词，开始出现常见抽象名词（method / issue / benefit）",
                 grammar="被动语态、宾语从句、动名词与不定式作主宾语",
                 topic="科技产品、环境与可持续、学习方法；阅读目的转向「知道点什么」"),
    "B2P_3": dict(d="B2+.3", wc=(900, 1200), msl=(22, 26), paras=8,
                  vocab="AWL 学术词密度 8–10%",
                  grammar="句法复杂度与词汇抽象度同时到顶",
                  topic="抽象论证、跨领域引用、文学性非虚构、当代思想散文"),
}
# 进阶锚点从这一档起才要求必现
ADV_FROM = {"A1_1": False, "A2_1": False, "B1_1": True, "B2P_3": True}


def distribute(n_paras, beats):
    """把 8 个节拍分配到 n_paras 段。规则与 docs/12 的分组表一致。"""
    k = len(beats)
    base = k // n_paras
    extra = k % n_paras
    out, i = [], 0
    for p in range(n_paras):
        take = base + (1 if p < extra else 0)
        out.append(list(range(i + 1, i + take + 1)))
        i += take
    return out


EXPAND_CLAUSE = """
【素材不足时怎么办（与线上 GEN 一致）】
- 若节拍表的信息量不足以撑到本档下限词数，**优先保证下限**：允许做
  **不引入新数字、新人名、新机构、新事件的合理扩写**——解释成因、打类比、
  举读者的日常场景、描述一般性影响、说明为什么这对普通人重要。
- **绝对不得编造**具体的百分比、年份、机构名、人名、地名——事实一致性是硬校验。
- 但**不允许以「怕编造」为理由把文章写短**：写不到下限同样判不合格。
"""


TIGHT_CLAUSE = """
【句数预算（本档最关键的一条）】
- 本档每个节拍**只允许写 1 句**，最多 2 句。
- **全篇句数必须控制在 9–13 句之间**（这是硬指标）。
- 不要写过渡句、不要写补充说明句、不要举例、不要重复。讲完意思立刻停。
"""


DEEP_CLAUSE = """
【每段词数预算（本档最关键的一条）】
- 段落数**严格固定 {n} 段，不允许增加段落来凑字数**。
- 每一段**必须写到 {plo}–{phi} 词**（这是每段硬指标，写不到下限就不许进入下一段）。
- 每段把这个节拍写足：解释成因与机制、给出细节与数字、说明对普通人的影响、必要时呈现多方立场。
- **不要靠加段落、也不要靠把单句写超长来凑字数**——靠把每一段的**内容展开得更充分**。
"""


def build_prompt(level_key, beats, material, expand=False, no_numbers=False, tight=False, deep=False):
    S = SPEC[level_key]
    adv = ADV_FROM[level_key]
    NUMERIC = {"25 degrees", "1 in 1,000 children", "85 years", "2 percent", "over a century"}

    def core_of(b):
        return [a for a in b["anchors_core"] if not (no_numbers and a in NUMERIC)]

    dc = DEEP_CLAUSE.format(n=S["paras"], plo=round(S["wc"][0] / S["paras"]),
                            phi=round(S["wc"][1] / S["paras"])) if deep else ""
    groups = distribute(S["paras"], beats)
    beat_lines = []
    for b in beats:
        core = core_of(b)
        adv_txt = ("、".join(b["anchors_adv"]) and f"\n     · 进阶锚点（{'本档必须出现' if adv else '本档不要求，不出现不算错'}）：" + "、".join(b["anchors_adv"])) if b["anchors_adv"] else ""
        core_txt = ("、".join(core)) if core else "（本档无强制锚点，讲清意思即可）"
        beat_lines.append(
            f"  {b['id']}. {b['point']}\n"
            f"     · 核心锚点（**所有档位都必须出现**）：" + core_txt + adv_txt)
    beats_txt = "\n".join(beat_lines)
    map_txt = "\n".join(f"  第 {i+1} 段 → 覆盖节拍 {g}" for i, g in enumerate(groups))

    return f"""你是英语分级阅读作者。基于给定的「内容节拍表」，生成 {S['d']} 这一档的**一篇**文章。

【本档硬性规格】
- 正文段落数：**{S['paras']} 段**（必须正好 {S['paras']} 段）
- 正文字数：**{S['wc'][0]}–{S['wc'][1]} 词**（硬区间：低于下限、超过上限都判不合格）
- 平均句长：**{S['msl'][0]}–{S['msl'][1]} 词/句**（按全篇平均）
- 词汇层级：{S['vocab']}
- 语法范围：{S['grammar']}
- 主题半径：{S['topic']}

【内容节拍表（共 {len(beats)} 个节拍，**一个都不能少**）】
{beats_txt}

【节拍覆盖要求（最重要）】
1. **{len(beats)} 个节拍必须全部出现在文章里**，顺序与编号一致。**不得因为语言简单就省略节拍**——
   {S['d']} 只是句子更短、词更简单，**信息总量不能少**。
2. 本档 {S['paras']} 段与节拍的对应关系固定为：
{map_txt}
3. 每一段只能写它应该覆盖的那几个节拍，**不要跨节拍、不要漏节拍、不要新增素材里没有的内容**。

【锚点要求】
- **核心锚点**必须在正文中出现（数字可以写成英文单词或阿拉伯数字）。
- **进阶锚点**：{"本档必须全部出现。" if adv else "本档不要求出现；如果为了凑字数硬塞进去，反而破坏本档语言难度，请不要出现。"}
- 🚫 **绝对不得出现素材里没有的数字、百分比、人名、机构名、地名**——幻觉是硬失败项。
{"- 🚫 **本档额外禁止**：不要出现任何具体数字、年份、百分比、温度值、时长（如 1901、2014、0.5%、2.7 degrees、85 years、2 percent、25 degrees）。本档只用简单的话讲清意思，数字留到更高档位再写。" if no_numbers else ""}

【输出格式：严格 JSON，只输出一个 JSON 对象，不要 markdown 代码块、不要解释】
{{"paras":["段1","段2","..."],"beat_map":{json.dumps(groups, ensure_ascii=False)},"words":["word — 中文释义"]}}

【素材原文（供你理解上下文，但文章要重写，不要照抄句子）】
{material}
{EXPAND_CLAUSE if expand else ""}
{TIGHT_CLAUSE if tight else ""}
{dc}
"""


def call_sf(prompt, max_tokens, temperature=0.45, model="deepseek-ai/DeepSeek-V4-Flash"):
    key = json.load(open(os.path.join(REPO, "backend/keys.fallback.json"), encoding="utf-8"))["SF_API_KEY"]
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "enable_thinking": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.siliconflow.cn/v1/chat/completions", data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    return d, time.time() - t0


def extract_json(text):
    s = text.replace("```json", "").replace("```", "").strip()
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b < 0:
        return None
    try:
        return json.loads(s[a:b + 1])
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--material", default=os.path.join(HERE, "material.txt"))
    ap.add_argument("--expand", action="store_true", help="加回线上「允许合理扩写」许可")
    ap.add_argument("--no-numbers", action="store_true", help="低档简化：不要求也不允许出现具体数字")
    ap.add_argument("--tight", action="store_true", help="句数预算：每节拍 1 句，全篇 9–13 句")
    ap.add_argument("--deep", action="store_true", help="每段词数预算：每段必须写到区间，且段数固定")
    ap.add_argument("--subset", default="", help="只使用指定节拍，如 1,3,5,7")
    a = ap.parse_args()

    beats = json.load(open(os.path.join(HERE, "beats.json"), encoding="utf-8"))["beats"]
    if a.subset:
        keep = {int(x) for x in a.subset.split(",") if x.strip()}
        beats = [b for b in beats if b["id"] in keep]
    material = open(a.material, encoding="utf-8").read().strip()
    prompt = build_prompt(a.level, beats, material, expand=a.expand,
                          no_numbers=a.no_numbers, tight=a.tight, deep=a.deep)
    open(a.out + ".prompt.txt", "w", encoding="utf-8").write(prompt)

    mt = 2000 if a.level in ("A1_1", "A2_1") else 9000
    d, dt = call_sf(prompt, mt)
    msg = d["choices"][0]["message"]
    raw = msg.get("content") or ""
    u = d.get("usage") or {}
    print("level=%s 耗时=%.1fs  prompt_tokens=%s completion_tokens=%s finish=%s" % (
        a.level, dt, u.get("prompt_tokens"), u.get("completion_tokens"), d["choices"][0].get("finish_reason")))
    obj = extract_json(raw)
    json.dump({"level": a.level, "elapsed": dt, "usage": u,
               "raw": raw, "parsed": obj, "prompt": prompt},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if obj is None:
        print("!! JSON 解析失败，原始输出前 500 字：")
        print(raw[:500])
        return
    paras = obj.get("paras") or []
    print("段数=%d (规格 %d)  字符数=%d" % (len(paras), SPEC[a.level]["paras"], sum(len(p) for p in paras)))
    for i, p in enumerate(paras, 1):
        print("  P%d: %s" % (i, str(p)[:150]))


if __name__ == "__main__":
    main()
