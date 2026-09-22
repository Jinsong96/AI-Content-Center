#!/usr/bin/env python3
"""从 tools/build_graphA.py 抽出各代码节点的 JS，写成可 require 的临时文件，供本地单测。

用法： python3 tools/_extract_gA_code.py [输出目录，默认 /tmp]
"""
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / 'build_graphA.py'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/tmp')
BLOCKS = {
    '_gA_final.js': 'FINAL_CODE',
    '_gA_count.js': 'COUNT_CODE',
    '_gA_clean.js': 'CLEAN_CODE',
}


def main():
    s = SRC.read_text(encoding='utf-8')
    n = 0
    for fname, var in BLOCKS.items():
        m = re.search(var + r" = r'''(.*?)'''", s, re.S)
        if not m:
            print('✗ 找不到', var)
            return 1
        p = OUT / fname
        p.write_text(m.group(1) + '\nmodule.exports = main;\n', encoding='utf-8')
        print('✓ %-16s → %s (%d chars)' % (var, p, len(m.group(1))))
        n += 1
    print('共抽出 %d 段 JS' % n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
