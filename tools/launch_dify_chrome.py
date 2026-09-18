#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReadPal · 启动可被 CDP 接管的 Chrome（专用 profile），供人工登录 Dify 控制台用。

为什么需要它：
  操作 Dify 控制台（拉草稿 / 推图 / 发布）都要复用一个**已人工登录**的页签。
  直接启动必须带 --remote-debugging-port，且必须用**独立的 --user-data-dir**，
  否则会把用户日常那套 Chrome 的会话搅进去（macOS 上 Chrome 单实例，共用 profile 时
  新参数不生效）。

用法：
    python3 tools/launch_dify_chrome.py [port]        # 默认 9224
    # 之后人工在弹出的窗口里登录 cloud.dify.ai，再：
    DIFY_CDP_PORT=<port> node tools/dump_full_draft.mjs <app_id> /tmp/live.json

⚠️ 坑（2026-09-18 实测）：本机常驻着若干 **headless** Chrome 实例（占 9224 / 9231 等端口，
   上面是 localhost:8899 之类别的任务）。若直接复用那些端口，脚本会 attach 到 headless 实例上：
   没有可见窗口、也没有 Dify 登录态，且一直等不到人登录。
   → 本脚本因此先探测端口是否**已被占用**；占用就直接复用（可能是别的任务），
     **启用前请先确认日志里 Browser 版本不是 HeadlessChrome**：
         curl -s http://127.0.0.1:<port>/json/version | grep -i headless
     命中就换一个未被占用的端口（例如 9237）。

退出码：0 = 端口已就绪；1 = 15s 内没起来
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9224
PROFILE = f"/tmp/chrome-dify-{PORT}"
URL = "https://cloud.dify.ai/"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def port_info(port):
    """端口上是否已有调试实例；有则返回 /json/version 的内容。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
            return json.load(r)
    except Exception:
        return None


if __name__ == "__main__":
    v = port_info(PORT)
    if v:
        ua = v.get("User-Agent", "")
        print(f"[warn] 端口 {PORT} 已被占用，直接复用：{v.get('Browser')}")
        if "HeadlessChrome" in ua:
            print("       ⚠️ 这是 headless 实例（无窗口、无登录态）。换一个空闲端口重跑本脚本。")
            sys.exit(1)
        sys.exit(0)

    if os.fork() > 0:
        for _ in range(30):                      # 父进程等端口就绪后再返回
            time.sleep(0.5)
            v = port_info(PORT)
            if v:
                print(f"[ok] Chrome 已就绪 port={PORT} profile={PROFILE}")
                print(f"     {v.get('Browser')}")
                sys.exit(0)
        print(f"[fail] 15s 内端口 {PORT} 未就绪，看 /tmp/chrome-dify-{PORT}.log")
        sys.exit(1)

    os.setsid()                                  # 双 fork + setsid：脱离调用方 shell 常驻
    if os.fork() > 0:
        os._exit(0)

    log = open(f"/tmp/chrome-dify-{PORT}.log", "a")
    subprocess.Popen(
        [
            CHROME,
            f"--remote-debugging-port={PORT}",
            f"--user-data-dir={PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            URL,
        ],
        stdout=log, stderr=log, stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    os._exit(0)
