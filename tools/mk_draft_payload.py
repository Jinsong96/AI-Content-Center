#!/usr/bin/env python3
"""把「新构建的 graph」装进「完整草稿」的骨架，产出可直接推送的 payload。

为什么需要它（别直接用 build_*.py 产出的文件去推）
--------------------------------------------------
`dify_push_graph.mjs` 的请求体是 `{ graph, features, conversation_variables, hash }`。
`build_graphA/B/C.py` 产出的 json 只带 `graph` + 空的 `features`，
直接推会把应用级配置（文件上传、语音、retriever 等）**清空**。
所以：先用 `dump_full_draft.mjs` 拉一份完整草稿当骨架，再在它上面只替换 `graph`。

用法
----
    node tools/dump_full_draft.mjs <app_id> /tmp/full.json          # 1. 拉完整草稿当骨架
    python3 tools/mk_draft_payload.py --graph=dify_graphs/graphC.new.json \
                                      --bak=/tmp/full.json --out=/tmp/payload.json
    node tools/dify_push_graph.mjs --app=<app_id> --graph=/tmp/payload.json

    # 只想替换单个节点的 model（换模型对照实验）时，用 --set-model 更精准：
    python3 tools/mk_draft_payload.py --graph=dify_graphs/graphC.luna.json \
                                      --bak=/tmp/full.json --out=/tmp/p.json --only-model
"""
from __future__ import annotations

import argparse
import json
import pathlib


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--graph', required=True, help='build_*.py 产出的新图')
    ap.add_argument('--bak', required=True, help='dump_full_draft.mjs 拉到的完整草稿')
    ap.add_argument('--out', required=True, help='输出去向')
    ap.add_argument('--only-model', action='store_true',
                    help='不动 graph 结构，只把 bak 里 LLM 节点的 model 改成新图里的同 id 节点')
    a = ap.parse_args()

    new = json.loads(pathlib.Path(a.graph).read_text(encoding='utf-8'))
    base = json.loads(pathlib.Path(a.bak).read_text(encoding='utf-8'))
    n_new = {n['id']: n for n in new['graph']['nodes']}

    if a.only_model:
        hits = 0
        for n in base['graph']['nodes']:
            if n.get('data', {}).get('type') == 'llm' and n['id'] in n_new:
                old = n['data'].get('model') or {}
                m = n_new[n['id']]['data']['model']
                n['data']['model'] = m
                print('  %s：%s | %s → %s | %s' % (n['id'], old.get('provider'), old.get('name'),
                                                   m.get('provider'), m.get('name')))
                hits += 1
        if not hits:
            print('✗ 没有匹配到任何 LLM 节点（id 对不上？）')
            return 1
    else:
        base['graph'] = new['graph']
        base['graph'].setdefault('viewport', {})

    pathlib.Path(a.out).write_text(json.dumps(base, ensure_ascii=False, indent=1), encoding='utf-8')
    print('✓ %s → %s（节点 %d / 边 %d）' % (
        pathlib.Path(a.graph).name, a.out, len(base['graph']['nodes']), len(base['graph']['edges'])))
    for n in base['graph']['nodes']:
        d = n.get('data', {})
        if d.get('type') == 'llm':
            print('   LLM  %s | %s | %s' % (n['id'], d['model'].get('provider'), d['model'].get('name')))
        elif d.get('type') == 'code':
            print('   CODE %s | %d 字符' % (n['id'], len(d.get('code') or '')))
    print('   保留应用级字段：%s' % ', '.join(k for k in base if k != 'graph'))
    if a.only_model:
        print('   ⚠️ --only-model：只有 model 变了，其余节点（含 code/提示词）保持骨架原样 ——')
        print('      想连 code / 提示词一起更新，去掉 --only-model 做整图替换。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
