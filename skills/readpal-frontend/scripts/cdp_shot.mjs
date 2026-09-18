// ReadPal · CDP 精确视口截图（零第三方依赖）
//
// 为什么需要它：`chrome --window-size` 受 Chrome 最小窗口尺寸限制（约 500×200），
// 想做 420px 的移动端验证时会拿到错误视口 —— 布局按 ~500px 排，截图却按 420 裁，
// 看起来像「内容溢出」。只有 CDP 的 Emulation.setDeviceMetricsOverride 能精确控制。
//
// 用法：
//   node tools/cdp_shot.mjs --url=http://127.0.0.1:8899/index.html \
//        --out=/tmp/shot --sizes=1440x900,1024x768,420x820 \
//        [--eval="openLogin('review');doLogin('review')"] [--wait=6000] [--full]
//
// 参数：
//   --url    页面地址（必填）
//   --out    输出前缀，实际文件为 <out>_<W>x<H>.png；也接受 .png 结尾（自动插尺寸）
//   --sizes  逗号分隔的 WxH 列表，默认 1440x900
//   --eval   页面加载后、截图前执行的 JS（用于登录 / 切页等）
//   --wait   导航后等待毫秒，默认 6000
//   --full   截整页（高于视口时也完整）
//   --dsf    设备像素比，默认 1（设 2 得高清图，文件更大）
//   CDP_PORT / CHROME_BIN 同 e2e_verify.mjs
//
// 退出码：0 全部成功；1 有失败

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

const URL_ = arg('url');
const OUT = arg('out', `/tmp/cdp_shot_${Date.now()}`);
const SIZES = arg('sizes', '1440x900').split(',').map(s => s.trim()).filter(Boolean);
const EVAL = arg('eval', '');
const WAIT = Number(arg('wait', 6000));
const FULL = has('full');
const DSF = Number(arg('dsf', 1));
const PORT = Number(arg('port', process.env.CDP_PORT || 9222));
const CDP = `http://127.0.0.1:${PORT}`;
const PROFILE = path.join(os.tmpdir(), `readpal_cdp_${PORT}`);

if (!URL_) { console.error('缺 --url'); process.exit(1); }

const sleep = ms => new Promise(r => setTimeout(r, ms));

function findChrome() {
  const cands = [
    process.env.CHROME_BIN,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium', '/usr/bin/chromium-browser',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  ].filter(Boolean);
  return cands.find(p => { try { return fs.statSync(p).isFile(); } catch { return false; } });
}
const cdpAlive = async () => { try { await fetch(`${CDP}/json/version`); return true; } catch { return false; } };

async function ensureChrome() {
  if (await cdpAlive()) { console.log(`复用已在运行的 Chrome (端口 ${PORT})`); return null; }
  const bin = findChrome();
  if (!bin) { console.error('✗ 找不到 Chrome，请设 CHROME_BIN'); process.exit(1); }
  fs.rmSync(PROFILE, { recursive: true, force: true });
  const child = spawn(bin, [
    '--headless=new', '--disable-gpu', '--no-sandbox',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
    '--hide-scrollbars', 'about:blank',
  ], { stdio: 'ignore', detached: false });
  for (let i = 0; i < 40; i++) { await sleep(400); if (await cdpAlive()) return child; }
  console.error('✗ Chrome 启动超时'); process.exit(1);
}

const outPath = (w, h) =>
  OUT.endsWith('.png') ? OUT.replace(/\.png$/, `_${w}x${h}.png`) : `${OUT}_${w}x${h}.png`;

async function main() {
  const chrome = await ensureChrome();
  const tab = await (await fetch(`${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));

  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  });
  const send = (method, params = {}) => new Promise(res => {
    const mid = ++id; pending.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  const evaluate = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    return r.result?.result?.value;
  };

  await send('Runtime.enable');
  await send('Page.enable');

  let fail = 0;
  for (const size of SIZES) {
    const [w, h] = size.split('x').map(Number);
    if (!w || !h) { console.error(`跳过非法尺寸: ${size}`); fail++; continue; }

    await send('Emulation.setDeviceMetricsOverride', {
      width: w, height: h, deviceScaleFactor: DSF, mobile: w < 600,
    });
    await send('Page.navigate', { url: URL_ });
    await sleep(WAIT);
    if (EVAL) { const r = await evaluate(EVAL); console.log(`[${size}] eval → ${r}`); await sleep(1200); }

    const shot = await send('Page.captureScreenshot', { captureBeyondViewport: FULL });
    if (!shot.result?.data) { console.error(`[${size}] 截图失败`); fail++; continue; }
    const file = outPath(w, h);
    fs.writeFileSync(file, Buffer.from(shot.result.data, 'base64'));

    // 顺带量一下关键尺寸，便于判断溢出/居中
    const metrics = await evaluate(`(()=>{
      const de=document.documentElement, lw=document.querySelector('#loginOv .lwrap');
      const r=lw?lw.getBoundingClientRect():null;
      return {vw:window.innerWidth, scrollW:de.scrollWidth, bodyScrollW:document.body.scrollWidth,
              lwrap:r?{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)}:null};
    })()`);
    console.log(`[${size}] ${file}  ${fs.statSync(file).size}B  ` +
      `vw=${metrics?.vw} scrollW=${metrics?.scrollW} lwrap=${JSON.stringify(metrics?.lwrap)}`);
  }

  ws.close();
  if (chrome) chrome.kill();
  process.exit(fail ? 1 : 0);
}
main().catch(e => { console.error('FAIL', e); process.exit(1); });
