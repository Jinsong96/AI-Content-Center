#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量把「多难度混排」的分级阅读 word 转成 ReadPal 后台导入格式，并做逐篇逐字核验。

用法：
  python batch_import_pack.py <源目录> <输出目录> [题目模板.xlsx]

产出：
  <输出目录>/<标题>_<难度>.docx          正文
  <输出目录>/<标题>_<难度>_母稿.docx      母稿正文
  <输出目录>/<标题>_题目.xlsx             题目（每难度一个工作表）
只读源文件，绝不改动。
"""
import glob
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_import_pack import (  # noqa: E402
    W, TEMPLATE_LEVELS, HEADER,
    parse_docx, parse_questions, clean_body, fix_refs, run,
)

DEFAULT_TPL = "/Users/jinsongli/Downloads/ReadPal题目上传模板.xlsx"


PASS = ("逐字一致", "0 条", "0 个", "逐字段一致", "保留")


def read_docx_paras(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    body = ET.fromstring(xml).find(W + "body")
    out = []
    for el in body:
        if el.tag != W + "p":
            continue
        txt = "".join(t.text or "" for t in el.iter(W + "t")).strip()
        if txt:
            out.append(txt)
    return out


def verify(src, outdir, title, levels, order):
    """返回 [(检查项, 结果, 详情)]"""
    checks = []
    # ---- 1. 正文逐字比对 ----
    for lv in order:
        d = levels[lv]
        base = lv.split("#")[0]
        suffix = base + ("_母稿" if d["mother"] else "")
        f = os.path.join(outdir, f"{title}_{suffix}.docx")
        expect = [clean_body(t) for t, _ in d["body"]]
        expect = [e for e in expect if e]
        got = read_docx_paras(f) if os.path.exists(f) else None
        if got is None:
            checks.append((f"{base} 正文", "缺失", f))
        elif got == expect:
            checks.append((f"{base} 正文", "逐字一致", f"{len(got)} 段"))
        else:
            diff = next((i for i, (a, b) in enumerate(zip(got, expect)) if a != b), min(len(got), len(expect)))
            checks.append((f"{base} 正文", "不一致", f"第{diff+1}段: {got[diff:diff+1]} vs {expect[diff:diff+1]}"))
        # 序号残留
        raw = [t for t, _ in d["body"]]
        if any(re.match(r"^\s*[①-⑳㉑-㉚⑴-⒇]", r) for r in raw):
            pass  # 源里有序号是正常的
        if any(re.match(r"^\s*[①-⑳㉑-㉚⑴-⒇]", g) for g in (got or [])):
            checks.append((f"{base} 正文", "序号残留", "仍有 ①②③"))
    # ---- 2. 题目逐字段比对 ----
    x = os.path.join(outdir, f"{title}_题目.xlsx")
    rows_by_lv = {}
    for lv in order:
        qs = parse_questions(levels[lv]["quiz"])
        if qs:
            rows_by_lv[lv.split("#")[0]] = qs
    if rows_by_lv:
        if not os.path.exists(x):
            checks.append(("题目 xlsx", "缺失", x))
            return checks
        import openpyxl
        wb = openpyxl.load_workbook(x)
        if wb.sheetnames != list(rows_by_lv.keys()):
            checks.append(("题目 工作表", "顺序/名称不符", f"{wb.sheetnames} vs {list(rows_by_lv.keys())}"))
        bad = 0
        for lv, rows in rows_by_lv.items():
            out_rows = list(wb[lv].iter_rows(min_row=2, values_only=True)) if lv in wb.sheetnames else []
            if len(out_rows) != len(rows):
                bad += 1
                checks.append((f"{lv} 题数", "不符", f"{len(out_rows)} vs {len(rows)}"))
                continue
            for r, o in zip(rows, out_rows):
                for i, k in enumerate(HEADER):
                    if r.get(k, "") != (o[i] or ""):
                        bad += 1
                        checks.append((f"{lv} 题目", "字段不符", f"{k}: {r.get(k)!r} vs {o[i]!r}"))
        if bad == 0:
            tot = sum(len(v) for v in rows_by_lv.values())
            checks.append(("题目 xlsx", "逐字段一致", f"{len(rows_by_lv)} 表 / {tot} 题"))
    # ---- 3. 引用改写残留检查 ----
    resid = 0
    circled = 0
    malformed = 0
    bare_ref = 0          # ④ 「the ... card(s)」泛指引用残留
    real_card = 0         # 真实词义的 card(s)（银行卡 / 支付卡 / 字卡）——应保留
    bare_samples = []
    if os.path.exists(x):
        import openpyxl
        wb = openpyxl.load_workbook(x)
        for sn in wb.sheetnames:
            for row in wb[sn].iter_rows(min_row=2, values_only=True):
                for c in row:
                    if not c:
                        continue
                    s = str(c)
                    # 只认「带编号」的卡片引用残留：「卡片⑨」「card ⑦」「cards ⑦」
                    # ⚠️ 两处坑（都是实测踩出来的）：
                    #   ① 不能简单用 `"卡" in s`——「闪卡」是正常词义，会假报；
                    #   ② `(?:cards?)` 前必须加 `(?<![A-Za-z])`，否则会匹配到
                    #      `flashcards` 里的 `cards`（中国文化批实测 1 处假报）。
                    if re.search(
                        r"卡片|张卡|卡\s*[①-⑳㉑-㉚]"
                        r"|(?<![A-Za-z])(?:cards?|Cards?)\s*(?:[①-⑳㉑-㉚]|\d{1,2})(?![A-Za-z])",
                        s,
                    ):
                        resid += 1
                    # ④ 泛指引用：「the last card」「the last two cards」「the cards about X」
                    #    应已改成 paragraph(s)；这里残留即漏改。
                    if re.search(
                        r"(?<![A-Za-z])(?:The|the)\s+"
                        r"(?:(?:last|first|second|third|fourth|fifth|final|next|other|"
                        r"remaining|previous|earlier|following|above)\s+)?"
                        r"(?:(?:one|two|three|four|five)\s+)?cards?(?![A-Za-z])",
                        s,
                    ):
                        bare_ref += 1
                        if len(bare_samples) < 3:
                            bare_samples.append(s[:70])
                    # 真实词义计数（证明没误伤）：不带 the 的 card(s)
                    real_card += len(
                        re.findall(r"(?<![A-Za-z])(?:cards?|Cards?)(?![A-Za-z])", s)
                    )
                    # 改写畸形：源「同一张卡片」若替换顺序反了会变成「同一张段」
                    if re.search(r"张段|段片|段卡", s):
                        malformed += 1
                    circled += len(re.findall(r"[①-⑳㉑-㉚]", s))
    checks.append(("「卡片」残留", "0 条" if resid == 0 else f"{resid} 条", ""))
    checks.append(("泛指 card 残留", "0 条" if bare_ref == 0 else f"{bare_ref} 条", " / ".join(bare_samples)))
    checks.append(("改写畸形（张段/段片）", "0 条" if malformed == 0 else f"{malformed} 条", ""))
    checks.append(("圈号残留（应全为「第N段」）", "0 个" if circled == 0 else f"{circled} 个", ""))
    checks.append(("真实词义 card（银行卡/字卡）", "保留", f"{real_card} 处（含改写后的 paragraph 不计）"))
    return checks


def main():
    srcdir = sys.argv[1]
    outdir = sys.argv[2]
    tpl = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_TPL
    files = sorted(
        os.path.join(d, f)
        for d, _, fs in os.walk(srcdir)
        for f in fs
        if f.lower().endswith(".docx") and not f.startswith("~$")
    )
    os.makedirs(outdir, exist_ok=True)
    print(f"源目录：{srcdir}\n共 {len(files)} 篇 → {outdir}\n")
    all_checks, summary = [], []
    for i, src in enumerate(files, 1):
        title, levels, order = parse_docx(src)
        out_title, report, rows = run(src, outdir, tpl)
        ch = verify(src, outdir, out_title, levels, order)
        bad = [c for c in ch if c[1] not in PASS]
        summary.append((i, out_title, order, rows, len(bad)))
        all_checks.append((out_title, ch))
        flag = "✓" if not bad else "✗"
        lv_txt = " ".join(f"{lv}({len(levels[lv]['body'])}段/{len(parse_questions(levels[lv]['quiz']))}题)" for lv in order)
        print(f"{flag} [{i:>2}] {out_title}")
        print(f"        {lv_txt}")
        for c in bad:
            print(f"        ⚠ {c[0]}：{c[1]} {c[2]}")
    print(f"\n{'='*80}\n合计 {len(files)} 篇，异常 {sum(s[4] for s in summary)} 项")
    for t, ch in all_checks:
        for c in ch:
            if c[1] not in PASS:
                print(f"  · {t} → {c[0]}: {c[1]} {c[2]}")


if __name__ == "__main__":
    main()
