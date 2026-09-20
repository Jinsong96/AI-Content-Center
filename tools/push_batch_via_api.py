#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量推送文件到 GitHub —— 所有文件合成**一个** commit。

和 `push_via_api.py` 的关系
--------------------------
`push_via_api.py` 走 Contents API，一次只能推一个文件（一个文件 = 一个 commit）。
推代码没问题，但推 300+ 个素材文件会产生 300+ 个 commit，历史很脏。
本脚本走 **Git Data API**：blobs → 一个新 tree → 一个 commit → 更新 ref，
无论多少文件都只留一条提交记录。

用法
----
    # 从 stdin 读路径列表（每行一个仓库相对路径）
    find calibration/text -name '*.txt' | python3 tools/push_batch_via_api.py -m "chore: 导入范文语料"

    # 或直接列路径
    python3 tools/push_batch_via_api.py -m "msg" calibration/report.md calibration/README.md

    # 只预演不提交
    python3 tools/push_batch_via_api.py --dry-run -m "msg" < list.txt

令牌解析顺序：`--token` > 环境变量 `READPAL_GH_TOKEN` / `GITHUB_TOKEN` > `tools/.env.json` 的 `gh_token`。
未改动（blob sha 与远端一致）的文件会自动跳过，不进入本次 commit。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

REPO = "Jinsong96/AI-Content-Center"
BRANCH = "main"
API = f"https://api.github.com/repos/{REPO}"

# 绝不入库（与 .gitignore 一致）
EXCLUDE = {
    "tools/.env.json",
    "backend/.article_cache.json",
    "backend/.toutiao_en_cache.json",
}


def blob_sha(data: bytes) -> str:
    """git blob 的 sha1 —— 用来判断本地与远端是否已一致。"""
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def resolve_token(args) -> str:
    if args.token:
        return args.token
    for env in ("READPAL_GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(env):
            return os.environ[env]
    cfg = pathlib.Path(__file__).parent / ".env.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8"))["gh_token"]
        except (json.JSONDecodeError, KeyError):
            pass
    sys.exit("找不到令牌：用 --token、环境变量 READPAL_GH_TOKEN，或写 tools/.env.json")


def api(url: str, token: str, method: str = "GET", payload=None, retries: int = 4):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"token {token}",
        "User-Agent": "readpal-push-batch",
        "Content-Type": "application/json",
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            if e.code in (502, 503, 504, 429) and attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            sys.exit(f"HTTP {e.code} {method} {url}\n{body}")
        except Exception as e:  # noqa: BLE001
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            sys.exit(f"请求失败 {method} {url}: {type(e).__name__}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="批量推送文件（一个 commit）")
    ap.add_argument("-m", "--message", required=True, help="commit message")
    ap.add_argument("paths", nargs="*", help="仓库相对路径；省略则从 stdin 读")
    ap.add_argument("--token", default=None)
    ap.add_argument("--workers", type=int, default=6, help="并发创建 blob 数（默认 6）")
    ap.add_argument("--dry-run", action="store_true", help="只列出要推的文件，不提交")
    args = ap.parse_args()

    if args.paths:
        raw = list(args.paths)
    else:
        raw = [ln.strip() for ln in sys.stdin if ln.strip()]

    # 规范化 + 过滤
    candidates: list[tuple[str, pathlib.Path]] = []
    seen = set()
    for p in raw:
        # ⚠️ 不能用 lstrip("./") —— 那会把 `.gitignore` 变成 `gitignore`（开头的点被吃掉）
        rel = p.replace(os.sep, "/")
        while rel.startswith("./"):
            rel = rel[2:]
        rel = rel.lstrip("/")
        if rel in seen or rel in EXCLUDE or rel.startswith("backend/audio/"):
            continue
        f = pathlib.Path(rel)
        if not f.is_file():
            print(f"  ⚠ 跳过不存在的文件: {rel}")
            continue
        seen.add(rel)
        candidates.append((rel, f))

    if not candidates:
        sys.exit("没有可推送的文件")

    token = resolve_token(args)

    # 远端当前状态
    ref = api(f"{API}/git/refs/heads/{BRANCH}", token)
    base_commit = ref["object"]["sha"]
    commit = api(f"{API}/git/commits/{base_commit}", token)
    base_tree = commit["tree"]["sha"]
    tree = api(f"{API}/git/trees/{base_tree}?recursive=1", token)
    remote = {e["path"]: e["sha"] for e in tree["tree"] if e["type"] == "blob"}

    # 找出真正需要更新的文件
    todo: list[tuple[str, bytes]] = []
    skipped = 0
    for rel, f in candidates:
        data = f.read_bytes()
        if remote.get(rel) == blob_sha(data):
            skipped += 1
            continue
        todo.append((rel, data))

    print(f"候选 {len(candidates)} · 未变化跳过 {skipped} · 待推送 {len(todo)}")
    if not todo:
        print("远端已是最新，无需提交")
        return 0
    if args.dry_run:
        for rel, _ in todo:
            print(f"   + {rel}")
        print(f"\n（--dry-run，未提交）")
        return 0

    # 并发创建 blob
    def make_blob(item):
        rel, data = item
        r = api(f"{API}/git/blobs", token, "POST", {
            "content": base64.b64encode(data).decode(),
            "encoding": "base64",
        })
        return {"path": rel, "mode": "100644", "type": "blob", "sha": r["sha"]}

    entries: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(make_blob, it): it[0] for it in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            entries.append(fut.result())
            if i % 25 == 0 or i == len(todo):
                print(f"  blob {i}/{len(todo)}")

    new_tree = api(f"{API}/git/trees", token, "POST",
                   {"base_tree": base_tree, "tree": entries})
    new_commit = api(f"{API}/git/commits", token, "POST", {
        "message": args.message,
        "tree": new_tree["sha"],
        "parents": [base_commit],
    })
    api(f"{API}/git/refs/heads/{BRANCH}", token, "PATCH",
        {"sha": new_commit["sha"], "force": False})

    print(f"\n✓ 已推送 {len(entries)} 个文件（跳过未变化 {skipped}）")
    print(f"  commit {new_commit['sha'][:10]}  ←  {base_commit[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
