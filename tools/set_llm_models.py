#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReadPal · 按 model_channels.POLICY 把一份完整草稿里的 LLM 节点换到目标渠道。

用途：换模型（生成档 → luna 之类）。**只动 `model` 字段**，图结构、节点代码、提示词
一律不碰 —— 这样绝不会因为「重新构建」而把别人在 Dify 上的改动冲掉。

用法
----
    node tools/dump_full_draft.mjs <app_id> /tmp/draft.json          # 1. 拿真源（完整草稿）
    python3 tools/set_llm_models.py --in=/tmp/draft.json --out=/tmp/payload.json
    node tools/dify_push_graph.mjs --app=<app_id> --graph=/tmp/payload.json   # 2. 推草稿
    node tools/dify_publish.mjs --app=<app_id> --note="…"                      # 3. 发布

    --dry   只打印将要发生的变更，不写文件
    --only=gen   只改生成节点（不动校验节点）；--only=check 反之

退出码：0 有变更且写出；1 出错或无变更；2 校验失败
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import model_channels as MC  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', required=True, help='dump_full_draft.mjs 拉到的完整草稿')
    ap.add_argument('--out', dest='dst', help='输出 payload（--dry 时可省）')
    ap.add_argument('--dry', action='store_true', help='只打印变更，不写文件')
    ap.add_argument('--only', choices=['gen', 'check'], help='只改某一类')
    ap.add_argument('--indent', type=int, default=1,
                    help='输出缩进（dify_graphs/graphA|graphB.new.json 是 2，其余是 1）')
    a = ap.parse_args()

    doc = json.loads(pathlib.Path(a.src).read_text(encoding='utf-8'))
    graph = doc.get('graph') or {}
    nodes = graph.get('nodes') or []
    if not nodes:
        print('✗ %s 里没有 graph.nodes —— 确认这是 dump_full_draft 的产物' % a.src)
        return 1

    rows, changed = [], 0
    seen = set()
    for n in nodes:
        d = n.get('data') or {}
        if d.get('type') != 'llm':
            continue
        nid = n['id']
        seen.add(nid)
        kind = MC.classify(nid)                    # 未知 id 会抛 KeyError
        if a.only and kind != a.only:
            rows.append((nid, kind, '跳过（--only=%s）' % a.only))
            continue
        hit, desc = MC.retarget_model(d.setdefault('model', {}), nid)
        changed += 1 if hit else 0
        cp = d['model'].get('completion_params') or {}
        rows.append((nid, kind, '%s | 参数=%s' % (desc, {k: v for k, v in cp.items()})))

    if not rows:
        print('✗ 这份草稿里没有 LLM 节点')
        return 1

    print('节点 %d 个 LLM：' % len(rows))
    for nid, kind, desc in rows:
        print('  %-16s [%s] %s' % (nid, kind, desc))

    # 事后自检：目标渠道 + 参数是否都到位（错一处就退出码 2，不静默）
    bad = []
    for n in nodes:
        d = n.get('data') or {}
        if d.get('type') != 'llm':
            continue
        kind = MC.classify(n['id'])
        if a.only and kind != a.only:
            continue
        ch = MC.CHANNELS[MC.POLICY[kind]]
        m = d.get('model') or {}
        if m.get('provider') != ch['provider'] or m.get('name') != ch['name']:
            bad.append('%s 渠道不对 %s/%s ≠ %s/%s' % (n['id'], m.get('provider'), m.get('name'),
                                                     ch['provider'], ch['name']))
        cp = m.get('completion_params') or {}
        for k in ch.get('drop_params', ()):
            if k in cp:
                bad.append('%s 残留上游不认的参数 %s' % (n['id'], k))
        if ch is MC.CHANNELS['luna']:
            want = MC.LUNA_MAX_TOKENS.get(n['id'])
            if want and cp.get('max_tokens') != want:
                bad.append('%s max_tokens=%s ≠ %s（推理型会静默截空）' % (n['id'], cp.get('max_tokens'), want))
            if (cp.get('max_tokens') or 0) < 4096:
                bad.append('%s max_tokens=%s 太小，luna 思考会吃光预算' % (n['id'], cp.get('max_tokens')))
    if bad:
        print('✗ 自检失败：' + '; '.join(bad))
        return 2

    unknown = seen - MC.GEN_NODE_IDS - MC.CHECK_NODE_IDS
    if unknown:
        print('✗ 有未归类节点：%s' % ', '.join(sorted(unknown)))
        return 2

    print('✓ 自检通过：%d 个节点已按策略到位（生成→%s / 校验→%s），实际变更 %d 处' % (
        len(rows), MC.POLICY['gen'], MC.POLICY['check'], changed))

    if a.dry:
        print('（--dry：未写文件）')
        return 0
    if not a.dst:
        print('✗ 非 --dry 时必须给 --out')
        return 1
    pathlib.Path(a.dst).write_text(json.dumps(doc, ensure_ascii=False, indent=a.indent), encoding='utf-8')
    print('✓ → %s（保留应用级字段：%s）' % (
        a.dst, ', '.join(k for k in doc if k != 'graph')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
