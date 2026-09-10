// ReadPal 全站配色审计（CDP，零依赖）
// 遍历全部页面 → 取每个元素的 computed 颜色 → 转 HSL → 揪出非「黑/灰/橙红」色相
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const SITE = process.env.SITE || 'http://127.0.0.1:8899/index.html';
const ROLE = process.env.ROLE || 'review';
const PAGES = Number(process.env.PAGES || 12);
const PORT = Number(process.env.CDP_PORT || 9222);
const CDP = `http://127.0.0.1:${PORT}`;
const PROFILE = path.join(os.tmpdir(), `readpal_audit_${PORT}`);
const sleep = ms => new Promise(r => setTimeout(r, ms));

const CHROME = [
  process.env.CHROME_BIN,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/google-chrome', '/usr/bin/chromium',
].filter(Boolean).find(p => { try { return fs.statSync(p).isFile(); } catch { return false; } });

async function main() {
  let child = null;
  try { await fetch(`${CDP}/json/version`); } catch {
    if (!CHROME) { console.error('找不到 Chrome'); process.exit(1); }
    fs.rmSync(PROFILE, { recursive: true, force: true });
    child = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-sandbox',
      `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
      '--window-size=1400,1000', 'about:blank'], { stdio: 'ignore' });
    for (let i = 0; i < 30; i++) { await sleep(400); try { await fetch(`${CDP}/json/version`); break; } catch {} }
  }

  const tab = await (await fetch(`${CDP}/json/new?${encodeURIComponent('about:blank')}`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));

  let id = 0; const pending = new Map();
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
    if (r.result?.exceptionDetails) return { __err: r.result.exceptionDetails.text };
    return r.result?.result?.value;
  };

  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.navigate', { url: SITE });
  await sleep(6000);
  await evaluate(`(()=>{try{ openLogin('${ROLE}'); doLogin('${ROLE}'); return 'ok'; }catch(e){ return 'ERR'; }})()`);
  await sleep(2500);

  const AUDIT = `(() => {
    const parse = c => { const m = c && c.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/);
      return m ? { r:+m[1], g:+m[2], b:+m[3], a: m[4]===undefined?1:+m[4] } : null; };
    const hsl = ({r,g,b}) => { r/=255; g/=255; b/=255;
      const mx=Math.max(r,g,b), mn=Math.min(r,g,b), d=mx-mn;
      let h=0;
      if (d) { if (mx===r) h=60*(((g-b)/d)%6); else if (mx===g) h=60*((b-r)/d+2); else h=60*((r-g)/d+4); }
      if (h<0) h+=360;
      const l=(mx+mn)/2, s = d===0?0:d/(1-Math.abs(2*l-1));
      return { h, s:s*100, l:l*100 };
    };
    const bad = {};
    const props = ['color','backgroundColor','borderTopColor','borderBottomColor','borderLeftColor','borderRightColor','outlineColor','fill','stroke'];
    document.querySelectorAll('*').forEach(el => {
      const t = el.tagName;
      if (t === 'SCRIPT' || t === 'STYLE' || t === 'HEAD' || t === 'META' || t === 'TITLE') return;
      const cs = getComputedStyle(el);
      props.forEach(p => {
        let v; try { v = cs[p]; } catch { return; }
        const c = parse(v); if (!c || c.a < 0.05) return;
        const { h, s, l } = hsl(c);
        if (s < 26) return;               // 灰阶（含带冷偏的中性灰）
        if (l > 90 || l < 12) return;     // 近白 / 近黑
        const ok = (h >= 0 && h <= 48) || h >= 345;   // 仅允许橙红→橙 与 红
        if (!ok) {
          const k = v;
          if (!bad[k]) bad[k] = { n:0, h:Math.round(h), s:Math.round(s), l:Math.round(l), ex:[] };
          bad[k].n++;
          if (bad[k].ex.length < 4) bad[k].ex.push(t + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/)[0] : '') + ' [' + p + ']');
        }
      });
    });
    return bad;
  })()`;

  const all = {};
  for (let i = 0; i < PAGES; i++) {
    await evaluate(`(()=>{try{ go(${i}); return 'ok'; }catch(e){ return 'ERR'; }})()`);
    await sleep(500);
    const r = await evaluate(AUDIT);
    for (const [k, v] of Object.entries(r || {})) {
      if (!all[k]) all[k] = { n: 0, h: v.h, s: v.s, l: v.l, pages: [], ex: v.ex };
      all[k].n += v.n;
      if (!all[k].pages.includes(i)) all[k].pages.push(i);
    }
    const n = Object.keys(r || {}).length;
    process.stdout.write(`  页 ${String(i).padStart(2)} → ${n ? '⚠ ' + n + ' 种违规色' : '✓'}\n`);
  }

  console.log('\n===== 配色审计结果 =====');
  const keys = Object.keys(all);
  if (!keys.length) {
    console.log('✅ 全部 ' + PAGES + ' 页均无蓝/绿/紫色相，色相全部落在 黑/灰/橙红 区间');
  } else {
    console.log('发现 ' + keys.length + ' 种非橙红色相：');
    for (const k of keys.sort((a, b) => all[b].n - all[a].n)) {
      const v = all[k];
      console.log(`  ${k}  出现 ${v.n} 次  hue=${v.h}° sat=${v.s}% 页面[${v.pages.join(',')}]`);
      v.ex.forEach(e => console.log(`      · ${e}`));
    }
  }
  ws.close();
  if (child) child.kill();
  process.exit(keys.length ? 1 : 0);
}
main().catch(e => { console.error('FAIL', e); process.exit(1); });
