#!/usr/bin/env python3
"""ReadPal · 头条热搜原文覆盖率探针（线上等价环境）

用途：验证「无 Chrome」环境下今日头条热搜能拿到多少可用正文。
这是**线上等价测试**的关键手法：本地跑时把三条渲染路径全部 stub 掉，
强制走纯 HTTP 的 SSR 路径 —— 与 Railway 容器（没装 Chrome）行为一致。

用法：
    python3 probe_toutiao_fulltext.py [仓库根目录]
    默认仓库根 = 当前目录（在用仓库副本里直接跑即可，无需传参）

判据（2026-09-14 建立）：
    · 头条可用正文（ok+short）应 ≈ 7/10
    · source 里**不应再出现「中文源兜底」**（那是假溯源标志）
    · no_source 应只留给「视频型」事件（本身没有文章正文）

⚠️ 必须带 --disable-sandbox 之外的网络权限运行；沙箱内 Chrome 会被拦但不影响本探针
   （本探针刻意不用 Chrome）。
"""
import collections
import os
import sys

REPO = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
sys.path.insert(0, REPO + "/backend")

import agent_reach_bridge as B  # noqa: E402

# ---- 模拟 Railway 容器：没有 Chrome ----
B._chrome_available = lambda: False
B.render_dom_with_chrome = lambda url, timeout=45: None
B.render_dom_via_cdp = lambda url, timeout=60: None
B.render_article_text = lambda aid, timeout=40: ("", "")

rows = B.fetch_toutiao(limit=12, want_fulltext=True)

print("=" * 78)
print("线上等价环境（无 Chrome）· 今日头条热搜原文覆盖率")
print("=" * 78)
cnt = collections.Counter()
for r in rows:
    cnt[r["fulltext_status"]] += 1
    print("  [%-9s] %5d 字  %-30s %s" % (r["fulltext_status"], r["fulltext_len"],
                                         (r["cn"] or "")[:28], (r["source"] or "")[:22]))
    if r["fulltext_err"]:
        print("               ↳ %s" % r["fulltext_err"][:96])
    if r["fulltext"]:
        print("               「%s」" % r["fulltext"][:70].replace("\n", " "))

n = len(rows)
usable = cnt["ok"] + cnt["short"]
print("\n  合计 %d 条：ok=%d  short=%d  no_source=%d" % (n, cnt["ok"], cnt["short"], cnt["no_source"]))
print("  **可用正文（ok+short）= %d/%d = %.0f%%**" % (usable, n, 100.0 * usable / max(1, n)))

fake = [r for r in rows if "中文源兜底" in (r["source"] or "")]
print("  假溯源（source 含「中文源兜底」）= %d 条  %s" % (len(fake), "✓ 通过" if not fake else "✗ 失败"))

print("\n  落到真正原文地址的条目：")
for r in rows:
    if r["fulltext"]:
        print("    %-32s → %s" % ((r["cn"] or "")[:30], r["url"][:70]))
