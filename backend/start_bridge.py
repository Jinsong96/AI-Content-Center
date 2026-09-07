#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
以守护进程方式启动 agent_reach_bridge.py（端口 8787）。

用两次 fork + setsid 脱离终端与进程组，这样启动它的 shell 退出后服务仍在。
幂等：已在监听则直接退出，不会起第二个。

用法：
    python3 start_bridge.py            # 启动（已在跑则跳过）
    python3 start_bridge.py --status   # 只看状态
    python3 start_bridge.py --stop     # 停掉

停止服务（任意方式）：
    pkill -f agent_reach_bridge.py
"""
import os
import sys
import socket
import signal
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "agent_reach_bridge.py")
LOG = "/tmp/agent_reach_bridge.log"
PORT = 8787
PY = sys.executable


def port_open(port=PORT, host="127.0.0.1"):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.6)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def stop():
    before = port_open()
    subprocess.run(["pkill", "-f", "agent_reach_bridge.py"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        if not port_open():
            print("已停止（端口 %d 已释放）" % PORT)
            return 0
        time.sleep(0.25)
    print("未确认停止；端口 %d 仍%s" % (PORT, "在监听" if port_open() else "空闲"))
    return 1 if before else 0


def main():
    if "--stop" in sys.argv:
        return stop()

    if port_open():
        print("桥接层已在运行：http://127.0.0.1:%d  （日志 %s）" % (PORT, LOG))
        if "--status" in sys.argv:
            return 0
        return 0

    if "--status" in sys.argv:
        print("桥接层未运行")
        return 1

    if not os.path.exists(SCRIPT):
        print("找不到 %s" % SCRIPT)
        return 1

    logf = open(LOG, "a", buffering=1)
    # 第一次 fork：脱离父进程
    if os.fork() > 0:
        os.wait()  # 收掉中间进程，避免僵尸
        # 等端口起来
        for _ in range(40):
            if port_open():
                print("桥接层已启动：http://127.0.0.1:%d  （日志 %s）" % (PORT, LOG))
                return 0
            time.sleep(0.25)
        print("启动超时，请查看日志 %s" % LOG)
        return 1

    # 中间进程：setsid 脱离会话与进程组
    os.setsid()
    if os.fork() > 0:
        os._exit(0)

    # 孙进程：真正干活
    os.chdir(HERE)
    os.dup2(logf.fileno(), sys.stdout.fileno())
    os.dup2(logf.fileno(), sys.stderr.fileno())
    try:
        os.execv(PY, [PY, SCRIPT])
    except Exception as e:
        logf.write("execv failed: %r\n" % (e,))
        logf.flush()
    os._exit(1)


if __name__ == "__main__":
    sys.exit(main())
