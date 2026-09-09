#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
构建「瘦身部署包」——给没有环境变量配置面板的托管平台用（如 workbuddy 单端口沙箱）。

背景：
  两套部署方式共用同一份 bridge：
    A. Railway  —— 有环境变量面板，密钥配在 Variables 里，源码不含密钥（更安全）
    B. workbuddy 单端口沙箱 —— 没有配置环境变量的入口，密钥只能随源码一起上传
  本脚本服务于 B：把 bridge 运行必需的文件复制到一个独立目录，
  密钥通过 frontend/config.local.js 随包分发（bridge 的 cfg_local_get 会回落读取它）。

安全性：
  config.local.js 不会被 HTTP 静态服务到 —— bridge 的路由是白名单制，
  只暴露 / 与 /audio/，实测 /config.local.js 返回 404。仅服务端读取。
  但密钥仍会随 HTML 注入下发到浏览器（F12 可见），所以要隐藏密钥请用方案 A。

用法：
  python3 tools/build_deploy_bundle.py            # 默认输出到 ../deploy_bundle
  python3 tools/build_deploy_bundle.py /path/to/dst

产物结构：
  deploy_bundle/
    backend/agent_reach_bridge.py    # bridge（零依赖，只标准库）
    backend/library.json             # 内容库
    backend/audio/*.mp3              # 仅 library.json 实际引用的音频
    frontend/index.html              # 干净版（密钥由 bridge 运行时注入）
    frontend/config.local.js         # 密钥兜底来源（不进 git）
    Procfile                         # web: python3 backend/agent_reach_bridge.py
    requirements.txt                 # 空（零依赖）

启动（本地验证）：
  cd deploy_bundle && PORT=8899 python3 backend/agent_reach_bridge.py
  自检: curl localhost:8899/api/proxy-health   # 4 个密钥都应为 true
"""
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build(dst):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(os.path.join(dst, "backend", "audio"))
    os.makedirs(os.path.join(dst, "frontend"))

    def cp(rel, target=None):
        src = os.path.join(ROOT, rel)
        dstp = os.path.join(dst, target or rel)
        if not os.path.exists(src):
            sys.exit("✗ 缺少源文件: %s" % src)
        os.makedirs(os.path.dirname(dstp), exist_ok=True)
        shutil.copy2(src, dstp)

    # 1) bridge
    cp("backend/agent_reach_bridge.py")
    # 2) 内容库
    cp("backend/library.json")
    # 3) 前端：干净版 index.html + 密钥兜底文件
    cp("frontend/index.html")
    if not os.path.exists(os.path.join(ROOT, "frontend/config.local.js")):
        sys.exit("✗ 缺少 frontend/config.local.js —— 先从 config.local.js.example 复制并填真实密钥")
    cp("frontend/config.local.js")
    # 3b) 随仓库分发的三级兜底（bridge 的 _load_cfg_cache 会读它）
    if os.path.exists(os.path.join(ROOT, "backend/keys.fallback.json")):
        cp("backend/keys.fallback.json")

    # 4) 只复制 library.json 实际引用到的音频（全量 audio 目录有 240MB，太大）
    with open(os.path.join(ROOT, "backend/library.json"), encoding="utf-8") as f:
        d = json.load(f)
    items = d if isinstance(d, list) else (d.get("items") or [])
    refs = set()
    for it in items:
        refs.update(re.findall(r"[A-Za-z0-9_\-]+\.mp3", json.dumps(it, ensure_ascii=False)))

    src_audio = os.path.join(ROOT, "backend/audio")
    dst_audio = os.path.join(dst, "backend/audio")
    n = total = missing = 0
    for name in sorted(refs):
        p = os.path.join(src_audio, name)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dst_audio, name))
            total += os.path.getsize(p)
            n += 1
        else:
            missing += 1
            print("  ! 库里引用但文件缺失:", name)

    # 5) 让平台识别为 Python 服务
    with open(os.path.join(dst, "Procfile"), "w") as f:
        f.write("web: python3 backend/agent_reach_bridge.py\n")
    with open(os.path.join(dst, "requirements.txt"), "w") as f:
        f.write("# 零依赖：仅 Python 标准库\n")

    size = sum(os.path.getsize(os.path.join(r, f))
               for r, _, fs in os.walk(dst) for f in fs)
    print("音频: %d 个 (%.1f MB)，缺失 %d 个" % (n, total / 1048576, missing))
    print("部署包: %.1f MB -> %s" % (size / 1048576, dst))
    return dst


if __name__ == "__main__":
    dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(ROOT), "deploy_bundle")
    build(dest)
