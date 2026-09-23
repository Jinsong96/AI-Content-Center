// 「轻量提示词」（lite）**真端到端**探针 —— 2026-09-23
//
// 与 probe_lite_route.mjs 的分工：
//   · probe_lite_route.mjs —— stub 掉 difyCall，只验 UI 状态机（快、可反复跑、不依赖密钥）
//   · 本探针 —— **不 stub**，真浏览器 → 真 api.dify.ai → 真图 C，验「整条路真的能跑出文章」
//     这一步以前没人做过（图 A/B 上线时也是先跑真链路才发现的字段名问题）。
//
// 前置：
//   1. frontend/config.local.js 必须有 DIFY_WF_LITE（否则页面会提示「未配置」，本探针会先拦下）
//   2. frontend/ 下起静态服务：python3 -m http.server 8899 --bind 127.0.0.1
//   3. 网络可达 api.dify.ai
//
// 用法：
//   node tools/probe_lite_e2e.mjs            # 真实生成一次（约 40–120s）
//   MASTER_FILE=/tmp/x.txt node tools/probe_lite_e2e.mjs
//
// 退出码：0 全绿；1 有失败
import fs from 'node:fs';
import { spawn } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';

const PORT = Number(process.env.CDP_PORT || 9276);
const CDP = `http://127.0.0.1:${PORT}`;
const PROFILE = path.join(os.tmpdir(), `readpal_lite_e2e_${PORT}`);
const URL_ = process.env.URL_ || 'http://127.0.0.1:8899/index.html';
const sleep = ms => new Promise(r => setTimeout(r, ms));

const DEFAULT_MASTER = [
  'Every spring, a quiet change happens on the rooftops of many European cities.',
  'Small wooden boxes appear above offices, schools and apartment blocks.',
  'Inside each box live thousands of honeybees.',
  'City councils once treated bees as a problem.',
  'Today many of them pay for the boxes and teach residents how to look after the insects.',
  'Supporters say city bees often do better than country bees.',
  'Farms grow one crop over huge areas, so bees there find food for only a few weeks.',
  'In cities, parks and gardens bloom at different times, which gives the insects a longer season.',
  'Not everyone is happy. Some scientists warn that too many hives can harm wild bees.',
  'The debate is not really about honey. It is about how a crowded place should share its space.',
].join('\n');
const MASTER = process.env.MASTER_FILE
  ? fs.readFileSync(process.env.MASTER_FILE, 'utf-8').trim()
  : DEFAULT_MASTER;
const MASTER_TITLE = process.env.MASTER_TITLE || 'City Bees Move to the Rooftops';
/* 母稿首段的特征串 —— 用来证明 B1 档入库的是「用户粘贴的原文」而不是模型改写 */
const MASTER_MARK = MASTER.split('\n')[0].slice(0, 40);

function findChrome() {
  return [process.env.CHROME_BIN,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium']
    .filter(Boolean).find(p => { try { return fs.statSync(p).isFile(); } catch { return false; } });
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

const SETUP = `(async()=>{
  const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
  const out={}; const errs=[];
  const _ce=console.error; console.error=function(){ errs.push(Array.prototype.slice.call(arguments).join(' ').slice(0,140)); return _ce.apply(console,arguments); };

  document.getElementById("loginOv").style.display="none";
  state.user={role:"produce",name:"curriculum_li",sources:(typeof initSources==="function"?initSources("produce"):[])};
  if(typeof refreshUserChip==="function") refreshUserChip();
  if(typeof buildRail==="function") buildRail();
  state.tagContent=["world"];
  if(typeof genLiveCover==="function") window.genLiveCover=function(){};

  /* ⓪ 密钥必须已注入 —— 否则后面「生成」按钮会直接报未配置，看起来像功能坏了 */
  out.hasCfg = !!(window.WB_CFG && Object.keys(window.WB_CFG).length);
  out.liteKeySet = !!(window.WB_CFG && window.WB_CFG.DIFY_WF_LITE);
  out.liteKeyTail = out.liteKeySet ? String(window.WB_CFG.DIFY_WF_LITE).slice(-5) : "";

  /* ① 入口 */
  go(0); state.route=null; render(); await sleep(200);
  const cards=Array.prototype.slice.call(document.querySelectorAll(".routegrid .srccard"));
  out.cardCount=cards.length;
  out.card5=(function(){ const h=cards[4]&&cards[4].querySelector("h4"); return h?h.textContent.trim():""; })();

  /* ② 进入 lite + 粘贴 */
  pickRoute("lite"); await sleep(300);
  out.hasPanel=!!document.getElementById("litePanel");
  const ta=document.getElementById("litePaste");
  ta.value=${JSON.stringify(MASTER)};
  ta.dispatchEvent(new Event("input",{bubbles:true}));
  await sleep(150);
  const ti=document.getElementById("liteTitle");
  ti.value=${JSON.stringify(MASTER_TITLE)};
  ti.dispatchEvent(new Event("input",{bubbles:true}));
  await sleep(200);
  const bar=document.querySelector("#stage .nextbar, #stage .waitbar");
  out.embarkClickable=!!(bar&&bar.querySelector("button"));

  /* ③ 真跑（不 stub）。最多等 240s，80% 时给一次「仍在跑」的记录 */
  const t0=Date.now();
  let done=false;
  const runner=liteRun();
  for(let i=0;i<240;i++){
    await sleep(1000);
    if(cur===7 || (state.live&&state.live.status==="done") || (state.lic&&state.lic.err)){ done=true; break; }
    if(i===79) out.stillRunningAt80s=true;
  }
  try{ await runner; }catch(e){ out.runnerThrew=String(e&&e.message||e).slice(0,120); }
  await sleep(800);
  out.elapsed=Math.round((Date.now()-t0)/1000);
  out.doneByRender=done;
  out.cur=cur;
  out.err=String((state.lic&&state.lic.err)||"").slice(0,180);

  /* ④ 三档文章
     ⚠️ GEN[k] **没有 text 字段** —— 结构是 {title, by, cover, paras:[[p],…], metrics, used}，
     正文只能由 paras 拼回来。第一版断言写了 GEN.A1.text ⇒ 恒为 0 词，是断言 bug 不是产品 bug。 */
  out.genKeys=Object.keys(GEN).sort();
  const paras=function(k){ return (GEN[k]&&GEN[k].paras)?GEN[k].paras:[]; };
  const txt=function(k){ return paras(k).map(function(p){ return Array.isArray(p)?p.join(" "):String(p); }).join(" "); };
  out.pA1=paras("A1").length; out.pA2=paras("A2").length; out.pB1=paras("B1").length;
  out.wordsA1=txt("A1").split(/\\s+/).filter(Boolean).length;
  out.wordsA2=txt("A2").split(/\\s+/).filter(Boolean).length;
  out.wordsB1=txt("B1").split(/\\s+/).filter(Boolean).length;
  out.b1IsMaster=!!(paras("B1")[0]&&String(paras("B1")[0]).indexOf(${JSON.stringify(MASTER_MARK)})>=0);
  out.b1ParaEqPaste=paras("B1").length === ${JSON.stringify(MASTER.split('\n').length)};
  /* A1 与 A2 必须真的不同 —— 「逐级简化」是否发生（这是提示词的核心要求） */
  out.a1a2Different = out.wordsA1>0 && txt("A1") !== txt("A2");
  out.a1Shorter = out.wordsA1>0 && out.wordsA2>0 && out.wordsA1 < out.wordsA2;
  /* 低档是否真的比母稿好读：A1- 句长应明显短于母稿 */
  const sentLen=function(k){ const t=txt(k); const s=t.split(/[.!?]+/).filter(function(x){return x.trim().length>2;}).length; return s?+(out["words"+k]/s).toFixed(1):0; };
  out.wpsA1=sentLen("A1"); out.wpsA2=sentLen("A2"); out.wpsB1=sentLen("B1");

  /* ⑤ 题目 */
  out.quizLevels=Object.keys(state.quiz||{}).sort();
  out.quizCounts=out.quizLevels.map(function(k){return k+":"+((state.quiz[k]||[]).length);});
  out.typesA1=(state.quiz.A1||[]).map(function(q){return q.type;}).join(",");
  out.typesA2=(state.quiz.A2||[]).map(function(q){return q.type;}).join(",");
  out.typesB1=(state.quiz.B1||[]).map(function(q){return q.type;}).join(",");
  out.optsOk=out.quizLevels.every(function(k){ return (state.quiz[k]||[]).every(function(q){
    return Array.isArray(q.options)&&q.options.length>=2&&typeof q.answer==="number"&&q.answer>=0&&q.answer<q.options.length&&String(q.explain||"").length>0; }); });
  out.answersAllFirst=out.quizLevels.every(function(k){ return (state.quiz[k]||[]).every(function(q){ return q.answer===0; }); });

  /* ⑥ 页面巡检：生成后每一页都不能空白 */
  const probePage=async function(idx){
    go(idx); await sleep(400);
    const w=document.querySelector("#stage .wrap");
    const t=w?w.textContent.replace(/\\s+/g," ").trim():"";
    return { idx:idx, len:t.length, head:t.slice(0,70) };
  };
  out.page7=await probePage(7);
  out.page8=await probePage(8);
  out.page9=await probePage(9);
  out.page10=await probePage(10);
  out.page11=await probePage(11);
  out.page8Note = out.page8.head.indexOf("不做质量校验")>=0 || out.page8.head.indexOf("本链路")>=0;

  /* ⑦ 产线约束不得泄漏进 lite（Bryan 2026-09-23：极简版「分级标准 / 检验标准 / 字数约束都不需要有」）。
     判据全部落在 **真实渲染出来的 DOM** 上 —— 不读代码、不读内存标记，避免「代码看着对、页面还是错」。 */
  const domOn=async function(idx, wait){
    go(idx); await sleep(wait||450);
    const q=function(s){ return document.querySelectorAll(s).length; };
    const tx=function(s){ const e=document.querySelector(s); return e?e.textContent.replace(/\\s+/g," ").trim():""; };
    return {
      stylebar:q("#stage .stylebar"), factused:q("#stage .factused"),
      bigtabs:q("#stage .bigtab"), gentabs:q("#stage .gentab"),
      b2pcards:q('#stage .aligngrid .pcard[data-k="B2"]'),
      alignmode:tx("#stage .alignmode"), qhint:tx("#stage .qalign-hint"),
      pills:q("#stage .plvl-pill"), paneh:tx("#stage .pane-h"),
      side:Array.prototype.slice.call(document.querySelectorAll("#stage .genside .metric .k")).map(function(e){return e.textContent.trim();}).join(" | "),
      m0:tx("#stage #m0"),
    };
  };
  /* ⚠️ 页面索引与步骤号不同名（fns=[s0,s1,s2,s3,sMaterialBank,s4,s5,s6,s7,s9,s12,sArticleBank]）：
     内容生成 = 7，AI 校验 = 8，段落校对 = 9，逐段审核 = 10，文章库 = 11。
     第一版把「审核」当成 11、又在内容生成页找档位条（那页只有 .gentab），两条断言取错了页面。 */
  out.pg7=await domOn(7, 3400);   /* 第 1 格指标由打字机在渲染后 1–3s 才填，等足 */
  out.pg9=await domOn(9);
  out.pg10=await domOn(10);
  out.pg11=await domOn(11);
  /* 负向对照：同一个 helper 在「非 lite」入口必须**仍给 4 档** ——
     证明收敛按链路判、不是把 3 写死了（否则以后产线页面会被一起砍成 3 档）。 */
  const _r=state.route; state.route="licensed";
  out.ctrlShownKeys=(typeof shownKeys==="function")?shownKeys().length:-1;
  out.ctrlBigBarB2=(typeof bigBarHTML==="function")?bigBarHTML().indexOf("B2")>=0:false;
  state.route=_r;
  go(7);

  out.consoleErrs=errs.slice(0,4);
  console.error=_ce;
  return JSON.stringify(out);
})()`;

async function main() {
  // 前置检查：静态服务必须活着，否则 Chrome 打开的是错误页，所有断言都无意义。
  // ⚠️ 只有本地 URL 才在 node 侧 fetch —— 沙箱直连 Railway 恒 000（不是站点挂了），
  //    线上跑法：URL_=https://web-production-2a16e.up.railway.app/ node tools/probe_lite_e2e.mjs
  //    远端交给自己这一侧（Chrome 走系统网络 + 下面第 231 行的密钥检查）兜住。
  const isLocal = /^https?:\/\/(127\.0\.0\.1|localhost)(:|\/)/.test(URL_);
  if (isLocal) {
    try {
      const r = await fetch(URL_);
      if (!r.ok) throw new Error('HTTP ' + r.status);
    } catch (e) {
      console.error(`✗ 打不开 ${URL_}（${e.message}）——先在 frontend/ 下起静态服务：\n` +
        `  python3 -m http.server 8899 --bind 127.0.0.1`);
      process.exit(1);
    }
  } else {
    console.log(`[前置] 远端 URL，跳过 node 侧联网检查（沙箱到 Railway 恒 000，非站点故障）`);
  }

  const chrome = await ensureChrome();
  const tab = await (await fetch(`${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  let id = 0; const pending = new Map();
  ws.addEventListener('message', ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
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

  // 先单调确认密钥已注入 —— 否则整个探针在测一个「必然失败」的场景
  const cfg = await evaluate(`JSON.stringify({cfg:!!(window.WB_CFG&&window.WB_CFG.DIFY_WF_LITE), src:(document.querySelector('script[src="config.local.js"]')?'tag':'inline')})`);
  console.log(`[前置] ${cfg}`);
  if (String(cfg).indexOf('"cfg":true') < 0) {
    console.error('✗ 前端拿不到 DIFY_WF_LITE —— 检查 frontend/config.local.js 是否存在且含该键'); 
    ws.close(); if (chrome) chrome.kill(); process.exit(1);
  }

  console.log(`[运行] 真实调用图 C（母稿 ${MASTER.split('\n').length} 段 / ${MASTER.split(/\s+/).length} 词），最长等 240s …`);
  const raw = await evaluate(SETUP);
  if (typeof raw !== 'string' || raw.startsWith('ERR')) {
    console.error('探针执行失败:', raw); ws.close(); if (chrome) chrome.kill(); process.exit(1);
  }
  const o = JSON.parse(raw);

  let pass = 0, fail = 0;
  const ok = (name, cond, extra = '') => {
    if (cond) { pass++; console.log(`  ✓ ${name}`); }
    else { fail++; console.log(`  ✗ ${name}   ${extra}`); }
  };

  console.log(`\n耗时 ${o.elapsed}s  cur=${o.cur}  err=${o.err || '(无)'}`);

  console.log('\n[1] 前端到图 C 的链路');
  ok('config.local.js 已注入且含 DIFY_WF_LITE', o.hasCfg && o.liteKeySet, `keyTail=${o.liteKeyTail}`);
  ok('素材选择页有 5 个入口', o.cardCount === 5, `实际 ${o.cardCount}`);
  ok('第 5 个入口是「轻量提示词」', o.card5 === '轻量提示词', o.card5);
  ok('lite 面板渲染出来了', o.hasPanel);
  ok('粘贴后底部按钮可点', o.embarkClickable);
  ok('无错误（state.lic.err 为空）', !o.err, o.err);

  console.log('\n[2] 真实产出：三档文章');
  ok('生成后落在内容生成页 idx=7', o.cur === 7, `cur=${o.cur}`);
  ok('GEN 建了 A1 / A2 / B1 三档', JSON.stringify(o.genKeys) === JSON.stringify(['A1', 'A2', 'B1']), JSON.stringify(o.genKeys));
  ok('A1- 有段落', o.pA1 > 0, `pA1=${o.pA1}`);
  ok('A2 有段落', o.pA2 > 0, `pA2=${o.pA2}`);
  ok('B1 有段落', o.pB1 > 0, `pB1=${o.pB1}`);
  ok('三档段数一致（段落一一对应）', o.pA1 > 0 && o.pA1 === o.pA2 && o.pA2 === o.pB1, `A1=${o.pA1} A2=${o.pA2} B1=${o.pB1}`);
  ok('B1 入库的是用户粘贴的母稿原文', o.b1IsMaster, `首段标记「${MASTER_MARK.slice(0, 20)}」`);
  ok('B1 段数 = 粘贴的段数', o.b1ParaEqPaste, `${o.pB1} vs ${MASTER.split('\n').length}`);
  ok('A1 与 A2 内容不同（确实做了逐级简化）', o.a1a2Different);
  ok('A1 比 A2 短（简化方向正确）', o.a1Shorter, `A1=${o.wordsA1} A2=${o.wordsA2}`);
  console.log(`     字数：A1- ${o.wordsA1} 词 / A2 ${o.wordsA2} 词 / B1 ${o.wordsB1} 词（参考靶心 A1- 150 / A2 240 / B1 380）`);
  console.log(`     平均句长：A1- ${o.wpsA1} / A2 ${o.wpsA2} / B1 ${o.wpsB1} 词/句（参考 A1- 6–9 / A2 10–13 / B1 14–17）`);

  console.log('\n[3] 真实产出：题目');
  ok('quiz 三档都在', JSON.stringify(o.quizLevels) === JSON.stringify(['A1', 'A2', 'B1']), JSON.stringify(o.quizLevels));
  ok('三档各 3 题', JSON.stringify(o.quizCounts) === JSON.stringify(['A1:3', 'A2:3', 'B1:3']), JSON.stringify(o.quizCounts));
  ok('A1- 配额 = 语言2 + 文本1', o.typesA1 === 'language,language,text', o.typesA1);
  ok('A2 配额 = 语言1 + 文本1 + 逻辑1', o.typesA2 === 'language,text,logic', o.typesA2);
  ok('B1 配额 = 文本1 + 逻辑1 + 认知1', o.typesB1 === 'text,logic,cognitive', o.typesB1);
  ok('每题都有 4 选项 / 合法 answer / 中文解析', o.optsOk);
  console.log(`     观察（非断言）：正确答案是否全落 0 号位 = ${o.answersAllFirst}`);

  console.log('\n[4] 后续页面非空白');
  ok('idx 7 内容生成页有内容', o.page7.len > 200, `len=${o.page7.len}`);
  ok('idx 8 校验页有内容', o.page8.len > 80, `len=${o.page8.len}`);
  ok('idx 8 明确写了「本链路不做质量校验」', o.page8Note, o.page8.head);
  ok('idx 9 分段页有内容', o.page9.len > 100, `len=${o.page9.len}`);
  ok('idx 10 / 11 有内容', o.page10.len > 60 && o.page11.len > 60, `10=${o.page10.len} 11=${o.page11.len}`);
  ok('无 console.error 异常', o.consoleErrs.length === 0, JSON.stringify(o.consoleErrs));

  console.log('\n[5] 产线约束未泄漏进 lite（分级标准 / 校验标准 / 字数靶心）');
  ok('idx 7 无「写作风格」条（点它会触发产线主链路）', o.pg7.stylebar === 0, `stylebar=${o.pg7.stylebar}`);
  ok('idx 7 无「事实卡引用」面板（lite 不抽事实）', o.pg7.factused === 0, `factused=${o.pg7.factused}`);
  ok('idx 7 侧栏不提「AI 校验得分」', o.pg7.side.indexOf('AI 校验') < 0, o.pg7.side);
  ok('idx 7 侧栏不提「蓝思 / 目标 x–y 词」', o.pg7.side.indexOf('蓝思') < 0 && o.pg7.side.indexOf('目标') < 0, o.pg7.side);
  ok('idx 7 第 1 格显示段数（不是校验的「—」）', /段/.test(o.pg7.m0), o.pg7.m0);
  ok('idx 7 档位页签只有 3 个（无空 B2+）', o.pg7.gentabs === 3, `gentab=${o.pg7.gentabs}`);
  ok('idx 9 档位条只有 3 档（无空 B2+ tab）', o.pg9.bigtabs === 3, `bigtab=${o.pg9.bigtabs}`);
  ok('idx 9 对齐网格无 B2+ 空列', o.pg9.b2pcards === 0, `B2 pcard=${o.pg9.b2pcards}`);
  ok('idx 9 视图条写「3 档对照」', o.pg9.alignmode.indexOf('3 档对照') >= 0, o.pg9.alignmode);
  ok('idx 9 题目区写「3 档练习题」', o.pg9.qhint.indexOf('3 档练习题') >= 0, o.pg9.qhint);
  ok('idx 9 题目档位 pill 只有 3 个', o.pg9.pills === 3, `pills=${o.pg9.pills}`);
  ok('idx 10 审核页档位条 3 档 + 标题写「3 档对齐」',
     o.pg10.bigtabs === 3 && o.pg10.paneh.indexOf('3 档对齐') >= 0,
     `bigtab=${o.pg10.bigtabs} paneh=${o.pg10.paneh}`);
  ok('负向对照：非 lite 链路仍给 4 档', o.ctrlShownKeys === 4 && o.ctrlBigBarB2,
     `shownKeys=${o.ctrlShownKeys} bigBarHasB2=${o.ctrlBigBarB2}`);

  console.log(`\n${pass}/${pass + fail} 项通过`);
  if (o.stillRunningAt80s) console.log('（注：80s 时仍在跑）');
  ws.close(); if (chrome) chrome.kill();
  process.exit(fail ? 1 : 0);
}

main();
