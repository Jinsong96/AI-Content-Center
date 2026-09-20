#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描版分级读物 → 逐页 OCR 文本（JSONL，带坐标）。

背景
----
教研认可的范文是 23 册扫描版分级读物：初级 → A2、中级 → B1、高级 → B2（缺高级第 2 册）。
全部**零文本层**，必须 OCR。一册 32 个 PDF 页 = 15 篇，每篇占 2 页：

  · 偶数索引页（0, 2, 4, …）= 英文正文（对开跨页：左页文字 + 右页插图）
  · 奇数索引页             = 中文「语篇概览 + 阅读检测 + 课标主题 + 文本类型」
  · 最后 2 页              = 答案

本脚本只抽**英文正文页**，并保留每行的 x/y 归一化坐标 ——
页面上正文与插图/气泡/页眉混排，清洗阶段需要用坐标区分区域，不能提前丢位置。

用法
----
    python3 calibration/ocr_sources.py                      # 全量 23 册
    python3 calibration/ocr_sources.py --book 初级1          # 单册（测试用）
    python3 calibration/ocr_sources.py --workers 6          # 调并发
    python3 calibration/ocr_sources.py --list               # 只列册子，不跑

依赖
----
    · pymupdf  → 用 /Users/<you>/.workbuddy/binaries/python/envs/default/bin/python 跑
    · macOS swift + Vision；OCR 脚本来自技能 macos-vision-ocr，先拷到 /tmp：
        cp <skill>/scripts/ocr_tsv.swift /tmp/

输出
----
    calibration/raw/<A2|B1|B2>/<册名>_p<页号>.jsonl
    每行: {"x": 0.06, "y": 0.62, "w": 0.41, "h": 0.07, "t": "Cory goes to school ..."}
    x/y/w/h 均为归一化坐标。⚠️ y 是 Vision 原生方向（**0 = 页面底部**，脚本未翻转），
    所以「从上到下」是 y **递减** —— 清洗阶段必须按 y 降序读，否则整篇会读反。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import pymupdf
except ImportError:  # pragma: no cover
    sys.exit("缺少 pymupdf。请用 ~/.workbuddy/binaries/python/envs/default/bin/python 运行")

# 用 ocr_tsv（逐块输出）而不是 ocr_lines（按行合并）：
# 页面是「对开跨页」，ocr_lines 会把左页正文和右页的气泡/插图文字拼成一行，
# 只剩一个 x 坐标，事后无法区分哪段属于正文。逐块输出才能按坐标分区清洗。
OCR_SWIFT = "/tmp/ocr_tsv.swift"
DEFAULT_SRC = "~/Desktop/教研/书籍"
# 目录名 → 等级。按关键词匹配，不写死完整目录名（目录名里有「缺高级第2册」这类说明）。
LEVEL_KEYWORDS = [("初级", "A2"), ("中级", "B1"), ("高级", "B2")]
MAX_PAGE_INDEX = 30  # 第 31/32 页是答案，不抽


def level_of(dirname: str) -> str | None:
    for kw, lv in LEVEL_KEYWORDS:
        if kw in dirname:
            return lv
    return None


def find_books(src_root: pathlib.Path) -> list[tuple[pathlib.Path, str]]:
    """返回 [(pdf 路径, 等级), ...]，按等级与册名排序。"""
    books = []
    for pdf in sorted(src_root.rglob("*.pdf")):
        lv = level_of(pdf.parent.name)
        if lv:
            books.append((pdf, lv))
    books.sort(key=lambda t: (t[1], t[0].stem.strip()))
    return books


def ocr_page(pdf_path: pathlib.Path, page_idx: int, scale: float) -> list[dict]:
    """渲染 + OCR 一个页面，返回按 (y, x) 排序的行。"""
    doc = pymupdf.open(pdf_path)
    try:
        pg = doc[page_idx]
        s = scale / max(pg.rect.width, pg.rect.height)
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        pg.get_pixmap(matrix=pymupdf.Matrix(s, s)).save(tmp)
    finally:
        doc.close()

    try:
        r = subprocess.run(
            ["swift", OCR_SWIFT, tmp],
            capture_output=True, text=True, timeout=180,
        )
    finally:
        os.unlink(tmp)

    rows = r.stdout.splitlines()
    if rows and rows[0].startswith("TEXT"):  # 跳过表头
        rows = rows[1:]
    blocks = []
    for ln in rows:
        parts = ln.split("\t")
        if len(parts) < 5:
            continue
        txt = parts[0].strip()
        if not txt:
            continue
        try:
            minx, miny, w, h = (float(v) for v in parts[1:5])
        except ValueError:
            continue
        blocks.append({
            "x": round(minx, 4), "y": round(miny, 4),
            "w": round(w, 4), "h": round(h, 4), "t": txt,
        })
    blocks.sort(key=lambda d: (d["y"], d["x"]))
    return blocks


def main() -> int:
    ap = argparse.ArgumentParser(description="扫描版分级读物 OCR")
    ap.add_argument("--src", default=DEFAULT_SRC, help=f"PDF 源根目录（默认 {DEFAULT_SRC}）")
    ap.add_argument("--out", default=str(pathlib.Path(__file__).parent / "raw"),
                    help="输出目录（默认 calibration/raw）")
    ap.add_argument("--workers", type=int, default=4, help="并发数（默认 4）")
    ap.add_argument("--scale", type=float, default=1500.0, help="渲染长边像素（默认 1500）")
    ap.add_argument("--book", default=None, help="只跑册名完全等于该值的册子（测试用）")
    ap.add_argument("--list", action="store_true", help="只列册子清单")
    ap.add_argument("--force", action="store_true", help="已存在的输出也重跑")
    args = ap.parse_args()

    if not pathlib.Path(OCR_SWIFT).exists():
        sys.exit(f"缺少 OCR 脚本 {OCR_SWIFT}，先从这里拷：<skill>/macos-vision-ocr/scripts/ocr_lines.swift")

    src_root = pathlib.Path(os.path.expanduser(args.src))
    if not src_root.is_dir():
        sys.exit(f"源目录不存在: {src_root}")

    books = find_books(src_root)
    if args.book:
        books = [b for b in books if b[0].stem.strip() == args.book]
        if not books:
            sys.exit(f"没找到册名 = {args.book} 的 PDF")

    out_root = pathlib.Path(args.out)

    if args.list:
        print(f"共 {len(books)} 册：")
        for pdf, lv in books:
            n = min(MAX_PAGE_INDEX, len(pymupdf.open(pdf)))
            print(f"  {lv}  {pdf.stem.strip():8s}  {n//2:2d} 篇  ({pdf.name})")
        return 0

    # 组装任务：每册取偶数索引页 = 英文正文页
    tasks = []
    for pdf, lv in books:
        name = pdf.stem.strip()
        n_pages = len(pymupdf.open(pdf))
        last = min(MAX_PAGE_INDEX, n_pages)
        for idx in range(0, last, 2):
            dst = out_root / lv / f"{name}_p{idx + 1:02d}.jsonl"
            if dst.exists() and not args.force:
                continue
            tasks.append((pdf, lv, name, idx, dst))

    if not tasks:
        print("没有待处理的页面（全部已存在，加 --force 可重跑）")
        return 0

    print(f"待处理 {len(tasks)} 页 · 并发 {args.workers} · 源 {src_root}")
    done = failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {
            pool.submit(ocr_page, pdf, idx, args.scale): (lv, name, idx, dst)
            for pdf, lv, name, idx, dst in tasks
        }
        for fut in as_completed(futs):
            lv, name, idx, dst = futs[fut]
            try:
                lines = fut.result()
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"  ✗ {lv}/{name} p{idx + 1}: {type(e).__name__}: {e}")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            with dst.open("w", encoding="utf-8") as f:
                for ln in lines:
                    f.write(json.dumps(ln, ensure_ascii=False) + "\n")
            done += 1
            if done % 25 == 0 or done == len(tasks):
                print(f"  进度 {done}/{len(tasks)}")

    print(f"\n完成：成功 {done} / 失败 {failed} / 共 {len(tasks)}")
    print(f"输出：{out_root}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
