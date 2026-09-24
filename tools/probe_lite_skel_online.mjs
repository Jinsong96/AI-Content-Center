// lite 骨架链路 · **线上真实 Chrome 端到端验收** —— 2026-09-24
//
// 与另外两个探针的分工：
//   · probe_lite_skeleton.mjs  —— 本地静态服务 + stub，验**前端逻辑**（交互/请求体/回炉分支）
//   · probe_lite_skel_e2e.mjs  —— 借真实 Chrome 直连 Dify，验**真模型**（骨架→对齐/逐段词数）
//   · 本脚本                  —— 打开**线上部署页**，真点按钮，走 **Railway 桥接层 → Dify**，
//                               验「用户实际拿到手的那条链路」到底通不通、对不对齐。
//   ⚠️ 沙箱直连 web-production-2a16e.up.railway.app 返回 000（被拦），必须借真实 Chrome。
//
// 判定（任一失败即退出码 1）：
//   [0] 线上已部署到本次版本（页面里有【逐段篇幅】字样）
//   [1] lite 路由底部按钮是「定骨架」；点它 → 图A 返回骨架，段数与母稿词数相符
//   [2] 骨架确认页渲染出来，逐段可编辑
//   [3] 点「确认，生成」→ 真出 A1- / A2 / B1 三档；段数 == 骨架段数
//   [4] 逐段词数落进该档区间（A1- 11–14 / A2 20–22），并报出越界段
//
// 用法：node tools/probe_lite_skel_online.mjs [--cdp=9243] [--material=/tmp/material_growing.txt]
import fs from 'node:fs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => { const h = argv.find(a => a.startsWith(`--${k}=`)); return h ? h.slice(k.length + 3) : d; };
const PORT = arg('cdp', '9243');
const CDP = `http://127.0.0.1:${PORT}`;
const SITE = arg('site', 'https://web-production-2a16e.up.railway.app/');
const MATERIAL = arg('material', '/tmp/material_growing.txt');
const OUT = arg('out', '/tmp/lite_skel_online');
const sleep = ms => new Promise(r => setTimeout(r, ms));

const text = fs.readFileSync(MATERIAL, 'utf-8').trim();
const TITLE = 'Growing Lesson';
const nwords = t => (String(t || '').match(/[A-Za-z0-9'-]+/g) || []).length;

const tab = await (await fetch(`${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id = 0; const pending = new Map();
ws.addEventListener('message', ev => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise(res => { const mid = ++id; pending.set(mid, res); ws.send(JSON.stringify({ id: mid, method, params })); });
const evaluate = async (expr, awaitPromise = true) => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise });
  if (r.result?.exceptionDetails) return { __err: r.result.exceptionDetails.exception?.description || 'error' };
  return r.result?.result?.value;
};
await send('Runtime.enable'); await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => { if (cond) { pass++; console.log(`  ✓ ${name}`); } else { fail++; console.log(`  ✗ ${name}   ${extra}`); } };

try {
  await send('Page.navigate', { url: SITE });
  await sleep(7000);

  /* ---- [0] 部署轮询（走页面同源 fetch，绕开沙箱） ---- */
  console.log('\n[0] 线上部署版本');
  let ver = null;
  for (let i = 0; i < 20; i++) {
    ver = await evaluate(`fetch('/index.html?ts='+Date.now(),{cache:'no-store'}).then(r=>r.text()).then(t=>({len:t.length, per:(t.match(/【逐段篇幅】/g)||[]).length, skel:(t.match(/liteSkel/g)||[]).length}))`);
    if (ver && !ver.__err && ver.per > 0) break;
    await sleep(15000);
  }
  ok('线上页面已含【逐段篇幅】（部署到位）', ver && !ver.__err && ver.per > 0, JSON.stringify(ver));
  ok('线上页面含骨架确认页代码', ver && !ver.__err && ver.skel > 0, JSON.stringify(ver));
  console.log(`  （线上 index.html ${ver && ver.len ? ver.len : '?'} 字符）`);

  /* ---- 打开 lite 路由、贴母稿 ---- */
  const setup = await evaluate(`(async()=>{
    const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
    const ov=document.getElementById("loginOv"); if(ov) ov.style.display="none";
    state.user={role:"produce",name:"bryan",sources:(typeof initSources==="function"?initSources("produce"):[])};
    if(typeof refreshUserChip==="function") refreshUserChip();
    pickRoute("lite"); await sleep(400);
    licState().liteText=${JSON.stringify(text)};
    licState().liteTitle=${JSON.stringify(TITLE)};
    render(); await sleep(300);
    const bar=document.getElementById("liteBar");
    const btn=bar?bar.querySelector("button"):null;
    return JSON.stringify({ label: btn?btn.textContent.trim():"(无)", route: state.route });
  })()`);
  const S = typeof setup === 'string' ? JSON.parse(setup) : { label: '(执行失败)' };
  console.log('\n[1] 定骨架（真点按钮 → Railway 桥接层 → 图A）');
  ok('已进入 lite 路由', S.route === 'lite', String(S.route));
  ok('底部按钮是「定骨架」', /定骨架/.test(S.label || ''), String(S.label));

  const t0 = Date.now();
  await evaluate(`(function(){ const b=document.getElementById("liteBar"); if(b){ const x=b.querySelector("button"); x.click(); } return 1; })()`, false);
  let prep = null;
  for (let i = 0; i < 60; i++) {
    await sleep(3000);
    const s = await evaluate(`JSON.stringify({ segs: (licState().prep&&licState().prep.segs)?licState().prep.segs.length:0, err: licState().err||null, busy: !!licState().busy, skel: !!document.querySelector("#liteSkel") })`);
    prep = typeof s === 'string' ? JSON.parse(s) : {};
    if (prep.segs || prep.err) break;
  }
  const skelMs = Date.now() - t0;
  ok('图A 真的返回了骨架（线上桥接层通）', prep && prep.segs > 0, JSON.stringify(prep));
  ok('骨架确认页渲染出来', prep && prep.skel === true, JSON.stringify(prep));
  const skelN = prep && prep.segs ? prep.segs : 0;
  console.log(`  骨架 ${skelN} 段 · 母稿 ${text.split(/\n\s*\n/).filter(Boolean).length} 段 / ${nwords(text)} 词 · ${(skelMs / 1000).toFixed(1)}s`);

  if (!skelN) { fs.writeFileSync(`${OUT}.json`, JSON.stringify({ ver, S, prep }, null, 1), 'utf-8'); throw new Error('没拿到骨架，后续无从验起'); }

  /* ---- 确认生成 ---- */
  console.log('\n[2] 确认生成（真点按钮 → 图C）');
  const t1 = Date.now();
  await evaluate(`(function(){ const b=document.querySelector("#liteSkel button.btn"); if(b) b.click(); return 1; })()`, false);
  let live = null;
  for (let i = 0; i < 100; i++) {
    await sleep(3000);
    const s = await evaluate(`JSON.stringify({
      status: state.live&&state.live.status||null, err: licState().err||null,
      licN: state.live&&state.live.licN||0, skelWarn: state.live&&state.live.skelWarn||"",
      cur: cur,
      paras: { A1:(GEN.A1&&GEN.A1.paras)?GEN.A1.paras.length:0, A2:(GEN.A2&&GEN.A2.paras)?GEN.A2.paras.length:0, B1:(GEN.B1&&GEN.B1.paras)?GEN.B1.paras.length:0 },
      per: { A1:(GEN.A1&&GEN.A1.paras)?GEN.A1.paras.map(p=>String(p).match(/[A-Za-z0-9'-]+/g)||[]).map(a=>a.length):[], A2:(GEN.A2&&GEN.A2.paras)?GEN.A2.paras.map(p=>String(p).match(/[A-Za-z0-9'-]+/g)||[]).map(a=>a.length):[] },
      quiz: state.quiz?Object.keys(state.quiz).length:0 })`);
    live = typeof s === 'string' ? JSON.parse(s) : {};
    if (live.status === 'done' || live.err) break;
  }
  const genMs = Date.now() - t1;
  ok('生成成功（status=done）', live && live.status === 'done', JSON.stringify(live && live.err ? live.err : live && live.status));
  const P = (live && live.paras) || {};
  ok('A1- 段数 == 骨架段数', P.A1 === skelN, `A1-=${P.A1} 骨架=${skelN}`);
  ok('A2 段数 == 骨架段数', P.A2 === skelN, `A2=${P.A2} 骨架=${skelN}`);
  ok('B1 段数 == 骨架段数', P.B1 === skelN, `B1=${P.B1} 骨架=${skelN}`);
  ok('没有段数报警（一轮过）', !live || !live.skelWarn, String(live && live.skelWarn));
  const inA1 = ((live && live.per && live.per.A1) || []).filter(n => n >= 11 && n <= 14).length;
  const inA2 = ((live && live.per && live.per.A2) || []).filter(n => n >= 20 && n <= 22).length;
  ok(`A1- 逐段词数落带 11–14（${inA1}/${skelN}）`, skelN > 0 && inA1 / skelN >= 0.8, JSON.stringify(live && live.per && live.per.A1));
  ok(`A2 逐段词数落带 20–22（${inA2}/${skelN}）`, skelN > 0 && inA2 / skelN >= 0.8, JSON.stringify(live && live.per && live.per.A2));
  console.log(`  A1- 逐段 [${((live && live.per && live.per.A1) || []).join(',')}]`);
  console.log(`  A2  逐段 [${((live && live.per && live.per.A2) || []).join(',')}]`);
  console.log(`  耗时：定骨架 ${(skelMs / 1000).toFixed(1)}s + 生成 ${(genMs / 1000).toFixed(1)}s · 题目档数 ${live && live.quiz} · 落页 idx=${live && live.cur}`);

  fs.writeFileSync(`${OUT}.json`, JSON.stringify({ ver, site: SITE, master: { paras: text.split(/\n\s*\n/).filter(Boolean).length, words: nwords(text) }, setup: S, prep, skelMs, live, genMs }, null, 1), 'utf-8');
  console.log(`\n[产物] ${OUT}.json`);
  console.log(`\n${fail === 0 ? '✅' : '✗'} ${pass}/${pass + fail} 通过`);
} catch (e) {
  console.log(`\n执行中断：${e.message}`);
  fail++;
} finally {
  ws.close();
  process.exit(fail === 0 ? 0 : 1);
}
