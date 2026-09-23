#!/usr/bin/env python3
"""
ReadPal · 图 C「轻量提示词」构建脚本（2026-09-23）

用途：Bryan 的对照实验 —— 把提示词压到一段（约 400 字，不含现有图 B 那套 3 万字
     分级规格 + 校验规则），看**模型裸能力**下 A1-/A2 两档文章与题目的产出质量。

【与图 A/B 的关系】
  图 A（预处理分段，7 节点）+ 图 B（向下生成 + 校验重跑，15 节点）是**产线链路**。
  图 C 是**独立实验链路**，不接图 A、不接图 B、不共用任何节点代码：
      开始 → ① LLM（一段提示词一次产出全部） → ② code（解析兜底） → 结束
  刻意只留 1 个 LLM 节点 —— 要测的就是「一段提示词的极限」，拆多了就不是这个实验了。

【产出契约】字段名与图 B 对齐，前端零改动即可渲染：
  articles_json  {"A1": 全文, "A2": 全文}
  paras_json     {"A1": [段…], "A2": [段…]}
  quiz_json      {"levels": {"A1": [3题], "A2": [3题], "B1": [3题]}}
  title          母稿标题（前端标题以导入时填的为准）

【刻意不做的】
  · 无字数校验、无段落对齐、无自动重跑 —— 全字面不出现在本图
  · 不生成 B1 / B2 文章（母稿即 B1，无需改动）
  · 不做精简模式、不做批量

用法：
    python3 tools/build_graphC.py [输出路径] [--model=deepseek|luna]
      · --model=deepseek（默认）→ dify_graphs/graphC.new.json
      · --model=luna     → dify_graphs/graphC.luna.json（OpenCode Go · GPT 5.6 Luna）
    ⚠️ 图 C 的**唯一实验变量是提示词**；换 --model 是另一类对照（模型对照），
       跑对照实验时一次只动一个变量，别同时改提示词。
"""
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _flag(name, default=None):
    for a in sys.argv[1:]:
        if a.startswith('--%s=' % name):
            return a.split('=', 1)[1].strip()
    return default


def _positional():
    return [a for a in sys.argv[1:] if not a.startswith('--')]


# ───────────────────── 模型档（--model=deepseek|luna，默认 deepseek）─────────────────────
# 为什么要有这个开关：2026-09-23 Bryan 要验证「换到 OpenCode Go 的 GPT 5.6 Luna 能不能用」。
# 换模型必须可回退、可对照 —— 所以做成档位而不是直接改死，出问题一条命令推回 deepseek 版。
#
# ⚠️ 两档的 completion_params 不完全一样，别照抄：
#   · deepseek 走 Dify 官方插件（langgenius/deepseek/deepseek），支持私有字段 `thinking`
#   · OpenCode Go 是 OpenAI 兼容聚合渠道，**没有 `thinking`** —— 带上可能被拒或被忽略，故不写
MODEL_PRESETS = {
    'deepseek': {
        'desc': 'DeepSeek 官方渠道（产线在用）',
        'model': {
            'provider': 'langgenius/deepseek/deepseek',
            'name': 'deepseek-v4-pro',
            'mode': 'chat',
            'completion_params': {'temperature': 0.45, 'max_tokens': 6000, 'thinking': False},
        },
    },
    'luna': {
        'desc': 'OpenCode Go 渠道 · GPT 5.6 Luna（对照实验）',
        'model': {
            'provider': 'langgenius/opencode_go/opencode_go',
            'name': 'gpt-5.6-luna',
            'mode': 'chat',
            'completion_params': {'temperature': 0.45, 'max_tokens': 6000},
        },
    },
}

MODEL_KEY = (_flag('model') or os.environ.get('GC_MODEL') or 'deepseek').lower()
if MODEL_KEY not in MODEL_PRESETS:
    print('✗ 未知模型档：%s（可选 %s）' % (MODEL_KEY, ' / '.join(MODEL_PRESETS)))
    sys.exit(2)

MODEL_PRO = MODEL_PRESETS[MODEL_KEY]['model']
MODEL_DESC = MODEL_PRESETS[MODEL_KEY]['desc']

_pos = _positional()
OUT = Path(_pos[0]) if _pos else REPO / 'dify_graphs' / (
    'graphC.new.json' if MODEL_KEY == 'deepseek' else 'graphC.%s.json' % MODEL_KEY)

# ───────────────────────── ① 轻量提示词（system）─────────────────────────
# 🔴 这是**实验的唯一变量** —— 除「出题档位明确化」与「输出格式约定」外，
#    不得加入任何分级规格、字数区间、校验要求。改这里前先确认是对照实验的意图。
LITE_SYS = """你是CEFR分级阅读的专家。我给你1篇{{#nodeStart.level#}}难度的文章（母稿无需改动）。

【任务一 生成两档改编文章】
根据CEFR的分级标准和词汇标准，分别生成A1-和A2的文章。要求：
段落一致性：所有版本（含母稿）保持段落数和段落内容对齐，每段表达一个主要思想。段落切分根据内容和文章长度来，一般在8-12段都可以。
保证主要内容和文章关键词不变，比如主题词（哪怕超纲也不要变）、人名、地名等关键信息。
语言逐级简化：
  A2版本：保留原文主要信息，但语言更简单，句子更短，更易理解。
  A1版本：使用简单词汇、短句，降低语法复杂性，更适合基础读者。
句式调整：从B1到A2再到A1，句式逐渐从复合句转换为简单句。

【任务二 出题：三档各3道，共9道】
每篇难度的文章生成3道选择题（英文题干）和解析（中文）。三档都要出题：A1-、A2、B1。
主要从4个层面去出题，就是语言、文本、逻辑、认知。各档配额固定如下：
  A1-（语言2 + 文本1）：读者能不能认出词、读懂最直白的句子，这个阶段还谈不上推理和思考。
  A2（语言1 + 文本1 + 逻辑1）：开始加一道最简单的推理，但语言和字面理解还是主力。
  B1（文本1 + 逻辑1 + 认知1）：语言题基本取消——默认这个等级的词汇量够用了，不该再考单词。开始出现一道真正的认知题。

样例（供参考）：
  语言题：比如"clutterer"这个词在文中最接近哪个意思（选项给近义词）
  文本题：Sam Gosling是做什么的？（原文直接说了）
  逻辑题：以月饼那篇为例——"为什么便宜月饼卖得好，但商家反而赚得少？"（需要连起两句话才能推出因果，但线索都在原文里，不算难）

【输出格式】
只输出一个JSON对象，不要任何解释性文字、不要markdown代码块。
articles_json 是每档的整篇正文；paras_json 是同一篇按段落切好的数组（两者段数必须一致）。
quiz_json.levels 里 type 只能取 language / text / logic / cognitive 之一；answer 是正确选项在 options 里的下标（0-3）。
格式如下：
{
 "articles_json": {"A1": "A1-整篇正文", "A2": "A2整篇正文"},
 "paras_json": {"A1": ["第1段", "第2段", "第3段"], "A2": ["第1段", "第2段", "第3段"]},
 "quiz_json": {"levels": {
   "A1": [{"type": "language", "q": "题目", "options": ["选项A", "选项B", "选项C", "选项D"], "answer": 0, "explain": "中文解析"}],
   "A2": [{"type": "logic", "q": "题目", "options": ["选项A", "选项B", "选项C", "选项D"], "answer": 1, "explain": "中文解析"}],
   "B1": [{"type": "cognitive", "q": "题目", "options": ["选项A", "选项B", "选项C", "选项D"], "answer": 2, "explain": "中文解析"}]
 }}
}
A1-、A2、B1 三档各写满 3 道题。"""

LITE_USER = """【标题】{{#nodeStart.title_in#}}

【母稿正文】
{{#nodeStart.master_text#}}

按上述要求：生成 A1- 和 A2 两篇文章，并为 A1-、A2、B1 三档各出 3 道题。只输出 JSON。"""

# ───────────────────────── ② 解析兜底（code）─────────────────────────
# 只做「把模型输出对齐成前端认的字段名」这一件事，**不修正内容**。
# 解析失败/缺档一律落进 parse_warn，前端显式提示 —— 不静默。
PARSE_CODE = r"""function main({ text, title_in }) {
  const warn = [];
  const res = { articles_json: '{}', paras_json: '{}', quiz_json: '{"levels":{}}',
                title: String(title_in || '').trim(), parse_ok: 'false', parse_warn: '' };

  // ── 宽松修复：只修**语法**，不碰任何内容。返回 {text, why[]}，why 空 = 无需修复。
  //    ① 字符串内的裸换行（未转义）② 对象/数组闭合前的尾随逗号
  //    🔴 逐字符扫描并跟踪「是否在字符串内」—— 否则正文里出现的 ,} 会被误改。
  const looseFix = function (s) {
    const why = [];
    // ① 字符串内裸换行 / 裸 tab → 转义
    let a = '', inStr = false, esc = false, nl = false;
    for (let i = 0; i < s.length; i++) {
      const c = s.charAt(i);
      if (inStr) {
        if (esc) { a += c; esc = false; continue; }
        if (c === '\\') { a += c; esc = true; continue; }
        if (c === '"') { a += c; inStr = false; continue; }
        if (c === '\n') { a += '\\n'; nl = true; continue; }
        if (c === '\r') { nl = true; continue; }
        if (c === '\t') { a += '\\t'; continue; }
      } else {
        if (c === '"') { inStr = true; }
      }
      a += c;
    }
    if (nl) why.push('字符串内裸换行');
    // ② 尾随逗号（迭代，最多 3 轮 —— 处理 ,,} 这类叠加）
    let b = a, tc = false;
    for (let round = 0; round < 3; round++) {
      let o = '', inS = false, es = false, hit = false;
      for (let i = 0; i < b.length; i++) {
        const c = b.charAt(i);
        if (inS) {
          o += c;
          if (es) { es = false; continue; }
          if (c === '\\') { es = true; continue; }
          if (c === '"') { inS = false; }
          continue;
        }
        if (c === '"') { inS = true; o += c; continue; }
        if (c === ',') {
          let j = i + 1;
          while (j < b.length && ' \t\r\n'.indexOf(b.charAt(j)) >= 0) j++;
          if (b.charAt(j) === '}' || b.charAt(j) === ']') { hit = true; continue; }
        }
        o += c;
      }
      b = o;
      if (!hit) break;
      tc = true;
    }
    if (tc) why.push('尾随逗号');
    return { text: b, why: why };
  };

  // 标题比对用的归一化（忽略大小写/标点/空白）
  const normT = function (s) {
    return String(s == null ? '' : s).toLowerCase().replace(/[\s"'“”‘’.,:;!?—–\-]/g, '');
  };

  let raw = String(text || '').trim();
  // 去 markdown 代码围栏
  raw = raw.replace(/^```[a-zA-Z0-9]*\s*/, '').replace(/\s*```\s*$/, '').trim();
  // 容错：截取第一个 { 到最后一个 }
  const i0 = raw.indexOf('{'), j0 = raw.lastIndexOf('}');
  if (i0 < 0 || j0 <= i0) {
    res.parse_warn = '模型输出里找不到 JSON 对象（收到 ' + raw.length + ' 字符）';
    return res;
  }
  if (i0 > 0 || j0 < raw.length - 1) { warn.push('输出含 JSON 之外的文字，已裁剪'); raw = raw.slice(i0, j0 + 1); }

  let obj = null;
  try { obj = JSON.parse(raw); } catch (e) {
    // 模型偶尔吐非法 JSON —— 先做**纯语法**宽松修复（不动内容），修不好才报错。
    // 实测动因：luna 4 次里 1 次在 articles_json 里多写一个尾随逗号，整条链路就全废。
    const fx = looseFix(raw);
    if (fx.why.length) {
      try {
        obj = JSON.parse(fx.text);
        warn.push('JSON 含 ' + fx.why.join('、') + '，已自动修复');
      } catch (e2) {
        res.parse_warn = 'JSON 解析失败（已试宽松修复：' + fx.why.join('、') + '）：' + String(e2 && e2.message || e2).slice(0, 140);
        return res;
      }
    } else {
      res.parse_warn = 'JSON 解析失败：' + String(e && e.message || e).slice(0, 160);
      return res;
    }
  }
  if (!obj || typeof obj !== 'object') { res.parse_warn = 'JSON 顶层不是对象'; return res; }

  // 键归一化：A1_1 / A1-1 / A1.1 / B2P_1 → A1 / A2 / B1 / B2
  const nk = function (s) {
    let t = String(s === null || s === undefined ? '' : s).trim().toUpperCase().split(' ').join('');
    if (!t) return '';
    t = t.split('B2+').join('B2P').replace(/[._·／\/-]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
    const m = t.match(/^(A1|A2|B1|B2P)(_?[123])?$/);
    return m ? (m[1] === 'B2P' ? 'B2' : m[1]) : '';
  };
  const pick = function (src) {
    const out = {};
    if (src && typeof src === 'object' && !Array.isArray(src)) {
      Object.keys(src).forEach(function (k) { const kk = nk(k); if (kk) out[kk] = src[k]; });
    }
    return out;
  };

  const arts = pick(obj.articles_json);
  const prs = pick(obj.paras_json);
  const lvq = (obj.quiz_json && typeof obj.quiz_json === 'object') ? pick(obj.quiz_json.levels) : {};

  // 本链路只认 A1 / A2 两篇文章（B1 即母稿，提示词明确不生成）
  const WANT = ['A1', 'A2'];
  const art2 = {}, par2 = {};
  WANT.forEach(function (k) {
    const t = String(arts[k] || '').trim();
    let ps = Array.isArray(prs[k]) ? prs[k].map(function (p) { return String(p || '').trim(); }).filter(Boolean) : [];
    if (!t && !ps.length) { warn.push('缺 ' + k + ' 文章'); return; }
    if (!ps.length) {
      // 无 paras_json → 按空行/换行拆（保持可见，不静默）
      ps = t.split(/\n+/).map(function (s) { return s.trim(); }).filter(Boolean);
      warn.push(k + ' 无 paras_json，已按换行拆分（' + ps.length + ' 段）');
    }
    if (t && ps.length) {
      const wcA = (t.match(/[A-Za-z][A-Za-z''-]*/g) || []).length;
      const wcP = ps.join(' ').match(/[A-Za-z][A-Za-z''-]*/g);
      const wcPv = wcP ? wcP.length : 0;
      if (wcA && wcPv && Math.abs(wcA - wcPv) / wcA > 0.08) {
        warn.push(k + ' 正文与分段词数不一致（正文 ' + wcA + ' / 分段 ' + wcPv + '）');
      }
    }
    art2[k] = t || ps.join('\n\n');
    par2[k] = ps;
  });
  // 向下档不带标题：正文/分段的首块若就是标题，剔除。
  // 🔴 确定性动作，不交给模型 —— 实测 luna 3/3 把标题写进正文（deepseek 0/3），
  //    而 paras_json 不含标题 ⇒ 不剔除就会「正文与分段不一致」，破坏段落对齐。
  const tl = normT(res.title);
  if (tl) {
    WANT.forEach(function (k) {
      if (art2[k]) {
        const lines = art2[k].split('\n');
        while (lines.length && !lines[0].trim()) lines.shift();
        if (lines.length && normT(lines[0]) === tl) {
          lines.shift();
          while (lines.length && !lines[0].trim()) lines.shift();
          art2[k] = lines.join('\n');
          warn.push(k + ' 正文首行是标题，已剔除');
        }
      }
      if (Array.isArray(par2[k]) && par2[k].length && normT(par2[k][0]) === tl) {
        par2[k].shift();
        warn.push(k + ' 分段首段是标题，已剔除');
      }
    });
  }

  const extra = Object.keys(arts).filter(function (k) { return WANT.indexOf(k) < 0; });
  if (extra.length) warn.push('模型额外产出了 ' + extra.join('/') + ' 文章，本链路不使用');

  // 题目：三档各要 3 道；type 白名单外的原样保留但报警（前端有默认标签兜底）
  const VALID = ['language', 'text', 'logic', 'cognitive'];
  const q2 = {};
  ['A1', 'A2', 'B1'].forEach(function (k) {
    const arr = Array.isArray(lvq[k]) ? lvq[k] : [];
    if (!arr.length) { warn.push('缺 ' + k + ' 题目'); return; }
    if (arr.length !== 3) warn.push(k + ' 题目数 ' + arr.length + ' 道（期望 3 道）');
    q2[k] = arr.slice(0, 3).map(function (q) {
      const o = (q && typeof q === 'object') ? q : {};
      let ty = String(o.type || '').trim().toLowerCase();
      if (VALID.indexOf(ty) < 0) { warn.push(k + ' 出现未知题型「' + ty + '」，按 text 展示'); ty = 'text'; }
      const opts = Array.isArray(o.options) ? o.options.map(function (x) { return String(x == null ? '' : x).trim(); }) : [];
      let ans = parseInt(o.answer, 10);
      if (isNaN(ans) || ans < 0 || ans >= (opts.length || 4)) {
        warn.push(k + ' 有一题的 answer 越界（' + o.answer + '），已置 0');
        ans = 0;
      }
      return { type: ty, q: String(o.q || '').trim(), options: opts, answer: ans, explain: String(o.explain || '').trim() };
    });
  });

  res.articles_json = JSON.stringify(art2);
  res.paras_json = JSON.stringify(par2);
  res.quiz_json = JSON.stringify({ levels: q2 });
  res.parse_ok = (Object.keys(art2).length && Object.keys(q2).length) ? 'true' : 'false';
  res.parse_warn = warn.join(' | ');
  return res;
}"""


def shell(nid, ntype, x, y, data, w=244, h=110):
    return {'id': nid, 'type': ntype, 'position': {'x': x, 'y': y},
            'positionAbsolute': {'x': x, 'y': y}, 'width': w, 'height': h, 'zIndex': 0, 'data': data}


def edge(eid, src, tgt, stype, ttype):
    return {'id': eid, 'source': src, 'target': tgt, 'type': 'custom',
            'sourceHandle': 'source', 'targetHandle': 'target', 'zIndex': 11,
            'data': {'isInIteration': False, 'sourceHandle': 'source', 'targetHandle': 'target',
                     'sourceType': stype, 'targetType': ttype, 'isInLoop': False}}


def build():
    nodes = []

    nodes.append(shell('nodeStart', 'start', 80, 300, {
        'type': 'start', 'title': '开始', 'selected': False,
        'desc': '接收母稿正文（B1）、标题、档位；不做任何预处理',
        'variables': [
            {'label': '母稿正文（不含标题）', 'variable': 'master_text', 'type': 'paragraph',
             'required': True, 'max_length': 20000, 'options': []},
            {'label': '标题', 'variable': 'title_in', 'type': 'text-input',
             'required': False, 'max_length': 300, 'options': []},
            {'label': '母稿档位', 'variable': 'level', 'type': 'select',
             'required': True, 'max_length': 48, 'options': ['B1', 'B2']},
        ],
    }, w=244, h=170))

    # ① 唯一一个 LLM 节点 —— 实验的核心变量
    nodes.append(shell('nodeLite', 'llm', 420, 280, {
        'type': 'llm', 'title': '① 轻量提示词生成', 'selected': False,
        'desc': '一段提示词一次产出：A1-/A2 两篇文章 + 三档各3道题（无分级规格、无校验）',
        'model': MODEL_PRO,
        'prompt_template': [
            {'role': 'system', 'text': LITE_SYS},
            {'role': 'user', 'text': LITE_USER},
        ],
        'context': {'enabled': False, 'variable_selector': []},
        'vision': {'enabled': False, 'configs': {'detail': 'low'}},
        'memory': None, 'answer': '',
    }, w=244, h=110))

    nodes.append(shell('nodeParse', 'code', 780, 280, {
        'type': 'code', 'title': '② 解析兜底', 'selected': False,
        'desc': 'JSON 解析 + 键归一化 + 缺档/越界报警（不修正内容，不改提示词）',
        'code_language': 'javascript', 'code': PARSE_CODE,
        'variables': [
            {'variable': 'text', 'value_selector': ['nodeLite', 'text']},
            {'variable': 'title_in', 'value_selector': ['nodeStart', 'title_in']},
        ],
        'outputs': {k: {'children': None, 'type': 'string'} for k in
                    ('articles_json', 'paras_json', 'quiz_json', 'title', 'parse_ok', 'parse_warn')},
    }))

    nodes.append(shell('nodeEnd', 'end', 1140, 280, {
        'type': 'end', 'title': '结束', 'selected': False,
        'desc': '输出 A1-/A2 文章、三档题目、标题、解析告警（字段名对齐图 B）',
        'outputs': [
            {'variable': 'articles_json', 'value_selector': ['nodeParse', 'articles_json']},
            {'variable': 'paras_json', 'value_selector': ['nodeParse', 'paras_json']},
            {'variable': 'quiz_json', 'value_selector': ['nodeParse', 'quiz_json']},
            {'variable': 'title', 'value_selector': ['nodeParse', 'title']},
            {'variable': 'parse_ok', 'value_selector': ['nodeParse', 'parse_ok']},
            {'variable': 'parse_warn', 'value_selector': ['nodeParse', 'parse_warn']},
            {'variable': 'level', 'value_selector': ['nodeStart', 'level']},
        ],
    }))

    edges = [
        edge('e-start-lite', 'nodeStart', 'nodeLite', 'start', 'llm'),
        edge('e-lite-parse', 'nodeLite', 'nodeParse', 'llm', 'code'),
        edge('e-parse-end', 'nodeParse', 'nodeEnd', 'code', 'end'),
    ]

    return {'graph': {'nodes': nodes, 'edges': edges, 'viewport': {}},
            'features': {}, 'conversation_variables': [], 'environment_variables': []}


def static_check(d):
    g = d['graph']
    ids = [n['id'] for n in g['nodes']]
    errs = []
    if len(set(ids)) != len(ids):
        errs.append('节点 id 重复')
    reach, changed = {'nodeStart'}, True
    while changed:
        changed = False
        for e in g['edges']:
            if e['source'] in reach and e['target'] not in reach:
                reach.add(e['target']); changed = True
    for i in ids:
        if i not in reach:
            errs.append('不可达节点：' + i)
    allout = {}
    for n in g['nodes']:
        if n['type'] == 'code':
            allout[n['id']] = set(n['data'].get('outputs', {}).keys())
        elif n['type'] == 'llm':
            allout[n['id']] = {'text'}
        elif n['type'] == 'start':
            allout[n['id']] = {v['variable'] for v in n['data'].get('variables', [])}
        elif n['type'] == 'end':
            allout[n['id']] = set()
    for n in g['nodes']:
        blob = json.dumps(n['data'], ensure_ascii=False)
        for m in re.finditer(r'\{\{#([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)#\}\}', blob):
            src, var = m.group(1), m.group(2)
            if src not in allout:
                errs.append('%s 引用了不存在的节点 %s' % (n['id'], src))
            elif var not in allout[src]:
                errs.append('%s 引用了 %s 上不存在的输出 %s' % (n['id'], src, var))
        for v in (n['data'].get('variables') or []):
            sel = v.get('value_selector')
            if not sel:
                continue
            if sel[0] not in allout or sel[1] not in allout.get(sel[0], set()):
                errs.append('%s 的入参 %s ← %s.%s 无法解析' % (n['id'], v['variable'], sel[0], sel[1]))
        if n['type'] == 'end':
            for o in n['data'].get('outputs', []):
                sel = o.get('value_selector')
                if not sel or sel[0] not in allout or sel[1] not in allout.get(sel[0], set()):
                    errs.append('end 的输出 %s ← %s 无法解析' % (o['variable'], '.'.join(sel or [])))
    return errs


def main():
    d = build()
    errs = static_check(d)
    print('节点 %d · 边 %d' % (len(d['graph']['nodes']), len(d['graph']['edges'])))
    print('  模型档：%s → %s | %s' % (MODEL_KEY, MODEL_PRO['provider'], MODEL_PRO['name']))
    print('  参数：%s' % json.dumps(MODEL_PRO['completion_params'], ensure_ascii=False))
    if errs:
        print('✗ 静态校验失败：')
        for e in errs:
            print('   -', e)
        return 1
    print('✅ 静态校验通过：引用可解析、无死节点、全部从 start 可达')
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
    print('✓ 已写出 %s (%d bytes)' % (OUT, OUT.stat().st_size))
    print('  提示词长度：system %d 字 + user %d 字 = %d 字' % (len(LITE_SYS), len(LITE_USER), len(LITE_SYS) + len(LITE_USER)))
    print('  推送：node tools/dify_push_graph.mjs --app=<图C的AppID> --graph=%s' % OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
