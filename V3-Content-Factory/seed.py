#!/usr/bin/env python3
"""把佳阳老师的示例文章（example_honesty）导入为种子数据。

目的：部署后即使没有配置任何模型密钥，也能看到完整的成品形态 ——
四级文章、15 类质检报告、可编辑、可导出 docx。配了密钥就能真的生成新文章。

幂等：固定 id，重复执行会覆盖而不是新增。
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import quality, render, store  # noqa: E402

SEED_ID = "seed-example-honesty"
SRC = ROOT.parent / "_refs" / "分级卡片工具包" / "articles" / "example_honesty"


def main():
    if not SRC.is_dir():
        print(f"找不到示例源目录：{SRC}", file=sys.stderr)
        return 1

    original = (SRC / "original.txt").read_text(encoding="utf-8")
    raw = (SRC / "cards.json").read_text(encoding="utf-8")
    raw = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", raw.strip())
    data = json.loads(raw)

    store.delete_article(SEED_ID) if (store.DATA / SEED_ID).is_dir() else None
    store.create_article(SEED_ID, original,
                         data.get("title_en", ""), data.get("title_zh", ""))

    article = store.get_article(SEED_ID)
    article["title_en"] = data.get("title_en", "")
    article["title_zh"] = data.get("title_zh", "")
    article["topic_words"] = data.get("topic_words") or []
    article["b2_card_starts"] = data.get("b2_card_starts") or []
    article["levels"] = {}
    for lv in quality.LEVELS:
        node = (data.get("levels") or {}).get(lv) or {}
        article["levels"][lv] = {
            "cards": list(node.get("cards") or []) if lv in quality.GRADED else [],
            "questions": list(node.get("questions") or []),
        }
    article["status"] = "done"
    store.save_article(article)

    report, cards = quality.evaluate(article)
    store.save_report(SEED_ID, "check", report)

    # 把老师原文自带的 report.txt 作为裁判报告占位，前端会显示"尚未裁判"
    store.save_report(SEED_ID, "judge", {
        "findings": [], "conclusion": "示例数据未跑语义裁判，点「L2 重跑裁判」可执行。",
        "p0_count": 0, "p1_count": 0, "not_run": True,
    })

    docx = render.render_article(article, cards)

    meta_path = store.DATA / SEED_ID / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["is_seed"] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已导入种子文章：{SEED_ID}")
    print(f"  标题：{data.get('title_en')} {data.get('title_zh')}")
    print(f"  四级卡片：{' / '.join(str(len(cards[lv])) for lv in quality.LEVELS)}")
    print(f"  质检：{'通过' if report['passed'] else '需修改 %d 处' % report['error_count']}"
          f"（警告 {report['warning_count']} 条）")
    print(f"  导出：{docx.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
