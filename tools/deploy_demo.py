#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
演示部署助手 —— 解决「线上演示需要密钥」与「git 仓库不能有密钥」的矛盾。

思路：
  git 仓库里的 index.html 永远是干净的（不含任何密钥），密钥只存在于
  frontend/config.local.js（已 gitignore）。部署时临时把密钥**内联**进
  index.html 上传，部署完立刻还原。密钥在磁盘上的暴露窗口只有几十秒。

用法：
  python3 tools/deploy_demo.py prepare    # 注入密钥 -> 可以部署了
  python3 tools/deploy_demo.py cleanup    # 部署完调用 -> 还原干净版本
  python3 tools/deploy_demo.py status     # 查看当前是干净版还是注入版

安全设计：
  - prepare 前先把干净版备份到 /tmp/index.clean.html，cleanup 从这里还原，
    不依赖 git，因此不会误伤你尚未提交的改动。
  - 任何情况下都可用 cleanup 强制还原。
"""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "frontend", "index.html")
CONFIG = os.path.join(ROOT, "frontend", "config.local.js")
BACKUP = "/tmp/index.clean.html"
MARKER = "/* __INJECTED_KEYS__ */"


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def load_keys():
    """从 config.local.js 里取出真实密钥"""
    if not os.path.exists(CONFIG):
        sys.exit("✗ 缺少 frontend/config.local.js —— 请先从 config.local.js.example 复制并填入真实值")
    s = read(CONFIG)
    if "window.WB_CONFIG" not in s:
        sys.exit("✗ config.local.js 格式不对，应包含 window.WB_CONFIG = {...}")
    return s


def status():
    s = read(INDEX)
    if MARKER in s:
        print("● 当前：注入版（含密钥）—— 请勿提交到 git，部署完记得 cleanup")
    else:
        print("● 当前：干净版（无密钥）—— 可以安全提交到 git")
    print("  备份存在：", "是" if os.path.exists(BACKUP) else "否")


def prepare():
    s = read(INDEX)
    if MARKER in s:
        print("! 已经是注入版，先 cleanup 再 prepare")
        return 1
    shutil.copy2(INDEX, BACKUP)
    cfg = load_keys()
    # 把 <script src="config.local.js"></script> 替换为内联脚本
    src_tag = '<script src="config.local.js"></script>'
    if src_tag not in s:
        print("✗ index.html 里找不到 config.local.js 引用，结构可能变了")
        return 1
    injected = MARKER + "\n<script>\n" + cfg + "\n</script>"
    s = s.replace(src_tag, injected, 1)
    write(INDEX, s)
    print("✓ 已注入密钥 ->", INDEX)
    print("  现在可以部署了。部署完成后务必执行：python3 tools/deploy_demo.py cleanup")
    return 0


def cleanup():
    if not os.path.exists(BACKUP):
        sys.exit("✗ 找不到备份 " + BACKUP + "，无法还原。请手动检查 index.html 是否含密钥")
    shutil.copy2(BACKUP, INDEX)
    os.remove(BACKUP)
    s = read(INDEX)
    if MARKER in s or re.search(r"sk-[A-Za-z0-9]{16,}", s):
        sys.exit("✗ 还原后仍检测到密钥，请手动处理！")
    print("✓ 已还原干净版，index.html 不含任何密钥，可以安全提交 git")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "prepare":
        sys.exit(prepare())
    elif cmd == "cleanup":
        sys.exit(cleanup())
    elif cmd == "status":
        status()
    else:
        print(__doc__)
