#!/usr/bin/env python3
"""
ReadPal · 单文件大 HTML 的 JS 语法校验

改完 frontend/index.html 必跑。抽出所有非空 <script> 块，逐个交给 node --check。
能挡住大部分白屏事故（典型症状：插入多层 if/else 时少一个闭合 }，
报错形如 Unexpected token 'catch'）。

用法：
    python3 tools/check_js.py frontend/index.html
    python3 tools/check_js.py frontend/index.html /path/to/node    # 指定 node

node 查找顺序：命令行第 2 参数 → 环境变量 NODE_BIN → PATH 里的 node → 常见安装路径

退出码：0 = 全部通过；1 = 有语法错误；2 = 用法错误或找不到 node
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

COMMON_NODE = [
    '/usr/local/bin/node',
    '/opt/homebrew/bin/node',
    '/usr/bin/node',
]


def find_node(explicit: str | None = None) -> str | None:
    for cand in [explicit, os.environ.get('NODE_BIN'), shutil.which('node'), *COMMON_NODE]:
        if not cand:
            continue
        p = cand if os.path.isabs(cand) else shutil.which(cand)
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    html = Path(sys.argv[1])
    if not html.is_file():
        print(f'✗ 文件不存在: {html}')
        return 2

    node = find_node(sys.argv[2] if len(sys.argv) > 2 else None)
    if not node:
        print('✗ 找不到 node。请安装 Node.js，或用第 2 个参数 / NODE_BIN 环境变量指定绝对路径。')
        return 2
    print(f'使用 node: {node}')

    src = html.read_text(encoding='utf-8')
    blocks = [b for b in re.findall(r'<script\b[^>]*>(.*?)</script>', src, re.S) if b.strip()]
    print(f'{html}: {len(src)} 字符 / {len(blocks)} 个非空 script 块\n')

    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i, b in enumerate(blocks):
            f = Path(tmp) / f'b{i}.js'
            f.write_text(b, encoding='utf-8')
            r = subprocess.run([node, '--check', str(f)], capture_output=True, text=True)
            if r.returncode == 0:
                print(f'  OK   b{i}.js ({len(b.encode("utf-8"))} bytes)')
            else:
                failed += 1
                print(f'  FAIL b{i}.js:')
                print('    ' + (r.stderr or r.stdout).strip().replace('\n', '\n    '))

    print('\n结果:', '全部通过 ✅' if failed == 0 else f'{failed} 个块有语法错误 ❌')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
