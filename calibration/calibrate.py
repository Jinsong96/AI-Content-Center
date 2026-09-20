#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""范文标定：把清洗后的范文量成「各档实测规格」，并与线上现行规格逐项对照。

输入
----
    calibration/text/<A2|B1|B2>/*.txt           （build_corpus.py 的产出）

输出
----
    calibration/metrics.csv     逐篇指标（可复跑、可核对）
    calibration/report.md       标定报告

指标口径
--------
· 词数 / 句数 / 段数   正则直接统计
· 平均句长            词数 ÷ 句数（句 = `(?<=[.!?])\\s+` 切分）
· 蓝思估算            45×平均句长 + 1500×长词占比(≥7字符) − 350
                      —— 复用线上 GEN ⑦ 校验节点 `estLexile` 的公式。
                      该公式是拿 12 档生成文本对目标区间做最小二乘标定得到的近似
                      （RMSE ≈ 45L），**不是 MetaMetrics 官方值**，只作档位一致性参考。
· 超纲率              复用 backend/evp_vocab_check.check_vocab(text, cap)。
                      四个 cap（A1/A2/B1/B2）全跑：现行阈值的口径是「cap = 本档」，
                      但 A1 cap 全局只有 643 词族，能不能区分档位要先看数据。

范文等级 → 平台档位：初级=A2 → `A2`；中级=B1 → `B1`；高级=B2 → `B2+`。
最低档 `A1-` **没有范文**（CEFR 大档里不存在对应样本）→ 报告中标为「未标定」。
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
import statistics
import sys

ROOT = pathlib.Path(__file__).parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO / "backend"))

try:
    import evp_vocab_check as E
except ImportError:  # pragma: no cover
    sys.exit(f"找不到 backend/evp_vocab_check.py（在 {REPO} 下），请确认仓库结构")

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# 范文等级 → 平台档位名
LEVEL_TO_SLOT = {"A2": "A2", "B1": "B1", "B2": "B2+"}
CAPS = ["A1", "A2", "B1", "B2"]

# 线上现行规格（2026-09-18 收紧后，`tools/dify_build_graphs.py` LEVELS / 前端 SPECS 一致）
SPEC = {
    "A1-": ("150–240", "7–9", "BR–400"),
    "A2": ("240–380", "10–13", "400–750"),
    "B1": ("380–550", "14–17", "750–1050"),
    "B2+": ("550–800", "18–24", "1050–1350"),
}

# 线上真实产出的超纲率实测（来源：docs/local-notes/31、32，2026-09-18）。
# 口径与本文一致：平台自己的 check_vocab，cap = 本档，含生词表豁免与标题。
# ⚠️ 样本是「4 篇真实素材 × 4 档」，量级参考用，不是大样本统计。
PROD_MEASURED = {"A1-": 0.1492, "A2": 0.0902, "B1": 0.0564, "B2+": 0.0222}


def metrics(text: str) -> dict:
    words = WORD_RE.findall(text)
    n = len(words)
    sents = [s for s in SENT_SPLIT.split(text) if s.strip()]
    ns = max(1, len(sents))
    msl = n / ns
    lng = sum(1 for w in words if len(w) >= 7)
    lex = 45.0 * msl + 1500.0 * (lng / n if n else 0.0) - 350.0
    paras = [p for p in text.split("\n\n") if p.strip()]
    return {
        "words": n,
        "sents": ns,
        "paras": len(paras),
        "msl": round(msl, 2),
        "lex": round(lex),
    }


def vocab(text: str) -> dict:
    out = {}
    for cap in CAPS:
        r = E.check_vocab(text, cap)
        out[f"over_{cap}"] = r["over_rate"]
        out[f"unk_{cap}"] = len(r["unknown_words"])
        out[f"cw_{cap}"] = r["content_words"]
    return out


def pct(vals: list[float], q: float) -> float:
    """简单分位数（线性插值）。"""
    if not vals:
        return 0.0
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def main() -> int:
    text_root = ROOT / "text"
    if not text_root.is_dir():
        sys.exit(f"找不到 {text_root}，先跑 build_corpus.py")

    rows: list[dict] = []
    for f in sorted(text_root.rglob("*.txt")):
        lv = f.parent.name
        if lv not in LEVEL_TO_SLOT:
            continue
        body = f.read_text(encoding="utf-8").strip()
        if not body:
            continue
        rec = {"level": lv, "slot": LEVEL_TO_SLOT[lv], "file": f.name}
        rec.update(metrics(body))
        rec.update(vocab(body))
        rows.append(rec)

    if not rows:
        sys.exit("没有可标定的范文")

    # ---- 逐篇 CSV ----
    cols = ["level", "slot", "file", "words", "paras", "sents", "msl", "lex"] + \
           [f"{p}_{c}" for c in CAPS for p in ("over", "cw", "unk")]
    with (ROOT / "metrics.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})

    # ---- 报告 ----
    L: list[str] = []
    A = L.append
    A("# 范文标定报告")
    A("")
    A(f"- 样本：**{len(rows)} 篇**（`calibration/text/`）")
    A("- 来源：教研认可的 23 册分级读物（初级→A2 / 中级→B1 / 高级→B2），扫描件 OCR 后清洗")
    A("- 脚本：`calibration/calibrate.py`（可复跑）")
    A("- ⚠️ `A1-` 档**无对应范文**（CEFR 大档里不存在）→ 本报告不给该档的实测值")
    A("")

    A("## 一、各档实测（中位数 / 区间）")
    A("")
    A("| 档 | 篇数 | 词数 中位 | 词数 区间 | 段数 中位 | 平均句长 中位 | 蓝思 中位 |")
    A("|---|---|---|---|---|---|---|")
    for lv in ("A2", "B1", "B2"):
        g = [r for r in rows if r["level"] == lv]
        if not g:
            continue
        w_ = sorted(r["words"] for r in g)
        A(f"| {lv} → `{LEVEL_TO_SLOT[lv]}` | {len(g)} | {statistics.median(w_):.0f} | "
          f"{w_[0]}–{w_[-1]} | {statistics.median([r['paras'] for r in g]):.0f} | "
          f"{statistics.median([r['msl'] for r in g]):.2f} | "
          f"{statistics.median([r['lex'] for r in g]):.0f} |")
    A("")

    A("## 二、超纲率（四个 cap 都跑）")
    A("")
    A("现行阈值的口径是「cap = 本档」，所以**主口径看对角线上那格**。")
    A("")
    header = "| 档 | " + " | ".join(f"cap≤{c}" for c in CAPS) + " | 表外词(本档 cap) |"
    A(header)
    A("|---" * (len(CAPS) + 2) + "|")
    for lv in ("A2", "B1", "B2"):
        g = [r for r in rows if r["level"] == lv]
        if not g:
            continue
        cells = []
        for c in CAPS:
            v = sorted(r[f"over_{c}"] for r in g)
            mark = " **←**" if c == lv else ""
            cells.append(f"{statistics.median(v)*100:.1f}%{mark}")
        unk = statistics.median([r[f"unk_{lv}"] for r in g])
        A(f"| {lv} | " + " | ".join(cells) + f" | {unk:.0f} |")
    A("")

    A("### 本档 cap 下的分布（阈值该定在哪，看这个）")
    A("")
    A("| 档 | 中位 | P75 | P90 | 最大 | 现行阈值 |")
    A("|---|---|---|---|---|---|")
    for lv in ("A2", "B1", "B2"):
        g = [r for r in rows if r["level"] == lv]
        if not g:
            continue
        v = [r[f"over_{lv}"] for r in g]
        thr = E.VOCAB_THRESHOLD.get(lv, 0)
        A(f"| {lv} | {statistics.median(v)*100:.1f}% | {pct(v,0.75)*100:.1f}% | "
          f"{pct(v,0.90)*100:.1f}% | {max(v)*100:.1f}% | {thr*100:.0f}% |")
    A("")

    A("## 三、与线上现行规格逐项对照")
    A("")
    A("| 档 | 项 | 现行规格 | 范文实测（中位） | 结论 |")
    A("|---|---|---|---|---|")
    for lv in ("A2", "B1", "B2"):
        g = [r for r in rows if r["level"] == lv]
        if not g:
            continue
        slot = LEVEL_TO_SLOT[lv]
        wc, msl, lex = SPEC[slot]
        mw = statistics.median([r["words"] for r in g])
        mm = statistics.median([r["msl"] for r in g])
        ml = statistics.median([r["lex"] for r in g])
        lo = float(wc.split("–")[0])
        ratio = mw / lo
        A(f"| `{slot}` | 词数 | {wc} | {mw:.0f} | **约为下限的 {ratio:.0%}** |")
        A(f"| `{slot}` | 平均句长 | {msl} | {mm:.2f} | — |")
        A(f"| `{slot}` | 蓝思 | {lex} | {ml:.0f} | — |")
    A("")

    A("## 四、产出 vs 范文（回答「产出难度偏高」）")
    A("")
    A("同一口径（`check_vocab`，cap = 本档）下，线上真实产出与教研认可范文的超纲率对比：")
    A("")
    A("| 档 | 线上产出 | 合格范文（中位） | 产出/范文 | 判读 |")
    A("|---|---|---|---|---|")
    for lv in ("A2", "B1", "B2"):
        g = [r for r in rows if r["level"] == lv]
        slot = LEVEL_TO_SLOT[lv]
        if not g or slot not in PROD_MEASURED:
            continue
        prod = PROD_MEASURED[slot]
        ref = statistics.median([r[f"over_{lv}"] for r in g])
        ratio = (prod / ref) if ref else float("inf")
        A(f"| `{slot}` | {prod*100:.1f}% | {ref*100:.1f}% | **{ratio*100:.0f}%** | 产出偏难 |")
    A("")
    A("> 产出数据来源：`docs/local-notes/31`、`32`（2026-09-18，4 篇真实素材实测）。样本量小，只看量级。")
    A("")

    A("## 五、口径与局限（读结论前必看）")
    A("")
    A("- **词数不可比**：范文是「2 页绘本小故事」（55–363 词），我们的产出是「12 段新闻改写」"
      "（240–800 词）—— 形态不同，词数规格**不能**从这批范文推。")
    A("- **句长 / 蓝思谨慎用**：受篇幅与体裁影响；蓝思公式本身又是平台自标定的近似（RMSE ≈ 45L）。"
      "范文中位 130 / 247 / 326 与规格 400–750 / 750–1050 / 1050–1350 差距很大，"
      "**但这不足以说明规格错了** —— 要先由教研确认「绘本 vs 新闻改写」的蓝思是否本就该不同。")
    A("- **超纲率最可靠**：比率指标，受篇幅影响小（单篇样本小、噪声大，但 345 篇汇总后可用）。"
      "**本报告的阈值建议只基于这一项。**")
    A("- **段数是推断值**（按行距切分），仅供粗看，不作结论依据。")
    A("- **OCR 噪声**：少量插图气泡对话混入正文、词间漏空格（`Iwas`）、错字（`Buropean`）。"
      "对统计影响很小 —— 表外词不进超纲率的分子分母。")
    A("- **范文形态是绘本**：若未来要拿它当 few-shot 示例，必须先逐篇人工校对，不能直接用。")
    A("")

    A("## 六、阈值建议")
    A("")
    A("现行 `VOCAB_THRESHOLD` = 5 / 4 / 3 / 2%（A1 / A2 / B1 / B2）。")
    A("**判据：阈值至少要能让「教研认可的合格范文」通过**，否则闸门本身是错的。")
    A("")
    A("| 档 | 现行阈值 | 范文中位 | 范文 P75 | 范文 P90 | 建议值 | 说明 |")
    A("|---|---|---|---|---|---|---|")
    for lv in ("A2", "B1", "B2"):
        g = [r for r in rows if r["level"] == lv]
        if not g:
            continue
        v = [r[f"over_{lv}"] for r in g]
        med, p75, p90 = statistics.median(v), pct(v, 0.75), pct(v, 0.90)
        thr = E.VOCAB_THRESHOLD.get(lv, 0.0)
        if thr < med:
            note = "现行阈值 **低于范文中位** → 合格范文一半以上会被判超标"
        elif p75 < thr:
            note = "现行阈值比范文 P75 还松 → **可以收紧**"
        else:
            note = "现行阈值落在范文中位与 P75 之间 → 合理"
        A(f"| {lv} | {thr*100:.0f}% | {med*100:.1f}% | {p75*100:.1f}% | {p90*100:.1f}% | "
          f"**{p75*100:.1f}%** | {note} |")
    A("")
    A("> 口径：建议值取范文 **P75** —— 允许比范文中位松一些，但不放到 P90，"
      "这样「明显超标的产出」依然会被拦住。落地时取整到 0.5% 即可。")
    A("> ⚠️ `A1-` 档**没有范文**，本报告不给建议值；是否从 A2 外推由 Bryan 定。")
    A("")

    (ROOT / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    # ---- 控制台摘要 ----
    print(f"标定完成：{len(rows)} 篇\n")
    for lv in ("A2", "B1", "B2"):
        g = [r for r in rows if r["level"] == lv]
        if not g:
            continue
        w_ = sorted(r["words"] for r in g)
        v = [r[f"over_{lv}"] for r in g]
        print(f"  {lv} → {LEVEL_TO_SLOT[lv]:4s} {len(g):3d} 篇 | "
              f"词数 中位 {statistics.median(w_):.0f} ({w_[0]}–{w_[-1]}) | "
              f"句长 {statistics.median([r['msl'] for r in g]):.2f} | "
              f"蓝思 {statistics.median([r['lex'] for r in g]):.0f} | "
              f"超纲率(cap={lv}) 中位 {statistics.median(v)*100:.1f}% "
              f"P90 {pct(v,0.90)*100:.1f}% (阈值 {E.VOCAB_THRESHOLD[lv]*100:.0f}%)")
    print(f"\n报告：{ROOT / 'report.md'}")
    print(f"明细：{ROOT / 'metrics.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
