// 段落编辑一致性回归探针 —— 2026-09-20
//
// 为什么需要它：`paraEdit(el)` 收到的是 `.pbody`，而 `data-k` / `data-i` 挂在父级 `.pcard` 上。
// 只要有人在回调里直接 `el.getAttribute("data-k")`，就会拿到 null → `GEN[null]` undefined
// → 函数第二行静默 return。**致命的是它一个字都不报错**：
// contenteditable 是浏览器原生行为，文字看上去确实改了，
// 但「内存 GEN / 本机草稿 / 存入文章库 / 审核环节」四处全是原文 —— 老师以为改好了，实际白改。
//
// 静态读代码看不出来（读起来完全通顺），必须用真实 DOM 走一遍「改 → 存 → 审」。
//
// 断言（任一失败即退出码 1）：
//   ① `.pbody` 确实可编辑，且 `.pcard` 才是属性宿主（`data-k` 在卡片上、不在正文上）
//   ② 编辑后：目标段变、同档邻段不变、其它档不变
//   ③ 700ms 防抖后草稿落盘且内容与编辑一致
//   ④ 段落词数徽标同步刷新
//   ⑤ 逐段审核页（idx 10）显示的是**编辑后**文本，且不含原文、且只读
//   ⑥ 切走再切回，校对页 DOM 仍是编辑后的
//   ⑦ 入库版本 buildBankArticle() 的 paras / articles 都含编辑、不含原文
//
// 用法：
//   cd <repo> && node tools/probe_para_edit.mjs                      # 本地 8899
//   URL_=https://web-production-2a16e.up.railway.app/ CDP_PORT=9265 node tools/probe_para_edit.mjs
// 前置：本地需先起静态服务（frontend/ 下 `python3 -m http.server 8899 --bind 127.0.0.1`，
//       必须 run_in_background，否则进程随 shell 退出被杀）
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const PORT = Number(process.env.CDP_PORT || 9265);
const CDP = `http://127.0.0.1:${PORT}`;
const PROFILE = path.join(os.tmpdir(), `readpal_pe_${PORT}`);
const URL_ = process.env.URL_ || 'http://127.0.0.1:8899/index.html';
const OUT = process.env.OUT || '/tmp/para_edit_probe';
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

const EDIT_VAL = 'EDITED-BY-PROBE';
const SETUP = `(async()=>{
  const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
  const out={};
  const L = (zh,_en)=>zh;
  document.getElementById("loginOv").style.display="none";
  state.user={role:"produce",name:"curriculum_li",sources:(typeof initSources==="function"?initSources("produce"):[])};
  if(typeof refreshUserChip==="function") refreshUserChip();
  if(typeof buildRail==="function") buildRail();
  state.live = state.live || {};
  state.live.status = "done";
  state.live.material = "PROBE MATERIAL ".repeat(20);
  state.live.label = "probe";
  state.tagContent = ["world"];
  localStorage.removeItem("wb_para_draft_v1");

  GEN = {};
  LEVELS12.forEach(function(l){
    GEN[l.key] = { title:"ProbeTitle", paras:[
      ["ORIGINAL-"+l.key+"-p1"], ["ORIGINAL-"+l.key+"-p2"], ["ORIGINAL-"+l.key+"-p3"]] };
  });

  go(9);
  await sleep(800);
  out.cur = cur;

  /* ① 属性宿主：卡片上是 "A1"，正文上必须是 null（旧 bug 的直接成因） */
  const card = document.querySelector('.pcard[data-k="A1"][data-i="0"]');
  out.hasCard = !!card;
  out.cardDataK = card ? card.getAttribute("data-k") : null;
  const body = card ? card.querySelector('.pbody[contenteditable="true"]') : null;
  out.bodyEditable = !!body;
  out.bodyDataK = body ? body.getAttribute("data-k") : "(no body)";

  if(body){
    body.focus();
    body.innerText = ${JSON.stringify(EDIT_VAL)};
    body.dispatchEvent(new Event("input", {bubbles:true}));
  }
  await sleep(300);
  out.genTarget   = JSON.stringify(GEN.A1.paras[0]);
  out.genNeighbor = JSON.stringify(GEN.A1.paras[1]);
  out.genOtherLvl = JSON.stringify(GEN.B1.paras[0]);
  const c = document.querySelector('.pcard[data-k="A1"][data-i="0"] .pword');
  out.wordBadge = c ? c.textContent : "(none)";

  await sleep(1100);   /* 等 700ms 防抖落盘 */
  let dr=null; try{ dr=JSON.parse(localStorage.getItem("wb_para_draft_v1")||"null"); }catch(e){}
  out.draftSaved = !!dr;
  out.draftTarget = (dr && dr.gen && dr.gen.A1) ? JSON.stringify(dr.gen.A1.paras[0]) : "(none)";
  out.draftStatShown = !!(document.getElementById("draftStat")||{}).textContent;

  /* ⑤ 逐段审核页 */
  go(10);
  await sleep(800);
  const rp = document.querySelector(".reviewparas");
  out.reviewText = rp ? rp.textContent.replace(/\\s+/g," ").trim().slice(0,120) : "(no .reviewparas)";
  out.reviewShowsEdited = rp ? rp.textContent.indexOf(${JSON.stringify(EDIT_VAL)})>=0 : null;
  out.reviewShowsOriginal = rp ? rp.textContent.indexOf("ORIGINAL-A1-p1")>=0 : null;
  out.reviewEditableCount = document.querySelectorAll('.reviewparas .pbody[contenteditable="true"]').length;

  /* ⑥ 切回校对页 */
  go(9);
  await sleep(800);
  const b2 = document.querySelector('.pcard[data-k="A1"][data-i="0"] .pbody');
  out.backText = b2 ? b2.innerText.trim() : "(none)";

  /* ⑦ 入库版本 */
  const art = buildBankArticle();
  out.bankParasA1 = JSON.stringify(art.paras.A1);
  out.bankHasEdit = String(art.articles.A1||"").indexOf(${JSON.stringify(EDIT_VAL)})>=0;
  out.bankHasOriginal = String(art.articles.A1||"").indexOf("ORIGINAL-A1-p1")>=0;
  return JSON.stringify(out);
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

  const raw = await evaluate(SETUP);
  if (typeof raw !== 'string' || raw.startsWith('ERR')) { console.error('探针执行失败:', raw); ws.close(); if (chrome) chrome.kill(); process.exit(1); }
  const o = JSON.parse(raw);

  const checks = [
    ['① 属性宿主：data-k 在卡片上', o.cardDataK === 'A1', `card=${o.cardDataK}`],
    ['① 属性宿主：正文上没有 data-k（这就是旧 bug 的成因）', o.bodyDataK === null, `pbody=${o.bodyDataK}`],
    ['① 正文可编辑', o.bodyEditable === true, String(o.bodyEditable)],
    ['② 编辑写入目标段', o.genTarget === JSON.stringify([EDIT_VAL]), o.genTarget],
    ['② 同档邻段未被误改', o.genNeighbor === JSON.stringify(['ORIGINAL-A1-p2']), o.genNeighbor],
    ['② 其它档未被误改', o.genOtherLvl === JSON.stringify(['ORIGINAL-B1-p1']), o.genOtherLvl],
    ['③ 草稿落盘且内容一致', o.draftSaved === true && o.draftTarget === JSON.stringify([EDIT_VAL]), `saved=${o.draftSaved} val=${o.draftTarget}`],
    ['③ 界面有「已自动保存」反馈', o.draftStatShown === true, String(o.draftStatShown)],
    ['④ 段落词数徽标已刷新', /^\d+/.test(String(o.wordBadge)), o.wordBadge],
    ['⑤ 审核页显示编辑后文本', o.reviewShowsEdited === true, String(o.reviewShowsEdited)],
    ['⑤ 审核页不含原文', o.reviewShowsOriginal === false, String(o.reviewShowsOriginal)],
    ['⑤ 审核页保持只读', o.reviewEditableCount === 0, String(o.reviewEditableCount)],
    ['⑥ 切回校对页仍是编辑后', o.backText === EDIT_VAL, o.backText],
    ['⑦ 入库 paras 含编辑', o.bankParasA1.indexOf(EDIT_VAL) >= 0, o.bankParasA1],
    ['⑦ 入库 articles 含编辑', o.bankHasEdit === true, String(o.bankHasEdit)],
    ['⑦ 入库 articles 不含原文', o.bankHasOriginal === false, String(o.bankHasOriginal)],
  ];

  let fail = 0;
  console.log(`\n===== 段落编辑一致性回归（${URL_}）=====\n`);
  for (const [name, ok, detail] of checks) {
    if (!ok) fail++;
    console.log(`${ok ? '  ✓' : '  ✗'} ${name}${ok ? '' : '   ← ' + detail}`);
  }
  console.log(`\n${fail ? `❌ ${fail} 项未通过` : '✅ 全部通过（16 项）'}`);
  if (errs.length) { console.log('运行时异常:', errs.join('\n')); fail++; }

  try {
    const shot = await send('Page.captureScreenshot', { captureBeyondViewport: false });
    fs.writeFileSync(`${OUT}.png`, Buffer.from(shot.result.data, 'base64'));
    console.log('截图:', `${OUT}.png`);
  } catch (e) {}

  ws.close(); if (chrome) chrome.kill();
  process.exit(fail ? 1 : 0);
}
main().catch(e => { console.error('FAIL', e); process.exit(1); });
