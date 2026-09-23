#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在「DeepSeek 官方」与「硅基流动」两个渠道之间切换 LLM 节点。

为什么需要它
------------
Dify 里 `langgenius/deepseek/deepseek`（api.deepseek.com）与本项目用的
`langgenius/siliconflow/siliconflow`（api.siliconflow.cn）**都挂着同名的 DeepSeek V4 模型**：

    官方 : deepseek-v4-pro      / deepseek-v4-flash
    硅基 : deepseek-ai/DeepSeek-V4-Pro / deepseek-ai/DeepSeek-V4-Flash

2026-09-21 官方账户余额归零 → 所有工作流在第一个 LLM 节点就 402
（`Insufficient Balance`，0.8s 秒退），线上 FACT/GEN 全线停摆。
本工具用于把图（源码里的 MODEL_* 常量，或已生成的 graph json）整体切到另一渠道。

用法
----
    # 切源码里的模型常量（build_graphA.py / build_graphB.py 等）
    python3 tools/patch_model_provider.py --to=sf   tools/build_graphB.py
    python3 tools/patch_model_provider.py --to=official tools/build_graphB.py

    # 直接切一份图 json（改了立刻能 push）
    python3 tools/patch_model_provider.py --to=sf   --graph=dify_graphs/graphB.new.json

    # 只看会改什么
    python3 tools/patch_model_provider.py --to=sf --check --graph=xxx.json

幂等：重复执行结果不变（已是目标渠道则报 0 处改动）。
"""

import argparse
import json
import re
from pathlib import Path

# 渠道定义：(provider 标识, {官方模型名: 硅基模型名}, 思考开关的参数名)
#
# 🔴 think_param 必须一起切，这是最容易漏的一步：
#   官方 `thinking` / 硅基 `enable_thinking` —— **参数名不同**，
#   写错的那个会被 Dify **静默丢弃**（不报错），模型就按渠道默认值跑。
#   2026-09-21 实测：只切 provider 没切参数名 → 硅基那边思考默认打开 →
#   「A1- 生成」跑了 **205 秒**才摔，报 `KeyError: 'choices'`（流被拖长/截断），
#   看着像网络问题，其实是参数名写错。同一份图在官方渠道用 `thinking` 是对的。
CHANNELS = {
    'official': {
        'provider': 'langgenius/deepseek/deepseek',
        'models': {
            'deepseek-v4-pro': 'deepseek-v4-pro',
            'deepseek-v4-flash': 'deepseek-v4-flash',
        },
        'think_param': 'thinking',
    },
    'sf': {
        'provider': 'langgenius/siliconflow/siliconflow',
        'models': {
            'deepseek-v4-pro': 'deepseek-ai/DeepSeek-V4-Pro',
            'deepseek-v4-flash': 'deepseek-ai/DeepSeek-V4-Flash',
        },
        'think_param': 'enable_thinking',
    },
}

ALL_THINK_PARAMS = ['thinking', 'enable_thinking']   # 已知写法；'thinking' 是 'enable_thinking' 的子串，替换要防串

# 反查：任意渠道下的模型名 → 规范键（deepseek-v4-pro / deepseek-v4-flash）
CANON = {}
for _ch in CHANNELS.values():
    for _canon, _actual in _ch['models'].items():
        CANON[_actual] = _canon


def canon_of(name):
    """把任意渠道的模型名归一化成规范键；认不出返回 None。"""
    if name in CANON:
        return CANON[name]
    low = str(name).lower()
    for key in ('v4-pro', 'v4-flash'):  # 兜底：容忍前缀/大小写差异
        if key in low:
            return 'deepseek-' + key
    return None


def rename_think_keys(obj, target):
    """把 completion_params 里的思考开关改成目标渠道的参数名。就地改，返回改动数。

    ⚠️ `'thinking'` 是 `'enable_thinking'` 的子串，不能直接 str.replace ——
    必须先改名字长的那个，否则 `enable_thinking` → `enable_enable_thinking`。
    """
    want = CHANNELS[target]['think_param']
    if not isinstance(obj, dict):
        return 0
    n = 0
    for src in ALL_THINK_PARAMS:
        if src == want or src not in obj:
            continue
        obj[want] = obj.pop(src)
        n += 1
    return n


def think_rename_specs(target):
    """生成源码文本替换对（长的先做），供 patch_text 用。"""
    want = CHANNELS[target]['think_param']
    specs = []
    for src in sorted(ALL_THINK_PARAMS, key=len, reverse=True):
        if src != want:
            specs.append((src, want))
    return specs


def patch_text(path, target):
    """改源码文件里的 provider / name 字面量。返回 (新文本, 改动数, 明细)"""
    s = Path(path).read_text(encoding='utf-8')
    # 🔴 2026-09-23：模型档已是 tools/model_channels.py 单一真源。
    #    这些建图脚本里的 provider/name 字面量**只是新建节点时的占位**，落盘前会被
    #    MC.apply_policy() 按节点 id 改写。再改字面量不但无效，还会制造「改了却没生效」
    #    的错觉（最坏情况：以为切了渠道，线上其实没变）。直接拒绝并指路。
    if 'model_channels' in s:
        raise SystemExit(
            '✗ 拒绝改写 %s：该文件已接入 tools/model_channels.py（模型档单一真源）。\n'
            '  · 要整体切渠道 → 改 model_channels.py 的 CHANNELS / POLICY\n'
            '  · 要换某张图某几个节点 → python3 tools/set_llm_models.py --in=<草稿dump> --out=<payload>' % path)
    ch = CHANNELS[target]
    hits = []

    # ① provider 字面量：任意已知渠道 → 目标渠道
    for src in CHANNELS.values():
        old = f"'provider': '{src['provider']}'"
        new = f"'provider': '{ch['provider']}'"
        n = s.count(old)
        if n and old != new:
            s = s.replace(old, new)
            hits.append(f'provider {src["provider"]} → {ch["provider"]} ×{n}')

    # ② 模型名：按规范键映射到目标渠道的名字
    for canon, actual in ch['models'].items():
        for src_name in CANON:                      # 所有已知写法
            if CANON[src_name] != canon or src_name == actual:
                continue
            old = f"'name': '{src_name}'"
            new = f"'name': '{actual}'"
            n = s.count(old)
            if n:
                s = s.replace(old, new)
                hits.append(f'name {src_name} → {actual} ×{n}')

    # ③ 思考开关参数名（带引号 + 冒号，所以 'thinking' 不会误伤 'enable_thinking'）
    for src, want in think_rename_specs(target):
        for q in ("'", '"'):
            old, new = f'{q}{src}{q}:', f'{q}{want}{q}:'
            n = s.count(old)
            if n:
                s = s.replace(old, new)
                hits.append(f'think 参数 {src} → {want} ×{n}')

    return s, len(hits), hits


def patch_graph(path, target):
    """改 graph json 里所有 llm 节点的 data.model。返回 (payload, 改动数, 明细)"""
    p = Path(path)
    g = json.loads(p.read_text(encoding='utf-8'))
    ch = CHANNELS[target]
    hits = []
    for n in g.get('graph', {}).get('nodes', []):
        d = n.get('data') or {}
        m = d.get('model')
        if not isinstance(m, dict):
            continue
        canon = canon_of(m.get('name'))
        if not canon:
            continue
        want = ch['models'][canon]
        if m.get('provider') != ch['provider'] or m.get('name') != want:
            hits.append(f'{n.get("id")}: {m.get("provider")}/{m.get("name")} → {ch["provider"]}/{want}')
            m['provider'] = ch['provider']
            m['name'] = want
        # 思考开关参数名随渠道走，别漏
        k = rename_think_keys(m.get('completion_params'), target)
        if k:
            hits.append(f'{n.get("id")}: think 参数 → {ch["think_param"]}')
    return g, len(hits), hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--to', required=True, choices=sorted(CHANNELS))
    ap.add_argument('--graph', help='直接改一份图 json（与位置参数二选一/可同时）')
    ap.add_argument('--check', action='store_true', help='只报告，不写盘')
    ap.add_argument('files', nargs='*', help='源码文件，如 tools/build_graphB.py')
    a = ap.parse_args()

    total = 0
    for f in a.files:
        new, n, hits = patch_text(f, a.to)
        total += n
        print(f'[{f}] {n} 处')
        for h in hits:
            print('   ·', h)
        if n and not a.check:
            Path(f).write_text(new, encoding='utf-8')

    if a.graph:
        g, n, hits = patch_graph(a.graph, a.to)
        total += n
        print(f'[{a.graph}] {n} 处')
        for h in hits:
            print('   ·', h)
        if n and not a.check:
            Path(a.graph).write_text(
                json.dumps(g, ensure_ascii=False, indent=2), encoding='utf-8')

    print(('🔎 仅检查，未写盘：' if a.check else '✅ 已写入：') + f'{total} 处 → {a.to}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
