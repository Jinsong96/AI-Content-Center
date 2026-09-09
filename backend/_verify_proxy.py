# -*- coding: utf-8 -*-
"""本地验证改造后的 bridge 代理路由：启动服务 -> 打真实请求 -> 关闭服务。

用法：python3 _verify_proxy.py
会从 frontend/config.local.js 读取真实密钥注入环境变量，验证：
  1) /api/proxy-health  环境变量是否被读到
  2) /api/dify/workflows/run (wf=fact)  Dify 代理 + 耗时
  3) /api/sf/chat/completions           SiliconFlow 代理
"""
import io, os, re, sys, json, time, signal, socket, subprocess, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
FE = os.path.join(os.path.dirname(HERE), "frontend")
CFG = os.path.join(FE, "config.local.js")
PORT = 8791  # 避开可能已在运行的 8787
BASE = "http://127.0.0.1:%d" % PORT

def load_keys():
    src = io.open(CFG, encoding="utf-8").read()
    return dict(re.findall(r'(\w+):\s*"([^"]*)"', src))

def wait_port(port, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False

def post(path, payload, timeout=200):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return time.time() - t0, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return time.time() - t0, {"__http_error": e.code,
                                  "detail": e.read().decode("utf-8", "ignore")[:300]}
    except Exception as e:
        return time.time() - t0, {"__error": str(e)}

def main():
    keys = load_keys()
    env = os.environ.copy()
    env["PORT"] = str(PORT)
    for k in ("SF_API_KEY", "DIFY_WF_MAIN", "DIFY_WF_GEN", "DIFY_WF_FACT"):
        env[k] = keys.get(k, "")
    print("注入环境变量：", {k: ("已设置 %d 位" % len(env[k])) if env[k] else "空" for k in
                       ("SF_API_KEY", "DIFY_WF_MAIN", "DIFY_WF_GEN", "DIFY_WF_FACT")})

    proc = subprocess.Popen([sys.executable, "agent_reach_bridge.py"],
                            cwd=HERE, env=env, start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("已启动 bridge (pid=%s, port=%d)" % (proc.pid, PORT))
    if not wait_port(PORT):
        print("❌ 服务未能在 25s 内监听端口"); proc.kill(); return 1

    ok = True
    try:
        # 1) 自检：环境变量是否读到
        el, d = post("/api/proxy-health", {}, timeout=10)
        print("\n[1] /api/proxy-health ->", d.get("configured"))
        if not all(d.get("configured", {}).values()):
            print("    ⚠️ 有环境变量未读到")

        # 2) Dify 事实抽取代理（真实调用，约 10s）
        print("\n[2] /api/dify/workflows/run (wf=fact) —— 真实调用，请稍候…")
        el, d = post("/api/dify/workflows/run", {
            "wf": "fact",
            "inputs": {"material": "Coral bleaching on the Great Barrier Reef has reached "
                                   "record levels as ocean temperatures rise.",
                       "level": "B1", "style": "default"},
            "response_mode": "blocking", "user": "verify",
        })
        st = (d.get("data") or {}).get("status")
        print("    耗时 %.1fs  状态=%s  _proxy_ms=%s" % (el, st, d.get("_proxy_ms")))
        if st != "succeeded":
            print("    ❌ 失败：", json.dumps(d, ensure_ascii=False)[:400]); ok = False
        else:
            print("    ✅ Dify 代理打通（密钥未走前端）")

        # 3) SiliconFlow LLM 代理
        print("\n[3] /api/sf/chat/completions")
        el, d = post("/api/sf/chat/completions", {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "messages": [{"role": "user", "content": "Reply with one English word: coral"}],
            "max_tokens": 20, "temperature": 0.2,
        }, timeout=90)
        txt = ""
        try:
            txt = d["choices"][0]["message"]["content"]
        except Exception:
            pass
        print("    耗时 %.1fs  返回=%r" % (el, txt[:80]))
        if not txt:
            print("    ❌ 失败：", json.dumps(d, ensure_ascii=False)[:300]); ok = False
        else:
            print("    ✅ SiliconFlow 代理打通")
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.kill()
        print("\n已关闭 bridge")

    print("\n" + ("全部通过 ✅" if ok else "存在失败 ❌"))
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
