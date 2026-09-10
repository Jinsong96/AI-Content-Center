#!/usr/bin/env python3
"""
ReadPal · 源码镜像（避免 git clone 的 90MB 音频地狱）

⚠️ 不要用 `git clone` —— 仓库含 31 个 mp3、约 90MB，浅克隆经常跑几分钟甚至超时。
   日常只需要源码，用本脚本走 GitHub API 逐个拉 raw，跳过 backend/audio。

产出：42 个源码文件，与远端 sha256 一致，可直接在本地改。

用法：
    python3 tools/fetch_sources.py /path/to/workdir        # 镜像到指定目录
    python3 tools/fetch_sources.py .                       # 镜像到当前目录

令牌来源同 push_via_api.py（--token= / READPAL_GH_TOKEN / GITHUB_TOKEN / tools/.env.json）

退出码：0 = 全部成功；1 = 有文件失败；2 = 用法错误
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

OWNER, REPO, BRANCH = 'Jinsong96', 'AI-Content-Center', 'main'
SKIP_PREFIX = ('backend/audio',)
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


def main(out_dir: str) -> int:
    tok = resolve_token()
    if not tok:
        print('✗ 找不到令牌。用 --token=xxx、READPAL_GH_TOKEN 环境变量，或写 tools/.env.json')
        return 1

    head = {'Authorization': 'token ' + tok,
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'readpal-agent'}

    url = f'https://api.github.com/repos/{OWNER}/{REPO}/git/trees/{BRANCH}?recursive=1'
    tree = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=head), timeout=60))
    blobs = [i for i in tree['tree']
             if i['type'] == 'blob' and not i['path'].startswith(SKIP_PREFIX)]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    skipped_audio = len(tree['tree']) - len(blobs) - sum(
        1 for i in tree['tree'] if i['type'] == 'tree')

    for b in blobs:
        dest = out / b['path']
        dest.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(4):
            try:
                r = urllib.request.Request(
                    f'https://api.github.com/repos/{OWNER}/{REPO}/contents/'
                    f'{urllib.parse.quote(b["path"])}?ref={BRANCH}',
                    headers={**head, 'Accept': 'application/vnd.github.v3.raw'})
                dest.write_bytes(urllib.request.urlopen(r, timeout=60).read())
                ok += 1
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 3:
                    print(f'  FAIL {b["path"]}: {type(e).__name__}: {e}')
                    fail += 1
                else:
                    time.sleep(3)

    print(f'\n镜像完成：成功 {ok} / 失败 {fail}  →  {out.resolve()}')
    print(f'（已跳过 backend/audio 下的音频文件）')
    return 0 if fail == 0 else 1


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 1:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(args[0]))
