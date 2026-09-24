// 「轻量提示词」骨架锁定链路回归探针 —— 2026-09-24
//
// 为什么需要它：lite 从「裸产出对照实验」改成「骨架锁定」生产链路后，多了一条**结构约束**：
//   ① 定骨架（调图 A，need_simplify=false）—— 按大意切、逐字保留原文
//   ② 确认页（可改 / 可删 / 可合并 / 可一键重切）
//   ③ 生成时把骨架**拼进 master_text**（图 C 一个字不改）
//   ④ 生成后用**代码**校验 A1-/A2 段数是否等于骨架段数，不齐带差量回炉（上限 3 次），仍不齐报警
// 这四步里 ①②④ 全是新的，且都是「读代码看着对、跑起来才发现错」的类型：
//   · 编辑段落不能只看输入框 —— 必须验 GEN/state 里那份数据真的变了（同段落校对的教训）；
//   · 骨架注入不能只看代码拼了字符串 —— 必须验**真实发出去的请求体**里有没有它；
//   · 回炉不能只看"调了几次" —— 必须验第二次请求体里带着**量出来的差量**（第几次几段）。
//
// 断言（任一失败即退出码 1）：
//   [1] 定骨架：调用的是 licprep、need_simplify=false、level=B1；#liteSkel 渲染；
//       导入面板让位；每段一行、标签齐全
//   [2] 确认页交互：编辑落进 state.prep.segs[0] 且词数标签同步 / 合并 -1 段且内容拼上 /
//       删除 -1 段 / 「返回改母稿」清骨架但**保留正文**
//   [3] 骨架注入：图 C 的真实请求体含【段落骨架】+「段数必须正好 N 段」+ 逐段编号
//   [4] 母稿档（B1）= 骨架（不是另按空行切一份）⇒ 四档段数天然一致；licN = 骨架段数
//   [5] 段数不齐 → 回炉一次；第二次请求体带差量「现在是 2 段」；回来后 skelWarn 清空
//   [6] 一直不齐 → 调满 3 次、报警写进 state.live.skelWarn、**不阻断**（GEN 仍建成、仍落到 7）
//   [7] 负向对照：没有骨架时**不进校验分支**（licN 退回模型实际段数）—— 证明上面测的确实是新逻辑
//
// 用法：
//   cd <repo> && node tools/probe_lite_skeleton.mjs
// 前置：frontend/ 下起静态服务（python3 -m http.server 8899 --bind 127.0.0.1，需后台运行）
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const PORT = Number(process.env.CDP_PORT || 9276);
const CDP = `http://127.0.0.1:${PORT}`;
const PROFILE = path.join(os.tmpdir(), `readpal_liteskel_${PORT}`);
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

/* 图 A 的骨架产出：把上面 6 行合成 3 段（模拟「按大意切」） */
const SKEL = [
  'Sam Gosling is a psychologist who studies what our rooms say about us. He walked into hundreds of offices and looked at the desks.',
  'Some desks were tidy. Others were covered with paper and cups.',
  'Gosling found that a messy desk can help people try new things.',
];
const A1_PARAS = ['Sam studies rooms.', 'He looked at many desks.', 'Some desks were messy.'];
const A2_PARAS = ['Sam Gosling studies what rooms say about us.', 'He visited many offices and looked at the desks.', 'Some desks were tidy, and others were messy.'];
const Q = t => ({ type: t, q: 'Sample question?', options: ['a', 'b', 'c', 'd'], answer: 0, explain: '中文解析' });
const QUIZ = JSON.stringify({ levels: { A1: [Q('language'), Q('language'), Q('text')], A2: [Q('language'), Q('text'), Q('logic')], B1: [Q('text'), Q('logic'), Q('cognitive')] } });
const MOCK_OK = {
  articles_json: JSON.stringify({ A1: A1_PARAS.join('\n\n'), A2: A2_PARAS.join('\n\n') }),
  paras_json: JSON.stringify({ A1: A1_PARAS, A2: A2_PARAS }),
  quiz_json: QUIZ, parse_ok: 'true', parse_warn: '', title: MASTER_TITLE,
};
const PREP_OUT = { segments_json: JSON.stringify(SKEL), word_count: '61', ok: 'true', warn: '' };

const SETUP = `(async()=>{
  const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
  const out={};
  const warns=[];
  const _cw=console.warn; console.warn=function(){ warns.push(Array.prototype.slice.call(arguments).join(' ').slice(0,160)); return _cw.apply(console,arguments); };
  const SKEL=${JSON.stringify(SKEL)};
  const A1_PARAS=${JSON.stringify(A1_PARAS)};
  const A2_PARAS=${JSON.stringify(A2_PARAS)};

  document.getElementById("loginOv").style.display="none";
  state.user={role:"produce",name:"curriculum_li",sources:(typeof initSources==="function"?initSources("produce"):[])};
  if(typeof refreshUserChip==="function") refreshUserChip();

  let calls=[], liteN=0;
  const realDify=difyCall;
  const stub=function(prepOut, liteOut){
    window.difyCall=async function(wf, inputs){
      calls.push({wf:wf, inputs:inputs});
      if(wf==="licprep") return {data:{status:"succeeded", outputs:prepOut}};
      if(wf==="lite"){ liteN++; return {data:{status:"succeeded", outputs:(typeof liteOut==="function"?liteOut(liteN):liteOut)}}; }
      return {data:{status:"succeeded", outputs:{}}};
    };
  };
  stub(${JSON.stringify(PREP_OUT)}, ${JSON.stringify(MOCK_OK)});

  /* ---- [1] 定骨架 ---- */
  pickRoute("lite"); await sleep(300);
  licState().liteText=${JSON.stringify(MASTER)};
  licState().liteTitle=${JSON.stringify(MASTER_TITLE)};
  render(); await sleep(200);
  const eb=document.getElementById("liteBar")?document.getElementById("liteBar").querySelector("button"):null;
  out.embarkLabel=eb?eb.textContent.trim():"(none)";
  await litePrep(); await sleep(350);

  out.prepWf=calls[0]&&calls[0].wf;
  out.prepNeedSimplify=calls[0]&&calls[0].inputs.need_simplify;
  out.prepLevel=calls[0]&&calls[0].inputs.level;
  out.prepMaterialLen=calls[0]?String(calls[0].inputs.material||"").length:0;
  out.prepSegs=(licState().prep&&licState().prep.segs.length)||0;
  out.hasSkel=!!document.querySelector("#liteSkel");
  out.panelGone=!document.querySelector("#litePanel");
  out.skelRows=document.querySelectorAll("#liteSkel .licseg").length;
  out.skelTags=Array.prototype.slice.call(document.querySelectorAll("#liteSkel .tint")).map(function(n){return n.textContent.trim();});
  out.skelBtns=Array.prototype.slice.call(document.querySelectorAll("#liteSkel .nextbar button")).map(function(b){return b.textContent.trim();});
  out.segWordLabels=Array.prototype.slice.call(document.querySelectorAll("#liteSkel .licsegw")).map(function(n){return n.textContent.trim();});
  out.bandText=Array.prototype.slice.call(document.querySelectorAll("#liteSkel .licsegt")).map(function(n){return n.textContent.trim();});

  /* ---- [2] 确认页交互（判据 = state 里那份数据，不是输入框）---- */
  const ta0=document.querySelectorAll("#liteSkel .licseg textarea")[0];
  ta0.value="Edited first paragraph about the study of rooms and desks.";
  ta0.dispatchEvent(new Event("input",{bubbles:true}));
  await sleep(150);
  out.editStored=licState().prep.segs[0];
  out.editLabel=(document.getElementById("licSegW0")||{}).textContent;
  out.editTaLen=ta0.value.length;

  const nBefore=licState().prep.segs.length;
  licMergeSeg(0); await sleep(200);
  out.mergeBefore=nBefore;
  out.mergeAfter=licState().prep.segs.length;
  out.mergeHasBoth=licState().prep.segs[0].indexOf("Edited first paragraph")>=0 && licState().prep.segs[0].indexOf("Some desks were tidy")>=0;

  licDelSeg(0); await sleep(200);
  out.delAfter=licState().prep.segs.length;

  const btns2=Array.prototype.slice.call(document.querySelectorAll("#liteSkel .nextbar button"));
  out.backLabel=btns2.length?btns2[btns2.length-1].textContent.trim():"(none)";
  if(btns2.length) btns2[btns2.length-1].click();
  await sleep(250);
  out.backPanel=!!document.querySelector("#litePanel");
  out.backSkelCleared=licState().prep===null;
  out.backTextKept=String(licState().liteText||"").indexOf("Sam Gosling")>=0;

  /* 重新定骨架（点底部「定骨架」按钮） */
  const eb2=document.getElementById("liteBar")?document.getElementById("liteBar").querySelector("button"):null;
  if(eb2) eb2.click();
  await sleep(450);
  out.reSkelSegs=(licState().prep&&licState().prep.segs.length)||0;

  /* ---- [3][4] 生成：骨架注入 + 母稿档取骨架 ---- */
  calls=[]; liteN=0;
  GEN={}; state.quiz={};
  const skelSnap=licState().prep.segs.slice();
  await liteRun(); await sleep(1000);
  const gc=calls.filter(function(c){return c.wf==="lite";});
  out.genCallCount=gc.length;
  const gm=gc[0]?String(gc[0].inputs.master_text||""):"";
  out.genHasSkelBlock=gm.indexOf("【段落骨架】")>=0;
  out.genHasCountRule=gm.indexOf("段数必须正好 3 段")>=0;
  out.genHasNumbered=gm.indexOf("\\n1. ")>=0&&gm.indexOf("\\n2. ")>=0&&gm.indexOf("\\n3. ")>=0;
  out.genSkelHead=gm.slice(0,110).replace(/\\s+/g," ");
  out.genHasNoKeepList=gm.indexOf("保留清单")<0&&gm.indexOf("必须保留")<0;
  /* 逐段篇幅：2026-09-24 真模型实测 —— 漏了这行，段数能对齐但每段会写成 20–30 词（规格 11–14）。
     所以它必须**在骨架列表之后**出现，且带 A1-/A2 两档区间。 */
  out.genPerLine=(gm.match(/【逐段篇幅】A1- 每段 11–14 词；A2 每段 20–22 词。按段分别控制，不卡全文字数。/g)||[]).length;
  out.genPerLineAfterSkel=gm.indexOf("【逐段篇幅】")>gm.indexOf("3. ");
  out.genTitleIn=gc[0]?gc[0].inputs.title_in:"";
  out.b1Paras=(GEN.B1&&GEN.B1.paras)?GEN.B1.paras.length:0;
  out.b1First=(GEN.B1&&GEN.B1.paras)?String(GEN.B1.paras[0][0]||"").slice(0,44):"";
  out.b1EqSkel=out.b1Paras===skelSnap.length;
  out.licN=state.live&&state.live.licN;
  out.skelWarnOk=state.live&&state.live.skelWarn;
  out.landed=cur;
  out.genKeys=Object.keys(GEN).sort().join(",");

  /* ---- [5] 段数不齐 → 回炉一次 ---- */
  calls=[]; liteN=0;
  GEN={}; state.quiz={};
  stub(${JSON.stringify(PREP_OUT)}, function(n){
    const A1=n===1?A1_PARAS.slice(0,2):A1_PARAS;
    return {articles_json:JSON.stringify({A1:A1.join("\\n\\n"),A2:A2_PARAS.join("\\n\\n")}),
            paras_json:JSON.stringify({A1:A1,A2:A2_PARAS}), quiz_json:${JSON.stringify(QUIZ)},
            parse_ok:"true", parse_warn:"", title:${JSON.stringify(MASTER_TITLE)}};
  });
  licState().prep={id:"lite",level:"B1",segs:SKEL,simplified:false,outOfBand:0,warn:""};
  render(); await sleep(200);
  await liteRun(); await sleep(1400);
  const gc2=calls.filter(function(c){return c.wf==="lite";});
  out.retryCalls=gc2.length;
  const g2=gc2[1]?String(gc2[1].inputs.master_text||""):"";
  out.retryHasFix=g2.indexOf("不合格")>=0;
  out.retryHasDelta=g2.indexOf("现在是 2 段")>=0&&g2.indexOf("必须正好 3 段")>=0;
  out.retryStillHasSkel=g2.indexOf("【段落骨架】")>=0;
  out.retryA1Paras=(GEN.A1&&GEN.A1.paras)?GEN.A1.paras.length:0;
  out.retryWarn=state.live&&state.live.skelWarn;
  out.retryErr=licState().err||null;          /* 诊断：回炉没跑起来时看这里 */
  out.retryStage=licState().errStage;

  /* ---- [6] 一直不齐 → 报警但不阻断 ---- */
  calls=[]; liteN=0; warns.length=0;
  GEN={}; state.quiz={};
  stub(${JSON.stringify(PREP_OUT)}, function(){
    return {articles_json:JSON.stringify({A1:A1_PARAS.slice(0,2).join("\\n\\n"),A2:A2_PARAS.join("\\n\\n")}),
            paras_json:JSON.stringify({A1:A1_PARAS.slice(0,2),A2:A2_PARAS}), quiz_json:${JSON.stringify(QUIZ)},
            parse_ok:"true", parse_warn:"", title:${JSON.stringify(MASTER_TITLE)}};
  });
  licState().prep={id:"lite",level:"B1",segs:SKEL,simplified:false,outOfBand:0,warn:""};
  render(); await sleep(200);
  await liteRun(); await sleep(1800);
  out.stuckCalls=calls.filter(function(c){return c.wf==="lite";}).length;
  out.stuckWarn=state.live&&state.live.skelWarn;
  out.stuckErr=licState().err||null;          /* 诊断：同上 */
  out.stuckGenBuilt=!!(GEN.A1&&GEN.A1.paras&&GEN.A1.paras.length);
  out.stuckLanded=cur;
  out.stuckConsoleWarns=warns.length;

  /* ---- [7] 负向对照：没有骨架时不进校验分支 ---- */
  calls=[]; liteN=0;
  GEN={}; state.quiz={};
  stub(${JSON.stringify(PREP_OUT)}, ${JSON.stringify(MOCK_OK)});
  licState().prep=null;
  state.lic.liteText=${JSON.stringify(MASTER)};
  render(); await sleep(150);
  await liteRun(); await sleep(900);
  const gc3=calls.filter(function(c){return c.wf==="lite";});
  out.noSkelCalls=gc3.length;
  out.noSkelHasBlock=(gc3[0]?String(gc3[0].inputs.master_text||"").indexOf("【段落骨架】"):-1)>=0;
  out.noSkelLicN=state.live&&state.live.licN;
  out.noSkelB1Paras=(GEN.B1&&GEN.B1.paras)?GEN.B1.paras.length:0;

  window.difyCall=realDify;
  console.warn=_cw;
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

  console.log('\n[1] 定骨架（图 A，need_simplify=false）');
  ok('入口底部按钮是「定骨架」而不是直接生成', /定骨架/.test(o.embarkLabel || ''), o.embarkLabel);
  ok('调的是 licprep（图 A）', o.prepWf === 'licprep', String(o.prepWf));
  ok('need_simplify 恒为 false（保留原文）', o.prepNeedSimplify === 'false', String(o.prepNeedSimplify));
  ok('母稿档 = B1', o.prepLevel === 'B1', String(o.prepLevel));
  ok('母稿正文真的传进去了', o.prepMaterialLen > 100, String(o.prepMaterialLen));
  ok('骨架建成 3 段', o.prepSegs === 3, String(o.prepSegs));
  ok('#liteSkel 渲染出来了', o.hasSkel);
  ok('导入面板让位（两个面板不同时出现）', o.panelGone);
  ok('确认页每段一行', o.skelRows === 3, String(o.skelRows));
  ok('标签含「骨架锁定」', (o.skelTags || []).indexOf('骨架锁定') >= 0, JSON.stringify(o.skelTags));
  ok('标签含「保留原文」', (o.skelTags || []).indexOf('保留原文') >= 0, JSON.stringify(o.skelTags));
  ok('每段显示词数', (o.segWordLabels || []).every(t => /词/.test(t)) && (o.segWordLabels || []).length === 3, JSON.stringify(o.segWordLabels));
  ok('每段显示目标区间', (o.bandText || []).every(t => /目标/.test(t)), JSON.stringify(o.bandText));

  console.log('\n[2] 确认页交互（判据 = 数据，不是输入框）');
  ok('编辑真的写进 state.prep.segs[0]', /Edited first paragraph/.test(o.editStored || ''), String(o.editStored).slice(0, 50));
  ok('词数标签跟着更新（10 词）', o.editLabel === '10 词', String(o.editLabel));
  ok('合并后段数 -1', o.mergeAfter === o.mergeBefore - 1, `${o.mergeBefore} → ${o.mergeAfter}`);
  ok('合并后两段内容都在同一段里', o.mergeHasBoth);
  ok('删除后段数再 -1', o.delAfter === o.mergeAfter - 1, `${o.mergeAfter} → ${o.delAfter}`);
  ok('有「返回改母稿」按钮', /返回改母稿/.test(o.backLabel || ''), o.backLabel);
  ok('返回后导入面板回来', o.backPanel);
  ok('返回清掉了骨架', o.backSkelCleared);
  ok('返回保留母稿正文（不用重贴）', o.backTextKept);
  ok('可以重新定骨架', o.reSkelSegs === 3, String(o.reSkelSegs));

  console.log('\n[3] 骨架注入（★ 图 C 一个字不改，只加持输入）');
  ok('生成只调 1 次（骨架段数与产出一致，不该回炉）', o.genCallCount === 1, String(o.genCallCount));
  ok('请求体含【段落骨架】', o.genHasSkelBlock);
  ok('含「段数必须正好 3 段」', o.genHasCountRule);
  ok('含逐段编号 1./2./3.', o.genHasNumbered);
  ok('第一版不带保留清单（刻意不做）', o.genHasNoKeepList);
  ok('带【逐段篇幅】且区间正确（A1- 11–14 / A2 20–22）', o.genPerLine === 1, String(o.genPerLine));
  ok('【逐段篇幅】排在骨架列表之后', o.genPerLineAfterSkel === true, String(o.genPerLineAfterSkel));
  ok('标题仍单独传', o.genTitleIn === MASTER_TITLE, String(o.genTitleIn));

  console.log('\n[4] 母稿档取骨架 ⇒ 四档段数一致');
  ok('B1 段数 = 骨架段数（不是母稿空行切的 6 段）', o.b1EqSkel && o.b1Paras === 3, String(o.b1Paras));
  ok('B1 首段 = 骨架第 1 段原文', /Sam Gosling is a psychologist/.test(o.b1First || ''), String(o.b1First));
  ok('licN = 骨架段数 3（不再让模型当裁判）', o.licN === 3, String(o.licN));
  ok('三档都建好', o.genKeys === 'A1,A2,B1', String(o.genKeys));
  ok('一轮过时不报警', !o.skelWarnOk, String(o.skelWarnOk));

  console.log('\n[5] 段数不齐 → 带差量回炉');
  ok('回炉了一次（共 2 次调用）', o.retryCalls === 2, String(o.retryCalls) + (o.retryErr ? ' | err=' + o.retryErr : ''));
  ok('第二次请求体带「不合格」判语', o.retryHasFix);
  ok('带**量出来的差量**（现在是 2 段 / 必须正好 3 段）', o.retryHasDelta);
  ok('回炉时骨架仍完整保留', o.retryStillHasSkel);
  ok('回炉后拿到合规产出（A1 = 3 段）', o.retryA1Paras === 3, String(o.retryA1Paras));
  ok('第二轮齐了 → 不残留报警', !o.retryWarn, String(o.retryWarn));

  console.log('\n[6] 一直不齐 → 报警但不阻断');
  ok('调满 3 次就停（不无限重试）', o.stuckCalls === 3, String(o.stuckCalls) + (o.stuckErr ? ' | err=' + o.stuckErr : ''));
  ok('报警写进 state.live.skelWarn', /段数不齐/.test(o.stuckWarn || '') && /A1- 2\/3/.test(o.stuckWarn || ''), String(o.stuckWarn));
  ok('同时写了 console.warn（不静默）', o.stuckConsoleWarns > 0, String(o.stuckConsoleWarns));
  ok('不阻断：GEN 仍然建成（可继续逐段审核手动处理）', o.stuckGenBuilt);
  ok('不阻断：仍然落到文章生产页 idx=7', o.stuckLanded === 7, String(o.stuckLanded));

  console.log('\n[7] 负向对照：没有骨架时不进校验分支');
  ok('无骨架时仍只调 1 次', o.noSkelCalls === 1, String(o.noSkelCalls));
  ok('无骨架时请求体里没有骨架块', o.noSkelHasBlock === false);
  ok('无骨架时 licN 退回模型实际段数（3）', o.noSkelLicN === 3, String(o.noSkelLicN));
  ok('无骨架时 B1 退回按原文空行切（6 段）', o.noSkelB1Paras === 6, String(o.noSkelB1Paras));

  console.log(`\n${fail === 0 ? '✅' : '✗'} ${pass}/${pass + fail} 通过`);
  ws.close(); if (chrome) chrome.kill();
  process.exit(fail === 0 ? 0 : 1);
}
main();
