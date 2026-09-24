// lite 骨架链路 · 真模型端到端探针 —— 2026-09-24
//
// 为什么需要它：probe_lite_skeleton.mjs 用 stub 验的是**前端逻辑**（面板/交互/请求体/回炉分支），
// 验不了「真模型拿到骨架后到底会不会对齐」。这个脚本走**真 Dify**（借真实 Chrome 的 CDP 通道，
// 沙箱直连 api.dify.ai 不可靠），把前端**逐字同一个请求体**发出去：
//
//   图A(licprep, need_simplify=false) → 骨架 → 拼【段落骨架】进 master_text → 图C(lite) → 量段数
//
// 判定：A1- / A2 / B1 段数是否 == 骨架段数；逐段词数是否落进该档区间
//      （A1- 11–14 / A2 20–22，真源 = 图B nodeValidate 的 PER 表）。
// 不齐时**复刻前端的回炉**（同一段 liteFixBlock 文案，上限 2 次），量回炉后是否收敛。
//
// 用法：
//   node tools/probe_lite_skel_e2e.mjs [--material=/tmp/material_growing.txt] [--title="Growing Lesson"]
//                                      [--rounds=1] [--cdp=9243] [--out=/tmp/lite_skel_e2e]
import fs from 'node:fs';
import { makeCtx } from './dify_console.mjs';
import { runWorkflowWith } from './dify_run_wf.mjs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => { const h = argv.find(a => a.startsWith(`--${k}=`)); return h ? h.slice(k.length + 3) : d; };

const MATERIAL = arg('material', '/tmp/material_growing.txt');
const TITLE = arg('title', 'Growing Lesson');
const OUT = arg('out', '/tmp/lite_skel_e2e');
const ROUNDS = Number(arg('rounds', 1));          // 独立重复几次（每次都是一条完整链路）
/* 与前端 AIWF_LICPREP / AIWF_LITE 同一个 App（键值来自 tools/ 既有常量，与 frontend/config.local.js 同源） */
const KEY_A = arg('a_key', 'app-R8iH0PGSdeCRIaS72sYZSqnT');     // 图A 母稿预处理
const KEY_LITE = arg('lite_key', 'app-qBLp2R8g0IuEsg40TUrpR6IF'); // 图C 轻量提示词

const PER = { A1: [11, 14], A2: [20, 22] };      // 逐段词数区间（A1- / A2）
const nwords = t => (String(t || '').match(/[A-Za-z0-9'-]+/g) || []).length;
const parseJsonLoose = s => {
  const t = String(s || '').replace(/^\s*```(?:json)?\s*/i, '').replace(/\s*```\s*$/, '').trim();
  try { return JSON.parse(t); } catch (e) { }
  const i = t.indexOf('{'), j = t.lastIndexOf('}');
  if (i >= 0 && j > i) { try { return JSON.parse(t.slice(i, j + 1)); } catch (e) { } }
  return null;
};
/* ★ 与前端 liteRun() 逐字同一段拼装逻辑 —— 改了前端必须同步改这里，否则本探针就失去意义 */
function skelBlock(segs) {
  const N = segs.length;
  if (!N) return '';
  return '【段落骨架】下面是母稿按大意切好的 ' + N + ' 段（每段一行）。\n'
    + '你改写时必须严格沿用这 ' + N + ' 段：段数必须正好 ' + N + ' 段，'
    + '第 i 段只讲骨架第 i 段的事，不得合并、不得拆分、不得调换顺序。\n\n'
    + segs.map((s, i) => (i + 1) + '. ' + s).join('\n') + '\n\n'
    + '【逐段篇幅】A1- 每段 ' + PER.A1[0] + '–' + PER.A1[1] + ' 词；A2 每段 '
    + PER.A2[0] + '–' + PER.A2[1] + ' 词。按段分别控制，不卡全文字数。\n\n';
}
function fixBlock(paras, wantN) {
  const out = ['【你上一轮的产出不合格，请整篇重做】'];
  [['A1', 'A1-'], ['A2', 'A2']].forEach(([k, disp]) => {
    const arr = (paras && paras[k]) || [];
    if (arr.length !== wantN) out.push('- ' + disp + ' 段数：现在是 ' + arr.length + ' 段，必须正好 ' + wantN + ' 段。');
  });
  out.push('重新按【段落骨架】逐段改写：段数必须与骨架相同，第 i 段只讲骨架第 i 段的事，不得合并、不得拆分、不得调换顺序。');
  out.push('输出与上次**完全相同的 JSON 结构**（A1- 与 A2 两篇 + A1-/A2/B1 各 3 道题）。');
  return out.join('\n');
}
const BUDGET = 20000;
function buildInput(segs, text, extra) {
  const head = (extra ? extra + '\n\n' : '') + skelBlock(segs);
  if (head.length >= BUDGET) return head.slice(0, BUDGET + 2000);
  return head + text.slice(0, BUDGET - head.length);
}

async function callWf(ctx, appKey, inputs, retries = 3) {
  let last;
  for (let i = 0; i < retries; i++) {
    try {
      const r = await runWorkflowWith(ctx, { appKey, inputs, user: 'readpal-lite-skel-e2e' });
      const d = r && r.data;
      if (d && /failed|error/i.test(String(d.status || ''))) { last = new Error('wf status=' + d.status); await new Promise(s => setTimeout(s, 1500)); continue; }
      if (d && d.data && d.data.outputs) return d.data.outputs;
      last = new Error('no outputs: ' + JSON.stringify(d || r).slice(0, 180));
    } catch (e) { last = e; }
    await new Promise(s => setTimeout(s, 1500));
  }
  throw last;
}

const text = fs.readFileSync(MATERIAL, 'utf-8').trim();
const masterParas = text.split(/\n\s*\n/).map(s => s.trim()).filter(Boolean);
console.log(`母稿：${masterParas.length} 段 / ${nwords(text)} 词  (${MATERIAL})\n`);

const ctx = await makeCtx(process.env.DIFY_CDP_PORT || String(arg('cdp', '9243')));
const summary = [];

try {
  for (let rd = 1; rd <= ROUNDS; rd++) {
    console.log(`════ 第 ${rd} 条链路 ════`);
    /* ① 图A 定骨架 */
    const tA = Date.now();
    const oa = await callWf(ctx, KEY_A, {
      material: text.slice(0, 20000), level: 'B1', need_simplify: 'false', title: TITLE,
    });
    const segs = parseJsonLoose(oa.segments_json);
    const skelMs = Date.now() - tA;
    if (!Array.isArray(segs) || !segs.length) {
      console.log(`   ✗ 图A 没给骨架（${(skelMs / 1000).toFixed(1)}s）：${JSON.stringify(oa).slice(0, 200)}\n`);
      summary.push({ rd, skelMs, skel: null });
      continue;
    }
    /* 逐字保留判定：按**词位**比对（拼接后比字符串会被换行/空格差异骗到 —— 图A 会把母稿
       的 9 个空行段细切成 11 段，拼接结果自然不同）。词位一致率 = 100% 才算逐字保留。 */
    const toksA = (segs.join(' ').match(/[A-Za-z0-9'’\-]+/g) || []).map(w => w.toLowerCase());
    const toksB = (text.match(/[A-Za-z0-9'’\-]+/g) || []).map(w => w.toLowerCase());
    let same = 0;
    for (let i = 0; i < Math.min(toksA.length, toksB.length); i++) if (toksA[i] === toksB[i]) same++;
    const verbatimRate = toksB.length ? Math.round(same / toksB.length * 1000) / 10 : 0;
    const skelVerbatim = verbatimRate === 100;
    console.log(`   ① 图A 骨架：${segs.length} 段 / ${nwords(segs.join(' '))} 词（母稿 ${nwords(text)} 词）· 逐词一致率 ${verbatimRate}% · ${(skelMs / 1000).toFixed(1)}s`);
    fs.writeFileSync(`${OUT}.skeleton.json`, JSON.stringify(segs, null, 1), 'utf-8');

    /* ② 图C 生成 + 段数校验回炉（复刻前端） */
    let tries = 0, ok = false, lastParas = null, lastBad = '';
    const calls = [];
    for (let attempt = 0; attempt < 3; attempt++) {
      tries = attempt + 1;
      const input = buildInput(segs, text, attempt ? fixBlock(lastParas, segs.length) : '');
      const t0 = Date.now();
      const o = await callWf(ctx, KEY_LITE, { master_text: input, title_in: TITLE.slice(0, 300), level: 'B1' });
      const ms = Date.now() - t0;
      let P = null;
      if (String(o.parse_ok || '') === 'true') P = parseJsonLoose(o.paras_json);
      calls.push({ attempt: tries, ms, parseOk: String(o.parse_ok || ''), warn: String(o.parse_warn || '').slice(0, 120) });
      if (!P) { lastBad = '输出不是合法 JSON'; console.log(`   ② 第 ${tries} 次（${(ms / 1000).toFixed(1)}s）解析失败：${String(o.parse_warn || '').slice(0, 120)}`); continue; }
      lastParas = P;
      const got = ['A1', 'A2'].map(k => `${k}=${(P[k] || []).length}`);
      const bad = ['A1', 'A2'].filter(k => ((P[k] || []).length !== segs.length));
      console.log(`   ② 第 ${tries} 次（${(ms / 1000).toFixed(1)}s）段数 ${got.join(' ')} / 骨架 ${segs.length} 段 → ${bad.length ? '不齐，回炉' : '齐'}`);
      if (!bad.length) { ok = true; break; }
      lastBad = '段数不齐：' + bad.map(k => `${k === 'A1' ? 'A1-' : k} ${(P[k] || []).length}/${segs.length}`).join('、');
    }
    if (!lastParas) { summary.push({ rd, skel: segs.length, aligned: false, note: '无合法产出' }); continue; }

    const perPara = {};
    ['A1', 'A2'].forEach(k => { perPara[k] = (lastParas[k] || []).map(nwords); });
    const inBand = {};
    ['A1', 'A2'].forEach(k => {
      const [lo, hi] = PER[k];
      inBand[k] = perPara[k].length ? perPara[k].filter(n => n >= lo && n <= hi).length + '/' + perPara[k].length : '0/0';
    });
    const b1 = segs.length;
    console.log(`   ③ 段数：A1- ${(lastParas.A1 || []).length} / A2 ${(lastParas.A2 || []).length} / B1 ${b1}（骨架 ${segs.length}）→ ${ok ? '✅ 对齐' : '✗ ' + lastBad}`);
    console.log(`   ④ 逐段词数落带：A1- ${inBand.A1}（11–14）· A2 ${inBand.A2}（20–22）`);
    console.log(`      A1- 逐段 [${perPara.A1.join(',')}]`);
    console.log(`      A2  逐段 [${perPara.A2.join(',')}]\n`);
    summary.push({ rd, skelMs, skel: segs.length, skelVerbatim, verbatimRate, tries, aligned: ok, lastBad,
                   paras: { A1: (lastParas.A1 || []).length, A2: (lastParas.A2 || []).length, B1: b1 },
                   inBand, perPara, calls, articles: { A1: lastParas.A1, A2: lastParas.A2 } });
  }
} finally {
  fs.writeFileSync(`${OUT}.summary.json`, JSON.stringify(summary, null, 1), 'utf-8');
  console.log(`[产物] ${OUT}.summary.json / ${OUT}.skeleton.json`);
  console.log(`[对齐率] ${summary.filter(s => s.aligned).length}/${summary.length}`);
  ctx.close();
}
