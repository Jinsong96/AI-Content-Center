#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机械层判定：规格达标 + 数字/专名溯源（可复现，不依赖模型）。"""
import json, os, re, sys, html

HERE = os.path.dirname(os.path.abspath(__file__))

SPEC = {
    "A1_1": dict(d="A1.1", wc=(60, 90),    msl=(5, 7),   paras=4),
    "A2_1": dict(d="A2.1", wc=(160, 200),  msl=(10, 12), paras=5),
    "B1_1": dict(d="B1.1", wc=(300, 380),  msl=(13, 15), paras=6),
    "B2P_3": dict(d="B2+.3", wc=(900, 1200), msl=(22, 26), paras=8),
}

# 英文数词 → 数字（覆盖本素材用到的量级）
NUMWORD = {
    "zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,
    "ten":10,"eleven":11,"twelve":12,"nineteen":19,"twenty":20,"twenty-five":25,"thirty":30,
    "thirty-four":34,"fifty":50,"sixty":60,"seventy":70,"eighty":80,"ninety":90,
    "hundred":100,"thousand":1000,"million":1000000,"billion":1000000000,
}
STOP_CAP = {"The","A","An","In","It","This","That","These","Those","But","And","Or","So","For",
            "However","Despite","Notwithstanding","Yet","While","When","If","As","Its","Their",
            "There","They","He","She","We","You","I","His","Her","More","Most","Many","Some",
            "In","On","At","By","To","Of","From","With","Also","Now","Today","Still","Even"}


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def word_tokens(text):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-\.%]*", text)


def extract_numbers(text):
    """抽出文章里出现的数字（阿拉伯 + 英文数词），归一化成字符串集合。"""
    out = set()
    for m in re.findall(r"\d+(?:[.,]\d+)?", text):
        out.add(m.rstrip("."))
    low = text.lower()
    for w, v in NUMWORD.items():
        if re.search(r"\b" + re.escape(w) + r"\b", low):
            out.add(str(v))
    return out


def extract_proper_nouns(text):
    """粗抽专名：连续大写词（≥1 个），过滤句首常见词。"""
    cand = set()
    for m in re.findall(r"\b(?:[A-Z][a-z]+)(?:\s+(?:of|the|and)?\s*[A-Z][a-z]+)*\b", text):
        m = m.strip()
        if m in STOP_CAP or len(m) < 3:
            continue
        cand.add(m)
    return cand


def main():
    mat = open(os.path.join(HERE, "material.txt"), encoding="utf-8").read()
    mat_low = mat.lower()
    mat_nums = extract_numbers(mat)
    beats = json.load(open(os.path.join(HERE, "beats.json"), encoding="utf-8"))["beats"]
    all_anchors_core = [a for b in beats for a in b["anchors_core"]]
    all_anchors_adv = [a for b in beats for a in b["anchors_adv"]]

    for lv in ("A1_1", "B2P_3"):
        p = os.path.join(HERE, "out_%s.json" % lv)
        if not os.path.exists(p):
            print("!! 缺少 %s，跳过" % p); continue
        d = json.load(open(p, encoding="utf-8"))
        obj = d.get("parsed") or {}
        paras = obj.get("paras") or []
        S = SPEC[lv]
        body = "\n".join(str(x) for x in paras)
        toks = word_tokens(body)
        sents = sentences(body)
        wc = len(toks); ns = max(1, len(sents)); msl = wc / ns

        print("=" * 96)
        print("【%s】耗时 %.1fs  completion_tokens=%s" % (S["d"], d["elapsed"], (d.get("usage") or {}).get("completion_tokens")))
        print("-" * 96)
        lo, hi = S["wc"]
        dev = "OK" if lo <= wc <= hi else ("%+d" % (wc - lo) if wc < lo else "%+d" % (wc - hi))
        slo, shi = S["msl"]
        sdev = "OK" if slo <= msl <= shi else ("%+.1f" % (msl - slo) if msl < slo else "%+.1f" % (msl - shi))
        print("  规格达标  | 词数 %d / %d-%d (%s) | 段数 %d / %d %s | 句数 %d | 平均句长 %.1f / %d-%d (%s)"
              % (wc, lo, hi, dev, len(paras), S["paras"], "OK" if len(paras) == S["paras"] else "<<<不符",
                 ns, msl, slo, shi, sdev))

        # 锚点命中（机械）
        arts_nums = extract_numbers(body)
        arts_pn = extract_proper_nouns(body)
        arts_blob = body.lower()
        hit_core = [a for a in all_anchors_core if a.lower() in arts_blob]
        miss_core = [a for a in all_anchors_core if a.lower() not in arts_blob]
        hit_adv = [a for a in all_anchors_adv if a.lower() in arts_blob]
        print("  核心锚点  %d/%d 命中；未命中: %s" % (len(hit_core), len(all_anchors_core), miss_core or "无"))
        print("  进阶锚点  %d/%d 命中 %s" % (len(hit_adv), len(all_anchors_adv), hit_adv or "无"))

        # 数字溯源
        extra_nums = sorted(arts_nums - mat_nums, key=lambda x: (len(x), x))
        print("  文章数字  %s" % (sorted(arts_nums, key=lambda x: (len(x), x))))
        print("  素材外数字（疑幻觉）: %s" % (extra_nums or "无 ✅"))

        # 专名溯源
        outside = []
        for pn in sorted(arts_pn):
            if pn.lower() in mat_low:
                continue
            outside.append(pn)
        print("  文章专名  %d 个；素材中找不到的: %s" % (len(arts_pn), outside or "无 ✅"))
        print()
        print("  正文：")
        for i, x in enumerate(paras, 1):
            print("    P%d: %s" % (i, str(x)[:230]))


if __name__ == "__main__":
    main()
