// ReadPal · 端到端浏览器实测（CDP，零第三方依赖）
//
// 为什么需要它：curl 只能证明代码在，证明不了运行时行为。
// 本脚本真实加载页面 → 登录 → 遍历全部页面 → 收集 JS 异常 → 截图。
//
// 用法：
//   node tools/e2e_verify.mjs
//
// 环境变量：
//   SITE         默认 https://web-production-2a16e.up.railway.app/
//   ROLE         登录角色，默认 review（全权限，可遍历全部 16 页）
//   PAGES        遍历页数，默认 16
//   SHOT         截图输出路径
//   CDP_PORT     调试端口，默认 9222
//   CHROME_BIN   指定 Chrome 可执行文件
//
// 脚本会自己拉起 headless Chrome，无需手动起进程。
//
// 验收线：页面遍历 0 条 JS 未捕获异常、0 条 console.error。
// 退出码：0 = 通过；1 = 未通过

import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const SITE = process.env.SITE || 'https://web-production-2a16e.up.railway.app/';
const ROLE = process.env.ROLE || 'review';
const PAGES = Number(process.env.PAGES || 16);
const PORT = Number(process.env.CDP_PORT || 9222);
const CDP = `http://127.0.0.1:${PORT}`;
const SHOT = process.env.SHOT || `/tmp/readpal_e2e_${Date.now()}.png`;
const PROFILE = path.join(os.tmpdir(), `readpal_cdp_${PORT}`);

const sleep = ms => new Promise(r => setTimeout(r, ms));

function findChrome() {
  const cands = [
    process.env.CHROME_BIN,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  ].filter(Boolean);
  return cands.find(p => { try { return fs.statSync(p).isFile(); } catch { return false; } });
}

async function cdpAlive() {
  try { await fetch(`${CDP}/json/version`); return true; } catch { return false; }
}

async function ensureChrome() {
  if (await cdpAlive()) { console.log(`复用已在运行的 Chrome (端口 ${PORT})`); return null; }
  const bin = findChrome();
  if (!bin) {
    console.error('✗ 找不到 Chrome。请设置 CHROME_BIN 环境变量指向可执行文件。');
    process.exit(1);
  }
  console.log(`启动 Chrome: ${bin}`);
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const child = spawn(bin, [
    '--headless=new', '--disable-gpu', '--no-sandbox',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--window-size=1400,900', 'about:blank',
  ], { stdio: 'ignore', detached: false });
  for (let i = 0; i < 30; i++) {
    await sleep(400);
    if (await cdpAlive()) return child;
  }
  console.error('✗ Chrome 启动超时');
  process.exit(1);
}

async function main() {
  const chrome = await ensureChrome();

  const tab = await (await fetch(`${CDP}/json/new?${encodeURIComponent(SITE)}`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));

  let id = 0;
  const pending = new Map();
  const errors = [];
  const consoleErrs = [];

  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails;
      errors.push(`${d.text} ${d.exception?.description || ''}`.trim().split('\n')[0]);
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErrs.push(m.params.args.map(a => a.value ?? a.description ?? '').join(' ').split('\n')[0]);
    }
  });

  const send = (method, params = {}) => new Promise(res => {
    const mid = ++id;
    pending.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });

  const evaluate = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result?.exceptionDetails) return { __err: r.result.exceptionDetails.text };
    return r.result?.result?.value;
  };

  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.navigate', { url: SITE });
  await sleep(6000);

  // ---- 1. 登录页结构 ----
  const loginInfo = await evaluate(`(() => {
    const q = s => document.querySelector(s);
    const btn = q('.lrole .rbtn'), logo = q('#loginOv .lgo');
    return {
      title: q('#loginOv .lhead h1')?.textContent?.trim(),
      cardCount: document.querySelectorAll('.lrole').length,
      btnMatchesLogoBg: (btn && logo)
        ? getComputedStyle(btn).backgroundImage === getComputedStyle(logo).backgroundImage
        : null,
    };
  })()`);
  console.log('【登录页结构】', JSON.stringify(loginInfo, null, 2));

  // ---- 2. 登录 ----
  const loginRes = await evaluate(
    `(()=>{try{ openLogin('${ROLE}'); doLogin('${ROLE}'); return 'ok'; }catch(e){ return 'ERR: '+e.message; }})()`);
  console.log(`【登录】角色 ${ROLE} → ${loginRes}`);
  await sleep(2500);

  // ---- 3. 登录后状态 ----
  const appInfo = await evaluate(`(() => {
    const q = s => document.querySelector(s);
    return {
      bridgeOk: typeof state !== 'undefined' ? state.bridgeOk : 'n/a',
      role: (typeof state !== 'undefined' && state.user) ? state.user.role : null,
      overlayHidden: q('#loginOv') ? getComputedStyle(q('#loginOv')).display === 'none' : null,
      topbarLogoBg: q('#topbar .logo') ? getComputedStyle(q('#topbar .logo')).backgroundImage.slice(0, 60) : null,
    };
  })()`);
  console.log('【登录后状态】', JSON.stringify(appInfo, null, 2));

  // ---- 4. 遍历页面 ----
  const before = errors.length;
  for (let i = 0; i < PAGES; i++) {
    await evaluate(`(()=>{try{ go(${i}); return 'ok'; }catch(e){ return 'ERR:'+e.message; }})()`);
    await sleep(420);
  }
  console.log(`【遍历 ${PAGES} 页】新增 JS 异常: ${errors.length - before} 条`);

  // ---- 5. 截图 ----
  try {
    const shot = await send('Page.captureScreenshot', {});
    fs.writeFileSync(SHOT, Buffer.from(shot.result.data, 'base64'));
    console.log(`截图: ${SHOT}`);
  } catch { /* 截图失败不影响结论 */ }

  console.log('\n===== JS 未捕获异常 =====');
  console.log(errors.length ? errors.join('\n') : '（无）');
  console.log('===== console.error =====');
  console.log(consoleErrs.length ? consoleErrs.join('\n') : '（无）');

  const pass = errors.length === 0 && consoleErrs.length === 0
    && appInfo?.bridgeOk === true;
  console.log(`\n结论: ${pass ? '通过 ✅' : '未通过 ❌'}`);

  ws.close();
  if (chrome) chrome.kill();
  process.exit(pass ? 0 : 1);
}

main().catch(e => { console.error('FAIL', e); process.exit(1); });
