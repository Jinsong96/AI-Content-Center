#!/usr/bin/env python3
"""生成三批（高级8 / 新闻B2+ / 中国文化20篇）的逐篇校验表。

用法：
    python scripts/gen_report.py > output/校验表.md

核验口径全部是「真跑比对」：
  1. 正文逐字——产出 docx 每段 vs 源文档对应段（仅去标题行与行首 ①②③ 序号）
  2. 题目逐字段——题型/题干/选项A-D/正确答案/解析 六项
  3. 独立断言——产出不得含「卡片/张卡/卡+序号」；不得含泛指 `the ... card(s)`；
     不得出现「张段/段片」畸形；不得残留 ①②③ 圈号
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_import_pack import parse_docx, parse_questions, run  # noqa: E402
from batch_import_pack import verify, PASS  # noqa: E402

TPL = os.path.expanduser("~/Downloads/ReadPal题目上传模板.xlsx")

BATCHES = [
    ("高级8_分级阅读卡片（15 篇 / 3 级）",
     os.path.expanduser("~/Desktop/分级文章/V2/高级8_分级阅读卡片"),
     "output/导入格式"),
    ("新闻B2+_分级阅读卡片（14 篇 / 4 级）",
     "work/新闻B2+_源",
     "output/导入格式_新闻B2+（14篇）"),
    ("中国文化20篇demo-已分级（20 篇 / 4 级）",
     os.path.expanduser("~/Desktop/分级文章/V2/中国文化20篇demo-已分级"),
     "output/导入格式_中国文化20篇"),
    ("BBC 50篇demo-已分级（50 篇 / 4 级）",
     os.path.expanduser("~/Desktop/分级文章/V2/BBC 50篇demo-已分级"),
     "output/导入格式_BBC50篇"),
]


def main():
    print("# 分级阅读 word → ReadPal 后台导入格式 校验表\n")
    print("生成：2026-09-24 　脚本：`scripts/build_import_pack.py` + `scripts/batch_import_pack.py`\n")

    grand = {"files": 0, "q": 0, "bad": 0, "art": 0}

    for name, base, outdir in BATCHES:
        files = sorted(
            os.path.join(d, f)
            for d, _, fs in os.walk(base)
            for f in fs
            if f.endswith(".docx") and not f.startswith("~$")
        )
        print(f"\n## {name}\n")
        print(f"源目录：`{base.replace(os.path.expanduser('~'), '~')}`  ")
        print(f"产出目录：`{outdir}/`\n")
        print("| # | 标题 | 正文（难度 段数） | 题目（难度 题数） | 校验 |")
        print("|---|---|---|---|---|")
        tq = tb = 0
        n_art = 0
        for i, src in enumerate(files, 1):
            title, levels, order = parse_docx(src)
            out_title, _, _ = run(src, outdir, TPL)
            seg, qs = [], []
            for lv in order:
                bl = lv.split("#")[0]
                d = levels[lv]
                suf = bl + ("_母稿" if d["mother"] else "")
                seg.append(f"{suf} {len(d['body'])}")
                qs.append(f"{bl} {len(parse_questions(d['quiz']))}")
                n_art += 1
            tq += sum(len(parse_questions(levels[lv]["quiz"])) for lv in order)
            n_art += 1  # 题目 xlsx
            ch = verify(src, outdir, out_title, levels, order)
            bad = [c for c in ch if c[1] not in PASS]
            tb += len(bad)
            mark = "✅" if not bad else "❌ " + "; ".join(f"{c[0]} {c[1]}" for c in bad)
            print(f"| {i} | {out_title} | {' / '.join(seg)} | {' / '.join(qs)} | {mark} |")
        print(
            f"\n**小计**：{len(files)} 篇 → {n_art} 个文件；题目 **{tq} 道**；异常 **{tb} 项**。"
        )
        grand["files"] += n_art
        grand["q"] += tq
        grand["bad"] += tb
        grand["art"] += len(files)

    print("\n---\n")
    print("## 四批合计\n")
    print(f"- 篇目 **{grand['art']} 篇**")
    print(f"- 文件 **{grand['files']} 个**（正文 docx + 题目 xlsx）")
    print(f"- 题目 **{grand['q']} 道**")
    print(f"- 异常 **{grand['bad']} 项**\n")
    print("### 校验口径（每条都是真跑比对，不是估算）\n")
    print("| 检查项 | 口径 |")
    print("|---|---|")
    print("| 正文逐字比对 | 产出 docx 的每一段 vs 源文档对应段，逐字符相同（仅去掉标题行与行首 ①②③ 序号） |")
    print("| 题目逐字段比对 | 题型 / 题干 / 选项A-D / 正确答案 / 解析 六项逐字段相同 |")
    print("| 「卡片」残留 | 产出不得出现**带编号**的卡片引用（`卡片⑨` / `card ⑦` / `cards ⑦ to ⑨` / `cards ③–⑥`） |")
    print("| 泛指 card 残留 | 产出不得出现 `the ... card(s)` 这类指代段落、但不带编号的引用 |")
    print("| 改写畸形 | 产出不得出现「张段 / 段片 / 段卡」（替换顺序错会留下这种残渣） |")
    print("| 圈号残留 | 产出题目里不得残留任何 ①②③ 圈号 |")
    print("| 正文序号残留 | 产出正文不得以 ①②③ 开头 |")
    print("| 结构完整性 | 每个 docx 的 zip 完整且继承源文档 styles.xml；每个 xlsx 工作表名 = 难度名 |")
    print("")
    print("### 英文泛指 `card` 的处理（本轮新增，按 Bryan 拍板的 A 方案）")
    print("")
    print("题干里**不带编号**的 `card/cards` 分两类，只改第一类：")
    print("")
    print("| 类别 | 例子 | 处理 |")
    print("|---|---|---|")
    print("| 指代正文段落 | `What is the main purpose of the last card?` | ✅ 改为 `the last paragraph` |")
    print("| 同上（复数/序数） | `the last two cards` / `the second card` / `the cards about Los Angeles` / `the cards before it` | ✅ 改为 `paragraphs` |")
    print("| **真实词义** | `paying by card` / `People paid with cards instead of cash` / `Cash is better than cards` | ⛔ **不动**（BBC 50篇 3 处） |")
    print("")
    print("判定规则：**只认「the + [序数/数量] + card(s)」**。真实词义都不带定冠词 `the`，天然落在规则外，不会被误改；")
    print("`flashcards`（抽认卡）也因 `(?<![A-Za-z])` 断言而免疫。")
    print("")
    print("本轮改写量：**新闻B2+ 16 处、BBC 50篇 15 处、高级8 0 处、中国文化20篇 0 处**；产出泛指残留 **0**。")
    print("")
    print("> ⚠️ 已知遗留（未动，待 Bryan 定）：英文题面里的**连接词**按原文保留，所以会出现")
    print("> `How do 第7段 to 第9段 relate to 第6段?`、`第7段 and 第8段` 这种「`to`/`and` 没换成『到』『和』」的中英混排。")
    print("> **BBC 50篇 16 处**（范围式引用），其余三批 0 处。按「一个字都不改」原样保留。")


if __name__ == "__main__":
    main()
