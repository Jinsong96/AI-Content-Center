// ReadPal · 「事实卡可编辑 / 可删除」回归探针 —— 2026-09-23
//
// 为什么需要它：事实分段抽完卡之后要允许教研就地改、删。这件事有两半，只有一半是肉眼可见的：
//   ① 界面上卡片文字变了（看得见）
//   ② state.factsCache.facts_text / facts_raw.facts 跟着变了（看不见）—— 而 GEN 生成的
//      B1/B2+ 高档素材，就是 nodeClean 逐条读 facts_raw.facts[].en 现拼出来的。
// 只做 ① 不做 ② = 「编辑了没用」的静默失败：界面上改了，生成出来的文章还是旧事实。
//
// 断言（任一失败退出码 1）：
//   ① 抽完卡后每张卡都带「编辑 / 删除」，兜底态（未抽到真卡）一个都不给
//   ② 编辑保存：卡片文字变 + facts_text 对应行变 + facts_raw.facts[i].en 变 —— 三项必须同时成立
//   ③ 编辑保存后该卡的 gist 归属号不丢（丢了 B1/B2+ 的细节会挂到错的大意上）
//   ④ 取消编辑：界面与入参都不留痕
//   ⑤ 删除：卡片数 / facts_text 行数 / facts_raw.facts 长度同步 -1，且留下的卡 gist 不串位
//   ⑥ 至少保留 1 张卡（删到只剩 1 张再删无效）
//   ⑦ 已产出文章后改卡：置脏 + 清掉按编号的 fact_map（否则校对页按旧编号标「被引用 P1」）
//   ⑧ 编辑层与 live 同源：state.live 清空（换素材 / 切入口）后，编辑层不得冒充当前素材的卡
//   ⑨ 新增事实卡（2026-09-23 · Bryan：把过长的事实拆成两条）：
//      点「＋新增」在**原卡后面**插一张并继承 gist；空卡不许进 facts_text；
//      保存后三处入参同步 +1；不填就取消则不留空卡、不污染入参
//   ⑩ 全程无 JS 异常
//
// 负向对照（证明 ②⑤ 的检测器不是摆设）：把 factsSyncToCache() 的两处调用去掉再跑同一探针，
// ② 的「入参那两项」必须失败 —— 那正是「只在渲染层叠加」的 bug 形态。
//
// 用法：
//   cd frontend && python3 -m http.server 8899 --bind 127.0.0.1   # 另开终端，必须后台常驻
//   node tools/probe_fact_edit.mjs --url=http://127.0.0.1:8899/index.html --port=9250
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const argv = process.argv.slice(2);
const arg = (k, d = null) => { const h = argv.find(a => a.startsWith(`--${k}=`)); return h ? h.slice(k.length + 3) : d; };
const URL_ = arg('url', 'http://127.0.0.1:8899/index.html');
const PORT = Number(arg('port', process.env.CDP_PORT || 9250));
const CDP = `http://127.0.0.1:${PORT}`;
const PROFILE = path.join(os.tmpdir(), `readpal_factedit_${PORT}`);
const sleep = ms => new Promise(r => setTimeout(r, ms));

function findChrome() {
  const c = [process.env.CHROME_BIN, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium', '/usr/bin/google-chrome',
    '/usr/bin/chromium'].filter(Boolean);
  return c.find(p => { try { return fs.statSync(p).isFile(); } catch { return false; } });
}
const alive = async () => { try { await fetch(`${CDP}/json/version`); return true; } catch { return false; } };
async function ensureChrome() {
  if (await alive()) return;
  const bin = findChrome();
  if (!bin) { console.error('✗ 找不到 Chrome'); process.exit(1); }
  fs.rmSync(PROFILE, { recursive: true, force: true });
  spawn(bin, ['--headless=new', '--disable-gpu', '--no-sandbox', `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE}`, '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  for (let i = 0; i < 40; i++) { await sleep(400); if (await alive()) return; }
  console.error('✗ Chrome 启动超时'); process.exit(1);
}

const R = [];
const errs = [];
const ok = (label, cond, detail) => R.push({ ok: !!cond, label, detail: detail == null ? '' : String(detail) });

// 4 张卡 / gist 归属 [1,1,2,2] —— 删卡后能看出 gist 有没有整体串位
const FACTS = [
  { en: 'A Li brocade workshop in Wuzhishan greets visitors with dolls and bags.', zh: '五指山的黎锦工坊用玩偶和手袋迎接访客。', gist: 1 },
  { en: 'Patterns once seen only on traditional garments now appear on daily items.', zh: '过去只见于传统服饰的纹样，如今用在了日用品上。', gist: 1 },
  { en: 'The workshop employs more than forty local weavers, most of them women.', zh: '工坊雇用了四十多名当地织工，多数是女性。', gist: 2 },
  { en: 'Sales reached nearly three million yuan in the first half of the year.', zh: '上半年销售额接近三百万元。', gist: 2 },
];
const EDITED = 'A Li brocade workshop now sells to buyers in eighteen countries.';
/* 用来测「新增事实卡」：把一条长事实拆成两条时，新卡该填的内容 */
const SPLIT = 'Most of those weavers learned the craft from their mothers.';

const SETUP = `(async()=>{
  const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
  var ov=document.getElementById("loginOv"); if(ov) ov.style.display="none";
  state.user = { role:"produce", name:"probe", sources: initSources("produce") };
  refreshUserChip(); buildRail();
  pickRoute("trend");

  /* ① 造一次「已抽完事实卡」的运行结果（不跑真工作流，只喂输出） */
  const F = ${JSON.stringify(FACTS)};
  const outs = {
    summary: "Young people revive Li brocade in Hainan",
    facts_json: JSON.stringify(F.map(function(f){ return { en:f.en, zh:f.zh }; })),
    facts_raw: JSON.stringify({ summary:"s", gist:[{en:"g1",zh:"g1"},{en:"g2",zh:"g2"}], facts:F }),
    facts_text: F.map(function(f,i){ return (i+1)+". "+f.en; }).join("\\n"),
    gist: "1. Reviving a traditional craft\\n2. Turning it into a business",
    angle: "culture", level:"B1", level_lo:"B1", level_hi:"B2"
  };
  window.__run = { data:{ status:"succeeded", outputs: outs } };
  state.live = { status:"done", material:"Li brocade workshop probe material long enough to pass the guard.", label:"probe", book:"", run: window.__run, err:null, t0:Date.now(), elapsed:1 };
  state.extracted = true;
  applyLive();
  /* step 5 = s4「事实分段」页（fns[4] 是素材库，别写错 —— 写错就变成「页面上没有卡」） */
  cur = 5; refreshRail(); render();

  const cards = function(){ return Array.prototype.slice.call(document.querySelectorAll("#factlist .fcard")); };
  const editBtn = function(i){ const c=cards()[i]; return c ? c.querySelector(".fop") : null; };
  const delBtn  = function(i){ const c=cards()[i]; if(!c) return null; const b=c.querySelectorAll(".fop"); return b.length ? b[b.length-1] : null; };
  const saveBtn = function(){ return document.querySelector(".fedit-bar .btn"); };
  const cancelBtn = function(){ const b=document.querySelectorAll(".fedit-bar .btn"); return b.length>1?b[1]:null; };
  const ta = function(k){ var e=document.querySelectorAll("#factlist .fedit"); return e[k||0]; };
  const cache = function(){ var fc=state.factsCache||{}; var raw={}; try{ raw=JSON.parse(fc.facts_raw||"{}"); }catch(e){}
    return { text:String(fc.facts_text||""), rawFacts:(raw.facts||[]).map(function(f){ return { en:f.en, gi:f.gist }; }) }; };
  const out = {};

  /* ② 初始态：4 张卡，每张都有编辑 + 删除 */
  out.init = { n: cards().length,
               fops: cards().map(function(c){ return c.querySelectorAll(".fop").length; }),
               texts: cards().map(function(c){ var s=c.querySelector(".stmt"); return s?s.textContent:""; }) };

  /* ③ 编辑第 2 张（index 1）：真敲进 textarea，再点保存 */
  editBtn(1).click();
  out.editOpen = { boxes: document.querySelectorAll("#factlist .fedit").length,
                   en: ta(0) ? ta(0).value : null, zh: ta(1) ? ta(1).value : null };
  ta(0).value = ${JSON.stringify(EDITED)};
  ta(0).dispatchEvent(new Event("input", {bubbles:true}));
  ta(1).value = "黎锦工坊现在卖到十八个国家。";
  ta(1).dispatchEvent(new Event("input", {bubbles:true}));
  saveBtn().click();
  var c1 = cache();
  out.afterEdit = {
    stmt1: (cards()[1].querySelector(".stmt")||{}).textContent || "",
    zh1: (cards()[1].querySelector(".zh")||{}).textContent || "",
    editedBadge: (cards()[1].innerText||"").indexOf("人工修订") >= 0,
    boxesLeft: document.querySelectorAll("#factlist .fedit").length,
    text: c1.text,
    raw1: c1.rawFacts[1],
    raw0: c1.rawFacts[0]
  };

  /* ④ 取消编辑：第 1 张改一半后取消，界面与入参都不许留痕 */
  editBtn(0).click();
  ta(0).value = "SHOULD NEVER SURVIVE";
  ta(0).dispatchEvent(new Event("input", {bubbles:true}));
  cancelBtn().click();
  var c2 = cache();
  out.afterCancel = { stmt0: (cards()[0].querySelector(".stmt")||{}).textContent || "",
                      boxesLeft: document.querySelectorAll("#factlist .fedit").length,
                      text: c2.text };

  /* ⑤ 删除第 1 张：编号整体前移，留下的卡必须还挂在原来那条大意上（gist 不串位） */
  delBtn(0).click();
  var c3 = cache();
  out.afterDelete = { n: cards().length, lines: c3.text.split("\\n").filter(Boolean).length,
                      rawLen: c3.rawFacts.length, raw: c3.rawFacts, zh0: (cards()[0].querySelector(".zh")||{}).textContent||"" };

  /* ⑥ 已产出文章后再删卡 → 置脏 + 清掉按编号的 fact_map（否则校对页按旧编号标「被引用 P1」） */
  GEN = { B2: { title:"t", by:"probe", used:[], metrics:[],
                cover:{ tag:{zh:"",en:""}, line:"", sub:{zh:"",en:""} },
                paras:[["placeholder paragraph for the dirty check"]] } };
  state.factMap = { B2:[[1],[2]] }; state.unusedFacts = [3];
  delBtn(0).click();
  out.afterDirty = { cards: cards().length, dirty: !!state.factsDirty,
                     factMap: state.factMap, unused: state.unusedFacts,
                     note: (document.querySelector("#stage").innerText||"").indexOf("事实卡已改动") >= 0 };

  /* ⑦ 保底 1 张：删到只剩 1 张后再删，必须无效 */
  while (cards().length > 1) delBtn(0).click();
  out.floor = { before: cards().length };
  delBtn(0).click();
  out.floor.after = cards().length;
  out.floor.editLen = (state.factsEdit||[]).length;

  /* ⑦b 新增事实卡 —— 用来把一条过长的事实拆成两条（Bryan 2026-09-23 提的需求） */
  const addBtnOf = function(k){
    var b = cards()[k].querySelectorAll(".fop");
    for(var i=0;i<b.length;i++){ if(b[i].textContent.indexOf("新增")>=0) return b[i]; }
    return null;
  };
  out.addInit = { n: cards().length,
                  fops: cards().map(function(c){ return c.querySelectorAll(".fop").length; }) };

  /* 点第 1 张开「＋ 新增」—— 新卡必须紧跟它，且立刻展开编辑框 */
  const ab0 = addBtnOf(0);
  out.addHasBtn = !!ab0;
  if(ab0) ab0.click();
  var cA = cache();
  out.afterAddOpen = {
    n: cards().length,
    atIdx: (function(){ var cs=cards(); for(var i=0;i<cs.length;i++){ if(cs[i].querySelector(".fedit")) return i; } return -1; })(),
    boxes: document.querySelectorAll("#factlist .fedit").length,
    en: ta(0) ? ta(0).value : null,
    /* 空卡不许进 facts_text：行数应仍等于「有内容的卡数」 */
    lines: cA.text.split("\\n").filter(Boolean).length
  };

  /* 填好保存 */
  ta(0).value = ${JSON.stringify(SPLIT)};
  ta(0).dispatchEvent(new Event("input", {bubbles:true}));
  ta(1).value = "多数织工的手艺是从母亲那里学的。";
  ta(1).dispatchEvent(new Event("input", {bubbles:true}));
  saveBtn().click();
  var cB = cache();
  out.afterAddSave = {
    n: cards().length,
    lines: cB.text.split("\\n").filter(Boolean).length,
    rawLen: cB.rawFacts.length,
    raw0: cB.rawFacts[0],                    /* 原卡 */
    raw1: cB.rawFacts[1],                    /* 新卡 */
    addedBadge: (cards()[1].innerText||"").indexOf("人工新增") >= 0,
    stmt1: (cards()[1].querySelector(".stmt")||{}).textContent || ""
  };

  /* 再新增一张，这次**不填就取消** —— 不许残留在界面/编辑层/入参里 */
  const ab1 = addBtnOf(0);
  if(ab1) ab1.click();
  out.afterAddOpen2 = { n: cards().length, boxes: document.querySelectorAll("#factlist .fedit").length };
  cancelBtn().click();
  var cC = cache();
  out.afterAddCancel = {
    n: cards().length,
    editLen: (state.factsEdit||[]).length,
    lines: cC.text.split("\\n").filter(Boolean).length,
    fops: document.querySelectorAll("#factlist .fop").length
  };

  /* ⑧ 编辑层与 live 同源：state.live 清空（≈换素材 / 切入口）后不得冒充当前素材 */
  state.live = { status:"idle", material:"", label:"", book:"", run:null, err:null, t0:0, elapsed:0 };
  render();
  out.afterLiveCleared = { cards: cards().length,
                           fops: document.querySelectorAll("#factlist .fop").length,
                           leakedEdit: (document.querySelector("#factlist").innerText||"").indexOf(${JSON.stringify(EDITED)}) >= 0 };

  return JSON.stringify(out);
})()`;

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
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || JSON.stringify(r.result.exceptionDetails).slice(0, 400));
    return r.result?.result?.value;
  };

  await send('Runtime.enable'); await send('Page.enable');
  await send('Page.navigate', { url: URL_ });
  await sleep(3500);

  const raw = await ev(SETUP);
  if (typeof raw !== 'string') { console.error('✗ SETUP 返回非字符串:', JSON.stringify(raw).slice(0, 400)); process.exit(1); }
  const r = JSON.parse(raw);

  const init = r.init || {};
  ok('抽完卡后渲染出 4 张事实卡', init.n === 4, `n=${init.n}`);
  ok('每张卡都带「编辑 + ＋新增 + 删除」三个入口', Array.isArray(init.fops) && init.fops.length === 4 && init.fops.every(n => n === 3),
     JSON.stringify(init.fops));

  const eo = r.editOpen || {}, ae = r.afterEdit || {};
  ok('点「编辑」就地展开两个输入框，且预填当前内容',
     eo.boxes === 2 && eo.en === FACTS[1].en && eo.zh === FACTS[1].zh, JSON.stringify(eo).slice(0, 160));
  ok('保存后卡片文字变成改后的版本', ae.stmt1 === EDITED && ae.zh1 === '黎锦工坊现在卖到十八个国家。', `stmt1=${String(ae.stmt1).slice(0, 50)}`);
  ok('保存后标出「人工修订」，且编辑框收起', ae.editedBadge === true && ae.boxesLeft === 0, `badge=${ae.editedBadge} boxes=${ae.boxesLeft}`);
  ok('🔴 保存后回写 facts_text（GEN 入参之一）', String(ae.text || '').split('\n')[1] === '2. ' + EDITED, String(ae.text || '').split('\n')[1]);
  ok('🔴 保存后回写 facts_raw.facts[1].en（B1/B2+ 高档素材的真源）', (ae.raw1 || {}).en === EDITED, JSON.stringify(ae.raw1).slice(0, 90));
  ok('保存后该卡 gist 归属号不丢（B1/B2+ 细节不串到别的大意上）', (ae.raw1 || {}).gi === FACTS[1].gist, JSON.stringify(ae.raw1).slice(0, 90));
  ok('未改动的卡原样保留（没被顺手覆盖成空）', (ae.raw0 || {}).en === FACTS[0].en && (ae.raw0 || {}).gi === FACTS[0].gist, JSON.stringify(ae.raw0).slice(0, 90));

  const ac = r.afterCancel || {};
  ok('取消编辑：界面不留痕', ac.stmt0 === FACTS[0].en && ac.boxesLeft === 0, `stmt0=${String(ac.stmt0).slice(0, 40)} boxes=${ac.boxesLeft}`);
  ok('取消编辑：入参不留痕（facts_text 与编辑前一致）', String(ac.text || '') === String(ae.text || ''), 'cancel changed facts_text');

  const ad = r.afterDelete || {};
  ok('删除后卡片数 -1', ad.n === 3, `n=${ad.n}`);
  ok('🔴 删除后 facts_text 行数同步 -1', ad.lines === 3, `lines=${ad.lines}`);
  ok('🔴 删除后 facts_raw.facts 长度同步 -1', ad.rawLen === 3, `len=${ad.rawLen}`);
  ok('🔴 删除后留下的卡仍挂原来那条大意（gist 不因子标前移而串位）',
     Array.isArray(ad.raw) && ad.raw.length === 3 && ad.raw[0].gi === FACTS[1].gist && ad.raw[1].gi === FACTS[2].gist && ad.raw[2].gi === FACTS[3].gist,
     JSON.stringify(ad.raw));
  /* 原来的第 2 张此刻应该是「已改过 + 已前移到第 1 位」的那张（改后的中文） */
  ok('删除后第一张卡是原来的第 2 张（且保留它的编辑结果）', String(ad.zh0 || '') === '黎锦工坊现在卖到十八个国家。', String(ad.zh0 || '').slice(0, 30));

  const adr = r.afterDirty || {};
  ok('已产出文章后改卡：置脏并在页面上明说「已生成文章不会自动更新」', adr.dirty === true && adr.note === true,
     `dirty=${adr.dirty} note=${adr.note}`);
  ok('已产出文章后删卡：按编号的 fact_map / unused_facts 被清掉（不留错位溯源）',
     adr.factMap === null && Array.isArray(adr.unused) && adr.unused.length === 0, JSON.stringify(adr).slice(0, 120));

  const fl = r.floor || {};
  ok('至少保留 1 张卡：删到剩 1 张后再删无效', fl.before === 1 && fl.after === 1 && fl.editLen === 1,
     `before=${fl.before} after=${fl.after} len=${fl.editLen}`);

  const ai = r.addInit || {}, ao = r.afterAddOpen || {}, as = r.afterAddSave || {}, acd = r.afterAddCancel || {};
  ok('「＋ 新增」入口存在于每张卡上', ai.fops && ai.fops.length >= 1 && ai.fops.every(n => n === 3), JSON.stringify(ai.fops));
  ok('点「＋ 新增」：卡片数 +1，且新卡插在原卡**后面**（不是追加到末尾）',
     r.addHasBtn === true && ao.n === (ai.n + 1) && ao.atIdx === 1, JSON.stringify(ao).slice(0, 140));
  ok('新卡直接展开空格子（可立刻填）', ao.boxes === 2 && ao.en === '', JSON.stringify(ao).slice(0, 140));
  ok('🔴 没填内容的卡不进 facts_text（否则多出一条空事实，后面编号全部错位）',
     ao.lines === ai.n, `lines=${ao.lines} expect=${ai.n}`);
  ok('保存新卡：卡片数与 facts_text 行数同步 +1',
     as.n === (ai.n + 1) && as.lines === (ai.n + 1), JSON.stringify(as).slice(0, 140));
  ok('🔴 保存新卡：回写 facts_raw.facts，且插在原卡后面',
     as.rawLen === (ai.n + 1) && (as.raw1 || {}).en === SPLIT, JSON.stringify(as.raw1).slice(0, 90));
  ok('🔴 新卡继承原卡的 gist 归属号（不继承 ⇒ GEN 拿到 NaN ⇒ 这张卡被静默丢弃）',
     (as.raw1 || {}).gi !== undefined && (as.raw1 || {}).gi === (as.raw0 || {}).gi,
     `new=${JSON.stringify(as.raw1)} orig=${JSON.stringify(as.raw0)}`);
  ok('新卡标「人工新增」（不是 AI 的 AUTO）', as.addedBadge === true, `badge=${as.addedBadge}`);
  /* 🔴 基准要看清：第一次新增已经**保存**了（卡数 +1），所以取消第二次之后应回到 ai.n + 1，
     不是 ai.n —— 这里先前写错过一次，代码没问题、是断言口径算错。 */
  ok('第二次点「＋ 新增」仍能插入（不是只能加一次）',
     (r.afterAddOpen2 || {}).n === ai.n + 2, JSON.stringify(r.afterAddOpen2 || {}));
  ok('新增后不填就取消：界面与编辑层都不留空卡（回到「只多了已保存的那张」）',
     acd.n === ai.n + 1 && acd.editLen === ai.n + 1, JSON.stringify(acd).slice(0, 140));
  ok('取消新增：facts_text 未被污染（空卡没进去，行数 = 已保存的卡数）',
     acd.lines === ai.n + 1, `lines=${acd.lines} expect=${ai.n + 1}`);

  const lc = r.afterLiveCleared || {};
  ok('🔴 state.live 清空后编辑层不冒充当前素材（不泄漏上一批的卡）', lc.leakedEdit === false, JSON.stringify(lc).slice(0, 120));
  ok('兜底态（无真卡）不给编辑/删除入口，不假装能改', lc.fops === 0, `fops=${lc.fops} cards=${lc.cards}`);

  ok('全程无 JS 异常', errs.length === 0, errs.join(' | '));

  console.log('\n=== 事实卡「可编辑 / 可删除」回归 ===');
  R.forEach(x => console.log(`${x.ok ? '  ✅' : '  ❌'} ${x.label}${x.detail ? '   → ' + x.detail : ''}`));
  const bad = R.filter(x => !x.ok).length;
  console.log(`\n结果: ${R.length - bad}/${R.length} 通过${bad ? ' ❌' : ' ✅'}`);
  process.exit(bad ? 1 : 0);
}
main().catch(e => { console.error('✗ 探针异常:', e.message); process.exit(1); });
