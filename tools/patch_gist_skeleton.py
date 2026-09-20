#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ReadPal · 把「4 档段落对齐」做成一等公民（2026-09-20）

════════════════════════════════════════════════════════════════════
解决的缺陷（见 docs/local-notes/39）
════════════════════════════════════════════════════════════════════
A1- 与其它三档逐段错位、且 A1- 常缺最后一段（信息来源）。根因链：

    ① A1/A2 吃 gist（12 条大意）、B1/B2+ 吃 facts_text（≤12 张卡）—— 两套基准不同源
    ② A1- 每段 12–20 词 × 12 段 = 零余量 → 遇到「重条」大意就拆段
    ③ 提示词只禁「写超长」，没禁「拆段」；硬自查五条里也没有「段数」
    ④ nodeAgg 无条件 slice 砍尾段，丢的正是最后一条
    ⑤ 告警写进 map_warn，但前端从不读它 → 静默
    ⑥ 校验层 10 项里没有「段落对齐」；⑨ 大意复核明文「低档覆盖不全不算失败」

════════════════════════════════════════════════════════════════════
本脚本做六件事（全部幂等，锚点命中失败即 raise，绝不盲改）
════════════════════════════════════════════════════════════════════
  FACT-1  nodeFact 提示词：每条 fact 增标 `gist` 归属号（1–12）
  FACT-2  nodeClean 增派生 buildGistSkeleton → gist_fact_map / gist_lines /
          level_material_b1 / level_material_b2p（+ 5 个 outputs）
  GEN-1   nodeClean 增入参 facts_raw + 同一套派生（+ 5 个 outputs）
  GEN-2   A1/A2 提示词：素材换「已编号大意骨架」（原为未编号 JSON）+ 禁拆段 +
          段数进硬自查（五条 → 六条）+ gist_map 严格 [i]
  GEN-3   B1/B2+ 提示词：素材换「大意骨架 + 每条挂细节」；输出 gist_map + fact_map
  GEN-4   nodeAgg：输出 align_map（4 档统一大意轴）/ fact_map（**语义统一成事实卡轴**）
  GEN-5   nodeValidate：新增第 11 项「段落对齐」硬失败；total_checks 10 → 11

用法
────
    python3 tools/patch_gist_skeleton.py            # 就地改 dify_graphs/{fact,gen}.new.json
    python3 tools/patch_gist_skeleton.py --check    # 只报会改哪里，不写文件
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
G_DIR = os.path.abspath(os.environ.get('DIFY_GRAPH_DIR') or os.path.join(_HERE, '..', 'dify_graphs'))
FACT_F = os.path.join(G_DIR, 'fact.new.json')
GEN_F = os.path.join(G_DIR, 'gen.new.json')

CHECK_ONLY = '--check' in sys.argv

# ════════════════════════════════════════════════════════════════════
# 共享 JS 片段：大意骨架派生（同时插进 FACT / GEN 的 nodeClean）
# ════════════════════════════════════════════════════════════════════
JS_SKELETON = r'''  /* ── 大意骨架统一（2026-09-20）─────────────────────────────────────
     4 档统一以 gist 的 12 条为段落骨架，facts 退化为「高档细节池」。
     事实卡的归属由 ① nodeFact 标注的 `gist` 字段给出（1–12），这里派生：
       gist_fact_map : 12 项，第 i 项 = 挂靠第 i 条大意的事实卡编号数组
       gist_lines    : 12 条大意的编号文本（给低档当段落骨架）
       level_material_b1 / _b2p : 大意骨架 + 每条下挂自己那些细节
     容错铁律（与全链路一致）：字段缺失 / 类型不对 → 一律降级为空，绝不抛错。 */
  const GN = 12;
  const buildGistSkeleton = (rawFact, fallbackText) => {
    const fo = (rawFact && typeof rawFact === 'object') ? rawFact : {};
    const fl = Array.isArray(fo.facts) ? fo.facts : [];
    const gl = Array.isArray(fo.gist) ? fo.gist : [];
    const txt = (x) => (typeof x === 'string' ? x : String((x && (x.en || x.zh)) || ''));
    const facts = fl.map((f) => ({
      en: String((f && f.en) || '').trim() || String((f && f.zh) || '').trim(),
      g: parseInt(f && f.gist, 10)
    })).filter((f) => f.en);
    /* 归属号纠偏：非整数 / 越界 / 缺省 → 按「已用最大号 + 1」顺序回填。
       绝不能因为模型漏标就把事实丢掉 —— 丢了细节，高档就写不出东西。 */
    let cursor = 1;
    facts.forEach((f) => {
      if (!(f.g >= 1 && f.g <= GN)) { f.g = cursor; }
      cursor = Math.max(cursor, f.g + 1);
    });
    /* 回填号越过 GN 时（模型**整体漏标**、而事实卡又多于 12 张）折回 1..GN 轮转。
       实测：14 张卡全部漏标 → 顺序回填成 1..14，第 13/14 张会因越界从骨架里消失。
       号溢出绝不能变成「事实卡被丢掉」。 */
    facts.forEach((f) => { if (f.g > GN) { f.g = ((f.g - 1) % GN) + 1; } });
    const map = [];
    for (let i = 1; i <= GN; i++) {
      map.push(facts.map((f, ix) => (f.g === i ? ix + 1 : 0)).filter(Boolean));
    }
    const gist = [];
    for (let i = 0; i < GN; i++) {
      const g = gl[i] || {};
      gist.push({ en: txt(g.en !== undefined ? g.en : g).trim(), zh: String((g && g.zh) || '').trim() });
    }
    /* 素材丢失兜底（只防事故，不改正常路径）：
       既没有 facts 也没有 gist 时（GEN 被单独调用、上游没传 facts_raw ——
       存量缓存里就有这种旧结果），若给了 fallbackText 就用它的编号行当骨架、
       高档材料退回该原文。绝不因为上游少传一个字段就让 B1/B2+「无米下锅」
       去凭空编内容 —— 那种塌陷没有任何报错，是最危险的一种。 */
    if (!facts.length && !gist.some((g) => g.en || g.zh)) {
      const rows = String(fallbackText || '').split(/\r?\n/)
        .map((s) => s.replace(/^\s*\d+\s*[.、)]\s*/, '').trim()).filter(Boolean);
      if (rows.length) {
        const fb = rows.join('\n');
        return {
          gist_fact_map: JSON.stringify(map),
          gist_lines: rows.map((t, ix) => (ix + 1) + '. ' + t).join('\n'),
          level_material_b1: fb,
          level_material_b2p: fb
        };
      }
    }
    const lines = [];
    for (let i = 1; i <= GN; i++) {
      lines.push('【大意 ' + i + '】' + (gist[i - 1].en || gist[i - 1].zh || '（本条无对应素材）'));
      map[i - 1].forEach((n) => lines.push('    细节：' + facts[n - 1].en));
    }
    const material = lines.join('\n');
    return {
      gist_fact_map: JSON.stringify(map),
      gist_lines: gist.map((g, i) => (i + 1) + '. ' + (g.en || g.zh)).join('\n'),
      level_material_b1: material,
      level_material_b2p: material
    };
  };
'''

SKEL_OUT_FIELDS = ['gist_fact_map', 'gist_lines', 'level_material_b1', 'level_material_b2p']

# ════════════════════════════════════════════════════════════════════
# 提示词补丁
# ════════════════════════════════════════════════════════════════════
DROP_SPLIT = (
    '\n- **一条大意 = 一段，严格 1:1**：既不得把一条大意拆成两段，也不得把两条大意并成一段。'
    '某条大意信息量超过本段词数上限时，**只保留主干、砍掉分支** —— 宁可少写一个细节，也**不许拆段**。'
    '\n- **第 12 段（最后一条大意）必须存在**：拆段会让段数变成 13 段，末尾那条就会被整段丢掉，'
    '整篇从拆段处起与其它档位**逐段错位**，读者切档时会看到内容跳位。'
)

SELF_CHECK_5 = '【必须自查的五条硬指标（篇幅与语言难度同等重要）】'
SELF_CHECK_6 = '【必须自查的六条硬指标（篇幅与语言难度同等重要）】'
SELF_CHECK_ADD = (
    '\n⑥ **段数**：正文必须是 **12 段**，且第 i 段严格对应第 i 条大意。'
    '写完先数一遍段落数、再数一遍大意条数 —— 两个数不相等就是不合格，必须重写。'
)

GISTMAP_OLD = '- 元素是该段所依据的大意条号（1-based，按升序排列）；第 i 段对应第 i 条大意（一对一）'
GISTMAP_NEW = ('- 元素是该段所依据的大意条号（1-based，按升序排列）；**第 i 段必须输出 `[i]`** —— '
               '出现 `[[1,2],…]` 这类合并、或跳号 / 少一项，即判不合格')

# A1/A2 原来直接塞 `{{#nodeClean.gist#}}`（未编号的 JSON 数组）——模型得自己数数组下标，
# 这是「段 i ↔ 大意 i」对应不稳的直接来源。换成已编号的 gist_lines。
A1A2_MATERIAL_OLD = ('素材大意（本档**只能依据下面的素材大意来写**，不得引入大意之外的信息）：\n'
                     '{{#nodeClean.gist#}}')
A1A2_MATERIAL_NEW = ('素材大意骨架（**共 12 条，已按 1–12 编号；第 i 段只写第 i 条**，'
                     '本档**只能依据下面的素材来写**，不得引入大意之外的信息）：\n'
                     '{{#nodeClean.gist_lines#}}')

FACT_TAIL_ANCHOR = '【两者的关系】facts 与 gist 是同一条素材的两种粒度，不是两份不同的内容：gist 就是 facts 去掉数字与专名之后的语义骨架。'
FACT_TAIL_ADD = '''

【事实卡挂靠大意（必须输出）】
10. **每条 fact 必须额外输出一个 `gist` 字段**：该事实归属的大意条号（整数 1–12）。
    - 归属判据：这条事实的语义落在哪一条大意上；**一条大意可以挂多条事实**（多对一）。
    - 所有 fact 的 `gist` 必须是 1–12 的整数，**不得缺省、不得为 null、不得超出范围**。
    - 12 条大意**每条都应至少挂到 1 条事实**；只有当某条大意确实只对应观点/态度、素材里没有对应事实时，才允许该条下面为空。
    - 这一步决定下游能否把「大意骨架」与「事实细节」对齐，标错会让 4 个难度档的段落全部错位。'''

B1B2_MATERIAL_OLD = '素材事实：\n{{#nodeClean.facts_text#}}'
B1B2_MATERIAL_NEW = ('素材大意骨架（**第 i 段只写【大意 i】那一条**；每条大意下缩进的「细节」是该条可用的真实素材，'
                     '只能用其中确实存在的信息，不得编造）：\n{{#nodeClean.level_material_b1#}}')
B1B2_MATERIAL_NEW_B2 = B1B2_MATERIAL_NEW.replace('level_material_b1', 'level_material_b2p')

B1B2_CITE_OLD = '''【事实卡引用标注（必须输出）】
上方「素材事实」按 1 开始编号。你必须在 JSON 中额外输出 fact_map，标明每一段依据了哪几张事实卡。
- 内层数组长度必须等于固定 12 段（4 档一致，第 i 段对应第 i 条大意）
- 元素是该段所依据的事实卡编号（1-based，按升序排列）；第 i 段对应第 i 条大意，每段最多引用 1 张卡；素材事实卡不足 12 张时，相邻段可复用同一张卡（一张卡的信息分摊到相邻 1–2 段），但不得把多张卡塞进同一段'''

B1B2_CITE_NEW = '''【引用标注（必须输出，两个键都要给）】
上方「素材大意骨架」按 1 开始编号（大意条号），每条大意下缩进的「细节」按事实卡号编号。
- **`gist_map`**：标明每一段依据了哪几条大意。内层数组长度必须等于固定 12 段，**第 i 段必须输出 `[i]`** —— 出现合并、跳号或少一项即判不合格。
- **`fact_map`**：标明每一段用到了哪几张事实卡（细节编号，1-based 升序）。该段没用到任何细节时给空数组 `[]`，**不得编造编号**。'''

B1_OUT_OLD = '{"B1":["段1",...,"段N"],"words":{"B1":["word — 中文释义"]},"fact_map":{"B1":[[1,2],...]}}'
B1_OUT_NEW = '{"B1":["段1",...,"段N"],"words":{"B1":["word — 中文释义"]},"gist_map":{"B1":[[1],[2],...]},"fact_map":{"B1":[[1,2],...]}}'
B2_OUT_OLD = '{"B2":["段1",...,"段N"],"words":{"B2":["word — 中文释义"]},"fact_map":{"B2":[[1,2],...]}}'
B2_OUT_NEW = '{"B2":["段1",...,"段N"],"words":{"B2":["word — 中文释义"]},"gist_map":{"B2":[[1],[2],...]},"fact_map":{"B2":[[1,2],...]}}'

# ════════════════════════════════════════════════════════════════════
# nodeAgg 补丁
# ════════════════════════════════════════════════════════════════════
AGG_PICK_OLD = '''      /* 引用标注：B1/B2+ 组输出 fact_map（基准=事实卡），A1/A2 组输出 gist_map（基准=大意条）。
         两者编号基准不同，必须分别记 basis —— 否则「未被引用」的审计会算错。 */
      const pickMap = (obj) => {
        if (!obj) return null;
        if (Array.isArray(obj[k])) return obj[k];
        const alt = k.replace('P_', '+_');
        return Array.isArray(obj[alt]) ? obj[alt] : null;
      };
      const fm = pickMap(o.fact_map);
      const gm = pickMap(o.gist_map);
      if (fm) factMaps[k] = { basis: 'fact', arr: fm };
      else if (gm) factMaps[k] = { basis: 'gist', arr: gm };'''
AGG_PICK_NEW = '''      /* 引用标注：2026-09-20 起 4 档都输出 gist_map（统一大意轴），
         B1/B2+ 额外输出 fact_map（细节轴）。两个都收下、后面分别归一 ——
         这样档间可比，且「段落↔事实卡」的溯源不会再串基准。 */
      const pickMap = (obj) => {
        if (!obj) return null;
        if (Array.isArray(obj[k])) return obj[k];
        const alt = k.replace('P_', '+_');
        return Array.isArray(obj[alt]) ? obj[alt] : null;
      };
      factMaps[k] = { gistArr: pickMap(o.gist_map), factArr: pickMap(o.fact_map) };'''

AGG_BASIS_OLD = '''      ALL.forEach((k) => {
        const info = factMaps[k];
        const basis = (info && info.basis === 'gist' && gist_count) ? 'gist' : 'fact';
        BASIS[k] = basis;
        raw_map[k] = normalizeMap(info ? info.arr : null, (paras[k] || []).length,
                                  basis === 'gist' ? gist_count : fact_count);
      });'''

AGG_BASIS_NEW = '''      /* 🔴 basis 必须**按档位固定**，不能「谁先返回就用谁」：
         B1/B2+ 现在会同时返回 gist_map（对齐用）与 fact_map（细节用），
         若按返回值判 basis，高档的事实一致性口径会被误降成低档口径（数字缺失不再判 fail）。
         固定口径：A1/A2 只用大意拍 → gist；B1/B2+ 吃细节卡 → fact。 */
      const BASIS_FIXED = { A1: 'gist', A2: 'gist', B1: 'fact', B2: 'fact' };
      /* fact 编号 → gist 编号 反查表（由 ① nodeFact 标注的挂靠关系派生） */
      const g2 = {};
      try {
        JSON.parse(GM.gist_fact_map).forEach((ids, i) => (ids || []).forEach((n) => { if (g2[n] === undefined) { g2[n] = i + 1; } }));
      } catch (e) { }
      const foldToGist = (ids) => {
        const out = [];
        (ids || []).forEach((n) => { const g = g2[n]; if (g >= 1 && g <= 12 && out.indexOf(g) < 0) { out.push(g); } });
        return out.sort((a, b) => a - b);
      };
      const expandFacts = (ids) => {
        const out = [];
        (ids || []).forEach((g) => (gfmCache[g] || []).forEach((n) => { if (out.indexOf(n) < 0) { out.push(n); } }));
        return out.sort((a, b) => a - b);
      };
      ALL.forEach((k) => {
        const info = factMaps[k] || {};
        const basis = BASIS_FIXED[k];
        BASIS[k] = basis;
        const n = (paras[k] || []).length;
        const gm = (Array.isArray(info.gistArr) && info.gistArr.length) ? info.gistArr : null;
        const fm = (Array.isArray(info.factArr) && info.factArr.length) ? info.factArr : null;
        /* 这一档是否**自己给出了**事实卡映射（而不是从大意展开的粗粒度版） */
        FACT_GIVEN[k] = !!fm;
        /* 大意轴（4 档统一口径）：优先用模型自己给的 gist_map；缺了就用 fact_map 折算 */
        const gRaw = gm ? normalizeMap(gm, n, 12)
                        : normalizeMap(fm, n, fact_count).map(foldToGist);
        /* 事实卡轴：优先用模型自己给的 fact_map；缺了就用 gist_map 展开（低档本来就没有事实卡） */
        const fRaw = fm ? normalizeMap(fm, n, fact_count)
                        : normalizeMap(gm, n, 12).map(expandFacts);
        alignMap[k] = gRaw;
        factFacts[k] = fRaw;
      });
      /* fact_map 的**字段名保留**，但语义统一成「事实卡轴」——
         这样前端 paraFactIds / factCiteHTML / factTraceHTML 无需分流基准就不会再张冠李戴。
         4 档同源：需要大意轴时一律读 align_map。 */
      fact_map = factFacts;'''

AGG_DECL_OLD = '  let fact_map = null, unused_facts = [], map_warn = [];'
AGG_DECL_NEW = ('  let fact_map = null, unused_facts = [], map_warn = [];\n'
                '  const alignMap = {}, factFacts = {}, gfmCache = {}, FACT_GIVEN = {};\n'
                '  try { JSON.parse(GM.gist_fact_map).forEach((ids, i) => { gfmCache[i + 1] = (ids || []); }); } catch (e) { }')

# 🔴 para_count 记的是**截断后**的段数（恒为 12），所以「模型写了 13 段 → 砍掉末段」
#    这个头号失败模式在 nodeValidate 里永远看不见。必须另报一个「清洗后、截断前」的计数。
AGG_CLEANDECL_OLD = '  const paras = {}, words = {}, factMaps = {}, raw_missing = [], para_warn = [];'
AGG_CLEANDECL_NEW = '  const paras = {}, words = {}, factMaps = {}, raw_missing = [], para_warn = [], cleanCount = {};'

AGG_CLEAN_OLD = '      const dropped = raw.length - arr.length;'
AGG_CLEAN_NEW = ('      const dropped = raw.length - arr.length;\n'
                 '      /* 清洗后、截断前 —— 「模型段数 ≠ 12」在这里还看得见（para_count 已经看不见了） */\n'
                 '      cleanCount[k] = arr.length;')

AGG_CLEANOUT_OLD = "    para_count: JSON.stringify(Object.keys(lengths).reduce((a, k) => { a[k] = lengths[k].paras; return a; }, {})),"
AGG_CLEANOUT_NEW = (AGG_CLEANOUT_OLD + "\n"
                    "    para_clean_count: JSON.stringify(cleanCount),")

# raw_map 是「按档位分叉」的中间变量：fact_map 统一成事实卡轴之后它成了死代码。
# ⚠️ 新文案必须带上这一行注释 —— 否则 `      fact_map = {};` 是旧文案的子串，
#    `new in txt` 恒真，第一次跑就会被判成「已是新文案」而静默跳过（已被 sub_once 拦下）。
AGG_RAWMAP_OLD = '      fact_map = {};\n      const raw_map = {};'
AGG_RAWMAP_NEW = ('      /* fact_map 恒为「事实卡轴」（4 档同源），不再需要按档位分叉的 raw_map */\n'
                  '      fact_map = {};')

# 🔴 旧代码把「各档自身基准」回写进 fact_map —— 正好抵消统一，必须删。
#    （实测：不删的话 A1/A2 的 fact_map 会退回大意号，前端按事实卡渲染就张冠李戴。）
AGG_GROUP_OLD = '''      /* 组内三档「段落一一对应」，事实卡绑定本应完全一致。
         模型偶有分歧，以组内第一个非空映射为准统一，并留下告警供人工确认。 */
      const size = (m) => (m || []).reduce((s, ids) => s + (ids ? ids.length : 0), 0);
      GROUP_KEYS.forEach((g) => {
        /* 4 档体系：每组 1 档，无需组内统一，直接采用各档自身的引用映射 */
        fact_map[g[0]] = raw_map[g[0]];
      });
      /* 「未被引用」只对以事实卡为基准的档位有意义：A1/A2 引的是大意条，混进来会把审计算错 */
      const used = {};
      ALL.forEach((k) => { if (BASIS[k] === 'fact') fact_map[k].forEach((ids) => ids.forEach((n) => { used[n] = 1; })); });'''

AGG_GROUP_NEW = '''      /* 🔴 绝不能再用「各档自身基准」回写 fact_map（旧代码 GROUP_KEYS.forEach 那三行）——
         那正好抵消了统一：A1/A2 的 fact_map 会从「事实卡轴」退回「大意号」，
         前端按事实卡渲染时就又张冠李戴了。需要大意轴一律读 align_map。 */
      /* 「未被引用」只统计**自己给出了事实卡映射**的档位（B1/B2+）：
         A1/A2 的 fact_map 是从大意展开出来的，粒度粗，混进来会把审计算松。 */
      const used = {};
      ALL.forEach((k) => { if (FACT_GIVEN[k]) fact_map[k].forEach((ids) => ids.forEach((n) => { used[n] = 1; })); });'''


AGG_OUT_OLD = "    fact_map: fact_map ? JSON.stringify(fact_map) : '',"
AGG_OUT_NEW = ("    fact_map: fact_map ? JSON.stringify(fact_map) : '',\n"
               "    align_map: JSON.stringify(alignMap),")

# ════════════════════════════════════════════════════════════════════
# nodeValidate 补丁
# ════════════════════════════════════════════════════════════════════
VAL_SIG_OLD = 'function main({ articles_json, plain_json, factcard, identity, map_basis }) {'
VAL_SIG_NEW = ('function main({ articles_json, plain_json, factcard, identity, map_basis, '
               'align_map, para_count, para_clean_count }) {')

VAL_TOTAL_OLD = '    total_checks: ALL.length * 10,'
VAL_TOTAL_NEW = '    total_checks: ALL.length * 11,'

VAL_ANCHOR = '    let idKeys = [];'
VAL_ADD = '''    /* 段落对齐（v1 · 2026-09-20）：这一项是「A1- 与其它档错位」的唯一机械拦截点。
       为什么必须单独有一项 ——
         ① 聚合层无条件把 >12 段 slice 回 12，所以 para_count **恒为 12**、
            「段数不一致」在最终产物里根本看不见 → 另取 para_clean_count（截断前）补上，
            否则「拆段 → 砍末段」这个头号失败模式仍会静默通过；
         ② nodeAgg 明确「4 档体系：每组 1 档，无需组内统一」，各档自报映射、互不校验；
         ③ ⑨ 大意复核明文「低档覆盖不全不算失败」。
       判据：align_map 是 4 档折算到同一 gist 轴后的映射，正常情况**恒等于 [[1],[2],…,[12]]**。
       任何合并 / 跳号 / 少一项，都意味着「第 i 段讲的不是第 i 条大意」→ 切档会跳位。 */
    {
      const am = JS(align_map, {});
      const pc = JS(para_count, {});
      const cc = JS(para_clean_count, {});
      const bad = [];
      const pure = Array.isArray(am[key]) ? am[key] : null;
      const pars = parseInt(pc[key], 10);
      if (pars !== 12) { bad.push('段数 ' + (isNaN(pars) ? '?' : pars) + '（应为 12）'); }
      const cleanN = parseInt(cc[key], 10);
      if (!isNaN(cleanN) && cleanN !== 12) {
        bad.push('模型原始段数 ' + cleanN + (cleanN > 12
          ? '（超过 12，聚合层已砍掉尾部 ' + (cleanN - 12) + ' 段，末段内容已丢失）'
          : '（不足 12，无法补齐）'));
      }
      if (!pure || pure.length !== 12) {
        bad.push('引用标注 ' + (pure ? pure.length : 0) + ' 项（应为 12）');
      } else {
        const off = [];
        for (let i = 0; i < 12; i++) {
          const ids = (pure[i] || []).map((x) => parseInt(x, 10));
          if (ids.indexOf(i + 1) < 0) { off.push('第' + (i + 1) + '段↔大意' + (i + 1) + '（实为 ' + JSON.stringify(ids) + '）'); }
        }
        if (off.length) { bad.push('错位 ' + off.length + ' 处：' + off.slice(0, 3).join('，')); }
      }
      if (bad.length) {
        fails.push('段落对齐: ' + LABEL[key] + ' ' + bad.join('；') + ' → 该档与其它档逐段错位，需重新生成');
        checks.push({ name: '段落对齐', status: 'fail', detail: bad.join('；') });
      } else {
        checks.push({ name: '段落对齐', status: 'pass', detail: '12 段 ↔ 12 条大意严格 1:1' });
      }
    }
'''

# nodeEnd 透出新字段
END_ADD_FIELDS = ['align_map', 'para_clean_count']


# ════════════════════════════════════════════════════════════════════
def sub_once(txt, old, new, label, report):
    """🔴 幂等判据必须用 `new in txt`，不能写 `new in txt and old not in txt`：
    有两处替换的新文案是以旧文案开头再追加澄清句（如提示词末尾追加规则），
    那种写法第二次跑会重复插入。

    🔴 反向护栏：**新文案不能是旧文案的子串** —— 那样 `new in txt` 会恒真，
    第一次跑就被判成「已是新文案」而静默跳过（踩过：`fact_map = {};` 是
    `fact_map = {};\\n const raw_map = {};` 的子串）。见到就直接报错，别让它静默。"""
    if new != old and new in old:
        raise RuntimeError('✗ 新文案是旧文案的子串，`new in txt` 会恒真导致静默跳过：%s' % label)
    if new in txt:
        report.append('  · %-46s 已是新文案，跳过' % label)
        return txt, False
    n = txt.count(old)
    if n != 1:
        raise RuntimeError('✗ 锚点命中 %d 次（应为 1）：%s\n---\n%s' % (n, label, old[:200]))
    return txt.replace(old, new, 1), True


def get(graph, nid):
    """graph = full['graph']（节点数组在 graph['nodes'] 下）"""
    for n in graph['nodes']:
        if n['id'] == nid:
            return n['data']
    raise RuntimeError('找不到节点 %s' % nid)


def add_outputs(d, fields, report, tag, src='nodeAgg'):
    """code 节点的 outputs 是 dict{var:{type}}；end 节点的 outputs 是 list[{variable,value_selector}]。"""
    out = d.get('outputs')
    if isinstance(out, list):
        have = set(str(o.get('variable')) for o in out if isinstance(o, dict))
        for f in fields:
            if f in have:
                report.append('  · %-46s output %s 已存在，跳过' % (tag, f))
            else:
                out.append({'variable': f, 'value_selector': [src, f]})
                report.append('  · %-46s + output %s' % (tag, f))
        return
    out = d.setdefault('outputs', {})
    for f in fields:
        if f in out:
            report.append('  · %-46s output %s 已存在，跳过' % (tag, f))
        else:
            out[f] = {'children': None, 'type': 'string'}
            report.append('  · %-46s + output %s' % (tag, f))


def add_variable(d, var, selector, report, tag):
    for v in (d.get('variables') or []):
        if v.get('variable') == var:
            report.append('  · %-46s 入参 %s 已存在，跳过' % (tag, var))
            return
    d.setdefault('variables', []).append({'variable': var, 'value_selector': selector})
    report.append('  · %-46s + 入参 %s ← %s' % (tag, var, '.'.join(selector)))


def patch_fact(full, report):
    data = full['graph']
    # ── FACT-1 nodeFact 提示词 ─────────────────────────────────────
    nf = get(data, 'nodeFact')
    t = nf['prompt_template'][0]['text']
    t, _ = sub_once(
        t,
        '"facts": [{"en": "English atomic fact, keep numbers/dates/names exactly", "zh": "对应中文事实"}]',
        '"facts": [{"en": "English atomic fact, keep numbers/dates/names exactly", "zh": "对应中文事实", "gist": 2}]',
        'nodeFact 输出格式加 gist 字段', report)
    t, _ = sub_once(t, FACT_TAIL_ANCHOR, FACT_TAIL_ANCHOR + FACT_TAIL_ADD,
                    'nodeFact 追加「事实卡挂靠大意」规则', report)
    nf['prompt_template'][0]['text'] = t

    # ── FACT-2 nodeClean 派生 ─────────────────────────────────────
    nc = get(data, 'nodeClean')
    c = nc['code']
    c, _ = sub_once(c, '  const strip = (t) =>', JS_SKELETON + '  const strip = (t) =>',
                    'nodeClean 插入 buildGistSkeleton', report)
    c, _ = sub_once(c, '  const fact = parseJSON(fact_text);\n  const grade = parseJSON(grade_text);',
                    '  const fact = parseJSON(fact_text);\n  const GM = buildGistSkeleton(fact);\n  const grade = parseJSON(grade_text);',
                    'nodeClean 调用 buildGistSkeleton', report)
    c, _ = sub_once(
        c,
        "    gist: gist.length ? gist.map((g, i) => (i + 1) + '. ' + (g.en || g.zh)).join('\\n') : '',",
        "    gist: gist.length ? gist.map((g, i) => (i + 1) + '. ' + (g.en || g.zh)).join('\\n') : '',\n"
        "    gist_fact_map: GM.gist_fact_map,\n"
        "    gist_lines: GM.gist_lines,\n"
        "    level_material_b1: GM.level_material_b1,\n"
        "    level_material_b2p: GM.level_material_b2p,",
        'nodeClean 返回值补 4 个派生字段', report)
    nc['code'] = c
    add_outputs(nc, SKEL_OUT_FIELDS, report, 'FACT nodeClean')


def patch_gen(full, report):
    data = full['graph']
    # ── GEN-1 nodeClean ───────────────────────────────────────────
    nc = get(data, 'nodeClean')
    nc['code'], _ = sub_once(
        nc['code'],
        'function main({ summary, facts_text, angle, level, gist, avoid_words }) {',
        'function main({ summary, facts_text, angle, level, gist, avoid_words, facts_raw }) {',
        'GEN nodeClean 签名加 facts_raw', report)
    add_variable(nc, 'facts_raw', ['nodeStart', 'facts_raw'], report, 'GEN nodeClean')
    nc['code'], _ = sub_once(nc['code'], '  const normLevel = (v) => {', JS_SKELETON + '''  /* GEN 可能被单独调用（不经抽取链路）而没传 facts_raw —— 必须容错，绝不抛错。 */
  const parseFact = (t) => {
    try {
      const s = String(t || '').replace(/<think>[\\s\\S]*?<\\/think>/g, '').replace(/```json|```/g, '');
      const m = s.match(/\\{[\\s\\S]*\\}/);
      if (!m) return {};
      try { return JSON.parse(m[0]); } catch (e) {
        try { return JSON.parse(m[0].replace(/,(\\s*[\\]}])/g, '$1')); } catch (e2) { }
      }
    } catch (e) { }
    return {};
  };
  const GM = buildGistSkeleton(parseFact(facts_raw), facts_text);
  const normLevel = (v) => {''', 'GEN nodeClean 插入骨架派生', report)
    nc['code'], _ = sub_once(
        nc['code'],
        "    gist: String(gist || '').trim() || String(facts_text || ''),",
        "    gist: String(gist || '').trim() || String(facts_text || ''),"
        "    /* 4 档统一骨架：低档直接用 gist_lines（= gist，加了编号口径归一），高档用挂细节的版本 */\n"
        "    gist_fact_map: GM.gist_fact_map,\n"
        "    gist_lines: GM.gist_lines,\n"
        "    level_material_b1: GM.level_material_b1,\n"
        "    level_material_b2p: GM.level_material_b2p,",
        'GEN nodeClean 返回值补 4 个派生字段', report)
    add_outputs(nc, SKEL_OUT_FIELDS, report, 'GEN nodeClean')

    # ── GEN-2 A1 / A2 提示词 ──────────────────────────────────────
    for nid in ('nodeGenA1', 'nodeGenA2'):
        nd = get(data, nid)
        t = nd['prompt_template'][0]['text']
        t, _ = sub_once(t, A1A2_MATERIAL_OLD, A1A2_MATERIAL_NEW,
                        '%s 素材换已编号骨架' % nid, report)
        t, _ = sub_once(t, GISTMAP_OLD, GISTMAP_NEW, '%s gist_map 判据加严' % nid, report)
        t, _ = sub_once(t, SELF_CHECK_5, SELF_CHECK_6, '%s 硬自查 五条→六条' % nid, report)
        t, _ = sub_once(
            t,
            '⑤ **语法复杂度**：严格遵守上「语法 Construction」四档（preferred/allowed/discouraged/forbidden），**不得用高等级句式来凑长度**。',
            '⑤ **语法复杂度**：严格遵守上「语法 Construction」四档（preferred/allowed/discouraged/forbidden），**不得用高等级句式来凑长度**。' + SELF_CHECK_ADD,
            '%s 追加第 ⑥ 条（段数）' % nid, report)
        t, _ = sub_once(
            t,
            '信息少的段则合理展开。段落之间词数要大致均匀，不允许某一段是其他段的 2 倍以上。',
            '信息少的段则合理展开。段落之间词数要大致均匀，不允许某一段是其他段的 2 倍以上。' + DROP_SPLIT,
            '%s 段数规则补「禁拆段」' % nid, report)
        nd['prompt_template'][0]['text'] = t

    # ── GEN-3 B1 / B2+ 提示词 ─────────────────────────────────────
    for nid, mat_old, mat_new, cite_key, out_old, out_new in (
        ('nodeGenB1', B1B2_MATERIAL_OLD, B1B2_MATERIAL_NEW, 'B1', B1_OUT_OLD, B1_OUT_NEW),
        ('nodeGenB2p', B1B2_MATERIAL_OLD, B1B2_MATERIAL_NEW_B2, 'B2', B2_OUT_OLD, B2_OUT_NEW),
    ):
        nd = get(data, nid)
        t = nd['prompt_template'][0]['text']
        t, _ = sub_once(t, mat_old, mat_new, '%s 素材换大意骨架' % nid, report)
        t, _ = sub_once(t, B1B2_CITE_OLD, B1B2_CITE_NEW, '%s 引用标注改双键' % nid, report)
        t, _ = sub_once(t, out_old, out_new, '%s 输出格式加 gist_map' % nid, report)
        t, _ = sub_once(
            t,
            '信息少的段则合理展开。段落之间词数要大致均匀，不允许某一段是其他段的 2 倍以上。',
            '信息少的段则合理展开。段落之间词数要大致均匀，不允许某一段是其他段的 2 倍以上。' + DROP_SPLIT,
            '%s 段数规则补「禁拆段」' % nid, report)
        nd['prompt_template'][0]['text'] = t

    # ── GEN-4 nodeAgg ────────────────────────────────────────────
    ag = get(data, 'nodeAgg')
    ag['code'], _ = sub_once(ag['code'], 'function main({ t_a1,', JS_SKELETON + 'function main({ t_a1,',
                             'nodeAgg 插入 buildGistSkeleton', report)
    ag['code'], _ = sub_once(
        ag['code'],
        '  const fact = parseJSON(fact_json);',
        '  const fact = parseJSON(fact_json);\n  const GM = buildGistSkeleton(fact);',
        'nodeAgg 调用 buildGistSkeleton', report)
    ag['code'], _ = sub_once(ag['code'], AGG_DECL_OLD, AGG_DECL_NEW,
                             'nodeAgg 声明 align_map / gfm 反查表', report)
    ag['code'], _ = sub_once(ag['code'], AGG_CLEANDECL_OLD, AGG_CLEANDECL_NEW,
                             'nodeAgg 声明 cleanCount', report)
    ag['code'], _ = sub_once(ag['code'], AGG_CLEAN_OLD, AGG_CLEAN_NEW,
                             'nodeAgg 记录清洗后段数', report)
    ag['code'], _ = sub_once(ag['code'], AGG_PICK_OLD, AGG_PICK_NEW,
                             'nodeAgg 同时收 gist_map 与 fact_map', report)
    ag['code'], _ = sub_once(ag['code'], AGG_BASIS_OLD, AGG_BASIS_NEW,
                             'nodeAgg 统一大意轴 / 事实卡轴', report)
    ag['code'], _ = sub_once(ag['code'], AGG_RAWMAP_OLD, AGG_RAWMAP_NEW,
                             'nodeAgg 删除死变量 raw_map', report)
    ag['code'], _ = sub_once(ag['code'], AGG_GROUP_OLD, AGG_GROUP_NEW,
                             'nodeAgg 删除「按档位回写 fact_map」', report)
    ag['code'], _ = sub_once(ag['code'], AGG_OUT_OLD, AGG_OUT_NEW,
                             'nodeAgg 输出 align_map', report)
    ag['code'], _ = sub_once(ag['code'], AGG_CLEANOUT_OLD, AGG_CLEANOUT_NEW,
                             'nodeAgg 输出 para_clean_count', report)
    add_outputs(ag, ['align_map', 'para_clean_count'], report, 'GEN nodeAgg')

    # ── GEN-5 nodeValidate ───────────────────────────────────────
    va = get(data, 'nodeValidate')
    va['code'], _ = sub_once(va['code'], VAL_SIG_OLD, VAL_SIG_NEW,
                             'nodeValidate 签名加入参', report)
    add_variable(va, 'align_map', ['nodeAgg', 'align_map'], report, 'GEN nodeValidate')
    add_variable(va, 'para_count', ['nodeAgg', 'para_count'], report, 'GEN nodeValidate')
    add_variable(va, 'para_clean_count', ['nodeAgg', 'para_clean_count'], report, 'GEN nodeValidate')
    va['code'], _ = sub_once(va['code'], VAL_ANCHOR, VAL_ADD + VAL_ANCHOR,
                             'nodeValidate 新增第 11 项「段落对齐」', report)
    va['code'], _ = sub_once(va['code'], VAL_TOTAL_OLD, VAL_TOTAL_NEW,
                             'nodeValidate total_checks 10→11', report)

    # ── nodeEnd 透出新字段 ────────────────────────────────────────
    en = get(data, 'nodeEnd')
    add_outputs(en, END_ADD_FIELDS, report, 'GEN nodeEnd')


def main():
    for f in (FACT_F, GEN_F):
        if not os.path.isfile(f):
            sys.exit('✗ 缺少输入：%s' % f)
    fact = json.load(open(FACT_F, encoding='utf-8'))
    gen = json.load(open(GEN_F, encoding='utf-8'))

    report = []
    patch_fact(fact, report)
    patch_gen(gen, report)

    # ── 回读核验：改动必须真的落进产物 ────────────────────────────
    def body(full, nid, kind='prompt'):
        d = get(full['graph'], nid)
        return d['prompt_template'][0]['text'] if kind == 'prompt' else d['code']

    checks = [
        ('FACT nodeFact 有 gist 字段', '"gist": 2' in body(fact, 'nodeFact')),
        ('FACT nodeClean 有派生', 'buildGistSkeleton' in body(fact, 'nodeClean', 'code')),
        ('GEN nodeClean 有派生', 'buildGistSkeleton' in body(gen, 'nodeClean', 'code')),
        ('A1 有禁拆段', '不许拆段' in body(gen, 'nodeGenA1')),
        ('A2 有禁拆段', '不许拆段' in body(gen, 'nodeGenA2')),
        ('A1 有六条自查', SELF_CHECK_6 in body(gen, 'nodeGenA1')),
        ('A1 素材用编号骨架', 'gist_lines' in body(gen, 'nodeGenA1')),
        ('A2 素材用编号骨架', 'gist_lines' in body(gen, 'nodeGenA2')),
        ('B1 用大意骨架', 'level_material_b1' in body(gen, 'nodeGenB1')),
        ('B2+ 用大意骨架', 'level_material_b2p' in body(gen, 'nodeGenB2p')),
        ('B1 输出 gist_map', '"gist_map":{"B1"' in body(gen, 'nodeGenB1')),
        ('nodeAgg 有 alignMap', 'alignMap[k]' in body(gen, 'nodeAgg', 'code')),
        ('nodeAgg fact_map 恒为事实卡轴', 'fact_map = factFacts;' in body(gen, 'nodeAgg', 'code')),
        ('nodeAgg 无 raw_map 残留', ('const raw_map' not in body(gen, 'nodeAgg', 'code')
                                 and 'raw_map[' not in body(gen, 'nodeAgg', 'code'))),
        ('nodeValidate 有对齐项', '段落对齐' in body(gen, 'nodeValidate', 'code')),
        ('nodeValidate 11 项', 'ALL.length * 11' in body(gen, 'nodeValidate', 'code')),
        ('nodeValidate 看得到原始段数', 'para_clean_count' in body(gen, 'nodeValidate', 'code')),
        ('nodeAgg 记录清洗后段数', 'cleanCount[k] = arr.length;' in body(gen, 'nodeAgg', 'code')),
    ]
    fail = [n for n, ok in checks if not ok]
    print('── 改动清单 ──')
    print('\n'.join(report))
    print('\n── 回读核验 ──')
    for n, ok in checks:
        print('  %s %s' % ('✓' if ok else '✗', n))
    if fail:
        sys.exit('\n✗ 以下核验未通过，拒绝写文件：%s' % ', '.join(fail))

    if CHECK_ONLY:
        print('\n(--check：未写文件)')
        return 0
    for path, obj in ((FACT_F, fact), (GEN_F, gen)):
        json.dump(obj, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('写入', path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
