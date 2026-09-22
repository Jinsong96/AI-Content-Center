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
1. 🔴 **条数 = 成稿的段数**，它必须让成稿能落进该档的**全文字数硬区间**：
   - 母稿 **B1** ⇒ 成稿要 **323–437 词**，按每段 28–35 词算 ⇒ **需要 10–15 条**
   - 母稿 **B2** ⇒ 成稿要 **468–632 词**，按每段 41–50 词算 ⇒ **需要 10–15 条**
   **一条 = 一个可以独立成段的信息单元**，按原文顺序排列（起因 → 发展 → 转折或分歧 → 结论）。
   ⚠️ 实测教训：**写宽区间时模型会取到远低于下限**（曾只给 6–7 条），
   重写时没有内容可填、**全文严重欠字数**（1433 词母稿只写出 188 词）。
   ⇒ **少于 10 条一定欠字数**，这是硬伤，务必给足；内容确实不够 10 条时也要把同一话题
   的细节充分展开成独立的几条，而不是合并压缩。
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

🔴 **段数 = 上一步清单的条数（10–15 段）** —— **一段写一条**，不合并、不拆分。
   这里**没有固定段数**：段数由内容定，但 **全文词数必须落进该档硬区间**（这才是硬指标）。
🔴 **本次母稿档位 = {{#nodeStart.level#}}** —— 请**只照这一档**来写，不要照另一档。

| 档位 | 段数 | **每段句数** | 每句词数 | 每段词数 | 全文词数（硬区间） |
|---|---|---|---|---|---|
| **B2** | 清单条数（10–15） | **4 句** | 10–13 | 40–52 | **468–632** |
| **B1** | 清单条数（10–15） | **2 句** | 14–17 | 28–34 | **323–437** |

⚠️ **不要写超长句去凑字数** —— 请用**句数**控制段落长度。
⚠️ **B1 档只写 2 句就停**：实测照 3–4 句写会把 B1 撑到 560 词、**直接超上限 437**。
   反之 B2 档必须写满 4 句，只写 3 句会掉到 439 词、**低于下限 468**。

【怎么做压缩】这是**做减法**，不是换词：
1. 按【要点清单】决定**保留哪些信息**；清单之外的信息（举例、个案、次要论证、重复表述）**一律删掉**。
2. **不得补充原文没有的内容**，不得推断，不得美化。关键数字原样保留。
3. 遇到"信息放不下"时：**继续删次要信息**，而不是把段写长、也不是加段。
4. 段与段之间用**空行**分隔（一行一段）。不要小标题、不要编号。
5. **写完必须自查（逐项做，别跳过）**：
   - ① 段数 = 清单条数吗？且落在 **10–15 段**内？
   - ② 逐段数句数：B2 必须 **4 句**；B1 必须 **2 句**。（最容易漏的就是这一项）
   - ③ 估全文词数：**B2 必须落 468–632；B1 必须落 323–437**（各段相加，不是每段平均值）。
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

# ── ② nodeSegment：分段（保留原文模式以「每段词数」为唯一依据） ──────
# 🔴 2026-09-22 二次重写（用户用真实 B1 母稿验收后拍板）。
#   上午那版把「每段词数」整个删掉了 —— 判断依据是「保留原文时词数不由我们控制」，
#   **这个判断是错的**：切开一段不改一个字，只是把切分点从段末移到句末，词数完全可控。
#   后果实测：用户导入 B1 母稿 What's in a Name?（8 个自然段、各 38–54 词、共 334 词），
#   模型原样照搬 8 段 —— 6 段越界（54/45/38/44/47/49），最后一段只有 18 词。
#   全文 334 词落在 B1 区间 323–437 内，**长度本身完全合格，问题只在切分点**：
#   按每段 31 词算本该切成 10–11 段。
#
# 🔴 用户口径（原话要点）：
#   · 「导入母稿的时候，字数反而没有每段段落的词数重要，其实字数不构成分段的影响」
#   · 「每段最后都是作为阅读卡片在 APP 上呈现给用户阅读的，所以不能太长也不能太短」
#   · 「均匀优先，可以根据内容大意等做微调整」
#   · 「允许小幅浮动」= **上下 5 个词**（B1 23–40 / B2+ 36–55）
#   · 段数 8–15 内不提示；模型切不准时由**代码自动兜底**（见 CLEAN_CODE），静默不标
#   ⇒ 「尽量靠近 12 段」这条在导入母稿场景下**废弃**，让位给每段规格。
#
# 🔴 2026-09-22 第三次修正 —— **精简模式也取消「正好 12 段」**：
#   用户原话：「精简模式下根据内容大意分段就行，不一定得定死 12 段，但是 4 个等级的段数
#   和每段的内容大意是必须一致的，这个不论是精简还是不精简模式都是如此。」
#   新口径：**全文字数优先**（精简 = 压进该档硬区间 323–437 / 468–632），
#   **段数按内容大意自然分，10–15 段只作兜底判定区间**（跑出去才判失败）。
#   数学依据：B1 323–437 ÷ 每段 28–35 ⇒ 10–15 段都可行；B2 468–632 ÷ 41–50 同理。
#   两端余量很窄（10 段时 B1 每段须 ≥32.3 词），真正宽松的落点是 11–13 段。
#   ⚠️ 正是「正好 12 段」这条让质检进不了精简模式（补切一刀就变 18 段）；区间化之后，
#      精简稿也能跑「段数兜底」了（只调段数、不按长度重排，见 CLEAN_CODE 的 2b）。
SEGMENT_SYS = '''你是英语分级阅读内容编辑。把下面这段文字**按内容大意分段**，产出的段落骨架将供后续多个难度档共用。

🔴 **先判断模式**（看下面的【是否需要精简】）：
- 值为 `true` ⇒ 只执行【模式 B】
- 其他（`false` / 空）⇒ 只执行【模式 A】

【模式 A · 保留原文】
正文**逐字保留**：你**只做切分**，不得改写、增删、调整任何一个词。

🔴 **切分依据只有一个：每段词数。** 全文字数**不参与**判断。
（这些段落之后会作为**阅读卡片**在 APP 上呈现给学生，太长太短都不行。）

1. **每段目标 = 该档规格**，允许上下浮动 5 个词：

   | 母稿档位 | 每段目标 | 可接受范围 |
   |---|---|---|
   | B1 | **28–35 词** | 23–40 词 |
   | B2+ | **41–50 词** | 36–55 词 |

2. **怎么切**：
   - **只在句子末尾切**（句号 / 问号 / 感叹号之后），**绝不在一句话中间切**。
   - **均匀优先**：让各段长度尽量接近区间中点（B1 约 31 词），哪里切更均衡就切哪里。
   - **可按内容大意微调**：某处正好是话题转折，即使词数略有偏差也优先在那里切。
3. **原文的自然段只是参考，不是边界**：一段太长就切成两段/多段；两段都太短就合并。
   ⚠️ 照搬原文的自然段是**错误**的 —— 原文一段 50 词，就必须拆成约 31 + 19 或两段各 25。
4. **段数不用凑**：段数 = 全文词数 ÷ 每段目标，自然算出来是多少就是多少（大约 8–15 段）。
   不要为了凑某个段数把段落拉长或切碎。
5. **标题必须剔除，不得进入段落骨架**：
   - 若【标题】字段非空，正文里与之相同（或高度相似）的那一行就是标题，**直接丢弃**。
   - 即便【标题】字段为空，正文**第一行/第一段如果是标题**（极短、独立的名词短语、
     不是完整句、与后文话题独立），也**必须丢弃**，不作为第一段。
   - 不要保留原文的小标题、编号、markdown 标记（`#`、`*`、`-` 等）。

🔴 **标题定义**：标题 = 一个孤立的短语（如 `Making money from your spare room`），
   它**不是一句话**（没有主语+谓语结构的完整陈述），是文章的题目。正文第一段往往
   才是真正的开头（如 `If a stranger offered you money...`）。务必分清「标题」和「第一段正文」。

⚠️ 输出的所有段落**按顺序拼接起来必须等于原文，一个词都不差**（连标点都不改）。
   你唯一的自由是**决定在哪里断开**。

【模式 B · 精简稿】
上一步已按内容大意分好段（10–15 段、一行一段）—— **直接采用它的既有切分**：
1. **不要重新合并或拆分**。它就是按大意分的，段数落在 10–15 段即为正常，
   这不算"段数不对"。
2. 唯一例外：某段**明显超过**该档上限（B1 超 45 词 / B2 超 65 词）⇒ 在句子边界切一刀；
   切完若段数**超过 15**，就把相邻的短段合并回去 —— **保证最终仍在 10–15 段内**。
3. 只做切分，不得改写用词。

【母稿档位】{{#nodeStart.level#}}
【是否需要精简】{{#nodeStart.need_simplify#}}
【标题】（单独提供，若为空表示正文里可能混有标题需要自行识别剔除）：{{#nodeStart.title#}}

【正文】
{{#nodeFinal.final_text#}}

【输出格式】只输出 JSON，不要 markdown 代码块，不要任何解释：
{"segments": ["第一段原文", "第二段原文", "第三段原文"]}'''

# ── ③ nodeClean：解析分段结果 + 质检程序 ────────────────────────────
# 🔴 2026-09-22 新增质检程序。用户拍板「要自动兜底，但界面上不用标出哪几段被调过」。
#   为什么必须有：模型按指令切分的稳定性只有六七成（实测 8 段里 6 段越界、错得离谱），
#   光靠提示词保证不了「每段落在 23–40」。
#
#   **两种模式跑两套逻辑**（2026-09-22 二次修正）：
#     · 保留原文 ⇒ 按长度重排（超切/短并/借邻居），把每段拉进 ±5 合格带；
#     · 精简稿   ⇒ **只做段数兜底**（>15 合并相邻最短、<10 切开最长），
#                  **不按长度重排** —— 精简稿是模型按内容大意切的，重排会切坏大意。
#
#   全程只移动切分点，**一个字都不改**（拼起来仍与原文逐字一致）。
CLEAN_CODE = r'''function main({ level, need_simplify, master, raw, fallback, title }) {
  const strip = (s) => String(s == null ? '' : s).replace(/```json/gi, '').replace(/```/g, '').trim();
  const wc = (t) => (String(t || '').match(/[A-Za-z][A-Za-z''-]*/g) || []).length;

  /* ---- 0) 标题兜底：即便模型没按指令剔除，代码也把「首段=标题」硬去掉 ----
     · 若有 title 入参且正文首段等于/包含该标题 → 直接丢弃首段；
     · 否则用标题形态启发式：首段词数极短（≤6 词）且是「非陈述句」（不含句末标点，
       或整段就是一个短语）→ 视为标题丢弃。
     这是给「母稿第①段混入标题 → 段数错位」的代码级防线，不依赖 LLM 自觉。 */
  const isTitleLine = (s) => {
    const t = String(s || '').trim();
    if (!t) return false;
    const n = wc(t);
    if (n > 6) return false;                 /* 标题不会太长 */
    if (/[.!?]$/.test(t)) return false;      /* 以句末标点结尾 → 是句子，不是标题 */
    const hasVerb = /\b(am|is|are|was|were|be|been|being|have|has|had|do|does|did|will|would|can|could|shall|should|may|might|must|say|said|says|start|started|starts|help|helps|helped|make|makes|made|use|uses|used|take|takes|took|go|goes|went|come|comes|came|get|gets|got|give|gives|gave|keep|keeps|kept|find|finds|found|think|thinks|thought|know|knows|knew|want|wants|wanted|need|needs|needed|try|tries|tried|look|looks|looked|work|works|worked|live|lives|lived|mean|means|believe|believes|believed|tell|tells|told|run|runs|walk|walks|eat|eats|see|sees|saw|watch|watches|read|reads|write|writes|play|plays|learn|learns|love|loves|like|likes|buy|buys|sell|sells|pay|pays|cost|costs|offer|offers|rent|rents|store|stores|share|shares|link|links|connect|connects)\b/i.test(t);
    if (hasVerb) return false;               /* 含谓语动词 → 更可能是句子开头 */
    return true;                             /* 极短、无句末标点、无谓语 → 标题 */
  };
  const stripTitle = (arr) => {
    const t = String(title || '').trim();
    if (arr.length && t) {
      const first = arr[0].trim();
      const norm = (x) => x.toLowerCase().replace(/[^a-z0-9]+/g, ' ').replace(/\s+/g, ' ').trim();
      const fn = norm(first), tn = norm(t);
      /* 🔴 守卫 1：title 经规范化后为空（纯中文/纯标点，如「粘贴的母稿」）时，
         不能进入「按 title 匹配」—— 否则 tn=""/indexOf("")==0 会误判"首段以标题开头"，
         再用 indexOf 找不到中文 title 返回 -1，slice(-1+len) 把正文开头几个字母切掉
         （实测：happy 被切成只剩 y）。 */
      const idx = first.toLowerCase().indexOf(t.toLowerCase());
      if (tn && fn && idx >= 0 && (fn === tn || fn.indexOf(tn) === 0)) {
        const rest = first.slice(idx + t.length).trim();
        if (rest) arr[0] = rest;             /* 标题和正文挤在一段 → 剥掉标题保留正文 */
        else arr.shift();                    /* 首段纯标题 → 整段丢弃 */
        return true;
      }
    }
    /* 无 title・title 无效・title 不匹配正文开头 时，用形态启发式 */
    if (arr.length && isTitleLine(arr[0])) { arr.shift(); return true; }
    return false;
  };

  /* ---- 1) 从模型输出里抠出 JSON（模型常带前后缀或 markdown 包裹） ---- */
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

  /* 首段标题剔除（代码硬兜底，在质检前做，避免标题被当正文段参与长度重排） */
  let titleDropped = false;
  if (segs.length) titleDropped = stripTitle(segs);

  const lv = String(level || '').trim();
  const spec = { B1: [323, 437, 28, 35], B2: [468, 632, 41, 50] }[lv] || null;
  const simp = String(need_simplify || '').trim().toLowerCase() === 'true';

  /* ---- 2) 质检程序：把每段拉进合格带（只移切分点，不改一个字） ----
     用户口径：导入母稿时**每段词数是分段的首要依据**，全文字数不参与决策；
     段落最后是 APP 上的阅读卡片，不能太长也不能太短。允许上下浮动 **5 词**。 */
  const TOL = 5;
  const lo = spec ? spec[2] - TOL : 0;      /* B1 → 23 · B2 → 36 */
  const hi = spec ? spec[3] + TOL : 0;      /* B1 → 40 · B2 → 55 */
  const mid = (lo + hi) / 2;

  /* 🔴 段数常规区间（两种模式共用）：10–15。
     2026-09-22 二次修正 —— 原先精简模式的硬指标是「正好 12 段」，用户拍板改为
     「**全文字数优先**（压进该档硬区间），段数按内容大意自然分，10–15 只作兜底判定区间」。
     数学依据：B1 硬区间 323–437 ÷ 每段 28–35 ⇒ 10–15 段都可行；B2 468–632 ÷ 41–50 同理。
     两端余量很窄（10 段时 B1 每段须 ≥32.3 词），真正宽松的落点是 11–13 段。 */
  const SEG_LO = 10, SEG_HI = 15;

  /* 按句末标点分句 —— 只在「句末标点 + 空格 + 疑似新句开头」处断，
     避免把 `Mac means "son of", ...` 这种引号/逗号切坏 */
  const packText = (text) => {
    const t = String(text).replace(/([.!?])\s+(?=["'(\[]?[A-Z0-9])/g, '$1\u0001');
    return t.split('\u0001').map((s) => s.trim()).filter((s) => s.length > 0);
  };

  /* 把若干句切成 k 段：k = round(总词数 ÷ 区间中点)，用 DP 最小化「各段偏离中点」的平方和
     （用户明确要求「均匀优先 —— 不能太长也不能太短」）。
     越界段额外加罚，保证 DP 优先选落在带内的切法。句子数 ≤ 10、k ≤ 5，DP 开销可忽略。
     用户原话：「每段最后都是作为阅读卡片在 APP 上呈现，所以不能太长也不能太短」。 */
  const dpSplit = (sents) => {
    const n = sents.length;
    if (n < 2) return [sents.join(' ')];
    const cnt = sents.map((s) => wc(s));
    const pre = [0];
    for (let a = 0; a < n; a++) pre.push(pre[a] + cnt[a]);
    const W = pre[n];
    let k = Math.max(1, Math.round(W / mid));
    if (W > hi && k < 2) k = 2;     /* 超上限就必须至少切一刀，让外层比较哪种更接近合格带 */
    if (k < 2) return [sents.join(' ')];
    k = Math.min(k, n);
    const dp = [], cut = [];
    for (let a = 0; a <= k; a++) {
      dp.push(new Array(n + 1).fill(Infinity));
      cut.push(new Array(n + 1).fill(-1));
    }
    dp[0][0] = 0;
    const cost = (len) => {
      const d = len - W / k;
      const pen = (len < lo ? (lo - len) * 40 : 0) + (len > hi ? (len - hi) * 40 : 0);
      return d * d + pen;
    };
    for (let a = 1; a <= k; a++) {
      for (let b = a; b <= n; b++) {
        for (let c = a - 1; c < b; c++) {
          if (dp[a - 1][c] === Infinity) continue;
          const v = dp[a - 1][c] + cost(pre[b] - pre[c]);
          if (v < dp[a][b]) { dp[a][b] = v; cut[a][b] = c; }
        }
      }
    }
    if (dp[k][n] === Infinity) return [sents.join(' ')];
    const parts = [];
    let b = n;
    for (let a = k; a >= 1; a--) {
      const c = cut[a][b];
      if (c < 0) return [sents.join(' ')];
      parts.unshift(sents.slice(c, b).join(' '));
      b = c;
    }
    return parts;
  };

  /* 越界量：段长离合格带有多远（带内为 0）。用它做「改还是不改」的判据 ——
     ⚠️ 不能只看「有没有越界」：B1 一段 44 词（超 4）比切成 30+14（14 严重偏短）更好，
     所以只在**窗口总越界量下降**时才采纳新的切法。 */
  const overOf = (len) => (len < lo ? lo - len : (len > hi ? len - hi : 0));
  const badSum = (arr) => arr.reduce((s, x) => s + overOf(wc(x)), 0);

  let autoFixed = 0;
  /* 🔴 两种模式都要质检，但**目标完全不同**（2026-09-22 二次修正）：
     · **保留原文** ⇒ 合格带 = 该档规格 ±5（B1 23–40）。段落是 APP 上的阅读卡片，
       不能太长也不能太短 ⇒ 按长度把每段拉进带内（只移切分点，一个字不改）。
     · **精简稿** ⇒ **只做段数兜底，不做长度重排**（见下面第二个 if）。精简稿是模型
       **按内容大意**切好的（用户明确要求「根据内容大意分段」），按长度重排会把大意边界切坏。
     ⚠️ 旧版这里是 `!simp &&`，理由写的是「精简模式契约是正好 12 段，一补切就变 18 段」——
        该理由只在「段数硬指标 = 12」时成立；段数改为 10–15 后它已消失。 */
  if (!simp && spec && segs.length > 1) {
    /* 逐处修，一次只动一个窗口，改完重新扫描（索引会变）。
       窗口候选：自身、与左邻、与右邻 —— 「借邻居一起重排」是必要的：
       例如 38 词 + 44 词两段单独都治不好，拼起来却能均匀切成 26/23/33 三段。 */
    let skip = {};
    for (let round = 0; round < 40; round++) {
      let hit = -1;
      for (let i = 0; i < segs.length; i++) {
        const k = wc(segs[i]);
        if ((k < lo || k > hi) && !skip[segs[i]]) { hit = i; break; }
      }
      if (hit < 0) break;

      /* 窗口候选从 ±1 扩到 ±2：只剩一段 18 词时，只看左右邻居往往无解
         （27+18=45 词切两段仍是 27/18，越界量没下降），拉上更外一层才腾得出空间。 */
      const cands = [];
      for (let L = 2; L >= 1; L--) { if (hit - L >= 0) cands.push([hit - L, hit]); }
      cands.push([hit, hit]);
      for (let R = 1; R <= 2; R++) { if (hit + R < segs.length) cands.push([hit, hit + R]); }

      let best = null;
      for (const c of cands) {
        const a = c[0], b = c[1];
        const win = segs.slice(a, b + 1);
        const before = badSum(win);
        const parts = dpSplit(packText(win.join(' ')));
        if (parts.length < 2) continue;
        const after = badSum(parts);
        if (after < before && (best === null || after < best.after)) {
          best = { a: a, b: b, parts: parts, after: after };
        }
      }
      if (!best) { skip[segs[hit]] = true; continue; }   /* 治不了（如整句超长），跳过这一段 */
      segs = segs.slice(0, best.a).concat(best.parts, segs.slice(best.b + 1));
      autoFixed++;
      skip = {};   /* 段落已变，之前的「治不了」判断全部作废 */
    }
  }

  /* ---- 2b) 精简稿质检：只调段数，不按长度重排 ----
     为什么不做长度重排：精简稿的段边界是模型**按内容大意**切出来的
     （用户 2026-09-22 明确「根据内容大意分段就行」），按长度重排会把大意的边界切坏。
     而精简模式的硬指标是「段数 10–15 + 全文字数落区间」，**每段词数只是软目标**
     （由前端标色提示，不成 fail）。所以这里只在段数跑出 10–15 时动手：
       · 多了（>15）⇒ 合并**相邻词数和最小**的两段（改动最小、最不伤大意）
       · 少了（<10）⇒ 把**最长且确实能切开**的一段按句边界均分两份
     全程只移动切分点，一个字都不改。 */
  if (simp && spec && segs.length > 1) {
    let guard = 0;
    while (segs.length > SEG_HI && guard++ < 40) {
      let bi = 0, bs = Infinity;
      for (let i = 0; i + 1 < segs.length; i++) {
        const s = wc(segs[i]) + wc(segs[i + 1]);
        if (s < bs) { bs = s; bi = i; }
      }
      segs = segs.slice(0, bi).concat([segs[bi] + ' ' + segs[bi + 1]], segs.slice(bi + 2));
      autoFixed++;
    }
    guard = 0;
    while (segs.length < SEG_LO && guard++ < 40) {
      let bi = -1, bw = -1;
      for (let i = 0; i < segs.length; i++) {
        const k = wc(segs[i]);
        if (k > bw && packText(segs[i]).length > 1) { bw = k; bi = i; }
      }
      if (bi < 0) break;   /* 全都切不动（整篇只有一句话）⇒ 交人处理，不硬凑 */
      const parts = dpSplit(packText(segs[bi]));
      if (parts.length < 2) break;
      segs = segs.slice(0, bi).concat(parts, segs.slice(bi + 1));
      autoFixed++;
    }
  }

  const per = segs.map((s) => wc(s));
  const total = per.reduce((a, b) => a + b, 0);

  /* ---- 3) 判定 ---- */
  /* 段数：**两种模式共用 10–15 这个常规区间**（2026-09-22 二次修正）。
     · 勾了精简 ⇒ 跑出区间判失败。精简稿的硬指标是「**全文字数落硬区间** + 段数在 10–15」。
     · 没勾精简 ⇒ 只提示、不判失败（保留原文时段数由内容决定，用户明确"别拦我"）。
     ⚠️ 旧版精简模式的判据是 `!== 12`（"正好 12 段"）—— 用户拍板改为
        「全文字数优先、段数按内容大意自然分，10–15 只作兜底判定区间」。 */
  const segBad = simp && (segs.length < SEG_LO || segs.length > SEG_HI);
  /* 当前仍越界的段数（含「一整句话超长、切不动」这种代码也治不了的） */
  const outOfBand = spec ? per.filter((k) => k < lo || k > hi).length : 0;

  const warns = [];
  if (!segs.length) warns.push('分段结果为空（模型没返回可用段落）');
  if (segBad && spec) warns.push('段数 ' + segs.length + ' 段跑出常规区间 '
    + SEG_LO + '–' + SEG_HI + ' 段（全文 ' + total + ' 词）');
  if (!spec) warns.push('未知档位');
  /* 词数越界只对精简稿才判 —— 保留原文的母稿长度本来就不由我们控制 */
  const wcBad = simp && !!spec && (total < spec[0] || total > spec[1]);
  if (wcBad && spec) warns.push(total < spec[0]
    ? ('总词数 ' + total + ' 低于 ' + lv + ' 下限 ' + spec[0])
    : ('总词数 ' + total + ' 超过 ' + lv + ' 上限 ' + spec[1]));
  /* 代码兜底也治不了的段：必须说出来（「一句话 60 词」这种情况无处可切）。
     ⚠️ 只在**保留原文**模式下报 —— 精简稿的段边界是模型按大意切的，
     这里跑的是「段数兜底」而不是长度重排（见 2b），拿 ±5 带去算越界数会误导成
     「连代码都没辙」。精简稿的每段词数由前端标色提示，不成 fail。 */
  if (!simp && spec && outOfBand > 0) {
    warns.push('有 ' + outOfBand + ' 段仍落在 ' + lo + '–' + hi + ' 词之外（句子太长、无处可切）');
  }
  /* 静默丢内容是 Bryan 最反感的 —— 分段若漏句，总词数会掉。
     ⚠️ 注意这里的 master 是**定稿正文**（精简模式下 = 精简稿本身），不是原始母稿，
     所以两种模式都适用：分段前后词数应当基本相等。 */
  const srcWc = wc(master);
  const lost = srcWc - total;
  if (srcWc > 0 && lost > Math.max(5, Math.round(srcWc * 0.03))) {
    warns.push('分段后总词数 ' + total + '，比正文 ' + srcWc + ' 少 ' + lost + ' 词 —— 可能有句子被漏掉');
  }
  const fb = String(fallback || '').trim().toLowerCase() === 'true';
  if (fb) warns.push('勾了精简但没拿到精简稿（模型未按指令输出），已自动回落为保留原文');

  /* 段数提示（非阻断）：只在跑出 10–15 这个常规区间时才说一句 */
  const note = (segs.length >= SEG_LO && segs.length <= SEG_HI) ? ''
    : ('切出 ' + segs.length + ' 段，超出常规区间 ' + SEG_LO + '–' + SEG_HI + ' 段'
       + '（全文 ' + total + ' 词；' + lv + (spec ? ' 要求 ' + spec[0] + '–' + spec[1] + ' 词、'
          + '每段 ' + spec[2] + '–' + spec[3] + ' 词' : '') + '）'
       + ' —— 请确认母稿长度与该档规格是否匹配');

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
    auto_fixed: String(autoFixed),
    out_of_band: String(outOfBand),
    title_dropped: titleDropped ? 'true' : 'false',
    /* 精简模式下「段数跑出 10–15」或「全文字数越区间」都算失败
       （精简的目的就是落进该档规格）；不精简模式 wcBad / segBad 恒为 false ⇒ 只提示不判失败。 */
    ok: (!segBad && !wcBad && !!spec && segs.length > 0) ? 'true' : 'false',
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
                {'label': '标题（单独摘出，正文不含标题）', 'variable': 'title', 'type': 'paragraph',
                 'required': False, 'max_length': 500, 'options': []},
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
            'desc': 'need_simplify=true 时提炼 10–15 条要点清单（条数由该档字数区间反推）；false 时**不做任何动作**（直接回空清单）',
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
            'desc': 'need_simplify=true → 按清单压缩成 10–15 段（全文字数落硬区间）；false → **逐字原样输出原文**',
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
            'title': '② 分段（以每段词数为准）',
            'desc': '保留原文时按该档「每段词数」在句末切分（段数自然算出）；精简稿则沿用它的既有切分（10–15 段）',
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
            'title': '③ 解析分段 + 质检兜底',
            'desc': '解析 segments；**代码自动补切/合并**把每段拉进合格带（只移切分点、不改字）；统计越界段',
            'selected': False,
            'code_language': 'javascript',
            'code': CLEAN_CODE,
            'variables': [
                {'variable': 'level', 'value_selector': ['nodeStart', 'level']},
                {'variable': 'need_simplify', 'value_selector': ['nodeStart', 'need_simplify']},
                {'variable': 'title', 'value_selector': ['nodeStart', 'title']},
                {'variable': 'master', 'value_selector': ['nodeFinal', 'final_text']},
                {'variable': 'raw', 'value_selector': ['nodeSegment', 'text']},
                {'variable': 'fallback', 'value_selector': ['nodeFinal', 'fallback']},
            ],
            'outputs': {k: {'children': None, 'type': 'string'} for k in
                        ('segments_json', 'seg_count', 'para_words', 'word_count',
                         'master_text', 'level', 'need_simplify', 'seg_note', 'fallback',
                         'auto_fixed', 'out_of_band', 'title_dropped', 'ok', 'warn')},
        }),
        shell('nodeEnd', 'end', 1740, 280, {
            'type': 'end',
            'title': '结束',
            'desc': '输出母稿段落骨架（供图 B 使用）',
            'selected': False,
            'outputs': [
                {'variable': k, 'value_selector': ['nodeClean', k]}
                for k in ('segments_json', 'seg_count', 'para_words', 'word_count',
                          'master_text', 'level', 'need_simplify', 'seg_note', 'fallback',
                          'auto_fixed', 'out_of_band', 'title_dropped', 'ok', 'warn')
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
