// 「轻量提示词」入口（lite）回归探针 —— 2026-09-23
//
// 为什么需要它：lite 与 CEFR文章分级（licensed）**共用 state.lic 状态机与生成后的渲染页**，
// 但少了三样 licensed 的前提：没有 st.prep（图 A 的分段结果）、没有校验数据、没有确认页。
// 这三样东西散落在 s0 / s6 / s7 的判断里 —— 少改一处就是「点了没反应」或「一片空白」，
// 而读代码看不出来（每处单看都通顺），必须真的走一遍：
//   入口出现 → 粘贴 → 生成 → 三档文章+9题建好 → 每个后续页面都不是空白。
//
// 断言（任一失败即退出码 1）：
//   ① 素材选择页有 5 个入口，第 5 个是「轻量提示词」
//   ② 进入后 #litePanel 存在，未粘正文时底部是「请先粘贴」等待态
//   ③ 粘贴后统计行更新、底部按钮变为可点
//   ④ 图 C 返回正常数据 → GEN 建成 A1/A2/B1 三档，quiz 三档各 3 题
//   ⑤ 母稿（B1）由前端补齐并入库，且是用户粘贴的原文
//   ⑥ AI 校验页（idx 8）**不是空白**，明确写着「本链路不做质量校验」
//   ⑦ 生成后自动落在内容生成页（idx 7）且渲染出文章预览
//   ⑧ 负向：parse_ok=false 时必须有错误条 + 重试按钮，且 GEN 保持为空（不静默、不留白）
//   ⑨ 负向：无正文时点「生成」不得发起调用
//
// 用法：
//   cd <repo> && node tools/probe_lite_route.mjs
// 前置：frontend/ 下起静态服务（python3 -m http.server 8899 --bind 127.0.0.1，需后台运行）
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const PORT = Number(process.env.CDP_PORT || 9275);
const CDP = `http://127.0.0.1:${PORT}`;
const PROFILE = path.join(os.tmpdir(), `readpal_lite_${PORT}`);
const URL_ = process.env.URL_ || 'http://127.0.0.1:8899/index.html';
const sleep = ms => new Promise(r => setTimeout(r, ms));

function findChrome() {
  const c = [process.env.CHROME_BIN,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium'].filter(Boolean);
  return c.find(p => { try { return fs.statSync(p).isFile(); } catch { return false; } });
}
const alive = async () => { try { await fetch(`${CDP}/json/version`); return true; } catch { return false; } };
async function ensureChrome() {
  if (await alive()) return null;
  const bin = findChrome();
  if (!bin) { console.error('找不到 Chrome，请设 CHROME_BIN'); process.exit(1); }
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const child = spawn(bin, ['--headless=new', '--disable-gpu', '--no-sandbox',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, '--hide-scrollbars', 'about:blank'],
    { stdio: 'ignore', detached: false });
  for (let i = 0; i < 40; i++) { await sleep(400); if (await alive()) return child; }
  console.error('Chrome 启动超时'); process.exit(1);
}

const MASTER = [
  'Sam Gosling is a psychologist who studies what our rooms say about us.',
  'He walked into hundreds of offices and looked at the desks.',
  'Some desks were tidy. Others were covered with paper and cups.',
  'Gosling found that a messy desk can help people try new things.',
  'A tidy desk, he says, makes people follow the rules and choose safe options.',
  'Still, most offices tell their workers to keep things clean.',
].join('\n');
const MASTER_TITLE = 'What Your Desk Says About You';

const A1_PARAS = ['Sam studies rooms.', 'He looked at many desks.', 'Some desks were messy.'];
const A2_PARAS = ['Sam Gosling studies what rooms say about us.', 'He visited many offices and looked at the desks.', 'Some desks were tidy, and others were messy.'];
const Q = (t) => ({ type: t, q: 'Sample question?', options: ['a', 'b', 'c', 'd'], answer: 0, explain: '中文解析' });

const MOCK_OK = {
  articles_json: JSON.stringify({ A1: A1_PARAS.join('\n\n'), A2: A2_PARAS.join('\n\n') }),
  paras_json: JSON.stringify({ A1: A1_PARAS, A2: A2_PARAS }),
  quiz_json: JSON.stringify({ levels: { A1: [Q('language'), Q('language'), Q('text')], A2: [Q('language'), Q('text'), Q('logic')], B1: [Q('text'), Q('logic'), Q('cognitive')] } }),
  parse_ok: 'true', parse_warn: '', title: MASTER_TITLE,
};
const MOCK_BAD = { articles_json: '{}', paras_json: '{}', quiz_json: '{"levels":{}}', parse_ok: 'false', parse_warn: 'JSON 解析失败：Unexpected token', title: '' };

const SETUP = `(async()=>{
  const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
  const out={};
  const errs=[];
  const _ce=console.error; console.error=function(){ errs.push(Array.prototype.slice.call(arguments).join(' ').slice(0,120)); return _ce.apply(console,arguments); };

  document.getElementById("loginOv").style.display="none";
  state.user={role:"produce",name:"curriculum_li",sources:(typeof initSources==="function"?initSources("produce"):[])};
  if(typeof refreshUserChip==="function") refreshUserChip();
  if(typeof buildRail==="function") buildRail();
  state.tagContent=["world"];
  /* 封面生成会发网络请求，探针里不需要 —— 换成空函数，避免污染 console.error 收集 */
  if(typeof genLiveCover==="function") window.genLiveCover=function(){};

  /* ① 五个入口 */
  go(0); state.route=null; render(); await sleep(200);
  const cards=Array.prototype.slice.call(document.querySelectorAll(".routegrid .srccard"));
  out.cardCount=cards.length;
  out.cardNames=cards.map(function(c){ const h=c.querySelector("h4"); return h?h.textContent.trim():"(none)"; });
  out.card5 = out.cardNames[4]||"";

  /* ② 进入 lite 入口 */
  pickRoute("lite"); await sleep(300);
  out.hasLitePanel=!!document.getElementById("litePanel");
  out.hasTitleInput=!!document.getElementById("liteTitle");
  out.hasPasteBox=!!document.getElementById("litePaste");
  const bar0=document.querySelector("#stage .nextbar, #stage .waitbar");
  out.embark0=bar0?bar0.textContent.trim().slice(0,40):"(none)";
  out.embark0Clickable=!!(bar0&&bar0.querySelector("button"));
  out.routeIsLite=state.route;

  /* ③ 粘贴正文 */
  let ta=document.getElementById("litePaste");
  ta.value=${JSON.stringify(MASTER)};
  ta.dispatchEvent(new Event("input",{bubbles:true}));
  await sleep(150);
  document.getElementById("liteTitle").value=${JSON.stringify(MASTER_TITLE)};
  document.getElementById("liteTitle").dispatchEvent(new Event("input",{bubbles:true}));
  await sleep(150);
  const stat=document.getElementById("liteStat");
  out.statText=stat?stat.textContent.replace(/\\s+/g," ").trim().slice(0,80):"(none)";
  const bar1=document.querySelector("#stage .nextbar, #stage .waitbar");
  out.embark1=bar1?bar1.textContent.trim().slice(0,40):"(none)";
  out.embark1Clickable=!!(bar1&&bar1.querySelector("button"));

  /* ⑩ 负向对照：抽掉 liteRefreshBar（模拟这个修复不存在）→ 粘贴后按钮**必须仍停在等待态**。
     这证明上面那条断言真的在测那个函数，而不是碰巧成立。
     ⚠️ 必须先把页面渲染回等待态（正文置空 + render），否则按钮会停在上一次已经变可点的状态，
     那样无论抽不抽掉刷新函数都是 clickable=true，对照就失去意义。 */
  const realRefresh=window.liteRefreshBar;
  window.liteRefreshBar=function(){};
  state.lic.liteText="";
  render();
  await sleep(250);
  const barB=document.querySelector("#stage .nextbar, #stage .waitbar");
  out.mutBeforeClickable=!!(barB&&barB.querySelector("button"));
  const ta2=document.getElementById("litePaste");
  ta2.value=${JSON.stringify(MASTER)};
  ta2.dispatchEvent(new Event("input",{bubbles:true}));
  await sleep(250);
  const barM=document.querySelector("#stage .nextbar, #stage .waitbar");
  out.mutClickable=!!(barM&&barM.querySelector("button"));
  out.mutStateHasText=!!String(state.lic.liteText||"").trim();
  window.liteRefreshBar=realRefresh;
  ta=document.getElementById("litePaste");

  /* ⑨ 负向：清空正文后点生成，不得发起任何调用 */
  let callCount=0;
  const realDify=difyCall;
  window.difyCall=async function(){ callCount++; return {data:{status:"succeeded",outputs:${JSON.stringify(MOCK_OK)}}}; };
  const saved=state.lic.liteText;
  state.lic.liteText="";
  await liteRun();
  out.negNoTextCalls=callCount;

  /* ④⑥⑦ 正常路径 */
  state.lic.liteText=saved;
  state.lic.liteTitle=${JSON.stringify(MASTER_TITLE)};
  await liteRun();
  await sleep(900);
  out.callsAfterRun=callCount;
  out.cur=cur;
  out.genKeys=Object.keys(GEN).sort();
  out.genA1Paras=(GEN.A1&&GEN.A1.paras)?GEN.A1.paras.length:0;
  out.genA2Paras=(GEN.A2&&GEN.A2.paras)?GEN.A2.paras.length:0;
  out.genB1Paras=(GEN.B1&&GEN.B1.paras)?GEN.B1.paras.length:0;
  out.genB1IsMaster=!!(GEN.B1&&GEN.B1.paras&&String(GEN.B1.paras[0][0]||"").indexOf("Sam Gosling is a psychologist")>=0);
  out.genTitles=[GEN.A1&&GEN.A1.title,GEN.A2&&GEN.A2.title,GEN.B1&&GEN.B1.title];
  out.quizLevels=Object.keys(state.quiz||{}).sort();
  out.quizCounts=Object.keys(state.quiz||{}).sort().map(function(k){return k+":"+(state.quiz[k]||[]).length;});
  out.quizTypesB1=(state.quiz.B1||[]).map(function(q){return q.type;});
  out.liveStatus=state.live&&state.live.status;
  out.liveLicN=state.live&&state.live.licN;
  out.errText=(state.lic&&state.lic.err)||"";

  /* 页面渲染巡检：每个后续页面都不能是空白 */
  const probePage=async function(idx){
    go(idx); await sleep(450);
    const wrap=document.querySelector("#stage .wrap");
    const txt=wrap?wrap.textContent.replace(/\\s+/g," ").trim():"";
    return { idx:idx, len:txt.length, head:txt.slice(0,60) };
  };
  out.page7=await probePage(7);
  /* ⑥ AI 校验页：lite 必须给明确说明，不是空壳 */
  out.page8=await probePage(8);
  out.page8HasNoValidateNote = out.page8.head.indexOf("不做质量校验")>=0 || out.page8.head.indexOf("本链路")>=0;
  out.page9=await probePage(9);
  out.page10=await probePage(10);
  out.page11=await probePage(11);
  out.page0=await probePage(0);

  /* ⑧ 负向：解析失败必须显式报错 + 重试，且 GEN 保持为空 */
  const before=Object.keys(GEN).length;
  window.difyCall=async function(){ callCount++; return {data:{status:"succeeded",outputs:${JSON.stringify(MOCK_BAD)}}}; };
  state.lic.liteText=${JSON.stringify(MASTER)};
  GEN={}; state.quiz={};
  await liteRun();
  await sleep(600);
  out.badErrShown=!!(state.lic&&state.lic.err);
  out.badErrText=String((state.lic&&state.lic.err)||"").slice(0,70);
  out.badGenEmpty=Object.keys(GEN).length===0;
  go(0); await sleep(400);
  const need=document.querySelector("#stage .licneed");
  out.badNeedBar=!!need;
  out.badNeedHasRetry=!!(need&&need.querySelector("button"));
  out.badConsoleErrs=errs.length;

  window.difyCall=realDify;
  console.error=_ce;
  return JSON.stringify(out);
})()`;

async function main() {
  const chrome = await ensureChrome();
  const tab = await (await fetch(`${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pending = new Map();
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  });
  const send = (method, params = {}) => new Promise(res => { const mid = ++id; pending.set(mid, res); ws.send(JSON.stringify({ id: mid, method, params })); });
  const evaluate = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result?.exceptionDetails) return 'ERR: ' + (r.result.exceptionDetails.exception?.description || '');
    return r.result?.result?.value;
  };
  await send('Runtime.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: URL_ });
  await sleep(6000);

  const raw = await evaluate(SETUP);
  if (typeof raw !== 'string' || raw.startsWith('ERR')) {
    console.error('探针执行失败:', raw); ws.close(); if (chrome) chrome.kill(); process.exit(1);
  }
  const o = JSON.parse(raw);

  let pass = 0, fail = 0;
  const ok = (name, cond, extra = '') => {
    if (cond) { pass++; console.log(`  ✓ ${name}`); }
    else { fail++; console.log(`  ✗ ${name}   ${extra}`); }
  };

  console.log('\n[1] 入口');
  ok('素材选择页有 5 个入口', o.cardCount === 5, `实际 ${o.cardCount}：${(o.cardNames || []).join(' / ')}`);
  ok('第 5 个是「轻量提示词」', o.card5 === '轻量提示词', o.card5);
  ok('4 个原有入口未被顶掉', o.cardNames[0] === '热点搜集' && o.cardNames[1] === '自有 / 合作版权' && o.cardNames[2] === '英文公版书' && o.cardNames[3] === 'CEFR文章分级');

  console.log('\n[2] 面板与按钮');
  ok('state.route = lite', o.routeIsLite === 'lite');
  ok('#litePanel 存在', o.hasLitePanel);
  ok('标题输入存在', o.hasTitleInput);
  ok('正文粘贴框存在', o.hasPasteBox);
  ok('未粘正文时是等待态（无按钮）', !o.embark0Clickable && /请先粘贴/.test(o.embark0), o.embark0);
  ok('粘贴后统计行显示词数与段数', /词/.test(o.statText) && /段/.test(o.statText), o.statText);
  ok('粘贴后按钮可点', o.embark1Clickable, o.embark1);
  ok('负向对照：抽掉 liteRefreshBar 后按钮停在等待态',
     o.mutBeforeClickable === false && !o.mutClickable && o.mutStateHasText,
     `before=${o.mutBeforeClickable} after=${o.mutClickable} stateHasText=${o.mutStateHasText}`);

  console.log('\n[3] 生成结果（mock 图 C）');
  ok('无正文时不发起调用', o.negNoTextCalls === 0, `callCount=${o.negNoTextCalls}`);
  ok('正常路径调用 1 次', o.callsAfterRun === 1, `callCount=${o.callsAfterRun}`);
  ok('GEN 建成 A1/A2/B1 三档', o.genKeys.join(',') === 'A1,A2,B1', o.genKeys.join(','));
  ok('A1 段落数 = 3', o.genA1Paras === 3, String(o.genA1Paras));
  ok('A2 段落数 = 3', o.genA2Paras === 3, String(o.genA2Paras));
  ok('B1 段落数 = 母稿 6 段', o.genB1Paras === 6, String(o.genB1Paras));
  ok('B1 内容 = 用户粘贴的母稿原文', o.genB1IsMaster);
  ok('标题用导入时填的（锁定不被模型覆盖）', (o.genTitles || []).every(t => t === MASTER_TITLE), JSON.stringify(o.genTitles));
  ok('quiz 三档齐', o.quizLevels.join(',') === 'A1,A2,B1', o.quizLevels.join(','));
  ok('三档各 3 题', o.quizCounts.join('|') === 'A1:3|A2:3|B1:3', o.quizCounts.join('|'));
  ok('B1 题型 = text/logic/cognitive', (o.quizTypesB1 || []).join(',') === 'text,logic,cognitive', (o.quizTypesB1 || []).join(','));
  ok('licN = 模型实际段数（非默认 12）', o.liveLicN === 3, String(o.liveLicN));
  ok('无错误残留', !o.errText, o.errText);

  console.log('\n[4] 后续页面都不空白');
  ok('生成后落在内容生成页 idx=7', o.cur === 7, String(o.cur));
  [['内容生成', o.page7], ['AI 校验', o.page8], ['段落校对', o.page9], ['逐段审核', o.page10], ['文章库', o.page11], ['素材选择', o.page0]].forEach(([n, p]) => {
    ok(n + ` 页有内容（len=${p.len}）`, p.len > 40, JSON.stringify(p));
  });
  ok('AI 校验页写明「不做质量校验」', o.page8HasNoValidateNote, o.page8.head);

  console.log('\n[5] 负向：解析失败');
  ok('有错误条', o.badErrShown);
  ok('错误文案说明解析失败', /解析|parse/i.test(o.badErrText), o.badErrText);
  ok('GEN 保持为空（不写半成品）', o.badGenEmpty);
  ok('页面上确有 .licneed 红条', o.badNeedBar);
  ok('红条带「重试生成」按钮', o.badNeedHasRetry);
  ok('全程无 console.error', o.badConsoleErrs === 0, `console.error × ${o.badConsoleErrs}`);

  console.log(`\n${fail === 0 ? '✅' : '✗'} ${pass}/${pass + fail} 通过`);
  ws.close(); if (chrome) chrome.kill();
  process.exit(fail === 0 ? 0 : 1);
}
main();
