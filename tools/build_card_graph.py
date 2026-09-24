#!/usr/bin/env python3
"""
ReadPal · 「分级卡片」图构建脚本（2026-09-24）

来源：Bryan 提供的 `分级卡片工具包.zip` 里那份「粘贴到 Project 指令.md」（2924 字）。
      他在对话模式下用这套提示词 + deepseek-v4-flash 生成的结果**满意**，
      本图就是把这套提示词原样搬进 Dify —— **提示词一字不改结构，只做两处工程适配**。

【与图 A/B/C 的关系】
  完全独立的新链路，不接图 A/B/C、不共用节点代码：
      开始 → ① LLM（分级卡片提示词，deepseek-v4-flash） → ② code（解析兜底） → 结束
  刻意只留 1 个 LLM 节点 —— 这套逻辑的核心就是「一段提示词一次产出全部」。

【相对原工具包的两处工程适配（其余原样）】
  1. 「项目知识库里的 example_honesty/cards.json 是标准范例」→ 改为**内嵌范例**
     （Dify 侧没有那份知识库文件）。范例取自 `dify_graphs/card_example.json`，
     **A1- 级给全量 10 张卡 + 3 道题**（最完整的风格锚点），A2/B1 只示首张卡以控篇幅。
  2. 删掉「如果我说『重写 B1』或『修改 A2 Q2』，只输出那一部分的 JSON 片段」
     —— 那是对话模式的交互约定，在无对话的单次调用里会误导模型只吐片段。

【产出契约】
  cards_json  模型输出的原始 JSON（已做键归一化与宽松修复），前端负责渲染 + 质检
  parse_ok    'true' / 'false'
  parse_warn  解析告警（缺档、非法 JSON 等），**不静默**
  title       前端导入时填的标题优先；没填才用模型给的 title_en

【刻意不做的】
  · 不做质检 —— 质检是**纯代码**的活（build_cards.py 的 check()），搬在前端跑，
    本图不出现在任何「用 AI 检查 AI」的节点。
  · 不做字数重跑、不做保留清单、不做专名分档。

用法：
    python3 tools/build_card_graph.py [输出路径]
      · 默认 → dify_graphs/card.new.json
"""

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith('--') \
    else REPO / 'dify_graphs' / 'card.new.json'

# 唯一模型档：deepseek-v4-flash（Bryan 在对话模式下实测满意的那个模型）
MODEL = {
    'provider': 'langgenius/deepseek/deepseek',
    'name': 'deepseek-v4-flash',
    'mode': 'chat',
    # temp 0.25（原 0.45）：实测同一提示词连跑 3 次，同一档位的词数占比能给到
    #   42% / 45% / 48% —— 方差大到「回炉」都收不住（第 2 轮修好、第 3 轮又飘走）。
    #   降温度换确定性，比加轮次便宜。max_tokens 12000 是给「4 档卡片 + 12 道题带中文解析」留的裕量
    # （Bryan 母稿约 450 词时，输出约 3500–5000 token；母稿更长时还要涨）
    'completion_params': {'temperature': 0.25, 'max_tokens': 12000, 'thinking': False},
}

# ───────────────────── ① 范例（从 card_example.json 裁）─────────────────────
EX_FILE = REPO / 'dify_graphs' / 'card_example.json'


def build_example_block() -> str:
    """标准范例 = 工具包原文里的 example_honesty/cards.json，**整体原样内嵌**。

    🔴 2026-09-24 实测教训：若把范例裁成「A1- 全量 + A2/B1 只给首张卡」，
       模型会把 A2/B1 也当成"只写几张"，且**完全不管词数占比** ——
       实测 A1- 59% / A2 90% / B1 98%（目标 30–42 / 48–60 / 65–78），等于没压缩。
       范例是模型唯一的「该压缩到什么程度」的锚点，**不能裁**。
    """
    obj = json.loads(EX_FILE.read_text(encoding='utf-8'))
    # 切分已归代码（母稿由程序切好喂进来）⇒ 范例里的 b2_card_starts 是过时字段，
    # 留着会误导模型去「自己数卡片边界」。**必须从范例里去掉**，不能只改提示词正文。
    obj.pop('b2_card_starts', None)
    body = json.dumps(obj, ensure_ascii=False, indent=1)
    return ('下面是标准范例，**格式与质量都以它为准**：四档卡片数相同、第 N 张讲同一件事、'
            '每档词数占原文的比例都落在上面的硬指标区间内。\n```json\n' + body + '\n```')


# ───────────────── ② 提示词（工具包原文，仅两处工程适配）─────────────────
CARD_SYS_HEAD = """你是 CEFR 分级阅读的专家。我会发给你一篇英文原文（B2+），你把它降级改写成 A1-、A2、B1 三级，并为四个级别各出 3 道题。

## 输出要求
- 只输出一个 JSON 对象，前后不写任何说明，不要 markdown 代码块。
- B2+ 就是原文：**不要输出 B2+ 的正文**（母稿正文由程序原样填），B2+ 只需要 3 道题。
- 不要输出任何「卡片锚点 / 分卡位置」字段（如 `b2_card_starts`）—— 母稿怎么切分由程序决定，已经切好给你了。

## 🔴 回炉时只输出点名的档位（最高优先级，压过下面所有要求）
- 输入里出现「【本轮只输出这几档】」时，`levels` 里**只放它列出的档位**，**其余档位整个不要出现在 JSON 里**。
  这不是省略，是明确要求：没列出的档位程序会**原样保留** —— 多输出一档，反而会把已经达标的档改坏
  （实测：整篇重写式的回炉方差极大，同一档在第 2 轮修好、第 3 轮又被改跑）。
- 这种时候 `title_en` / `title_zh` / `topic_words` 照抄上一稿，不要重选、不要改写。
- 没出现那段说明时，才输出 A1- / A2 / B1 三档正文（B2+ 任何情况下都只出题、不出正文）。

## 卡片（母稿**已经切好**，不要再切）
- 上面给你的母稿**已经由程序切成 10 张卡**（标号 [1] 到 [10]），这就是四档共同的分卡骨架。
- 你**不需要切卡**，也不要改动这个划分。就按这 10 张卡的顺序逐张写，**第 i 张卡在四个级别里讲的必须是同一件事**。
- B2+ 就是母稿本身，母稿正文由程序填、**你不要输出 B2+ 的 cards** —— B2+ 只需要 3 道题。

## 各级硬指标
| | A1- | A2 | B1 |
|---|---|---|---|
| 每张卡压缩到**该张母稿卡**词数 | 30–42% | 48–60% | 65–78% |
| 单句词数 | 4–12 | 5–16 | 6–22 |
| 语法 | 一般现在/过去时、can、and/but/so/because/then；禁用从句、may/might/must、if、动名词作主语、被动 | 加上现在完成、will、should/must/have to、when/if/because 从句、who/that 短关系从句 | 加上 which/whose、第二类条件句、被动、间接引语、however/although |
| 专有名词 | 全文最多 3 个 | 保留主要人名 | 全保留 |

🔴 **词数照抄「逐卡预算」里的数字，不做估算。** 上面每一张卡都给了「词数 + 约几句」，
照抄着写就行，**不要逐句翻译** —— 逐句翻译一定超。
压缩只有三种手段：删掉次要细节、把复杂词换成简单词、把长句拆短。
一个细节都不想删，就一定会超。
⚠️ 实测经验（很重要）：凭感觉写，**几乎总是超 20% 以上**（A1- 实际写到 45%、A2 写到 63%、B1 写到 88%），
因为「把意思说全」的本能会压过数字。所以：写完**逐张数字数**，超一个词都要回头删到预算内再交。
🔴 **句数也要照预算写。** 低级别你天然会写 6–9 词的短句，于是「多写一句」就是超词数最常见的原因：
预算说「约 2 句」就写 2 句，别写 3 句。**句数是先写死的，词数是从句数长出来的。**

## 先压词数，再拆句（顺序不能反）
- **总词数是第一优先，句长是第二。** 先把每张卡压进比例区间，再在**这个词数预算内**拆句。
- 如果为了拆句而让词数超了，那是拆错了 —— 回去删内容，而不是让它超。
- 拆句时补主语（It / They / This）会**增加词数**，补了就从本张卡别处删掉同样多的词。

## 拆句（低级别最容易失分的地方）
- 单句词数是**硬上限**，不是建议：A1- ≤12、A2 ≤16、B1 ≤22。写完回头**逐句数字数**，超了就拆成两句再交。
- **逗号不算断句** —— 逗号连成的长串仍然算一句，别用逗号假装拆开了。
- 低级别（A1- / A2）**把原文的长直接引语改成间接引语**再拆句，不要为了保住引语而写出超长句。
  只有很短的格言式引语（6 词以内，如 honesty is the best policy）才原样保留并加引号。
- 🔴 **长列举四档都适用，不是只管低级别**（实测 B1 也照样写到 29 词）。原文里的**长列举**
  （冒号、分号或逗号引出的清单，形如 `…a Mediterranean diet: olive oil; oily fish, full of omega 3; whole grains; lots of fruits and vegetables.`）
  **不要整串照搬** —— 冒号和分号不算断句，整串会被算成一句，必然超长。拆成独立的短句：
  `He says the Mediterranean diet is best. Olive oil. Oily fish. Whole grains. Fruit and vegetables.`
  列举项都是事实，**一个都不许删**，但必须拆开写。

## 保真（最重要）
- 原文的核心观点和事实在每一级都要保留。降级只能通过删细节、换词、拆句来实现。
- 不得新增原文没有的事实。不得改变主体（谁对谁做了什么）。推测不能写成断言，反问不能写成肯定，作者的立场不能改。
- 从标题和原文核心中选 3–5 个主题词，写进 `topic_words`，每一级都必须出现，不得替换成同义的简单词。主题词第一次出现的那张卡，要给出足以推断词义的语境。
- ⚠️ **选词前先过一遍 A1-**：这个词在 A1- 里能不能自然用出来？像 depression / anxiety / evolution
  这类抽象词，A1- 只允许用 very sad / worry 表达 —— 那就**别选它当主题词**，换一个四档都能落地的词。
  （实测「A1- 缺少主题词」是最常见的失败项，根源是主题词本身在 A1- 的语法里无处安放。）
- 原文中的习语，低级别改用直白的说法。

## 题目
- 每一级 3 道题，每题 4 个选项。只能依据本级的正文出题，答案必须能在本级正文里找到。
- 题型：A1-/A2 考语境词义和细节；B1 考细节、原因和作者态度；B2+ 考比喻义推断、段落关系和写作意图。
- 答案字母要分散。干扰项要合理，其中至少一个来自文中其他位置的信息。
- 解析固定两句：`卡片X说"<本级正文原句>"，……所以X正确。X最容易误选，因为……`。引用的英文必须和本级正文逐字一致。
- 🔴 B2+ 的题干与解析里引用的英文，**必须从上面那 10 张卡里整句原样复制**（一个词都不要改）。
  B2+ 正文就是母稿原文，你若凭记忆改写，引文就会在正文里找不到 —— 这是实测最常见的失败项。

## 交稿前自查（逐条数一遍，不过就回去改）
1. `levels` 里 A1- / A2 / B1 的 `cards` 各 10 项，与母稿的 10 张卡一一对应；`levels['B2+']` 里**没有 cards**。
2. 逐张卡对照母稿的第 i 张卡，词数与句数都落在上面给的预算里 —— 不是「差不多」，是落进去。
   全文合计还有一条**死线**（A1- / A2 / B1 各自的绝对词数上限，见预算表最后一行），越线即不合格。
3. 把每张卡**逐句数字数**，没有一句超过该级上限。
4. 每一级都出现了 `topic_words` 里的全部词，且没有被换成同义简单词。
5. 每一级 3 道题、每题 4 个选项、答案字母分散、解析里的英文引文能在本级正文里逐字找到
   （B2+ 的引文要能在上面 10 张母稿卡里逐字找到）。

## JSON 格式
```json
{
 "title_en": "", "title_zh": "",
 "topic_words": ["", ""],
 "levels": {
  "A1-": {"cards": ["第1张卡的正文（不带编号）", "…共 10 项，与母稿的 10 张一一对应"],
          "questions": [{"q": "", "options": ["", "", "", ""], "answer": "B", "explanation": ""}]},
  "A2":  {"cards": [], "questions": []},
  "B1":  {"cards": [], "questions": []},
  "B2+": {"questions": []}          // ← B2+ **不要**写 cards，母稿正文由程序填
 }
}
```
"""

# 【回炉】fix_list 只在重跑时非空 —— 里面是**上一稿的量化差量**
#（例：A1- 全文 246 词，目标 132–186 词；A2 第⑥张卡有一句 25 词 > 上限 16 词）。
# 这是我们定的架构里「回合」的载体：把差量带回上一环，而不是让模型自由再写一遍。
CARD_USER = """【标题】{{#nodeStart.title_in#}}

【母稿（B2+）—— 已由代码切成下面这些卡，B2+ 的正文就是它们，逐字不要改】
{{#nodeStart.master_cards#}}

【每张卡的词数预算 —— 照这个数字写，写完逐张核一遍】
{{#nodeStart.master_budget#}}
{{#nodeStart.fix_list#}}
{{#nodeStart.fix_levels#}}
按上述要求改写并出题，只输出 JSON。"""


def build_prompts():
    ex = build_example_block()
    return CARD_SYS_HEAD + '\n' + ex + '\n', CARD_USER


# ───────────────────────── ③ 解析兜底（code）─────────────────────────
# 与图 C 的 PARSE_CODE 同一套「只修语法、不碰内容」的宽松修复，
# 差别只在输出契约（卡片字段）与告警项。
PARSE_CODE = r"""function main({ text, title_in, master_cards, fix_levels }) {
  const warn = [];
  const res = { cards_json: '{}', parse_ok: 'false', parse_warn: '', title: String(title_in || '').trim() };

  // ── 母稿卡片：**由代码从输入硬取**，模型碰不到 ────────────────────────
  // 项目既有原则：『必须逐字不变』的动作不能交给模型，用 code 节点硬取。
  // 输入形如「[1] 第一张卡正文\n[2] …」，这里按行剥掉序号。
  const b2 = String(master_cards || '').split('\n')
    .map(function (l) { return l.replace(/^\s*\[\d+\]\s*/, '').trim(); })
    .filter(function (l) { return l; });

  // ── 宽松修复：只修**语法**，不碰任何内容。① 字符串内裸换行 ② 尾随逗号
  const looseFix = function (s) {
    const why = [];
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

  let raw = String(text || '').trim();
  raw = raw.replace(/^```[a-zA-Z0-9]*\s*/, '').replace(/\s*```\s*$/, '').trim();
  const i0 = raw.indexOf('{'), j0 = raw.lastIndexOf('}');
  if (i0 < 0 || j0 <= i0) {
    res.parse_warn = '模型输出里找不到 JSON 对象（收到 ' + raw.length + ' 字符）';
    return res;
  }
  if (i0 > 0 || j0 < raw.length - 1) { warn.push('输出含 JSON 之外的文字，已裁剪'); raw = raw.slice(i0, j0 + 1); }

  let obj = null;
  try { obj = JSON.parse(raw); } catch (e) {
    const fx = looseFix(raw);
    if (fx.why.length) {
      try { obj = JSON.parse(fx.text); warn.push('JSON 含 ' + fx.why.join('、') + '，已自动修复'); }
      catch (e2) {
        res.parse_warn = 'JSON 解析失败（已试宽松修复：' + fx.why.join('、') + '）：' + String(e2 && e2.message || e2).slice(0, 140);
        return res;
      }
    } else {
      res.parse_warn = 'JSON 解析失败：' + String(e && e.message || e).slice(0, 160);
      return res;
    }
  }
  if (!obj || typeof obj !== 'object') { res.parse_warn = 'JSON 顶层不是对象'; return res; }

  // 键归一化：B2+ / B2P / B2 都认；A1- / A1 / A1_1 都认
  const nk = function (s) {
    let t = String(s === null || s === undefined ? '' : s).trim().toUpperCase().split(' ').join('');
    if (!t) return '';
    t = t.split('B2+').join('B2P').split('B2').join('B2P').replace(/[._·／\/\-]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
    if (t.indexOf('A1') === 0) return 'A1-';
    if (t.indexOf('A2') === 0) return 'A2';
    if (t.indexOf('B1') === 0) return 'B1';
    if (t.indexOf('B2P') === 0 || t.indexOf('B2') === 0) return 'B2+';
    return '';
  };
  const pick = function (src) {
    const out = {};
    if (src && typeof src === 'object' && !Array.isArray(src)) {
      Object.keys(src).forEach(function (k) { const kk = nk(k); if (kk) out[kk] = src[k]; });
    }
    return out;
  };

  const levels = (obj.levels && typeof obj.levels === 'object') ? pick(obj.levels) : {};
  const out = { title_en: String(obj.title_en || '').trim(), title_zh: String(obj.title_zh || '').trim(),
                topic_words: Array.isArray(obj.topic_words) ? obj.topic_words.map(function (w) { return String(w || '').trim(); }).filter(Boolean) : [],
                levels: {} };

  // 🔴 这里**只做结构归一化 + 报警**，不做任何内容修正，也不做质检（质检在前端代码里）
  const WANT = ['A1-', 'A2', 'B1', 'B2+'];
  // 回炉时页面会传 fix_levels（「本轮只输出这几档」）—— 缺档报警和 parse_ok 都要跟着**收窄**，
  // 否则「只重写 A2 / B1」会被自己判成「缺 A1-」而整轮失败。
  const asked = String(fix_levels || '').split(/[\/,、\s]+/)
    .map(function (s) { return nk(s); }).filter(function (s) { return s; });
  // ASKED = 本轮**应该出现**的档位。回炉只点名没过的档位，没点名的档位缺正文是**正常**的，
  // 既不能报警、也不能算 parse_ok 失败 —— 否则「只重写 A2 / B1」会被自己判成「缺 A1-」，
  // 整轮直接失败（页面表现为报错，而不是合并）。实测踩过。
  const ASKED = asked.length ? asked : ['A1-', 'A2', 'B1', 'B2+'];
  const n = b2.length;
  if (!n) { res.parse_warn = '没有收到切好的母稿卡片（上游没传 master_cards）'; return res; }
  WANT.forEach(function (lv) {
    const L = (levels[lv] && typeof levels[lv] === 'object') ? levels[lv] : null;
    if (!L && ASKED.indexOf(lv) >= 0) warn.push('缺 ' + lv + ' 一级');
    const src = L || {};
    let cards = Array.isArray(src.cards) ? src.cards.map(function (c) { return String(c == null ? '' : c).trim(); }).filter(Boolean) : [];
    if (lv === 'B2+') cards = b2.slice();      // ← 母稿正文由代码硬取，模型写的一律忽略
    const qs = Array.isArray(src.questions) ? src.questions.map(function (q) {
      const o = (q && typeof q === 'object') ? q : {};
      const opts = Array.isArray(o.options) ? o.options.map(function (x) { return String(x == null ? '' : x).trim(); }) : [];
      let ans = String(o.answer == null ? '' : o.answer).trim().toUpperCase();
      if (['A', 'B', 'C', 'D'].indexOf(ans) < 0) {
        const num = parseInt(o.answer, 10);
        ans = (!isNaN(num) && num >= 0 && num < 4) ? 'ABCD'.charAt(num) : '';
        if (!ans) warn.push(lv + ' 有一题 answer 无法识别（' + o.answer + '）');
      }
      return { q: String(o.q || '').trim(), options: opts, answer: ans,
               explanation: String(o.explanation || o.explain || '').trim() };
    }) : [];
    if (ASKED.indexOf(lv) >= 0) {            // 只有本轮点名的档位才做「缺正文 / 题数不对」的判定
      if (lv !== 'B2+' && !cards.length) warn.push('缺 ' + lv + ' 卡片正文');
      if (qs.length !== 3) warn.push(lv + ' 题目数 ' + qs.length + ' 道（期望 3 道）');
    }
    out.levels[lv] = { cards: cards, questions: qs };
  });

  res.cards_json = JSON.stringify(out);
  if (!res.title) res.title = out.title_en;
  const missing = ASKED.filter(function (lv) {
    if (lv === 'B2+') return false;          // 母稿正文由代码填，不参与缺档判定
    const L = out.levels[lv] || { cards: [] };
    return !L.cards.length;
  });
  if (missing.length) warn.push('本轮缺正文的档位：' + missing.join(' / '));
  res.parse_ok = (n && out.levels['B2+'].cards.length && !missing.length) ? 'true' : 'false';
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
    sys_prompt, user_prompt = build_prompts()
    nodes = []

    nodes.append(shell('nodeStart', 'start', 80, 300, {
        'type': 'start', 'title': '开始', 'selected': False,
        'desc': '接收**已由代码切好的母稿 10 张卡**（每行 [序号] 正文）与标题；切卡不交给模型',
        'variables': [
            {'label': '母稿：代码切好的 10 张卡（每行 [序号] 正文）', 'variable': 'master_cards',
             'type': 'paragraph', 'required': True, 'max_length': 30000, 'options': []},
            {'label': '每张卡的词数预算（代码算好，给模型照数字写）', 'variable': 'master_budget',
             'type': 'paragraph', 'required': False, 'max_length': 6000, 'options': []},
            {'label': '标题（可留空，留空则由模型给）', 'variable': 'title_in', 'type': 'text-input',
             'required': False, 'max_length': 300, 'options': []},
            {'label': '上一稿问题清单 + 上一稿正文（回炉时带，首次为空）', 'variable': 'fix_list',
             'type': 'paragraph', 'required': False, 'max_length': 20000, 'options': []},
            {'label': '本轮输出范围（回炉只重写这几档，其余由程序原样保留；首次为空）',
             'variable': 'fix_levels', 'type': 'paragraph', 'required': False,
             'max_length': 600, 'options': []},
        ],
    }, w=244, h=190))

    nodes.append(shell('nodeCard', 'llm', 420, 280, {
        'type': 'llm', 'title': '① 分级卡片生成', 'selected': False,
        'desc': '工具包提示词原样：一次产出 A1-/A2/B1 三级卡片 + 四档各 3 道题（deepseek-v4-flash）',
        'model': MODEL,
        'prompt_template': [
            {'role': 'system', 'text': sys_prompt},
            {'role': 'user', 'text': user_prompt},
        ],
        'context': {'enabled': False, 'variable_selector': []},
        'vision': {'enabled': False, 'configs': {'detail': 'low'}},
        'memory': None, 'answer': '',
    }, w=244, h=110))

    nodes.append(shell('nodeParse', 'code', 780, 280, {
        'type': 'code', 'title': '② 解析兜底', 'selected': False,
        'desc': 'JSON 解析 + 键归一化 + 缺档报警（只修语法，不碰内容；不做质检）',
        'code_language': 'javascript', 'code': PARSE_CODE,
        'variables': [
            {'variable': 'text', 'value_selector': ['nodeCard', 'text']},
            {'variable': 'title_in', 'value_selector': ['nodeStart', 'title_in']},
            {'variable': 'master_cards', 'value_selector': ['nodeStart', 'master_cards']},
            {'variable': 'fix_levels', 'value_selector': ['nodeStart', 'fix_levels']},
        ],
        'outputs': {k: {'children': None, 'type': 'string'} for k in
                    ('cards_json', 'parse_ok', 'parse_warn', 'title')},
    }))

    nodes.append(shell('nodeEnd', 'end', 1140, 280, {
        'type': 'end', 'title': '结束', 'selected': False,
        'desc': '输出卡片 JSON、解析状态与告警；质检由前端代码完成',
        'outputs': [
            {'variable': 'cards_json', 'value_selector': ['nodeParse', 'cards_json']},
            {'variable': 'parse_ok', 'value_selector': ['nodeParse', 'parse_ok']},
            {'variable': 'parse_warn', 'value_selector': ['nodeParse', 'parse_warn']},
            {'variable': 'title', 'value_selector': ['nodeParse', 'title']},
        ],
    }))

    edges = [
        edge('e-start-card', 'nodeStart', 'nodeCard', 'start', 'llm'),
        edge('e-card-parse', 'nodeCard', 'nodeParse', 'llm', 'code'),
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
    sys_prompt, user_prompt = build_prompts()
    print('节点 %d · 边 %d' % (len(d['graph']['nodes']), len(d['graph']['edges'])))
    print('  模型：%s/%s  参数：%s' % (MODEL['provider'], MODEL['name'],
                                    json.dumps(MODEL['completion_params'], ensure_ascii=False)))
    if errs:
        print('✗ 静态校验失败：')
        for e in errs:
            print('   -', e)
        return 1
    print('✅ 静态校验通过：引用可解析、无死节点、全部从 start 可达')
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
    print('✓ 已写出 %s (%d bytes)' % (OUT, OUT.stat().st_size))
    print('  提示词：system %d 字 + user %d 字 = %d 字（工具包原文 2924 字 + 内嵌范例）'
          % (len(sys_prompt), len(user_prompt), len(sys_prompt) + len(user_prompt)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
