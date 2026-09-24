// ReadPal · 校验前端质检 JS（frontend/card_check.js）与工具包 build_cards.py 判定一致
//
// 基准数据 = 工具包里的 example_honesty（original.txt + cards.json + report.txt），
// **正向**要求与 report.txt 逐项吻合；**负向**要求改坏后必须抓到。
//
// 用法：node tools/probe_card_check.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function loadCC() {
  const code = fs.readFileSync(path.join(REPO, 'frontend/card_check.js'), 'utf-8');
  const ctx = {};
  new Function('self', 'module', 'exports', code)(ctx, undefined, undefined);
  return ctx.CardCheck;
}
const CC = loadCC();
const data = JSON.parse(fs.readFileSync(path.join(REPO, 'dify_graphs/card_example.json'), 'utf-8'));
const orig = fs.readFileSync(path.join(REPO, 'dify_graphs/card_example_original.txt'), 'utf-8');

let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log('    ✓ ' + name); }
  else { fail++; console.log('    ✗ ' + name + (extra ? '   → ' + extra : '')); }
};
const clone = o => JSON.parse(JSON.stringify(o));

console.log('[1] 工具包示例：应与 report.txt 同为「✓ 通过」');
const r = CC.run(data, orig);
ok('无硬错误', r.errs.length === 0, JSON.stringify(r.errs).slice(0, 400));
console.log(`    告警 ${r.warns.length} 条` + (r.warns.length ? '：' : ''));
r.warns.slice(0, 5).forEach(w => console.log('      ! ' + w));
r.stats.forEach(s => console.log(`      ${s.level.padEnd(4)} 卡${String(s.cards).padStart(2)}  词数 ${String(s.wc).padStart(3)}  占原文 ${(s.ratio * 100).toFixed(0).padStart(3)}%  平均句长 ${s.avg.toFixed(1).padStart(4)}  最长 ${String(s.max).padStart(2)}  最短 ${s.min}`));

console.log('\n[2] 与 report.txt 逐项对照（基准：A1- 175/40%/6.5，A2 242/55%/10.1，B1 321/72%/14.0，B2+ 443/100%/22.1）');
const expect = { 'A1-': [175, 40, 6.5], 'A2': [242, 55, 10.1], 'B1': [321, 72, 14.0], 'B2+': [443, 100, 22.1] };
r.stats.forEach(s => {
  const e = expect[s.level];
  ok(`${s.level} 词数 ${s.wc}`, s.wc === e[0], `期望 ${e[0]}`);
  ok(`${s.level} 占原文 ${Math.round(s.ratio * 100)}%`, Math.round(s.ratio * 100) === e[1], `期望 ${e[1]}%`);
  ok(`${s.level} 平均句长 ${s.avg.toFixed(1)}`, Math.abs(s.avg - e[2]) < 0.15, `期望 ${e[2]}`);
});
ok('母稿词数 443', r.origWc === 443, String(r.origWc));
ok('母稿卡数 10', r.cardCount === 10, String(r.cardCount));

console.log('\n[3] 负向：改坏后必须抓到');
let d1 = clone(data); d1.topic_words = ['honest', 'dishonest', 'honesty', 'zzznothere'];
let r1 = CC.run(d1, orig);
ok('主题词缺失被抓', r1.errs.some(e => e.indexOf('zzznothere') >= 0), JSON.stringify(r1.errs).slice(0, 160));

let d2 = clone(data); d2.levels['A2'].cards = d2.levels['A2'].cards.slice(0, 9);
let r2 = CC.run(d2, orig);
ok('四档卡片数不齐被抓', r2.errs.some(e => e.indexOf('没对齐') >= 0), JSON.stringify(r2.errs).slice(0, 160));

let d3 = clone(data);
d3.levels['A1-'].questions[0].explanation = '卡片①说"This sentence appears nowhere in the card text at all"，所以A正确。B最容易误选，因为……';
let r3 = CC.run(d3, orig);
ok('解析引文不可查被抓', r3.errs.some(e => e.indexOf('解析引用') >= 0), JSON.stringify(r3.errs).slice(0, 160));

let d4 = clone(data);
d4.levels['A2'].questions[0].q = 'According to the text, what does "a totally missing phrase" mean?';
let r4 = CC.run(d4, orig);
ok('题干引文不可查被抓', r4.errs.some(e => e.indexOf('题干引用') >= 0), JSON.stringify(r4.errs).slice(0, 160));

let d5 = clone(data);
d5.levels['A1-'].cards[0] = 'This is a deliberately very long sentence that runs on and on well beyond the twelve word ceiling. Short.';
let r5 = CC.run(d5, orig);
ok('A1- 超长句被抓（>12 词）', r5.errs.some(e => e.indexOf('> 12') >= 0), JSON.stringify(r5.errs).slice(0, 160));

/* 主路径：母稿卡由**代码**切好直接给定 —— 模型返回的 b2_card_starts 一律忽略。
   实测踩坑：模型会先列段落级锚点、再追加段内锚点，位置是乱序的（1053 排在 2035 之后），
   所以锚点这条路只作回退，不能当主路径。 */
const mc = CC.splitToCards(orig, CC.CARD_MIN).cards;
let d6 = clone(data); d6.b2_card_starts = ['zzz nowhere in the original', 'also missing'];
let r6 = CC.run(d6, orig, mc);
ok('主路径忽略模型锚点（给了 masterCards 就不看 b2_card_starts）',
   !r6.fatal && r6.cardCount === mc.length,
   'fatal=' + r6.fatal + ' cardCount=' + r6.cardCount + ' 期望=' + mc.length);

/* 回退路径：锚点个数不在规格内 → 代码兜底重切，**必须说明**（不静默、也不硬失败） */
let d7 = clone(data); d7.b2_card_starts = d7.b2_card_starts.slice(1);
let r7 = CC.run(d7, orig);
ok('回退路径锚点个数不对 → 代码兜底重切并明说',
   !r7.fatal && String(r7.splitNote).indexOf('锚点不可用') >= 0
     && r7.warns.some(w => String(w).indexOf('锚点不可用') >= 0),
   'fatal=' + r7.fatal + ' splitNote=' + String(r7.splitNote).slice(0, 70));

let d8 = clone(data); d8.levels['A1-'].cards = d8.levels['A1-'].cards.map(c => CC.words(c).slice(0, 4).join(' ') + '.');
let r8 = CC.run(d8, orig);
ok('A1- 词数比例越界被抓', r8.errs.some(e => e.indexOf('词数') >= 0), JSON.stringify(r8.errs).slice(0, 200));

let d9 = clone(data); d9.levels['B1'].questions = d9.levels['B1'].questions.slice(0, 2);
let r9 = CC.run(d9, orig);
ok('题数不足 3 被抓', r9.errs.some(e => e.indexOf('题目数量') >= 0), JSON.stringify(r9.errs).slice(0, 160));

let d10 = clone(data); d10.levels['A1-'].questions[0].answer = 'E';
let r10 = CC.run(d10, orig);
ok('答案字母无效被抓', r10.errs.some(e => e.indexOf('答案字母无效') >= 0), JSON.stringify(r10.errs).slice(0, 160));

let d11 = clone(data); d11.b2_card_starts = [];
let r11 = CC.run(d11, orig);
ok('回退路径缺 b2_card_starts → 代码兜底，不再硬失败',
   !r11.fatal && r11.cardCount >= CC.CARD_MIN,
   'fatal=' + r11.fatal + ' cardCount=' + r11.cardCount);

console.log('\n[4] 页面 ↔ 生成侧探针 逻辑同源（防漂移）');
/* 由来：改共享函数时漏同步过两次（漏 scopeHint / 把 buildFixList 整段删掉），
   靠人眼比对不可靠 —— 这里把「两边必须逐字一致」钉成断言。 */
const PAGE_HTML = fs.readFileSync(path.join(REPO, 'frontend/card.html'), 'utf-8');
const GEN_PROBE = fs.readFileSync(path.join(REPO, 'tools/probe_card_gen.mjs'), 'utf-8');
/* 用大括号配对抽取函数体（跳过字符串与注释）—— 正则找「下一个 function」会跑过头 */
function grabFn(src, name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) return null;
  let j = src.indexOf('{', i), d = 0, q = null, esc = false, line = false, blk = false;
  for (let k = j; k < src.length; k++) {
    const c = src.charAt(k), n = src.charAt(k + 1);
    if (line) { if (c === '\n') line = false; continue; }
    if (blk) { if (c === '*' && n === '/') { blk = false; k++; } continue; }
    if (q) {
      if (esc) { esc = false; continue; }
      if (c === '\\') { esc = true; continue; }
      if (c === q) q = null;
      continue;
    }
    if (c === '/' && n === '/') { line = true; k++; continue; }
    if (c === '/' && n === '*') { blk = true; k++; continue; }
    if (c === '"' || c === "'" || c === '`') { q = c; continue; }
    if (c === '{') d++;
    else if (c === '}') { d--; if (d === 0) return src.slice(i, k + 1); }
  }
  return null;
}
['keepBest', 'assembleBest', 'mergeCard', 'failingLevels', 'scopeHint', 'buildFixList'].forEach(n => {
  const a = grabFn(PAGE_HTML, n), b = grabFn(GEN_PROBE, n);
  ok('同源：' + n, !!a && !!b && a === b,
     a ? (a === b ? '' : '页面 ' + a.length + ' 字符 vs 探针 ' + (b ? b.length : '缺失')) : '页面里找不到该函数');
});

/* [5] 跨侧不变式：页面写出去的 fix_levels，图上的解析节点必须能还原成这几档。
   由来（2026-09-24）：页面把「本轮只输出这几档」整句当 fix_levels 传，而解析节点当时是
   「按分隔符切词 + 档位名前缀匹配」—— 切出来的第一个词带中文前缀，匹配落空 ⇒ ASKED 退回四档 ⇒
   「只重写 B2+」被判成「缺 A1-/A2/B1」⇒ 回炉整轮作废（实测第 3–5 轮连续白跑）。
   这类坑靠人眼看不出来，所以把「两头口径」钉成断言。 */
console.log('\n[5] 跨侧：fix_levels 文本 ↔ 解析侧档位还原');
const GRAPH_PY = fs.readFileSync(path.join(REPO, 'tools/build_card_graph.py'), 'utf-8');
/* 解析侧口径（与 build_card_graph.py 的 PARSE_CODE 同一套）：全文扫描档位名 */
const askedOf = s => {
  const out = [];
  (String(s || '').match(/A1-?|A2|B1|B2\+/gi) || []).forEach(t => {
    const k = t.toUpperCase().replace(/^A1-?$/, 'A1-').replace(/^B2\+$/, 'B2+');
    if (out.indexOf(k) < 0) out.push(k);
  });
  return out;
};
const pageScopeHint = grabFn(PAGE_HTML, 'scopeHint');
ok('页面里能取到 scopeHint', !!pageScopeHint);
if (pageScopeHint) {
  /* 直接跑页面的 scopeHint（用 new Function 还原成可调用函数） */
  const fn = new Function(pageScopeHint + '; return scopeHint;')();
  [['B2+'], ['A2', 'B1'], ['A1-', 'A2', 'B1', 'B2+'], ['B1', 'B2+']].forEach(lv => {
    const txt = fn(lv);
    const back = askedOf(txt);
    ok('还原 ' + lv.join('/') + '（' + txt.slice(0, 24) + '…）', back.join('/') === lv.join('/'),
       '口径还原成 ' + JSON.stringify(back));
  });
}
ok('图侧解析已改成「全文扫描档位名」（不再依赖档位出现在第几个词）',
   GRAPH_PY.indexOf('match(/A1-?|A2|B1|B2\\+/gi)') >= 0,
   'build_card_graph.py 里找不到全文扫描的档位正则');
ok('图侧仍把未点名的档位排除在缺档判定外（ASKED 机制在）',
   GRAPH_PY.indexOf('ASKED.indexOf(lv) >= 0') >= 0, 'ASKED 判定没找到');
ok('图侧主题词硬约束在（必须逐字出现在母稿正文里）',
   GRAPH_PY.indexOf('主题词必须逐字出现在母稿正文里') >= 0, '提示词里没有这条约束');
ok('图侧禁止照抄范例的题目/解析（实测会整题串味）',
   GRAPH_PY.indexOf('范例只示范「格式和难度」') >= 0, '提示词里没有禁止照抄范例的约束');

/* [6] 回炉指令本身（buildFixList）：它现在承担了大部分回炉语义，必须直接测。
   实测逼出来的三条：① 超上限要给**句数差量**（「删掉 5 个整句」，只给词数它不动）；
   ② 低于下限要给**均句长**方向（不能靠加句，句数已到上限）；
   ③ 长句要**逐句**列出并明说「用分号假装断句无效」。 */
console.log('\n[6] 回炉指令 buildFixList（双向篇幅指引 + 逐句拆法）');
const pageFix = grabFn(PAGE_HTML, 'buildFixList');
ok('页面里能取到 buildFixList', !!pageFix);
if (pageFix) {
  const mkFix = new Function('CardCheck', pageFix + '; return buildFixList;')(CC);
  /* 10 张母稿卡（词数与真实切分同量级：25–63 词） */
  const MC = [40, 57, 37, 52, 51, 34, 48, 53, 25, 63].map(n =>
    Array.from({ length: n }, (_, i) => 'word' + i).join(' ') + '.');
  /* 生成「每卡 sentences 句 × wps 词」的卡（真实形态：B1 每卡 2–3 句、A1- 每卡 2 句）。
     ⚠️ 每句首字母必须大写 —— 断句器按 `.?!` + 空白 + `["'A-Z0-9]` 切，小写开头切不开。 */
  const lvCards = (sentences, wps) => Array.from({ length: 10 }, () =>
    Array.from({ length: sentences }, () => Array.from({ length: wps }, (_, i) => (i ? 'w' : 'W') + i).join(' ') + '.').join(' '));
  /* ① B1 超上限：10 卡 × 3 句 × 14 词 = 420 词 / 30 句（B1 句数上限 25 ⇒ 超 5 句） */
  let rep = { origWc: 460, cardsByLevel: { 'B1': lvCards(3, 14) },
    stats: [{ level: 'B1', wc: 420, ratio: 0.913, avg: 14.0 }],
    errs: ['B1 词数 420（91%），目标 65–78%，即 299–358 词'] };
  let t = mkFix(rep, { levels: { 'B1': { questions: [] } } }, MC);
  ok('超上限：给出**句数差量**（删掉 N 个整句）', /删掉 \d+ 个整句/.test(t), t.slice(0, 260));
  ok('超上限：给出**逐张卡硬上限**', /逐张卡硬上限/.test(t), '');
  ok('超上限：明说「不许靠合并句子压词数」', t.indexOf('不许靠') >= 0 && t.indexOf('合并句子') >= 0, '');
  /* ② A1- 低于下限：10 卡 × 2 句 × 6 词 = 120 词 / 20 句（A1- 句数上限 19 ⇒ 句数也超）
     —— 正是实测遇到的那种「句数超、字数却不够」的两头夹心，必须只给「加词」方向 */
  rep = { origWc: 460, cardsByLevel: { 'A1-': lvCards(2, 6) },
    stats: [{ level: 'A1-', wc: 120, ratio: 0.26, avg: 6.0 }],
    errs: ['A1- 词数 120（26%），目标 30–42%，即 138–193 词'] };
  t = mkFix(rep, { levels: { 'A1-': { questions: [] } } }, MC);
  ok('低于下限：方向是**加词**', t.indexOf('方向是**加词**') >= 0, t.slice(0, 260));
  ok('低于下限：给**均句长**目标（不靠加句）', /均句长/.test(t) && /句数上限/.test(t), '');
  ok('低于下限：明说不要新增原文没有的事实', t.indexOf('不要新增原文没有的事实') >= 0, '');
  ok('低于下限：**不再同时出现「删掉 N 个整句」**（两头夹心只说一个方向）',
     !/删掉 \d+ 个整句/.test(t), '同时给了删句和加词两个反向指令');
  /* ③ 篇幅已达标 + 长句：逐句列出并说明分号无效 */
  rep = { origWc: 460, cardsByLevel: { 'B1': lvCards(25) },
    stats: [{ level: 'B1', wc: 340, ratio: 0.74, avg: 14.0 }],
    errs: ['B1 卡⑧ 句子 28 词 > 22：He says the Mediterranean diet is best.'] };
  t = mkFix(rep, { levels: { 'B1': { questions: [] } } }, MC);
  ok('长句：逐句列出并给出「各拆成 2 句」', /必须各拆成 2 句/.test(t), '');
  ok('长句：明说「用分号 / 逗号假装断句无效」', t.indexOf('假装') >= 0 && t.indexOf('只认') >= 0, '');
}

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
