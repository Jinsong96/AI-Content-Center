#!/usr/bin/env python3
"""
ReadPal · 原子替换工具

用途：对**同一个文件**做多处替换时，避免「并行 Edit 静默互相覆盖」（见 AGENTS.md 坑 1）。

核心保证：**先全量校验命中数，全部通过才写盘**。任何一项命中数不符 → 整体中止、不写盘。
这样就不可能发生「明明改了却没生效」。

用法：
    python3 tools/atomic_replace.py <目标文件> <规格.json>

规格.json 格式（数组，每项一个替换）：
    [
      {"type":"literal","old":"原文","new":"新文","expect":1,"label":"说明"},
      {"type":"regex","old":"\\\\n\\\\s*<p>.*?</p>","new":"","expect":1,"label":"正则删整段"}
    ]

    expect  期望命中次数，省略默认 1。写 0 表示「允许不存在」（用于幂等场景）
    new     省略则默认空串（即删除）
    type    省略默认 literal

退出码：0 = 全部成功；1 = 有断言不符或执行错误；2 = 用法/参数错误

⚠️ 调用方注意：请用 <<'PY'（带引号的 heredoc）或独立 .py 文件来生成规格，
   否则 bash 会展开 $ 把 JS 模板字符串搞坏。
"""
import json
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    target, spec_path = Path(sys.argv[1]), Path(sys.argv[2])
    if not target.is_file():
        print(f'✗ 目标文件不存在: {target}')
        return 2
    if not spec_path.is_file():
        print(f'✗ 规格文件不存在: {spec_path}')
        return 2

    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    if not isinstance(spec, list):
        print('✗ 规格文件必须是 JSON 数组')
        return 2

    src = orig = target.read_text(encoding='utf-8')

    # ---------- 阶段 1：全量校验（不写盘）----------
    plan = []
    for i, item in enumerate(spec):
        kind = item.get('type', 'literal')
        old = item['old']
        expect = item.get('expect', 1)
        label = item.get('label', f'#{i}')

        if kind == 'literal':
            n = src.count(old)
        elif kind == 'regex':
            n = len(re.findall(old, src, re.S))
        else:
            print(f'✗ ABORT [{label}] 未知 type: {kind}')
            return 1

        if n != expect:
            print(f'✗ ABORT [{label}] 期望命中 {expect} 次，实际 {n} 次 —— 未写盘，文件保持原样')
            return 1
        plan.append((kind, old, item.get('new', ''), expect, label))

    # ---------- 阶段 2：全部通过，执行替换 ----------
    for kind, old, new, expect, label in plan:
        if kind == 'literal':
            src = src.replace(old, new)
        else:
            src = re.sub(old, new, src, flags=re.S)
        print(f'✓ {label}  ({expect} 处)')

    target.write_text(src, encoding='utf-8')
    print(f'\n写入完成：{len(orig)} → {len(src)} 字符（差 {len(src) - len(orig):+d}）')
    print('下一步：python3 tools/check_js.py ' + str(target))
    return 0


if __name__ == '__main__':
    sys.exit(main())
