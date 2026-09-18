// 分档视图（大档切换条 + 三栏对齐）回归探针 —— 2026-09-14
//
// 为什么需要它：`alignedViewHTML()` 里那种「整块 return ""」的守卫会让**同一块内**的
// 大档切换条一并消失。用真实 DOM 计数才能发现「切换条数变成 0 → 用户点不回去」这类死锁，
// 静态读代码只会看到"没内容就不渲染"这句看起来很合理的话。
//
// 场景：文章只含 A1/A2 两档（区间模型下短素材的常态）
// 断言：① 切换条在页面级（在 .reviewparas 之上 → 首屏可见）
//       ② 切到空档 B1 后切换条仍在、仍有 4 个 tab、给出空态卡片
//       ③ 能点回 A1（死锁已解）
//       ④ tab 上有「有无内容」标识（有内容=橙点+段数；空档=虚线+灰点 0）
//       ⑤ s9 段落校对 同样不丢切换条
//
// 用法：
//   cd <repo> && CDP_PORT=9233 node <此脚本>                       # 本地 8899
//   URL_=https://web-production-2a16e.up.railway.app/ CDP_PORT=9236 node <此脚本>   # 线上
// 前置：本地需先起静态服务（run_in_background=true，否则进程随 shell 退出被杀）
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const PORT = Number(process.env.CDP_PORT || 9233);
const CDP = `http://127.0.0.1:${PORT}`;
const PROFILE = path.join(os.tmpdir(), `readpal_rv_${PORT}`);
const URL_ = process.env.URL_ || 'http://127.0.0.1:8899/index.html';
const OUT = process.env.OUT || '/tmp/rp/rev_shot';
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
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const child = spawn(bin, ['--headless=new', '--disable-gpu', '--no-sandbox',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`, '--hide-scrollbars', 'about:blank'],
    { stdio: 'ignore', detached: false });
  for (let i = 0; i < 40; i++) { await sleep(400); if (await alive()) return child; }
  console.error('Chrome 启动超时'); process.exit(1);
}

const SETUP = `(async()=>{
  const log = [], shots = [];
  openLogin('review'); doLogin('review');
  await new Promise(r=>setTimeout(r,2200));
  const paras = {}, arts = {};
  const paraCount = k => (k.indexOf('A1')===0?4 : k.indexOf('A2')===0?5 : k.indexOf('B1')===0?6 : 8);
  ['A1_1','A1_2','A1_3','A2_1','A2_2','A2_3'].forEach(function(k){
    const n = paraCount(k), arr = [];
    for (let i=0;i<n;i++) arr.push('[' + nkDisp(k) + ' P' + (i+1) + '] The city trees make nearby streets cooler in summer, and the study looked at many trees in one season.');
    paras[k] = arr; arts[k] = arr.join('\\n\\n');
  });
  LEVELS12.forEach(function(l){ if(!paras[l.key]){ paras[l.key]=[]; arts[l.key]=''; } });
  const mkQ = k => ['language','text','logic'].map(function(t,i){
    return { q:'Sample question ' + (i+1) + ' for ' + k + '?', options:['Option A','Option B','Option C','Option D'], answer:0, type:t };
  });
  const quiz = {};
  ['A1_1','A1_2','A1_3','A2_1','A2_2','A2_3'].forEach(function(k){ quiz[k]=mkQ(k); });
  LEVELS12.forEach(function(l){ if(!quiz[l.key]) quiz[l.key]=[]; });
  const rec = { id:'TEST-A12', title:'Short Material Article (A1–A2 only)', level:'A2_2', style:'default',
    material:{ label:'Short Material', source:'manual', url:'', text:'Short source material text.' },
    articles:arts, paras:paras, facts:['Fact one.'], identity:{ contentId:'TEST-A12', tags:[] },
    coverDataUrl:'', coverPrompt:'', audio:{}, audioMeta:null, quiz:quiz, guide:{},
    factMap:null, unusedFacts:[], createdAt:Date.now(), createdByRole:'source', reviewedBy:'' };
  localStorage.setItem('wb_content_bank_v1', JSON.stringify([rec]));
  reviewDraftFromBank('TEST-A12');
  await new Promise(r=>setTimeout(r,900));

  function snap(tag){
    const bar = document.querySelector('.bigbar');
    const tabs = Array.from(document.querySelectorAll('.bigtab')).map(function(t){
      const n = t.querySelector('.bt-n');
      return { g: t.querySelector('b').textContent, sel: t.classList.contains('sel'),
               blank: t.classList.contains('blank'), n: n ? n.textContent : null,
               off: n ? n.classList.contains('off') : null };
    });
    // 切换条是否在页面级：它是否位于 .reviewparas 之前
    const rp = document.querySelector('.reviewparas');
    const above = bar && rp ? (bar.compareDocumentPosition(rp) & Node.DOCUMENT_POSITION_FOLLOWING) > 0 : null;
    return { tag: tag, big: state.big, lvl: state.lvl,
      bigbar: document.querySelectorAll('.bigbar').length,
      bigtab: document.querySelectorAll('.bigtab').length,
      tabs: tabs,
      pcard: document.querySelectorAll('.pcard').length,
      aligngrid: document.querySelectorAll('.aligngrid').length,
      svempty: document.querySelectorAll('.pcard.svempty').length,
      svemptyText: (document.querySelector('.pcard.svempty .svempty-t')||{}).textContent || null,
      barAboveParas: above,
      barTopPx: bar ? Math.round(bar.getBoundingClientRect().top + window.scrollY) : null
    };
  }
  log.push(snap('① 进入审核（默认 A2）'));
  setBig('B1');
  await new Promise(r=>setTimeout(r,700));
  log.push(snap('② 点 B1（空档）→ 修复点'));
  shots.push('B1空档');
  setBig('A1');
  await new Promise(r=>setTimeout(r,700));
  log.push(snap('③ 点回 A1 → 死锁已解'));
  shots.push('A1回来');
  setBig('B2+');
  await new Promise(r=>setTimeout(r,700));
  log.push(snap('④ 点 B2+（空档）'));
  setBig('A2');
  await new Promise(r=>setTimeout(r,700));
  log.push(snap('⑤ 点回 A2'));
  // s9 段落校对
  go(9);
  await new Promise(r=>setTimeout(r,900));
  log.push(snap('⑥ s9 段落校对（A2 有内容）'));
  setBig('B1');
  await new Promise(r=>setTimeout(r,700));
  log.push(snap('⑦ s9 切到 B1 空档'));
  window.__log = JSON.stringify(log, null, 1);
  window.__shots = shots;
  return window.__log;
})()`;

async function main() {
  const chrome = await ensureChrome();
  const tab = await (await fetch(`${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pending = new Map(); const errs = [];
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === 'Runtime.exceptionThrown') errs.push(m.params?.exceptionDetails?.exception?.description || 'exc');
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
  const out = await evaluate(SETUP);
  console.log(typeof out === 'string' ? out : JSON.stringify(out, null, 1));

  // 停在 s9 B1 空档态截图
  await evaluate(`(()=>{const e=document.querySelector('.bigbar'); if(e) e.scrollIntoView({block:'start'}); window.scrollBy(0,-70); return 1;})()`);
  await sleep(600);
  let shot = await send('Page.captureScreenshot', { captureBeyondViewport: false });
  fs.writeFileSync(`${OUT}_s9空档.png`, Buffer.from(shot.result.data, 'base64'));

  // 回到审核页空档态截图
  await evaluate(`(async()=>{ reviewDraftFromBank('TEST-A12'); await new Promise(r=>setTimeout(r,700)); setBig('B1'); await new Promise(r=>setTimeout(r,700)); const e=document.querySelector('.bigbar'); if(e) e.scrollIntoView({block:'start'}); window.scrollBy(0,-70); return 1; })()`);
  await sleep(700);
  shot = await send('Page.captureScreenshot', { captureBeyondViewport: false });
  fs.writeFileSync(`${OUT}_审核空档.png`, Buffer.from(shot.result.data, 'base64'));

  console.log('JS 异常:', errs.length ? errs.join('\n') : '（无）');
  console.log('截图:', `${OUT}_s9空档.png`, `${OUT}_审核空档.png`);
  ws.close(); if (chrome) chrome.kill();
}
main().catch(e => { console.error('FAIL', e); process.exit(1); });
