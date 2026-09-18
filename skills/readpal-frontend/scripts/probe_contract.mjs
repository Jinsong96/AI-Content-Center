// ReadPal · 运行时契约探针（stub fetch，抓真实请求体）
//
// 为什么需要它：静态读代码只能证明「源码长这样」，证明不了「运行时真的这么发」。
// 改了 Dify 入参（wfInputs）后，用它把真实请求体抓出来看，比重读一遍源码可靠得多。
//
// 原理：把 window.fetch 换成记录器并立即 reject。两个调用点都包在 try/catch 里
// （startLiveRun / runGeneration），reject 被内部吞掉、不污染页面状态，但请求体已拿到。
//
// 用法：
//   node scripts/probe_contract.mjs [--url=http://127.0.0.1:8899/index.html] [--port=9222]
//
// ⚠️ 两个必须踩对的前提（踩过）：
//   1. 本地没有 config.local.js → AIWF_*.appKey 为空 → 函数内部提前 throw，
//      表现为 captured 为空数组。本脚本会先补一个假 key。
//   2. runGeneration 有守卫 `if(!fc || !fc.summary || !fc.facts_text)`，
//      所以脚本自己造 state.factsCache（含 gist）。
//
// 退出码：0 抓到至少 1 个请求；1 一个都没抓到

import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const argv = process.argv.slice(2);
const arg = (k, d = null) => {
  const hit = argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};

const URL_ = arg('url', 'http://127.0.0.1:8899/index.html');
const PORT = Number(arg('port', process.env.CDP_PORT || 9222));
const CDP = `http://127.0.0.1:${PORT}`;
const PROFILE = path.join(os.tmpdir(), `readpal_probe_${PORT}`);
const sleep = ms => new Promise(r => setTimeout(r, ms));

function findChrome() {
  const c = [process.env.CHROME_BIN,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium'].filter(Boolean);
  return c.find(p => { try { return fs.statSync(p).isFile(); } catch { return false; } });
}
const alive = async () => { try { await fetch(`${CDP}/json/version`); return true; } catch { return false; } };

async function ensureChrome() {
  if (await alive()) { console.log('复用已在运行的 Chrome'); return null; }
  const bin = findChrome();
  if (!bin) { console.error('找不到 Chrome，请设 CHROME_BIN'); process.exit(1); }
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const child = spawn(bin, ['--headless=new', '--disable-gpu', '--no-sandbox',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  for (let i = 0; i < 40; i++) { await sleep(400); if (await alive()) return child; }
  console.error('Chrome 启动超时'); process.exit(1);
}

const MATERIAL = 'A new study from the University of Tokyo found that city trees can cool '
  + 'nearby streets by up to five degrees Celsius.';

const PROBE = `
(async () => {
  const cap = [];
  const realFetch = window.fetch;
  window.fetch = function (u, opt) {
    let body = null;
    try { body = opt && opt.body ? JSON.parse(opt.body) : null; } catch (e) {}
    cap.push({ url: String(u), inputs: body ? body.inputs : null, mode: body ? body.response_mode : null });
    return Promise.reject(new Error('STUB_NO_NETWORK'));
  };
  const out = { steps: [], diag: {} };

  // 前提 1：本地无 config.local.js → appKey 空 → 内部 early-throw
  out.diag.appKey_before = { fact: AIWF_FACT.appKey, gen: AIWF_GEN.appKey };
  try { AIWF_FACT.appKey = 'app-PROBE-FACT'; AIWF_GEN.appKey = 'app-PROBE-GEN'; } catch (e) { out.diag.keyErr = e.message; }

  // 顺带核一下归一化函数（业务代码里不应手写档位字符串）
  try {
    out.diag.nkDisp = { A1_1: nkDisp('A1_1'), A2_2: nkDisp('A2.2'), B2P_3: nkDisp('B2P_3'),
                        empty: nkDisp(''), undef: nkDisp(undefined) };
  } catch (e) { out.diag.nkDisp = 'ERR ' + e.message; }

  // ---- FACT ----
  try {
    state.live = { status: 'idle', material: '', label: '', book: '', run: null, err: null, t0: Date.now(), elapsed: 0 };
    await startLiveRun(${JSON.stringify(MATERIAL)}, 'probe');
    out.diag.fact_live = { status: state.live.status, err: state.live.err };
  } catch (e) { out.steps.push('startLiveRun 抛: ' + e.message); }

  // ---- GEN（前提 2：自造 factsCache，含 gist）----
  try {
    state.factsCache = { summary: 'PROBE SUMMARY', facts_text: '1. PROBE FACT', angle: '',
                         level: 'A2.2', gist: '1. PROBE GIST LINE', facts_raw: '' };
    state.live = { status: 'done', material: '', label: '', book: '', run: null, err: null, t0: Date.now(), elapsed: 0 };
    await runGeneration();
  } catch (e) { out.steps.push('runGeneration 抛: ' + e.message); }

  window.fetch = realFetch;
  out.captured = cap;
  return JSON.stringify(out, null, 1);
})()
`;

async function main() {
  const chrome = await ensureChrome();
  const tab = await (await fetch(`${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pending = new Map();
  ws.addEventListener('message', e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  });
  const send = (method, params = {}) => new Promise(res => {
    const mid = ++id; pending.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.navigate', { url: URL_ });
  await sleep(4000);
  const r = await send('Runtime.evaluate', { expression: PROBE, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) {
    console.log('页面异常:', r.result.exceptionDetails.exception?.description?.slice(0, 400));
  }
  const out = r.result?.result?.value || '';
  console.log(out);
  ws.close();
  if (chrome) chrome.kill();
  let n = 0;
  try { n = (JSON.parse(out).captured || []).length; } catch { }
  process.exit(n ? 0 : 1);
}
main().catch(e => { console.error('FAIL', e); process.exit(1); });
