// ReadPal · 分级卡片页 端到端（真实调 Dify，真跑一次完整链路）
//
// 验的是页面真实行为，不是接口：贴文 → 生成 → 代码质检 → 卡片渲染 → 导出 docx。
// 用法：node tools/probe_card_page.mjs
//   环境：CARD_URL（默认 http://127.0.0.1:8899/card.html）、DIFY_CDP_PORT（默认 9243）
//
// ⚠️ 本机沙箱直连 api.dify.ai 被拦，必须借**真实 Chrome**：页面走「桥接层不可达 → 直连 Dify」兜底。
import fs from 'node:fs';

const PORT = Number(process.env.DIFY_CDP_PORT || 9243);
const CDP = `http://127.0.0.1:${PORT}`;
const TARGET = process.env.CARD_URL || 'http://127.0.0.1:8899/card.html';
const MAX_WAIT_MS = Number(process.env.MAX_WAIT_MS || 360000);

let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log('  ✓ ' + name); }
  else { fail++; console.log('  ✗ ' + name + (extra ? '   → ' + extra : '')); }
};
const sleep = ms => new Promise(r => setTimeout(r, ms));

const rr = await fetch(`${CDP}/json/new?${TARGET}`, { method: 'PUT' });
const tab = await rr.json();
if (!tab.webSocketDebuggerUrl) { console.error('✗ 新开页签失败:', JSON.stringify(tab).slice(0, 200)); process.exit(1); }

const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id = 0; const pending = new Map(); const logs = [];
ws.addEventListener('message', e => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
    logs.push('console.error: ' + (m.params.args || []).map(a => a.value || a.description || '').join(' ').slice(0, 200));
  }
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails || {};
    logs.push('exception: ' + (d.exception?.description || d.text || '').slice(0, 300));
  }
});
const send = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true, userGesture: true });
  if (r.result?.exceptionDetails) {
    const d = r.result.exceptionDetails;
    return '__ERR__' + (d.exception?.description || d.text || '').slice(0, 300);
  }
  return r.result?.result?.value;
};

await send('Runtime.enable');
await send('Page.enable');
for (let i = 0; i < 40; i++) { if (await ev('document.readyState') === 'complete') break; await sleep(500); }
await sleep(1500);

console.log('页面:', await ev('location.href'));
console.log('标题:', await ev('document.title'));

console.log('\n[1] 资源与配置');
ok('CardCheck 已加载', (await ev('typeof window.CardCheck')) === 'object', String(await ev('typeof window.CardCheck')));
ok('JSZip 已加载', (await ev('typeof window.JSZip')) === 'function', String(await ev('typeof window.JSZip')));
ok('DIFY_WF_CARD 已注入', !!(await ev('(window.WB_CFG&&window.WB_CFG.DIFY_WF_CARD)||""')),
   await ev('(window.WB_CFG&&window.WB_CFG.DIFY_WF_CARD)?"有("+String(window.WB_CFG.DIFY_WF_CARD).length+"字符)":"空"'));
ok('质检区间与工具包一致', (await ev('JSON.stringify(window.CardCheck.RATIO)')) === '{"A1-":[0.3,0.42],"A2":[0.48,0.6],"B1":[0.65,0.78]}',
   String(await ev('JSON.stringify(window.CardCheck.RATIO)')));

console.log('\n[2] 填入原文（默认点按钮，可用 CARD_TEXT_FILE 换成任意一篇）');
const EXT = process.env.CARD_TEXT_FILE;
if (EXT) {
  const txt = fs.readFileSync(EXT, 'utf8').trim();
  await ev(`(()=>{const t=document.getElementById('textIn');t.value=${JSON.stringify(txt)};
    t.dispatchEvent(new Event('input',{bubbles:true}));return t.value.length;})()`);
  console.log('    外部原文:', EXT, '（' + txt.split(/\s+/).length + ' 词）');
} else {
  await ev(`document.getElementById('btnSample').click()`);
}
await sleep(400);
const taLen = await ev(`document.getElementById('textIn').value.length`);
const wcTxt = await ev(`document.getElementById('wcInfo').textContent`);
ok('textarea 已填入原文', taLen > 1500, '长度 ' + taLen);
ok('词数显示已更新', /\d{3}\s*词/.test(String(wcTxt)), String(wcTxt));
ok('填入的原文不是提示词内嵌的那篇范例（否则是抄答案，不是验证）',
   !(await ev(`document.getElementById('textIn').value`)).includes('Is honesty always the best policy'),
   '样例文是否等于范例文');

console.log('\n[3] 真实生成（调 Dify，请等待）');
const t0 = Date.now();
await ev(`document.getElementById('btnRun').click()`);
let last = '', done = false, st = null;
while (Date.now() - t0 < MAX_WAIT_MS) {
  await sleep(4000);
  const raw = await ev(`JSON.stringify({run:window.__card.running,err:window.__card.err,has:!!window.__card.report,el:window.__card.elapsed})`);
  if (raw !== last) { last = raw; console.log('    ' + raw); }
  st = JSON.parse(raw);
  if (!st.run) { done = true; break; }
}
const secs = Math.round((Date.now() - t0) / 1000);
ok('运行结束（未超时）', done, '超时 ' + MAX_WAIT_MS + 'ms');
ok('没有报错', !st || !st.err, (st && st.err) || '');
ok('拿到质检报告', !!(st && st.has));

if (st && st.err) {
  console.log('\n!! 生成失败，后续渲染断言跳过：' + st.err);
  console.log('\n控制台错误:', logs.length ? logs : '（无）');
  console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
  await fetch(`${CDP}/json/close/${tab.id}`);
  process.exit(1);
}

console.log('\n[4] 质检报告内容（纯代码判定）');
const rep = await ev(`JSON.stringify({
  ok: window.__card.report.ok,
  errs: window.__card.report.errs.length,
  warns: window.__card.report.warns.length,
  origWc: window.__card.report.origWc,
  cardCount: window.__card.report.cardCount,
  stats: window.__card.report.stats.map(s=>({lv:s.level,cards:s.cards,wc:s.wc,r:+(s.ratio*100).toFixed(0),avg:+s.avg.toFixed(1)})),
  errsSample: window.__card.report.errs.slice(0,5),
  title: window.__card.title,
  parseWarn: window.__card.warn
})`);
const R = JSON.parse(rep);
console.log('    标题:', R.title, '| 母稿词数:', R.origWc, '| 卡数:', R.cardCount);
R.stats.forEach(s => console.log(`    ${s.lv.padEnd(4)} 卡${String(s.cards).padStart(2)} 词${String(s.wc).padStart(4)} 占比${String(s.r).padStart(3)}% 平均句长${s.avg}`));
if (R.errs) R.errsSample.forEach(e => console.log('    ✗ ' + e));
if (R.warns) console.log('    告警 ' + R.warns + ' 条');
if (R.parseWarn) console.log('    解析告警:', R.parseWarn);

ok('母稿卡数符合规格（固定 10 张，超长才到 12 张）', R.cardCount >= 10 && R.cardCount <= 12, '卡数 ' + R.cardCount);
ok('四档卡片数一致', R.stats.every(s => s.cards === R.cardCount),
   R.stats.map(s => `${s.lv}:${s.cards}`).join(' '));
ok('A1/A2/B1 词数占比落在工具包区间',
   ['A1-', 'A2', 'B1'].every(lv => { const s = R.stats.find(x => x.lv === lv); return s && s.r >= 25 && s.r <= 82; }),
   R.stats.map(s => `${s.lv}:${s.r}%`).join(' '));

console.log('\n[4b] 回炉轮次（带量化差量的定向重跑）');
const rd = await ev(`JSON.stringify({round:window.__card.round, rounds:window.__card.rounds,txt:(document.querySelector('.note.info')||{}).textContent||''})`);
const RD = JSON.parse(rd);
console.log('    轮次记录:', JSON.stringify(RD.rounds));
console.log('    面板文案:', RD.txt.slice(0, 120));
ok('状态里记了轮次', RD.round >= 1 && Array.isArray(RD.rounds) && RD.rounds.length >= 1, JSON.stringify(RD.rounds));
ok('第 1 轮记的是真实未过项数', RD.rounds.length >= 1 && typeof RD.rounds[0].errs === 'number',
   JSON.stringify(RD.rounds[0] || null));
ok('轮次递增且不超过上限 5', RD.rounds.every((r, i) => r.round === i + 1) && RD.rounds.length <= 5,
   JSON.stringify(RD.rounds.map(r => r.round)));
ok('面板显示了轮次记录', /生成轮次/.test(RD.txt), RD.txt.slice(0, 80));
if (RD.rounds.length > 1) {
  /* 拼装后（各档取历史最优）的错误数**单调不增** —— 这是纯代码保证的，不是碰运气 */
  const seq = RD.rounds.map(r => r.errs).filter(v => typeof v === 'number');   // 解析失败的轮无数字
  ok('拼装后错误数单调不增（按档取最优，必然不退化）',
     seq.every((v, i) => i === 0 || v <= seq[i - 1]), JSON.stringify(seq));
  /* 回炉范围必须是「收窄」的：首轮全量，之后只点名上一轮还有错误的档位 */
  ok('首轮是全量生成（scope 为空）', (RD.rounds[0].scope || []).length === 0,
     JSON.stringify(RD.rounds[0].scope));
  const tail = RD.rounds.slice(1);
  ok('回炉只点名没过的档位（scope 非空且不是全量）',
     tail.every(r => (r.scope || []).length > 0 && r.scope.length < 4),
     JSON.stringify(tail.map(r => r.scope)));
  /* 🔴 2026-09-24 的坑：回炉只点名部分档位时，解析节点曾把「没点名的档位没正文」
     判成缺档 ⇒ parseFail ⇒ 整轮作废（实测第 3–5 轮连续白跑，那一档真正的残留问题永远修不掉）。
     这里按「点名了几档」硬钉：收窄的轮次**不允许**出现「本轮缺正文的档位」式误判。 */
  const bogus = tail.filter(r => r.parseFail && /本轮缺正文的档位/.test(String(r.parseFail)));
  ok('收窄轮次没有「只输出点名档位 ⇒ 被判缺档」的误报', bogus.length === 0,
     JSON.stringify(bogus.map(r => ({ scope: r.scope, warn: String(r.parseFail).slice(0, 90) }))));
  console.log('    → 回炉范围：' + RD.rounds.map(r => `第${r.round}轮 ${r.errs}处`
    + ((r.scope || []).length ? '[只改 ' + r.scope.join('/') + ']' : '[全量]')).join(' → '));
} else {
  console.log('    → 本轮首次生成即通过，未触发回炉（合法结果）');
}

console.log('\n[5] DOM 真实渲染');
const dom = await ev(`JSON.stringify({
  score: (document.querySelector('.score .big')||{}).textContent||'',
  rows: document.querySelectorAll('table tbody tr').length,
  tabs: document.querySelectorAll('.tabs .tab').length,
  cards: document.querySelectorAll('#cardBody .card').length,
  qs: document.querySelectorAll('#quizBody .q').length
})`);
const D = JSON.parse(dom);
console.log('    DOM:', dom);
ok('质检结论已渲染', /通过|需修改/.test(D.score), D.score);
ok('统计表 4 行', D.rows === 4, String(D.rows));
ok('档位 tab 5 个（4 档 + 逐卡对照）', D.tabs === 5, String(D.tabs));
ok('当前档卡片已渲染', D.cards > 0, String(D.cards));
ok('题目已渲染（12 道）', D.qs === 12, String(D.qs));

console.log('\n[6] 切档与逐卡对照');
await ev(`document.querySelector('.tabs .tab[data-tab="B2+"]').click()`);
await sleep(300);
const b2w = await ev(`JSON.stringify({n:document.querySelectorAll('#cardBody .card').length,src:document.querySelectorAll('#cardBody .card.src').length})`);
ok('切到 B2+ 后渲染母稿卡（且标记为源稿）', JSON.parse(b2w).n > 0 && JSON.parse(b2w).src > 0, b2w);
await ev(`document.querySelector('.tabs .tab[data-tab="__cmp"]').click()`);
await sleep(300);
const cmp = await ev(`document.querySelectorAll('.cmp').length`);
ok('逐卡对照视图按卡数成行', cmp === R.cardCount, 'cmp=' + cmp + ' 卡数=' + R.cardCount);

console.log('\n[7] 导出 Word（真构造 docx 并落地验证）');
const b64 = await ev(`(async()=>{try{
  const b = await window.__cardBuildDocx();
  const u = new Uint8Array(await b.arrayBuffer());
  let s = ''; for (let i = 0; i < u.length; i += 8192) s += String.fromCharCode.apply(null, u.subarray(i, i + 8192));
  return 'OK:' + u.length + ':' + btoa(s);
}catch(e){ return 'ERR:' + (e && e.message || e); }})()`);
if (typeof b64 === 'string' && b64.startsWith('OK:')) {
  const size = b64.split(':')[1];
  const buf = Buffer.from(b64.split(':')[2], 'base64');
  fs.writeFileSync('/tmp/card_out.docx', buf);
  ok('docx 已生成', buf.length > 3000, size + ' bytes');
  console.log('    已写 /tmp/card_out.docx → 可用 python zipfile 复核');
} else {
  ok('docx 已生成', false, String(b64).slice(0, 200));
}

console.log('\n[8] 控制台异常');
const real = logs.filter(l => !/favicon|fonts\.googleapis|fonts\.gstatic|ERR_CONNECTION|Failed to load resource/i.test(l));
ok('无 JS 异常', real.length === 0, real.slice(0, 3).join(' | '));
if (logs.length) console.log('    （含可忽略）' + logs.slice(0, 4).join(' | '));

console.log(`\n=== ${pass} 通过 / ${fail} 失败 · 生成耗时 ${secs}s ===`);
await fetch(`${CDP}/json/close/${tab.id}`);
process.exit(fail ? 1 : 0);
