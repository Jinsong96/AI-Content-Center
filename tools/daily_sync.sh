#!/usr/bin/env bash
# 每日归档：把当天改动提交到 git（有 remote 时一并推送）
#
# 用法：
#   ./tools/daily_sync.sh                # 用默认提交信息「chore: YYYY-MM-DD 日常更新」
#   ./tools/daily_sync.sh "修复封面生成"   # 自定义说明
#
# 安全：提交前会先检查 index.html 是否为「干净版」（不含密钥）。
#       如果检测到你刚部署完还没 cleanup，会直接拒绝提交。

set -euo pipefail
cd "$(dirname "$0")/.."

PY=$(command -v python3 || echo /Users/bryan/.workbuddy/binaries/python/versions/3.13.12/bin/python3)

echo "== 检查工作区是否安全 =="
if grep -qE '(sk|app)-[A-Za-z0-9]{16,}' frontend/index.html 2>/dev/null; then
  echo "✗ index.html 里检测到密钥，说明还处于「部署注入版」。"
  echo "  请先执行：python3 tools/deploy_demo.py cleanup"
  exit 1
fi
echo "✓ index.html 干净，无密钥"

echo
echo "== 待提交的改动 =="
git add -A
if git diff --cached --quiet; then
  echo "  没有需要提交的改动"
else
  git diff --cached --stat
fi

MSG="${1:-chore: $(date +%Y-%m-%d) 日常更新}"
echo
echo "== 提交 =="
if git diff --cached --quiet; then
  echo "  跳过提交（无改动）"
else
  git commit -q -m "$MSG"
  echo "✓ 已提交：$MSG"
fi

echo
echo "== 推送 =="
if git remote get-url origin >/dev/null 2>&1; then
  git push && echo "✓ 已推送到 origin"
else
  echo "  ⚠ 尚未配置远程仓库，本次只提交到本地。"
  echo "    配置方法：git remote add origin git@github.com:<用户名>/readpal-platform.git"
  echo "              git push -u origin main"
fi

echo
echo "== 完成 =="
git log --oneline -3
