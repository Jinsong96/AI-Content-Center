#!/usr/bin/env bash
# ReadPal · 线上生效核验
#
# 用法:
#   bash verify_live.sh                       # 跑默认基线检查
#   bash verify_live.sh "词A" "词B" ...        # 额外断言这些词在线上应为 0 次
#
# 说明：线上 HTML 是 bridge 注入后的版本，比源码多出
#   <script>window.WB_API_BASE="";window.WB_CONFIG={...}</script>
# 这一行属正常现象，不要试图"修掉"（除非在做密钥下发改造）。
set -uo pipefail

SITE="${READPAL_SITE:-https://web-production-2a16e.up.railway.app}"
TMP="$(mktemp -t readpal_live.XXXXXX.html)"

echo "=== 拉取线上首页 ==="
curl -s -o "$TMP" -w "HTTP %{http_code} | %{size_download} bytes\n" "$SITE/"

count() { grep -o "$1" "$TMP" 2>/dev/null | wc -l | tr -d ' '; }

echo
echo "=== 品牌与健康基线 ==="
printf "  %-22s %s 次\n" "ReadPal"                "$(count ReadPal)"
printf "  %-22s %s 次\n" "127.0.0.1:8787(应=1)"   "$(count '127.0.0.1:8787')"
printf "  %-22s %s 次\n" "Read Pal(错写,应=0)"     "$(count 'Read Pal')"

if [ "$#" -gt 0 ]; then
  echo
  echo "=== 自定义断言（期望均为 0 次）==="
  for kw in "$@"; do
    n="$(count "$kw")"
    if [ "$n" = "0" ]; then printf "  ✓ %-20s 0 次\n" "$kw"
    else printf "  ✗ %-20s %s 次（未清理干净）\n" "$kw" "$n"; fi
  done
fi

echo
echo "=== 桥接健康 ==="
curl -s "$SITE/api/proxy-health" | head -c 400
echo

echo
echo "=== 桥接是否已重启（state 会随部署刷新）==="
curl -s -o /dev/null -w "  /api/health HTTP %{http_code}\n" "$SITE/api/health"

rm -f "$TMP"
