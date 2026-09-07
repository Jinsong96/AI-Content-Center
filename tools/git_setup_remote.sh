#!/bin/bash
# ============================================================
# ReadPal —— 一键把本地仓库推送到 GitHub（私有库）
#
# 用法：
#   ./tools/git_setup_remote.sh <你的GitHub用户名> [仓库名]
#   例： ./tools/git_setup_remote.sh bryan
#        ./tools/git_setup_remote.sh bryan readpal-platform
#
# 前置条件：已执行 gh auth login 完成登录
# 脚本是幂等的：重复运行不会重复建库，只会推送新提交
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

USER="${1:-}"
REPO="${2:-readpal-platform}"

if [ -z "$USER" ]; then
  echo "用法: ./tools/git_setup_remote.sh <你的GitHub用户名> [仓库名]"
  echo "例:   ./tools/git_setup_remote.sh bryan"
  exit 1
fi

echo "仓库根目录: $REPO_ROOT"
echo "目标: github.com/$USER/$REPO (私有)"
echo

# ---------- 1. 检查 gh 登录 ----------
echo "[1/6] 检查 GitHub 登录状态..."
if ! gh auth status >/dev/null 2>&1; then
  echo "  ✗ 尚未登录 GitHub"
  echo "  请先执行:  gh auth login"
  echo "  按提示选择 GitHub.com → HTTPS → 浏览器授权"
  exit 1
fi
GH_USER="$(gh api user --jq .login 2>/dev/null || echo "")"
echo "  ✓ 已登录为: $GH_USER"
if [ -n "$GH_USER" ] && [ "$GH_USER" != "$USER" ]; then
  echo "  ⚠ 登录账号($GH_USER)与传入用户名($USER)不一致，以登录账号为准"
  USER="$GH_USER"
fi

# ---------- 2. 安全检查：index.html 不能含密钥 ----------
echo "[2/6] 安全检查：扫描 index.html 是否含明文密钥..."
HITS="$(grep -c -E '(sk|app)-[A-Za-z0-9]{16,}' frontend/index.html || true)"
if [ "${HITS:-0}" != "0" ]; then
  echo "  ✗ index.html 含 $HITS 处密钥，拒绝推送！"
  echo "  请先执行:  python3 tools/deploy_demo.py cleanup"
  echo "  或:        git checkout -- frontend/index.html"
  exit 1
fi
echo "  ✓ 无密钥（0 处）"

# ---------- 3. 检查是否有未提交改动 ----------
echo "[3/6] 检查工作区..."
python3 -c "
import glob,os
[os.remove(f) for f in glob.glob('.git/**/*.lock', recursive=True)]
" 2>/dev/null || true
if [ -n "$(git status --porcelain)" ]; then
  echo "  发现未提交改动:"
  git status --short | head -10
  echo
  echo "  选择: [c] 先提交再推送 / [q] 退出手动处理"
  read -r -p "  请输入 c 或 q: " choice
  case "$choice" in
    c|C)
      read -r -p "  提交说明: " msg
      git add -A
      git commit -q -m "${msg:-chore: 日常更新}"
      echo "  ✓ 已提交"
      ;;
    *)
      echo "  已退出，未推送"
      exit 0
      ;;
  esac
else
  echo "  ✓ 工作区干净"
fi

# ---------- 4. 统一分支名为 main ----------
echo "[4/6] 统一分支名..."
CUR="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CUR" != "main" ]; then
  git branch -M main
  echo "  ✓ $CUR → main"
else
  echo "  ✓ 已是 main"
fi

# ---------- 5. 创建或关联远程仓库 ----------
echo "[5/6] 关联远程仓库..."
if git remote get-url origin >/dev/null 2>&1; then
  echo "  ✓ 已关联: $(git remote get-url origin)"
else
  if gh repo view "$USER/$REPO" >/dev/null 2>&1; then
    echo "  远程库已存在，直接关联"
    git remote add origin "https://github.com/$USER/$REPO.git"
  else
    echo "  创建私有库 github.com/$USER/$REPO ..."
    gh repo create "$REPO" --private --source=. --remote=origin
  fi
  echo "  ✓ 关联完成"
fi

# ---------- 6. 推送 ----------
echo "[6/6] 推送到 GitHub..."
git push -u origin main

echo
echo "============================================"
echo "  推送完成"
echo "  仓库地址: https://github.com/$USER/$REPO"
echo "============================================"
echo
echo "后续操作:"
echo "  每天归档（仅本地提交）: ./tools/daily_sync.sh \"改了什么\""
echo "  同步到 GitHub:          git push"
echo "  邀请后端同事:           网页进入仓库 → Settings → Collaborators"
