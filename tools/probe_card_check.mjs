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

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
