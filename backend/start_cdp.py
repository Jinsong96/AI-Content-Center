#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
以「真守护进程」方式启动 headless Chrome 并开放 CDP 9222 端口。

为什么不用 nohup：
    在 WorkBuddy 的 Bash 工具里跑 nohup ... & ，工具调用结束时会清理整个进程组，
    Chrome 会被一起杀掉。必须两次 fork + setsid 脱离会话与进程组，才能真正常驻。

    在 macOS 系统终端（Terminal / iTerm）里手动跑 nohup 是没问题的，
    但为了「在哪跑都一样」，统一用这个脚本。

为什么需要 CDP：
    桥接层（agent_reach_bridge.py）自己是 setsid 守护进程，在 macOS 下拿不到 GUI 会话，
    自己拉不起 Chrome。只能借一个已开着 CDP 的 Chrome 来渲染头条话题页/文章页取原文。
    没有它 → 今日头条热搜约 88% 条目拿不到正文 → 事实抽取报「0 张事实卡」。

用法：
    python3 start_cdp.py            # 启动（已在跑则跳过）
    python3 start_cdp.py --status   # 只检查状态
    python3 start_cdp.py --restart  # 先杀再起

停止：
    pkill -f "remote-debugging-port=9222"
"""
import os
import sys
import time
import socket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
UD = "/tmp/chrome-hl-cdp"
LOG = "/tmp/chrome-hl-cdp.log"
PORT = 9222


def port_open(port=PORT, timeout=0.6):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def main():
    args = sys.argv[1:]

    if "--status" in args:
        print("🟢 CDP 正在运行：http://127.0.0.1:%d" % PORT if port_open()
              else "🔴 CDP 未运行")
        return 0 if port_open() else 1

    if "--restart" in args:
        os.system('pkill -f "remote-debugging-port=%d" >/dev/null 2>&1' % PORT)
        for _ in range(20):
            if not port_open():
                break
            time.sleep(0.5)
        print("已停止旧实例")

    if port_open():
        print("✅ CDP 已在运行：http://127.0.0.1:%d （无需重复启动）" % PORT)
        return 0

    if not os.path.exists(CHROME):
        print("❌ 找不到 Chrome：%s" % CHROME)
        return 1

    # ---- 双 fork + setsid：脱离会话与进程组，成为真守护进程 ----
    pid = os.fork()
    if pid > 0:
        os.waitpid(pid, 0)
        for _ in range(40):
            if port_open():
                print("✅ Chrome headless 已启动（无窗口 · 不抢焦点）：http://127.0.0.1:%d" % PORT)
                return 0
            time.sleep(0.5)
        print("⚠️ 启动超时，请查看日志：%s" % LOG)
        return 1

    os.setsid()
    if os.fork() > 0:
        os._exit(0)

    try:
        os.makedirs(UD, exist_ok=True)
        logf = open(LOG, "a", buffering=1)
        os.dup2(logf.fileno(), 1)
        os.dup2(logf.fileno(), 2)
    except Exception:
        pass

    try:
        os.execv(CHROME, [
            CHROME,
            "--headless=new",
            "--remote-debugging-port=%d" % PORT,
            "--user-data-dir=%s" % UD,
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
        ])
    except Exception as e:
        sys.stderr.write("execv failed: %r\n" % (e,))
    os._exit(1)


if __name__ == "__main__":
    sys.exit(main())
