// ReadPal · 分级卡片「生成侧」诊断（不渲染页面，调提示词时用）
//
// 为什么单独做这个：E2E 探针把生成、渲染、导出全跑一遍（40s+），调提示词时太重。
// 这里只做「跑图 → 用同一份 card_check.js 质检 → 落盘原始输出」，一轮 ~15s。
//
// 用法：
//   node tools/probe_card_gen.mjs                       # 用页面同款示例原文
//   CARD_TEXT_FILE=/abs/path.txt node tools/probe_card_gen.mjs
//   ROUNDS=3 node tools/probe_card_gen.mjs              # 带量化差量回炉（复刻页面逻辑）
//
// 产出：/tmp/card_gen_round<N>.json（模型原始 cards_json）+ /tmp/card_gen_round<N>.raw.json（Dify 完整回包）
import fs from 'node:fs';
import path from 'node:path';
import { runWorkflowWith } from './dify_run_wf.mjs';
import { makeCtx } from './dify_console.mjs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const CardCheck = require('../frontend/card_check.js');

const APP_KEY = process.env.CARD_APP_KEY || 'app-Lkai6OvrZHUekw0U3GTOWXrE';
const PORT = process.env.DIFY_CDP_PORT || '9243';
const ROUNDS = Number(process.env.ROUNDS || 1);
const REPO = path.resolve(import.meta.dirname, '..');

/* 默认原文 = 页面 SAMPLE（从 card.html 里取，保证两边同源，不会各改各的） */
function sampleFromPage() {
  const h = fs.readFileSync(path.join(REPO, 'frontend', 'card.html'), 'utf8');
  const line = h.split('\n').find(l => l.startsWith('const SAMPLE = '));
  if (!line) throw new Error('card.html 里找不到 SAMPLE');
  return eval(line.replace(/^const SAMPLE = /, '').replace(/;$/, ''));
}

const text = process.env.CARD_TEXT_FILE
  ? fs.readFileSync(process.env.CARD_TEXT_FILE, 'utf8').trim()
  : sampleFromPage();

console.log('原文：' + (process.env.CARD_TEXT_FILE || 'card.html SAMPLE')
  + '（' + text.split(/\s+/).length + ' 词 / ' + text.split(/\n\s*\n/).filter(Boolean).length + ' 自然段）');

/* ⚠️ 下面这段与页面 card.html 的对应函数**逐字保持一致**（两处逻辑必须同源，改了要一起改）：
   按档取历史最优 + 增量合并 + 回炉范围。 */
const genericErrs = rep => (rep.errs || []).filter(e => !/^(A1-|A2|B1|B2\+)/.test(String(e)));
const levelErrs = (rep, lv) => (rep.errs || []).filter(e => String(e).indexOf(lv) === 0).length;

/* 本轮有「不带档位前缀」的错误（结构性问题）时整轮不可信，一档都不收 */
function keepBest(rep, card, best) {
  if (genericErrs(rep).length) return [];
  const got = [];
  ['A1-', 'A2', 'B1', 'B2+'].forEach(lv => {
    const cards = (rep.cardsByLevel || {})[lv] || [];
    if (lv !== 'B2+' && !cards.length) return;
    const n = levelErrs(rep, lv);
    if (best[lv] && best[lv].errs <= n) return;      // 手里已经有更好的一版
    const qs = (((card.levels || {})[lv] || {}).questions) || [];
    best[lv] = { cards: cards.slice(), questions: qs.slice(), errs: n };
    got.push(lv);
  });
  return got;
}

/* 把历史最优按档覆盖回当前稿（没进 best 的档位保持当前稿） */
function assembleBest(card, best) {
  const keys = Object.keys(best);
  if (!keys.length) return card;
  const out = JSON.parse(JSON.stringify(card || {}));
  out.levels = out.levels || {};
  keys.forEach(lv => {
    out.levels[lv] = out.levels[lv] || {};
    out.levels[lv].cards = best[lv].cards.slice();
    out.levels[lv].questions = best[lv].questions.slice();
  });
  return out;
}

/* 增量合并：只取「本轮点名重写」的档位，其余档位一个字都不动。
   fixLevels 为空 = 全量替换（首次生成，或结构性问题需要整篇重来）。
   注意母稿正文（B2+ 的 cards）永远以代码算的那份为准。 */
function mergeCard(prev, partial, fixLevels) {
  if (!prev || !fixLevels || !fixLevels.length) return partial;
  const out = JSON.parse(JSON.stringify(prev));
  out.levels = out.levels || {};
  fixLevels.forEach(lv => {
    const P = ((partial || {}).levels || {})[lv];
    if (P) out.levels[lv] = { cards: (P.cards || []).slice(), questions: (P.questions || []).slice() };
  });
  const B = ((partial || {}).levels || {})['B2+'];
  if (B && (B.cards || []).length) {
    out.levels['B2+'] = out.levels['B2+'] || {};
    out.levels['B2+'].cards = B.cards.slice();
  }
  return out;
}

/* 下一轮要点名重写哪几档。整轮结构性问题 ⇒ 空数组（= 整篇重来） */
function failingLevels(rep) {
  if (genericErrs(rep).length) return [];
  const lv = [];
  ['A1-', 'A2', 'B1', 'B2+'].forEach(x => { if (levelErrs(rep, x) > 0) lv.push(x); });
  return lv;
}

/* ⚠️ 与页面 card.html 的 buildFixList() **逐字保持一致**（两处逻辑必须同源，改了要一起改）。 */
function buildFixList(report, card, masterCards) {
  const errs = (report.errs || []).map(String);
  /* 🔴 回炉的三条硬规矩（都是实测逼出来的）：
     ① **一次只改一类** —— 词数是一切的前提，先单独把它修到位；
     ② **带上上一稿正文** —— 不然模型每轮重写，篇幅在 46% 与 88% 之间来回振荡；
     ③ **单一目标 + 具体数字 + 逐卡现状** —— 只说「超上限了」它删不动（实测三轮 226/225/225
        几乎没变）；必须给出「现在多少、要减到多少、每张卡现在几个词」。
     已验证：预算/指令类字段确实能送达并被遵守（标记式哨兵实测 10/10 张卡照做），
     所以篇幅对不上不是「没收到底」，是指令不够硬 + 模型输出本身方差大。 */
  const wcErrs = errs.filter(e => e.indexOf("词数") >= 0);
  const out = ["【上一稿未通过代码质检。请**在上一稿的基础上改**，不要重写、不要解释、只输出 JSON。】"];

  const cardsOf = lv => (((report.cardsByLevel || {})[lv] || []).length)
    ? report.cardsByLevel[lv] : ((((card || {}).levels || {})[lv] || {}).cards || []);

  /* Dify 那边 fix_list 有长度上限（历史值 4000 字符）。按预算逐档附，附不下就明说 ——
     绝不让上游 400 硬失败、也绝不静默省掉说明。 */
  const LIMIT = 3800;
  const attach = levels => {
    levels.forEach(lv => {
      const t = cardsOf(lv);
      if (!t.length) return;
      const blk = ["", "【" + lv + " 的上一稿（" + t.length + " 张卡）—— 就在这个基础上改】"];
      t.forEach((c, i) => blk.push("  (" + (i + 1) + ") " + c));
      if (out.join("\n").length + blk.join("\n").length > LIMIT) {
        out.push("");
        out.push("（" + lv + " 的上一稿因长度上限未附上，请按上面的量化差量自行调整）");
        return;
      }
      blk.forEach(l => out.push(l));
    });
  };

  /* 🔴 分档并行（实测逼出来的）：
     篇幅没过关的档，本轮**只让它改篇幅**（删词和拆句掺在一起会互相抵消）；
     而**篇幅已经过关的档，本轮就修它自己的具体问题**。
     早先版本是「只要有篇幅错误，其他问题一律下一轮再说」—— 结果 A2 的长句被饿死：
     每轮都有别的档篇幅不过，A2 的问题永远排不上队（实测 3 轮跑完 A2 长句仍在）。 */
  const byLv = {};
  errs.forEach(e => {
    const mm = e.match(/^(A1-|A2|B1|B2\+)/);
    const k = mm ? mm[1] : "通用";
    (byLv[k] = byLv[k] || []).push(mm ? e.slice(k.length).replace(/^\s*/, "") : e);
  });
  const wcBad = {};
  wcErrs.forEach(e => { const mm = e.match(/^(A1-|A2|B1)/); if (mm) wcBad[mm[1]] = true; });
  const wcLv = Object.keys(wcBad);
  if (wcLv.length) {
    out.push("⚠️ 标了「只改篇幅」的档，本轮**只改篇幅**；没标的档篇幅已达标，**篇幅一个字都别动**。");
  }
  wcLv.forEach(lv => {
    const st = (report.stats || []).find(x => x.level === lv);
    if (!st) return;
    const rng = (typeof CardCheck !== "undefined" && CardCheck.RATIO[lv]) || null;
    const lo = rng ? Math.floor(rng[0] * report.origWc) : 0;
    const hi = rng ? Math.floor(rng[1] * report.origWc) : 0;
    const per = cardsOf(lv).map(c => CardCheck.words(c).length);
    out.push("· " + lv + "（只改篇幅）：现在 **" + st.wc + " 词**（" + Math.round(st.ratio * 100) + "%），"
      + "必须落到 **" + lo + "–" + hi + " 词**" + (st.wc > hi ? " —— 也就是全文要**删掉 "
        + (st.wc - hi) + " 个词以上**，建议删到 " + Math.round((lo + hi) / 2) + " 词左右"
        : " —— 也就是全文要**补回 " + (lo - st.wc) + " 个词以上**"));
    out.push("    逐张卡现状：" + per.map((n, i) => "(" + (i + 1) + ")" + n).join(" ")
      + " —— 删完再逐张数一遍");
  });
  Object.keys(byLv).forEach(lv => {
    if (lv !== "通用" && wcBad[lv]) return;   // 该档本轮只改篇幅，别的问题下轮再说
    const list = byLv[lv];
    out.push(lv === "通用" ? "· 通篇需要修的问题："
      : "· " + lv + " 篇幅已达标，只修这些问题（篇幅别动）：");
    list.slice(0, 10).forEach(x => out.push("    - " + x));
    if (list.length > 10) out.push("    -（同类问题另有 " + (list.length - 10) + " 处，一并处理）");
  });
  attach(wcLv.concat(Object.keys(byLv).filter(lv => lv !== "通用" && !wcBad[lv])));
  out.push("");
  out.push("· 只做加减，**不要把整段换一套说法重写**（重写会让篇幅弹到另一端）。");
  out.push("✗ 不得删掉原文的核心事实，不得改变谁对谁做了什么；四档卡片数不变、第 N 张仍讲同一件事。");
  return out.join("\n");
}


/* 「本轮只输出这几档」这句话由代码写死 —— 不指望提示词自己推断出回炉范围 */
function scopeHint(levels) {
  return '【本轮只输出这几档】' + levels.join(' / ') + '：`levels` 里**只放列出的档位**，'
    + '其余档位整个不要出现在 JSON 里（程序会把它们原样保留，多输出反而会把已达标的档改坏）。'
    + '`title_en` / `title_zh` / `topic_words` 照抄上一稿，不要重选。';
}

/* 母稿切分：与页面同一条路径（代码切，不交给模型） */
const cut = CardCheck.splitToCards(text, CardCheck.CARD_MIN);
if (!cut) { console.error('✗ 原文太短，切不出 ' + CardCheck.CARD_MIN + ' 张卡'); process.exit(1); }
const MASTER_CARDS = cut.cards;
const MASTER_BLOCK = MASTER_CARDS.map((c, i) => '[' + (i + 1) + '] ' + c).join('\n');
const MASTER_BUDGET = CardCheck.budgetTable(MASTER_CARDS);
console.log('母稿切分：' + cut.words + ' 词 / ' + cut.sentences + ' 句 → ' + MASTER_CARDS.length + ' 张卡');

const ctx = await makeCtx(PORT, 'dify');
let fix = '', fixLevels = [];
const best = {};
let card = null;
try {
  for (let round = 1; round <= ROUNDS; round++) {
    const t0 = Date.now();
    const r = await runWorkflowWith(ctx, {
      appKey: APP_KEY,
      inputs: { master_cards: MASTER_BLOCK, master_budget: MASTER_BUDGET, title_in: '',
                fix_list: fix, fix_levels: fixLevels.length ? scopeHint(fixLevels) : '' },
      user: 'card-gen-probe'
    });
    const d = r.data || {};
    const out = d.data?.outputs || d.outputs || {};
    const ms = Date.now() - t0;
    fs.writeFileSync('/tmp/card_gen_round' + round + '.raw.json', JSON.stringify(d, null, 1));
    fs.writeFileSync('/tmp/card_gen_round' + round + '.json', out.cards_json || '{}');

    let partial = {};
    try { partial = JSON.parse(out.cards_json || '{}'); } catch (e) { /* 解析失败下面会体现 */ }
    /* 与页面同一条路：回炉只收点名的档位，其余沿用上一稿 */
    card = mergeCard(card, partial, fixLevels);
    const lvCards = lv => (((card.levels || {})[lv] || {}).cards || []).length;

    const rep = CardCheck.run(card, text, MASTER_CARDS);
    console.log('\n──── 第 ' + round + ' 轮 · ' + (ms / 1000).toFixed(1) + 's · parse_ok=' + out.parse_ok + ' ────');
    console.log('  母稿卡（代码切）= ' + MASTER_CARDS.length + ' 张  ← B2+ 卡数由它决定，不由模型');
    console.log('  各档 cards 长度：A1-=' + lvCards('A1-') + '  A2=' + lvCards('A2')
      + '  B1=' + lvCards('B1') + '  B2+(=母稿卡数)=' + lvCards('B2+'));
    console.log('  topic_words=' + JSON.stringify(card.topic_words || []));
    if (out.parse_warn) console.log('  解析告警：' + out.parse_warn);
    rep.stats.forEach(s => console.log('    ' + s.level.padEnd(4) + ' 卡' + String(s.cards).padStart(2)
      + ' 词' + String(s.wc).padStart(4) + ' 占比' + String(Math.round(s.ratio * 100)).padStart(4)
      + '% 句长 ' + s.min + '–' + s.max + ' 均' + s.avg.toFixed(1)
      + '  [目标 ' + (CardCheck.RATIO[s.level] ? Math.round(CardCheck.RATIO[s.level][0] * 100) + '–'
        + Math.round(CardCheck.RATIO[s.level][1] * 100) + '% / ≤' + CardCheck.MAX_SENT[s.level] + '词' : '母稿') + ']'));
    console.log('  硬错误 ' + rep.errs.length + ' / 告警 ' + rep.warns.length);
    if (rep.splitNote) console.log('  ⚠ 切卡兜底：' + rep.splitNote);
    (rep.alignNotes || []).forEach(n => console.log('  ⚠ 卡数对齐：' + n));
    rep.errs.slice(0, 14).forEach(e => console.log('    ✗ ' + e));
    rep.warns.slice(0, 6).forEach(w => console.log('    ! ' + w));

    const got = keepBest(rep, card, best);
    if (got.length) console.log('  ❄ 刷新历史最优：' + got.join(' / '));
    const merged = assembleBest(card, best);
    const mrep = CardCheck.run(merged, text, MASTER_CARDS);
    if (mrep !== rep) {
      console.log('  拼装后（各档取历史最优）：硬错误 ' + mrep.errs.length + ' / 告警 ' + mrep.warns.length);
      mrep.errs.slice(0, 10).forEach(e => console.log('    ✗ ' + e));
    }
    if (mrep.ok || round === ROUNDS) {
      console.log('\n' + (mrep.ok ? '✅ 拼装后全部通过（第 ' + round + ' 轮达成）'
        : '❌ ' + ROUNDS + ' 轮后仍未通过（拼装后 ' + mrep.errs.length + ' 处）'));
      break;
    }
    fixLevels = failingLevels(mrep);
    fix = buildFixList(mrep, merged, MASTER_CARDS);
    console.log('  → 回炉第 ' + (round + 1) + ' 轮：只重写 ' + fixLevels.join('/')
      + '（' + fix.split('\n').length + ' 行指令）');
  }
} catch (e) {
  console.error('✗ 跑图失败：' + (e && e.message ? e.message : e));
  process.exitCode = 1;
} finally {
  ctx.close();
}
