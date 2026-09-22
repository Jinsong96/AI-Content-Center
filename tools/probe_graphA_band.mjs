// ReadPal · 图 A 质检程序（nodeClean）本地回归 —— 不需要线上、不需要 Chrome
//
// 覆盖 2026-09-22 用户拍板的口径：
//   · **保留原文**：每段词数是分段的唯一依据，合格带 = 该档每段规格 ±5（B1 23–40 / B2+ 36–55）；
//     段数由「全文词数 ÷ 每段目标」算出，落在 10–15 内不提示；切不准时代码自动兜底
//     （补切/合并/借邻居重排），只移切分点、一个字不改
//   · **精简稿**：全文字数优先（落该档硬区间），段数按内容大意自然分，**10–15 只作兜底判定区间**；
//     质检**只调段数不按长度重排**（重排会切坏大意）
//
// 用法：
//   python3 tools/extract_graphA_code.py /tmp          # 先抽出 JS
//   node tools/probe_graphA_band.mjs [--text=<文件>]    # 传外部素材时按空行分段喂进去
//
// 退出码 0 = 全过。
import fs from 'node:fs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => { const h = argv.find(a => a.startsWith(`--${k}=`)); return h ? h.slice(k.length + 3) : d; };
const EXT = arg('text', null);

const main = (await import('/tmp/_gA_clean.js')).default;
const wc = t => (String(t).match(/[A-Za-z][A-Za-z'-]*/g) || []).length;
const norm = t => (String(t).toLowerCase().match(/[a-z][a-z'-]*/g) || []);
const bandOf = lv => (lv === 'B1' ? [23, 40] : [36, 55]);
const inBand = (k, lv) => { const b = bandOf(lv); return k >= b[0] && k <= b[1]; };

const R = [];
const ok = (label, cond, detail) => R.push({ ok: !!cond, label, detail: detail == null ? '' : String(detail) });
const run = (lv, simp, body, master) => main({
  level: lv, need_simplify: simp ? 'true' : 'false',
  master: master === undefined ? body.join('\n\n') : master,
  raw: JSON.stringify({ segments: body }), fallback: 'false',
});
const same = (a, b) => { const x = norm(a), y = norm(b); return x.length === y.length && x.every((w, i) => w === y[i]); };

/* ── 内置合成素材：8 个自然段、各 38–55 词（仿真「原文自然段就这么长」的母稿，
      与用户实测那篇 B1 同形态；用自造词句，不含任何版权内容） ── */
const PARAS = [
  /* 首段刻意造到 ~46 词、末段 ~16 词 —— 复刻用户实测那篇 B1 的形态
     （原文自然段 38–54 词 + 一个 18 词的收尾段），这样才真的走到「补切」和「合并」两条兜底路径 */
  'Most cities now measure the air above their streets. The sensors are cheap, easy to install, ' +
    'and report a number every few minutes. Officials say the data has changed how they plan. ' +
    'Dozens of new networks appeared in a single year, and some cover whole neighbourhoods.',
  'The first networks went up near schools and hospitals. Readings there were often worse than expected. ' +
    'That finding alone shifted several budget decisions. Local councils began publishing the numbers weekly.',
  'Not every device is accurate. Cheap sensors drift when the weather turns humid or very cold. ' +
    'Researchers compared them against reference stations for a full year. The gap narrowed after calibration.',
  'Citizens use the same feed the city does. Some neighbourhood groups print the daily figures and post them. ' +
    'Others send alerts when a street crosses a threshold. Participation has grown steadily since the launch.',
  'Industry representatives argue the picture is incomplete. They point to wind patterns that move pollution across districts. ' +
    'A single monitor can therefore blame the wrong block. Several firms have offered to fund more stations.',
  'Regulators are cautious about acting on raw readings. They want a documented method before fines are issued. ' +
    'A draft standard is under review this year. Until then most cities treat the numbers as advisory.',
  'The cost of a basic unit has fallen sharply. Five years ago a station cost as much as a used car. ' +
    'Today a school can afford a small cluster. That price drop is the main reason the maps look so full.',
  'The real test is what happens next. Data alone rarely clears the air, officials admit.',
];
const FIXTURE = EXT ? fs.readFileSync(EXT, 'utf8').trim().split(/\n\s*\n/).map(s => s.trim()).filter(Boolean) : PARAS;

console.log('素材：' + FIXTURE.length + ' 段 · ' + FIXTURE.map(wc).join('/') + ' 词 · 共 ' + wc(FIXTURE.join(' ')) + ' 词'
  + (EXT ? '（来自 ' + EXT + '）' : '（内置合成）'));
console.log('');

/* ── 1) 核心场景：模型照搬原文自然段 → 质检拉进合格带 ── */
for (const lv of ['B1', 'B2']) {
  const r = run(lv, false, FIXTURE);
  const per = JSON.parse(r.para_words);
  const segs = JSON.parse(r.segments_json);
  const b = bandOf(lv);
  const est = Math.max(1, Math.round(wc(FIXTURE.join(' ')) / ((b[0] + b[1]) / 2)));
  console.log(`【${lv}】${per.length} 段 · ${per.join('/')}   （按每段中点预估 ${est} 段）`);
  ok(`${lv}：每段落在 ${b[0]}–${b[1]}`, per.every(k => inBand(k, lv)),
    per.filter(k => !inBand(k, lv)).join(',') || '全部达标');
  /* 段数由「全文词数 ÷ 每段中点」算出 —— 允许 ±1（兜底重排会小幅调整）。
     ⚠️ 不能一律断言 8–15：同一篇按 B2+ 算本来就只该 6 段（原文 266 词偏短）。 */
  ok(`${lv}：段数与「词数 ÷ 每段中点」一致（±1）`, Math.abs(per.length - est) <= 1,
    `实际 ${per.length} / 预估 ${est}`);
  if (lv === 'B1') ok('B1：段数在常规区间 10–15 内，或已给出 seg_note（不许静默）',
    (per.length >= 10 && per.length <= 15) || r.seg_note !== '',
    per.length + ' 段 · seg_note="' + r.seg_note + '"');
  ok(`${lv}：逐字一致（只移切分点）`, same(segs.join(' '), FIXTURE.join('\n\n')));
  ok(`${lv}：无告警`, r.warn === '', '"' + r.warn + '"');
  ok(`${lv}：out_of_band = 0`, r.out_of_band === '0', r.out_of_band);
  ok(`${lv}：auto_fixed > 0（确实兜底过）`, Number(r.auto_fixed) > 0, 'auto_fixed=' + r.auto_fixed);
}

/* ── 2) 幂等：把结果再喂一遍，不应再变动 ── */
{
  const r1 = run('B1', false, FIXTURE);
  const once = JSON.parse(r1.segments_json);
  const r2 = run('B1', false, once);
  console.log('\n【幂等】' + JSON.parse(r1.para_words).join('/') + '  →  ' + JSON.parse(r2.para_words).join('/'));
  ok('二次处理无变化', JSON.stringify(once) === JSON.stringify(JSON.parse(r2.segments_json)));
  ok('二次 auto_fixed = 0', r2.auto_fixed === '0', 'auto_fixed=' + r2.auto_fixed);
}

/* ── 3) 精简模式：段数 10–15 是兜底区间；质检**只调段数、不按长度重排** ── */
{
  const w = n => Array(n).fill('word').join(' ');
  /* 每段造两句（句号后接大写词），才能被「按句边界补切」切开 —— 一整句话的段切不动。
     ⚠️ 编号**不能用数字**（`s0a` 会被词数正则拆成 s + a 两个词，字数统计全错）。 */
  const para = (a, b) => w(a) + ' Alpha. Then ' + w(b) + ' Beta.';
  const simpP = (n, a, b) => Array.from({ length: n }, () => para(a, b));

  /* 3a) 12 段 × ~33 词（396 词，B1 区间内）⇒ 段数在区间内，质检不得介入 */
  const c12 = simpP(12, 15, 16);
  const r12 = run('B1', true, c12, c12.join('\n\n'));
  console.log('\n【精简 12 段】' + r12.seg_count + ' 段 · ' + r12.word_count + ' 词 · auto_fixed=' + r12.auto_fixed + ' · ok=' + r12.ok);
  ok('精简 12 段：保持 12 段', r12.seg_count === '12', r12.seg_count);
  ok('精简 12 段：质检不介入', r12.auto_fixed === '0', 'auto_fixed=' + r12.auto_fixed);
  ok('精简 12 段：ok = true', r12.ok === 'true', '"' + r12.warn + '"');
  ok('精简 12 段：无告警', r12.warn === '', '"' + r12.warn + '"');

  /* 3b) 18 段 × ~22 词（396 词）⇒ 段数超上限，合并回 ≤15 */
  const c18 = simpP(18, 10, 10);
  const r18 = run('B1', true, c18, c18.join('\n\n'));
  console.log('【精简 18 段】' + r18.seg_count + ' 段 · ' + r18.word_count + ' 词 · auto_fixed=' + r18.auto_fixed + ' · ok=' + r18.ok);
  ok('精简 18 段：兜底后回到 ≤15 段', Number(r18.seg_count) <= 15, r18.seg_count);
  ok('精简 18 段：确实兜底过', Number(r18.auto_fixed) > 0, 'auto_fixed=' + r18.auto_fixed);
  ok('精简 18 段：ok 变 true（字数没动）', r18.ok === 'true', '"' + r18.warn + '"');
  ok('精简 18 段：逐字一致（只合并、不改字）',
    same(JSON.parse(r18.segments_json).join(' '), c18.join('\n\n')));

  /* 3c) 6 段 × ~62 词（372 词）⇒ 段数低于下限，按句边界补切回 ≥10 */
  const c6 = simpP(6, 30, 30);
  const r6 = run('B1', true, c6, c6.join('\n\n'));
  console.log('【精简 6 段】' + r6.seg_count + ' 段 · ' + r6.word_count + ' 词 · auto_fixed=' + r6.auto_fixed + ' · ok=' + r6.ok);
  ok('精简 6 段：兜底后回到 ≥10 段', Number(r6.seg_count) >= 10, r6.seg_count);
  ok('精简 6 段：确实兜底过', Number(r6.auto_fixed) > 0, 'auto_fixed=' + r6.auto_fixed);
  ok('精简 6 段：ok 变 true', r6.ok === 'true', '"' + r6.warn + '"');

  /* 3d) 🔴 精简模式**不做长度重排**：词数不匀的 12 段必须原样返回
         （段边界是模型按内容大意切的，按长度重排会切坏大意 —— 用户 2026-09-22 明确） */
  const cu = [36, 26, 36, 26, 31, 31, 31, 31, 31, 31, 31, 31].map(k => para(Math.floor(k / 2), k - Math.floor(k / 2)));
  const ru = run('B1', true, cu, cu.join('\n\n'));
  console.log('【精简·词数不匀】' + JSON.parse(ru.para_words).join('/') + ' · auto_fixed=' + ru.auto_fixed);
  ok('精简模式不按长度重排（段落逐段原样）', JSON.stringify(cu) === JSON.stringify(JSON.parse(ru.segments_json)));
  ok('精简·不匀：段数仍 12', ru.seg_count === '12', ru.seg_count);

  /* 3e) 精简模式段数合格但字数越界 ⇒ 必须判失败并写明原因 */
  const c41 = simpP(12, 8, 9);   /* 12 × 19 ≈ 228 词，低于 B1 下限 323 */
  const r41 = run('B1', true, c41, c41.join('\n\n'));
  console.log('【精简·字数偏低】' + r41.seg_count + ' 段 · ' + r41.word_count + ' 词 · ok=' + r41.ok + ' · warn="' + r41.warn + '"');
  ok('精简·字数偏低：ok = false', r41.ok === 'false');
  ok('精简·字数偏低：warn 写明低于下限', r41.warn.indexOf('下限') >= 0, '"' + r41.warn + '"');
}

/* ── 4) 一整句话超长 → 报出来，不许静默 ── */
{
  const w = n => Array(n).fill('word').join(' ');
  const long = w(60) + '. ' + w(60) + '.';
  const r = run('B1', false, [long], long);
  console.log('\n【整句超长】' + r.para_words + ' · warn="' + r.warn + '"');
  ok('越界段被计数', Number(r.out_of_band) > 0, 'out_of_band=' + r.out_of_band);
  ok('warn 非空（不许静默）', r.warn !== '');
}

/* ── 5) 异常输入不崩 ── */
{
  const w = n => Array(n).fill('word').join(' ');
  const fx = FIXTURE.join('\n\n');
  const cases = [
    ['空输入', { level: 'B1', need_simplify: 'false', master: '', raw: '', fallback: 'false' }, r => r.ok === 'false'],
    ['未知档位', { level: 'C1', need_simplify: 'false', master: fx, raw: JSON.stringify({ segments: FIXTURE }), fallback: 'false' }, r => r.ok === 'false'],
    ['缺 need_simplify', { level: 'B1', master: fx, raw: JSON.stringify({ segments: FIXTURE }), fallback: 'false' }, r => r.ok === 'true'],
    ['raw 是纯文本非 JSON', { level: 'B1', need_simplify: 'false', master: fx, raw: FIXTURE.join('\n\n'), fallback: 'false' }, r => r.ok === 'true'],
    ['段落含 markdown 标记', { level: 'B1', need_simplify: 'false', master: fx, raw: JSON.stringify({ segments: FIXTURE.map(p => '## ' + p) }), fallback: 'false' }, r => r.ok === 'true'],
  ];
  for (const [name, inp, expect] of cases) {
    let res = null, err = '';
    try { res = main(inp); } catch (e) { err = e.message; }
    ok(name + ' 不抛异常', !err, err ? 'THROW ' + err : 'seg=' + (res && res.seg_count) + ' ok=' + (res && res.ok));
    if (res && !err) ok(name + ' 判定符合预期', expect(res), 'ok=' + res.ok);
  }
  void w;
}

const pass = R.filter(r => r.ok).length;
console.log('\n=== 结果 ===');
R.forEach(r => console.log(`  ${r.ok ? '✓' : '✗'} ${r.label}${r.detail ? '   [' + r.detail + ']' : ''}`));
console.log(`\n${pass}/${R.length} 项通过`);
process.exit(pass === R.length ? 0 : 1);
