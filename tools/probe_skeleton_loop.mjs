// ReadPal · 「骨架锁定 + 轻提示词生成 + 严格事实检 + 回炉」探针 v2
//
// 与 v1（probe_lite_loop.mjs）的差别 —— 按 Bryan 2026-09-24 的新判定标准：
//   ① 段落骨架**先定**（复用图A nodeSegment：按大意切、逐字保留原文、段数 10–15）
//   ② 生成端按骨架**逐段对应**改写（第 i 段 = 骨架第 i 段的事，段数必须一致）
//   ③ 字数只看**逐段**（A1- 11–14 词/段，A2 20–22 词/段），不卡全文字数
//   ④ 事实检仍用「事实检查」图（DeepSeek Pro），参照物换成骨架逐段
//
// 链路：
//   图A(定骨架, 缓存) → 图C(轻提示词生成) → 代码闸门(段数+逐段词数) + 事实检 → 拼反馈 → 回炉
//
// 用法：
//   DIFY_CDP_PORT=9243 node tools/probe_skeleton_loop.mjs [--rounds=3] [--material=path]
//     [--skel=/tmp/skel.json] [--out=/tmp/skel_loop] [--reuse-skel]
//
// 产物：<out>.round{N}.json、<out>.summary.json、<skel>
import fs from 'node:fs';
import path from 'node:path';
import { makeCtx } from './dify_console.mjs';
import { runWorkflowWith } from './dify_run_wf.mjs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => { const h = argv.find(a => a.startsWith(`--${k}=`)); return h ? h.slice(k.length + 3) : d; };
const flag = (k) => argv.includes(`--${k}`);

const HERE = '/Users/jinsongli/WorkBuddy/2026-09-10-10-51-04/readpal';
const KEY_GEN = arg('gen_key', 'app-qBLp2R8g0IuEsg40TUrpR6IF');   // 图C 轻量提示词（luna）
const KEY_CHK = arg('chk_key', 'app-pwuyZh2e2VP48h9pjNCo1ylx');   // 事实检查（DeepSeek Pro）
const KEY_A = arg('a_key', 'app-R8iH0PGSdeCRIaS72sYZSqnT');       // 图A 母稿预处理（定骨架）

const ROUNDS = Number(arg('rounds', 3));
const OUT = arg('out', '/tmp/skel_loop');
const MATERIAL = arg('material', path.join(HERE, 'tools/beat_experiment/material_food_mood.txt'));
const SKEL = arg('skel', '/tmp/skel_food_mood.json');
const TITLE = arg('title', 'Food and mood');
const MASTER_LEVEL = arg('master_level', 'B1');   // 母稿档位（决定骨架每段词数：B1 28–35）

// 逐段规格（真源 = 图B nodeValidate 的 PER 表）；本实验只测 A1- / A2
const PER = { A1: [11, 14], A2: [20, 22] };
const SENT = { A1: [6, 9], A2: [10, 13] };
const SEG_MIN = 10, SEG_MAX = 15;

// ── 工具 ────────────────────────────────────────────────────────────────────
const stripFence = (s) => String(s || '').replace(/^\s*```(?:json)?\s*/i, '').replace(/\s*```\s*$/, '').trim();
function parseJsonLoose(s) {
  const t = stripFence(s);
  try { return JSON.parse(t); } catch (e) { }
  const fixed = t.replace(/,\s*([}\]])/g, '$1');
  try { return JSON.parse(fixed); } catch (e) { }
  const i = t.indexOf('{'), j = t.lastIndexOf('}');
  if (i >= 0 && j > i) { try { return JSON.parse(t.slice(i, j + 1).replace(/,\s*([}\]])/g, '$1')); } catch (e) { } }
  return null;
}
const nwords = (t) => (String(t || '').match(/[A-Za-z0-9'-]+/g) || []).length;
function metrics(paras) {
  const txt = paras.join(' ');
  const sents = txt.split(/[.!?]+/).map(s => s.trim()).filter(Boolean);
  const lens = sents.map(s => nwords(s));
  const avg = lens.length ? lens.reduce((a, b) => a + b, 0) / lens.length : 0;
  return {
    paras: paras.length, words: nwords(txt), sentAvg: Math.round(avg * 10) / 10,
    perPara: paras.map(p => nwords(p)),
  };
}

async function callWf(ctx, { appKey, inputs, tag, retries = 3 }) {
  let last;
  for (let i = 0; i < retries; i++) {
    try {
      const r = await runWorkflowWith(ctx, { appKey, inputs, user: 'readpal-skel-loop' });
      return (r.data.data || {}).outputs || {};
    } catch (e) {
      last = e;
      console.log(`   ⚠️ ${tag} 失败（${i + 1}/${retries}）：${String(e.message).slice(0, 110)}`);
      if (e.http === 502 || e.http === 504 || e.http === -1) { await new Promise(r => setTimeout(r, 5000)); continue; }
      throw e;
    }
  }
  throw last;
}

// ── 阶段一：定骨架（图A，带缓存）────────────────────────────────────────────
const masterRaw = fs.readFileSync(MATERIAL, 'utf-8').trim();
const MP = masterRaw.split(/\n+/).map(s => s.trim()).filter(Boolean);
console.log(`[母稿] ${path.basename(MATERIAL)} | 自然段 ${MP.length} | ${nwords(masterRaw)} 词`);

const ctx = await makeCtx();
console.log(`[attach] ${ctx.info}`);
console.log(`[refresh] ${await ctx.refresh()}`);

let skeleton = null;
if (flag('reuse-skel') && fs.existsSync(SKEL)) {
  skeleton = JSON.parse(fs.readFileSync(SKEL, 'utf-8'));
  console.log(`[骨架] 复用缓存 ${SKEL}（${skeleton.segs.length} 段）`);
} else {
  console.log(`[骨架] 调图A 分段中（母稿档 ${MASTER_LEVEL}）…`);
  const t0 = Date.now();
  const o = await callWf(ctx, {
    appKey: KEY_A, tag: '图A',
    inputs: { material: masterRaw, title: TITLE, level: MASTER_LEVEL, need_simplify: 'false', style: 'default' },
  });
  const segs = parseJsonLoose(o.segments_json) || [];
  // 逐词保真自检：骨架拼接必须与原文字词完全一致
  const a = (masterRaw.match(/[A-Za-z0-9'-]+/g) || []);
  const b = (segs.join(' ').match(/[A-Za-z0-9'-]+/g) || []);
  skeleton = {
    source: MATERIAL, level: MASTER_LEVEL, segs,
    seg_count: segs.length,
    per_para_words: segs.map(nwords),
    verbatim_ok: JSON.stringify(a) === JSON.stringify(b),
    word_count: a.length,
    warn: o.warn || '', ms: Date.now() - t0,
  };
  fs.writeFileSync(SKEL, JSON.stringify(skeleton, null, 1), 'utf-8');
  console.log(`[骨架] ${segs.length} 段 / 每段词数 ${skeleton.per_para_words.join(',')} / 逐词一致=${skeleton.verbatim_ok} / ${(skeleton.ms / 1000).toFixed(1)}s`);
  if (skeleton.warn) console.log(`[骨架 warn] ${skeleton.warn}`);
}
const SEGS = skeleton.segs;
const SEGN = SEGS.length;
if (SEGN < SEG_MIN || SEGN > SEG_MAX) console.log(`  ⚠️ 骨架段数 ${SEGN} 不在 ${SEG_MIN}–${SEG_MAX} 内`);

// ── 生成输入拼装 ────────────────────────────────────────────────────────────
const skelBlock = SEGS.map((s, i) => `${i + 1}. ${s}`).join('\n');

function buildInput(feedback) {
  return [
    `【标题】${TITLE}`,
    '',
    '【母稿正文】',
    masterRaw,
    '',
    `【段落骨架】下面是母稿按大意切好的 ${SEGN} 段（每段一行）。`,
    `你改写时必须**严格沿用这 ${SEGN} 段**：段数必须正好 ${SEGN} 段，第 i 段只讲骨架第 i 段的事，不得合并、不得拆分、不得调换顺序。`,
    skelBlock,
    '',
    `【逐段篇幅】A1- 每段 ${PER.A1[0]}–${PER.A1[1]} 词；A2 每段 ${PER.A2[0]}–${PER.A2[1]} 词。按段分别控制，不卡全文字数。`,
    feedback || '',
  ].join('\n');
}

function buildFeedback(round, prev, checks, met) {
  const L = [];
  L.push('');
  L.push('———————————');
  L.push(`【对话记录 · 第 ${round} 轮】你上一轮的产出被审校退回。请**只改被指出的地方**，其余段落保持上一轮的处理方式。`);
  L.push('');
  L.push(`【你上一轮的产出（逐段，共 ${SEGN} 段应为基准）】`);
  for (const lv of ['A1', 'A2']) {
    L.push('');
    L.push(`— 上一轮 ${lv === 'A1' ? 'A1-' : 'A2'}（${(prev.paras[lv] || []).length} 段）—`);
    (prev.paras[lv] || []).forEach((p, i) => L.push(`${i + 1}. [${nwords(p)}词] ${p}`));
  }
  L.push('');
  L.push('【必须修正的硬指标】');
  for (const lv of ['A1', 'A2']) {
    const name = lv === 'A1' ? 'A1-' : 'A2';
    const p = prev.paras[lv] || [];
    if (p.length !== SEGN) L.push(`- ${name} 段数：现在 ${p.length} 段，**必须正好 ${SEGN} 段**（与骨架逐段对应）。`);
    const bad = [];
    for (let i = 0; i < Math.min(p.length, SEGN); i++) {
      const w = nwords(p[i]);
      if (w < PER[lv][0] || w > PER[lv][1]) {
        const d = w > PER[lv][1] ? `删 ${w - PER[lv][1]} 词` : `补 ${PER[lv][0] - w} 词`;
        bad.push(`第 ${i + 1} 段 ${w} 词→需 ${PER[lv][0]}–${PER[lv][1]} 词（${d}）`);
      }
    }
    L.push(`- ${name} 逐段词数（${PER[lv][0]}–${PER[lv][1]} 词/段）：${bad.length ? bad.join('；') : '全部达标（保持）'}`);
    const s = met[lv].sentAvg;
    L.push(`- ${name} 句子长度：句均 ${s} 词（参考区间 ${SENT[lv][0]}–${SENT[lv][1]}）。${s > SENT[lv][1] ? '偏长，请拆短句。' : (s < SENT[lv][0] ? '偏短，可合并短句。' : '达标。')}`);
  }
  L.push('');
  L.push('⚠️ 压缩只能动「语言和细节铺陈」：把从句拆成简单句、删掉修饰与举例、用更短的表达。');
  L.push('**不许删掉母稿的事实**：数字、专名（人名/地名/机构名）、主题词必须保留。');
  L.push('每段讲的那件事不能换 —— 骨架第 i 段讲什么，改写稿第 i 段就讲什么。');
  L.push('');
  L.push('【事实与语义审校意见】');
  let n = 0;
  for (const lv of ['A1', 'A2']) {
    const c = checks[lv];
    if (!c || !c.parsed || !Array.isArray(c.parsed.issues)) continue;
    for (const it of c.parsed.issues) {
      n++;
      L.push(`- ${lv === 'A1' ? 'A1-' : 'A2'} 第 ${it.para} 段（${it.type}）：${it.detail}`);
    }
  }
  if (!n) L.push('- 事实与语义无问题（保持）');
  L.push('');
  L.push(`仍然按前面的要求输出 JSON：A1- 与 A2 两篇，各正好 ${SEGN} 段，并为 A1-、A2、B1 三档各出 3 道题。`);
  return L.join('\n');
}

// ── 主循环 ──────────────────────────────────────────────────────────────────
console.log(`[设置] 生成=图C轻量提示词(luna) | 检查=DeepSeek Pro | 骨架 ${SEGN} 段 | 最多 ${ROUNDS} 轮\n`);
const rounds = [];
let feedback = '';
let convergedAt = null;

for (let rd = 1; rd <= ROUNDS; rd++) {
  console.log(`━━━ 第 ${rd} 轮 ━━━`);
  const input = buildInput(feedback);
  // 🔴 luna 偶发输出非法 JSON（实测 1/3~1/4），这不是内容问题而是格式问题
  //    ⇒ 同一输入重试，不计入回炉轮次（否则会把「格式抖动」误算成「模型改不好」）
  let outs = null, genMs = 0;
  for (let att = 1; att <= 3; att++) {
    const t0 = Date.now();
    outs = await callWf(ctx, { appKey: KEY_GEN, tag: '图C', inputs: { master_text: input, title_in: TITLE, level: MASTER_LEVEL } });
    genMs = Date.now() - t0;
    if (String(outs.parse_ok) === 'true') break;
    console.log(`   ⚠️ 第 ${rd} 轮第 ${att} 次产出 JSON 非法（${String(outs.parse_warn || '').slice(0, 80)}），重试`);
    if (att === 3) break;
    await new Promise(r => setTimeout(r, 2000));
  }
  const articles = parseJsonLoose(outs.articles_json) || {};
  const paras = parseJsonLoose(outs.paras_json) || {};
  const quiz = parseJsonLoose(outs.quiz_json) || {};
  console.log(`  生成 ${(genMs / 1000).toFixed(0)}s | parse_ok=${outs.parse_ok} | warn=${String(outs.parse_warn || '').slice(0, 70)}`);

  const met = {}, gateOk = {};
  for (const lv of ['A1', 'A2']) {
    const p = paras[lv] || [];
    met[lv] = metrics(p);
    const okP = p.length === SEGN;
    const out = [];
    for (let i = 0; i < p.length; i++) {
      const w = nwords(p[i]);
      if (w < PER[lv][0] || w > PER[lv][1]) out.push(`${i + 1}:${w}`);
    }
    gateOk[lv] = okP && out.length === 0;
    console.log(`  ${lv}: ${p.length}段${okP ? ' ✅' : ` ❌(需${SEGN})`} | ${met[lv].words}词 | 句均${met[lv].sentAvg} | 段词数[${met[lv].perPara.join(',')}]`);
    if (out.length) console.log(`      越界段(需${PER[lv][0]}-${PER[lv][1]}): ${out.join(' ')}`);
  }

  // 事实检：参照物 = 骨架逐段
  const skelForCheck = SEGS.map((s, i) => `${i + 1}. ${s}`).join('\n');
  const checks = {};
  for (const lv of ['A1', 'A2']) {
    const o = await callWf(ctx, {
      appKey: KEY_CHK, tag: `检${lv}`,
      inputs: { master_text: skelForCheck, candidate: (paras[lv] || []).map((p, i) => `${i + 1}. ${p}`).join('\n'), level: lv === 'A1' ? 'A1-' : 'A2' },
    });
    const parsed = parseJsonLoose(o.raw);
    checks[lv] = { raw: o.raw, parsed };
    const iss = (parsed && parsed.issues) || [];
    console.log(`  检 ${lv}: ${parsed ? parsed.verdict : '解析失败'} | ${iss.length} 条`);
    for (const it of iss) console.log(`      · 第${it.para}段 [${it.type}] ${String(it.detail).slice(0, 88)}`);
  }

  const factIssues = ['A1', 'A2'].reduce((a, lv) => a + (((checks[lv].parsed || {}).issues || []).length), 0);
  const mechPass = gateOk.A1 && gateOk.A2;
  const verdict = { mech: gateOk, mechPass, factPass: factIssues === 0, factIssues, pass: mechPass && factIssues === 0 };

  fs.writeFileSync(`${OUT}.round${rd}.json`, JSON.stringify({
    round: rd, genMs, inputUsed: input, articles, paras, quiz, metrics: met, verdict,
    checks: { A1: checks.A1.parsed, A2: checks.A2.parsed }, rawChecks: { A1: checks.A1.raw, A2: checks.A2.raw },
  }, null, 1), 'utf-8');

  rounds.push({ round: rd, genMs, metrics: met, gate: gateOk, issues: factIssues, pass: verdict.pass });

  if (verdict.pass) { convergedAt = rd; console.log(`  ✅ 第 ${rd} 轮收敛\n`); break; }
  console.log(`  判定：机械 ${mechPass ? '达标' : '不达标'} | 事实问题 ${factIssues} 条\n`);
  if (rd < ROUNDS) { feedback = buildFeedback(rd, { paras }, checks, met); }
}

fs.writeFileSync(`${OUT}.summary.json`, JSON.stringify({ material: MATERIAL, skeleton: SKEL, segCount: SEGN, rounds, convergedAt }, null, 1), 'utf-8');
console.log(`\n[收敛] ${convergedAt ? `第 ${convergedAt} 轮` : `${ROUNDS} 轮内未收敛`}`);
console.log(`[产物] ${OUT}.round*.json / ${OUT}.summary.json / ${SKEL}`);
ctx.close();
