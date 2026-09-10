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
//   ROLE         登录角色，默认 review（全权限，可遍历全部 12 页）
//   PAGES        遍历页数，默认 12
//   REQUIRE_BRIDGE 设 0 则跳过 bridgeOk 校验（本地静态服务没桥接层时用）
//   SHOT         截图输出路径
//   CDP_PORT     调试端口，默认 9222
//   CHROME_BIN   指定 Chrome 可执行文件
//
// 脚本会自己拉起 headless Chrome，无需手动起进程。
//
// 验收线：页面遍历 0 条 JS 未捕获异常、0 条 console.error（线上另要求 bridgeOk=true）。
// 退出码：0 = 通过；1 = 未通过

import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const SITE = process.env.SITE || 'https://web-production-2a16e.up.railway.app/';
const ROLE = process.env.ROLE || 'review';
const PAGES = Number(process.env.PAGES || 12);
const REQUIRE_BRIDGE = process.env.REQUIRE_BRIDGE !== '0';
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

  // ---- 4b. 统一返回按钮断言（显示规则 + 落点 + 路线跳步感知）----
  const bbRes = await evaluate(`(() => {
    const btn = () => document.querySelector('.backbar .backbtn');
    const out = [];
    const T = (n, v) => out.push({ t: n, ok: !!v });
    const click = () => { const b = btn(); if (b) b.click(); };

    state.route = null; go(0);
    T('素材创建首页 · 无返回按钮', btn() === null);

    state.route = 'owned'; go(0);
    out.push({ t: '素材创建已选入口 · 按钮文案', ok: true, v: btn() ? btn().textContent.trim() : '' });
    click();
    T('已选入口 · 返回后清空入口回到卡片', state.route === null && cur === 0);

    state.route = 'trend'; go(1); click();
    T('热点搜集 · 返回 → 01', cur === 0);

    state.route = 'owned'; go(2); click();
    T('敏感排除(owned) · 返回 → 01（跳过热点）', cur === 0);

    state.route = 'trend'; go(2); click();
    T('敏感排除(trend) · 返回 → 热点搜集', cur === 1);

    state.route = 'trend'; go(3); click();
    T('选题标签 · 返回 → 敏感排除', cur === 2);

    go(4); T('素材库 · 无返回按钮（侧边栏顶层）', btn() === null);
    go(5); T('文章生产首页 · 无返回按钮（侧边栏顶层）', btn() === null);

    state.route = 'trend'; go(6); click();
    T('分级标准(trend) · 返回 → 事实抽取', cur === 5);

    state.route = 'owned'; go(6);
    T('分级标准(owned) · 无返回（本路线首步）', btn() === null);

    state.route = 'trend'; go(10); click();
    T('逐段审核 · 返回 → 段落校对', cur === 9);

    go(11); T('文章库 · 无返回按钮（侧边栏顶层）', btn() === null);

    state.route = 'owned'; go(2); railGo(0);
    T('侧边栏「素材创建」· 回模块首页并清空入口', state.route === null && cur === 0);

    /* 只读态：review 角色可操作全部 0–11，不会进只读；临时切成 source（只可操作 0–4）再进 06 */
    const savedRole = state.user.role;
    state.user.role = 'source';
    state.route = 'trend'; go(6);
    const w = document.querySelector('.wrap'), b2 = btn();
    T('只读态下返回按钮仍可点', !!w && w.classList.contains('ro')
      && !!b2 && getComputedStyle(b2).pointerEvents === 'auto');
    state.user.role = savedRole;
    T('已删「重选素材」按钮', !document.body.innerHTML.includes('Re-pick route'));

    go(0);
    return out;
  })()`);
  console.log('【统一返回按钮】');
  let bbFail = 0;
  (bbRes || []).forEach(r => {
    if (!r.ok) bbFail++;
    console.log(`  ${r.ok ? '✓' : '✗'} ${r.t}${r.v ? ' → ' + r.v : ''}`);
  });
  if (!bbRes) { bbFail = 1; console.log('  ✗ 断言块未返回结果'); }

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

  const pass = errors.length === 0 && consoleErrs.length === 0 && bbFail === 0
    && (!REQUIRE_BRIDGE || appInfo?.bridgeOk === true);
  console.log(`\n结论: ${pass ? '通过 ✅' : '未通过 ❌'}`
    + (REQUIRE_BRIDGE ? '' : '（已跳过 bridgeOk 校验：REQUIRE_BRIDGE=0）'));

  ws.close();
  if (chrome) chrome.kill();
  process.exit(pass ? 0 : 1);
}

main().catch(e => { console.error('FAIL', e); process.exit(1); });
