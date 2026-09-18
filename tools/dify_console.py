# -*- coding: utf-8 -*-
"""复用本机 Chrome(Default profile) 的 Dify 控制台登录态，直接调 console API。
不依赖 CDP 调试端口。"""
import hashlib, sqlite3, shutil, subprocess, tempfile, os, sys, json, urllib.request, urllib.parse, time

PROFILE = os.path.expanduser("~/Library/Application Support/Google/Chrome/Default")
BASE = "https://cloud.dify.ai"


def _key():
    pw = subprocess.run(["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage", "-a", "Chrome"],
                        capture_output=True, text=True, check=True).stdout.strip()
    return hashlib.pbkdf2_hmac("sha1", pw.encode(), b"saltysalt", 1003, 16).hex()


def _dec(enc, keyhex, host):
    if enc[:3] != b"v10":
        try:
            return enc.decode()
        except Exception:
            return ""
    p = subprocess.run(["openssl", "enc", "-aes-128-cbc", "-d", "-K", keyhex,
                        "-iv", "20" * 16, "-nopad"],
                       input=enc[3:], capture_output=True)
    raw = p.stdout
    if not raw:
        return ""
    raw = raw[:-raw[-1]] if raw[-1] <= 16 else raw
    if len(raw) >= 32 and raw[:32] == hashlib.sha256(host.encode()).digest():
        raw = raw[32:]
    return raw.decode("utf-8", "replace")


def load_cookies():
    src = os.path.join(PROFILE, "Cookies")
    tmp = tempfile.mktemp()
    shutil.copy(src, tmp)
    con = sqlite3.connect(tmp)
    rows = con.execute("select host_key,name,encrypted_value from cookies where host_key like '%dify%'").fetchall()
    con.close(); os.remove(tmp)
    k = _key()
    out = {}
    for host, name, enc in rows:
        v = _dec(enc, k, host)
        if v:
            out[name] = v
    return out


COOKIES = None


def _cookie_header():
    global COOKIES
    if COOKIES is None:
        COOKIES = load_cookies()
    return "; ".join("%s=%s" % (k, v) for k, v in COOKIES.items())


def refresh():
    global COOKIES
    COOKIES = load_cookies()
    body = json.dumps({"refresh_token": COOKIES.get("__Host-refresh_token", "")}).encode()
    req = urllib.request.Request(BASE + "/console/api/refresh-token", data=body, method="POST")
    req.add_header("Cookie", _cookie_header())
    req.add_header("Content-Type", "application/json")
    req.add_header("X-CSRF-Token", urllib.parse.unquote(COOKIES.get("__Host-csrf_token", "")))
    try:
        r = urllib.request.urlopen(req, timeout=30)
        j = json.loads(r.read())
        print("[refresh] ok", list(j.keys()))
        for k in ("access_token", "refresh_token"):
            if j.get(k):
                COOKIES["__Host-" + k.replace("_", "-")] = j[k]
        return True
    except Exception as e:
        print("[refresh] fail", e)
        return False


def call(method, path, body=None, raw=False):
    global COOKIES
    for attempt in (0, 1):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method)
        req.add_header("Cookie", _cookie_header())
        req.add_header("Content-Type", "application/json")
        req.add_header("X-CSRF-Token", urllib.parse.unquote((COOKIES or load_cookies()).get("__Host-csrf_token", "")))
        req.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")
        try:
            r = urllib.request.urlopen(req, timeout=60)
            b = r.read()
            return json.loads(b) if not raw else b
        except urllib.error.HTTPError as e:
            b = e.read()
            if e.code == 401 and attempt == 0:
                print("[401] 尝试刷新会话…")
                refresh()
                continue
            print("[HTTP %d] %s" % (e.code, b[:400].decode("utf-8", "replace")))
            return None
    return None


if __name__ == "__main__":
    c = load_cookies()
    print("cookies:", sorted(c.keys()))
    print("access_token len:", len(c.get("__Host-access_token", "")), "csrf len:", len(c.get("__Host-csrf_token", "")))
    r = call("GET", "/console/api/apps?page=1&limit=5")
    if r:
        for a in r.get("data", []):
            print(" ", a["id"], a["name"], a.get("mode"))
