#!/bin/bash
# 以「无窗口 headless + 后台」方式启动 Chrome 并开放 CDP 9222 端口。
#
# 用途：桥接层是 setsid 守护进程，在 macOS 下拿不到 GUI 会话，自己拉不起 Chrome；
#       只能借一个开着 CDP 的 Chrome 来渲染头条话题页/文章页取原文。
#       之前用有头 Chrome，每次开标签都会把窗口拉到前台，严重干扰操作。
#       改用 headless 后：无可见窗口、不抢焦点、Dock 也不闪。
#
# 用法：
#   bash start_cdp.sh          # 启动（已在跑则跳过）
#
# 停止：
#   pkill -f "remote-debugging-port=9222"
# 用法：
#   bash start_cdp.sh          # 启动（已在跑则跳过）
#
# 停止：
#   pkill -f "remote-debugging-port=9222"
#
# 注意：真正的启动逻辑在 start_cdp.py（双 fork + setsid 守护进程）。
#       在 WorkBuddy 的 Bash 工具里 nohup 起的进程会随工具调用结束被清理，
#       所以本脚本一律委托给 python 版，避免「显示启动了但其实已死」。
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PYBIN:-/Users/bryan/.workbuddy/binaries/python/versions/3.13.12/bin/python3}"
[ -x "$PY" ] || PY="$(command -v python3)"
exec "$PY" "$HERE/start_cdp.py" "$@"
