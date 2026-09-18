#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""素材梯度 + 短素材实验（对应 docs/15 §9 遗留项 1、3）。

回答两个问题：
  Q1 素材多长，能出到哪一档？         → 逐版本抽取信息点 → 条数 → 规则推出的上界 → 实测校准
  Q2 「信息点条数决定区间」成立吗？    → 用低信息点的短素材跑，看区间上界是否随之下移

与 run_range.py 同源，复用其 SPEC / 生成 / 校验；本脚本只新增「抽取」与「规则推断」两步。
全程直连硅基流动，**不改 Dify 任何图、不推 draft**。

用法：
  P=/Users/jinsongli/.workbuddy/binaries/python/versions/3.13.12/bin/python3
  $P run_gradient.py --stage=extract --material=mat_v100.txt
  $P run_gradient.py --stage=plan    --material=mat_v100.txt
  $P run_gradient.py --stage=gen     --material=mat_v100.txt
  $P run_gradient.py --stage=check   --material=mat_v100.txt
  $P run_gradient.py --stage=all     --material=short_s1.txt
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_range as rr            # noqa: E402  （复用 SPEC / ORDER / 生成 / 校验）

WORK = os.environ.get("RANGE_WORK", "/tmp/rp/gradient")


def load_json(p, default=None):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def save_json(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ════════════════════════════════════════════════════════════════════════════
# Step E —— 抽取「细节节拍」（条数不固定，由素材自身决定）
# ════════════════════════════════════════════════════════════════════════════
EXTRACT_PROMPT = """你是英语分级阅读的内容编辑。下面是一篇真实素材。

任务：把素材拆成若干「内容节拍」。**一个节拍 = 一个可以独立成段的信息点。**

【拆解规则】
1. **数量不固定，由素材自身决定**。只拆素材里真实存在、且彼此不同的信息点。
   - 能拆 8 条就 8 条，只有 4 条就 4 条。**不要为了凑数把同一件事硬拆成两条**，也不要漏掉独立的事实。
   - 判断标准：「这一条能不能单独写成一个段落而不显得空？」能，才算一条。
2. 每条节拍用一句中文说清「谁 / 发生了什么 / 为什么 / 结果是什么」。
3. 每条节拍必须给出**锚点**（英文词，供后续校验用）：
   - `anchors_core`：这一条的骨感词 2–4 个，**是所有难度档都必须出现的词**。
   - `anchors_adv`：更难的细节锚点（数字、年份、机构名、人名、专有名词、学术词），**只有 B1 及以上才要求出现**。
4. 节拍顺序按素材自身的信息顺序排列。
5. **不得引入素材里没有的信息。**

【素材】
%s

输出 JSON（只输出 JSON，不要 markdown 代码块、不要解释）：
{"topic_kind":"20字内说明这篇素材属于哪类题材（如 科研机制/政策/日常生活/人物故事）",
 "abstractness":"high|mid|low（概念抽象度：能否落到看得见的人事物）",
 "beat_count":N,
 "beats":[{"id":1,"point":"…","anchors_core":["…"],"anchors_adv":["…"]}]}
"""


EXTRACT_FINE_ADD = """
【额外要求：拆到最细（本次实验的关键变量）】
- 上面的「不要凑数」指的是**不能把同一件事重复拆成两条**，但**绝不等于少拆**。
- 如果一条里明显包含两个可以**各自独立成段**的小点——例如「历史上的分布地区」与「传播所需的温度阈值」、
  「研究方法」与「样本规模」、「总体结果」与「地区差异」——**必须拆成两条**。
- 目标是：**每一条只讲一件事，且都能单独写成一段而不显得空**。
"""


def extract_beats(material, fine=False):
    prompt = EXTRACT_PROMPT + (EXTRACT_FINE_ADD if fine else "")
    d, dt = rr.call_sf(prompt % material[:8000], 4000, temperature=0.2)
    obj = rr.extract_json(d["choices"][0]["message"].get("content") or "")
    beats = (obj or {}).get("beats") or []
    # 规整 id
    for i, b in enumerate(beats, 1):
        b["id"] = i
        b["anchors_core"] = [str(x) for x in (b.get("anchors_core") or []) if str(x).strip()]
        b["anchors_adv"] = [str(x) for x in (b.get("anchors_adv") or []) if str(x).strip()]
    info = dict(beat_count=len(beats),
                topic_kind=(obj or {}).get("topic_kind"),
                abstractness=(obj or {}).get("abstractness"),
                declared=(obj or {}).get("beat_count"))
    print("   [E] 抽出 %d 条节拍（模型自报 %s）｜题材=%s｜抽象度=%s｜%.0fs"
          % (len(beats), info["declared"], info["topic_kind"], info["abstractness"], dt))
    for b in beats:
        print("        %d. %s" % (b["id"], b["point"][:70]))
    return beats, info, dt


# ════════════════════════════════════════════════════════════════════════════
# Step M —— 把 K 条细节拍合并成 P 条「大意拍」（去数字、去专名）
# ════════════════════════════════════════════════════════════════════════════
MERGE_PROMPT = """下面是一篇真实素材的 %d 个「细节节拍」（每个 = 一个必讲的信息点）。

任务：把它们**合并压缩**成 %d 个「大意拍」，供低难度文章使用。

合并规则（严格遵守）：
1. **必须正好 %d 条**：按顺序把 %d 个节拍尽量均分到 %d 组，相邻的节拍合成一条大意。
   （%d 个节拍 ÷ %d 组 = 每组约 %s 个节拍；保证每条大意都有内容，**不允许出现空组**。）
2. 每条大意只保留「谁 / 发生了什么 / 意味着什么」的**语义骨架**，用一句中文说清。
3. **绝对不得出现任何数字、百分比、年份、温度、机构名、人名、地名。**
4. 不得引入素材里没有的信息，不得改变方向（增加↔减少、有利↔不利）。
5. 语言口语化、具象——低档读者是初学者，抽象概念要落到「看得见的事」上。

【%d 个细节节拍】
%s

输出 JSON（只输出 JSON）：
{"plain":[{"id":1,"point":"…"},…]}
"""


def merge_beats(beats, P):
    K = len(beats)
    if P >= K:
        return [dict(id=i + 1, point=b["point"]) for i, b in enumerate(beats)], 0.0
    txt = "\n".join("  %d. %s" % (b["id"], b["point"]) for b in beats)
    d, dt = rr.call_sf(MERGE_PROMPT % (K, P, P, K, P, K, P,
                                       ("%.1f" % (K / P)), K, txt), 2000, temperature=0.3)
    obj = rr.extract_json(d["choices"][0]["message"].get("content") or "")
    plain = (obj or {}).get("plain") or []
    for i, p in enumerate(plain):          # 强制 P 条、id 连续
        p["id"] = i + 1
    return plain, dt


# ════════════════════════════════════════════════════════════════════════════
# Step R —— 规则推断（「节拍数 = 段数」→ 信息点条数定上界）
# ════════════════════════════════════════════════════════════════════════════
def rule_top(K):
    """K 条信息点最高能撑起哪一档：取「段数 ≤ K」的最高档。"""
    top = None
    for k in rr.ORDER:
        if rr.SPEC[k]["paras"] <= K:
            top = k
    return top


def rule_all(K):
    """全部可行档位（按规则）。"""
    return [k for k in rr.ORDER if rr.SPEC[k]["paras"] <= K]


# ════════════════════════════════════════════════════════════════════════════
# Step V —— LLM 区间判定（与规则对照用；沿用参数化提示词）
# ════════════════════════════════════════════════════════════════════════════
VIAB_PROMPT_G = """你是英语分级阅读的内容规划师。下面给你一篇真实素材，以及从它抽出的 %d 个「细节节拍」（信息点）。

任务：对 12 个子档**逐一判断**——"这篇素材能不能重写成该档位的文章"。

【判定原则】

**上限由「信息点条数」决定**（最重要的一条）：
- 本档要求的正文段数见下方规格表。**若信息点条数 < 本档段数，判 false**——段数撑不满，模型只能自己编。
- 本素材共 **%d 条**信息点。

**下限由「可简化度」决定**：素材越依赖数字、专名、抽象机制，越写不出低档。
- A1.1 只有 60–90 词 / 4 段 / 每段 15–22 词，每段只够讲一件极其具体的小事。
- 判低档时问自己：把数字、专名、抽象机制全部去掉后，剩下的几件「小事」还能构成一篇完整文章吗？如果只剩空话，判 false。

【12 个子档规格】
A1.1｜60–90 词｜4 段
A1.2｜90–120 词｜4 段
A1.3｜120–160 词｜4 段
A2.1｜160–200 词｜5 段
A2.2｜200–250 词｜5 段
A2.3｜250–300 词｜5 段
B1.1｜300–380 词｜6 段
B1.2｜380–450 词｜6 段
B1.3｜450–550 词｜6 段
B2+.1｜550–700 词｜8 段
B2+.2｜700–900 词｜8 段
B2+.3｜900–1200 词｜8 段

【素材】
%s

【%d 个细节节拍】
%s

【合并后的 %d 条「大意拍」】（低档用这个，去数字、去专名、只留语义骨架）
%s

输出 JSON（只输出 JSON）：
{"levels":{"A1.1":{"ok":true,"why":"20字内"},…,"B2+.3":{…}}}
"""


def judge_viability_g(material, beats, plain):
    txt = "\n".join("  %d. %s" % (b["id"], b["point"]) for b in beats)
    ptxt = "\n".join("  %d. %s" % (p.get("id"), p.get("point")) for p in plain) or "（无）"
    d, dt = rr.call_sf(VIAB_PROMPT_G % (len(beats), len(beats), material[:7000],
                                        len(beats), txt, len(plain), ptxt),
                       3000, temperature=0.1)
    obj = rr.extract_json(d["choices"][0]["message"].get("content") or "") or {}
    print("   [V] LLM 区间判定完成 %.0fs" % dt)
    return obj, dt


# ════════════════════════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=["extract", "plan", "gen", "check", "all"])
    ap.add_argument("--material", required=True, help="素材文件名（相对脚本目录）或绝对路径")
    ap.add_argument("--work", default=WORK)
    ap.add_argument("--levels", default="", help="覆盖生成档位；默认=规则上界 + A1.1 探针")
    ap.add_argument("--grain", default="coarse", choices=["coarse", "fine"],
                    help="抽取粒度：coarse=按语段自然拆；fine=拆到最细（每条只讲一件事）")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    mp = a.material if os.path.isabs(a.material) else os.path.join(HERE, a.material)
    material = open(mp, encoding="utf-8").read().strip()
    tag = os.path.splitext(os.path.basename(mp))[0] + ("_fine" if a.grain == "fine" else "")
    os.makedirs(a.work, exist_ok=True)

    # ── extract ───────────────────────────────────────────────────────────
    ef = os.path.join(a.work, "%s.beats.json" % tag)
    if a.stage in ("extract", "plan", "gen", "all") or not os.path.exists(ef):
        if os.path.exists(ef) and not a.force:
            info = load_json(ef)
            beats = info["beats"]
            print("【E】读缓存：%d 条节拍" % len(beats))
        else:
            print("=" * 92)
            print("【E】抽取细节节拍：%s（%d 词）｜粒度=%s"
                  % (tag, len(rr.word_tokens(material)), a.grain))
            beats, info, _ = extract_beats(material, fine=(a.grain == "fine"))
            info["beats"] = beats
            info["material_words"] = len(rr.word_tokens(material))
            info["material_file"] = os.path.basename(mp)
            save_json(ef, info)
    else:
        info = load_json(ef)
        beats = info["beats"]

    K = len(beats)
    top = rule_top(K)
    ok_keys = rule_all(K)
    print("   规则推断：信息点 %d 条 ⇒ 可行档位 %s ⇒ **上界 %s**"
          % (K, [rr.SPEC[k]["d"] for k in ok_keys] or "无",
             rr.SPEC[top]["d"] if top else "不可用"))

    # ── plan ──────────────────────────────────────────────────────────────
    if a.stage in ("plan", "gen", "check", "all"):
        # 大意拍：A1 组需要 4 条、A2 组需要 5 条
        plains = {}
        for P in (4, 5):
            pf = os.path.join(a.work, "%s.plain%d.json" % (tag, P))
            if os.path.exists(pf) and not a.force:
                plains[P] = load_json(pf)
            else:
                if P > K:
                    plains[P] = [dict(id=i + 1, point=b["point"]) for i, b in enumerate(beats)]
                else:
                    pl, _ = merge_beats(beats, P)
                    plains[P] = pl
                save_json(pf, plains[P])
                print("   大意拍 P=%d：" % P +
                      " ｜ ".join(str(p.get("point"))[:34] for p in plains[P]))

        bf = os.path.join(a.work, "%s.baseline.json" % tag)
        if a.stage in ("plan", "all") or not os.path.exists(bf):
            if os.path.exists(bf) and not a.force:
                print("【0b】读缓存 baseline")
            else:
                base, _ = rr.build_baseline(material)
                save_json(bf, base)

        vf = os.path.join(a.work, "%s.viab.json" % tag)
        if a.stage in ("plan", "all") or not os.path.exists(vf):
            if os.path.exists(vf) and not a.force:
                viab = load_json(vf)
            else:
                viab, _ = judge_viability_g(material, beats, plains[4])
                save_json(vf, viab)
        else:
            viab = load_json(vf) or {}
        lv = (viab or {}).get("levels") or {}
        if lv:
            lo, hi, kont, allok = rr.longest_contiguous(lv)
            print("   LLM 判：最长连续区间 %s（true 集合 %s）"
                  % ("%s – %s" % (rr.SPEC[lo]["d"], rr.SPEC[hi]["d"]) if lo else "无",
                     [rr.SPEC[k]["d"] for k in allok]))
        save_json(os.path.join(a.work, "%s.range.json" % tag),
                  dict(beats=K, rule_top=top, rule_ok=ok_keys,
                       llm_lo=(lv and rr.longest_contiguous(lv)[0]),
                       llm_hi=(lv and rr.longest_contiguous(lv)[1])))

    # ── gen ───────────────────────────────────────────────────────────────
    if a.stage in ("gen", "all"):
        if not top:
            print("   ⚠️ 信息点不足 4 条，规则上界为空 —— 本素材不出任何档")
        want = [x.strip() for x in a.levels.split(",") if x.strip()]
        if not want:
            want = ([top] if top else []) + (["A1_1"] if top != "A1_1" else [])
        plains = {P: load_json(os.path.join(a.work, "%s.plain%d.json" % (tag, P)))
                  for P in (4, 5)}
        print("【G】生成：%s" % ", ".join(rr.SPEC[k]["d"] for k in want))
        for k in want:
            out = os.path.join(a.work, "%s.gen_%s.json" % (tag, k))
            if os.path.exists(out) and not a.force:
                print("   %-6s （已存在，跳过）" % rr.SPEC[k]["d"]); continue
            if k in rr.PLAIN_LEVELS:
                use = [dict(id=p["id"], point=p["point"], anchors_core=[], anchors_adv=[])
                       for p in plains[rr.SPEC[k]["paras"]]]
            else:
                use = beats
            r = rr.gen_one(k, use, material)
            save_json(out, r)
            if r["parsed"]:
                m = rr.mech(k, r["parsed"].get("paras") or [], material, use)
                print("   %-6s %4d词(%s) %d段(%s) %d句 句长%.1f(%s) 消费=%s %.0fs"
                      % (rr.SPEC[k]["d"], m["wc"], "OK" if m["wc_ok"] else "%+d" % m["wc_dev"],
                         m["paras"], "OK" if m["paras_ok"] else "✗",
                         m["sents"], m["msl"], "OK" if m["msl_ok"] else "✗",
                         (r["usage"] or {}).get("completion_tokens"), r["elapsed"]))
            else:
                print("   %-6s !! JSON 解析失败 finish=%s" % (rr.SPEC[k]["d"], r["finish"]))

    # ── check ─────────────────────────────────────────────────────────────
    if a.stage in ("check", "all"):
        baseline = load_json(os.path.join(a.work, "%s.baseline.json" % tag)) or []
        plains = {P: load_json(os.path.join(a.work, "%s.plain%d.json" % (tag, P)))
                  for P in (4, 5)} if os.path.exists(os.path.join(a.work, "%s.plain4.json" % tag)) else {}
        print("【C】大意复核 + 机械校验")
        rows = []
        for k in rr.ORDER:
            p = os.path.join(a.work, "%s.gen_%s.json" % (tag, k))
            if not os.path.exists(p):
                continue
            r = load_json(p)
            if not r or not r.get("parsed"):
                continue
            paras = r["parsed"].get("paras") or []
            if k in rr.PLAIN_LEVELS and plains:
                use = [dict(id=q["id"], point=q["point"], anchors_core=[], anchors_adv=[])
                       for q in plains[rr.SPEC[k]["paras"]]]
            else:
                use = beats
            body = "\n".join(str(x) for x in paras)
            m = rr.mech(k, paras, material, use)
            c, _ = rr.check_one(k, baseline, body)
            rows.append(dict(level=rr.SPEC[k]["d"], key=k, mech=m, check=c))
            print("   %-6s | %4d词 %s | %d段 %s | %d句 %.1f %s | 幻觉数字%s | 大意%s %s"
                  % (rr.SPEC[k]["d"], m["wc"], "OK" if m["wc_ok"] else "%+d" % m["wc_dev"],
                     m["paras"], "OK" if m["paras_ok"] else "✗",
                     m["sents"], m["msl"], "OK" if m["msl_ok"] else "✗",
                     m["halluc_nums"] or "无",
                     "一致" if c.get("consistent") else "**偏离**", c.get("why", "")))
        save_json(os.path.join(a.work, "%s.report.json" % tag), rows)


if __name__ == "__main__":
    main()
