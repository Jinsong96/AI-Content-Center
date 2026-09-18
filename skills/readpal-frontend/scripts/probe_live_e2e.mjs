// ReadPal · 线上端到端探针（真实登录 → FACT → GEN，等同用户点两次按钮）
//
// 为什么需要它：curl / 静态检查只能证明「代码在线上」，证明不了「线上真的能跑」。
// 这是「bug 已修」的最强证据 —— 修复前 FACT 传下划线键会 2.1s / 0 token 被门口打回。
//
// 用法：
//   node scripts/probe_live_e2e.mjs [--url=https://web-production-2a16e.up.railway.app/]
//                                   [--port=9233] [--fact-only]
//
// ⚠️ 这里用**穿透式记录器**（记录请求体 + 照常发真实请求），不要用「轮询结束后读
//    state.live.run」的写法 —— runGeneration 结束时会把 state.live.run 换成 **GEN 的响应**，
//    那时再去读就会把 GEN 的 outputs 当成 FACT 的，得出 level_lo/info_points 缺失、
//    gist_len=0 的**假结论**（踩过）。
//
// 耗时：FACT ~20–30s；GEN ~110–180s。退出码：0 全部 done；1 有一步未 done

import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const argv = process.argv.slice(2);
const arg = (k, d = null) => {
  const hit = argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const has = k => argv.includes(`--${k}`);

const URL_ = arg('url', 'https://web-production-2a16e.up.railway.app/');
const PORT = Number(arg('port', process.env.CDP_PORT || 9233));
const FACT_ONLY = has('fact-only');
const CDP = `http://127.0.0.1:${PORT}`;
const PROFILE = path.join(os.tmpdir(), `readpal_live_e2e_${PORT}`);
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
  const child = spawn(bin, ['--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run',
    '--disable-component-update', '--disable-background-networking',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  for (let i = 0; i < 40; i++) { await sleep(400); if (await alive()) return child; }
  console.error('Chrome 启动超时'); process.exit(1);
}

const MATERIAL = 'A new study from the University of Tokyo found that city trees can cool nearby '
  + 'streets by up to five degrees Celsius. Researchers measured air temperature around 200 trees '
  + 'in three districts over one summer. The cooling effect was strongest in narrow streets with '
  + 'little wind. The team says planting more trees could help cities adapt to hotter summers.';

const INSTALL_RECORDER = `
(() => {
  if (window.__rec) return 'already';
  window.__rec = [];
  const of = window.fetch;
  window.fetch = function (u, opt) {
    try {
      const b = opt && opt.body ? JSON.parse(opt.body) : null;
      if (b && b.inputs) window.__rec.push({ ts: Date.now(), mode: b.response_mode, inputs: b.inputs });
    } catch (e) {}
    return of.apply(this, arguments);   // 穿透：照常发真实请求
  };
  return 'installed';
})()
`;

const LOGIN_FACT = `
(async () => {
  const info = {};
  try {
    const r = ROLES.find(x => x.id === 'review');
    document.querySelector('#lu-review').value = r.user;
    document.querySelector('#lp-review').value = r.pass;
    doLogin('review');
    info.loggedIn = !!state.user;
    startLiveRun(${JSON.stringify(MATERIAL)}, 'live-probe');
  } catch (e) { info.err = e.message; }
  return JSON.stringify(info);
})()
`;

const POLL = `
(() => JSON.stringify({ status: state.live && state.live.status, elapsed: state.live && state.live.elapsed,
                        err: state.live && state.live.err }))()
`;

// ⚠️ 只能在 FACT 刚结束、GEN 还没开始时调用
const AFTER_FACT = `
(() => {
  const o = state.live.run.data.outputs;
  return JSON.stringify({ outputs_keys: Object.keys(o).sort(), level: o.level,
    level_lo: o.level_lo, level_hi: o.level_hi, info_points: o.info_points,
    gist_len: (o.gist || '').length,
    factsCache: { has: !!state.factsCache, gist_len: ((state.factsCache||{}).gist||'').length,
                  level: (state.factsCache||{}).level } });
})()
`;

const FINAL = `
(() => {
  const o = state.live.run.data.outputs;
  const jp = v => { try { return JSON.parse(v); } catch (e) { return null; } };
  const arts = jp(o.articles_json) || {}, quiz = jp(o.quiz_json) || {};
  const vj = jp(o.validation_json) || {}, gc = jp(o.gist_check_json) || {};
  let nq = 0; Object.values(quiz.levels || {}).forEach(v => { if (Array.isArray(v)) nq += v.length; });
  let nFail = 0;
  (vj.results || []).forEach(r => (r.checks || []).forEach(c => { if (c.status === 'fail') nFail++; }));
  const reqs = (window.__rec || []).map(r => ({ mode: r.mode, keys: Object.keys(r.inputs).sort(),
    level: r.inputs.level, gist_len: ((r.inputs.gist) || '').length }));
  return JSON.stringify({
    requested: reqs,
    gen_out: { articles: Object.keys(arts).length, quizzes: nq,
               checks_pass: vj.total_pass, checks_total: vj.total_checks, hard_fail: nFail,
               gist_check_pass: gc.pass, gist_check_fail: gc.fail_levels || [] }
  }, null, 1);
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
  const ev = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result?.exceptionDetails) {
      return 'EXC: ' + (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text);
    }
    return r.result?.result?.value;
  };

  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.navigate', { url: URL_ });
  await sleep(6000);

  const spin = async (label, maxSec) => {
    console.log(`== ${label}`);
    for (let s = 4; s <= maxSec; s += 4) {
      await sleep(4000);
      const raw = await ev(POLL);
      let j; try { j = JSON.parse(raw); } catch { j = { status: raw }; }
      console.log(`   [${s}s] ${j.status}  ${(j.err || '').slice(0, 90)}`);
      if (j.status && j.status !== 'running') return j.status;
    }
    return 'timeout';
  };

  console.log('安装穿透式记录器:', await ev(INSTALL_RECORDER));
  console.log('== 登录 + 发起 FACT ==');
  console.log(await ev(LOGIN_FACT));
  const s1 = await spin('FACT 事实抽取', 120);
  if (s1 !== 'done') { console.log('FACT 未成功，终止'); ws.close(); if (chrome) chrome.kill(); process.exit(1); }
  console.log('\n== FACT 结束时的真实状态（此刻 state.live.run 仍是 FACT 响应）==');
  console.log(await ev(AFTER_FACT));

  if (FACT_ONLY) { ws.close(); if (chrome) chrome.kill(); process.exit(0); }

  console.log('\n== 接续 GEN 生成 12 子档（约 110–180s）==');
  console.log(await ev('(async()=>{ try { await runGeneration(); return "gen-returned"; } catch(e){ return "gen-threw: "+e.message; } })()'));
  const s2 = await spin('GEN 内容生成', 320);

  console.log('\n===== 最终结果 =====');
  console.log(s2 === 'done' ? await ev(FINAL) : 'GEN status=' + s2);
  ws.close();
  if (chrome) chrome.kill();
  process.exit(s2 === 'done' ? 0 : 1);
}
main().catch(e => { console.error('FAIL', e); process.exit(1); });
