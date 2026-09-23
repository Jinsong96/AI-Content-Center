#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReadPal · 事实保真度对照：产线（图A+图B/MAIN） vs 轻提示词链路

为什么用规则而不是 AI
--------------------
「某个数字/专名还在不在」有唯一正确答案 —— 代码 100% 准、零成本。
拿 AI 去判这类问题，是花最贵的钱拿最不可靠的结论。
这里只做一件事：把母稿里的**关键事实条目**逐条在各档产出里找一遍，数命中率。

事实清单**人工核定**（不靠粗糙正则），保证结论可复核。

用法：
  python3 tools/fact_fidelity_compare.py
"""
from __future__ import annotations

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ── 母稿关键事实（人工核定，来自 tools/beat_experiment/material.txt）──────────
NUMBERS = {
    "0.5 percent": [r"0\.5\s*(?:percent|%)"],
    "1,000 children": [r"1[,.]?000\s*children", r"per\s*(?:1[,.]?000|thousand)"],
    "8 cases / 1,000": [r"8\s*(?:extra\s+|more\s+)?cases", r"8\s*per"],
    "1 to 2 percent": [r"1\s*(?:to|-|–|—)\s*2\s*(?:percent|%)"],
    "four fewer cases": [r"four\s+fewer"],
    "2 percent (85y)": [r"2\s*(?:percent|%)"],
    "85 years": [r"\b85\b"],
    "2.7°C": [r"2\.7"],
    "25° Celsius": [r"\b25\s*(?:°|degrees?)"],
    "19° C": [r"\b19\s*(?:°|degrees?)"],
    "34° C": [r"\b34\s*(?:°|degrees?)"],
    "1901 to 2014": [r"1901", r"2014"],
    "July 29": [r"July\s*29"],
}

NAMES = {
    "Malaria": [r"[Mm]alaria"],
    "Nature(期刊)": [r"\bNature\b"],
    "Romaric Odoulami": [r"Odoulami"],
    "Univ. of Cape Town": [r"Cape\s+Town"],
    "South Africa": [r"South\s+Africa"],
    "Plasmodium": [r"Plasmodium"],
    "Anopheles": [r"Anopheles"],
    "Nigeria": [r"Nigeria"],
    "DR Congo": [r"(?:Democratic\s+Republic|DR)\s*(?:of\s+the\s+)?Congo"],
    "Ethiopian highlands": [r"Ethiopi"],
    "Cyril Caminade": [r"Caminade"],
    "Abdus Salam ICTP": [r"Abdus\s+Salam", r"Theoretical\s+Physics"],
    "Trieste": [r"Trieste"],
    "sub-Saharan Africa": [r"sub-?Saharan"],
    "West/Central Africa": [r"West\s+and\s+Central", r"western\s+and\s+central"],
}

# 因果方向（说反 = 事实错误）
CAUSAL = {
    "气候变化→传播增加(net +0.5%)": [r"(?:raised|increased|rose|grew|more)[^.]{0,60}0\.5", r"0\.5[^.]{0,60}(?:increase|rise|more)"],
    "埃塞俄比亚高地 +8 例": [r"Ethiopi[^.]{0,200}\b8\b", r"\b8\b[^.]{0,120}(?:highland|Ethiopi)"],
    "西非传播下降 1–2%": [r"West\s+Africa[^.]{0,140}(?:fell|decreas|fewer|lower|down)", r"decreas[^.]{0,140}West\s+Africa"],
    "控制措施 > 气候(影响更大)": [r"control[^.]{0,90}(?:matter|bigger|stronger|more|outweigh|largely)", r"outweigh"],
    "疟疾在向东南迁移": [r"(?:east|south)(?:ern)?\s+(?:and\s+south(?:ern)?\s+)?regions", r"toward\s+the\s+east", r"east[^.]{0,60}(?:toward|shift|move|spread)"],
}


def hits(text: str, pats: list[str]) -> bool:
    return any(re.search(p, text, re.I) for p in pats)


def score(name: str, text: str, table: dict) -> tuple[int, int, list[str]]:
    miss = []
    ok = 0
    for label, pats in table.items():
        if hits(text, pats):
            ok += 1
        else:
            miss.append(label)
    return ok, len(table), miss


def count_words(t: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z'\-]*", t))


def main():
    master = open(os.path.join(ROOT, "tools/beat_experiment/material.txt"), encoding="utf-8").read()

    # 各条链路的 A1- / A2 产出（逐段数组）
    sources = {}

    # 轻提示词链路（本实验第 1/3 轮）
    for rd in (1, 3):
        p = f"/tmp/lite_loop.round{rd}.json"
        if os.path.exists(p):
            d = json.load(open(p, encoding="utf-8"))
            for lv in ("A1", "A2"):
                key = f"轻提示词 第{rd}轮 {('A1-' if lv == 'A1' else lv)}"
                sources[key] = d["paras"][lv]

    # 产线 MAIN 图（端到端，12 段）
    p = "/tmp/prod_main.json"
    if os.path.exists(p):
        m = json.load(open(p, encoding="utf-8"))
        P = json.loads(m["paras_json"])
        for lv in ("A1", "A2"):
            sources[f"产线 MAIN {('A1-' if lv == 'A1' else lv)}"] = P[lv]

    # 产线 图B（授权母稿向下生成，11 段）
    p = "/tmp/prod_licgen3.json"
    if os.path.exists(p):
        m = json.load(open(p, encoding="utf-8"))
        P = json.loads(m["paras_json"])
        for lv in ("A1", "A2"):
            if lv in P:
                sources[f"产线 图B {('A1-' if lv == 'A1' else lv)}"] = P[lv]

    rows = []
    for name, paras in sources.items():
        text = " ".join(paras)
        n_ok, n_tot, n_miss = score(name, text, NUMBERS)
        m_ok, m_tot, m_miss = score(name, text, NAMES)
        c_ok, c_tot, c_miss = score(name, text, CAUSAL)
        rows.append({
            "name": name, "paras": len(paras), "words": count_words(text),
            "num": f"{n_ok}/{n_tot}", "name_ok": f"{m_ok}/{m_tot}", "causal": f"{c_ok}/{c_tot}",
            "total_pct": round((n_ok + m_ok + c_ok) / (n_tot + m_tot + c_tot) * 100),
            "miss": (n_miss + m_miss + c_miss),
        })

    # 母稿基线
    mn, nt, _ = score("master", master, NUMBERS)
    nn, mt, _ = score("master", master, NAMES)
    cn, ct, _ = score("master", master, CAUSAL)

    print("=" * 104)
    print(f"{'产出':<26}{'段':>4}{'词':>6}{'数字':>9}{'专名':>9}{'因果':>9}{'保真度':>9}")
    print("-" * 104)
    print(f"{'母稿（基线）':<26}{8:>4}{count_words(master):>6}"
          f"{f'{mn}/{nt}':>9}{f'{nn}/{mt}':>9}{f'{cn}/{ct}':>9}{'100%':>9}")
    print("-" * 104)
    for r in rows:
        print(f"{r['name']:<26}{r['paras']:>4}{r['words']:>6}{r['num']:>9}{r['name_ok']:>9}{r['causal']:>9}{str(r['total_pct'])+'%':>9}")
    print("=" * 104)
    print()
    for r in rows:
        if r["miss"]:
            print(f"✗ {r['name']}")
            print(f"   丢失：{'、'.join(r['miss'])}")
    print()
    print("规格对照（A1- 目标 150 词 / 硬区间 128–172；A2 目标 240 / 204–276）")


if __name__ == "__main__":
    main()
