#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReadPal · 事实保真度对照（Food and mood 母稿）：骨架锁定轻提示词链路 vs 产线（图A+图B）

为什么用规则而不是 AI
--------------------
「某个数字/专名还在不在」有唯一正确答案 —— 代码 100% 准、零成本。
事实清单**人工核定**（逐条列出可接受的等价表达），保证结论可复核。

对照四方（同一篇母稿 tools/beat_experiment/material_food_mood.txt，458 词 / 骨架 15 段）：
  ① 母稿基线
  ② 轻提示词 + 骨架锁定（第 1 轮）
  ③ 轻提示词 + 骨架锁定（第 2 轮，收敛轮）
  ④ 产线 图A + 图B（同骨架，105.5s）

用法：
  python3 tools/fact_fidelity_foodmood.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ── 母稿关键事实（人工核定，来自 tools/beat_experiment/material_food_mood.txt）──
# 规则从宽：每条列出所有可接受的等价表达（含低档的近义替代），
# 目的是「在宽松判据下产线仍然丢」—— 结论才硬。
NUMBERS = {
    "39 trillion(体内微生物数)": [r"39\s*trillion", r"thirty-?nine\s+trillion"],
}

NAMES = {
    "gut bacteria(主题词)": [r"gut\s+bacteria", r"bacteria\s+in\s+(?:our|the)\s+gut", r"bacteria in our gut"],
    "bacteria(泛指)": [r"\bbacteria\b"],
    "McMaster University": [r"McMaster"],
    "University College Cork": [r"College\s+Cork", r"\bCork\b"],
    "Canada": [r"Canada"],
    "Ireland": [r"Ireland"],
    "Kyushu University": [r"Kyushu"],
    "Michael Mosley(专家)": [r"Mosley"],
    "BBC(来源)": [r"\bBBC\b"],
    "Mediterranean diet": [r"Mediterranean"],
    "miso soup": [r"miso"],
    "yoghurt/yogurt": [r"yogh?urt"],
    "sauerkraut": [r"sauerkraut"],
    "omega 3": [r"omega[\s-]*3", r"omega"],
    "olive oil": [r"olive\s+oil"],
    "diabetes": [r"diabet"],
    "depression(抑郁)": [r"depress", r"feel\s+(?:very\s+)?sad", r"unhappy", r"low\s+mood"],
    "mice(小鼠实验)": [r"\bmice\b", r"\bmouse\b"],
    "anxiety(焦虑)": [r"anxi", r"worried", r"worry", r"afraid"],
}

# 因果/方向（说反或抹掉 = 事实错误）
CAUSAL = {
    "坏食物长期→增重/糖尿病/心理": [r"(?:bad|unhealthy|junk)[^.]{0,90}(?:weight|diabet|depress|sad|health)",
                              r"(?:weight|diabet|depress)[^.]{0,60}(?:bad|unhealthy|junk)"],
    "肠道细菌→影响情绪": [r"bacteri[^.]{0,90}(?:mood|emotion|feel)", r"(?:mood|emotion)[^.]{0,60}bacteri"],
    "好细菌→减轻小鼠焦虑": [r"(?:good\s+)?bacteri[^.]{0,90}(?:reduce|lower|less)[^.]{0,40}(?:anxi|worr|stress|afraid)",
                     r"(?:reduce|lower|less)[^.]{0,50}(?:anxi|worr|stress|afraid)"],
    "地中海饮食→让人开心": [r"Mediterranean[^.]{0,110}(?:cheer|happy|happier|feel\s+good|mood|best)",
                     r"(?:cheer|happy|happier)[^.]{0,80}Mediterranean"],
    "糖/油(应少吃)": [r"sugar[^.]{0,60}(?:bad|less|not\s+good|terrible)", r"(?:less|cut)[^.]{0,40}sugar",
                   r"fatty[^.]{0,40}sugary"],
    "we are what we eat(食物塑造人)": [r"what\s+we\s+eat", r"shape\s+(?:who\s+we\s+are|us)", r"determine[^.]{0,30}(?:who|person)"],
}


def hits(text: str, pats: list[str]) -> bool:
    return any(re.search(p, text, re.I) for p in pats)


# B 档专名（只标来源，`专名分档`图判为可省/可泛化）—— 按 Bryan 规则，丢失不算错
# 用于把「原始 19 项」折算成「必需保真度」
TIER_B = {"McMaster University", "University College Cork", "Kyushu University",
          "Michael Mosley(专家)", "BBC(来源)"}


def score(text: str, table: dict) -> tuple[int, int, list[str]]:
    miss = [k for k, v in table.items() if not hits(text, v)]
    return len(table) - len(miss), len(table), miss


def count_words(t: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z'\-]*", t))


def overband(path: str, level: str) -> str:
    """超纲率（EVP 口径），返回形如 '47.4% (76/160)'"""
    try:
        out = subprocess.run(["python3", os.path.join(ROOT, "backend/evp_vocab_check.py"),
                              f"--file={path}", f"--level={level}"],
                             capture_output=True, text=True, timeout=120).stdout
    except Exception as e:
        return f"err {e}"
    m = re.findall(r"(\d+(?:\.\d+)?)\s*%", out)
    return (m[-1] + "%") if m else "n/a"


def main():
    master = open(os.path.join(ROOT, "tools/beat_experiment/material_food_mood.txt"), encoding="utf-8").read()

    sources: dict[str, list[str]] = {}

    # 轻提示词 + 骨架锁定（多组实验并存，便于看「逐步加约束」的差异）
    for tag, base in (
        ("骨架·无清单", "/tmp/skel_loop"),
        ("骨架+清单(无数字)", "/tmp/skel_keep"),
        ("骨架+清单+数字", "/tmp/skel_keepnum"),
    ):
        # 只取该组的「收敛轮」（存在的最大轮次），三组同口径才可比
        rounds = [rd for rd in (1, 2, 3, 4, 5) if os.path.exists(f"{base}.round{rd}.json")]
        if rounds:
            rd = max(rounds)
            d = json.load(open(f"{base}.round{rd}.json", encoding="utf-8"))
            for lv in ("A1", "A2"):
                sources[f"{tag} 第{rd}轮 {('A1-' if lv == 'A1' else lv)}"] = d["paras"][lv]

    # 产线 图A+图B（同骨架）
    p = "/tmp/prod_food.json"
    if os.path.exists(p):
        o = json.load(open(p, encoding="utf-8"))
        P = json.loads(o["paras_json"])
        for lv in ("A1", "A2"):
            if lv in P:
                sources[f"产线 图A+图B {('A1-' if lv == 'A1' else lv)}"] = P[lv]

    rows = []
    for name, paras in sources.items():
        text = " ".join(paras)
        n_ok, n_tot, n_miss = score(text, NUMBERS)
        m_ok, m_tot, m_miss = score(text, NAMES)
        c_ok, c_tot, c_miss = score(text, CAUSAL)
        p = f"/tmp/fid_{re.sub(r'[^A-Za-z0-9]+', '_', name)}.txt"
        open(p, "w", encoding="utf-8").write(text)
        lv = "A1" if "A1-" in name else "A2"
        # 必需保真度：把 B 档专名（可省）从分母/丢分里剔除 —— 对齐 Bryan 的专名分档规则
        miss_req = [x for x in (n_miss + m_miss + c_miss) if x not in TIER_B]
        tot_req = (n_tot + m_tot + c_tot) - len(TIER_B)
        req_pct = round((tot_req - len(miss_req)) / tot_req * 100)
        rows.append({
            "name": name, "paras": len(paras), "words": count_words(text),
            "num": f"{n_ok}/{n_tot}", "name_ok": f"{m_ok}/{m_tot}", "causal": f"{c_ok}/{c_tot}",
            "total_pct": round((n_ok + m_ok + c_ok) / (n_tot + m_tot + c_tot) * 100),
            "miss": n_miss + m_miss + c_miss,
            "req_pct": req_pct,
            "overband": overband(p, lv),
        })

    mn, nt, _ = score(master, NUMBERS)
    nn, mt, _ = score(master, NAMES)
    cn, ct, _ = score(master, CAUSAL)
    mp = "/tmp/fid_master.txt"
    open(mp, "w", encoding="utf-8").write(master)

    print("=" * 112)
    print("母稿：Food and mood（458 词 / 骨架 15 段）｜事实清单：数字 ×%d、专名实体 ×%d、因果 ×%d"
          % (nt, mt, ct))
    print("=" * 112)
    print(f"{'产出':<27}{'段':>4}{'词':>6}{'数字':>7}{'专名':>8}{'因果':>7}{'原始':>7}{'必需':>7}{'超纲率':>9}")
    print("-" * 112)
    print(f"{'母稿（基线）':<27}{5:>4}{count_words(master):>6}"
          f"{f'{mn}/{nt}':>7}{f'{nn}/{mt}':>8}{f'{cn}/{ct}':>7}{'100%':>7}{'100%':>7}{overband(mp, 'A1'):>9}")
    print("-" * 112)
    for r in rows:
        print(f"{r['name']:<27}{r['paras']:>4}{r['words']:>6}{r['num']:>7}{r['name_ok']:>8}"
              f"{r['causal']:>7}{str(r['total_pct']) + '%':>7}{str(r['req_pct']) + '%':>7}{r['overband']:>9}")
    print("=" * 112)
    print()
    for r in rows:
        if r["miss"]:
            print(f"✗ {r['name']}（丢 {r['miss']} 项）")
            print(f"   丢失：{'、'.join(r['miss'])}")
            print()

    # ── 逐段实体落位（「第 i 段大意对应骨架第 i 段」的确定性证据）────────────────
    # 每条 = 骨架该段的标志性实体；检查它在候选里的**段号**是否等于 i。
    #   命中段 == i  → ✓ 对齐
    #   命中段 != i  → ⚠ 串位
    #   完全没命中    → ✗ 丢失
    SEG_ANCHORS = {
        3: ("ice cream / chocolate", [r"ice\s*cream", r"chocolate"]),
        5: ("diabetes", [r"diabet"]),
        6: ("gut bacteria + mood", [r"gut\s+bacteria", r"bacteri[^.]{0,60}mood", r"mood"]),
        7: ("39 trillion", [r"39\s*trillion"]),
        7.1: ("McMaster", [r"McMaster"]),
        7.2: ("College Cork", [r"College\s+Cork", r"\bCork\b"]),
        8: ("Kyushu", [r"Kyushu"]),
        9: ("miso soup", [r"miso"]),
        9.1: ("sauerkraut", [r"sauerkraut"]),
        10: ("Michael Mosley", [r"Mosley"]),
        11: ("BBC", [r"\bBBC\b"]),
        11.1: ("Mediterranean", [r"Mediterranean"]),
        12: ("omega 3", [r"omega[\s-]*3"]),
    }
    print("=" * 112)
    print("逐段实体落位（骨架 15 段；✓=落在对应段  ⚠=串到别的段  ✗=整篇丢失）")
    print("=" * 112)
    names = list(sources.keys())
    hdr = f"{'骨架段 · 标志性实体':<26}" + "".join(f"{n.replace('轻提示词+骨架 ', '轻+骨').replace('产线 图A+图B ', '产线'):>18}" for n in names)
    print(hdr)
    print("-" * 112)
    for k in sorted(SEG_ANCHORS.keys()):
        seg = int(k)
        label, pats = SEG_ANCHORS[k]
        line = f"{seg:>2} · {label:<22}"
        for n in names:
            paras = sources[n]
            at = [i + 1 for i, pp in enumerate(paras) if hits(pp, pats)]
            if not at:
                mark = "✗"
            elif at == [seg]:
                mark = "✓"
            elif seg in at:
                mark = "✓" + str([x for x in at if x != seg])
            else:
                mark = "⚠" + str(at)
            line += f"{mark:>18}"
        print(line)
    print("=" * 112)


if __name__ == "__main__":
    main()
