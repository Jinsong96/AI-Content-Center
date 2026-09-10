#!/usr/bin/env python3
"""
ReadPal · GitHub API 直传（不能用 git push！）

背景：本地 git 仓库与远程 main **历史已分叉**，`git push` 会被拒绝。
      统一走 GitHub API 直传。

原理：GET /repos/{o}/{r}/contents/{path} 拿 sha
      → PUT 同路径，带 content(base64) + sha + branch:main

大文件（约 682KB）偶发 IncompleteRead，脚本内置重试 4 次 × 3s，一般第 1~2 次即成功。

用法：
    python3 tools/push_via_api.py frontend/index.html frontend/index.html "commit message"
    python3 tools/push_via_api.py AGENTS.md AGENTS.md "docs: update"

令牌来源（按优先级）：
    1) --token=xxx 参数
    2) 环境变量 READPAL_GH_TOKEN
    3) 环境变量 GITHUB_TOKEN
    4) tools/.env.json  内容 {"gh_token":"..."}   ← 已被 .gitignore 排除，勿提交

退出码：0 = 成功；1 = 失败；2 = 用法错误
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OWNER, REPO, BRANCH = 'Jinsong96', 'AI-Content-Center', 'main'
API = f'https://api.github.com/repos/{OWNER}/{REPO}/contents/'
ENV_FILE = Path(__file__).resolve().parent / '.env.json'


def resolve_token() -> str | None:
    for a in sys.argv[1:]:
        if a.startswith('--token='):
            return a.split('=', 1)[1].strip()
    for var in ('READPAL_GH_TOKEN', 'GITHUB_TOKEN'):
        if os.environ.get(var):
            return os.environ[var].strip()
    if ENV_FILE.is_file():
        try:
            return json.loads(ENV_FILE.read_text(encoding='utf-8')).get('gh_token', '').strip() or None
        except Exception:  # noqa: BLE001
            pass
    return None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) < 2:
        print(__doc__)
        return 2

    remote_path, local_path = args[0], Path(args[1])
    message = args[2] if len(args) > 2 else f'chore: update {remote_path}'

    if not local_path.is_file():
        print(f'✗ 本地文件不存在: {local_path}')
        return 1

    tok = resolve_token()
    if not tok:
        print('✗ 找不到令牌。用 --token=xxx、READPAL_GH_TOKEN 环境变量，或写 tools/.env.json')
        return 1

    head = {'Authorization': 'token ' + tok,
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'readpal-agent',
            'Content-Type': 'application/json'}

    data = local_path.read_bytes()
    print(f'>> 推送 {remote_path}  ({len(data)} bytes, base64≈{len(data) * 4 // 3} bytes)')

    try:
        req = urllib.request.Request(API + remote_path + f'?ref={BRANCH}', headers=head)
        meta = json.load(urllib.request.urlopen(req, timeout=60))
        sha = meta['sha']
        print(f'   远端当前 sha: {sha[:12]}  size={meta["size"]}')
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f'   ⚠ 远端尚无 {remote_path}，将作为新文件创建')
            sha = None
        else:
            print(f'✗ 读取远端失败: {e}')
            return 1

    payload = {'message': message,
               'content': base64.b64encode(data).decode('ascii'),
               'branch': BRANCH}
    if sha:
        payload['sha'] = sha
    body = json.dumps(payload).encode('utf-8')

    for attempt in range(1, 5):
        try:
            req = urllib.request.Request(API + remote_path, data=body, headers=head, method='PUT')
            res = json.load(urllib.request.urlopen(req, timeout=180))
            print(f'   ✓ 第 {attempt} 次成功  commit={res["commit"]["sha"][:12]}  '
                  f'new_sha={res["content"]["sha"][:12]}')
            print('\n已推送。Railway 约 90 秒后自动部署完成。')
            print('下一步：等 95 秒后核验线上，或跑 node tools/e2e_verify.mjs')
            return 0
        except Exception as e:  # noqa: BLE001
            print(f'   ✗ 第 {attempt} 次失败: {type(e).__name__}: {e}')
            if attempt == 4:
                print('   放弃')
                return 1
            time.sleep(3)
    return 1


if __name__ == '__main__':
    sys.exit(main())
