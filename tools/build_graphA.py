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


# ── ① nodeSimplify：可选精简（清单） ──────────────────────────────────
# 🔴 2026-09-22：加【第一步·分支】。此前无论勾不勾精简都强行提炼清单 ——
#   不勾精简时那份清单完全没人用，白跑一次长输出（每次 10–25 秒、白烧 token）。
#   现在 false 时只回一个空清单，几乎不耗时，也不做任何"精简"动作。
SIMPLIFY_SYS = '''你是英语分级阅读内容编辑。下面是一篇**已获授权**的母稿（BBC Learning English / 出版社书系等）。

【第一步 · 先看是否需要精简】
看下面的【是否需要精简】：
- 值为 `true` ⇒ 执行【提炼要点清单】。
- 其他（`false` / 空）⇒ **不要提炼、不要分析、不要总结**，直接输出：{"outline": []}
  （本次不使用清单；下一步会**逐字保留原文**，所以你在这里做的任何删减都是错的。）

【提炼要点清单】（**仅当值为 `true` 时执行**）
把这篇母稿切成**信息单元**，提炼成一份清单。清单决定「重写时保留哪些信息」。

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
【是否需要精简】{{#nodeStart.need_simplify#}}

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

【原样模式】（**未勾选精简时的唯一动作**）
🔴 **不要输出正文，也不要用原文改写**。只输出下面这一行，一个字符都不要多、不要加引号或句号：

__KEEP_ORIGINAL__

（为什么：不精简 = 逐字保留原文，正文由下游节点**直接取原文**，不经过模型 ——
 实测让模型"原样输出"时它仍会改写措辞，「一台复制机」这种措辞约束并不可靠。）

【母稿档位】{{#nodeStart.level#}}
【是否需要重写】{{#nodeStart.need_simplify#}}

【要点清单】
{{#nodeSimplify.text#}}

【母稿原文】（重写模式下它是**压缩的素材**；原样模式下要逐字输出它）
{{#nodeStart.material#}}

【输出要求】
只输出正文本身。不要任何解释、不要 markdown、不要标题。'''

# ── ①-c nodeFinal：定稿正文（**硬机制**，不靠模型自觉） ────────────────
# 🔴 2026-09-22 真跑抓到的 bug：不精简时让模型「逐字原样输出」，它仍然改写了措辞 ——
#   实测 "has moved from a hobby" → "has grown from a small hobby into"（443 词 vs 原文 454 词）。
#   ⇒ 正文在 false 模式下**不经过模型**，直接取 nodeStart.material。
#   模型在这条分支只需吐一个占位符，既保证逐字一致，又把耗时/成本压到最低。
FINAL_CODE = r'''function main({ need_simplify, material, rewritten }) {
  const simp = String(need_simplify || '').trim().toLowerCase() === 'true';
  const src = String(material || '');
  const raw = String(rewritten || '').trim();
  /* 占位符残留（模型没按指令走）/ 输出为空 / 精简稿为空 ⇒ 一律回落原文，绝不产出空正文 */
  const isStub = !raw || raw.indexOf('__KEEP_ORIGINAL__') >= 0;
  const final = (!simp || isStub) ? src : raw;
  return {
    final_text: final,
    used_original: (simp && !isStub) ? 'false' : 'true',
    need_simplify: simp ? 'true' : 'false',
    /* fallback=true 表示「勾了精简却没拿到稿子、回落到原文」—— 需要人在确认页知情 */
    fallback: (simp && isStub) ? 'true' : 'false',
  };
}'''

COUNT_CODE = r'''function main({ text }) {
  const wc = (t) => (String(t || '').match(/[A-Za-z][A-Za-z''-]*/g) || []).length;
  const t = String(text || '');
  return { word_count: String(wc(t)), text: t };
}'''

# ── ② nodeSegment：按内容大意自然分段 ────────────────────────────────
# 🔴 2026-09-22 重写。旧版有三条规则互相打架，原文一长就必然失控：
#   ① 「段数上限 16」② 「B1 每段 28–35 / B2 每段 41–50 词」③ 「段数 = 总词数 ÷ 每段词数」
#   —— 1400 词的不精简母稿按 ② 反推要 28–34 段，直接顶破 ①；模型只能乱给（实测给过 6 段）。
#   新规则：**段数由内容决定** —— 不勾精简时「能合则合、尽量靠近 12，合不动就多，不设上限」；
#   勾了精简时「必须正好 12 段」。词数规格不再用来反推段数（那是下游各档的事）。
SEGMENT_SYS = '''你是英语分级阅读内容编辑。把下面这段文字**按内容大意分段**，产出的段落骨架将供后续多个难度档共用。

🔴 **先判断模式**（看下面的【是否需要精简】）：
- 值为 `true` ⇒ 只执行【模式 B】
- 其他（`false` / 空）⇒ 只执行【模式 A】

【模式 A · 保留原文】
正文**逐字保留**：你**只做切分**，不得改写、增删、调整任何一个词。
1. **一个段落 = 一个信息单元（一个"大意"）**。不要把一段里的小句拆出来单独成段。
2. **能合则合**：讲同一件事、同一话题的相邻内容，合并成一段。
3. **目标 12 段**（这是产品规格），但 **以内容为准，绝不硬凑**：
   - 信息单元**不足 12 个** ⇒ **照实给**（给 8 段就给 8 段）。硬拆凑数会让后续改写**逐段错位**，
     这是最严重的错误，比段数不对更严重。
   - 信息单元**多于 12 个** ⇒ 先把同一话题的相邻单元合并，尽量靠近 12 段；
     **合并会破坏意思的，宁可多于 12 段**。段数**不设上限**，由内容决定。
4. **不要输出碎段**：低于 20 词的段落，除非它本身就是独立大意，否则并入相邻段。
5. 不要保留原文的小标题、编号、markdown 标记（`#`、`*`、`-` 等）。

【模式 B · 精简稿】
上一步已按 12 段写好，**必须正好 12 段**：
1. **直接采用它的既有切分**（一行一段、段间空行），不要重新合并或拆分 —— 这不算"段数不对"。
2. 唯一例外：某段**明显超过**该档上限（B1 超 45 词 / B2 超 65 词）⇒ 在此处切一刀，
   同时把相邻的短段合并回去，**切完段数仍必须是 12**。
3. 只做切分，不得改写用词。

【母稿档位】{{#nodeStart.level#}}
【是否需要精简】{{#nodeStart.need_simplify#}}

【正文】
{{#nodeFinal.final_text#}}

【输出格式】只输出 JSON，不要 markdown 代码块，不要任何解释：
{"segments": ["第一段原文", "第二段原文", "第三段原文"]}'''

# ── ③ nodeClean：解析分段结果 ───────────────────────────────────────
CLEAN_CODE = r'''function main({ level, need_simplify, master, raw, fallback }) {
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
  const simp = String(need_simplify || '').trim().toLowerCase() === 'true';

  /* 🔴 段数的判定口径（2026-09-22 用户拍板）：
     · **勾了精简** ⇒ 12 段是硬指标（精简稿本来就是按 12 段写的），不对就 ok=false。
     · **没勾精简** ⇒ 段数由内容决定（能合则合、尽量靠近 12、合不动就多，**不设上限**）。
       此时段数 ≠ 12 只报 `seg_note` 给前端提示，**不判失败、不阻断生成**。
     同时词数越界也只对「精简稿」才判 —— 保留原文的母稿长度本来就不由我们控制。 */
  const SEGN = 12;
  const segBad = simp && segs.length !== SEGN;
  const wcBad = simp && !!spec && (total < spec[0] || total > spec[1]);
  const warns = [];
  if (segBad) warns.push('段数 ' + segs.length + ' 不等于要求的 ' + SEGN + ' 段');
  if (!spec) warns.push('未知档位');
  if (wcBad && spec) warns.push(total < spec[0]
    ? ('总词数 ' + total + ' 低于 ' + lv + ' 下限 ' + spec[0])
    : ('总词数 ' + total + ' 超过 ' + lv + ' 上限 ' + spec[1]));
  const fb = String(fallback || '').trim().toLowerCase() === 'true';
  if (fb) warns.push('勾了精简但没拿到精简稿（模型未按指令输出），已自动回落为保留原文');

  /* 段数提示（非阻断）：偏离 12 就说一句，让老师心里有数 */
  const note = (segs.length === SEGN) ? ''
    : ('按内容分成 ' + segs.length + ' 段（推荐 12 段）');

  return {
    segments_json: JSON.stringify(segs),
    seg_count: String(segs.length),
    para_words: JSON.stringify(per),
    word_count: String(total),
    master_text: String(master || ''),
    level: lv,
    need_simplify: simp ? 'true' : 'false',
    seg_note: note,
    fallback: fb ? 'true' : 'false',
    /* 精简模式下「段数或词数不达标」都算失败（精简的目的就是落进规格）；
       不精简模式 wcBad 恒为 false、segBad 恒为 false ⇒ 只提示不判失败。 */
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
            'title': '① 提炼要点清单（仅精简时）',
            'desc': 'need_simplify=true 时提炼 12 条要点清单；false 时**不做任何动作**（直接回空清单）',
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
            'title': '①-b 产出母稿正文',
            'desc': 'need_simplify=true → 按清单压缩成 12 段；false → **逐字原样输出原文**',
            'selected': False,
            'model': MODEL_PRO,
            'prompt_template': [{'role': 'system', 'text': SIMPLIFY2_SYS}],
            'context': {'enabled': False, 'variable_selector': []},
            'vision': {'enabled': False, 'configs': {'detail': 'low'}},
            'memory': None,
            'answer': '',
        }),
        shell('nodeFinal', 'code', 900, 470, {
            'type': 'code',
            'title': '①-c 定稿正文',
            'desc': '不精简 → 直接取原文（逐字，不经过模型）；精简 → 取重写稿。占位符/空输出一律回落原文',
            'selected': False,
            'code_language': 'javascript',
            'code': FINAL_CODE,
            'variables': [
                {'variable': 'need_simplify', 'value_selector': ['nodeStart', 'need_simplify']},
                {'variable': 'material', 'value_selector': ['nodeStart', 'material']},
                {'variable': 'rewritten', 'value_selector': ['nodeSimplify2', 'text']},
            ],
            'outputs': {k: {'children': None, 'type': 'string'}
                        for k in ('final_text', 'used_original', 'need_simplify', 'fallback')},
        }),
        shell('nodeSegment', 'llm', 1190, 280, {
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
        shell('nodeClean', 'code', 1470, 280, {
            'type': 'code',
            'title': '③ 解析分段',
            'desc': '解析 segments、统计段数与每段词数、标注越界告警',
            'selected': False,
            'code_language': 'javascript',
            'code': CLEAN_CODE,
            'variables': [
                {'variable': 'level', 'value_selector': ['nodeStart', 'level']},
                {'variable': 'need_simplify', 'value_selector': ['nodeStart', 'need_simplify']},
                {'variable': 'master', 'value_selector': ['nodeFinal', 'final_text']},
                {'variable': 'raw', 'value_selector': ['nodeSegment', 'text']},
                {'variable': 'fallback', 'value_selector': ['nodeFinal', 'fallback']},
            ],
            'outputs': {k: {'children': None, 'type': 'string'} for k in
                        ('segments_json', 'seg_count', 'para_words', 'word_count',
                         'master_text', 'level', 'need_simplify', 'seg_note', 'fallback', 'ok', 'warn')},
        }),
        shell('nodeEnd', 'end', 1740, 280, {
            'type': 'end',
            'title': '结束',
            'desc': '输出母稿段落骨架（供图 B 使用）',
            'selected': False,
            'outputs': [
                {'variable': k, 'value_selector': ['nodeClean', k]}
                for k in ('segments_json', 'seg_count', 'para_words', 'word_count',
                          'master_text', 'level', 'need_simplify', 'seg_note', 'fallback', 'ok', 'warn')
            ],
        }),
    ]

    edges = [
        edge('e-start-simplify', 'nodeStart', 'nodeSimplify', 'start', 'llm'),
        edge('e-simplify-simplify2', 'nodeSimplify', 'nodeSimplify2', 'llm', 'llm'),
        edge('e-simplify2-final', 'nodeSimplify2', 'nodeFinal', 'llm', 'code'),
        edge('e-final-segment', 'nodeFinal', 'nodeSegment', 'code', 'llm'),
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
