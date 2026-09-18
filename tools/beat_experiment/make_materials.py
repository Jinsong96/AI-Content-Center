#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""派生「素材梯度」实验素材：把 500 词原素材按句末截断成 100/200/300/400/500 词五版。

用途：定出「素材多长 → 能出到哪一档」。截断一律落在句末，避免半句。
"""
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))


def wc(t):
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-\.%]*", t))


def main():
    src = open(os.path.join(HERE, "material.txt"), encoding="utf-8").read().strip()
    lines = [p.strip() for p in src.split("\n") if p.strip()]
    sents = []
    for p in lines:
        sents += [s.strip() for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()]
    print("原素材：%d 句 / %d 词" % (len(sents), wc(src)))

    for target in (100, 200, 300, 400, 500):
        buf = []
        for s in sents:
            if wc(" ".join(buf)) >= target:
                break
            buf.append(s)
        txt = " ".join(buf)
        p = os.path.join(HERE, "mat_v%03d.txt" % target)
        open(p, "w", encoding="utf-8").write(txt + "\n")
        print("  mat_v%03d.txt  → %3d 词 / %2d 句" % (target, wc(txt), len(buf)))


if __name__ == "__main__":
    main()
