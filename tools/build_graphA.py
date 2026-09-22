#!/usr/bin/env python3
"""
ReadPal · 图 A「母稿预处理」构建脚本（2026-09-21）

背景：授权母稿（BBC Learning English / 超级阅读力 / 大愚出版社等）向下改写前，
需要先把母稿处理成「可用的段落骨架」：可选精简 + 按内容自然分段。

⚠️ 本图是**新建 App 的空白草稿**，节点必须从零组装。
   节点/边的字段格式取自现有 GEN 图（顶层 type 与 data.type 同名；LLM 节点输出变量名是 `text`）。

App ID：d4e0905b-b8da-47f1-9d10-a1ca87bdc401

流水线（线性，先跑通再优化）：
  nodeStart → nodeSimplify(可选精简) → nodeSegment(按大意分段) → nodeClean(解析) → nodeEnd

产出契约：
  segments_json  分段数组（JSON 字符串）
  seg_count      段数
  para_words     每段词数（JSON 数组）
  word_count     总词数
  simplified_text 精简后的母稿正文（未精简时即原文）
  level / need_simplify / ok

用法：
    python3 tools/build_graphA.py [输出路径，默认 dify_graphs/graphA.new.json]
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / 'dify_graphs' / 'graphA.new.json'

# 档位与字数规格（与 GEN 图保持一致；母稿只可能是 B1 / B2）
LEVEL_SPEC = {
    'B1': {'target': 380, 'lo': 323, 'hi': 437, 'per_lo': 28, 'per_hi': 35},
    'B2': {'target': 550, 'lo': 468, 'hi': 632, 'per_lo': 41, 'per_hi': 50},
}

MODEL_FLASH = {
    'provider': 'langgenius/deepseek/deepseek',
    'name': 'deepseek-v4-flash',
    'mode': 'chat',
    'completion_params': {'temperature': 0.2, 'max_tokens': 4000, 'thinking': False},
}
MODEL_PRO = {
    'provider': 'langgenius/deepseek/deepseek',
    'name': 'deepseek-v4-pro',
    'mode': 'chat',
    'completion_params': {'temperature': 0.3, 'max_tokens': 8000, 'thinking': False},
}

STYLE_OPTIONS = ['hemingway', 'austen', 'ohenry', 'twain', 'dickens', 'orwell', 'shakespeare', 'default']


def shell(nid, ntype, x, y, data, w=244, h=110):
    return {
        'id': nid, 'type': ntype,
        'position': {'x': x, 'y': y},
        'positionAbsolute': {'x': x, 'y': y},
        'width': w, 'height': h, 'zIndex': 0,
        'data': data,
    }


def edge(eid, src, tgt, stype, ttype):
    return {
        'id': eid, 'source': src, 'target': tgt,
        'type': 'custom', 'sourceHandle': 'source', 'targetHandle': 'target', 'zIndex': 11,
        'data': {'isInIteration': False, 'sourceHandle': 'source', 'targetHandle': 'target',
                 'sourceType': stype, 'targetType': ttype, 'isInLoop': False},
    }


# ── ① nodeSimplify：可选精简 ─────────────────────────────────────────
SIMPLIFY_SYS = '''你是英语分级阅读内容编辑。下面是一篇**已获授权**的母稿（BBC Learning English / 出版社书系等）。

【任务】把这篇母稿切成**信息单元**，提炼成一份清单。清单决定「重写时保留哪些信息」。

【要求】
1. 🔴 **固定 12 条**（这是硬指标，不多不少）。原文每一段都含 1 个以上信息单元，
   请把相邻的合并成 12 个单元 —— **一条 = 一个可以独立成段的信息单元**，
   按原文顺序排列（起因 → 发展 → 转折或分歧 → 结论）。
   ⚠️ 实测教训：写「8–12 条」这类宽区间时，模型会**取到远低于下限**（曾只给 6–7 条），
   导致重写时没有内容可填、全文严重欠字数。所以请**凑满 12 条**。
2. 每条**一句话说清**，**15–30 个英文单词**（不要写得太短，也不要超过 30）。
3. **关键数字必须带进对应条目**（原样保留，一个都不能改、不能丢）。
4. 只写母稿里确实讲到的内容，**不得推断、不得补充、不得美化**。
5. **只丢这三类**：纯过渡句、重复表述、与主题无关的枝节。
   ⚠️ **举例、个案、专家发言、数据来源都要保留**（它们正是展开成段落的血肉）。
6. 清单总量约为原文的 **35–45%**，这是正常的 —— 它承载的是重写时要保留的全部信息。

【母稿档位】{{#nodeStart.level#}}

【母稿原文】
{{#nodeStart.material#}}

【输出格式】只输出 JSON，不要 markdown 代码块，不要任何解释：
{"outline": ["第一条要点", "第二条要点"]}'''

# ── ①-b 按清单重写───────────────────────────────────────────
# 实测教训（四轮）：让模型「在既有文本上继续删」基本无效 ——
#   936 → 801 → 744 → 726 → 705 词（B2 上限 632），每轮只砍 2–6%。
# 根因：模型对已有文本倾向保守保留。⇒ 改为**信息瓶颈法**：先提炼要点清单，
#   再按清单重写。清单负责「保留哪些信息」，**段数/句数框架负责「写多长」**。
#
# 🔴 2026-09-22 关键修正（真跑 3 轮才定位）：「只按清单重写、不给原文」会**严重欠字数**。
#   客观数据：1433 词母稿 → 精简稿 352 词（8–12 条）→ 188 词（12–14 条），B2 下限 468。
#   两条根因：
#   ① **条数不可控**：写「8–12 条」模型给 6–7 条，写「12–14 条」还是给 7 条 ——
#      条数由模型对「主线」的判断决定，**给区间也压不住**。⇒ 改为固定 12 条 + 放宽「只提主线」，
#      并明确「一条 = 一个可独立成段的信息单元」。
#   ② **句长超出模型能力**：原要求「每段 2 句 × 20–25 词」，但模型自然句长只有 ~13 词
#      （与 GEN 上实测的 B1 句长 10.1–12.4 完全同源）⇒ B2 每段 41–50 词用 2 句**物理上写不出来**，
#      必然欠写。**这是 B2 长期不达标的真正原因。**
#   ⇒ 结论：**控字数要用「句数」，不要用「句长」**。B2 改 3 句 × 13–17 词（每段 39–51 词），
#      并重新把原文交回给它作为压缩素材（清单退化为「保什么」的指引）。
SIMPLIFY2_SYS = '''上一步已经提炼出要点清单。现在产出**入库用的母稿正文**。关键：**要不要重写，取决于 need_simplify**。

【分支判断】看下面的「是否需要重写」：
- 值为 `true` ⇒ 执行【重写模式】
- 其他（`false` / 空）⇒ 执行【原样模式】

【重写模式】
把【母稿原文】**压缩**成一篇更短、更简单的连贯正文。

🔴 **段数固定 12 段**。这是硬指标，不多不少 —— 每一段对应原文相邻的若干个信息单元。
🔴 **本次母稿档位 = {{#nodeStart.level#}}** —— 请**只照这一档**来写，不要照另一档。

| 档位 | 段数 | **每段句数** | 每句词数 | 每段词数 | 全文词数（硬区间） |
|---|---|---|---|---|---|
| **B2** | 12 | **4 句** | 10–13 | 40–52 | **480–624**（硬区间 468–632） |
| **B1** | 12 | **2 句** | 14–17 | 28–34 | **336–408**（硬区间 323–437） |

⚠️ **不要写超长句去凑字数** —— 请用**句数**控制段落长度。
⚠️ **B1 档只写 2 句就停**：实测照 3–4 句写会把 B1 撑到 560 词、**直接超上限 437**。
   反之 B2 档必须写满 4 句，只写 3 句会掉到 439 词、**低于下限 468**。

【怎么做压缩】这是**做减法**，不是换词：
1. 按【要点清单】决定**保留哪些信息**；清单之外的信息（举例、个案、次要论证、重复表述）**一律删掉**。
2. **不得补充原文没有的内容**，不得推断，不得美化。关键数字原样保留。
3. 遇到"信息放不下"时：**继续删次要信息**，而不是把段写长、也不是加段。
4. 段与段之间用**空行**分隔（一行一段）。不要小标题、不要编号。
5. **写完必须自查（逐项做，别跳过）**：
   - ① 数段数 = **12** 段？
   - ② 逐段数句数：B2 必须 **4 句**；B1 必须 **2 句**。（最容易漏的就是这一项）
   - ③ 估全文词数：B2 目标 480–624；B1 目标 336–408。
   - ④ 全文不足下限 ⇒ 先检查是不是**句数写少了**（B2 补满 4 句 / B1 补满 2 句），再考虑把次要信息加回来。
   - ⑤ 全文超上限 ⇒ 再删一两条次要信息（不要靠缩句）。

【原样模式】
**逐字原样输出**下面的原文。不得改写、不得增删、不得调整顺序、不得纠正用词。

【母稿档位】{{#nodeStart.level#}}
【是否需要重写】{{#nodeStart.need_simplify#}}

【要点清单】
{{#nodeSimplify.text#}}

【母稿原文】（重写模式下它是**压缩的素材**；原样模式下要逐字输出它）
{{#nodeStart.material#}}

【输出要求】
只输出正文本身。不要任何解释、不要 markdown、不要标题。'''

COUNT_CODE = r'''function main({ text }) {
  const wc = (t) => (String(t || '').match(/[A-Za-z][A-Za-z''-]*/g) || []).length;
  const t = String(text || '');
  return { word_count: String(wc(t)), text: t };
}'''

# ── ② nodeSegment：按内容大意自然分段 ────────────────────────────────
SEGMENT_SYS = '''你是英语分级阅读内容编辑。把下面这篇母稿**按内容大意自然分段**，产出的段落骨架将供后续多个难度档共用。

【分段规则】
0. 🔴 **先看正文的既有切分**：若正文已经是一行一段、段间有空行（重写模式必然如此），
   **直接采用这个切分**，不要重新合并或拆分 —— 除非某段明显超过上限（那就再切一刀）。
   此时**段数 = 要点条数**，这是设计使然，不是"段数不对"。
1. **按内容大意切**：一个段落 = 一个完整的信息单元（一个"大意"）。不要硬凑段数，也不要为了美观拆出碎片段。
2. **段数上限 16 段**，且**通常不会用到这么多**。段数由内容自然决定。
3. **每段词数要纳入规格考虑**（这是硬约束，决定后续各档能否达标）：
   - 母稿 B1：每段约 **28–35 词**
   - 母稿 B2：每段约 **41–50 词**
   ⇒ **段数 = 总词数 ÷ 每段词数**。先估一下正文大约多少词，反推段数大约多少段，再按这个数量去切。
4. **切完必须自查**：逐段数词数。
   - 某段低于下限 ⇒ 与相邻段**合并**
   - 某段高于上限 ⇒ 在此处**再切一刀**
   若反复出现"某段超上限"，而段数已经接近 16 段上限 ⇒ 说明**正文本身还太长**，
   回到精简那一步的思路：**再删掉一些举例与次要观点**，而不是把段数硬顶到上限。
5. **只做切分，不做改写**：不得增删信息、不得调整顺序、不得改写用词。
6. 不要保留原文的小标题、编号、markdown 标记。

【母稿档位】{{#nodeStart.level#}}

【母稿正文】
{{#nodeSimplify2.text#}}

【输出格式】只输出 JSON，不要 markdown 代码块，不要任何解释：
{"segments": ["第一段原文", "第二段原文", "第三段原文"]}'''

# ── ③ nodeClean：解析分段结果 ───────────────────────────────────────
CLEAN_CODE = r'''function main({ level, need_simplify, simplified, raw }) {
  const strip = (s) => String(s == null ? '' : s).replace(/```json/gi, '').replace(/```/g, '').trim();

  /* 从模型输出里抠出 JSON（模型常带前后缀或 markdown 包裹） */
  let segs = [];
  const txt = strip(raw);
  const i = txt.indexOf('{'), j = txt.lastIndexOf('}');
  if (i >= 0 && j > i) {
    try {
      const o = JSON.parse(txt.slice(i, j + 1));
      const arr = Array.isArray(o.segments) ? o.segments : (Array.isArray(o) ? o : []);
      segs = arr.map((x) => String(x || '').trim()).filter((x) => x.length > 0);
    } catch (e) { segs = []; }
  }
  /* 兜底：模型没给 JSON 时按空行切 */
  if (!segs.length) {
    segs = txt.split(/\n\s*\n/).map((s) => s.trim()).filter((s) => s.length > 0);
  }

  const wc = (t) => (String(t || '').match(/[A-Za-z][A-Za-z''-]*/g) || []).length;
  const per = segs.map((s) => wc(s));
  const total = per.reduce((a, b) => a + b, 0);
  const lv = String(level || '').trim();
  const spec = { B1: [323, 437, 28, 35], B2: [468, 632, 41, 50] }[lv] || null;

  /* 🔴 段数是**硬要求**（2026-09-22 修）：下游档位都要按同一骨架逐段对齐，
     段数不对 ⇒ 骨架不可用。此前 ok 只判 `>= 3`、warn 只看词数 ⇒
     模型给出 6 段的错误结果会被**静默放行**（真跑第 4 次：6 段 329 词、warn 空）。
     现在段数与词数**分别判定**，任一不合格都 ok=false 并写明原因。 */
  const SEGN = 12;
  const segBad = segs.length !== SEGN;
  const wcBad = !!spec && (total < spec[0] || total > spec[1]);
  const tooMany = segs.length > 16;          /* 需求硬上限，独立于 SEGN 报出 */
  const warns = [];
  if (segBad) warns.push('段数 ' + segs.length + ' 不等于要求的 ' + SEGN + ' 段');
  if (!spec) warns.push('未知档位');
  else if (total < spec[0]) warns.push('总词数 ' + total + ' 低于 ' + lv + ' 下限 ' + spec[0]);
  else if (total > spec[1]) warns.push('总词数 ' + total + ' 超过 ' + lv + ' 上限 ' + spec[1]);

  return {
    segments_json: JSON.stringify(segs),
    seg_count: String(segs.length),
    para_words: JSON.stringify(per),
    word_count: String(total),
    simplified_text: String(simplified || ''),
    level: lv,
    need_simplify: String(need_simplify || 'false'),
    over_limit: tooMany ? 'true' : 'false',
    ok: (!segBad && !wcBad && !!spec) ? 'true' : 'false',
    warn: warns.join('；'),
  };
}'''


def build():
    nodes = [
        shell('nodeStart', 'start', 60, 280, {
            'type': 'start',
            'title': '开始',
            'desc': '接收授权母稿原文、人工标注的档位、是否精简、写作风格',
            'selected': False,
            'variables': [
                {'label': '母稿原文', 'variable': 'material', 'type': 'paragraph',
                 'required': True, 'max_length': 20000, 'options': []},
                {'label': '母稿档位（人工标注）', 'variable': 'level', 'type': 'select',
                 'required': True, 'max_length': 48, 'options': ['B1', 'B2']},
                {'label': '是否需要精简（超出该档字数时才为 true）', 'variable': 'need_simplify',
                 'type': 'select', 'required': False, 'max_length': 48, 'options': ['true', 'false']},
                {'label': '写作风格', 'variable': 'style', 'type': 'select',
                 'required': False, 'max_length': 48, 'options': STYLE_OPTIONS},
            ],
        }),
        shell('nodeSimplify', 'llm', 340, 280, {
            'type': 'llm',
            'title': '① 母稿精简（可选）',
            'desc': 'need_simplify=true 时大幅删次要信息、保主线，压到该档字数；false 时逐字原样输出',
            'selected': False,
            'model': MODEL_PRO,
            'prompt_template': [{'role': 'system', 'text': SIMPLIFY_SYS}],
            'context': {'enabled': False, 'variable_selector': []},
            'vision': {'enabled': False, 'configs': {'detail': 'low'}},
            'memory': None,
            'answer': '',
        }),
        shell('nodeSimplify2', 'llm', 620, 280, {
            'type': 'llm',
            'title': '①-c 二次精简（收尾）',
            'desc': '带"当前还超多少"的反馈再砍一轮；已达标则逐字原样输出',
            'selected': False,
            'model': MODEL_PRO,
            'prompt_template': [{'role': 'system', 'text': SIMPLIFY2_SYS}],
            'context': {'enabled': False, 'variable_selector': []},
            'vision': {'enabled': False, 'configs': {'detail': 'low'}},
            'memory': None,
            'answer': '',
        }),
        shell('nodeSegment', 'llm', 900, 280, {
            'type': 'llm',
            'title': '② 按大意分段',
            'desc': '按内容自然切分（段数上限 16），并把每段词数纳入该档规格',
            'selected': False,
            'model': MODEL_PRO,
            'prompt_template': [{'role': 'system', 'text': SEGMENT_SYS}],
            'context': {'enabled': False, 'variable_selector': []},
            'vision': {'enabled': False, 'configs': {'detail': 'low'}},
            'memory': None,
            'answer': '',
        }),
        shell('nodeClean', 'code', 1460, 280, {
            'type': 'code',
            'title': '③ 解析分段',
            'desc': '解析 segments、统计段数与每段词数、标注越界告警',
            'selected': False,
            'code_language': 'javascript',
            'code': CLEAN_CODE,
            'variables': [
                {'variable': 'level', 'value_selector': ['nodeStart', 'level']},
                {'variable': 'need_simplify', 'value_selector': ['nodeStart', 'need_simplify']},
                {'variable': 'simplified', 'value_selector': ['nodeSimplify2', 'text']},
                {'variable': 'raw', 'value_selector': ['nodeSegment', 'text']},
            ],
            'outputs': {k: {'children': None, 'type': 'string'} for k in
                        ('segments_json', 'seg_count', 'para_words', 'word_count',
                         'simplified_text', 'level', 'need_simplify', 'over_limit', 'ok', 'warn')},
        }),
        shell('nodeEnd', 'end', 1740, 280, {
            'type': 'end',
            'title': '结束',
            'desc': '输出母稿段落骨架（供图 B 使用）',
            'selected': False,
            'outputs': [
                {'variable': k, 'value_selector': ['nodeClean', k]}
                for k in ('segments_json', 'seg_count', 'para_words', 'word_count',
                          'simplified_text', 'level', 'need_simplify', 'over_limit', 'ok', 'warn')
            ],
        }),
    ]

    edges = [
        edge('e-start-simplify', 'nodeStart', 'nodeSimplify', 'start', 'llm'),
        edge('e-simplify-simplify2', 'nodeSimplify', 'nodeSimplify2', 'llm', 'llm'),
        edge('e-simplify2-segment', 'nodeSimplify2', 'nodeSegment', 'llm', 'llm'),
        edge('e-segment-clean', 'nodeSegment', 'nodeClean', 'llm', 'code'),
        edge('e-clean-end', 'nodeClean', 'nodeEnd', 'code', 'end'),
    ]

    return {
        'graph': {'nodes': nodes, 'edges': edges, 'viewport': {}},
        'features': {},
        'conversation_variables': [],
        'environment_variables': [],
    }


def static_check(d):
    g = d['graph']
    ids = [n['id'] for n in g['nodes']]
    errs = []
    if len(set(ids)) != len(ids):
        errs.append('节点 id 重复')
    ts = {n['id']: n['type'] for n in g['nodes']}
    # 边可达性
    reach = {'nodeStart'}
    changed = True
    while changed:
        changed = False
        for e in g['edges']:
            if e['source'] in reach and e['target'] not in reach:
                reach.add(e['target']); changed = True
    for i in ids:
        if i not in reach:
            errs.append('不可达节点：' + i)
    # 变量引用可解析
    import re
    allout = {}
    for n in g['nodes']:
        if n['type'] == 'code':
            allout[n['id']] = set(n['data'].get('outputs', {}).keys())
        elif n['type'] == 'llm':
            allout[n['id']] = {'text'}
        elif n['type'] == 'start':
            allout[n['id']] = {v['variable'] for v in n['data'].get('variables', [])}
    for n in g['nodes']:
        blob = json.dumps(n['data'], ensure_ascii=False)
        for m in re.finditer(r'\{\{#([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)#\}\}', blob):
            src, var = m.group(1), m.group(2)
            if src not in allout:
                errs.append('%s 引用了不存在的节点 %s' % (n['id'], src))
            elif var not in allout[src]:
                errs.append('%s 引用了 %s 上不存在的输出 %s' % (n['id'], src, var))
        for v in n['data'].get('variables', []) or []:
            sel = v.get('value_selector')
            if not sel:
                continue
            src, var = sel[0], sel[1]
            if src not in allout or var not in allout.get(src, set()):
                errs.append('%s 的入参 %s ← %s.%s 无法解析' % (n['id'], v['variable'], src, var))
    return errs


def main():
    d = build()
    errs = static_check(d)
    print('节点 %d · 边 %d' % (len(d['graph']['nodes']), len(d['graph']['edges'])))
    if errs:
        print('✗ 静态校验失败：')
        for e in errs:
            print('   -', e)
        return 1
    print('✅ 静态校验通过：引用可解析、无死节点、全部从 start 可达')
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
    print('✓ 已写出 %s (%d bytes)' % (OUT, OUT.stat().st_size))
    print('  推送：node tools/dify_push_graph.mjs --app=d4e0905b-b8da-47f1-9d10-a1ca87bdc401 --graph=%s' % OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
