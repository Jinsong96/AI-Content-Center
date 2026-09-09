#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""以「Railway 模式」在本地启动 bridge：密钥走环境变量（而非 config.local.js），
并让 bridge 一并托管前端单页，前后端同域。用于部署前在本地复现线上行为。

用法：
    python3 start_railway_local.py            # 默认 8793 端口
    python3 start_railway_local.py 8800       # 指定端口
    python3 start_railway_local.py --stop     # 停止

启动后访问 http://127.0.0.1:<端口>/ 即可看到完整平台（与部署到 Railway 后一致）。
"""
import io
import os
import re
import sys
import time
import socket
import signal
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
FE = os.path.join(os.path.dirname(HERE), "frontend")
CFG = os.path.join(FE, "config.local.js")
PIDFILE = os.path.join(HERE, ".railway_local.pid")
LOGFILE = os.path.join(HERE, ".railway_local.log")
DEFAULT_PORT = 8793


def load_keys():
    """从本地 config.local.js 读真实密钥，注入环境变量（仅本地模拟用）。"""
    if not os.path.exists(CFG):
        return {}
    return dict(re.findall(r'(\w+):\s*"([^"]*)"', io.open(CFG, encoding="utf-8").read()))


def port_open(port):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        return True
    except OSError:
        return False


def stop():
    if not os.path.exists(PIDFILE):
        print("没有运行中的实例（未找到 pid 文件）")
        return
    pid = int(io.open(PIDFILE).read().strip())
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        print("已停止 pid=%s" % pid)
    except Exception as e:
        print("停止失败（可能已退出）:", e)
    try:
        os.remove(PIDFILE)
    except OSError:
        pass


def main():
    args = sys.argv[1:]
    if args and args[0] == "--stop":
        return stop()

    port = int(args[0]) if args and args[0].isdigit() else DEFAULT_PORT
    if port_open(port):
        print("端口 %d 已被占用，换一个端口或先 --stop" % port)
        return 1

    keys = load_keys()
    env = os.environ.copy()
    env["PORT"] = str(port)
    for k in ("SF_API_KEY", "DIFY_WF_MAIN", "DIFY_WF_GEN", "DIFY_WF_FACT",
              "DEMO_PASS"):
        env[k] = keys.get(k, "")
    env.setdefault("FRONTEND_HTML", os.path.join(FE, "index.html"))

    log = open(LOGFILE, "w")
    # start_new_session=True -> 脱离当前进程组，避免被父进程退出时一起清理
    proc = subprocess.Popen([sys.executable, "agent_reach_bridge.py"],
                            cwd=HERE, env=env, start_new_session=True,
                            stdout=log, stderr=subprocess.STDOUT)
    io.open(PIDFILE, "w").write(str(proc.pid))

    for _ in range(60):
        if port_open(port):
            break
        time.sleep(0.3)
    else:
        print("启动超时，查看日志：", LOGFILE)
        return 1

    cfg = {k: bool(env.get(k)) for k in ("SF_API_KEY", "DIFY_WF_MAIN", "DIFY_WF_GEN", "DIFY_WF_FACT")}
    print("=" * 54)
    print("Railway 模式已启动")
    print("  访问地址: http://127.0.0.1:%d/" % port)
    print("  pid: %s  （停止：python3 start_railway_local.py --stop）" % proc.pid)
    print("  密钥注入: " + ", ".join("%s=%s" % (k, "已配置" if v else "缺失") for k, v in cfg.items()))
    print("  日志: %s" % LOGFILE)
    print("=" * 54)
    return 0


if __name__ == "__main__":
    sys.exit(main())
