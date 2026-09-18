#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""区间模型离线验证（对应 docs/14-素材池与档位区间设计.md §10.3）。

验证四件事：
  V1 区间判定  —— 给定素材，模型判出的档位区间是否连续？下界与信息点条数是否吻合？
  V2 逐档生成  —— 区间内每一档能否达标（词数/段数/句长/锚点/无幻觉）？
  V3 大意复核  —— 每档产出的大意与素材基准是否一致？（R5 的失败率）
  V4 预算微调  —— A1.1 能否落进 90 词？B2+.3 每段 100–135 能否达标？（docs/13 遗留未解项 1、2）

全程直连硅基流动，**不改 Dify 任何图、不推 draft**。

用法：
  P=/Users/jinsongli/.workbuddy/binaries/python/versions/3.13.12/bin/python3
  $P run_range.py --stage=plan
  $P run_range.py --stage=gen
  $P run_range.py --stage=check
"""
import json, os, re, sys, time, argparse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "/Users/jinsongli/WorkBuddy/2026-09-10-10-51-04/readpal"
WORK = os.environ.get("RANGE_WORK", "/tmp/rp/range")

GEN_MODEL = "deepseek-ai/DeepSeek-V4-Flash"     # 与线上 GEN 同模型
JUDGE_MODEL = "deepseek-ai/DeepSeek-V4-Pro"     # 换模型判，避免自评偏差

# ── 12 档规格（唯一真源：tools/dify_build_graphs.py 的 LEVELS，此处只取本实验需要的字段）──
SPEC = {
    "A1_1": dict(d="A1.1", wc=(60, 90),     msl=(5, 7),   paras=4,  smax=3,
                 vocab="只用最高频 600–800 词，几乎不出现派生词与抽象名词",
                 grammar="一般现在时、be 动词、there be；连接词只用 and / but",
                 topic="读者五米之内的世界；一个场景一件事，不设转折"),
    "A1_2": dict(d="A1.2", wc=(90, 120),    msl=(7, 9),   paras=4,  smax=3,
                 vocab="最高频 800 词以内，只用具象名词",
                 grammar="新增现在进行时、can / like to、because / so",
                 topic="动物、身体、四季、简单节日；两段式结构"),
    "A1_3": dict(d="A1.3", wc=(120, 160),   msl=(8, 10),  paras=4,  smax=4,
                 vocab="最高频 800–1000 词",
                 grammar="一般过去时（规则动词 + 约 20 个高频不规则）",
                 topic="从「我每天做什么」转向「我昨天遇到了什么」"),
    "A2_1": dict(d="A2.1", wc=(160, 200),   msl=(10, 12), paras=5,  smax=3,
                 vocab="最高频 1000–1200 词，只用具象名词",
                 grammar="比较级、be going to / will、基础定语从句（who / which）",
                 topic="兴趣爱好、旅行出行、朋友与情绪；开头—发展—结尾或总分关系"),
    "A2_2": dict(d="A2.2", wc=(200, 250),   msl=(11, 13), paras=5,  smax=4,
                 vocab="最高频 1200–1500 词",
                 grammar="现在完成时、情态动词、when / if 状语从句",
                 topic="具象科普——动物为什么冬眠、雨是怎么来的"),
    "A2_3": dict(d="A2.3", wc=(250, 300),   msl=(12, 14), paras=5,  smax=4,
                 vocab="最高频 1500–1800 词",
                 grammar="初步被动语态、过去进行时",
                 topic="第一次离开读者的直接生活经验；简单中外对比"),
    "B1_1": dict(d="B1.1", wc=(300, 380),   msl=(13, 15), paras=6,  smax=4,
                 vocab="最高频 2000–2500 词，开始出现常见抽象名词（method / issue / benefit）",
                 grammar="被动语态、宾语从句、动名词与不定式作主宾语",
                 topic="科技产品、环境与可持续、学习方法；阅读目的转向「知道点什么」"),
    "B1_2": dict(d="B1.2", wc=(380, 450),   msl=(15, 17), paras=6,  smax=5,
                 vocab="最高频 2500–3000 词，可含常见抽象名词与轻学术词",
                 grammar="条件句 I / II、现在完成进行时、非限定性定语从句",
                 topic="社会现象、创业与商业常识、健康科学；出现明确的作者立场"),
    "B1_3": dict(d="B1.3", wc=(450, 550),   msl=(16, 18), paras=6,  smax=5,
                 vocab="最高频 3000 词，可含轻学术词与报道性动词",
                 grammar="过去完成时、报道性动词、分词短语作状语",
                 topic="人物故事、事件复盘、深度文化对比"),
    "B2P_1": dict(d="B2+.1", wc=(550, 700), msl=(18, 21), paras=8,  smax=5,
                  vocab="AWL 学术词密度 4–6%",
                  grammar="名词化密度上升、hedging、倒装、多重从句嵌套",
                  topic="主流媒体的解释性报道与商业案例"),
    "B2P_2": dict(d="B2+.2", wc=(700, 900), msl=(20, 23), paras=8,  smax=6,
                  vocab="AWL 学术词密度 6–8%",
                  grammar="反讽、隐喻、让步结构与显性的作者声音",
                  topic="有真实争议、有多方立场的议题"),
    "B2P_3": dict(d="B2+.3", wc=(900, 1200), msl=(22, 26), paras=8, smax=7,
                  vocab="AWL 学术词密度 8–10%",
                  grammar="句法复杂度与词汇抽象度同时到顶",
                  topic="抽象论证、跨领域引用、文学性非虚构"),
}
ORDER = ["A1_1", "A1_2", "A1_3", "A2_1", "A2_2", "A2_3",
         "B1_1", "B1_2", "B1_3", "B2P_1", "B2P_2", "B2P_3"]
# 进阶锚点从这一档起才要求必现
ADV_FROM = {"A1_1": False, "A1_2": False, "A1_3": False,
            "A2_1": False, "A2_2": False, "A2_3": False,
            "B1_1": True, "B1_2": True, "B1_3": True,
            "B2P_1": True, "B2P_2": True, "B2P_3": True}
# 低档用「大意拍」的档位组（段数 ≤5 → 用合并后的大意拍）
PLAIN_LEVELS = {"A1_1", "A1_2", "A1_3", "A2_1", "A2_2", "A2_3"}


# ════════════════════════════════════════════════════════════════════════════
# 基础工具
# ════════════════════════════════════════════════════════════════════════════
def call_sf(prompt, max_tokens, temperature=0.45, model=GEN_MODEL, retries=2):
    key = json.load(open(os.path.join(REPO, "backend/keys.fallback.json"),
                         encoding="utf-8"))["SF_API_KEY"]
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "enable_thinking": False,
    }).encode("utf-8")
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(
                "https://api.siliconflow.cn/v1/chat/completions", data=body,
                headers={"Authorization": "Bearer " + key,
                         "Content-Type": "application/json"}, method="POST")
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            return d, time.time() - t0
        except Exception as e:                      # noqa: BLE001
            last = e
            print("   !! 调用失败(%d/%d): %s" % (i + 1, retries + 1, e))
            if i < retries:
                time.sleep(3)
    raise last


def extract_json(text):
    """容错解析：剥 think / markdown 围栏，再去尾逗号（真实踩过的坑）。"""
    s = re.sub(r"<think>[\s\S]*?</think>", "", str(text or ""))
    s = s.replace("```json", "").replace("```", "").strip()
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b < 0:
        return None
    frag = s[a:b + 1]
    for cand in (frag, re.sub(r",(\s*[\]\}])", r"\1", frag)):
        try:
            return json.loads(cand)
        except Exception:                           # noqa: BLE001
            continue
    return None


def word_tokens(t):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-\.%]*", t)


def sentences(t):
    return [s for s in re.split(r"(?<=[.!?])\s+", t.strip()) if s.strip()]


NUMWORD = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
           "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
           "nineteen": 19, "twenty": 20, "twenty-five": 25, "thirty": 30,
           "thirty-four": 34, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
           "ninety": 90, "hundred": 100, "thousand": 1000, "million": 1000000}


def extract_numbers(t):
    out = set()
    for m in re.findall(r"\d+(?:[.,]\d+)?", t):
        out.add(m.rstrip("."))
    low = t.lower()
    for w, v in NUMWORD.items():
        if re.search(r"\b" + re.escape(w) + r"\b", low):
            out.add(str(v))
    return out


def distribute(n_paras, beats):
    """把节拍分配到段落（前 extra 段多分一个）。"""
    k = len(beats)
    base, extra = k // n_paras, k % n_paras
    out, i = [], 0
    for p in range(n_paras):
        take = base + (1 if p < extra else 0)
        out.append(list(range(i + 1, i + take + 1)))
        i += take
    return out


def load_json(p, default=None):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def save_json(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ════════════════════════════════════════════════════════════════════════════
# Step 0a —— 把 8 个细节拍合并成「大意拍」（去数字、去专名，只留语义）
# ════════════════════════════════════════════════════════════════════════════
PLAIN_PROMPT = """下面是一篇真实素材的 8 个「细节节拍」（每个节拍 = 一个必讲的信息点，含核心锚点与进阶锚点）。

任务：把它们**合并压缩**成 4 个「大意拍」，供 A1 / A2 低难度文章使用。

合并规则（严格遵守）：
1. **固定合并为 4 条**：第 1+2 拍 → 大意 A；第 3+4 拍 → 大意 B；第 5+6 拍 → 大意 C；第 7+8 拍 → 大意 D。
2. 每条大意只保留「谁 / 发生了什么 / 意味着什么」的**语义骨架**，用一句中文说清。
3. **绝对不得出现任何数字、百分比、年份、温度、机构名、人名、地名**（这些是锚点，低档不写）。
4. 不得引入素材里没有的信息、不得改变方向（增加↔减少、有利↔不利）。
5. 语言要口语化、具象——低档读者是初学者，抽象概念要落到「看得见的事」上。

【8 个细节节拍】
%s

输出 JSON（只输出 JSON）：
{"plain":[{"id":"A","point":"…"},{"id":"B","point":"…"},{"id":"C","point":"…"},{"id":"D","point":"…"}]}
"""


def build_plain_beats(beats):
    txt = "\n".join("  %d. %s" % (b["id"], b["point"]) for b in beats)
    d, dt = call_sf(PLAIN_PROMPT % txt, 1200, temperature=0.3)
    obj = extract_json(d["choices"][0]["message"].get("content") or "")
    plain = (obj or {}).get("plain") or []
    print("   [0a] 大意拍 %d 条，耗时 %.1fs" % (len(plain), dt))
    for p in plain:
        print("        %s. %s" % (p.get("id"), p.get("point")))
    return plain, dt


# ════════════════════════════════════════════════════════════════════════════
# Step 0b —— 素材大意基准（跨档对齐的锚）
# ════════════════════════════════════════════════════════════════════════════
BASELINE_PROMPT = """阅读下面的英文素材，写出它的**分层大意**。

要求：
1. 用中文，**正好 6 句**，按素材自身的信息顺序排列。
2. 每句对应一个信息层，说清「谁 / 发生了什么 / 为什么 / 结果是什么」。
3. **必须包含素材里的关键数字、年份、机构名**（这是给复核用的基准，数字不能省）。
4. 不得引入素材里没有的信息，不得改变方向（增加↔减少、有利↔不利、地区张冠李戴）。

【素材】
%s

输出 JSON（只输出 JSON）：
{"baseline":["第1句","第2句","第3句","第4句","第5句","第6句"]}
"""


def build_baseline(material):
    d, dt = call_sf(BASELINE_PROMPT % material, 1200, temperature=0.2)
    obj = extract_json(d["choices"][0]["message"].get("content") or "")
    base = (obj or {}).get("baseline") or []
    print("   [0b] 素材大意基准 %d 句，耗时 %.1fs" % (len(base), dt))
    for i, b in enumerate(base, 1):
        print("        %d. %s" % (i, b))
    return base, dt


# ════════════════════════════════════════════════════════════════════════════
# Step 1 —— 区间判定：12 档逐一判可行性 → 取最长连续区间
# ════════════════════════════════════════════════════════════════════════════
VIAB_PROMPT = """你是英语分级阅读的内容规划师。下面给你一篇真实素材和从它抽出的 8 个「细节节拍」（信息点）。

任务：对 12 个子档**逐一判断**——"这篇素材能不能重写成该档位的文章"。

【判定原则】

**上限由「信息点条数」决定**：一篇素材能出的最高档，取决于它有多少个可展开的细节。
- 高档（B2+ 需 900–1200 词 / 8 段）必须有 8 个以上可展开的细节才能撑满篇幅。
- 如果素材只有 4 个信息点，B2+ 判 false（撑不满）。

**下限由「可简化度」决定**：素材越依赖数字/专名/抽象机制，越写不出低档。
- A1.1 只有 60–90 词 / 4 段 / 每段 15–22 词。**每段只够讲一件极其具体的小事**。
- 判定 A1 时问自己：把数字、专名、抽象机制全部去掉后，剩下的 4 件"小事"还能构成一篇完整的文章吗？如果去掉后只剩空话，判 false。
- 一般规律：**信息点越多、机制越抽象，下界越高**；反之越低。

【12 个子档的字数规格】
A1.1｜60–90 词｜4 段｜每段 15–22 词
A1.2｜90–120 词｜4 段｜每段 23–30 词
A1.3｜120–160 词｜4 段｜每段 30–40 词
A2.1｜160–200 词｜5 段｜每段 32–40 词
A2.2｜200–250 词｜5 段｜每段 40–50 词
A2.3｜250–300 词｜5 段｜每段 50–60 词
B1.1｜300–380 词｜6 段｜每段 50–63 词
B1.2｜380–450 词｜6 段｜每段 63–75 词
B1.3｜450–550 词｜6 段｜每段 75–92 词
B2+.1｜550–700 词｜8 段｜每段 69–88 词
B2+.2｜700–900 词｜8 段｜每段 88–113 词
B2+.3｜900–1200 词｜8 段｜每段 113–150 词

【素材】
%s

【素材的 8 个细节节拍】（供 B1 及以上使用）
%s

【已合并好的 4 条「大意拍」】（供 A1 / A2 使用：去数字、去专名，只留语义骨架）
%s

**判定低档（A1/A2）时，输入用的是上面这 4 条大意拍，不是 8 个细节拍。**
所以判低档要问的是：**这 4 条大意拍能否各自展开成一段具体内容？**
- 4 条大意拍与低档段数 1:1 对应（A1 用 4 段、A2 用 5 段）。
- 只要每条大意拍都能写出**具体的人、事、地方或因果关系**（而不是"某件事在变化"这种空话），低档就判可行。
- 只有当大意拍本身是空话、或几条大意拍讲的是同一件事（无法撑满段数）时，才判不可行。

输出 JSON（只输出 JSON）：
{"info_points":8,
 "levels":{"A1.1":{"ok":true,"why":"20字内"},"A1.2":{...},"A1.3":{...},
           "A2.1":{...},"A2.2":{...},"A2.3":{...},
           "B1.1":{...},"B1.2":{...},"B1.3":{...},
           "B2+.1":{...},"B2+.2":{...},"B2+.3":{...}}}
"""


def judge_viability(material, beats, plain=None):
    txt = "\n".join("  %d. %s" % (b["id"], b["point"]) for b in beats)
    plain_txt = "\n".join("  %s. %s" % (p.get("id"), p.get("point"))
                          for p in (plain or [])) or "（未提供）"
    d, dt = call_sf(VIAB_PROMPT % (material[:6000], txt, plain_txt), 3000, temperature=0.1)
    obj = extract_json(d["choices"][0]["message"].get("content") or "")
    lv = (obj or {}).get("levels") or {}
    print("   [1] 区间判定完成，耗时 %.1fs" % dt)
    return obj or {}, dt


def longest_contiguous(levels):
    """取最长连续 true 区间。返回 (lo_key, hi_key, ok_keys, bool_map)"""
    ok = [k for k in ORDER if (levels.get(SPEC[k]["d"]) or {}).get("ok")]
    if not ok:
        return None, None, [], []
    best = cur = [ok[0]]
    for k in ok[1:]:
        if ORDER.index(k) == ORDER.index(cur[-1]) + 1:
            cur.append(k)
        else:
            cur = [k]
        if len(cur) > len(best):
            best = cur
    return best[0], best[-1], best, [k for k in ORDER if k in ok]


# ════════════════════════════════════════════════════════════════════════════
# Step 2 —— 生成一档
# ════════════════════════════════════════════════════════════════════════════
TUNED_CLAUSE = """
【每段预算（本档最关键的一条，必须严格遵守）】
- 段落数**严格固定 {n} 段**，不允许增减。
- 每一段**必须写到 {plo}–{phi} 词**（每段硬指标）。
- 每一段**最多 {smax} 句**，全篇句数不超过 {smax_total} 句。
- **不要靠增加段落、也不要靠把单句写超长来凑字数**——靠把每一段的内容展开得更充分。
"""


def gen_prompt(level_key, beats_used, material, plain=False):
    S = SPEC[level_key]
    adv = ADV_FROM[level_key]
    groups = distribute(S["paras"], beats_used)
    lines = []
    for b in beats_used:
        core = "、".join(b.get("anchors_core") or []) or "（本档无强制锚点，讲清意思即可）"
        at = b.get("anchors_adv") or []
        adv_txt = ("\n     · 进阶锚点（%s）：%s" % ("本档必须出现" if adv else "本档不要求，出现不算错",
                                                "、".join(at))) if at else ""
        lines.append("  %s. %s\n     · 核心锚点（本档必须出现）：%s%s"
                     % (b["id"], b["point"], core, adv_txt))
    map_txt = "\n".join("  第 %d 段 → 覆盖 %s %s" % (i + 1, "大意拍" if plain else "节拍", g)
                        for i, g in enumerate(groups))
    kind = "大意拍（语义骨架，不含数字与专名）" if plain else "内容节拍"
    extra = ""
    if plain:
        extra = ("\n- 🚫 本档**不要求也不允许**出现具体数字、年份、百分比、温度、时长；"
                 "不要求出现机构名与人名。低档只用简单的话把意思讲清楚，"
                 "这些细节留到更高档位再写。如果为了凑字数硬塞进去，反而破坏本档语言难度。")
    return """你是英语分级阅读作者。基于给定的「%s」，生成 %s 这一档的**一篇**文章。

【本档硬性规格】
- 正文段落数：**%d 段**（必须正好 %d 段）
- 正文字数：**%d–%d 词**（硬区间：低于下限、超过上限都判不合格）
- 平均句长：**%d–%d 词/句**（按全篇平均）
- 词汇层级：%s
- 语法范围：%s
- 主题半径：%s

【%s（共 %d 条，**一条都不能少**）】
%s

【覆盖要求（最重要）】
1. **%d 条必须全部出现在文章里**，顺序与编号一致。不得因为语言简单就省略——
   %s 只是句子更短、词更简单，**信息总量不能少**。
2. 本档 %d 段与它们的对应关系固定为：
%s
3. 每一段只写它应该覆盖的那几条，**不要跨、不要漏、不要新增素材里没有的内容**。

【锚点要求】
- 核心锚点必须在正文中出现。%s%s%s

【输出格式：严格 JSON，只输出一个 JSON 对象，不要 markdown 代码块、不要解释】
{"paras":["段1","段2"],"beat_map":%s}
%s
【素材原文（供你理解上下文，但文章要重写，不要照抄句子）】
%s
""" % (kind, S["d"], S["paras"], S["paras"], S["wc"][0], S["wc"][1],
       S["msl"][0], S["msl"][1], S["vocab"], S["grammar"], S["topic"],
       kind, len(beats_used), "\n".join(lines),
       len(beats_used), S["d"], S["paras"], map_txt,
       ("进阶锚点：" + ("本档必须全部出现。" if adv else "本档不要求出现。")) if not plain else "低档不要求进阶锚点。",
       "",
       extra,
       json.dumps(groups, ensure_ascii=False),
       TUNED_CLAUSE.format(n=S["paras"], plo=round(S["wc"][0] / S["paras"]),
                           phi=round(S["wc"][1] / S["paras"]),
                           smax=S["smax"], smax_total=S["smax"] * S["paras"]),
       material)


def gen_one(level_key, beats_used, material):
    S = SPEC[level_key]
    plain = level_key in PLAIN_LEVELS
    prompt = gen_prompt(level_key, beats_used, material, plain=plain)
    mt = 2500 if level_key in ("A1_1", "A1_2") else (4000 if S["paras"] <= 5 else 9000)
    d, dt = call_sf(prompt, mt)
    msg = d["choices"][0]
    obj = extract_json(msg["message"].get("content") or "")
    u = d.get("usage") or {}
    return dict(level=level_key, plain=plain, elapsed=dt, usage=u,
                finish=msg.get("finish_reason"), parsed=obj,
                raw=msg["message"].get("content") or "", prompt=prompt)


# ════════════════════════════════════════════════════════════════════════════
# Step 3 —— 大意复核（R5）
# ════════════════════════════════════════════════════════════════════════════
CHECK_PROMPT = """你是英语分级阅读的审校员。下面有一篇素材的「标准大意基准」（中文），以及一篇据此写出的分级文章。

任务：判断这篇文章**有没有偏离基准主线**。

判定关注点（逐条核查）：
1. **方向**：有没有把「增加」写成「减少」、「有利」写成「不利」、「上升」写成「下降」？
2. **归属**：有没有把 A 地区/A 机构的事写到 B 地区/B 机构头上？
3. **程度**：有没有明显夸大或缩小（如"小幅上升"写成"急剧飙升"）？
4. **主线完整性**：基准里的主要信息层，文章是否都涉及了？（低档可以大幅简化，但**不能完全不提**）

注意：
- 低档文章用词简单、细节少、做了简化，**这本身不是偏离**，不要因此判失败。
- 低档删掉具体数字（低档不要求出现数字）**不算偏离**。
- 只有"讲错了方向 / 张冠李戴 / 主线上完全缺失某一块"才算偏离。

【标准大意基准】
%s

【待审的分级文章】
%s

输出 JSON（只输出 JSON）：
{"consistent":true,"missing":[],"distorted":[],"why":"40字内"}
"""


def check_one(level_key, baseline, article_text):
    d, dt = call_sf(CHECK_PROMPT % ("\n".join("- " + b for b in baseline), article_text),
                    900, temperature=0.0, model=JUDGE_MODEL)
    obj = extract_json(d["choices"][0]["message"].get("content") or "") or {}
    return obj, dt


# ════════════════════════════════════════════════════════════════════════════
# Step 4 —— 机械校验（本地，可复现）
# ════════════════════════════════════════════════════════════════════════════
def mech(level_key, paras, material, beats):
    S = SPEC[level_key]
    body = "\n".join(str(x) for x in paras)
    toks = word_tokens(body)
    sents = sentences(body)
    wc, ns = len(toks), max(1, len(sentences(body)))
    msl = wc / ns
    core = [a for b in beats for a in (b.get("anchors_core") or [])]
    adv = [a for b in beats for a in (b.get("anchors_adv") or [])]
    low = body.lower()
    hit_core = [a for a in core if a.lower() in low]
    miss_core = [a for a in core if a.lower() not in low]
    hit_adv = [a for a in adv if a.lower() in low]
    extra_nums = sorted(extract_numbers(body) - extract_numbers(material),
                        key=lambda x: (len(x), x))
    per_para = []
    for p in paras:
        pt = word_tokens(str(p))
        ps = sentences(str(p))
        per_para.append((len(pt), len(ps)))
    return dict(
        wc=wc, wc_range=S["wc"],
        wc_ok=S["wc"][0] <= wc <= S["wc"][1],
        wc_dev=(wc - S["wc"][0]) if wc < S["wc"][0] else (wc - S["wc"][1] if wc > S["wc"][1] else 0),
        paras=len(paras), paras_ok=len(paras) == S["paras"],
        sents=ns, msl=round(msl, 1), msl_range=S["msl"],
        msl_ok=S["msl"][0] <= msl <= S["msl"][1],
        core_hit=len(hit_core), core_total=len(core), miss_core=miss_core,
        adv_hit=len(hit_adv), adv_total=len(adv),
        halluc_nums=extra_nums,
        per_para=per_para,
    )


# ════════════════════════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="plan", choices=["plan", "gen", "check", "all"])
    ap.add_argument("--material", default=os.path.join(HERE, "material.txt"))
    ap.add_argument("--beats", default=os.path.join(HERE, "beats.json"))
    ap.add_argument("--work", default=WORK)
    ap.add_argument("--levels", default="", help="覆盖生成档位，如 A1_1,A2_1,B1_1,B2P_3")
    ap.add_argument("--force", action="store_true", help="忽略缓存重跑")
    a = ap.parse_args()

    os.makedirs(a.work, exist_ok=True)
    material = open(a.material, encoding="utf-8").read().strip()
    beats = json.load(open(a.beats, encoding="utf-8"))["beats"]
    tag = os.path.splitext(os.path.basename(a.material))[0]

    # ── plan ──────────────────────────────────────────────────────────────
    if a.stage in ("plan", "all"):
        print("=" * 92)
        print("【Step 0a】把 8 个细节拍合并成 4 个「大意拍」")
        pf = os.path.join(a.work, "%s.plain.json" % tag)
        if os.path.exists(pf) and not a.force:
            plain = json.load(open(pf, encoding="utf-8"))
            print("   （读缓存）")
        else:
            plain, _ = build_plain_beats(beats)
            save_json(pf, plain)

        print("【Step 0b】素材大意基准（跨档对齐的锚）")
        bf = os.path.join(a.work, "%s.baseline.json" % tag)
        if os.path.exists(bf) and not a.force:
            baseline = json.load(open(bf, encoding="utf-8"))
            print("   （读缓存）%d 句" % len(baseline))
        else:
            baseline, _ = build_baseline(material)
            save_json(bf, baseline)

        print("【Step 1】区间判定：12 档逐一判可行性")
        vf = os.path.join(a.work, "%s.viab.json" % tag)
        if os.path.exists(vf) and not a.force:
            viab = json.load(open(vf, encoding="utf-8"))
            print("   （读缓存）")
        else:
            viab, _ = judge_viability(material, beats, plain)
            save_json(vf, viab)

        lv = viab.get("levels") or {}
        print("   info_points = %s" % viab.get("info_points"))
        print("   逐档判定：")
        for k in ORDER:
            o = lv.get(SPEC[k]["d"]) or {}
            print("      %-6s %-5s %s" % (SPEC[k]["d"], "✓" if o.get("ok") else "✗", o.get("why", "")))
        lo, hi, ok_keys, all_ok = longest_contiguous(lv)
        if lo:
            print("   ⇒ 最长连续区间：%s – %s（%d 档）" % (SPEC[lo]["d"], SPEC[hi]["d"], len(ok_keys)))
            if len(ok_keys) != len(all_ok):
                print("   ⚠️ 判 true 的档位不连续！true 集合=%s" %
                      [SPEC[k]["d"] for k in all_ok])
        else:
            print("   ⇒ 无可行档位")
        save_json(os.path.join(a.work, "%s.range.json" % tag),
                  dict(lo=lo, hi=hi, ok_keys=ok_keys, all_ok=all_ok))

    # ── gen ───────────────────────────────────────────────────────────────
    if a.stage in ("gen", "all"):
        rng = load_json(os.path.join(a.work, "%s.range.json" % tag)) or {}
        plain = load_json(os.path.join(a.work, "%s.plain.json" % tag)) or []
        want = [x.strip() for x in a.levels.split(",") if x.strip()] or rng.get("ok_keys") or []
        if not want:
            print("!! 没有可生成的档位（先跑 --stage=plan）"); return
        print("=" * 92)
        print("【Step 2】逐档生成：%s" % ", ".join(SPEC[k]["d"] for k in want))
        for k in want:
            out = os.path.join(a.work, "%s.gen_%s.json" % (tag, k))
            if os.path.exists(out) and not a.force:
                print("   %-6s （已存在，跳过；--force 可重跑）" % SPEC[k]["d"]); continue
            use = ([dict(id=i + 1, point=p.get("point"), anchors_core=[], anchors_adv=[])
                    for i, p in enumerate(plain)] if k in PLAIN_LEVELS else beats)
            r = gen_one(k, use, material)
            save_json(out, r)
            m = mech(k, (r["parsed"] or {}).get("paras") or [], material, use) if r["parsed"] else None
            if m:
                print("   %-6s %4d词(%s) %d段(%s) %d句 句长%.1f(%s) 锚点%d/%d finish=%s %.0fs"
                      % (SPEC[k]["d"], m["wc"], "OK" if m["wc_ok"] else "%+d" % m["wc_dev"],
                         m["paras"], "OK" if m["paras_ok"] else "✗",
                         m["sents"], m["msl"], "OK" if m["msl_ok"] else "✗",
                         m["core_hit"], m["core_total"], r["finish"], r["elapsed"]))
            else:
                print("   %-6s !! JSON 解析失败 finish=%s %.0fs" % (SPEC[k]["d"], r["finish"], r["elapsed"]))

    # ── check ─────────────────────────────────────────────────────────────
    if a.stage in ("check", "all"):
        baseline = load_json(os.path.join(a.work, "%s.baseline.json" % tag)) or []
        plain = load_json(os.path.join(a.work, "%s.plain.json" % tag)) or []
        rng = load_json(os.path.join(a.work, "%s.range.json" % tag)) or {}
        want = [x.strip() for x in a.levels.split(",") if x.strip()] or rng.get("ok_keys") or []
        print("=" * 92)
        print("【Step 3/4】大意复核 + 机械校验")
        rows = []
        for k in want:
            p = os.path.join(a.work, "%s.gen_%s.json" % (tag, k))
            r = load_json(p)
            if not r or not r.get("parsed"):
                print("   %-6s 缺产出" % SPEC[k]["d"]); continue
            paras = r["parsed"].get("paras") or []
            use = ([dict(id=i + 1, point=q.get("point"), anchors_core=[], anchors_adv=[])
                    for i, q in enumerate(plain)] if k in PLAIN_LEVELS else beats)
            body = "\n".join(str(x) for x in paras)
            m = mech(k, paras, material, use)
            c, ct = check_one(k, baseline, body)
            rec = dict(level=SPEC[k]["d"], key=k, mech=m, check=c, check_elapsed=ct)
            rows.append(rec)
            print("   %-6s | %4d词 %s | %d段 %s | %d句 %.1f %s | 锚点%d/%d | 幻觉数字%s | 大意%s %s"
                  % (SPEC[k]["d"], m["wc"], "OK" if m["wc_ok"] else "%+d" % m["wc_dev"],
                     m["paras"], "OK" if m["paras_ok"] else "✗",
                     m["sents"], m["msl"], "OK" if m["msl_ok"] else "✗",
                     m["core_hit"], m["core_total"], m["halluc_nums"] or "无",
                     "一致" if c.get("consistent") else "**偏离**", c.get("why", "")))
            if c.get("missing"):
                print("          缺失：%s" % c["missing"])
            if c.get("distorted"):
                print("          失真：%s" % c["distorted"])
        save_json(os.path.join(a.work, "%s.report.json" % tag), rows)
        n = len(rows)
        if n:
            passed = sum(1 for r in rows if r["check"].get("consistent"))
            in_spec = sum(1 for r in rows if r["mech"]["wc_ok"] and r["mech"]["paras_ok"])
            print("-" * 92)
            print("   合计 %d 档｜规格达标 %d/%d｜大意一致 %d/%d" % (n, in_spec, n, passed, n))


if __name__ == "__main__":
    main()
