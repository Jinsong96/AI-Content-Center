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
    const nw = levelWcErrs(rep, lv);
    if (best[lv]) {
      if (best[lv].errs < n) return;                                  // 手里已经有更好的一版
      if (best[lv].errs === n && best[lv].wc <= nw) return;           // 打平：篇幅已达标的优先
    }
    const qs = (((card.levels || {})[lv] || {}).questions) || [];
    best[lv] = { cards: cards.slice(), questions: qs.slice(), errs: n, wc: nw };
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
   注意母稿正文（B2+ 的 cards）永远以代码算的那份为准。

   ⚠️ topic_words 是**全局**字段（不属于任何一档），但也必须收进来：
   「缺少主题词」是唯一一条**只能靠换词修**的错误 —— B2+ 正文是代码硬取的原文，
   改正文修不掉它；不收 topic_words 就等于这条错误永远修不动（实测：跑满 5 轮仍停在
   「B2+ 缺少主题词」，整轮生成白费）。照抄上一稿时模型给的就是原值，不产生漂移。
   档位的 cards / questions 仍走「按错误数留历史最优」，最终结论也在拼装后**重算**，
   所以交付不会因为这一条而变差。 */
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
  const tw = ((partial || {}).topic_words || []).map(w => String(w || '').trim()).filter(Boolean);
  if (tw.length) out.topic_words = tw;
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

  /* Dify 那边 fix_list 有 max_length 上限，**图上现在是 20000**（见 build_card_graph.py）。
     这里留 3000 字符余量给 Dify 自身的包装。
     ⛔ 早先写 3800 是「图上限 4000」时代的遗留，后果很隐蔽：一次回炉点 2–3 个档时，
     后面的档位草稿会被丢弃，模型拿不到「上一稿」就只能整段重写 —— 篇幅反复压不下来
     （实测 B1 连续 4 轮停在 84%）。附不下仍然明说，绝不静默。 */
  const LIMIT = 17000;
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
    /* 🔴 句数差量（实测 2026-09-24 证明这是唯一有效的那个量）：
       同一篇原文，B1 预算 ≤25 句，模型连续 4 轮都写 30 句、词数 402–436（87–94%）不降；
       而它的均句长 13.4 本就是对的 —— 也就是说**超词数 100% 来自多写的 5 句**。
       只在指令里写「删掉 44 个词」它不动；写「删掉 5 个整句」它才数得动、才执行。
       这也正是本项目的既有原则：控字数靠「可数的量」（句数），不靠百分比。 */
    const lvCards = cardsOf(lv);
    const curSent = CardCheck.sentences(lvCards.join(" ")).length;
    const capSent = (typeof CardCheck.sentCap === "function") ? CardCheck.sentCap(masterCards, lv) : 0;
    const overSent = capSent ? Math.max(0, curSent - capSent) : 0;
    out.push("· " + lv + "（只改篇幅）：现在 **" + st.wc + " 词 / " + curSent + " 句**（"
      + Math.round(st.ratio * 100) + "%），"
      + "必须落到 **" + lo + "–" + hi + " 词**" + (st.wc > hi ? " —— 也就是全文要**删掉 "
        + (st.wc - hi) + " 个词以上**，建议删到 " + Math.round((lo + hi) / 2) + " 词左右"
        : " —— 也就是全文要**补回 " + (lo - st.wc) + " 个词以上**"));
    if (overSent && st.wc > hi) {
      out.push("    🔴 **句数超了 " + overSent + " 句**（现在 " + curSent + " 句，上限 " + capSent
        + " 句）：**删掉 " + overSent + " 个整句** —— 这是本轮最容易做到、也最有效的一步。");
      out.push("        句数是硬上限，也是词数的来源：把句数降到 " + capSent
        + " 句以内，词数自然就进区间。（你的句子长度本来就是对的，**别再写短句**，是**少写几句**。）");
    }
    out.push("    逐张卡现状（**句数/词数**）：" + lvCards.map((c, i) => "(" + (i + 1) + ")"
      + CardCheck.sentences(c).length + "/" + per[i]).join(" ")
      + " —— 改完再逐张数一遍（词数和句数都要数）");
    /* 🔴 把「删掉 N 个词」翻译成模型算得动的形式：**逐张卡的绝对上限**。
       实测（2026-09-24，B1 原文 460 词）：只给「全文要删 12 个词」这种总量指令，
       连续 3 轮回炉词数 370 → 375 → 390，**不降反涨**；而给「每张卡 ≤ 35 词」
       它每张卡都能当下核对。同一条思路的既有依据：控字数靠**可数的量**（句数），不靠百分比。 */
    if (st.wc > hi && per.length) {
      const cap = Math.floor(hi / per.length);
      out.push("    🔴 逐张卡硬上限 **" + cap + " 词**（= " + hi + " ÷ " + per.length
        + " 张）：**每张卡都要 ≤ " + cap + "**，" + per.length + " 张加起来就自然 ≤ " + hi + "。"
        + "现在超上限的卡：" + per.map((n, i) => n > cap ? "(" + (i + 1) + ")" + n : null)
            .filter(Boolean).join(" ") + " —— 只改这几张。");
      out.push("    怎么删（照这个做，**不要整段换一套说法重写**）：");
      out.push("      ① **整句删**是首选 —— 举例、旁证、可有可无的修饰句直接不要");
      out.push("         （如 such as diabetes / for example / Doctor X agrees 这类）；");
      out.push("      ② 保真只要求**核心观点和主体**在，**不要求每个细节都在**；");
      out.push("      ③ ⛔ 不许靠**合并句子**来压词数（合并会撞本档单句上限，等于没改），要删就整句删。");
    }
    /* 🔴 反方向也要给（2026-09-24 补）：**低于下限**同样不合格，而且它是被「拆句」规则带出来的 ——
       长列举被拆成一项一句（`Olive oil.` / `Oily fish.`）后，A1- 只剩均 6 词/句、总词数 121（26%），
       连续 5 轮回炉补不回来。低于下限时**不能靠加句**（句数已到上限），只能把句子写长，
       所以这里给的是「均句长」这个量，并给出本档的单句上下限（MIN_SENT / MAX_SENT）。 */
    if (st.wc < lo && per.length) {
      const mn = (CardCheck.MIN_SENT || {})[lv], mx = (CardCheck.MAX_SENT || {})[lv];
      out.push("    🔴 方向是**加词**（现在比下限还少 " + (lo - st.wc) + " 个词）："
        + "**不要靠多写句子**（句数上限 " + capSent + " 句" + (overSent ? "，你现在 "
          + curSent + " 句、反而已经超了)：" : "，已经满了)：") + "要靠**把句子写长**。");
      out.push("        现在均句长 **" + st.avg.toFixed(1) + " 词/句**，太短了 —— 本档单句可以写到 "
        + mx + " 词（低于 " + mn + " 词的碎片句也算问题）。目标均句长 **"
        + Math.max(mn, Math.ceil((lo + hi) / 2 / Math.max(1, curSent))) + "–"
        + Math.min(mx, Math.ceil(hi / Math.max(1, curSent))) + " 词/句**。");
      out.push("        怎么加：① 把碎片句**并回完整句**（`Olive oil.` → `People should eat olive oil and oily fish.`，"
        + "既补了词数又减了句数）；");
      out.push("        ② 名词补形容词、动作补对象（`We eat food.` → `We eat healthy food every day.`）；");
      out.push("        ③ ⛔ 不要新增原文没有的事实，也不要把一句话拆成两句。");
    }
  });
  Object.keys(byLv).forEach(lv => {
    if (lv !== "通用" && wcBad[lv]) return;   // 该档本轮只改篇幅，别的问题下轮再说
    const list = byLv[lv];
    out.push(lv === "通用" ? "· 通篇需要修的问题："
      : "· " + lv + " 篇幅已达标，只修这些问题（篇幅别动）：");
    list.slice(0, 10).forEach(x => out.push("    - " + x));
    if (list.length > 10) out.push("    -（同类问题另有 " + (list.length - 10) + " 处，一并处理）");
    /* 把「拆句」这件事说到**具体哪一句**上。起因（实测 2026-09-24）：提示词里已经写了
       「断句只看 . ? !」「长列举要拆开」，但模型连续 4 轮都把那句 28 词的地中海饮食列举原样留着
       —— 规则埋在长提示词里不管用，落在「这一句、拆成两句」上才有动作。
       ⛔ 这里只给规则和原文，**不替它造句子**（造句子属于生成，会引入代码编造的内容）。 */
    const longS = list.map(x => x.match(/^卡(\S+)\s+句子\s+(\d+)\s+词\s+>\s+(\d+)：(.+)$/)).filter(Boolean);
    if (longS.length) {
      out.push("    ⚠️ 下面这 " + longS.length + " 句**必须各拆成 2 句**（本档单句硬上限 "
        + longS[0][3] + " 词）：");
      longS.slice(0, 6).forEach(m => out.push("      · 卡" + m[1] + " 现 " + m[2] + " 词 → 拆成 2 句：" + m[4]));
      out.push("      ⛔ 用分号 / 逗号「假装」断句**无效**（代码只认 `.` `?` `!`）；"
        + "列举串就**一项一句**（`…. Olive oil. Oily fish. Whole grains.`）。"
        + "拆句**不需要删事实**，只是把一句变成两句。");
    }
  });
  attach(wcLv.concat(Object.keys(byLv).filter(lv => lv !== "通用" && !wcBad[lv])));
  out.push("");
  out.push(wcLv.length
    ? "· 标了「只改篇幅」的档，**只按上面给的方向改篇幅**（该删就删、该加就加，别两件事一起做），"
      + "**不要把整段换一套说法重写**（重写会让篇幅弹到另一端）。"
    : "· 只做加减，**不要把整段换一套说法重写**（重写会让篇幅弹到另一端）。");
  out.push("✗ 不得改变谁对谁做了什么（主体 / 因果 / 立场）；四档卡片数不变、第 N 张仍讲同一件事。"
    + (wcLv.length ? " ⚠️ 本条只约束「不许改」，**不约束「不许删」** —— 该删的整句照删。" : ""));
  return out.join("\n");
}


/* 「本轮只输出这几档」这句话由代码写死 —— 不指望提示词自己推断出回炉范围。
   ⛔ 档位列表**必须放在最前面**（历史教训 2026-09-24）：这句文本同时被图上的解析节点
   （parse）拿去做「本轮应该出现哪几档」的判定，用的是「按分隔符切词 + 档位名匹配」。
   早先写「【本轮只输出这几档】B2+：…」，切出来的第一个词带中文前缀 → 匹配落空 →
   解析判成「缺 A1-/A2/B1」→ 回炉整轮作废（第 3–5 轮连续白跑）。
   现在两头都加固：图侧改成全文扫描档位名，这里也把列表放在最前，位置加错一层也不怕。 */
function scopeHint(levels) {
  return levels.join(' / ') + '（本轮只输出这几档）：`levels` 里**只放列出的档位**，'
    + '其余档位整个不要出现在 JSON 里（程序会把它们原样保留，多输出反而会把已达标的档改坏）。'
    + '`title_en` / `title_zh` 照抄上一稿，不要重选；`topic_words` 也照抄上一稿，'
    + '**只有本轮问题清单里点了「缺少主题词」时才换词** —— 换成一个**母稿正文里逐字出现过**的词。';
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
