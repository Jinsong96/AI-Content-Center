#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ReadPal · 把「完整工作流」(MAIN App) 重建为 12 子档

════════════════════════════════════════════════════════════════════
单真源原则（这是本脚本存在的全部理由）
════════════════════════════════════════════════════════════════════
    MAIN(完整工作流) = FACT(12档) 的抽取链路  ⊕  GEN(12档) 的生成链路

**不新增任何第二套提示词、不复制任何标准**。只做三件事：
    1) 节点搬运：从 fact.new.json / gen.new.json 里按 id 取节点
    2) 变量改写：把 GEN 侧对 `nodeStart.*` 的引用改到 `nodeClean.*`
       （因为 MAIN 没有 GEN 那种「外部传入 facts」的入口，facts 由链路自己抽出来）
    3) 边重连：把生成链路挂在敏感分流闸门的 false 分支后面

这样三个 App（MAIN / FACT / GEN）的 12 档标准永远只有一份，
改提示词只需要改 fact/gen 的生成器，重跑本脚本即可。

════════════════════════════════════════════════════════════════════
为什么不能直接照抄 GEN 的边
════════════════════════════════════════════════════════════════════
GEN 里是 `nodeClean → nodeTitle` **直连**（GEN 没有敏感闸门）。
如果原样搬到 MAIN，敏感内容会**绕过闸门照样生成**。
所以 MAIN 里必须走：nodeClean → nodeGate --false--> nodeStyle → nodeTitle。
（nodeStart → nodeStyle 这条直连边保留，只为让 nodeStyle 能取到 `nodeStart.style`。）

════════════════════════════════════════════════════════════════════
用法
════════════════════════════════════════════════════════════════════
    python3 tools/build_main_graph.py            # 生成 + 静态校验
    python3 tools/build_main_graph.py --check    # 只校验，不写文件

输出：dify_graphs/main.new.json
     （用 tools/dify_push_graph.mjs 推送到 Dify draft）

数据来源：
    dify_graphs/fact.new.json   事实抽取链路（12 档真源）
    dify_graphs/gen.new.json    生成链路（12 档真源）
    dify_graphs/main.graph.json MAIN 改造前的原始备份（仅取 app 级 features，
                                以及用于「改造前后差异」自检）

退出码：0 校验通过；1 校验失败
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
G_DIR = os.path.abspath(os.environ.get('DIFY_GRAPH_DIR') or os.path.join(_HERE, '..', 'dify_graphs'))

FACT_IN = os.path.join(G_DIR, 'fact.new.json')
GEN_IN = os.path.join(G_DIR, 'gen.new.json')
MAIN_BAK = os.path.join(G_DIR, 'main.graph.json')
OUT = os.path.join(G_DIR, 'main.new.json')

# ── 节点分配表：哪个节点从哪个图取 ────────────────────────────────
FROM_FACT = [
    'nodeStart',      # 入口（含 12 档 level 下拉选项）
    'nodeFact',       # ① 事实抽取
    'nodeQRule',      # KB 敏感规则检索词（code，输出固定中文检索意图）
    'nodeKBSens',     # KB 敏感规则检索
    'nodeCheck',      # ② 敏感排查
    'nodeQGrade',     # KB 分级标准检索词
    'nodeKBGrade',    # KB 分级标准检索
    'nodeGrade',      # ③ 分级（12 子档）
    'nodeClean',      # ③+ 清洗解析（FACT 版：解析 3 个 LLM 输出，输出 12 个字段）
    'nodeGate',       # 敏感分流（if-else）
    'nodeExcluded',   # 结束（敏感排除）
]

FROM_GEN = [
    'nodeStyle',      # ⑧ 写作风格映射
    'nodeTitle',      # ④-0 统一标题
    'nodeGenA1',      # ④-A1 生成（A1.1 / A1.2 / A1.3）
    'nodeGenA2',      # ④-A2 生成（A2.1 / A2.2 / A2.3）
    'nodeGenB1',      # ④-B1 生成（B1.1 / B1.2 / B1.3）
    'nodeGenB2p',     # ④-B2+ 生成（B2+.1 / B2+.2 / B2+.3）
    'nodeAgg',        # ⑤ 聚合+身份记录
    'nodeQuiz',       # ⑥ 练习题生成（12 档 × 3 题）
    'nodeValidate',   # ⑦ 8 项校验 × 12 档
    'nodeEnd',        # 结束
]

# ── 变量改写：GEN 里从 nodeStart 取、MAIN 里必须从 nodeClean 取 ──
# key = 变量名，value = 新来源节点 id
REWIRE = {
    'facts_raw':  'nodeClean',   # GEN 的 nodeStart.facts_raw → MAIN 的 nodeClean.facts_raw
    'summary':    'nodeClean',
    'facts_text': 'nodeClean',
    'angle':      'nodeClean',
}
# 注意：level / style 不改写 —— MAIN 的 nodeStart 本来就有这两个变量。

# ── 新图的边（source, target, sourceHandle）─────────────────────
EDGES = [
    # 抽取链路（与 FACT 完全一致）
    ('nodeStart', 'nodeFact', 'source'),
    ('nodeFact', 'nodeQRule', 'source'),
    ('nodeStart', 'nodeQRule', 'source'),     # KB 检索词节点需要 start 可达入边
    ('nodeQRule', 'nodeKBSens', 'source'),
    ('nodeKBSens', 'nodeCheck', 'source'),
    ('nodeCheck', 'nodeQGrade', 'source'),
    ('nodeStart', 'nodeQGrade', 'source'),    # 同上
    ('nodeQGrade', 'nodeKBGrade', 'source'),
    ('nodeKBGrade', 'nodeGrade', 'source'),
    ('nodeGrade', 'nodeClean', 'source'),
    ('nodeClean', 'nodeGate', 'source'),
    ('nodeGate', 'nodeExcluded', 'true'),     # 敏感 → 直接结束
    # 生成链路：必须挂在闸门 false 分支后面（不能像 GEN 那样从 nodeClean 直连）
    ('nodeGate', 'nodeStyle', 'false'),
    ('nodeStart', 'nodeStyle', 'source'),     # 让 nodeStyle 能取到 nodeStart.style
    ('nodeStyle', 'nodeTitle', 'source'),
    ('nodeTitle', 'nodeGenA1', 'source'),
    ('nodeTitle', 'nodeGenA2', 'source'),
    ('nodeTitle', 'nodeGenB1', 'source'),
    ('nodeTitle', 'nodeGenB2p', 'source'),
    ('nodeGenA1', 'nodeAgg', 'source'),
    ('nodeGenA2', 'nodeAgg', 'source'),
    ('nodeGenB1', 'nodeAgg', 'source'),
    ('nodeGenB2p', 'nodeAgg', 'source'),
    ('nodeAgg', 'nodeQuiz', 'source'),
    ('nodeAgg', 'nodeValidate', 'source'),
    ('nodeQuiz', 'nodeEnd', 'source'),
    ('nodeValidate', 'nodeEnd', 'source'),
]

# GEN 侧生成链路整体下移，避免与抽取链路在画布上叠在一起
Y_OFFSET_GEN = 520.0

LLM_OUTPUTS = {'text', 'reasoning_content', 'usage', 'finish_reason'}
KB_OUTPUTS = {'result'}
LEVELS12 = ['A1.1', 'A1.2', 'A1.3', 'A2.1', 'A2.2', 'A2.3',
            'B1.1', 'B1.2', 'B1.3', 'B2+.1', 'B2+.2', 'B2+.3']
REQUIRED_MODEL = 'deepseek-ai/DeepSeek-V4-Flash'


def load_graph(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def rewire(data, node_id, log):
    """把 GEN 侧对 nodeStart.{facts_raw,summary,facts_text,angle} 的引用改到 nodeClean 上。
    覆盖三处：prompt/code 文本里的 {{#...#}}、variables[].value_selector、
    outputs[].value_selector、conditions[].variable_selector。
    返回改写次数。"""
    n = 0

    def fix_selector(sel):
        nonlocal n
        if (isinstance(sel, list) and len(sel) >= 2
                and sel[0] == 'nodeStart' and str(sel[1]) in REWIRE):
            n += 1
            return [REWIRE[str(sel[1])]] + list(sel[1:])
        return sel

    def walk(o):
        nonlocal n
        if isinstance(o, str):
            def repl(m):
                nonlocal n
                var = m.group(1)
                if var in REWIRE:
                    n += 1
                    return '{{#%s.%s#}}' % (REWIRE[var], var)
                return m.group(0)
            return re.sub(r'\{\{#nodeStart\.([A-Za-z0-9_]+)#\}\}', repl, o)
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                if k in ('value_selector', 'variable_selector', 'query_variable_selector'):
                    out[k] = fix_selector(v)
                else:
                    out[k] = walk(v)
            return out
        return o

    new = walk(data)
    if n:
        log.append('  %-14s 改写 %d 处 nodeStart.* → nodeClean.*' % (node_id, n))
    return new, n


def build():
    fact, gen, bak = load_graph(FACT_IN), load_graph(GEN_IN), load_graph(MAIN_BAK)
    fnodes = {n['id']: n for n in fact['graph']['nodes']}
    gnodes = {n['id']: n for n in gen['graph']['nodes']}

    missing = [i for i in FROM_FACT if i not in fnodes]
    if missing:
        sys.exit('✗ fact.new.json 缺少节点: %s' % missing)
    missing = [i for i in FROM_GEN if i not in gnodes]
    if missing:
        sys.exit('✗ gen.new.json 缺少节点: %s' % missing)

    nodes, log = [], []
    for i in FROM_FACT:
        nodes.append(json.loads(json.dumps(fnodes[i])))
    for i in FROM_GEN:
        nd = json.loads(json.dumps(gnodes[i]))
        nd['data'], _ = rewire(nd['data'], i, log)
        pos = nd.get('position') or {}
        nd['position'] = {'x': pos.get('x', 0), 'y': pos.get('y', 0) + Y_OFFSET_GEN}
        if nd.get('positionAbsolute'):
            nd['positionAbsolute'] = {'x': nd['positionAbsolute'].get('x', 0),
                                      'y': nd['positionAbsolute'].get('y', 0) + Y_OFFSET_GEN}
        nodes.append(nd)

    ntype = {n['id']: n['data'].get('type') for n in nodes}
    edges = []
    for src, tgt, handle in EDGES:
        edges.append({
            'id': 'e-%s-%s-%s' % (src, tgt, handle),
            'source': src, 'target': tgt, 'type': 'custom',
            'sourceHandle': handle, 'targetHandle': 'target', 'zIndex': 0,
            'data': {
                'sourceType': ntype[src], 'targetType': ntype[tgt],
                'sourceHandle': '1', 'targetHandle': '2',
                'isInIteration': False, 'isInLoop': False,
            },
        })

    out = {
        'graph': {'nodes': nodes, 'edges': edges, 'viewport': {'x': 0, 'y': 0, 'zoom': 0.7}},
        'features': bak.get('features') or {},
        'conversation_variables': bak.get('conversation_variables') or [],
    }
    return out, log, fnodes, gnodes, bak


# ══════════════════════ 静态校验 ══════════════════════
def node_outputs(n):
    t = n['data'].get('type')
    if t == 'start':
        return {v['variable'] for v in n['data'].get('variables') or []}
    if t == 'llm':
        return set(LLM_OUTPUTS)
    if t == 'code':
        return set((n['data'].get('outputs') or {}).keys())
    if t == 'knowledge-retrieval':
        return set(KB_OUTPUTS)
    return set()


def collect_refs(data):
    """收集节点里所有 (来源节点, 变量名) 引用"""
    out = set()

    def walk(o):
        if isinstance(o, str):
            for m in re.findall(r'\{\{#([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)#\}\}', o):
                out.add(m)
        elif isinstance(o, list):
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k in ('value_selector', 'variable_selector', 'query_variable_selector'):
                    if isinstance(v, list) and len(v) >= 2:
                        out.add((str(v[0]), str(v[1])))
                else:
                    walk(v)
    walk(data)
    return out


def check(g):
    nodes = {n['id']: n for n in g['nodes']}
    errs, warns = [], []

    # 1) 变量引用可解析 + 可达性
    adj = {}
    for e in g['edges']:
        adj.setdefault(e['source'], set()).add(e['target'])

    def reachable(src, dst):
        """BFS：src 能否沿边走到 dst（含 src == dst）。
        用独立的 visited 集合，避免菱形图上共享 seen 导致的假阴性。"""
        stack, seen = [src], set()
        while stack:
            cur = stack.pop()
            if cur == dst:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adj.get(cur, ()))
        return False

    refcount = 0
    for nid, n in nodes.items():
        for src, var in sorted(collect_refs(n['data'])):
            refcount += 1
            if src not in nodes:
                errs.append('%s 引用了不存在的节点 #%s.%s#' % (nid, src, var))
                continue
            outs = node_outputs(nodes[src])
            if outs and var not in outs:
                errs.append('%s 引用了 #%s.%s#，但 %s 没有该输出（可用: %s）'
                            % (nid, src, var, src, ','.join(sorted(outs)) or '无'))
                continue
            if not reachable(src, nid):
                errs.append('%s 引用 #%s.%s#，但 %s → %s 无可达路径'
                            % (nid, src, var, src, nid))

    # 2) 死节点（无入边且非 start）
    indeg = {i: 0 for i in nodes}
    for e in g['edges']:
        indeg[e['target']] = indeg.get(e['target'], 0) + 1
    for nid, d in indeg.items():
        if d == 0 and nodes[nid]['data'].get('type') != 'start':
            errs.append('节点 %s (%s) 无入边，永远不会执行'
                        % (nid, nodes[nid]['data'].get('title')))

    # 3) 全部节点从 start 可达
    for nid in nodes:
        if not reachable('nodeStart', nid):
            errs.append('节点 %s 从 start 不可达' % nid)

    # 4) 边两端存在
    for e in g['edges']:
        if e['source'] not in nodes or e['target'] not in nodes:
            errs.append('悬空边 %s → %s' % (e['source'], e['target']))

    # 5) 模型与思考开关
    llm = 0
    for nid, n in nodes.items():
        d = n['data']
        if d.get('type') != 'llm':
            continue
        llm += 1
        m = d.get('model') or {}
        if m.get('name') != REQUIRED_MODEL:
            errs.append('%s 模型应为 %s，实为 %s' % (nid, REQUIRED_MODEL, m.get('name')))
        if m.get('provider') != 'langgenius/siliconflow/siliconflow':
            errs.append('%s provider 应为硅基流动，实为 %s' % (nid, m.get('provider')))
        cp = m.get('completion_params') or {}
        if cp.get('enable_thinking') is not False:
            errs.append('%s 缺少 enable_thinking=false（会被平台默认开着思考跑）' % nid)
        if 'thinking' in cp:
            errs.append('%s 残留了错误的参数名 `thinking`（会被 Dify 静默丢弃）' % nid)

    # 6) 12 档下拉选项
    for nid, n in nodes.items():
        if n['data'].get('type') != 'start':
            continue
        for v in n['data'].get('variables') or []:
            if v.get('variable') == 'level':
                got = v.get('options') or []
                if got != LEVELS12:
                    errs.append('start.level 选项不是 12 档：%s' % got)

    # 7) 无遗留旧三档字样
    #    注意：「三档」本身是合法措辞（同一大档内的三个子档，如 A2.1/A2.2/A2.3），
    #    只拦真正表示「旧三档体系」的写法。
    flat = json.dumps(g, ensure_ascii=False).replace(' ', '')
    for bad in ('["A2","B1","B2"]', '三档生成', '旧三档', '档A2/A2'):
        if bad.replace(' ', '') in flat:
            errs.append('图里还有旧三档体系的痕迹：%s' % bad)

    # 8) 生成节点标题必须点明 12 子档
    want = {'nodeGenA1': 'A1.1', 'nodeGenA2': 'A2.1', 'nodeGenB1': 'B1.1', 'nodeGenB2p': 'B2+.1'}
    for nid, marker in want.items():
        if nid in nodes:
            t = nodes[nid]['data'].get('title') or ''
            if marker not in t:
                errs.append('%s 标题未标明子档范围（缺 %s）：%r' % (nid, marker, t))

    return errs, warns, refcount, llm


def main():
    out, log, fnodes, gnodes, bak = build()
    print('══ 拼装 ══')
    print('  取自 FACT : %s' % ', '.join(FROM_FACT))
    print('  取自 GEN  : %s' % ', '.join(FROM_GEN))
    print('  丢弃      : nodeGenAll（旧三档生成）、GEN 的 nodeClean（透传版，与 FACT 版同 id 冲突）')
    if log:
        print('  变量改写：')
        for l in log:
            print(l)
    else:
        print('  ⚠ 没有发生任何变量改写 —— GEN 侧居然不引用 nodeStart.*？请人工确认')

    g = out['graph']
    print('\n  节点 %d  边 %d' % (len(g['nodes']), len(g['edges'])))

    errs, warns, refcount, llm = check(g)
    print('\n══ 静态校验 ══')
    print('  变量引用 %d 处 / LLM 节点 %d 个' % (refcount, llm))
    for w in warns:
        print('  ⚠ ' + w)
    if errs:
        for e in errs:
            print('  ✗ ' + e)
        print('\n✗ 校验失败（%d 项），未写出文件' % len(errs))
        return 1
    print('  ✅ 全部通过：引用可解析、无死节点、全部从 start 可达、模型与思考开关正确、12 档选项完整')

    if '--check' in sys.argv:
        print('\n[--check] 仅校验，未写文件')
        return 0

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\n✓ 已写出 %s (%d bytes)' % (OUT, os.path.getsize(OUT)))
    print('  推送：node tools/dify_push_graph.mjs --app=466e1815-c5bb-4d50-8437-2fc4768dd4f0 --graph=dify_graphs/main.new.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
