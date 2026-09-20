#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 OCR 原始块（JSONL）清洗成「分篇范文」纯文本 + 清单。

输入
----
    calibration/raw/<A2|B1|B2>/<册名>_p<页号>.jsonl      （{x,y,w,h,t} 逐块）

输出
----
    calibration/text/<A2|B1|B2>/<册名>_<篇号>.txt        （干净正文，一段一行）
    calibration/manifest.json                             （篇目清单，供人工核对）

清洗规则（依据 2026-09-20 对页面的实测，见 docs/local-notes/33）
--------------------------------------------------------------
1. 版面是「对开跨页」：左页 x<0.50 是正文，右页 x≈0.55 是正文延续，
   **插图区文字在 x≥0.70**（如 "This piece goes here."）→ 只保留 x<0.70。
2. 丢弃纯数字块 —— 页码（y≈0.32 或页面底部）与篇号图标（y≈0.90）。
3. 丢弃不含 ≥3 字母英文词的块 —— OCR 乱码如 "Aa B6Ca"、"9939"、"込+2+3-"。
4. 阅读顺序：左页正文在前，右页正文在后，各自按 y **降序**
   —— ocr_tsv 的 MINY 是 Vision 原生坐标，归一化后 **0 = 页面底部**（未翻转），
   所以「从上到下」是 y 递减。⚠️ 2026-09-20 踩过：按升序排会把整篇读反。
5. 段落切分：相邻块 y 间距 > 0.04 或跨页时开新段；段内多块用空格拼接。
6. 全角标点转半角 —— OCR 在中文识别模式下会把英文标点识别成 `，！？：`。
7. 修两处高频 OCR 错：`lt` → `It`（大写 I 误识成小写 l）、句末误识的下划线 `_`。

⚠️ 已知未修的 OCR 噪声（影响很小 —— 表外词不进超纲率的分子分母）：
   词间漏空格（`Iwas`）、错字（`afraidof`←afraid of、`Buropean`←European）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

RIGHT_COL_MAX = 0.70   # x ≥ 此值 = 插图区，丢弃
PAGE_SPLIT = 0.50      # x < 此值 = 左页
PARA_GAP = 0.04        # 相邻块 y 间距超过此值 = 新段落

NUM_ONLY = re.compile(r"^[\d\s.\-]+$")
HAS_WORD = re.compile(r"[A-Za-z]{3,}")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")

PUNCT = str.maketrans({
    "，": ",", "。": ".", "！": "!", "？": "?", "：": ":", "；": ";",
    "（": "(", "）": ")", "“": '"', "”": '"', "‘": "'", "’": "'",
    "、": ",", "《": "<", "》": ">", "—": "-", "－": "-", "…": "...",
})


def load_blocks(path: pathlib.Path) -> list[dict]:
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(d, dict) and "t" in d and "x" in d and "y" in d:
            out.append(d)
    return out


def select_and_order(blocks: list[dict]) -> list[dict]:
    """过滤噪声 → 按「左页在前、右页在后，各自 y 升序」排序。"""
    kept = []
    for b in blocks:
        t = str(b["t"]).strip()
        if not t:
            continue
        x = float(b["x"])
        if x >= RIGHT_COL_MAX:          # 插图区
            continue
        if NUM_ONLY.match(t):           # 页码 / 篇号
            continue
        if not HAS_WORD.search(t):      # OCR 乱码
            continue
        kept.append({**b, "x": x, "y": float(b["y"]),
                     "side": "L" if x < PAGE_SPLIT else "R"})
    # ⚠️ ocr_tsv 的 MINY 归一化后 **0 = 页面底部**（Vision 原生坐标系，未翻转）。
    # 页面从上到下的阅读顺序 = y **降序**。2026-09-20 踩过：按升序排会把整篇读反。
    left = sorted((b for b in kept if b["side"] == "L"), key=lambda d: -d["y"])
    right = sorted((b for b in kept if b["side"] == "R"), key=lambda d: -d["y"])
    return left + right


def to_paragraphs(blocks: list[dict]) -> list[str]:
    paras: list[str] = []
    cur: list[str] = []
    last_y = None
    last_side = None
    for b in blocks:
        t = re.sub(r"\s*\|\s*", " ", str(b["t"]))
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        new_para = (
            cur and (
                b["side"] != last_side
                or (last_y is not None and last_y - b["y"] > PARA_GAP)
            )
        )
        if new_para:
            paras.append(" ".join(cur))
            cur = []
        cur.append(t)
        last_y, last_side = b["y"], b["side"]
    if cur:
        paras.append(" ".join(cur))
    return paras


def polish(text: str) -> str:
    text = text.translate(PUNCT)
    text = re.sub(r"\blt\b", "It", text)                    # OCR：大写 I 误识成小写 l（"lt's" → "It's"）
    text = re.sub(r"_\s*$", "", text)                       # OCR：句末标点误识成下划线（"learn_" → "learn"）
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)            # 标点前不留空格
    text = re.sub(r"([,.!?;:])(?=[A-Za-z])", r"\1 ", text)  # 标点后补一空格
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def main() -> int:
    root = pathlib.Path(__file__).parent
    raw_root = root / "raw"
    text_root = root / "text"
    if not raw_root.is_dir():
        sys.exit(f"找不到 {raw_root}，先跑 ocr_sources.py")

    manifest = []
    for raw in sorted(raw_root.rglob("*.jsonl")):
        level = raw.parent.name
        book, _, page_s = raw.stem.rpartition("_p")
        if not page_s.isdigit():
            continue
        piece = (int(page_s) + 1) // 2

        blocks = select_and_order(load_blocks(raw))
        paras = [polish(p) for p in to_paragraphs(blocks)]
        paras = [p for p in paras if p]
        if not paras:
            print(f"  ⚠ {raw.name} 清洗后为空，跳过")
            continue
        body = "\n\n".join(paras)

        (text_root / level).mkdir(parents=True, exist_ok=True)
        dst = text_root / level / f"{book}_{piece:02d}.txt"
        dst.write_text(body + "\n", encoding="utf-8")

        manifest.append({
            "level": level,
            "book": book,
            "piece": piece,
            "file": str(dst.relative_to(root)),
            "words": len(WORD_RE.findall(body)),
            "paras": len(paras),
            "title": paras[0][:60],
        })

    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    # 汇总
    print(f"共 {len(manifest)} 篇 → {text_root}")
    for lv in ("A2", "B1", "B2"):
        ws = sorted(m["words"] for m in manifest if m["level"] == lv)
        if not ws:
            continue
        mid = ws[len(ws) // 2]
        print(f"  {lv}: {len(ws):3d} 篇 | 词数 中位 {mid:3d} | 区间 {ws[0]}–{ws[-1]}")
    print(f"清单：{root / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
