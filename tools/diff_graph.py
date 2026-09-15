# -*- coding: utf-8 -*-
"""比对两份 Dify graph：线上 draft vs 本地新图。逐字段列出差异。"""
import json, sys, difflib


def load(p):
    return json.load(open(p, encoding='utf-8'))


def unwrap(g):
    return g['graph'] if isinstance(g, dict) and 'graph' in g and 'nodes' not in g else g


online = unwrap(load(sys.argv[1]))
local = unwrap(load(sys.argv[2]))


def by_id(g):
    return {n['id']: n for n in g['nodes']}


A, B = by_id(online), by_id(local)

print('=== 节点集合 ===')
print('  线上 %d / 本地 %d' % (len(A), len(B)))
onlyA, onlyB = sorted(set(A) - set(B)), sorted(set(B) - set(A))
print('  仅线上: %s' % (onlyA or '—'))
print('  仅本地: %s' % (onlyB or '—'))


def show(a, b, label, maxlines=30):
    if a == b:
        return
    print('    · %s' % label)
    la = a.splitlines() if isinstance(a, str) else json.dumps(a, ensure_ascii=False, indent=1).splitlines()
    lb = b.splitlines() if isinstance(b, str) else json.dumps(b, ensure_ascii=False, indent=1).splitlines()
    n = 0
    for line in difflib.unified_diff(la, lb, 'online', 'local', lineterm='', n=0):
        if line.startswith('---') or line.startswith('+++'):
            continue
        print('        %s' % line[:240])
        n += 1
        if n >= maxlines:
            print('        ...（截断）')
            break


print('=== 节点内差异 ===')
ndiff = 0
for k in sorted(set(A) & set(B)):
    if A[k] == B[k]:
        continue
    ndiff += 1
    print('  ■ %s (%s)' % (k, A[k].get('data', {}).get('title')))
    da, db = A[k].get('data', {}), B[k].get('data', {})
    for f in sorted(set(da) | set(db)):
        if da.get(f) != db.get(f):
            show(da.get(f), db.get(f), 'data.%s' % f)
    for f in sorted(set(A[k]) | set(B[k])):
        if f == 'data':
            continue
        if A[k].get(f) != B[k].get(f):
            show(A[k].get(f), B[k].get(f), f)
if not ndiff:
    print('  （无差异）')

print('=== 边差异 ===')
ea = sorted((e['source'], e['target']) for e in online.get('edges', []))
eb = sorted((e['source'], e['target']) for e in local.get('edges', []))
if ea == eb:
    print('  （无差异）')
else:
    print('  仅线上: %s' % [x for x in ea if x not in eb])
    print('  仅本地: %s' % [x for x in eb if x not in ea])
