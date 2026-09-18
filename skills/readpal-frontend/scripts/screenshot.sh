#!/usr/bin/env bash
# ReadPal · 无头 Chrome 截图
#
# 用法: bash screenshot.sh <url> <输出png> [宽] [高] [额外Chrome参数...]
#
# ⚠️ 务必传唯一文件名（带时间戳），否则系统会按内容哈希去重，读到旧图。
# ⚠️ 若截图是 "This site can't be reached"，说明本地服务已随 shell 退出被杀 ——
#    本地服务必须用 run_in_background=true 启动。
set -euo pipefail

URL="${1:?用法: screenshot.sh <url> <输出png> [宽] [高]}"
OUT="${2:?缺少输出路径}"
W="${3:-1400}"
H="${4:-900}"
shift $(( $# > 4 ? 4 : $# )) || true

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
[ -x "$CHROME" ] || { echo "找不到 Chrome: $CHROME"; exit 1; }

"$CHROME" --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
  --force-device-scale-factor=2 --window-size="${W},${H}" \
  --virtual-time-budget=8000 \
  --screenshot="$OUT" "$URL" "$@" 2>&1 | grep -i written || true

if [ -s "$OUT" ]; then
  echo "截图完成: $OUT  ($(wc -c < "$OUT" | tr -d ' ') bytes)"
else
  echo "截图失败或为空: $OUT"
  exit 1
fi
