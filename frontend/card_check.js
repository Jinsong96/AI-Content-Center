/* ReadPal · 分级卡片质检（100% 代码，零 AI 调用）
 * ============================================================
 * 逐条移植自教研工具包 `build_cards.py` 的 `split_original()` 与 `check()`，
 * **判据一个不改**（比例区间、句长上下限、超纲信号词、主题词、引文可查）。
 *
 * 为什么用代码而不是再叫一个大模型：
 *   AI 抽专名实测会漏项（Canada / Ireland 母稿明文有却没抽出来），
 *   主题词数量判定在 4 与 5 之间抖 —— 要求「完备」和「可计数」的判断
 *   交给概率模型必然出现静默漏洞。可枚举、可计数的部分交给代码，
 *   AI 只负责「这段是不是讲的同一件事」这类语义判断。
 *
 * 与页面解耦：浏览器挂 window.CardCheck；node 侧可 require（见 tools/probe_card_check.mjs）。
 */
(function (root) {
  'use strict';

  var LEVELS = ['A1-', 'A2', 'B1', 'B2+'];

  // ===== 质检参数（与工具包 build_cards.py 逐字一致，改这里等于改验收标准）=====
  // 词数口径 = **占原文百分比**，不是绝对词数 —— 母稿多长都不用改规格。
  var RATIO = { 'A1-': [0.30, 0.42], 'A2': [0.48, 0.60], 'B1': [0.65, 0.78] };
  var MAX_SENT = { 'A1-': 12, 'A2': 16, 'B1': 22 };   // 超了判错
  var MIN_SENT = { 'A1-': 4, 'A2': 5, 'B1': 6 };      // 短了只警告
  var FLAG_WORDS = {                                   // 超纲语法信号词：只警告，不判错
    'A1-': ['may', 'might', 'if', 'which', 'whose', 'who', 'would', 'could', 'been',
            'should', 'must', 'although', 'however', 'while'],
    'A2': ['which', 'whose', 'might', 'although', 'whereas', 'had been', 'would have'],
    'B1': ['were i', 'had i', 'not only', 'whereby']
  };
  var NUMS = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
  // 卡数规格：固定 10 张，原文超长才到 12 张 —— **不随原文的段落数变**
  var CARD_MIN = 10, CARD_MAX = 12;

  function numMark(i) { return i < NUMS.length ? NUMS.charAt(i) : '(' + (i + 1) + ')'; }

  function norm(s) {
    return String(s == null ? '' : s)
      .replace(/[\u2019\u2018]/g, "'")
      .replace(/[\u201c\u201d]/g, '"')
      .replace(/\u2014/g, '\u2013')
      .replace(/\s+/g, ' ').trim();
  }

  function words(s) {
    var m = String(s == null ? '' : s).match(/[A-Za-z0-9]+(?:['\u2019][A-Za-z]+)?/g);
    return m || [];
  }

  function sentences(text) {
    var parts = norm(text).split(/(?<=[.?!])["']?\s+(?=["'A-Z0-9])/);
    return parts.filter(function (p) { return /[A-Za-z0-9]/.test(p); });
  }

  /* 取出成对双引号里的纯英文片段（≥3 个词）；中文引语跳过 */
  function quotedEnglish(s) {
    var parts = norm(s).split('"');
    var out = [];
    for (var i = 1; i < parts.length; i += 2) {
      var q = parts[i];
      if (/[\u4e00-\u9fff]/.test(q)) continue;
      if (words(q).length >= 3) out.push(q);
    }
    return out;
  }

  /* 把原文按 b2_card_starts（每张卡开头 4 个词）切开 —— 母稿**不由模型写**，由代码逐字取。
     两条硬校验：找不到锚点、或第一张卡不是从原文开头起 ⇒ 抛错（原文被漏掉不是小问题）。 */
  function splitOriginal(orig, starts) {
    var o = norm(orig), pos = 0, idx = [];
    var list = Array.isArray(starts) ? starts : [];
    for (var i = 0; i < list.length; i++) {
      var s = norm(list[i]);
      if (!s) throw new Error('第 ' + (i + 1) + ' 张卡的起始词为空');
      var at = o.indexOf(s, pos);
      if (at < 0) at = o.toLowerCase().indexOf(s.toLowerCase(), pos);
      if (at < 0) throw new Error('原文里找不到卡片起始句：' + JSON.stringify(list[i]));
      idx.push(at); pos = at + 1;
    }
    idx.push(o.length);
    if (idx[0] !== 0) throw new Error('第一张卡没有从原文开头开始，原文开头被漏掉了');
    var out = [];
    for (var k = 0; k < list.length; k++) out.push(o.slice(idx[k], idx[k + 1]).trim());
    return out;
  }

  /* 锚点可用性预检：**个数对不对**是明面的，**顺序对不对**是隐蔽的。
     实测（463 词 / 5 自然段的原文，3 次生成）模型给出的锚点：
        · 有时 5 个（= 原文自然段数）
        · 有时 10 个，但**不是按原文顺序排的** —— 它先列 5 个「段级」锚点，
          再把 5 个「段内细分」锚点追加在后面（第 6 个的位置在 1053，却排在位置 2035 的后面），
          还出现过两个锚点落在同一位置（1488）。
     splitOriginal 用递进 indexOf，隐含「锚点必须有序」这个前提 ——
     范例是单段原文、天然有序，所以一直没暴露。多段原文一碰就碎。
     所以这里先判，不可用就交给代码切分，**而不是直接判失败**。 */
  function validateStarts(orig, starts) {
    var o = norm(orig), ol = o.toLowerCase(), pos = 0, list = starts || [];
    for (var i = 0; i < list.length; i++) {
      var s = norm(list[i]);
      if (!s) return { ok: false, reason: '第 ' + (i + 1) + ' 个锚点是空的' };
      var at = o.indexOf(s, pos);
      if (at < 0) at = ol.indexOf(s.toLowerCase(), pos);
      if (at < 0) {
        var anywhere = o.indexOf(s) >= 0 || ol.indexOf(s.toLowerCase()) >= 0;
        return {
          ok: false,
          reason: '第 ' + (i + 1) + ' 个锚点 "' + list[i] + '" '
            + (anywhere ? '在原文里的位置比前一个锚点还靠前 —— 锚点没有按原文顺序排列'
                        : '在原文里根本找不到 —— 模型改写了原文词句')
        };
      }
      pos = at + 1;
    }
    return { ok: true, reason: '' };
  }

  function sub(needle, haystackLower) {
    var q = needle.toLowerCase().replace(/^[\s.,]+/, '').replace(/[\s.,]+$/, '');
    return q && haystackLower.indexOf(q) >= 0;
  }

  function esc(re) { return re.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  /* 保留段落换行的归一化（splitToCards 需要段落边界） */
  function normKeepPara(s) {
    return String(s == null ? '' : s)
      .replace(/[\u2019\u2018]/g, "'")
      .replace(/[\u201c\u201d]/g, '"')
      .replace(/\u2014/g, '\u2013')
      .replace(/[ \t]+/g, ' ')
      .replace(/\s*\n\s*/g, '\n')
      .trim();
  }

  /* 代码切卡兜底：把原文切成**恰好 target 张**。
     为什么必须有它：实测模型给的 b2_card_starts 项数 = **原文自然段数** ——
     5 个自然段的原文它只给 5 个锚点，B2+ 就只有 5 张卡，四档永远对不齐；
     而单段原文它就乖乖给 10 个（已用 436 词单段 / 463 词五段做过对照实验）。
     两版提示词加压（点明「锚点项数=卡数≠段落数」+ 交稿自查清单）均无效 ——
     模型不会真的数字数。所以这件「错了会静默」的事交给代码。
     切法：句子是最小单位（绝不切坏句子）；切点取累计词数 k*总词数/target 处，
     距离相当（≤6 词）时**优先落在段落边界**上，保住语义单元。 */
  function splitToCards(orig, target) {
    var paras = normKeepPara(orig).split('\n')
      .map(function (p) { return p.trim(); }).filter(function (p) { return p; });
    if (!paras.length) return null;
    var units = [];
    paras.forEach(function (p) {
      var ss = sentences(p);
      ss.forEach(function (s, si) {
        units.push({ text: s, wc: words(s).length, paraEnd: si === ss.length - 1 });
      });
    });
    var m = units.length;
    if (m < target) return null;                    // 句子比卡还少，切不出来
    var total = 0, cum = [0];
    units.forEach(function (u) { total += u.wc; cum.push(total); });
    if (!total) return null;
    var cuts = [], prev = 0;
    for (var k = 1; k < target; k++) {
      var ideal = total * k / target;
      var lo = prev + 1, hi = m - (target - k);
      var best = -1, bestD = Infinity, bestPara = false;
      for (var j = lo; j <= hi; j++) {
        var d = Math.abs(cum[j] - ideal), pe = !!units[j - 1].paraEnd, better = false;
        if (best < 0) better = true;
        else if (Math.abs(d - bestD) <= 6) { if (pe && !bestPara) better = true; }
        else if (d < bestD) better = true;
        if (better) { best = j; bestD = d; bestPara = pe; }
      }
      cuts.push(best); prev = best;
    }
    var cards = [], from = 0;
    cuts.concat([m]).forEach(function (to) {
      var t = [];
      for (var q = from; q < to; q++) t.push(units[q].text);
      cards.push(t.join(' ').trim());
      from = to;
    });
    return { cards: cards, words: total, sentences: m };
  }

  /* 低级别卡数对齐（**只重新分组，一个字都不改**）：
     模型给的 A1-/A2/B1 卡片数实测在 10–18 之间抖 —— 同一个提示词、同一个温度，
     两次跑出来 10 张和 18 张都有。而母稿卡数由代码钉死。
     与其回炉重写（实测越修越乱，词数还会反弹到 98%），不如按顺序把相邻卡合并成母稿的张数：
     文本逐字不变、只是重新分组，所以词数 / 句长 / 主题词这些判定结果一个字都不差。
     卡数**少于**母稿时没法合并（凭空拆分等于让代码编正文），返回 null ——
     这种交给 check() 判错、走回炉。 */
  function alignCards(cards, target) {
    var n = cards.length;
    if (!n) return null;
    if (n === target) return { cards: cards.slice(), changed: false };
    if (n < target) return null;
    var wc = cards.map(function (c) { return words(c).length; });
    var cum = [0];
    wc.forEach(function (w) { cum.push(cum[cum.length - 1] + w); });
    var total = cum[n];
    var cuts = [], prev = 0;
    for (var k = 1; k < target; k++) {
      var ideal = total * k / target;
      var lo = prev + 1, hi = n - (target - k);
      var best = lo, bestD = Infinity;
      for (var j = lo; j <= hi; j++) {
        var d = Math.abs(cum[j] - ideal);
        if (d < bestD) { bestD = d; best = j; }
      }
      cuts.push(best); prev = best;
    }
    var out = [], from = 0;
    cuts.concat([n]).forEach(function (to) {
      out.push(cards.slice(from, to).join(' ').replace(/\s+/g, ' ').trim());
      from = to;
    });
    return { cards: out, changed: true };
  }

  /* 逐卡词数预算表：把「占原文 30–42%」这种百分比，换成**每张卡具体要写多少词**。
     实测动机：百分比模型算不动 —— 它写出来总是**恰好超上限 5–7 个百分点**
     （A1- 45–47% / A2 64–67% / B1 80–85%），三轮回炉都压不进带。
     换成具体数字（「第 5 张写 14–19 词」）它才照得住。这张表由代码算，确定性。 */
  /* 预算靶心**内缩**到硬区间的 25%–85% 分位。
     实测动机：把区间上界直接当预算给，模型就往上界写、还偶尔擦边超（B1 360 vs 上限 358）。
     给一个偏中段的靶心，它才有余量落进硬区间。**验收标准不动**，这里只是施工指导。 */
  /* 靶心取区间的**下半段**（15%~65%），不是中段。实测：模型系统性超写 3~5%，
     靶心放中点会让它正好顶破硬区间上界（A1- 实测 195 词 vs 上界 193，就差 2 个词）。
     把靶心下移留出余量，比事后回炉便宜得多。 */
  function band(lv) {
    var lo = RATIO[lv][0], hi = RATIO[lv][1], d = hi - lo;
    return [lo + d * 0.15, lo + d * 0.65];
  }

  /* 模型在该级别的「自然句长」（实测值）—— 用来把词数预算折成句数。
     为什么必须给句数：词数 = 句数 × 句长，而低级别写出来天然就是 6–9 词的短句，
     于是「顺手多写一句」就是超词数最常见的原因。只给词数，模型数不准；
     把句数先写死，词数才是从句数长出来的。 */
  var NAT_SENT = { 'A1-': 8, 'A2': 10, 'B1': 13 };

  function budgetTable(masterCards) {
    var total = 0;
    var lines = ['每张卡的词数预算（= 母稿该卡词数 × 档位比例，代码算好）。'
      + '写法照抄「词数 + 约几句」，不要自己估：'];
    masterCards.forEach(function (c, i) {
      var n = words(c).length; total += n;
      var seg = ['A1-', 'A2', 'B1'].map(function (lv) {
        var b = band(lv);
        var mid = n * (b[0] + b[1]) / 2;
        var sc = Math.max(1, Math.round(mid / NAT_SENT[lv]));
        return lv + ' ' + Math.round(n * b[0]) + '–' + Math.round(n * b[1])
          + ' 词（约 ' + sc + ' 句）';
      });
      lines.push('[' + (i + 1) + '] 母稿 ' + n + ' 词　→　' + seg.join(' ｜ '));
    });
    var sum = ['A1-', 'A2', 'B1'].map(function (lv) {
      var b = band(lv);
      return lv + ' ' + Math.round(total * b[0]) + '–' + Math.round(total * b[1]) + ' 词';
    });
    lines.push('合计（全文）：' + sum.join(' ｜ '));
    /* 死线单独列一行：模型的系统性超写只靠「靶心」约束不住，必须把不可越过的上界
       用绝对词数写死（不是百分比 —— 它算不动百分比）。 */
    var ceil = ['A1-', 'A2', 'B1'].map(function (lv) {
      return lv + ' ≤ ' + Math.floor(total * RATIO[lv][1]) + ' 词';
    });
    lines.push('🔴 死线（越线即不合格，必须回头删）：' + ceil.join(' ｜ '));
    return lines.join('\n');
  }

  /* 与工具包 check() 同判据：返回 {stats, errs, warns} */
  function check(data, cardsByLevel) {
    var errs = [], warns = [], stats = [];
    var b2 = cardsByLevel['B2+'] || [];
    var n = b2.length;
    var origWc = words(b2.join(' ')).length;

    /* 卡数规格：固定 10 张（原文超长才到 12 张），**不随原文的段落数变**。
       实测踩坑：原文是 5 个自然段时，模型顺着段落切成 5 张 —— 每张卡信息量翻倍，
       低级别为了保住事实只能写长句，句长硬上限反而破了。
       所以卡数要单独判：原文词数够切 10 张却没切够 ⇒ 硬错误，把差量带回上一环。 */
    if (n > CARD_MAX) {
      errs.push('切了 ' + n + ' 张卡，超过上限 ' + CARD_MAX + ' 张');
    } else if (n < CARD_MIN) {
      var msg = '只切了 ' + n + ' 张卡，规格是 ' + CARD_MIN + ' 张（原文超长才到 ' + CARD_MAX + ' 张）。'
        + '卡片边界不是段落边界：原文的自然段只是排版，一段要拆成好几张卡，'
        + '不要一段一张。按「每张卡约 ' + Math.round(origWc / CARD_MIN) + ' 词」来分。';
      if (origWc >= 250) errs.push(msg); else warns.push(msg);
    }

    LEVELS.forEach(function (lv) {
      var cards = cardsByLevel[lv] || [];
      var text = cards.join(' ');
      var textLower = norm(text).toLowerCase();
      var wc = words(text).length;

      if (cards.length !== n) {
        errs.push(lv + ' 有 ' + cards.length + ' 张卡，B2+ 有 ' + n + ' 张 —— 卡片没对齐');
      }

      var lens = sentences(text).map(function (s) { return words(s).length; });
      var ratio = origWc ? wc / origWc : 0;
      stats.push({
        level: lv, cards: cards.length, wc: wc, ratio: ratio,
        avg: lens.length ? lens.reduce(function (a, b) { return a + b; }, 0) / lens.length : 0,
        max: lens.length ? Math.max.apply(null, lens) : 0,
        min: lens.length ? Math.min.apply(null, lens) : 0
      });

      if (RATIO[lv]) {
        var lo = RATIO[lv][0], hi = RATIO[lv][1];
        if (!(ratio >= lo && ratio <= hi)) {
          errs.push(lv + ' 词数 ' + wc + '（' + Math.round(ratio * 100) + '%），目标 '
                    + Math.round(lo * 100) + '–' + Math.round(hi * 100) + '%，即 '
                    + Math.floor(lo * origWc) + '–' + Math.floor(hi * origWc) + ' 词');
        }
        cards.forEach(function (c, ci) {
          sentences(c).forEach(function (s) {
            var k = words(s).length;
            if (k > MAX_SENT[lv]) {
              errs.push(lv + ' 卡' + numMark(ci) + ' 句子 ' + k + ' 词 > ' + MAX_SENT[lv] + '：' + s);
            } else if (k < MIN_SENT[lv]) {
              warns.push(lv + ' 卡' + numMark(ci) + ' 句子 ' + k + ' 词 < ' + MIN_SENT[lv] + '：' + s);
            }
          });
        });
        var low = ' ' + textLower.replace(/[^a-z' ]/g, ' ') + ' ';
        (FLAG_WORDS[lv] || []).forEach(function (w) {
          if (low.indexOf(' ' + w + ' ') >= 0) {
            warns.push(lv + ' 出现可能超纲的 "' + w + '"，请人工确认');
          }
        });
      }

      // 主题词：每一档都必须出现，且不得替换成同义的简单词
      (data.topic_words || []).forEach(function (tw) {
        if (!new RegExp('\\b' + esc(String(tw)) + '\\b', 'i').test(text)) {
          errs.push(lv + ' 缺少主题词 "' + tw + '"');
        }
      });

      // 题目
      var qs = (((data.levels || {})[lv] || {}).questions) || [];
      if (qs.length !== 3) errs.push(lv + ' 题目数量 ' + qs.length + '，应为 3');
      qs.forEach(function (q, qi) {
        if (((q.options || []).length) !== 4) errs.push(lv + ' Q' + (qi + 1) + ' 选项不是 4 个');
        if (!/^[ABCD]$/.test(q.answer || '')) errs.push(lv + ' Q' + (qi + 1) + ' 答案字母无效');
        quotedEnglish(q.explanation || '').forEach(function (quote) {
          if (!sub(quote, textLower)) {
            errs.push(lv + ' Q' + (qi + 1) + ' 解析引用的英文在本级正文里找不到："' + quote + '"');
          }
        });
        quotedEnglish(q.q || '').forEach(function (quote) {
          if (!sub(quote, textLower)) {
            errs.push(lv + ' Q' + (qi + 1) + ' 题干引用的英文在本级正文里找不到："' + quote + '"');
          }
        });
      });
      var answers = qs.map(function (q) { return q.answer; });
      if (answers.length === 3 && answers[0] && answers[0] === answers[1] && answers[1] === answers[2]) {
        warns.push(lv + ' 三道题答案都是 ' + answers[0]);
      }
    });

    return { stats: stats, errs: errs, warns: warns, origWc: origWc, cardCount: n };
  }

  /* 一次跑完整轮：定母稿卡 → 低档卡数对齐 → 逐档对照 → 出报告
     masterCards 由调用方（页面）用 splitToCards 算好传进来 ——
     这样**每一轮回炉都用同一套母稿切分**，跨轮可比、可择优；
     离线测试不传时，才回退到「用模型锚点 / 代码兜底」的老逻辑。 */
  function run(data, originalText, masterCards) {
    var base = { ok: false, fatal: '', errs: [], warns: [], stats: [], cardsByLevel: null,
                 origWc: 0, cardCount: 0, splitNote: '', splitWarn: false };
    if (!data || typeof data !== 'object') { base.fatal = '没有拿到卡片数据'; base.errs = [base.fatal]; return base; }
    var b2 = null, why = '';
    if (Array.isArray(masterCards) && masterCards.length) {
      /* 主路径：母稿卡由代码切好、直接给定（切分不交给模型） */
      b2 = masterCards.map(function (c) { return norm(c); }).filter(function (c) { return c; });
      base.splitNote = '母稿由代码切成 ' + b2.length + ' 张卡 —— 切卡不交给模型，'
        + '四档都按这 ' + b2.length + ' 张对齐。';
    } else {
      /* 回退路径：模型锚点必须同时过两关（个数在规格内、严格按原文顺序） */
      var starts = data.b2_card_starts || [];
      if (starts.length >= CARD_MIN && starts.length <= CARD_MAX) {
        var v = validateStarts(originalText, starts);
        if (v.ok) {
          try {
            b2 = splitOriginal(originalText, starts);
          } catch (e) {
            why = e && e.message ? e.message : String(e);
          }
        } else {
          why = v.reason;
        }
      } else {
        why = '个数是 ' + starts.length + ' 个，规格是 ' + CARD_MIN + ' 个';
      }
      if (!b2) {
        /* 模型锚点不可用 → 代码兜底重切。**必须说明，不静默** */
        var auto = splitToCards(originalText, CARD_MIN);
        if (!auto) {
          base.fatal = '模型的卡片锚点不可用（' + why + '），代码也没法把原文切成 '
            + CARD_MIN + ' 张（原文句子数不足 ' + CARD_MIN + '）——请换一篇更长的原文';
          base.errs = [base.fatal];
          return base;
        }
        b2 = auto.cards;
        base.splitNote = '模型的卡片锚点不可用（' + why + '）——已由代码按「句子完整、'
          + '段落边界优先」重切成 ' + b2.length + ' 张母稿卡，四档都按这 ' + b2.length
          + ' 张对齐。原文共 ' + auto.sentences + ' 句 / ' + auto.words + ' 词。';
        base.splitWarn = true;
      }
    }
    var raw = {
      'A1-': ((data.levels || {})['A1-'] || {}).cards || [],
      'A2': ((data.levels || {})['A2'] || {}).cards || [],
      'B1': ((data.levels || {})['B1'] || {}).cards || []
    };
    var cards = { 'B2+': b2 }, alignNotes = [];
    ['A1-', 'A2', 'B1'].forEach(function (lv) {
      var a = alignCards(raw[lv], b2.length);
      if (a) {
        cards[lv] = a.cards;
        if (a.changed) {
          alignNotes.push(lv + ' 模型给了 ' + raw[lv].length + ' 张卡，已按顺序合并成 '
            + b2.length + ' 张（文字一个字没改，只是重新分组）');
        }
      } else {
        cards[lv] = raw[lv];          // 少于母稿：合并不了，交给 check() 判错走回炉
      }
    });

    var r = check(data, cards);
    r.cardsByLevel = cards;
    r.ok = r.errs.length === 0;
    r.fatal = '';
    /* ⚠️ check() 返回的是自己的对象 —— base 上写的东西必须**显式带过去**，
       否则「切卡兜底」「合并对齐」这些说明会被静默丢掉（踩过一次）。 */
    r.splitNote = base.splitNote;
    r.alignNotes = alignNotes;
    if (base.splitWarn && base.splitNote) r.warns.unshift(base.splitNote);
    alignNotes.forEach(function (n) { r.warns.unshift(n); });
    return r;
  }

  var API = {
    LEVELS: LEVELS, RATIO: RATIO, MAX_SENT: MAX_SENT, MIN_SENT: MIN_SENT,
    CARD_MIN: CARD_MIN, CARD_MAX: CARD_MAX,
    FLAG_WORDS: FLAG_WORDS, NUMS: NUMS, numMark: numMark,
    norm: norm, words: words, sentences: sentences, quotedEnglish: quotedEnglish,
    splitOriginal: splitOriginal, splitToCards: splitToCards, alignCards: alignCards,
    validateStarts: validateStarts,
    normKeepPara: normKeepPara, budgetTable: budgetTable, band: band,
    check: check, run: run
  };

  root.CardCheck = API;
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
})(typeof self !== 'undefined' ? self : this);
