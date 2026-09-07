#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""library.json → 飞书「内容库」记录映射。

把生产平台 bridge 暂存的文章（buildBankArticle 结构）映射成飞书多维表格记录，
输出 {"create_records":[...]} JSON 文件，供 lark-cli base +record-batch-create --json @file 使用。

用法：python3 sync_to_feishu.py [输出文件路径]
"""
import json
import sys
import os

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library.json")

THEME_OPTS = ["城市与日常生活", "文化与知识", "旅行与社会", "流行文化", "心理与行为", "科技与未来"]
STATUS_OPTS = ["草稿", "审查中", "已批准", "已暂缓", "已退役", "待推送", "已推送"]
STYLE_MAP = {
    "default": "默认", "hemingway": "海明威", "zhuziqing": "朱自清", "ohenry": "欧·亨利",
    "twain": "马克·吐温", "murakami": "村上春树", "luxun": "鲁迅", "shakespeare": "莎士比亚",
}


def _tag(art, key):
    tags = (art.get("identity") or {}).get("tags") or []
    for t in tags:
        k = t.get("k") or {}
        v = t.get("v") or {}
        if key in (k.get("zh", ""), k.get("en", "")):
            return v.get("zh", "")
    return ""


def _shelf(s):
    if not s:
        return "热点时效"
    if "常绿" in s or "evergreen" in s.lower():
        return "常绿"
    if "时令" in s or "season" in s.lower():
        return "时令"
    return "热点时效"


def _sel(v, opts, default):
    return [v] if v in opts else [default]


def art_to_record(art):
    ts = _tag(art, "主题 / 子主题") or _tag(art, "Theme / Sub-theme")
    theme, sub = "", ""
    if " · " in ts:
        theme, sub = ts.split(" · ", 1)
    else:
        theme = ts
    theme = theme or "文化与知识"
    if theme not in THEME_OPTS:
        theme = "文化与知识"
    style = art.get("style") or "default"
    articles = art.get("articles") or {}
    return {
        "内容ID": art.get("id", ""),
        "标题": art.get("title", ""),
        "主题": [theme],
        "子主题": sub,
        "文章角度": _tag(art, "文章角度") or _tag(art, "Article angle"),
        "格式类型": _tag(art, "格式 / 类型") or _tag(art, "Format / type"),
        "语气": _tag(art, "语气") or _tag(art, "Tone"),
        "保鲜期": [_shelf(_tag(art, "保鲜期") or _tag(art, "Shelf life"))],
        "写作风格": _sel(STYLE_MAP.get(style, style), list(STYLE_MAP.values()), "默认"),
        "CEFR主档": _sel(art.get("level", "B1"), ["A2", "B1", "B2"], "B1"),
        "状态": _sel(art.get("status", "待推送"), STATUS_OPTS, "待推送"),
        "全文A2": articles.get("A2", ""),
        "全文B1": articles.get("B1", ""),
        "全文B2": articles.get("B2", ""),
        "段落JSON": json.dumps(art.get("paras", {}), ensure_ascii=False),
        "题目JSON": json.dumps(art.get("quiz", {}), ensure_ascii=False),
        "音频JSON": json.dumps(art.get("audio", {}), ensure_ascii=False),
        "事实卡": " | ".join(art.get("facts") or []),
        "素材来源": (art.get("material") or {}).get("source", ""),
        "素材链接": (art.get("material") or {}).get("url", ""),
        "审核人": art.get("reviewedBy", ""),
    }


def main():
    with open(LIB, encoding="utf-8") as f:
        arts = json.load(f)
    if not isinstance(arts, list):
        arts = []
    recs = [art_to_record(a) for a in arts if isinstance(a, dict)]
    out = sys.argv[1] if len(sys.argv) > 1 else None
    payload = {"create_records": recs}
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        print("WROTE %d records -> %s" % (len(recs), out))
    else:
        print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
