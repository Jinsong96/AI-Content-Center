#!/usr/bin/env python3
"""
ReadPal · 图 B「母稿向下生成」构建脚本（2026-09-21）

背景：图 A 已经产出母稿的段落骨架（N 段）。本图按骨架**逐段改写**成更低的档位，
     出题 + 全套校验，产出直接进文章库。

App ID：d26cabd2-8837-4833-ab88-6f7aed015d4f

【复用策略】Bryan 明确要求「现有分级标准和所有判定逻辑都不变」⇒
  - 生成节点的提示词：**整体拷贝 GEN 图**的 nodeGenA1/A2/B1，只替换「素材区块」
    （原为 `{{#nodeClean.gist_lines#}}` 等，改为母稿段落骨架）
  - nodeValidate：**整体拷贝 GEN 图**，做 3 处精准替换
      a) SPEC 由「全文字数区间」改为「每段词数区间」（校验时 × N）
      b) ALL 按母稿档位收窄（B2 → B1/A2/A1；B1 → A2/A1）
      c) 段落对齐里的硬编码 12 → 动态 N
  - nodeQuiz / nodeGistCheck：拷贝 + 改档位引用

【流水线】
  nodeStart → nodeClean(解析骨架 + 算目标档) → nodeGenB1 / nodeGenA2 / nodeGenA1
            → nodeFix(量词数) → nodeCompress(收尾压缩) → nodeAgg(收集 + align_map)
            → nodeQuiz → nodeValidate → nodeGistCheck(整体主线)
            → nodeSemCheck(逐段大意核对) → nodeEnd

⚠️ 三档生成节点**都会跑**（Dify 是静态图，不做条件跳过）：
   母稿 B1 时 nodeGenB1 的结果会被 nodeAgg 丢弃 —— 代价是一次多余调用（约 8 秒），
   换来图的简单与稳定。若后续要省这几秒，再加 if-else 分支。

用法：
    python3 tools/build_graphB.py [输出路径，默认 dify_graphs/graphB.new.json]
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GEN_PATH = REPO / 'dify_graphs' / 'gen.new.json'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / 'dify_graphs' / 'graphB.new.json'

MODEL_PRO = {
    'provider': 'langgenius/deepseek/deepseek',
    'name': 'deepseek-v4-pro',
    'mode': 'chat',
    'completion_params': {'temperature': 0.45, 'max_tokens': 6000, 'thinking': False},
}
MODEL_FLASH_LOW = {
    'provider': 'langgenius/deepseek/deepseek',
    'name': 'deepseek-v4-flash',
    'mode': 'chat',
    'completion_params': {'temperature': 0.1, 'max_tokens': 2400, 'thinking': False},
}

# 母稿档位 → 要产的低档（顺序即 nodeAgg 收集顺序）
TARGETS = {'B2': ['B1', 'A2', 'A1'], 'B1': ['A2', 'A1']}

# 每段词数区间（与 GEN 的 SPEC 前两位一致；校验时 × 段数）
PER_PARA = {'A1': [11, 14], 'A2': [20, 22], 'B1': [28, 35], 'B2': [41, 50]}


def shell(nid, ntype, x, y, data, w=244, h=110):
    return {'id': nid, 'type': ntype, 'position': {'x': x, 'y': y},
            'positionAbsolute': {'x': x, 'y': y}, 'width': w, 'height': h, 'zIndex': 0, 'data': data}


def edge(eid, src, tgt, stype, ttype):
    return {'id': eid, 'source': src, 'target': tgt, 'type': 'custom',
            'sourceHandle': 'source', 'targetHandle': 'target', 'zIndex': 11,
            'data': {'isInIteration': False, 'sourceHandle': 'source', 'targetHandle': 'target',
                     'sourceType': stype, 'targetType': ttype, 'isInLoop': False}}


# ───────────────────────── nodeClean（图 B 版）─────────────────────────
CLEAN_CODE = r'''function main({ segments_json, level, style, avoid_words, source }) {
  const JS = (t, d) => { try { const v = JSON.parse(t || ''); return (v && typeof v === 'object') ? v : d; } catch (e) { return d; } };
  const segs = (JS(segments_json, []) || []).map((s) => String(s || '').trim()).filter(Boolean);
  const N = segs.length;
  const lv = String(level || '').trim().toUpperCase();
  const lvBig = lv === 'B2' ? 'B2' : 'B1';

  /* 要产的低档：母稿 B2 → B1/A2/A1-；母稿 B1 → A2/A1-（只能往下，不能往上） */
  const TARGETS = { B2: ['B1', 'A2', 'A1'], B1: ['A2', 'A1'] };
  const targets = TARGETS[lvBig] || [];

  /* 编号段落骨架：第 i 段 → 第 i 段，严格 1:1（与 GEN 的 gist_lines 同构，便于沿用同一套提示词） */
  const lines = [];
  segs.forEach((s, i) => { lines.push('【段 ' + (i + 1) + '】' + s); });
  const seg_lines = lines.join('\n\n');

  /* 主题摘要：取首段前若干词，供标题/校验引用（图 B 不再单独跑摘要节点） */
  const summary = segs.length ? segs[0].split(/\s+/).slice(0, 24).join(' ') : '';

  const avoid = JS(avoid_words, {});
  const pick = (k) => JSON.stringify(avoid[k] || avoid[k.toUpperCase()] || []);

  /* 🔴 每段词数规格与 GEN **完全一致、不改**（Bryan 2026-09-21 定案）。
     但图 B 的段数由母稿决定（不是固定 12 段）⇒ 全文区间必须**按 N 现算**，
     否则 N=11 时模型仍按 12 段的总量写，各档会集体超标（实测 A1- 23 词/段、B1 51 词/段）。 */
  const PER = { A1: [11, 14], A2: [20, 22], B1: [28, 35], B2: [41, 50] };
  const spec = {};
  Object.keys(PER).forEach((k) => {
    const lo = PER[k][0] * N, hi = PER[k][1] * N, tg = Math.round((lo + hi) / 2);
    spec[k] = { per: PER[k][0] + '–' + PER[k][1], lo: lo, hi: hi, tgt: tg };
  });
  const sp = (k, f) => String(spec[k][f]);

  return {
    seg_lines: seg_lines,
    seg_count: String(N),
    summary: summary,
    level: lvBig,
    level_big: lvBig,
    style: String(style || 'default'),
    source: String(source || '').trim(),
    targets_json: JSON.stringify(targets),
    target_count: String(targets.length),
    avoid_a1: pick('A1'), avoid_a2: pick('A2'), avoid_b1: pick('B1'), avoid_b2: pick('B2'),
    /* 各档「全文字数」按段数现算（供生成节点插值）*/
    spec_json: JSON.stringify(spec),
    a1_lo: sp('A1', 'lo'), a1_hi: sp('A1', 'hi'), a1_tgt: sp('A1', 'tgt'), a1_per: spec.A1.per,
    a2_lo: sp('A2', 'lo'), a2_hi: sp('A2', 'hi'), a2_tgt: sp('A2', 'tgt'), a2_per: spec.A2.per,
    b1_lo: sp('B1', 'lo'), b1_hi: sp('B1', 'hi'), b1_tgt: sp('B1', 'tgt'), b1_per: spec.B1.per,
    b2_lo: sp('B2', 'lo'), b2_hi: sp('B2', 'hi'), b2_tgt: sp('B2', 'tgt'), b2_per: spec.B2.per,
    /* 母稿正文（各段拼接）—— 它就是入库的高档稿件 */
    mat_text: segs.join('\n\n'),
    ok: (N >= 3 && targets.length > 0) ? 'true' : 'false',
  };
}'''

# ───────────────────── nodeFix（量词数 → 决定哪个档要压缩）─────────────────────
# 为什么要这一步：五轮实测证明「纯提示词控篇幅」到不了位 ——
#   模型按「每段句数 × 句长」铺段，且倾向写满上限，各档稳定超 10–60%。
#   ⇒ 改成「生成 → **实测逐段词数** → 带真实数字做一轮收尾压缩」，
#     这是唯一能既保住「每段词数严格按规格」、又不靠重跑碰运气的做法。
FIX_CODE = r'''function main({ t_b1, t_a2, t_a1, targets_json, seg_count }) {
  const JS = (t, d) => { try { const v = JSON.parse(t || ''); return (v && typeof v === 'object') ? v : d; } catch (e) { return d; } };
  const N = parseInt(seg_count, 10) || 0;
  const targets = JS(targets_json, []);
  const LABEL = { A1: 'A1-', A2: 'A2', B1: 'B1', B2: 'B2+' };
  const PER = { A1: [11, 14], A2: [20, 22], B1: [28, 35], B2: [41, 50] };
  const clean = (r) => String(r == null ? '' : r).replace(/Invalid JSON[^\n]*/g, '').replace(/```json/gi, '').replace(/```/g, '').trim();
  const parse = (r) => { const t = clean(r); const i = t.indexOf('{'), j = t.lastIndexOf('}'); if (i < 0 || j <= i) return null; try { return JSON.parse(t.slice(i, j + 1)); } catch (e) { return null; } };
  const paras = (r, k) => { const o = parse(r); if (o) { const c = o[k] || o.paras || o.paragraphs; if (Array.isArray(c) && c.length) return c.map((x) => String(x || '').trim()).filter(Boolean); } return clean(r).split(/\n\s*\n/).map((x) => x.trim()).filter(Boolean); };

  const RAW = { B1: t_b1, A2: t_a2, A1: t_a1 };
  const rep = {}, texts = {}, need = [];
  targets.forEach((k) => {
    const arr = paras(RAW[k], k);
    const lo = PER[k][0], hi = PER[k][1];
    const counts = arr.map((x) => (x.match(/[A-Za-z0-9'-]+/g) || []).length);
    const bad = [];
    counts.forEach((c, i) => { if (c < lo || c > hi) { bad.push((i + 1) + ':' + c); } });
    const tot = counts.reduce((a, b) => a + b, 0);
    /* 🔴 必须给出「超出上限多少词」的**硬差值** —— 只说「压到区间内」，模型会估着压、压不到位
       （实测：A1- 前一轮 174 词 vs 上限 154，交回来的还是 174，等于没压）。 */
    const over = Math.max(0, tot - hi * arr.length);
    const under = Math.max(0, lo * arr.length - tot);
    rep[k] = { per: lo + '-' + hi, lo: lo, hi: hi, n: arr.length, counts: counts,
               total: tot, total_lo: lo * arr.length, total_hi: hi * arr.length,
               must_cut: over ? String(over) : '', must_add: under ? String(under) : '',
               bad: bad.join(' ') };
    texts[k] = arr.join('\n\n');
    if (bad.length) { need.push(LABEL[k]); }
  });

  return {
    need: need.join('、'),
    need_count: String(need.length),
    /* 给压缩节点用的「逐段实测词数台账」—— 压缩必须看到真实数字才砍得准 */
    fix_json: JSON.stringify(rep),
    b1: texts.B1 || '', a2: texts.A2 || '', a1: texts.A1 || '',
  };
}'''


# ───────────────────────── nodeCompress（按实测台账收尾压缩）─────────────────────────
COMPRESS_SYS = '''上一步已经把母稿降档改写完成，但**篇幅普遍超标**。现在做收尾压缩。

【第一步：看实测台账】
{{#nodeFix.fix_json#}}

台账字段说明：`per` = 每段应有词数区间；`counts` = **每一段的实际词数**（按段号顺序）；
`total` = 全文实际词数；`total_lo`/`total_hi` = 全文应有区间；`bad` = 超标的「段号:词数」。

【需要压缩的档位】{{#nodeFix.need#}}
（若为空 ⇒ **逐字原样输出下面三段，一个字都不要动**，直接按输出格式返回。）

【任务】
只压缩**超标**的档位；**不超标的档位逐字原样输出**。

🔴 **每档必须砍掉的词数（硬指标，砍不够就是失败）**：
- `must_cut` 不为空 ⇒ 该档**至少要删掉这么多词**（如 `must_cut: "24"` ⇒ 全文至少减 24 词）。
- 压完之后再数一遍：没达到 `must_cut` 就继续删，直到达到为止。
- `must_add` 不为空 ⇒ 该档偏短，补回最有价值的一个细节。

压缩规则（这一轮**只做减法**，不换更难的词、不改难度、不重新创作）：
1. **段数一段都不能变** —— 第 i 段压缩后仍是第 i 段，讲的还是同一个意思。
2. 先把 `must_cut` 的总量**分派到各超标段**（超得多的段多删），再逐段照 `counts` 压到 `per` 区间内。
   优先删：举例、数字罗列、解释性从句、可省的形容词与状语。
   **不要为了压词数把句子写得不通顺** —— 宁可删掉一个次要信息点。
3. 每段保持 2 句（A1- 可以是 1 句主语 + 1 个短句），每句按该档的每句词数区间写。
4. A1- 特别提醒：**一段往往就是一个短句 + 一个更短的句子**，不要保留任何铺陈。

【A1- 原文】
{{#nodeFix.a1#}}

【A2 原文】
{{#nodeFix.a2#}}

【B1 原文】
{{#nodeFix.b1#}}

【输出格式：严格 JSON，只输出一个 JSON 对象，不要 markdown 代码块、不要解释、不要多余文字】
{"A1":["段1","段2",…],"A2":["段1","段2",…],"B1":["段1","段2",…]}
（每档的元素个数必须与该档原文的段数**完全一致**。）'''


# ───────────────────────── nodeAgg（图 B 版，精简）─────────────────────
AGG_CODE = r'''function main({ t_b1, t_a2, t_a1, targets_json, seg_count, mat_text, level, title_in, source, summary }) {
  const JS = (t, d) => { try { const v = JSON.parse(t || ''); return (v && typeof v === 'object') ? v : d; } catch (e) { return d; } };
  const N = parseInt(seg_count, 10) || 0;
  const targets = JS(targets_json, []);
  const LABEL = { A1: 'A1-', A2: 'A2', B1: 'B1', B2: 'B2+' };

  /* 🔴 key 必须传进来：生成节点的输出是 {"B1":["段1",…]} ——
     只认 o.paras / o.paragraphs 会把整块 JSON 当一段（踩过：各档 para_count 全是 1）。 */
  const cleanJSON = (raw) => String(raw == null ? '' : raw)
    .replace(/Invalid JSON[^\n]*/g, '').replace(/```json/gi, '').replace(/```/g, '').trim();
  const parseObj = (raw) => {
    const t = cleanJSON(raw);
    const i = t.indexOf('{'), j = t.lastIndexOf('}');
    if (i < 0 || j <= i) return null;
    try { return JSON.parse(t.slice(i, j + 1)); } catch (e) { return null; }
  };
  const splitParas = (raw, key) => {
    const t = cleanJSON(raw);
    const o = parseObj(t);
    if (o) {
      const cand = o[key] || o.paras || o.paragraphs;
      if (Array.isArray(cand) && cand.length) {
        return cand.map((x) => String(x || '').trim()).filter(Boolean);
      }
    }
    return t.split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean);
  };
  /* 模型自报的「第 i 段 ↔ 母稿第 i 段」映射（gist_map 字段名沿用 GEN，语义是段号轴） */
  const pickMap = (raw, key) => {
    const o = parseObj(raw);
    if (!o) return null;
    const m = o.gist_map || o.seg_map;
    const a = m && m[key];
    if (!Array.isArray(a) || !a.length) return null;
    return a.map((x) => (Array.isArray(x) ? x : [x]).map((n) => parseInt(n, 10)).filter((n) => n >= 1)).sort((p, q) => (p[0] || 0) - (q[0] || 0));
  };

  const RAW = { B1: t_b1, A2: t_a2, A1: t_a1 };
  const paras = {}, alignMap = {}, paraClean = {}, unused = [];
  const warns = [];

  targets.forEach((k) => {
    let arr = splitParas(RAW[k], k);
    let am = pickMap(RAW[k], k);
    paraClean[k] = arr.length;
    /* 段数硬约束：必须与母稿骨架一致（N 段） */
    if (N && arr.length !== N) {
      if (arr.length > N) { warns.push(LABEL[k] + ' 段数 ' + arr.length + ' → ' + N + '（截断 ' + (arr.length - N) + ' 段，末段内容已丢失）'); arr = arr.slice(0, N); }
      else { warns.push(LABEL[k] + ' 段数 ' + arr.length + ' 不足 ' + N + ' 段（无法补齐）'); }
    }
    paras[k] = arr;
    /* 段落对齐：优先用模型自报的映射；缺了就按「第 i 段 = 第 i 段」恒等。
       恒等不代表没问题 —— 段数是否对得上由 para_count / para_clean_count 管。 */
    if (am && am.length === arr.length) {
      alignMap[k] = am;
      if (am.length === N) {
        for (let i = 0; i < N; i++) {
          if ((am[i] || []).indexOf(i + 1) < 0) { warns.push(LABEL[k] + ' 第 ' + (i + 1) + ' 段↔母稿第 ' + (i + 1) + ' 段错位（实为 ' + JSON.stringify(am[i]) + '）'); break; }
        }
      }
    } else {
      const idm = []; for (let i = 0; i < arr.length; i++) idm.push([i + 1]);
      alignMap[k] = idm;
    }
  });

  /* 母稿本身也作为一篇进入产出（它就是入库的高档稿） */
  const matParas = String(mat_text || '').split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean);
  paras[level] = matParas;
  paraClean[level] = matParas.length;
  const am2 = []; for (let i = 0; i < N; i++) am2.push([i + 1]);
  alignMap[level] = am2;

  const allKeys = [level].concat(targets);
  const articles = {}, plain = {};
  allKeys.forEach((k) => {
    const arr = paras[k] || [];
    articles[k] = arr.join('\n\n');
    plain[k] = arr.join('\n\n');
  });

  return {
    title: String(title_in || '').trim() || 'Untitled',
    articles_json: JSON.stringify(articles),
    paras_json: JSON.stringify(paras),
    align_map: JSON.stringify(alignMap),
    para_count: JSON.stringify(Object.fromEntries(allKeys.map((k) => [k, (paras[k] || []).length]))),
    para_clean_count: JSON.stringify(paraClean),
    seg_count: String(N),
    levels_json: JSON.stringify(allKeys),
    levels_out: allKeys.join(','),
    map_warn: warns.join('；'),
    unused_facts: '[]',
    map_basis: JSON.stringify(Object.fromEntries(allKeys.map((k) => [k, 'seg']))),
    /* 身份完整性（授权链路专属）：版权来源必须留痕，缺了就会判 fail */
    identity_json: JSON.stringify({
      theme: String(summary || '').slice(0, 120),
      angle: '授权母稿逐段降档改写',
      shelf: String(source || '').trim() || '授权母稿',
      fit: level,
      provenance: '授权母稿向下改写 · 母稿档位 ' + level + ' · 来源 ' + (String(source || '').trim() || '未填'),
    }),
    /* 出题节点的素材：按档给出「档位 → 文章」的清单 */
    quiz_source: allKeys.map((k) => '=== ' + LABEL[k] + ' ===\n' + (articles[k] || '').slice(0, 4000)).join('\n\n'),
    is_owned: 'true',
  };
}'''


# ───────────────── nodeSemCheck：逐段大意一致性核对 ─────────────────
# 🔴 2026-09-22 新增。用户原话：「4 个等级的段数和每段的内容大意是必须一致的，
#    这个不论是精简还是不精简模式都是如此。」
#
# **为什么代码层保证不了「每段大意一致」**：
#   · 段数一致 ⇒ 是**结构性保证**（三档生成节点都用 {{#nodeClean.seg_count#}}，
#     nodeAgg 还有「多了就截断 + map_warn」的硬约束）——这块已经稳。
#   · 「第 i 段讲的是不是母稿第 i 段那件事」⇒ **代码验不了**。图 B 不像 GEN 那样抽事实，
#     没有独立的事实轴可以反查；nodeValidate 的「段落对齐」项查的是
#     「模型**自报**的 gist_map 格式」（长度 = N、第 i 项含 [i]），
#     而 gist_map 是模型自己写的 —— 它完全可以自报 [i] 而实际错位（实测就出过）。
#   ⇒ 只能补一个 LLM 节点做**独立的语义核对**，这是本链路唯一的办法。
#
# 口径（2026-09-22 与用户确认）：
#   · **只报对不上的段号，不判 fail、不拦入库**（报警性质，不进校验分母）
#   · 低档更简略 / 换例子 / 换说法 **都不算错位**；只有「换了一件事」「两段混讲」
#     「凭空新增」才算 —— 与 nodeGistCheck 的判据口径保持一致
#   · 输出要短（只列 bad 段号），这是在为链路耗时做取舍
#
# 与 nodeGistCheck 的分工：nodeGistCheck 判「整体主线有没有跑题」（4 档横向比一个基准），
# nodeSemCheck 判「逐段有没有错位」（各档纵向跟母稿第 i 段比）—— 互补，不重复。
SEM_SYS = '''你是英语分级阅读流水线上的「逐段对齐审核员」。同一篇已授权母稿被按骨架逐段改写成若干个更低难度档位。每一档都必须是 N 段，且**第 i 段必须讲母稿第 i 段的那件事**。你的任务：逐档逐段核对，**只挑出真正错位的段号**。

⚠️ 先建立正确预期：这些低档稿**本来就是大幅删减后的概要**（每段只有母稿的三分之一到一半）。
   降档 = 删次要信息、只留主干 —— 这是**设计目标**，不是错位。

【判据】只看「这一段的主信息是不是母稿同一段的那件事」—— **信息点级锁死**：
- 低档更简略、词更简单、句子更短 —— **不算错位**。
- 同一件事换了说法、换了例子 —— **不算错位**。
- **删掉了部分细节、删掉了多余的例子、删掉了次要的名字/数字/铺陈** —— **不算错位**。
  （例：母稿某段列了 Jackson/Anderson/Davidson 三个姓，低档只写 Jackson 一个 —— **不算错位**。）
- **只要该段还保留着母稿同一段的「核心实体或主题」就算对齐**（哪怕只剩一个例子、一个名字）。

🔴 **「信息点串位」必须算错位**（这是本次收紧的关键，最容易漏）：
  每段都有**归属它自己的核心实体/事实点**（人名、机构名、产品名、关键数字、关键事件）。
  如果某档的第 i 段**丢失了母稿第 i 段自己的核心实体**（比如第 i 段母稿讲「Airbnb + DogVacay」，
  这一段却写成了「很多公司租床/单车/车位」）；或者**把母稿相邻段（第 i-1 或 i+1 段）独有的
  实体/事实挪进了本段**、而本段该讲的实体不见了 —— **都算错位**，要列进 `bad`。
  （典型症状：A2 某段把「贵 160 元」这个点丢掉了，换成了上一段的「随时取物」；
  或把段 2 的「床/单车/车位」例子挪到段 3，而段 3 本该讲的 Airbnb/DogVacay 消失了。）

- **下列情况才算错位**：
  ① 把母稿第 i 段的内容讲成了**另一件事**（主信息整个换了，如把「姓氏来源」讲成「饮食文化」）；
  ② 该段**核心实体/事实点串位**：丢了本段该讲的实体（人名/机构/产品/关键数字）、
     或把**相邻段独有的实体/事实**挪进了本段（见上「信息点串位」）；
  ③ **凭空增加**了母稿里不存在的新事件、新结论、新数字、新例子；
  ④ **整段主信息被漏光**：该段母稿的核心意思在低档里**一个都没留下**（不是删多了，是删光了）；
  ⑤ 段数本身不对（某一档不是 N 段）—— 也要如实报告。

【不要报】下列都**不是**错位，**一律不要列进 bad**：
- 该段保留的例子比母稿少（只要还剩 ≥1 个相关例子或核心意思）；
- 母稿某段含两个信息点，低档只写了其中一个（**只要写的那一个仍属于同一段**）。
  ⚠️ 但「写了另一个、那个却属于相邻段」就不行 —— 那是「串位」，要报。

【核对范围】只核对下面列出的档位；**母稿档位本身（{{#nodeClean.level#}}）不在核对范围内，请跳过**。

输出严格 JSON（只输出 JSON，不要 markdown 代码块，不要任何解释）：
{"levels":[{"level":"B1","bad":[3,7],"notes":["第 3 段讲的是 X，母稿第 3 段讲的是 Y"]}],"bad_total":2,"summary":"一句话中文结论"}

字段说明：
- `levels`：每个待核对档位一条，按档位从高到低排列。
- `bad`：**只列出对不上的段号**（1-based、升序）。全部对得上就输出空数组 `[]`。
- `notes`：与 `bad` **一一对应**的中文说明，每条 30 字以内；`bad` 为空时同样输出 `[]`。
- ⚠️ **拿不准就不报**：这段只要还能对上母稿同一段的核心意思，就**不要**列进 `bad`。
  `bad` 是为「整段讲错事 / 凭空编造 / 主信息漏光」预留的，宁缺毋滥。
- `bad_total`：所有档位 `bad` 项数之和；全对时为 0。
- `summary`：一句话中文结论（如「3 档逐段对齐，无错位」或「B1 有 2 段错位」）。

【母稿段落骨架（共 {{#nodeClean.seg_count#}} 段，按 1 开始编号）】
{{#nodeClean.seg_lines#}}

【待核对的档位】
{{#nodeAgg.levels_out#}}

【各档正文段落】（JSON：键为档位，值为该档的段落数组；含母稿档，请跳过它）
{{#nodeAgg.paras_json#}}

请逐档逐段核对，输出严格 JSON。'''


def carry_node(nid, retitle=None, refs=None):
    """从 GEN 图整段拷贝一个节点，并按 refs 映射重接所有变量引用。

    refs: {'nodeClean.gist': 'nodeClean.seg_lines', ...} —— 对整个 data 做文本替换，
          这样 prompt_template 与 variables（value_selector）会一起被改正。
    """
    g = json.loads(GEN_PATH.read_text(encoding='utf-8'))
    node = json.loads(json.dumps([x for x in g['graph']['nodes'] if x['id'] == nid][0]))
    blob = json.dumps(node['data'], ensure_ascii=False)
    for a, b in (refs or {}).items():
        blob = blob.replace('{{#%s#}}' % a, '{{#%s#}}' % b)
        blob = blob.replace('"%s"' % a, '"%s"' % b)      # variables 的 value_selector
    node['data'] = json.loads(blob)
    if retitle:
        node['data']['title'] = retitle
    return node


def normalize_models(d):
    """把所有 LLM 节点统一到本文件当前的渠道（MODEL_PRO / MODEL_FLASH_LOW）。

    🔴 **必须做，别删**：图里有一部分节点是 `carry_node()` 从 GEN 图**整段拷贝**来的
    （nodeStyle / nodeTitle / nodeGenX / nodeQuiz / nodeGistCheck），
    它们带着 GEN 当时的 provider/model 字面量，**完全绕过本文件的 MODEL_* 常量**。
    不归一化就会出现「一半节点走 A 渠道、一半走 B 渠道」的混合图。

    2026-09-21 就是这么踩的：DeepSeek 官方余额归零后改 MODEL_* 常量切到硅基流动，
    图 A（全是自己写的节点）一次通过，图 B 仍 402 —— 因为**失败的是拷来的 nodeTitle**。
    判据：改完渠道后逐节点打印 provider/name，不能只看常量。
    """
    chan = {}
    for spec in (MODEL_PRO, MODEL_FLASH_LOW):
        key = 'pro' if 'pro' in spec['name'].lower() else 'flash'
        # 思考开关的参数名是**渠道相关**的：官方 `thinking` / 硅基 `enable_thinking`。
        # 写错会被 Dify 静默丢弃 → 模型按渠道默认跑（硅基默认开思考 → 慢 6.75 倍、
        # 实测 A1- 生成卡 205s 后摔 KeyError: 'choices'）。
        think = 'enable_thinking' if 'siliconflow' in spec['provider'] else 'thinking'
        chan[key] = (spec['provider'], spec['name'], think)
    n = 0
    for node in d['graph']['nodes']:
        dd = node.get('data') or {}
        if dd.get('type') != 'llm':
            continue
        m = dd.get('model')
        if not isinstance(m, dict):
            continue
        prov, name, think = chan['pro' if 'pro' in str(m.get('name', '')).lower() else 'flash']
        cp = m.get('completion_params')
        if isinstance(cp, dict):
            for src in ('thinking', 'enable_thinking'):
                if src != think and src in cp:
                    print('   ↻ %s: 思考参数 %s → %s' % (node.get('id'), src, think))
                    cp[think] = cp.pop(src)
                    n += 1
        if m.get('provider') != prov or m.get('name') != name:
            print('   ↻ %s: %s/%s → %s/%s' % (node.get('id'), m.get('provider'), m.get('name'), prov, name))
            m['provider'], m['name'] = prov, name
            n += 1
    return n


# 生成节点：素材来源从「大意骨架 / 细节池」换成「母稿段落骨架」
GEN_REFS = {
    'nodeClean.gist_lines': 'nodeClean.seg_lines',
    'nodeClean.level_material_b1': 'nodeClean.seg_lines',
    'nodeClean.level_material_b2p': 'nodeClean.seg_lines',
    'nodeClean.angle': 'nodeClean.summary',
}


def gen_node(nid, spec_note):
    node = carry_node(nid, refs=GEN_REFS)
    t = node['data']['prompt_template'][0]['text']

    # 段数：由固定 12 改为「与母稿骨架一致（N 由 nodeClean.seg_count 给）」
    # 🔴 一律「锚点 → 最终文案」整句替换，**不能用 '12 段' 这种碎片替换** ——
    #    碎片替换会把「固定 12 段」切成「固定 与母稿相同的段数」这种病句（已踩过一次）。
    N = '{{#nodeClean.seg_count#}}'
    SEG_OPS = [
        ('全篇固定 12 段（4 档一致，第 i 段对应第 i 条大意）',
         '全篇段数 = 母稿骨架段数（共 ' + N + ' 段，4 档完全一致）'),
        ('全篇 12–12 段（4 档段数必须完全一致）',
         '全篇 ' + N + ' 段（4 档段数必须完全一致）'),
        ('12 段（每段词数 = 全文词数 ÷ 段数，见写作标尺）',
         N + ' 段（每段词数 = 全文词数 ÷ 段数，见写作标尺）'),
        ('12 段里写 1 句的段落可以占到一半', N + ' 段里写 1 句的段落可以占到一半'),
        ('- 内层数组长度必须等于固定 12 段（4 档一致，第 i 段对应第 i 条大意）',
         '- 内层数组长度必须等于段数 ' + N + '（第 i 段对应母稿第 i 段）'),
        ('（固定 12 段，4 档一致，第 i 段严格对应第 i 条大意）',
         '（共 ' + N + ' 段，第 i 段严格对应母稿第 i 段）'),
        ('⑥ **段数**：正文必须是 **12 段**，且第 i 段严格对应第 i 条大意。写完先数一遍段落数、再数一遍大意条数 —— 两个数不相等就是不合格，必须重写。',
         '⑥ **段数**：正文必须是 **' + N + ' 段**，且第 i 段严格对应母稿第 i 段。'
         '写完先数一遍段落数、再数一遍母稿段落数 —— 两个数不相等就是不合格，必须重写。'),
        ('- **`gist_map`**：标明每一段依据了哪几条大意。内层数组长度必须等于固定 12 段，**第 i 段必须输出 `[i]`** —— 出现合并、跳号或少一项即判不合格。',
         '- **`gist_map`**：标明每一段依据了母稿的哪几段。内层数组长度必须等于段数 ' + N +
         '，**第 i 段必须输出 `[i]`** —— 出现合并（如 `[[1,2],…]`）、跳号或少一项即判不合格。'),
        ('- **第 12 段（最后一条大意）必须存在**',
         '- **最后一段（第 ' + N + ' 段）必须存在**'),
        ('第 12 段', '最后一段'),
        # ── 素材区块标题：从「大意骨架」改成「母稿段落骨架」──────────────
        # A1/A2 版
        ('素材大意骨架（**共 12 条，已按 1–12 编号；第 i 段只写第 i 条**，本档**只能依据下面的素材来写**，不得引入大意之外的信息）：',
         '母稿段落骨架（**共 ' + N + ' 段，按 1 开始编号；第 i 段只写第 i 段**，'
         '本档**只能依据下面的素材来写**，不得引入该段之外的信息）：'),
        # B1/B2+ 版
        ('素材大意骨架（**第 i 段只写【大意 i】那一条**；每条大意下缩进的「细节」是该条可用的真实素材，只能用其中确实存在的信息，不得编造）：',
         '母稿段落骨架（**共 ' + N + ' 段；第 i 段只写第 i 段**，只能用下面素材里确实存在的信息，不得编造）：'),
        ('素材大意骨架」按 1 开始编号（大意条号），每条大意下缩进的「细节」按事实卡号编号。',
         '母稿段落骨架」按 1 开始编号（段号）。'),
        ('不得引入大意之外的信息', '不得引入该段之外的信息'),
    ]
    for a, b in SEG_OPS:
        t = t.replace(a, b)

    # 兜底断言：段数文案里不允许再出现裸的「12 段」
    if '12 段' in t:
        bad = [l.strip()[:110] for l in t.split('\n') if '12 段' in l]
        raise RuntimeError('✗ %s 段数文案未清理干净：\n  %s' % (nid, '\n  '.join(bad)))

    # ── 全文目标：图 B 的段数由母稿决定，**不能再用 GEN 的 12 段定值** ────────
    # 实测：沿用 12 段的「目标 X 词 / 硬区间 a–b」时，N=11 会让模型按 12 段的总量写，
    #       各档集体超标（A1- 23 词/段 vs 规格 11–14、B1 51 词/段 vs 28–35）。
    # ⇒ 目标与区间都从 nodeClean 现算值插值。
    TGT = {
        'nodeGenA1': ('a1', '11–14', '150', '128–172'),
        'nodeGenA2': ('a2', '20–22', '240', '204–276'),
        'nodeGenB1': ('b1', '28–35', '380', '323–437'),
        'nodeGenB2p': ('b2', '41–50', '550', '468–632'),
    }
    pfx, per, tgt, rng = TGT.get(nid, (None, None, None, None))
    if pfx:
        lo = '{{#nodeClean.%s_lo#}}' % pfx
        hi = '{{#nodeClean.%s_hi#}}' % pfx
        tg = '{{#nodeClean.%s_tgt#}}' % pfx
        t = t.replace(tgt + ' 词', tg + ' 词')
        t = t.replace(rng, lo + '–' + hi)

    # 开头补「降档改写」的任务说明
    # 🔴 关键框架（2026-09-21 实测教训）：本链路的母稿是**完整原文**（每段 40–60 词），
    #    而目标档每段只有 11–50 词。若只说「降档改写」，模型会做「换词保信息」——
    #    结果各档集体超字数 1.5–1.8 倍（A1- 24.8 词/段 vs 规格 11–14、B1 50.5 vs 28–35）。
    #    ⇒ 必须把「降档 = 做减法」写成第一原则，并明确「只换词不删内容一定超字数」。
    head = ('你是英语分级阅读教学专家，专精 CEFR 分级改写。任务：把已获授权的英文母稿'
            '（难度 {{#nodeClean.level#}}）**降档改写**成 ' + spec_note + ' 严格达标的文章。\n\n'
            '🔴 **降档的本质是「大幅做减法」，不是「换词」。** 这是本链路最容易做错的地方：\n'
            '   - 母稿每一段是**完整原文**（往往 40–60 词、3–4 句），而目标档每段只有 '
            + (per or '本档规格要求的词数') + ' 词 —— **信息量必须砍掉一半以上**。\n'
            '   - 每一段**只保留最核心的一个意思**；该段的数字罗列、次要论证、铺陈与过渡句、'
            '**多余的并列举例一律删掉**。只换更简单的词、却不删内容，**一定超字数**。\n'
            '   - ⚠️ 但「做减法」≠「删光例子」：撑起该段意思的那个**具体例子必须留下**'
            '（删多余的，留最能说明问题的那一个）—— 见下方【篇幅 · 逐段硬约束】。\n'
            '   - 因此产出**不是母稿段的逐句翻译**，而是母稿段的**概要**：'
            '读者拿到的是这个意思，而不是原段的所有细节。\n'
            '   - 语言难度同时要降到位（更简单的词、更短的句子、更少的从句）。\n\n')
    m = re.search(r'你是英语分级阅读教学专家[^\n]*\n', t)
    if m:
        t = t[:m.start()] + head + t[m.end():]
    else:
        t = head + t

    # 素材区块标题再点一次「这是原料、要压缩」
    t = t.replace('母稿段落骨架（**共 ' + N + ' 段，按 1 开始编号；第 i 段只写第 i 段**，'
                  '本档**只能依据下面的素材来写**，不得引入该段之外的信息）：',
                  '母稿段落骨架（**共 ' + N + ' 段，按 1 开始编号；第 i 段只写第 i 段**）——'
                  '下面是母稿**原文**，是**待压缩的原料**，不是要你逐句改写：')
    t = t.replace('母稿段落骨架（**共 ' + N + ' 段；第 i 段只写第 i 段**，'
                  '只能用下面素材里确实存在的信息，不得编造）：',
                  '母稿段落骨架（**共 ' + N + ' 段；第 i 段只写第 i 段**）——'
                  '下面是母稿**原文**，是**待压缩的原料**，不是要你逐句改写：')

    # 逐段硬约束（图 B 专属；GEN 的 12 段语境在这里不成立）
    t += ('\n\n【篇幅 · 逐段硬约束（本链路：段数由母稿决定，**不是固定 12 段**）】\n'
          '- 母稿骨架共 {{#nodeClean.seg_count#}} 段 ⇒ 产出**也必须是这 {{#nodeClean.seg_count#}} 段**，'
          '第 i 段只写母稿第 i 段的内容。\n'
          '- **每一段都必须落在 ' + per + ' 词**（这是逐段硬约束，不是平均要求）。\n'
          '- 全文目标 = **' + tg + ' 词**（= ' + '{{#nodeClean.seg_count#}} 段 × 每段 ' + per + ' 词'
          ' ⇒ 硬区间 ' + lo + '–' + hi + ' 词）。\n'
          '- 逐段写完后**一段一段数词数**：某段超过上限 ⇒ 删掉该段的次要信息'
          '（多余的举例、个案罗列、解释性从句、铺陈）或把两句并成一句；'
          '**不许把两段合成一段，也不许补写母稿里没有的内容。**\n'
          '- 🔴 **删减的底线（内容保真）**：每段**至少要保留一个具体例子或专名**'
          '（一个人名、一个地名、一个具体动作、一个具体事物）。\n'
          '  **不许只剩抽象规则、一个实例都不留** —— 母稿第 i 段若靠某个例子撑起意思'
          '（如「Mac 意为“……之子”，故 MacDonald = Donald 之子」），\n'
          '  低档**必须留下这个例子**，可以删掉并列的其它例子，但**不能全删光**。\n'
          '  删多了不算达标，删光了算内容缺失。\n'
          '- 段数、每段词数、全文词数**三者必须同时成立** —— 只满足一个不算合格。\n')

    # ── 句数预算（2026-09-21 关键杠杆；2026-09-22 A1- 放宽为 1–2 句）────────
    # 教训链：光写「每段 11–14 词」模型数不准（三轮实测 24.8 → 18.7 词/段，始终超）。
    #   而 2026-09-21 在 GEN 上的六轮实测结论是：**模型是按「每段句数 × 句长」铺段的**。
    #   ⇒ 句数/句长要写成可数的预算。
    # 🔴 2026-09-22 修正（Bryan 验收：A2≈A1- 看着没区别）：
    #   此前这里给 A1- 也强加「每段恰好 2 句」，而 A1- 每段只有 11–14 词 ⇒ 每句只能 5–7 词，
    #   模型压不进 2 句就偷偷写 3 句（实测 A1- 每段 14–24 词、2–3 句，与 A2 撞车）。
    #   ⇒ A1- 改为 **每段 1–2 句**（与 GEN 图本身的口径一致），允许用 1 句交代信息量少的段，
    #     这才压得住总词数、与 A2 真正拉开。⚠️ GEN 拷贝来的原文里**本就写着「A1- 每段 1–2 句」**，
    #     旧版那句「本预算覆盖上文任何「每段 1–2 句」的表述：一律每段 2 句」是在**推翻原口径**、制造打架 —— 已删。
    # 句长区间的取法：2 句 × 句长 ≈ 每段词数区间（A2 2×10–11=20–22、B1 2×14–17=28–34）；
    #   A1- 取 6–9（1–2 句 × 6–9 = 6–18，覆盖 11–14 且允许单句段）。
    SENT = {'nodeGenA1': '6–9', 'nodeGenA2': '10–11', 'nodeGenB1': '14–17', 'nodeGenB2p': '21–24'}
    SB = SENT.get(nid)
    if SB and per:
        if nid == 'nodeGenA1':
            t += ('\n\n【每段句数预算 —— **照这个写，篇幅就会自动命中**】\n'
                  '- 本档**每段写 1–2 句**（信息量少的段写 1 句即可，**不要求每段都写 2 句**），'
                  '每句 **' + SB + ' 词** ⇒ 每段 ' + per + ' 词。\n'
                  '- 🔴 **不许写 3 句**：3 句会把篇幅顶上去、一定超上限。'
                  '句数错了，篇幅必错。\n'
                  '- 句数预算与篇幅是同一件事的两种说法 —— 满足句数预算就等于满足篇幅；'
                  '两者不能同时满足时**以每段词数为准**（宁可该段只写 1 句，也别撑出上限）。\n'
                  '- ⚠️ **段数一个都不能多**：只能写 {{#nodeClean.seg_count#}} 段。'
                  '多写一段会被聚合层砍掉末段，整篇从那里起与其它档错位。\n')
        else:
            t += ('\n\n【每段句数预算 —— **照这个写，篇幅就会自动命中**】\n'
                  '- 本档**每一段恰好写 2 句**，每句 **' + SB + ' 词** ⇒ 每段 ' + per + ' 词。\n'
                  '- 全篇 = {{#nodeClean.seg_count#}} 段 × 2 句 = **约 ' +
                  '{{#nodeClean.seg_count#}}×2 句**，正好落在 ' + lo + '–' + hi + ' 词。\n'
                  '- 🔴 **不许写 3 句**：3 句会把篇幅顶到 1.5 倍，一定超上限；'
                  '**也不许写 1 句**：会低于下限。句数错了，篇幅必错。\n'
                  '- 句数预算与篇幅是同一件事的两种说法 —— 满足句数预算就等于满足篇幅。\n'
                  '- ⚠️ 本预算**覆盖上文任何「每段 2–3 句」的表述**：本链路一律每段 2 句。\n'
                  '- ⚠️ 本预算里的**每句词数优先于**上文「平均句长 X–Y 词」的表述 —— '
                  '本预算的区间本就落在那个区间**之内**，所以两者不冲突，只是更紧、更可执行。\n'
                  '- ⚠️ **段数一个都不能多**：只能写 {{#nodeClean.seg_count#}} 段。'
                  '多写一段会被聚合层砍掉末段，整篇从那里起与其它档错位。\n')

    node['data']['prompt_template'][0]['text'] = t
    return node


def validate_code():
    """拷贝 GEN nodeValidate，做 3 处精准替换。"""
    g = json.loads(GEN_PATH.read_text(encoding='utf-8'))
    v = [x for x in g['graph']['nodes'] if x['id'] == 'nodeValidate'][0]['data']['code']

    # a) 签名：加 seg_count
    v = v.replace('function main({ articles_json, plain_json, factcard, identity, map_basis, align_map, para_count, para_clean_count }) {',
                  'function main({ articles_json, plain_json, map_basis, align_map, para_count, para_clean_count, seg_count, levels_json, identity_json }) {')
    # 图 B 没有事实卡与身份记录节点 ⇒ 这两项校验的数据源改为空（校验项会自行跳过）
    v = v.replace("JSON.parse(factcard || '{}')", "JSON.parse('{}')")
    v = v.replace("JSON.parse(identity || '{}')", "JSON.parse(identity_json || '{}')")
    v = v.replace('if (!isNaN(cleanN) && cleanN !== 12) {', 'if (!isNaN(cleanN) && cleanN !== SEGN) {')
    v = v.replace("try { idKeys = Object.keys(JSON.parse('{}')); } catch (e) { }",
                  "try { idKeys = Object.keys(JSON.parse(identity_json || '{}')); } catch (e) { }")

    # b) SPEC 改为「每段词数区间」（前两位是每段下限/上限，校验时 × N）
    old_spec = re.search(r'const SPEC = \{.*?\};', v, re.S).group(0)
    new_spec = ('const PER = {\n'
                '    A1: [11, 14, -1000, 400, 6, 9],\n'
                '    A2: [20, 22, 400, 750, 10, 13],\n'
                '    B1: [28, 35, 750, 1050, 14, 17],\n'
                '    B2: [41, 50, 1050, 1350, 18, 24]\n'
                '  };\n'
                '  const SEGN = parseInt(seg_count, 10) || 12;\n'
                '  const SPEC = {};\n'
                '  /* 🔴 必须保留全部 6 个字段：顺序 = [词数下限, 上限, 蓝思下限, 上限, 句长下限, 上限]。\n'
                '     只算前 2 个会让后 4 项变 undefined → 「句长校验」「蓝思校验」永远 fail（已踩）。 */\n'
                "  Object.keys(PER).forEach((k) => { SPEC[k] = [Math.round(SEGN * PER[k][0]), Math.round(SEGN * PER[k][1]), PER[k][2], PER[k][3], PER[k][4], PER[k][5]]; });")
    v = v.replace(old_spec, new_spec)

    # c) ALL 改为按母稿档位收窄，并**剔掉母稿档本身**
    #    🔴 2026-09-22 用户拍板：母稿只标注「授权母稿来源」入库，**不参与规格校验** ——
    #    它的长度不由我们控制（保留原文时可能远超该档区间），拿它去算分数只会制造噪音。
    #    nodeAgg 的 levels_json 第一项恒为母稿档（[level].concat(targets)），校验只跑后面的低档。
    #    实测：19 段长母稿跑完 44 项里 B2+ 那 11 项全在拿母稿计分，用户明确要求去掉。
    v = v.replace("const ALL = ['A1','A2','B1','B2'];",
                  "const ALL = (function(){ try { var a = JSON.parse(levels_json||'[]');"
                  " if(!Array.isArray(a) || !a.length) return ['A1','A2','B1','B2'];"
                  " var t = a.slice(1);   /* 第 0 项 = 母稿档，不参与校验 */"
                  " return t.length ? t : ['A1','A2','B1','B2']; } catch(e){ return ['A1','A2','B1','B2']; } })();")

    # d) 段落对齐块：12 → N
    v = v.replace('if (pars !== 12) { bad.push(\'段数 \' + (isNaN(pars) ? \'?\' : pars) + \'（应为 12）\'); }',
                  'if (pars !== SEGN) { bad.push(\'段数 \' + (isNaN(pars) ? \'?\' : pars) + \'（应为 \' + SEGN + \'）\'); }')
    v = v.replace('bad.push(\'模型原始段数 \' + cleanN + (cleanN > 12',
                  'bad.push(\'模型原始段数 \' + cleanN + (cleanN > SEGN')
    v = v.replace("'（超过 12，聚合层已砍掉尾部 ' + (cleanN - 12) + ' 段，末段内容已丢失）'",
                  "'（超过 ' + SEGN + '，聚合层已砍掉尾部 ' + (cleanN - SEGN) + ' 段，末段内容已丢失）'")
    v = v.replace(": '（不足 12，无法补齐）'));", ": '（不足 ' + SEGN + '，无法补齐）'));")
    v = v.replace('if (!pure || pure.length !== 12) {', 'if (!pure || pure.length !== SEGN) {')
    v = v.replace("bad.push('引用标注 ' + (pure ? pure.length : 0) + ' 项（应为 12）');",
                  "bad.push('引用标注 ' + (pure ? pure.length : 0) + ' 项（应为 ' + SEGN + '）');")
    v = v.replace('for (let i = 0; i < 12; i++) {', 'for (let i = 0; i < SEGN; i++) {')
    v = v.replace("checks.push({ name: '段落对齐', status: 'pass', detail: '12 段 ↔ 12 条大意严格 1:1' });",
                  "checks.push({ name: '段落对齐', status: 'pass', detail: SEGN + ' 段 ↔ 母稿 ' + SEGN + ' 段严格 1:1' });")

    # e) 去掉 GEN 专有的 4 档说明性注释里会误导的措辞
    v = v.replace('① 聚合层无条件把 >12 段 slice 回 12，所以 para_count **恒为 12**、',
                  '① 聚合层无条件把 >N 段 slice 回 N，所以 para_count **恒为 N**、')
    v = v.replace('判据：align_map 是 4 档折算到同一 gist 轴后的映射，正常情况**恒等于 [[1],[2],…,[12]]**。',
                  '判据：align_map 是各档折算到同一母稿段落轴后的映射，正常情况**恒等于 [[1],[2],…,[N]]**。')
    return v


def build():
    g = json.loads(GEN_PATH.read_text(encoding='utf-8'))
    old_quiz = [x for x in g['graph']['nodes'] if x['id'] == 'nodeQuiz'][0]
    old_gist = [x for x in g['graph']['nodes'] if x['id'] == 'nodeGistCheck'][0]

    # nodeStyle / nodeTitle：图 B 也需要（生成节点会引用 style_instruction 与 title）
    style = carry_node('nodeStyle')
    title = carry_node('nodeTitle', refs={'nodeClean.angle': 'nodeClean.summary'})

    # nodeQuiz：素材来源改为聚合后的文章；入参里补 levels_json / seg_count
    quiz = carry_node('nodeQuiz', retitle='③ 练习题生成',
                      refs={'nodeClean.summary': 'nodeClean.summary'})
    quiz['data']['variables'] = [
        {'variable': 'quiz_source', 'value_selector': ['nodeAgg', 'quiz_source']},
        {'variable': 'levels_json', 'value_selector': ['nodeAgg', 'levels_json']},
    ]

    # nodeGistCheck：大意基准改为「各档段落」+ 母稿骨架
    gist = carry_node('nodeGistCheck',
                      refs={'nodeClean.gist': 'nodeClean.seg_lines'})
    gist['data']['variables'] = [
        {'variable': 'paras_json', 'value_selector': ['nodeAgg', 'paras_json']},
        {'variable': 'gist', 'value_selector': ['nodeClean', 'seg_lines']},
    ]

    nodes = [
        shell('nodeStart', 'start', 60, 300, {
            'type': 'start', 'title': '开始', 'selected': False,
            'desc': '接收母稿段落骨架（来自图 A）、母稿档位、写作风格',
            'variables': [
                {'label': '母稿段落骨架（JSON 数组，来自图 A 的 segments_json）', 'variable': 'segments_json',
                 'type': 'paragraph', 'required': True, 'max_length': 20000, 'options': []},
                {'label': '母稿档位（人工标注）', 'variable': 'level', 'type': 'select',
                 'required': True, 'max_length': 48, 'options': ['B1', 'B2']},
                {'label': '授权来源（BBC Learning English / 超级阅读力 / 大愚出版社 / 其它）',
                 'variable': 'source', 'type': 'text-input',
                 'required': False, 'max_length': 120, 'options': []},
                {'label': '统一标题', 'variable': 'title_in', 'type': 'text-input',
                 'required': False, 'max_length': 200, 'options': []},
                {'label': '写作风格', 'variable': 'style', 'type': 'select',
                 'required': False, 'max_length': 48,
                 'options': ['hemingway', 'austen', 'ohenry', 'twain', 'dickens', 'orwell', 'shakespeare', 'default']},
                {'label': '上一稿超纲词（按档 JSON）', 'variable': 'avoid_words',
                 'type': 'paragraph', 'required': False, 'max_length': 4000, 'options': []},
            ],
        }),
        shell('nodeClean', 'code', 340, 300, {
            'type': 'code', 'title': '① 解析骨架', 'selected': False,
            'desc': '解析母稿段落、派生编号骨架 seg_lines、算出目标档列表',
            'code_language': 'javascript', 'code': CLEAN_CODE,
            'variables': [
                {'variable': 'segments_json', 'value_selector': ['nodeStart', 'segments_json']},
                {'variable': 'level', 'value_selector': ['nodeStart', 'level']},
                {'variable': 'style', 'value_selector': ['nodeStart', 'style']},
                {'variable': 'avoid_words', 'value_selector': ['nodeStart', 'avoid_words']},
                {'variable': 'source', 'value_selector': ['nodeStart', 'source']},
            ],
            'outputs': {k: {'children': None, 'type': 'string'} for k in
                        ('seg_lines', 'seg_count', 'summary', 'level', 'level_big', 'style', 'source',
                         'targets_json', 'target_count', 'avoid_a1', 'avoid_a2', 'avoid_b1', 'avoid_b2',
                         'spec_json',
                         'a1_lo', 'a1_hi', 'a1_tgt', 'a1_per',
                         'a2_lo', 'a2_hi', 'a2_tgt', 'a2_per',
                         'b1_lo', 'b1_hi', 'b1_tgt', 'b1_per',
                         'b2_lo', 'b2_hi', 'b2_tgt', 'b2_per',
                         'mat_text', 'ok')},
        }),
    ]

    for i, n in enumerate((style, title)):
        n['position'] = {'x': 340, 'y': 560 + i * 180}
        n['positionAbsolute'] = dict(n['position'])
    nodes.append(style)
    nodes.append(title)

    # 生成节点：三档都建（母稿 B1 时 nodeGenB1 的结果会在聚合层被丢弃）
    nodes.append(gen_node('nodeGenB1', 'B1'))
    nodes.append(gen_node('nodeGenA2', 'A2'))
    nodes.append(gen_node('nodeGenA1', 'A1-'))
    for i, n in enumerate((nodes[-3], nodes[-2], nodes[-1]), start=0):
        n['position'] = {'x': 620, 'y': 120 + i * 180}
        n['positionAbsolute'] = dict(n['position'])

    fixn = shell('nodeFix', 'code', 900, 40, {
        'type': 'code', 'title': '②-a 量词数', 'selected': False,
        'desc': '量出每档逐段实际词数，标出超标的段号（压缩节点的输入）',
        'code_language': 'javascript', 'code': FIX_CODE,
        'variables': [
            {'variable': 't_b1', 'value_selector': ['nodeGenB1', 'text']},
            {'variable': 't_a2', 'value_selector': ['nodeGenA2', 'text']},
            {'variable': 't_a1', 'value_selector': ['nodeGenA1', 'text']},
            {'variable': 'targets_json', 'value_selector': ['nodeClean', 'targets_json']},
            {'variable': 'seg_count', 'value_selector': ['nodeClean', 'seg_count']},
        ],
        'outputs': {k: {'children': None, 'type': 'string'} for k in
                    ('need', 'need_count', 'fix_json', 'b1', 'a2', 'a1')},
    })
    nodes.append(fixn)

    cmpn = shell('nodeCompress', 'llm', 900, 620, {
        'type': 'llm', 'title': '②-b 按实测压缩', 'selected': False,
        'desc': '带「每段实际词数」反馈做收尾压缩；已达标则逐字原样输出',
        'model': MODEL_PRO,
        'prompt_template': [{'role': 'system', 'text': COMPRESS_SYS}],
        'context': {'enabled': False, 'variable_selector': []},
        'vision': {'enabled': False, 'configs': {'detail': 'low'}},
        'memory': None, 'answer': '',
    })
    nodes.append(cmpn)

    nodes += [
        shell('nodeAgg', 'code', 1240, 300, {
            'type': 'code', 'title': '② 聚合', 'selected': False,
            'desc': '按母稿档位收集目标档产出 + 母稿本身，生成 align_map',
            'code_language': 'javascript', 'code': AGG_CODE,
            'variables': [
                # 收尾压缩之后的稿子（已按实测词数砍过一轮）；达标档由 nodeCompress 逐字原样透传
                {'variable': 't_b1', 'value_selector': ['nodeCompress', 'text']},
                {'variable': 't_a2', 'value_selector': ['nodeCompress', 'text']},
                {'variable': 't_a1', 'value_selector': ['nodeCompress', 'text']},
                {'variable': 'targets_json', 'value_selector': ['nodeClean', 'targets_json']},
                {'variable': 'seg_count', 'value_selector': ['nodeClean', 'seg_count']},
                {'variable': 'mat_text', 'value_selector': ['nodeClean', 'mat_text']},
                {'variable': 'level', 'value_selector': ['nodeClean', 'level']},
                {'variable': 'title_in', 'value_selector': ['nodeStart', 'title_in']},
        {'variable': 'source', 'value_selector': ['nodeClean', 'source']},
        {'variable': 'summary', 'value_selector': ['nodeClean', 'summary']},
            ],
            'outputs': {k: {'children': None, 'type': 'string'} for k in
                        ('title', 'articles_json', 'paras_json', 'align_map', 'para_count',
                         'para_clean_count', 'seg_count', 'levels_json', 'levels_out',
                         'map_warn', 'unused_facts', 'map_basis', 'quiz_source', 'is_owned',
                         'identity_json')},
        }),
    ]

    quiz['id'] = 'nodeQuiz'
    quiz['type'] = 'llm'
    quiz['position'] = {'x': 1520, 'y': 480}
    quiz['positionAbsolute'] = dict(quiz['position'])
    quiz['data']['title'] = '③ 练习题生成'
    nodes.append(quiz)

    val = shell('nodeValidate', 'code', 1520, 260, {
        'type': 'code', 'title': '④ 全套校验', 'selected': False,
        'desc': '字数（段数 × 每段区间）/ 句长 / 蓝思 / 词汇 / 语法 / 段落对齐',
        'code_language': 'javascript', 'code': validate_code(),
        'variables': [
            {'variable': 'articles_json', 'value_selector': ['nodeAgg', 'articles_json']},
            {'variable': 'plain_json', 'value_selector': ['nodeAgg', 'paras_json']},
            {'variable': 'levels_json', 'value_selector': ['nodeAgg', 'levels_json']},
            {'variable': 'align_map', 'value_selector': ['nodeAgg', 'align_map']},
            {'variable': 'para_count', 'value_selector': ['nodeAgg', 'para_count']},
            {'variable': 'para_clean_count', 'value_selector': ['nodeAgg', 'para_clean_count']},
            {'variable': 'seg_count', 'value_selector': ['nodeAgg', 'seg_count']},
            {'variable': 'map_basis', 'value_selector': ['nodeAgg', 'map_basis']},
            {'variable': 'identity_json', 'value_selector': ['nodeAgg', 'identity_json']},
        ],
        'outputs': {k: {'children': None, 'type': 'string'} for k in
                    ('validation_json', 'validation_pass', 'validation_score')},
    })
    nodes.append(val)

    gist['id'] = 'nodeGistCheck'
    gist['type'] = 'llm'
    gist['position'] = {'x': 1520, 'y': 40}
    gist['positionAbsolute'] = dict(gist['position'])
    nodes.append(gist)

    # nodeSemCheck：逐段大意一致性核对（新节点，见 SEM_SYS 的注释）
    # ⚠️ 用 flash 档：这是**核对**任务（不是创作），且输出很短（只列错位段号）。
    #    与 nodeGistCheck 同款模型，保持链路里两个审核节点的口径一致。
    sem = shell('nodeSemCheck', 'llm', 1800, 620, {
        'type': 'llm', 'title': '⑤ 逐段大意核对', 'selected': False,
        'desc': '逐档核对「第 i 段是否讲母稿第 i 段那件事」；只报错位段号，报警不拦入库',
        'model': MODEL_FLASH_LOW,
        'prompt_template': [{'role': 'system', 'text': SEM_SYS}],
        'context': {'enabled': False, 'variable_selector': []},
        'vision': {'enabled': False, 'configs': {'detail': 'low'}},
        'memory': None, 'answer': '',
    })
    nodes.append(sem)

    nodes.append(shell('nodeEnd', 'end', 1800, 300, {
        'type': 'end', 'title': '结束', 'selected': False,
        'desc': '输出母稿 + 各低档文章 / 题目 / 校验结果 / 逐段大意核对',
        'outputs': [
            {'variable': 'articles_json', 'value_selector': ['nodeAgg', 'articles_json']},
            {'variable': 'paras_json', 'value_selector': ['nodeAgg', 'paras_json']},
            {'variable': 'align_map', 'value_selector': ['nodeAgg', 'align_map']},
            {'variable': 'levels_json', 'value_selector': ['nodeAgg', 'levels_json']},
            {'variable': 'seg_count', 'value_selector': ['nodeAgg', 'seg_count']},
            {'variable': 'map_warn', 'value_selector': ['nodeAgg', 'map_warn']},
            {'variable': 'title', 'value_selector': ['nodeAgg', 'title']},
            {'variable': 'quiz_json', 'value_selector': ['nodeQuiz', 'text']},
            {'variable': 'validation_json', 'value_selector': ['nodeValidate', 'validation_json']},
            {'variable': 'validation_pass', 'value_selector': ['nodeValidate', 'validation_pass']},
            {'variable': 'validation_score', 'value_selector': ['nodeValidate', 'validation_score']},
            {'variable': 'sem_json', 'value_selector': ['nodeSemCheck', 'text']},
            {'variable': 'level', 'value_selector': ['nodeClean', 'level']},
        ],
    }))

    # ⚠️ 边 = 依赖。Dify 靠边决定执行顺序，**LLM 节点的 variables 是空的**，
    #    所以「生成节点要等 nodeStyle / nodeTitle」这件事必须由边来表达（照抄 GEN 拓扑）。
    edges = [
        edge('e-start-clean', 'nodeStart', 'nodeClean', 'start', 'code'),
        edge('e-start-style', 'nodeStart', 'nodeStyle', 'start', 'code'),
        edge('e-clean-title', 'nodeClean', 'nodeTitle', 'code', 'llm'),
    ]
    for k in ('B1', 'A2', 'A1'):
        edges += [
            edge('e-clean-%s' % k.lower(), 'nodeClean', 'nodeGen' + k, 'code', 'llm'),
            edge('e-style-%s' % k.lower(), 'nodeStyle', 'nodeGen' + k, 'code', 'llm'),
            edge('e-title-%s' % k.lower(), 'nodeTitle', 'nodeGen' + k, 'llm', 'llm'),
            edge('e-%s-fix' % k.lower(), 'nodeGen' + k, 'nodeFix', 'llm', 'code'),
        ]
    edges += [
        edge('e-fix-compress', 'nodeFix', 'nodeCompress', 'code', 'llm'),
        edge('e-compress-agg', 'nodeCompress', 'nodeAgg', 'llm', 'code'),
        edge('e-agg-quiz', 'nodeAgg', 'nodeQuiz', 'code', 'llm'),
        edge('e-agg-validate', 'nodeAgg', 'nodeValidate', 'code', 'code'),
        edge('e-agg-gist', 'nodeAgg', 'nodeGistCheck', 'code', 'llm'),
        edge('e-quiz-end', 'nodeQuiz', 'nodeEnd', 'llm', 'end'),
        edge('e-validate-end', 'nodeValidate', 'nodeEnd', 'code', 'end'),
        edge('e-gist-end', 'nodeGistCheck', 'nodeEnd', 'llm', 'end'),
        # nodeSemCheck 引用 nodeAgg 的两个输出，所以必须先有 agg→sem 这条边
        edge('e-agg-sem', 'nodeAgg', 'nodeSemCheck', 'code', 'llm'),
        edge('e-sem-end', 'nodeSemCheck', 'nodeEnd', 'llm', 'end'),
    ]

    return {'graph': {'nodes': nodes, 'edges': edges, 'viewport': {}},
            'features': {}, 'conversation_variables': [], 'environment_variables': []}


def static_check(d):
    g = d['graph']
    ids = [n['id'] for n in g['nodes']]
    errs = []
    if len(set(ids)) != len(ids):
        errs.append('节点 id 重复：' + ','.join(sorted({i for i in ids if ids.count(i) > 1})))
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
        for v in (n['data'].get('variables') or []):
            sel = v.get('value_selector')
            if not sel:
                continue
            if sel[0] not in allout or sel[1] not in allout.get(sel[0], set()):
                errs.append('%s 的入参 %s ← %s.%s 无法解析' % (n['id'], v['variable'], sel[0], sel[1]))
    return errs


def main():
    d = build()
    fixed = normalize_models(d)
    if fixed:
        print('   （以上 %d 个节点是 carry_node 从 GEN 拷来的，已归一到本图渠道）' % fixed)
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
    print('  推送：node tools/dify_push_graph.mjs --app=d26cabd2-8837-4833-ab88-6f7aed015d4f --graph=%s' % OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
