#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReadPal · 统一 LLM 节点的「生成 / 校验」两类模型策略（单一真源）。

为什么要有这个文件
------------------
各建图脚本（build_graphA/B/main、dify_build_graphs、build_graphC）各自硬编码过
provider/model 字面量，历史上因此踩过两次坑：

  1. 2026-09-21 切硅基流动：图 A（自建节点）一次通过，图 B 仍 402 ——
     因为图 B 里 nodeTitle/nodeQuiz/nodeGenX 是 `carry_node()` 从 GEN 图**整段拷贝**的，
     带着 GEN 当时的字面量，**完全绕过本文件的常量**。
  2. 换模型时按「模型名里有没有 'pro'」来判定档位。一旦生成节点换成名字里没有 pro 的模型
     （如 gpt-5.6-luna），它会被误判成 flash 档 → 被改回 deepseek-v4-flash，**静默回退**。

所以本文件只做三件事，且**全部靠显式表，不做名字猜测**：
  · CHANNELS      渠道定义（provider / 默认参数 / 思考参数键名）
  · GEN_NODE_IDS  哪些节点属于「内容生成」 → POLICY['gen']
  · CHECK_NODE_IDS 哪些节点属于「校验/辅助」 → POLICY['check']
遇到不认识的 LLM 节点 id **直接报错**，绝不静默跳过（Bryan 最反感静默失败）。

改模型档位只改 POLICY 一处；改节点归类只改下面两张表。
"""
from __future__ import annotations

# ── 渠道定义 ────────────────────────────────────────────────────────────────
# completion_params 只是「新建节点时的默认值」；对已有节点我们**保留节点自带的
# temperature / max_tokens**（它们是逐档调过的），只做渠道兼容性归一。
CHANNELS = {
    'luna': {
        'provider': 'langgenius/opencode_go/opencode_go',
        'name': 'gpt-5.6-luna',
        'mode': 'chat',
        'completion_params': {'max_tokens': 8192},
        'think_key': None,          # 该渠道没有思考开关，写进去会被静默丢弃
        # 上游明确不支持、会被插件剥离的参数 —— 留着只会误导后人
        'drop_params': ('temperature', 'top_p', 'thinking', 'enable_thinking'),
    },
    'deepseek_pro': {
        'provider': 'langgenius/deepseek/deepseek',
        'name': 'deepseek-v4-pro',
        'mode': 'chat',
        'completion_params': {'temperature': 0.45, 'max_tokens': 6000, 'thinking': False},
        'think_key': 'thinking',
        'drop_params': (),
    },
    'deepseek_flash': {
        'provider': 'langgenius/deepseek/deepseek',
        'name': 'deepseek-v4-flash',
        'mode': 'chat',
        'completion_params': {'temperature': 0.1, 'max_tokens': 2400, 'thinking': False},
        'think_key': 'thinking',
        'drop_params': (),
    },
}

# 🔴 luna 是**推理型**模型：出正文前先花 2000–3000 token 思考，且该渠道**没有关闭思考的参数**
#    （参数规则只有 temperature / top_p / max_tokens / extra_headers，前两个上游还直接忽略）。
# 实测（2026-09-23，MAIN 图，母稿 517 词）：
#   A1 max_tokens=2000 → 完成 2000（撞满）→ text 为空；A2 max_tokens=3000 → 同样撞满为空；
#   B1=4500 → 3546 正常、B2=6000 → 4275 正常。
#   ⇒ 沿用 deepseek 那套逐档的小额度（2000/3000）会把小档正文挤空。
# ⚠️ 且这是**静默失败**：finish_reason 仍为 `stop`、节点仍报 succeeded、输出为空字符串，
#    不可依赖 finish_reason 判别截断（只能靠下游校验/段数信号发现）。
# ⇒ luna 档必须给足上限。只设天花板、按实际用量计费，所以给宽不浪费钱。
LUNA_MAX_TOKENS = {
    'nodeGenA1': 8192,
    'nodeGenA2': 8192,
    'nodeGenB1': 10240,
    'nodeGenB2p': 12288,
    'nodeQuiz': 16384,
    'nodeCompress': 12288,
    'nodeSimplify': 12288,
    'nodeSimplify2': 12288,
    'nodeSegment': 12288,
}

# ── 节点归类（显式 id 表，唯一真源）────────────────────────────────────────
# 内容生成：四档正文、练习题、按实测压缩、母稿提炼/产出/分段
GEN_NODE_IDS = {
    'nodeGenA1', 'nodeGenA2', 'nodeGenB1', 'nodeGenB2p',   # 四档正文
    'nodeQuiz',                                            # 练习题
    'nodeCompress',                                        # 图B 按实测压缩
    'nodeSimplify', 'nodeSimplify2', 'nodeSegment',        # 图A 母稿预处理
}
# 校验 / 辅助：统一标题、大意复核、逐段大意核对、事实抽取、敏感排查、分级
CHECK_NODE_IDS = {
    'nodeTitle', 'nodeGistCheck', 'nodeSemCheck',
    'nodeFact', 'nodeCheck', 'nodeGrade',
}

# 当前策略：生成 → luna；校验 → deepseek-v4-flash
POLICY = {'gen': 'luna', 'check': 'deepseek_flash'}


def classify(node_id: str) -> str:
    """返回 'gen' / 'check'；未知 id 抛错（**不静默**）。"""
    if node_id in GEN_NODE_IDS:
        return 'gen'
    if node_id in CHECK_NODE_IDS:
        return 'check'
    raise KeyError(
        '未知 LLM 节点 id：%s —— 请在本文件 GEN_NODE_IDS / CHECK_NODE_IDS 里显式归类，'
        '不要让它默默走默认档' % node_id)


def channel_of(node_id: str) -> dict:
    return CHANNELS[POLICY[classify(node_id)]]


def retarget_model(model: dict, node_id: str) -> tuple[bool, str]:
    """把 model 指到该节点对应的渠道。

    返回 (是否变化, 说明)。deepseek 档**保留节点自带的 temperature / max_tokens**
    （逐档调过）；luna 档则按 LUNA_MAX_TOKENS 抬上限、并清掉上游不认的参数。
    """
    ch = channel_of(node_id)
    before = '%s / %s (max_tok=%s)' % (model.get('provider'), model.get('name'),
                                       (model.get('completion_params') or {}).get('max_tokens'))
    changed = False
    if model.get('provider') != ch['provider'] or model.get('name') != ch['name']:
        model['provider'] = ch['provider']
        model['name'] = ch['name']
        changed = True
    if model.get('mode') != ch['mode']:
        model['mode'] = ch['mode']
        changed = True

    cp = model.get('completion_params')
    if isinstance(cp, dict):
        # 该渠道不支持的参数：清掉（例如 luna 上游忽略 temperature）
        for k in ch.get('drop_params', ()):
            if k in cp:
                cp.pop(k)
                changed = True
        # 思考参数键名归一（deepseek 官方是 thinking）
        want = ch.get('think_key')
        for k in ('thinking', 'enable_thinking'):
            if k == want:
                continue
            if k in cp:
                cp.pop(k)
                changed = True
        if want and want not in cp:
            cp[want] = False
            changed = True
        # luna 是推理型：必须给足预算（详见 LUNA_MAX_TOKENS 注释）
        if ch is CHANNELS['luna'] and node_id in LUNA_MAX_TOKENS:
            target = LUNA_MAX_TOKENS[node_id]
            if cp.get('max_tokens') != target:
                cp['max_tokens'] = target
                changed = True

    after = '%s / %s (max_tok=%s)' % (model.get('provider'), model.get('name'),
                                      (model.get('completion_params') or {}).get('max_tokens'))
    return changed, ('%s → %s' % (before, after)) if changed else ('%s（未变）' % after)


def apply_policy(graph, only=None):
    """按 POLICY 就地改写 graph 里所有 LLM 节点的 model。

    ⚠️ 各建图脚本**必须在 json.dump 之前**调它一次：脚本里那些
    `'model': MODEL_PRO` 字面量是历史遗留，容易被拷贝/归一化绕过
    （图 B 的 normalize_models、main 的节点搬运都出过这个问题）。
    放在落盘前统一过一遍，才是「单一真源」。

    返回 [(node_id, kind, 说明)]；遇到未归类 id 会抛 KeyError。
    """
    rows = []
    for n in (graph.get('nodes') or []):
        d = n.get('data') or {}
        if d.get('type') != 'llm':
            continue
        kind = classify(n['id'])
        if only and kind != only:
            continue
        _, desc = retarget_model(d.setdefault('model', {}), n['id'])
        rows.append((n['id'], kind, desc))
    return rows


def verify_policy(graph, only=None):
    """落盘前自检：返回问题列表（空 = 全部到位）。有问题就**别落盘**。"""
    bad = []
    for n in (graph.get('nodes') or []):
        d = n.get('data') or {}
        if d.get('type') != 'llm':
            continue
        kind = classify(n['id'])
        if only and kind != only:
            continue
        ch = CHANNELS[POLICY[kind]]
        m = d.get('model') or {}
        if m.get('provider') != ch['provider'] or m.get('name') != ch['name']:
            bad.append('%s 应为 %s/%s，实为 %s/%s' % (
                n['id'], ch['provider'], ch['name'], m.get('provider'), m.get('name')))
        cp = m.get('completion_params') or {}
        for k in ch.get('drop_params', ()):
            if k in cp:
                bad.append('%s 残留上游不认的参数 %s' % (n['id'], k))
        want = ch.get('think_key')
        if want and cp.get(want) is not False:
            bad.append('%s 缺少 %s=false（会被平台默认开着思考跑，慢且易超时）' % (n['id'], want))
        if want is None and ('thinking' in cp or 'enable_thinking' in cp):
            bad.append('%s 带着别家渠道的思考参数（会被静默丢弃）' % n['id'])
        if ch is CHANNELS['luna']:
            want = LUNA_MAX_TOKENS.get(n['id'])
            if want and cp.get('max_tokens') != want:
                bad.append('%s max_tokens=%s ≠ %s（luna 是推理型，预算不足会静默截空）' % (
                    n['id'], cp.get('max_tokens'), want))
    return bad


if __name__ == '__main__':
    print('渠道：')
    for k, v in CHANNELS.items():
        print('  %-15s %s / %s  params=%s' % (k, v['provider'], v['name'], v['completion_params']))
    print('策略：生成(%d 类) → %s ；校验(%d 类) → %s' % (
        len(GEN_NODE_IDS), POLICY['gen'], len(CHECK_NODE_IDS), POLICY['check']))
    print('  生成：%s' % ', '.join(sorted(GEN_NODE_IDS)))
    print('  校验：%s' % ', '.join(sorted(CHECK_NODE_IDS)))
