#!/usr/bin/env bash
# ============================================================
#  AI 内容生产平台 Demo · macOS 一键启动（无需编程基础）
#  用法1：双击本文件（首次如提示"无法打开"，右键 → 打开）
#  用法2：打开终端粘贴： cd ~/Downloads/AI_Content_Platform_Demo && bash 启动Demo.command
# ============================================================
cd "$(cd "$(dirname "$0")" && pwd)" || exit 1
echo "======================================================"
echo "  AI 内容生产平台 Demo · 正在为您启动…"
echo "======================================================"

# ---------- 1) 检查 / 安装 Python3 ----------
if ! command -v python3 >/dev/null 2>&1; then
  echo ""
  echo "未检测到 Python3 → 正在通过「Xcode 命令行工具」自动安装。"
  echo "若屏幕弹出安装窗口，请点击【安装】并耐心等待（约 5–15 分钟，仅首次需要）。"
  xcode-select --install >/dev/null 2>&1 || true
  echo "等待安装完成（每 15 秒自动检查一次，最长 30 分钟）…"
  for _ in $(seq 1 120); do
    command -v python3 >/dev/null 2>&1 && break
    sleep 15
  done
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo ""
  echo "❌ Python3 仍未就绪。请任选其一手动安装："
  echo "   A. 打开 https://www.python.org/downloads/ 下载安装（勾选 Add to PATH）"
  echo "   B. 或运行命令：  brew install python"
  echo "装好后重新双击本文件即可。"
  echo ""
  read -r -n 1 -s -p "按任意键退出…"
  echo ""
  exit 1
fi
echo "✅ Python 已就绪：$(python3 --version 2>&1)"

# ---------- 2) 启动后端桥接层（热点 / 标签 / TTS 音频） ----------
echo "→ 启动后端服务 http://127.0.0.1:8787 …"
python3 backend/start_bridge.py >/dev/null 2>&1 || true
python3 backend/start_bridge.py --status 2>/dev/null || echo "（后端状态查询失败，可忽略）"

# ---------- 3) 启动前端网页并自动打开浏览器 ----------
echo "→ 启动前端页面并打开浏览器 http://localhost:8000 …"
sleep 1
open "http://localhost:8000"
cd "$(cd "$(dirname "$0")" && pwd)" || exit 1
python3 -m http.server 8000 --bind 127.0.0.1 -d frontend
