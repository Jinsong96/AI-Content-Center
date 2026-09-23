// ReadPal · 「轻提示词生成 + 严格事实检 + 回炉」对话式循环探针
//
// 目的：验证 Bryan 提的路线 ——
//   生成端（GPT luna）提示词保持**极简**（就用图 C 那条已在对话模式验证过的提示词），
//   检查端（DeepSeek Pro）判据**写死从严**，查出的问题带回去重生成，直到过关。
//   等于把「对话模式里 Bryan 的角色」换成 DeepSeek。
//
// 链路：
//   图C(轻量提示词) → 本地机械指标(观测) → 检查图(DeepSeek Pro, 逐档) → 拼反馈 → 回炉
//
// 用法：
//   node tools/probe_lite_loop.mjs [--rounds=3] [--material=path] [--out=/tmp/lite_loop]
//
// 产物：<out>.round{N}.json（每轮原始产出 + 指标 + issues）、<out>.summary.json
import fs from 'node:fs';
import path from 'node:path';
import { makeCtx } from './dify_console.mjs';
import { runWorkflowWith } from './dify_run_wf.mjs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => { const h = argv.find(a => a.startsWith(`--${k}=`)); return h ? h.slice(k.length + 3) : d; };

const HERE = '/Users/jinsongli/WorkBuddy/2026-09-10-10-51-04/readpal';
const KEY_GEN = arg('gen_key', 'app-qBLp2R8g0IuEsg40TUrpR6IF');      // 图C 轻量提示词
const KEY_CHK = arg('chk_key', 'app-pwuyZh2e2VP48h9pjNCo1ylx');      // 事实检查图
const ROUNDS = Number(arg('rounds', 3));
const OUT = arg('out', '/tmp/lite_loop');
const MATERIAL = arg('material', path.join(HERE, 'tools/beat_experiment/material.txt'));

// 规格（只用于观测，不在本实验里拦截）；key 用产出里的档位字段名 A1/A2
const SPEC = { A1: { words: [128, 172], sent: [6, 9] }, A2: { words: [204, 276], sent: [10, 13] } };

const masterRaw = fs.readFileSync(MATERIAL, 'utf-8').trim();
const MP = masterRaw.split(/\n+/).map(s => s.trim()).filter(Boolean);   // 母稿逐段

// ── 工具函数 ────────────────────────────────────────────────────────────────
const stripFence = (s) => String(s || '').replace(/^\s*```(?:json)?\s*/i, '').replace(/\s*```\s*$/, '').trim();

function parseJsonLoose(s) {
  const t = stripFence(s);
  try { return JSON.parse(t); } catch (e) { }
  // 尾随逗号 / 裸换行兜底（与图 C nodeParse 同思路）
  const fixed = t.replace(/,\s*([}\]])/g, '$1');
  try { return JSON.parse(fixed); } catch (e) { }
  const i = t.indexOf('{'), j = t.lastIndexOf('}');
  if (i >= 0 && j > i) { try { return JSON.parse(t.slice(i, j + 1).replace(/,\s*([}\]])/g, '$1')); } catch (e) { } }
  return null;
}

function metrics(paras) {
  const txt = paras.join(' ');
  const words = txt.split(/\s+/).filter(Boolean).length;
  const sents = txt.split(/[.!?]+/).map(s => s.trim()).filter(Boolean);
  const lens = sents.map(s => s.split(/\s+/).filter(Boolean).length);
  const avg = lens.length ? lens.reduce((a, b) => a + b, 0) / lens.length : 0;
  return { paras: paras.length, words, sentCount: sents.length, sentAvg: Math.round(avg * 10) / 10 };
}

async function callGen(ctx, masterText, titleIn, level) {
  let lastErr;
  for (let i = 0; i < 3; i++) {
    try {
      return await runWorkflowWith(ctx, {
        appKey: KEY_GEN,
        inputs: { master_text: masterText, title_in: titleIn, level },
        user: 'readpal-lite-loop',
      });
    } catch (e) {
      lastErr = e;
      console.log(`   ⚠️ 生成失败（第 ${i + 1} 次）：${String(e.message).slice(0, 120)}`);
      if (e.http === 502 || e.http === 504 || e.http === -1) { await new Promise(r => setTimeout(r, 4000)); continue; }
      throw e;
    }
  }
  throw lastErr;
}

async function callCheck(ctx, masterText, candParas, level) {
  const r = await runWorkflowWith(ctx, {
    appKey: KEY_CHK,
    inputs: { master_text: masterText, candidate: candParas.join('\n'), level },
    user: 'readpal-lite-loop',
  });
  const raw = ((r.data.data || {}).outputs || {}).raw || '';
  const parsed = parseJsonLoose(raw);
  return { raw, parsed, ms: r.ms };
}

function buildFeedback(round, prev, checks, met) {
  const lines = [];
  lines.push('');
  lines.push('———————————');
  lines.push(`【对话记录 · 第 ${round} 轮】你上一轮的产出被审校退回，问题如下。请按意见重写。`);
  lines.push('');
  lines.push('【硬指标（必须达到，这是给读者的分级标准）】');
  const LV_TARGET = { A1: { name: 'A1-', w: 150, s: [6, 9] }, A2: { name: 'A2', w: 240, s: [10, 13] } };
  for (const lv of ['A1', 'A2']) {
    const m = met[lv], t = LV_TARGET[lv], sp = SPEC[lv];
    const diff = m.words - t.w;
    const wordNote = (m.words >= sp.words[0] && m.words <= sp.words[1])
      ? `达标（${m.words} 词）`
      : `**不达标**：现在 ${m.words} 词，要求 ${sp.words[0]}–${sp.words[1]} 词，请压到约 ${t.w} 词（${diff > 0 ? '删掉约 ' + diff + ' 词' : '补足约 ' + (-diff) + ' 词'}）`;
    const sentNote = (m.sentAvg >= sp.sent[0] && m.sentAvg <= sp.sent[1])
      ? `达标（句均 ${m.sentAvg} 词）`
      : `**不达标**：现在句均 ${m.sentAvg} 词，要求 ${sp.sent[0]}–${sp.sent[1]} 词，请把长句拆成短句`;
    lines.push(`- ${t.name} 篇幅：${wordNote}`);
    lines.push(`- ${t.name} 句子长度：${sentNote}`);
    if (m.paras !== MP.length) lines.push(`- ${t.name} 段数：现在 ${m.paras} 段，必须与母稿一致（${MP.length} 段）`);
  }
  lines.push('');
  lines.push('⚠️ 压缩只能动「语言和细节的铺陈」，**不许删掉母稿的事实**：数字、专名（人名/地名/机构名）、');
  lines.push('主题词必须保留。压缩手段是：把从句拆成简单句、删掉修饰和举例、用更短的表达。');
  lines.push('');
  lines.push('【你上一轮的产出（逐段）】');
  for (const lv of ['A1', 'A2']) {
    lines.push('');
    lines.push(`— 上一轮的 ${lv === 'A1' ? 'A1-' : 'A2'} —`);
    (prev.paras[lv] || []).forEach((p, i) => lines.push(`${i + 1}. ${p}`));
  }
  lines.push('');
  lines.push('【事实与语义审校意见】');
  let n = 0;
  for (const lv of ['A1', 'A2']) {
    const c = checks[lv];
    if (!c || !c.parsed || !Array.isArray(c.parsed.issues)) continue;
    for (const it of c.parsed.issues) {
      n++;
      const paraRef = lv === 'A1' ? 'A1-' : 'A2';
      lines.push(`- ${paraRef} 第 ${it.para} 段（${it.type}）：${it.detail}`);
    }
  }
  if (!n) lines.push('- 无（事实与语义全部通过，改写时保持）');
  lines.push('');
  lines.push('仍然按前面的要求输出 JSON：A1- 与 A2 两篇、段数与母稿一一对应、三档各 3 道题。');
  return lines.join('\n');
}

// ── 主循环 ──────────────────────────────────────────────────────────────────
const ctx = await makeCtx();
console.log(`[attach] ${ctx.info}`);
console.log(`[refresh] ${await ctx.refresh()}`);
console.log(`[母稿] ${MATERIAL} | ${MP.length} 段 / ${masterRaw.split(/\s+/).filter(Boolean).length} 词`);
console.log(`[设置] 生成=图C轻量提示词(luna) | 检查=DeepSeek Pro | 最多 ${ROUNDS} 轮\n`);

const rounds = [];
let masterText = masterRaw;
let feedback = '';
let convergedAt = null;

for (let rd = 1; rd <= ROUNDS; rd++) {
  console.log(`━━━ 第 ${rd} 轮 ━━━`);
  const t0 = Date.now();
  const gen = await callGen(ctx, masterText, '', 'B1');
  const outs = (gen.data.data || {}).outputs || {};
  const articles = parseJsonLoose(outs.articles_json) || {};
  const paras = parseJsonLoose(outs.paras_json) || {};
  const quiz = parseJsonLoose(outs.quiz_json) || {};
  const genMs = Date.now() - t0;
  console.log(`  生成 ${Math.round(genMs / 1000)}s | parse_ok=${outs.parse_ok} | warn=${String(outs.parse_warn || '').slice(0, 80)}`);

  const met = {};
  const mechOk = {};
  for (const lv of ['A1', 'A2']) {
    const p = paras[lv] || [];
    met[lv] = metrics(p);
    const sp = SPEC[lv];
    const okW = met[lv].words >= sp.words[0] && met[lv].words <= sp.words[1];
    const okS = met[lv].sentAvg >= sp.sent[0] && met[lv].sentAvg <= sp.sent[1];
    const okP = met[lv].paras === MP.length;
    mechOk[lv] = okW && okS && okP;
    console.log(`  ${lv}: ${met[lv].paras} 段${okP ? ' ✅' : ` ❌(需${MP.length})`} / ${met[lv].words} 词(区间${sp.words.join('-')}${okW ? ' ✅' : ' ❌'}) / 句长 ${met[lv].sentAvg}(${sp.sent.join('-')}${okS ? ' ✅' : ' ❌'})`);
  }

  const checks = {};
  for (const lv of ['A1', 'A2']) {
    const c = await callCheck(ctx, masterRaw, paras[lv] || [], lv === 'A1' ? 'A1-' : 'A2');
    checks[lv] = c;
    const iss = (c.parsed && c.parsed.issues) || [];
    console.log(`  检 ${lv}: ${c.parsed ? c.parsed.verdict : '解析失败'} | ${iss.length} 条问题 (${Math.round(c.ms / 1000)}s)`);
    for (const it of iss) console.log(`      · 第${it.para}段 [${it.type}] ${String(it.detail).slice(0, 90)}`);
  }

  const totalIssues = ['A1', 'A2'].reduce((a, lv) => a + (((checks[lv].parsed || {}).issues || []).length), 0);
  const allMech = mechOk.A1 && mechOk.A2;
  const verdict = {
    mech: mechOk, mechPass: allMech,
    factPass: totalIssues === 0, factIssues: totalIssues,
    pass: allMech && totalIssues === 0,
  };
  fs.writeFileSync(`${OUT}.round${rd}.json`, JSON.stringify({
    round: rd, genMs, masterTextUsed: masterText, feedbackUsed: feedback,
    articles, paras, quiz, metrics: met, verdict,
    checks: { A1: checks.A1.parsed, A2: checks.A2.parsed }, rawChecks: { A1: checks.A1.raw, A2: checks.A2.raw },
  }, null, 1), 'utf-8');

  rounds.push({ round: rd, genMs, metrics: met, issues: totalIssues, verdicts: { A1: (checks.A1.parsed || {}).verdict, A2: (checks.A2.parsed || {}).verdict }, verdict });

  if (verdict.pass) { convergedAt = rd; console.log(`  ✅ 第 ${rd} 轮收敛（机械达标 + 事实零问题）\n`); break; }
  console.log(`  判定：机械 ${allMech ? '达标' : '不达标'} | 事实问题 ${totalIssues} 条\n`);

  feedback = buildFeedback(rd, { paras }, checks, met);
  masterText = masterRaw + '\n' + feedback;
  console.log(`  ↻ 带回反馈，母稿输入增至 ${masterText.length} 字符\n`);
}

fs.writeFileSync(`${OUT}.summary.json`, JSON.stringify({
  material: MATERIAL, masterParas: MP.length, rounds, convergedAt,
}, null, 1), 'utf-8');
console.log(`\n[收敛] ${convergedAt ? `第 ${convergedAt} 轮` : `${ROUNDS} 轮内未收敛`}`);
console.log(`[产物] ${OUT}.round*.json / ${OUT}.summary.json`);
ctx.close();
