#!/usr/bin/env python3
"""
ReadPal · 四档字数下调（2026-09-21）

Bryan 要求：字数全部降一档，其他标准（蓝思 / 句长 / 语篇层 / 语法层）不变。

【为什么不是简单地改几个数字】
现行「全文区间 ≈ 12 × 每段词数」，两个数字是绑在一起的；只改全文会与
「每段词数 × 12 段」打架，出现物理不可达的区间。所以本次**成对下调**。
另外三处经计算做了技术修正（详见 docs/local-notes/40）。

| 档   | 目标 | 硬区间    | 每段词数   | 每段句数        | 备注 |
|------|------|-----------|------------|-----------------|------|
| A1-  | 150  | 135–165   | 12–20 → 11–14 | 2 → **1–2**（放宽） | 「每段必须 2 句」下最低只能到 168 词，达不到 140–150，Bryan 拍板放宽句数 |
| A2   | 240  | 240–265   | 20–32 → 20–22 | 2（不变）        | 下限 240 = 2 句 × 10 词 × 12 段，数学下限 |
| B1   | 380  | 342–418   | 32–46 → 28–35 | 2–3（不变）      | 原下限 32×12=384 已超新上限 380，必须同步降每段词数 |
| B2+  | 550  | 495–605   | 46–67 → 41–50 | 3–4 → **2–3**    | 纯 2 句会把上限锁死在 576，装不下 605 |

改动面（4 处，缺一不可）：
  GEN   nodeGenA1/A2/B1/B2p  —— 规格块 + 自查块（同一数字各出现 2–3 次）
  GEN   nodeValidate         —— [词数下限, 上限, 蓝思下限, 上限, 句长下限, 上限]
  FACT  nodeGrade            —— 4 档速查表
  frontend/index.html        —— SPECS 的 len 字段（中英各 4 处，用 atomic_replace 改）

用法：
    python3 tools/patch_word_count.py            # 实际写入
    python3 tools/patch_word_count.py --check    # 只报告命中，不写盘

退出码：0 = 成功；1 = 断言失败；2 = 用法错误
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GEN_PATH = REPO / 'dify_graphs' / 'gen.new.json'
FACT_PATH = REPO / 'dify_graphs' / 'fact.new.json'

# ── GEN：4 个生成节点各自的替换（old, new, expect）──────────────────
NODE_OPS = {
    'nodeGenA1': [
        ('目标 195 词', '目标 150 词', 2),
        ('150–240', '128–172', 3),
        # 第五轮：Bryan 明确「可以每段 1-2 句、句子长度也可以短一些，不用每段 2 句」。
        # ⇒ 句长下限 7 → 6，让 12 × 2 × 6 = 144 成为真正可达的下限（正好卡住靶心 150）。
        ('平均句长 7–9 词', '平均句长 6–9 词', 2),
        ('每段约 12–20 词', '每段约 11–14 词', 1),
        # 🔴 所有项都必须「锚点 → **最终**文案」一步到位。
        #    踩过两次坑：任何「A→B 再由 B→C」的链条，第二次跑时 A 项的 new 已被 B 项消费，
        #    `new in txt` 判定失效 → count(old)=0 → 抛错，幂等性直接失效（第三次跑才暴露）。
        ('（约 2 句，平均句长约 8 词）',
         '（**每段 1–2 句** —— 不需要每段都写 2 句，句子也可以短一些；全篇约 150 词）', 1),
        ('【篇幅】每段 1–2 句；全文 128–172 词',
         '【篇幅】每段 **1–2 句**（**不要求每段都写 2 句**，信息量少的段写 1 句即可）；'
         '每句 6–9 词 —— 全篇约 **150 词**（硬区间 128–172）', 1),
    ],
    'nodeGenA2': [
        ('目标 310 词', '目标 240 词', 2),
        ('240–380', '204–276', 3),
        ('每段约 20–32 词', '每段约 20–22 词', 1),
        # 20–22 词 ÷ 2 句 = 10–11 词/句，原文「约 12 词」会自相矛盾；
        # 首轮实测 A2 = 275 词（超上限 265，2 句 × 11.5 词），把句长一并引导到区间下半段。
        # ⚠️ 必须写成**一步**替换（12 → 10–11）。若拆成两步（12→11 再 11→10–11），
        #    第二步会吃掉第一步的锚点，第二次跑时 count=0 直接抛错，幂等性失效。
        ('（约 2 句，平均句长约 12 词）', '（约 2 句，平均句长约 10–11 词）', 1),
    ],
    'nodeGenB1': [
        ('目标 465 词', '目标 380 词', 2),
        ('380–550', '323–437', 3),
        ('每段约 32–46 词', '每段约 28–35 词', 1),
        # 28–35 词装不下 3 句（3×16=48），改为 2 句（2×16=32）
        # 第五轮实测 442（超上限 5 词、1.1%）：模型仍按「每段 2–3 句」取了 2.5 句。
        # ⇒ 与 B2+ 同样处理：把「2 句为主」写进【篇幅】，并把算式显式给出来。
        ('（约 3 句，平均句长约 16 词）',
         '（**全篇约 24 句** × 每句约 15–16 词 ≈ 380 词；**不要为了撑篇幅写 3 句**）', 1),
        ('每段 2–3 句；全文 323–437 词', '每段 **2 句为主**；全文 323–437 词', 1),
    ],
    'nodeGenB2p': [
        ('目标 675 词', '目标 550 词', 2),
        ('550–800', '468–632', 3),
        ('每段约 46–67 词', '每段约 41–50 词', 1),
        ('每段 3–4 句；全文', '每段 **2 句为主**；全文', 1),
        # 第四轮：三轮实测 455（偏低 95）—— 说「不要写 3 句」模型就全写 2 句 ×19 词 = 456。
        # 目标 550 ⇒ 全篇约 26 句 × 每句约 21 词，且句长要落在 18–24 的**中部**。
        ('（约 3 句，平均句长约 21 词）',
         '（**全篇约 26 句** × 每句约 21 词 ≈ 550 词；句长要落在 18–24 的**中部**，不要只写 18–19 词）', 1),
    ],
}

# ── GEN：4 档共有文案 ──────────────────────────────────────────────
# ① A2 的区间 240–265 中点是 252.5、目标写 240，「靠近区间中点」不再等于「靠近目标值」；
#    改成「靠近目标值」对四档都成立（原 150–240 的中点恰好 = 目标 195）。
# ② A1- 放宽为 1–2 句，必须把「低档每段就是 2 句」拆成分档表述，否则与新区间打架。
SPLIT_OLD = ('**低档（A1- / A2）每段就是 2 句**：不得合成 1 句长句，也不得只写 1 句 —— '
             '句数不足会同时造成篇幅偏短与句长超标，两项都判不合格。')
SPLIT_NEW = ('**低档句数**：**A2 每段就是 2 句**—— 不得合成 1 句长句，也不得只写 1 句'
             '（句数不足会同时造成篇幅偏短与句长超标，两项都判不合格）；'
             '**A1- 每段 1–2 句** —— **不要求每段都写 2 句**，信息量少的段写 1 句即可；'
             '句子也可以短一些（6–9 词），但每句不得少于 4 词。')

COMMON_OPS = [
    ('宁可靠近区间中点，也不要低于下限', '宁可靠近目标值，也不要低于下限', 1),
    (SPLIT_OLD, SPLIT_NEW, 1),
]

# ── GEN：nodeValidate 的 [词数下限, 上限, 蓝思下限, 上限, 句长下限, 上限] ──
VALIDATE_OPS = [
    ('[150, 240', '[128, 172', 1),
    ('[128, 172, -1000, 400, 7, 9]', '[128, 172, -1000, 400, 6, 9]', 1),
    ('[240, 380', '[204, 276', 1),
    ('[380, 550', '[323, 437', 1),
    ('[550, 800', '[468, 632', 1),
]

# ── 「每段词数优先于每段句数」（2026-09-21 第二轮）────────────────────
# 首轮实测教训：模型是按「每段句数 × 句长」铺段的，而且**句数一律取区间上限** ——
#   A1- 2 句 · A2 2 句 · B1 3 句 · B2+ 3 句
# → 全篇系统性偏高 10–23%：实测 185 / 275 / 455 / 601，目标 150 / 240 / 380 / 550，
#   四档里只有 B2+ 侥幸压线。
# 修法：**不动「每段句数」标准**，改为声明「每段词数优先」，
#   让模型自己从词数倒推出该写几句（B1 倒推出 2 句、A1- 倒推出 1–2 句混合）。
PRIORITY_OLD = ('宁可靠近目标值，也不要低于下限。\n'
                '② **每段句数**：按写作标尺给出的「约 M 句」写足。')

PER_PARA = {'nodeGenA1': (11, 14), 'nodeGenA2': (20, 22), 'nodeGenB1': (28, 35), 'nodeGenB2p': (41, 50)}


def priority_new(lo, hi, extra=''):
    return ('宁可靠近目标值，也不要低于下限。\n'
            '   **每段词数优先于每段句数**：先保证每段落在写作标尺的「每段约 %d–%d 词」内，'
            '再决定该段写几句；两者不能同时满足时**以词数为准** —— '
            '宁可让某段句数低于标尺，也不要把全篇撑出上限。\n'
            '%s'
            '② **每段句数**：按写作标尺给出的「约 M 句」写足。' % (lo, hi, extra))


A1_EXTRA = ('   A1- 特别注意：**不需要每段都写 2 句** —— 12 段里写 1 句的段落可以占到一半；'
            '句子也可以写得短一些（6–9 词）。全篇约 150 词（硬区间 128–172）。\n')

# ── FACT：nodeGrade 的 4 档速查表 ─────────────────────────────────
GRADE_OPS = [
    ('A1 ｜150–240', 'A1 ｜128–172', 1),
    ('128–172 ｜BR–400L   ｜7–9', '128–172 ｜BR–400L   ｜6–9', 1),
    ('A2 ｜240–380', 'A2 ｜204–276', 1),
    ('B1 ｜380–550', 'B1 ｜323–437', 1),
    ('B2 ｜550–800', 'B2 ｜468–632', 1),
]


def get(graph, nid):
    for n in graph['nodes']:
        if n['id'] == nid:
            return n
    raise KeyError('节点不存在：' + nid)


def node_text(node):
    """取节点可改写文本的载体（prompt_template 首段 或 code）"""
    d = node['data']
    if d.get('type') == 'code':
        return 'code', d
    return 'text', d


def sub_once(txt, old, new, label, report, dry):
    """🔴 幂等判据用 `new in txt`，并且必须排除「新文案是旧文案子串」的反向陷阱。"""
    if new in txt:
        if new != old and old not in txt:
            report.append('  · %-52s 已是新文案，跳过' % label)
            return txt, False
        # new 是 old 的子串且 old 仍在 —— 说明是「以旧文案开头追加澄清句」的写法，
        # 此时 new in txt 恒真，不能据此判定已改过，必须按命中数正常替换。
    n = txt.count(old)
    if n != 1:
        raise RuntimeError('✗ 锚点命中 %d 次（应为 1）：%s\n---\n%s' % (n, label, old[:180]))
    report.append('  ✓ %-52s 1 处' % label)
    if dry:
        return txt, True
    return txt.replace(old, new, 1), True


def apply_ops(txt, ops, tag, report, dry):
    for old, new, exp in ops:
        n = txt.count(old)
        if new in txt and old not in txt:
            report.append('  · %-52s 已是新文案，跳过' % (tag + ' ' + old[:24]))
            continue
        if n != exp:
            raise RuntimeError('✗ %s 锚点「%s」命中 %d 次（应为 %d）' % (tag, old[:40], n, exp))
        report.append('  ✓ %-52s %d 处' % (tag + ' ' + old[:26], n))
        txt = txt.replace(old, new)
    return txt


def patch_gen(data, report, dry):
    """注意：dry 只决定「是否落盘」，不决定「是否替换」。
    替换始终在内存对象上完成 —— 否则 --check 的回读核验读到的是未改的旧值，永远全红。"""
    stats = {}
    for nid, ops in NODE_OPS.items():
        nd = get(data['graph'], nid)
        t = nd['data']['prompt_template'][0]['text']
        t2 = apply_ops(t, ops, nid, report, dry)
        t2 = apply_ops(t2, COMMON_OPS, nid, report, dry)
        lo, hi = PER_PARA[nid]
        extra = A1_EXTRA if nid == 'nodeGenA1' else ''
        t2 = apply_ops(t2, [(PRIORITY_OLD, priority_new(lo, hi, extra), 1)],
                       nid + ' 词数优先', report, dry)
        nd['data']['prompt_template'][0]['text'] = t2
        stats[nid] = len(ops) + len(COMMON_OPS) + 1
    va = get(data['graph'], 'nodeValidate')
    va['data']['code'] = apply_ops(va['data']['code'], VALIDATE_OPS, 'nodeValidate', report, dry)
    stats['nodeValidate'] = len(VALIDATE_OPS)
    return stats


def patch_fact(data, report, dry):
    nd = get(data['graph'], 'nodeGrade')
    t = nd['data']['prompt_template'][0]['text']
    nd['data']['prompt_template'][0]['text'] = apply_ops(t, GRADE_OPS, 'nodeGrade', report, dry)
    return {'nodeGrade': len(GRADE_OPS)}


def verify(gen, fact, report):
    """回读核验：断言目标值确实生效、旧值已绝迹"""
    checks = [
        ('GEN A1 目标 150', '目标 150 词' in get(gen['graph'], 'nodeGenA1')['data']['prompt_template'][0]['text']),
        ('GEN A1 区间 128–172', '128–172' in get(gen['graph'], 'nodeGenA1')['data']['prompt_template'][0]['text']),
        ('GEN A1 句长放宽 6–9', '平均句长 6–9 词' in get(gen['graph'], 'nodeGenA1')['data']['prompt_template'][0]['text']),
        ('GEN A1 每段 11–14 词', '每段约 11–14 词' in get(gen['graph'], 'nodeGenA1')['data']['prompt_template'][0]['text']),
        ('GEN A2 目标 240', '目标 240 词' in get(gen['graph'], 'nodeGenA2')['data']['prompt_template'][0]['text']),
        ('GEN A2 区间 204–276', '204–276' in get(gen['graph'], 'nodeGenA2')['data']['prompt_template'][0]['text']),
        ('GEN B1 目标 380', '目标 380 词' in get(gen['graph'], 'nodeGenB1')['data']['prompt_template'][0]['text']),
        ('GEN B1 区间 323–437', '323–437' in get(gen['graph'], 'nodeGenB1')['data']['prompt_template'][0]['text']),
        ('GEN B1 篇幅「2 句为主」', '每段 **2 句为主**' in get(gen['graph'], 'nodeGenB1')['data']['prompt_template'][0]['text']),
        ('GEN B1 算式提示（约 24 句 ≈ 380 词）', '**全篇约 24 句**' in get(gen['graph'], 'nodeGenB1')['data']['prompt_template'][0]['text']),
        ('GEN B2+ 目标 550', '目标 550 词' in get(gen['graph'], 'nodeGenB2p')['data']['prompt_template'][0]['text']),
        ('GEN B2+ 区间 468–632', '468–632' in get(gen['graph'], 'nodeGenB2p')['data']['prompt_template'][0]['text']),
        ('GEN B2+ 篇幅「2 句为主」', '每段 **2 句为主**' in get(gen['graph'], 'nodeGenB2p')['data']['prompt_template'][0]['text']),
        ('A1- / A2 仍保「每段就是 2 句」约束（A2）', '**A2 每段就是 2 句**' in get(gen['graph'], 'nodeGenA1')['data']['prompt_template'][0]['text']),
    ]
    # 「每段词数优先」规则必须四档都在（首轮实测就是缺了它导致全篇偏高）
    for nid in ('nodeGenA1', 'nodeGenA2', 'nodeGenB1', 'nodeGenB2p'):
        checks.append(('词数优先规则 · %s' % nid,
                       '**每段词数优先于每段句数**' in get(gen['graph'], nid)['data']['prompt_template'][0]['text']))
    checks.append(('A1- 句数放宽提示', '不需要每段都写 2 句' in get(gen['graph'], 'nodeGenA1')['data']['prompt_template'][0]['text']))
    checks.append(('A2 句长引导 10–11', '平均句长约 10–11 词' in get(gen['graph'], 'nodeGenA2')['data']['prompt_template'][0]['text']))
    checks.append(('A1- 篇幅「不要求每段都写 2 句」', '**不要求每段都写 2 句**' in get(gen['graph'], 'nodeGenA1')['data']['prompt_template'][0]['text']))
    checks.append(('A1- 低档句数「每段 1–2 句」', '**A1- 每段 1–2 句**' in get(gen['graph'], 'nodeGenA1')['data']['prompt_template'][0]['text']))
    checks.append(('B2+ 篇幅「2 句为主」', '每段 **2 句为主**' in get(gen['graph'], 'nodeGenB2p')['data']['prompt_template'][0]['text']))
    checks.append(('B2+ 算式提示（约 26 句 ≈ 550 词）', '**全篇约 26 句**' in get(gen['graph'], 'nodeGenB2p')['data']['prompt_template'][0]['text']))
    vcode = get(gen['graph'], 'nodeValidate')['data']['code']
    for key, lo in (('A1', 128), ('A2', 204), ('B1', 323), ('B2', 468)):
        checks.append(('校验层 %s 下限 %d' % (key, lo), '[%d,' % lo in vcode))
    gt = get(fact['graph'], 'nodeGrade')['data']['prompt_template'][0]['text']
    checks.append(('FACT 速查表 A1 句长 6–9', '｜BR–400L   ｜6–9' in gt))
    for key, rng in (('A1', '128–172'), ('A2', '204–276'), ('B1', '323–437'), ('B2', '468–632')):
        checks.append(('FACT 速查表 %s %s' % (key, rng), rng in gt))
    # 旧值必须绝迹
    old_vals = ['150–240', '240–380', '380–550', '550–800',
                '目标 195 词', '目标 310 词', '目标 465 词', '目标 675 词']
    for nid in ('nodeGenA1', 'nodeGenA2', 'nodeGenB1', 'nodeGenB2p'):
        t = get(gen['graph'], nid)['data']['prompt_template'][0]['text']
        left = [o for o in old_vals if o in t]
        checks.append(('旧值已绝迹 · %s' % nid, not left))
    report.append('')
    report.append('  ── 回读核验 ──')
    ok = True
    for name, passed in checks:
        report.append('   %s %s' % ('✓' if passed else '✗', name))
        ok = ok and passed
    return ok, len(checks)


def main():
    dry = '--check' in sys.argv
    report = []
    report.append('ReadPal · 四档字数下调' + ('【--check 只报告，不写盘】' if dry else ''))
    gen = json.loads(GEN_PATH.read_text(encoding='utf-8'))
    fact = json.loads(FACT_PATH.read_text(encoding='utf-8'))
    try:
        sg = patch_gen(gen, report, dry)
        sf = patch_fact(fact, report, dry)
    except RuntimeError as e:
        print('\n'.join(report))
        print('\n' + str(e))
        return 1
    ok, nchk = verify(gen, fact, report)
    print('\n'.join(report))
    if dry:
        print('\n[--check] 未写盘。核验 %d 项：%s' % (nchk, '全绿' if ok else '有失败'))
        return 0 if ok else 1
    GEN_PATH.write_text(json.dumps(gen, ensure_ascii=False, indent=2), encoding='utf-8')
    FACT_PATH.write_text(json.dumps(fact, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\n已写入 %s' % GEN_PATH.name)
    print('已写入 %s' % FACT_PATH.name)
    print('核验 %d 项：%s' % (nchk, '全绿' if ok else '⚠ 有失败'))
    print('下一步：python3 tools/build_main_graph.py 重拼 MAIN，再推图发布')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
