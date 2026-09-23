// ReadPal · 授权链路（第四入口）回归
//
// 覆盖 2026-09-22 二次改口径：**导入母稿时每段词数是分段的唯一依据，全文字数不参与决策**；
// 合格带 = 该档每段规格 ±5 词（B1 23–40 / B2+ 36–55）；段数 10–15 内不提示；
// 「参考段数」输入框已撤，改成只读「预计段数」。
//
// 🔴 第 1b 组跑的是**真实 DOM 事件**（dispatchEvent change，全程不手动 render）——
//    「改档位后界面不刷新 → 进不了下一步」那个阻塞 bug 就是因为旧用例每次都在
//    licSet 之后补一句 render()，把问题盖住了。新增断言时别再加那个 render()。
//
// 用法：
//   cd frontend && python3 -m http.server 8899      # 另开一个终端
//   node tools/probe_lic_flow.mjs --url=http://127.0.0.1:8899/index.html --port=9242
//
// 退出码 0 = 全过且无 JS 异常。
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const argv = process.argv.slice(2);
const arg = (k, d = null) => { const h = argv.find(a => a.startsWith(`--${k}=`)); return h ? h.slice(k.length + 3) : d; };
const URL_ = arg('url', 'http://127.0.0.1:8899/index.html');
const PORT = Number(arg('port', process.env.CDP_PORT || 9242));
const CDP = `http://127.0.0.1:${PORT}`;
const PROFILE = path.join(os.tmpdir(), `readpal_licprobe_${PORT}`);
const SHOT = arg('out', '/tmp/licshot3');
const sleep = ms => new Promise(r => setTimeout(r, ms));

function findChrome() {
  const c = [process.env.CHROME_BIN, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium', '/usr/bin/google-chrome',
    '/usr/bin/chromium'].filter(Boolean);
  return c.find(p => { try { return fs.statSync(p).isFile(); } catch { return false; } });
}
const alive = async () => { try { await fetch(`${CDP}/json/version`); return true; } catch { return false; } };
async function ensureChrome() {
  if (await alive()) return null;
  const bin = findChrome();
  if (!bin) { console.error('✗ 找不到 Chrome'); process.exit(1); }
  fs.rmSync(PROFILE, { recursive: true, force: true });
  spawn(bin, ['--headless=new', '--disable-gpu', '--no-sandbox', `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE}`, '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  for (let i = 0; i < 40; i++) { await sleep(400); if (await alive()) return true; }
  console.error('✗ Chrome 启动超时'); process.exit(1);
}

const R = [];
const errs = [];
const ok = (label, cond, detail) => R.push({ ok: !!cond, label, detail: detail == null ? '' : String(detail) });

/* 51 词的样例正文（前端 licWordCount 按空白切词） */
const ART = 'Virtual reality is spreading through history classrooms faster than most schools expected. ' +
  'A study of more than two thousand students found measurable comprehension gains. ' +
  'Teachers welcome the engagement, but cost and training remain unsolved. ' +
  'Rural districts face the steepest climb of all. ' +
  'Some have started sharing headsets on a rotating schedule.';
const ART_WC = 51;

async function main() {
  await ensureChrome();
  const tab = await (await fetch(`${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pend = new Map();
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); return; }
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params?.exceptionDetails || {};
      errs.push('exception: ' + (d.exception?.description || d.text || '').slice(0, 300));
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params?.type === 'error') {
      errs.push('console.error: ' + (m.params.args || []).map(a => a.value ?? a.description ?? '').join(' ').slice(0, 300));
    }
  });
  const send = (method, params = {}) => new Promise(res => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true, userGesture: true });
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || JSON.stringify(r.result.exceptionDetails).slice(0, 300));
    return r.result?.result?.value;
  };
  await send('Runtime.enable'); await send('Page.enable');
  await send('Network.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });
  const view = (w, h) => send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  const shot = async (w, h, name) => {
    await view(w, h);
    const r = await send('Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(`${SHOT}_${name}.png`, Buffer.from(r.result.data, 'base64'));
  };
  const nav = async (w, h) => { await view(w, h); await send('Page.navigate', { url: URL_ }); await sleep(3500); };

  // ---------- 1) 入口 + 导入面板 ----------
  await nav(1440, 900);
  await ev(`(function(){
    var ov=document.getElementById("loginOv"); if(ov) ov.style.display="none";
    state.user = { role:"produce", name:"curriculum_li", sources: initSources("produce") };
    refreshUserChip(); buildRail(); render(); return "ok";
  })()`);
  await sleep(400);
  ok('入口卡数量 = 4', (await ev(`document.querySelectorAll(".routegrid .srccard").length`)) === 4);
  await ev(`pickRoute("licensed"); "ok"`);
  await sleep(700);
  ok('授权导入面板渲染', await ev(`!!document.getElementById("licPanel")`));

  const push = (title, text) => ev(`(function(){ licPush(${JSON.stringify(title)}, ${JSON.stringify(text)}); render(); return 1; })()`);
  await ev(`(function(){ licState().arts = []; return 1; })()`);
  await push('VR in the Classroom', ART);
  await sleep(250);

  // ---- 字段：参考段数 → 只读「预计段数」 ----
  const labels = await ev(`(function(){
    var ls=document.querySelectorAll("#licPanel .licf span"); var t=[];
    for(var i=0;i<ls.length;i++) t.push(ls[i].textContent);
    return t.join("|");
  })()`);
  ok('字段改名「预计段数」（不再叫「参考段数」/「目标段数」）',
     labels.indexOf('预计段数') >= 0 && labels.indexOf('参考段数') < 0 && labels.indexOf('目标段数') < 0, labels);
  ok('「目标段数」输入框已撤（面板里不再有 number 输入）',
     (await ev(`document.querySelectorAll("#licPanel input[type=number]").length`)) === 0);

  // ---- 预计段数算法 ----
  const ests = await ev(`(function(){
    return { b1: licEstSegs("B1", ${ART_WC}), b2: licEstSegs("B2", ${ART_WC}),
             b1long: licEstSegs("B1", ${ART_WC * 8}), b1vlong: licEstSegs("B1", ${ART_WC * 12}),
             none: licEstSegs("", ${ART_WC}) };
  })()`);
  ok('预计段数 = 词数 ÷ 每段中点（51 词 → B1 2 段 / B2 1 段）',
     ests.b1 === 2 && ests.b2 === 1, JSON.stringify(ests));
  ok('预计段数：无档位时返回 0', ests.none === 0, String(ests.none));

  // ---- 偏短 / 偏长提示 ----
  await ev(`(function(){ licSet(licArts()[0].id,"level","B1"); render(); return 1; })()`);
  await sleep(220);
  const shortCalc = await ev(`(document.querySelectorAll("#licPanel .liccalc")[0]||{}).textContent||""`);
  /* 2026-09-23 口径变更（Bryan 拍板「保持静默」）：面板里的「偏短 / 偏长 / 常规区间」
     提示文字已按轻量化要求删除，这里从「应该出现」反转成「不该出现」。 */
  ok('正文偏短：不再出现「偏短 / 常规区间」提示文字',
     shortCalc.indexOf('偏短') < 0 && shortCalc.indexOf('常规区间') < 0 && shortCalc.indexOf('10–15') < 0,
     shortCalc.slice(0, 130));

  await ev(`(function(){ licArts()[0].text = ${JSON.stringify(ART.repeat(12))}; render(); return 1; })()`);
  await sleep(220);
  const longCalc = await ev(`(document.querySelectorAll("#licPanel .liccalc")[0]||{}).textContent||""`);
  const longCls = await ev(`(document.querySelectorAll("#licPanel .liccalc")[0]||{}).className||""`);
  ok('正文偏长：不再出现提示文字，但黄底警示 class 仍在（静默 ≠ 无标记）',
     longCalc.indexOf('偏长') < 0 && longCalc.indexOf('常规区间') < 0 && longCls.indexOf('warn') >= 0,
     longCalc.slice(0, 130) + ' | cls=' + longCls);

  await ev(`(function(){ licArts()[0].text = ${JSON.stringify(ART)}; licSet(licArts()[0].id,"level","B2"); render(); return 1; })()`);
  await sleep(220);
  await shot(1440, 900, '1_panel');

  // ---------- 1b) 真实 DOM 事件：改档位 / 勾精简必须**立刻**刷新就绪态与底部按钮 ----------
  // Bryan 2026-09-22 实测踩到的阻塞 bug：`licSet` 只改状态不重绘 ⇒ 粘完正文、选完档位，
  // 红条仍写「第 01 篇还没选母稿档位」，行内仍写「先选母稿档位，才能预估段数」，
  // 底部渲染的还是 `waitBtn`（**压根不是 button**）⇒ 进不了下一步。
  // 🔴 本组**不许调用 render()** —— 手动重绘会把 bug 盖掉，这正是旧回归漏掉它的原因。
  await ev(`(function(){ licState().arts = []; licPush("Gate test", ${JSON.stringify(ART)}); render(); return 1; })()`);
  await sleep(260);
  const gate0 = await ev(`(function(){
    return { need: (document.querySelector("#licPanel .licneed")||{}).textContent || "",
             btn: !!document.querySelector(".nextbar button"),
             foot: (document.querySelector(".nextbar")||{}).textContent || "" };
  })()`);
  ok('未选档位：不再出红条；底部是不可点按钮且写明「请先补全」',
     gate0.need === '' && gate0.btn === false &&
     gate0.foot.indexOf('请先补全') >= 0, JSON.stringify(gate0).slice(0, 140));

  const sel = await ev(`(function(){
    var s = document.querySelector("#licPanel select"); if(!s) return "no-select";
    s.value = "B1"; s.dispatchEvent(new Event("change", { bubbles: true })); return "dispatched";
  })()`);
  await sleep(320);
  const gate1 = await ev(`(function(){
    var b = document.querySelector(".nextbar button");
    return { level: (licArts()[0]||{}).level,
             need: (document.querySelector("#licPanel .licneed")||{}).textContent || "",
             okbar: (document.querySelector("#licPanel .licok")||{}).textContent || "",
             calc: (document.querySelectorAll("#licPanel .liccalc")[0]||{}).textContent || "",
             btn: b ? b.textContent.trim() : "",
             onclick: b ? (b.getAttribute("onclick")||"") : "",
             issues: licIssues().length };
  })()`);
  ok('选完档位（真实 change 事件）：状态写入 B1', sel === 'dispatched' && gate1.level === 'B1',
     sel + ' level=' + gate1.level);
  ok('选完档位：红条与就绪条都不出现（改由底部按钮状态表达）',
     gate1.need === '' && gate1.okbar.indexOf('已就绪') < 0, JSON.stringify([gate1.need, gate1.okbar]));
  ok('选完档位：行内「先选母稿档位，才能预估段数」立刻换成预估结果',
     gate1.calc.indexOf('先选母稿档位') < 0 && gate1.calc.indexOf('预计切成') >= 0, gate1.calc.slice(0, 90));
  ok('选完档位：底部换成真正可点的「开始分段」按钮（licRunPrep）且就绪判定为空',
     gate1.btn.indexOf('开始分段') >= 0 && gate1.onclick.indexOf('licRunPrep') >= 0 && gate1.issues === 0,
     JSON.stringify([gate1.btn, gate1.onclick, gate1.issues]));

  await ev(`(function(){ var c = document.querySelector("#licPanel input[type=checkbox]");
    c.checked = true; c.dispatchEvent(new Event("change", { bubbles: true })); return 1; })()`);
  await sleep(320);
  ok('勾「需要精简」同样立刻落到状态（走同一个 licSet 通道，勾选框也重绘了）',
     (await ev(`(licArts()[0]||{}).simplify === true && (document.querySelector("#licPanel input[type=checkbox]")||{}).checked === true`)) === true);

  // ---------- 1c) 真实 DOM 事件：粘贴 → 加入列表 → 移除，就绪态必须跟着走 ----------
  // 与 1b 同源问题：任何「改了状态却不重绘」的入口都会让红条 / 底部按钮停在旧样子。
  // 这里走的是 Bryan 实际操作的前半段（往输入框粘正文、点「加入列表」）。
  await ev(`(function(){ licState().arts = []; licPush("Keep me", ${JSON.stringify(ART)});
    licSet(licArts()[0].id, "level", "B2"); render(); return 1; })()`);
  await sleep(260);

  const pasteDispatch = await ev(`(function(){
    var t = document.getElementById("licPaste"); if(!t) return "no-textarea";
    t.value = ${JSON.stringify(ART)};
    t.dispatchEvent(new Event("input", { bubbles: true }));
    return licState().paste ? "synced" : "not-synced";
  })()`);
  ok('粘贴正文：输入框内容立刻写进 state.paste（不重绘，避免丢焦点）',
     pasteDispatch === 'synced', pasteDispatch);

  const addClick = await ev(`(function(){
    var bs = document.querySelectorAll("#licPanel .licimp-c button");
    for(var i=0;i<bs.length;i++){ if(bs[i].textContent.indexOf("加入列表")>=0){ bs[i].click(); return "clicked"; } }
    return "no-button";
  })()`);
  await sleep(400);
  const afterAdd = await ev(`(function(){
    return { n: licArts().length,
             ta: (document.getElementById("licPaste")||{}).value || "",
             need: (document.querySelector("#licPanel .licneed")||{}).textContent || "",
             btn: !!document.querySelector(".nextbar button"),
             foot: (document.querySelector(".nextbar")||document.body).textContent || "" };
  })()`);
  ok('点「加入列表」：列表 +1、输入框清空、无红条、底部回落到不可点',
     addClick === 'clicked' && afterAdd.n === 2 && afterAdd.ta === '' &&
     afterAdd.need === '' &&
     afterAdd.btn === false && afterAdd.foot.indexOf('请先补全') >= 0,
     JSON.stringify(afterAdd).slice(0, 160));

  const delClick = await ev(`(function(){
    var ds = document.querySelectorAll("#licPanel .licrow .licdel");
    if(ds.length < 2) return "rows=" + ds.length;
    ds[1].click(); return "clicked";
  })()`);
  await sleep(400);
  const afterDel = await ev(`(function(){
    return { n: licArts().length,
             need: (document.querySelector("#licPanel .licneed")||{}).textContent || "",
             okbar: (document.querySelector("#licPanel .licok")||{}).textContent || "",
             btn: (document.querySelector(".nextbar button")||{}).textContent || "" };
  })()`);
  ok('点「移除」：列表 −1、无红条无就绪条、底部换成可点的「开始分段」',
     delClick === 'clicked' && afterDel.n === 1 && afterDel.need === '' &&
     afterDel.okbar === '' && afterDel.btn.indexOf('开始分段') >= 0,
     JSON.stringify(afterDel).slice(0, 160));

  /* 还原成后面各组期望的状态：一篇 ART、档位 B2、不精简 */
  await ev(`(function(){ licState().arts = []; licPush("VR in the Classroom", ${JSON.stringify(ART)});
    licSet(licArts()[0].id, "level", "B2"); render(); return 1; })()`);
  await sleep(280);

  // ---------- 2) 确认页 · 保留原文 + 10 段（10–15 内 → 无黄条） ----------
  const prepSet = (simplified, segs, extra, level) => ev(`(function(){
    var A = licArts();
    state.lic.queue = [A[0].id]; state.lic.qi = 0; state.lic.doneIds = [];
    state.lic.prep = Object.assign({ id: A[0].id, level: ${JSON.stringify(level || "B2")}, simplified: ${simplified ? 'true' : 'false'},
      masterText: "", rawWordCount: 0, segNote: "", ok: true, warn: "", outOfBand: 0 },
      ${JSON.stringify({ segs: segs })}, ${JSON.stringify(extra || {})});
    render(); return 1;
  })()`);
  const seg10 = Array.from({ length: 10 }, () => ART);
  const seg20 = Array.from({ length: 20 }, () => ART);

  await prepSet(false, seg10, {}, 'B2');
  await sleep(350);
  ok('确认页渲染（保留原文）', await ev(`!!document.getElementById("licConfirm")`));
  const title1 = await ev(`document.querySelector("#licConfirm b").textContent`);
  ok('标题 = 确认分段（保留原文）', title1.indexOf('保留原文') >= 0, title1);
  ok('10 段（10–15 内）：不出现段数黄条',
     (await ev(`document.querySelectorAll("#licConfirm .licneed").length`)) === 0);
  const tgts1 = await ev(`(function(){
    var e=document.querySelectorAll("#licConfirm .licsegt"); return e.length? e[0].textContent : "";
  })()`);
  ok('保留原文：每段显示合格带目标「36–55 词」（B2 ±5）', tgts1.indexOf('36–55') >= 0, tgts1);
  ok('保留原文：51 词落在 B2 合格带内 → 不标红',
     (await ev(`document.querySelectorAll("#licConfirm .licsegw.warn").length`)) === 0);
  const tot1 = await ev(`document.getElementById("licSegTot").textContent.replace(/\\s+/g," ")`);
  ok('全文行写「全文字数不参与分段判断」（不再摆字数区间）',
     tot1.indexOf('不参与分段判断') >= 0 && tot1.indexOf('切成') >= 0, tot1.slice(0, 140));
  ok('全文行不再出现「× 41–50 词/段 = 区间」这种乘积',
     tot1.indexOf('词/段 =') < 0, tot1.slice(0, 140));
  await shot(1440, 900, '2_confirm_plain10');

  // ---------- 2b) 保留原文 + B1：51 词超出 23–40 → 必须标红 ----------
  await prepSet(false, seg10, {}, 'B1');
  await sleep(320);
  const tgtsB1 = await ev(`(function(){
    var e=document.querySelectorAll("#licConfirm .licsegt"); return e.length? e[0].textContent : "";
  })()`);
  ok('B1 保留原文：合格带目标显示「23–40 词」', tgtsB1.indexOf('23–40') >= 0, tgtsB1);
  ok('B1 保留原文：51 词越界 → 10 段全标红（±5 外）',
     (await ev(`document.querySelectorAll("#licConfirm .licsegw.warn").length`)) === 10);
  await shot(1440, 900, '2b_confirm_plain10_b1');

  // ---------- 3) 确认页 · 保留原文 + 20 段（> 15 → 提示 + 仍然继续生成，但不拦） ----------
  await prepSet(false, seg20, { segNote: '切出 20 段，超出常规区间 10–15 段' }, 'B2');
  await sleep(350);
  const bar = await ev(`(document.querySelector("#licConfirm .licneed")||{}).textContent||""`);
  /* 2026-09-23 Bryan 拍板：段数跑出常规区间**保持静默**（不再出提示、也不再给确认按钮）。
     这条因此反转成「不该出现」——但仍要证明它没被阻断（见下一条）。 */
  ok('20 段：不再出段数提示（保持静默）', bar === '', JSON.stringify(bar.slice(0, 140)));
  const contBtn = await ev(`(function(){
    var b=document.querySelectorAll("#licConfirm .licneed button"); for(var i=0;i<b.length;i++){ if(b[i].textContent.indexOf("继续生成")>=0) return b[i].getAttribute("onclick")||""; } return "";
  })()`);
  ok('不再有「仍然继续生成」按钮（已不阻断，无所谓人工确认）', contBtn === '', JSON.stringify(contBtn));
  const mainBtn = await ev(`(function(){ var b = document.querySelector("#licConfirm .nextbar button");
    return b ? (b.textContent.trim() + "|" + (b.getAttribute("onclick")||"")) : ""; })()`);
  ok('20 段：主生成按钮仍然可用（不阻断）· 文案为「确认，进入下一步」',
     mainBtn.indexOf('确认，进入下一步') >= 0 && mainBtn.indexOf('licGoGen') >= 0, mainBtn);
  ok('段数上限拦截已移除（源码里不再有 LIC_MAX_SEG）',
     (await ev(`typeof LIC_MAX_SEG === "undefined" && licRunGen.toString().indexOf("LIC_MAX_SEG") < 0 && licRunGen.toString().indexOf("段数超过上限") < 0`)));
  await shot(1440, 900, '3_confirm_plain20');

  // ---------- 4) 确认页 · 精简 + 12 段（标题切换 + 严格规格 + 判红） ----------
  await prepSet(true, Array.from({ length: 12 }, () => ART), {}, 'B2');
  await sleep(350);
  const title2 = await ev(`document.querySelector("#licConfirm b").textContent`);
  ok('标题 = 确认分段与精简稿', title2.indexOf('精简稿') >= 0, title2);
  const tgts2 = await ev(`(function(){
    var e=document.querySelectorAll("#licConfirm .licsegt"); return e.length? e[0].textContent : "";
  })()`);
  ok('精简模式：目标显示严格规格「41–50 词」（不带 ±5）', tgts2.indexOf('41–50') >= 0, tgts2);
  ok('精简模式：51 词越严格规格 → 12 段全红',
     (await ev(`document.querySelectorAll("#licConfirm .licsegw.warn").length`)) === 12);
  /* 全文行必须按**实际段数**现算（2026-09-22 修）：以前用 licSegRange().n，
     那个值被 LIC_REF_MIN/MAX（6–30）夹过 ⇒ 段数跑出该范围时这行会写错段数。 */
  const totSimp = await ev(`document.getElementById("licSegTot").textContent.replace(/\\s+/g," ")`);
  ok('精简模式：全文行写「12 段 × 41–50 词/段 = 492–600 词」（按实际段数现算）',
     totSimp.indexOf('12 段 × 41–50') >= 0 && totSimp.indexOf('492–600') >= 0, totSimp.slice(0, 110));
  await shot(1440, 900, '4_confirm_simp12');

  /* ---------- 4b) 展示辅助函数不许说假话：段数 > LIC_REF_MAX(30) 时不能被夹成 30 ---------- */
  await prepSet(true, Array.from({ length: 40 }, () => ART), {}, 'B2');
  await sleep(340);
  const tot40 = await ev(`document.getElementById("licSegTot").textContent.replace(/\\s+/g," ")`);
  ok('精简模式：40 段不被 LIC_REF_MAX 夹歪（写 40 段、区间按 40 现算 1640–2000）',
     tot40.indexOf('40 段') >= 0 && tot40.indexOf('1640–2000') >= 0 && tot40.indexOf('30 段') < 0,
     tot40.slice(0, 110));

  // ---------- 5) 确认页 · 精简 + 6 段（未达标 → 红条 + 重跑出口） ----------
  await prepSet(true, Array.from({ length: 6 }, () => ART), { ok: false, warn: '段数 6 段跑出常规区间 10–15 段（全文 228 词）' }, 'B2');
  await sleep(350);
  const bad = await ev(`(document.querySelector("#licConfirm .licneed.bad")||{}).textContent||""`);
  ok('精简未达标：红条写明原因', bad.indexOf('段数 6') >= 0, bad.slice(0, 120));
  ok('精简未达标：红条同时给出「重新预处理」出口',
     (await ev(`document.querySelectorAll("#licConfirm .nextbar button").length`)) >= 2);
  await shot(1440, 900, '5_confirm_simp6');

  // ---------- 6) 质检兜底治不了的段：out_of_band 必须显式说 ----------
  await prepSet(false, seg10, { outOfBand: 2, warn: '有 2 段仍落在 36–55 词之外（句子太长、无处可切）' }, 'B2');
  await sleep(320);
  const obTxt = await ev(`(document.querySelector("#licConfirm .licneed")||{}).textContent||""`);
  ok('代码也治不了的越界段：界面明说，不静默',
     obTxt.indexOf('无处可切') >= 0, obTxt.slice(0, 130));
  ok('out_of_band 已被前端收进 state',
     (await ev(`licState().prep.outOfBand`)) === 2);

  // ---------- 7) 交互不回归：单行刷新不丢焦点、合并/删除 ----------
  await prepSet(false, seg10, {}, 'B2');
  await sleep(300);
  const before = await ev(`(function(){ window.__ta = document.querySelectorAll("#licConfirm .licseg textarea")[0]; window.__ta.focus(); return document.activeElement === window.__ta; })()`);
  await ev(`(function(){ licSetSeg(0, "One two three four five six seven eight nine ten eleven twelve thirteen fourteen."); return 1; })()`);
  const after = await ev(`(function(){ return { foc: document.activeElement === window.__ta, w: document.getElementById("licSegW0").textContent, others: document.getElementById("licSegW1").textContent }; })()`);
  ok('打字时焦点不丢（未整页重渲染）', before && after.foc, 'focus=' + after.foc);
  ok('只更新第 1 段徽标，其余段不动', after.w.indexOf('14') >= 0 && after.others.indexOf('14') < 0, JSON.stringify(after));
  await ev(`licMergeSeg(0); "ok"`); await sleep(180);
  ok('合并下一段后段数 = 9', (await ev(`document.querySelectorAll("#licConfirm .licseg").length`)) === 9);
  await ev(`licDelSeg(0); "ok"`); await sleep(180);
  ok('删一段后段数 = 8', (await ev(`document.querySelectorAll("#licConfirm .licseg").length`)) === 8);
  const totAfter = await ev(`document.getElementById("licSegTot").textContent.replace(/\\s+/g," ")`);
  ok('改完段数后全文行按新段数重算', totAfter.indexOf('切成 8 段') >= 0, totAfter.slice(0, 110));

  // ---------- 8) 护栏：期望段数动态 ----------
  const wn1 = await ev(`(function(){ state.live = { status:"done", licN: 20 }; return expectedParaCount(); })()`);
  ok('期望段数取本轮授权分段数（20 段，超旧上限 16 仍生效）', wn1 === 20, String(wn1));
  const wn2 = await ev(`(function(){ state.live = { status:"done" }; return expectedParaCount(); })()`);
  ok('热点链路无 licN 时回退 12 段', wn2 === 12, String(wn2));
  const wn3 = await ev(`(function(){ state.live = { status:"done", licN: 999 }; return expectedParaCount(); })()`);
  ok('越界段数兜底 12（脏数据不崩）', wn3 === 12, String(wn3));
  const wnTxt = await ev(`(function(){ state.live={status:"done",licN:20}; state.alignGuard={warn:"",off:[],counts:["A1- 18 段"]}; return alignWarnHTML(); })()`);
  ok('告警文案说「不是 20 段」', String(wnTxt).indexOf('不是 20 段') >= 0, String(wnTxt).slice(0, 120));
  await ev(`(function(){ state.live={status:"idle"}; state.alignGuard=null; return 1; })()`);

  // ---------- 9) 精简回落（fallback）必须显式提示，不能静默 ----------
  await prepSet(true, Array.from({ length: 12 }, () => ART),
    { fallback: true, ok: false, warn: '勾了精简但没拿到精简稿（模型未按指令输出），已自动回落为保留原文' }, 'B2');
  await sleep(320);
  const fbTxt = await ev(`(document.querySelector("#licConfirm .licneed.bad")||{}).textContent||""`);
  ok('精简未跑出来 → 显式提示已保留原文（不静默）',
     fbTxt.indexOf('保留原文') >= 0 && fbTxt.indexOf('重新预处理') >= 0, fbTxt.slice(0, 120));

  // ---------- 10) 校验区：分母用后端回传值 + 说明母稿档不参与校验 ----------
  const sumTxt = await ev(`(function(){
    var d=document.createElement("div"); d.id="vsum"; document.body.appendChild(d);
    state.live = { status:"done", licN:19, run:{ data:{ outputs:{
      validation_json: JSON.stringify({total_checks:33,total_pass:28,results:[{level:"B1",fail_reasons:["长度校验"]}]}) } } } };
    state.lic = state.lic || {};
    state.lic.prep = { id:1, level:"B2", simplified:false, segs:["a"], ok:true, warn:"", segNote:"", fallback:false, masterText:"", rawWordCount:0 };
    showVSum();
    var t = d.textContent.replace(/\\s+/g," ");
    d.remove();
    return t;
  })()`);
  ok('校验分母用后端回传的 total_checks（33，不写死 44）', sumTxt.indexOf('28/33') >= 0, sumTxt.slice(0, 90));
  ok('校验区说明「母稿档不参与规格校验」', sumTxt.indexOf('不参与规格校验') >= 0, sumTxt.slice(-130));
  await ev(`(function(){ state.live={status:"idle"}; state.lic.prep=null; return 1; })()`);

  // ---------- 11) 逐段大意核对（图 B · nodeSemCheck，2026-09-22 新增） ----------
  // 覆盖：全过 / 有错位 / markdown 包裹 / 无法解析 / 无字段 五种情况，
  // 以及「被点名的行加 sembad 标记」。判据全部走真实渲染，不查源码字符串。
  {
    const setSem = (raw) => ev(`(function(){
      state.live = { status:"done", licN:12, run:{ data:{ outputs:{ sem_json: ${JSON.stringify(raw)} } } } };
      state.lic = state.lic || {};
      state.lic.prep = { id:1, level:"B2", simplified:false, segs:["a"], ok:true, warn:"", segNote:"", fallback:false, masterText:"", rawWordCount:0 };
      var d=document.createElement("div"); d.id="licSemBox"; d.innerHTML = semWarnHTML();
      return d.textContent.replace(/\\s+/g," ");
    })()`);

    const allOk = await setSem(JSON.stringify({ levels:[{level:"B1",bad:[],notes:[]},{level:"A2",bad:[],notes:[]}], bad_total:0, summary:"2 档逐段对齐，无错位" }));
    ok('大意核对全过：整块不显示（中性提示已撤）+ 不报警',
       String(allOk).trim() === '' && allOk.indexOf('发现错位') < 0, JSON.stringify(String(allOk).slice(0, 110)));

    const badTxt = await setSem(JSON.stringify({ levels:[{level:"B1",bad:[3,7],notes:["第3段讲的是成本","第7段讲的是师资"]},{level:"A2",bad:[],notes:[]}], bad_total:2, summary:"B1 有 2 段错位" }));
    ok('大意核对有错位：报警 + 点名档位与段号',
      badTxt.indexOf('发现错位') >= 0 && badTxt.indexOf('B1') >= 0 && badTxt.indexOf('第 3、7 段') >= 0, badTxt.slice(0, 150));
    ok('大意核对：写明「不影响入库」（不拦）', badTxt.indexOf('不影响入库') >= 0, badTxt.slice(-80));
    /* 文案里不许残留 markdown 星号（HTML 不解析，会原样显示出来） */
    const star = await ev(`(function(){
      state.live = { status:"done", licN:12, run:{ data:{ outputs:{ sem_json: JSON.stringify({levels:[{level:"B1",bad:[3],notes:["x"]}],bad_total:1,summary:""}) } } } };
      return semWarnHTML().indexOf("**") >= 0;
    })()`);
    ok('大意核对：渲染结果里不含 markdown 星号', star === false, 'has**=' + star);

    const wrapped = await setSem('```json\n' + JSON.stringify({ levels:[{level:"B1",bad:[2],notes:["两段混讲"]}], bad_total:1, summary:"1 段错位" }) + '\n```');
    ok('大意核对：带 markdown 包裹仍能解析', wrapped.indexOf('第 2 段') >= 0, wrapped.slice(0, 120));

    const broken = await setSem('模型这次没按约定输出 JSON');
    ok('大意核对：无法解析时显式提示（不静默）', broken.indexOf('无法解析') >= 0, broken.slice(0, 120));

    const noneTxt = await setSem('');
    ok('无 sem_json 时整块不显示（热点链路 / 老图不受影响）', String(noneTxt).trim() === '', JSON.stringify(String(noneTxt).slice(0, 50)));

    /* 行标记：被点名的段号必须给对应行加 sembad（直接渲染对齐视图，不依赖当前路由） */
    const mark = await ev(`(function(){
      state.live = { status:"done", licN:3, run:{ data:{ outputs:{
        sem_json: JSON.stringify({levels:[{level:"B1",bad:[3],notes:["x"]}],bad_total:1,summary:""}),
        articles_json: JSON.stringify({B2:"b2a\\n\\nb2b\\n\\nb2c", B1:"b1a\\n\\nb1b\\n\\nb1c", A2:"a2a\\n\\na2b\\n\\na2c", A1:"a1a\\n\\na1b\\n\\na1c"}),
        paras_json: JSON.stringify({B2:["b2a","b2b","b2c"], B1:["b1a","b1b","b1c"], A2:["a2a","a2b","a2c"], A1:["a1a","a1b","a1c"]}),
        levels_json: JSON.stringify(["B2","B1","A2","A1"]) } } } };
      applyLive();
      var d=document.createElement("div"); d.innerHTML = alignBodyHTML(false); document.body.appendChild(d);
      var rows = d.querySelectorAll(".alignrow.sembad").length;
      var all = d.querySelectorAll(".alignrow").length;
      var ok1 = d.querySelectorAll(".alignrow.sembad .arow-no").length;
      d.remove();
      return JSON.stringify({ set: Object.keys(semBadSegs()), rows: rows, all: all, no: ok1 });
    })()`);
    const mj = JSON.parse(mark);
    ok('行标记：semBadSegs 认出错位档位', mj.set.indexOf('B1') >= 0, mark);
    ok('行标记：3 行段落、恰好 1 行被标 sembad', mj.all === 3 && mj.rows === 1, mark);
    await ev(`(function(){ state.live={status:"idle"}; return 1; })()`);
  }

  // ---------- 12) 窄屏不塌 ----------
  for (const [w, h, tag] of [[1024, 800, '6_panel_1024'], [420, 820, '7_panel_420']]) {
    await ev(`(function(){ state.lic.prep = null; render(); return 1; })()`);
    await sleep(220);
    await view(w, h); await sleep(450);
    const m = await ev(`JSON.stringify({sw: document.documentElement.scrollWidth, iw: window.innerWidth})`);
    ok(`${w}px 无横向溢出`, JSON.parse(m).sw === JSON.parse(m).iw, m);
    await shot(w, h, tag);
  }

  const pass = R.filter(r => r.ok).length;
  console.log('\n=== 结果 ===');
  R.forEach(r => console.log(`  ${r.ok ? '✓' : '✗'} ${r.label}${r.detail ? '   [' + r.detail + ']' : ''}`));
  console.log(`\n${pass}/${R.length} 项通过`);
  const realErrs = errs.filter(e => !/Failed to load resource|net::ERR|favicon|config\.local/i.test(e));
  console.log('JS 异常 / console.error：' + (realErrs.length ? '\n  ' + realErrs.join('\n  ') : '0 条 ✅'));
  console.log('截图：' + SHOT + '_*.png');
  ws.close();
  process.exit(pass === R.length && realErrs.length === 0 ? 0 : 1);
}
main().catch(e => { console.error('探针异常：', e && e.stack || e); process.exit(1); });
