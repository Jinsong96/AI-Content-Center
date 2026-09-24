// ReadPal · 分级卡片「解析节点」本地单测（不打网络，秒级）
//
// 为什么单独测它：解析节点是**回炉能不能收敛的闸门**。它的 fix_levels 判定一旦收窄失败，
// 页面就会看到「缺 A1-/A2/B1」→ 整轮作废 → 那一档真正的残留问题永远修不掉，而且**不报错**，
// 只在轮次面板上显示「解析未通过·已跳过」——属于最难发现的一类静默退化。
//
// 覆盖的事实（都是实测踩过的）：
//   [A] 首轮（fix_levels 空）四档齐全 → 通过
//   [B] 回炉只点名 B2+，fix_levels 是**页面真实生成的整句**（不是手写列表）→ 必须通过
//       ⛔ 2026-09-24 的坑：页面传的整句被「按分隔符切词 + 档位名前缀匹配」判成空 ⇒ ASKED 退回四档
//   [C] 回炉点名多档（A2 / B1）→ 通过
//   [D] 守卫不能被放跑：fix_levels 空 + 只给 B2+ ⇒ 必须判失败并报缺三档
//   [E] 纯列表（"B2+"）向后兼容
//
// 用法：node tools/probe_card_parse.mjs
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const graph = JSON.parse(fs.readFileSync(path.join(REPO, 'dify_graphs/card.new.json'), 'utf-8')).graph;
const codeNode = graph.nodes.find(n => n.data.type === 'code');
if (!codeNode) { console.error('✗ 图里找不到 code 节点（解析兜底）'); process.exit(1); }
const runParse = input => new Function(codeNode.data.code + '; return main;')()(input);

/* scopeHint 从页面**现取**（不手写一份），否则测的就不是页面真实传的东西了 */
const html = fs.readFileSync(path.join(REPO, 'frontend/card.html'), 'utf-8');
const at = html.indexOf('function scopeHint(');
if (at < 0) { console.error('✗ card.html 里找不到 scopeHint'); process.exit(1); }
let d = 0, end = -1;
for (let k = html.indexOf('{', at); k < html.length; k++) {
  if (html[k] === '{') d++;
  else if (html[k] === '}') { d--; if (!d) { end = k + 1; break; } }
}
const scopeHint = new Function(html.slice(at, end) + '; return scopeHint;')();

let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + (extra ? '  → ' + extra : '')); }
};

const MASTER = [
  '[1] Food and mood are linked.', '[2] Sugar gives a quick lift.', '[3] Too much sugar brings you down.',
  '[4] Fish and nuts help the brain.', '[5] Water matters too.', '[6] Sleep and food work together.',
  '[7] Breakfast matters.', '[8] Small changes help.', '[9] Doctors say eat well.', '[10] Choose real food.',
].join('\n');
const mkQ = () => [1, 2, 3].map(n => ({ q: 'Q' + n + '?', options: ['a', 'b', 'c', 'd'], answer: 'A', explanation: 'e' }));
const lvBlock = () => ({ cards: ['Food and mood are linked.', 'Sugar gives a quick lift.'], questions: mkQ() });
const TW = ['food', 'sugar', 'mood'];
const full = { title_en: 'T', title_zh: '题', topic_words: TW,
  levels: { 'A1-': lvBlock(), 'A2': lvBlock(), 'B1': lvBlock(), 'B2+': lvBlock() } };
const onlyB2 = { title_en: 'T', title_zh: '题', topic_words: TW, levels: { 'B2+': lvBlock() } };
const onlyAB = { title_en: 'T', title_zh: '题', topic_words: TW, levels: { 'A2': lvBlock(), 'B1': lvBlock() } };
const call = (obj, fix) => runParse({ text: JSON.stringify(obj), title_in: 'T', master_cards: MASTER, fix_levels: fix });

console.log('[A] 首轮（fix_levels 空）＋四档齐全');
let r = call(full, '');
ok('parse_ok=true', r.parse_ok === 'true', r.parse_warn);
ok('无告警', !r.parse_warn, r.parse_warn);

console.log('\n[B] 回炉只点名 B2+，fix_levels 用页面真实生成的整句');
r = call(onlyB2, scopeHint(['B2+']));
ok('parse_ok=true（不再判成缺档）', r.parse_ok === 'true', r.parse_warn);
ok('不再误报「缺 A1- / A2 / B1」',
   r.parse_warn.indexOf('缺 A1-') < 0 && r.parse_warn.indexOf('缺 A2') < 0 && r.parse_warn.indexOf('缺 B1') < 0,
   r.parse_warn);

console.log('\n[C] 回炉点名多档（A2 / B1）');
r = call(onlyAB, scopeHint(['A2', 'B1']));
ok('parse_ok=true', r.parse_ok === 'true', r.parse_warn);

console.log('\n[D] 守卫不能被放跑：fix_levels 空 + 只给 B2+ ⇒ 必须报缺三档');
r = call(onlyB2, '');
ok('parse_ok=false', r.parse_ok === 'false', r.parse_ok);
ok('明确报缺 A1-/A2/B1',
   r.parse_warn.indexOf('缺 A1-') >= 0 && r.parse_warn.indexOf('缺 A2') >= 0 && r.parse_warn.indexOf('缺 B1') >= 0,
   r.parse_warn);

console.log('\n[E] 纯列表形式（"B2+"）向后兼容');
r = call(onlyB2, 'B2+');
ok('parse_ok=true', r.parse_ok === 'true', r.parse_warn);

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
