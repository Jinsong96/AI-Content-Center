"""关卡一：确定性质检内核。

来源：移植自佳阳老师《分级卡片工具包》build_cards.py 的 check() / split_original()。
三处增强（原脚本没有）：
  1. 结构化输出 —— 每条问题带 rule / level / target，前端可点击定位到具体卡片或题目
  2. 新增第 12 类 —— 关键专有名词（人名）保留检查。老师方法论明确要求
     「A1- 关键人名必须保留，可加同位语（Graves, a scientist），不可泛称替代（A scientist）」，
     但原脚本对此 0 行代码。
  3. 切卡失败降级为一条 error，不再抛异常终止整篇处理。

规则口径与老师脚本逐条保持一致，未作改动。
"""
import re

NUMS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
LEVELS = ["A1-", "A2", "B1", "B2+"]
GRADED = ["A1-", "A2", "B1"]          # B2+ 是原文，不参与降级改写

# ---------- 质检参数（与老师脚本一致，按需可调） ----------
RATIO = {"A1-": (0.30, 0.42), "A2": (0.48, 0.60), "B1": (0.65, 0.78)}
MAX_SENT = {"A1-": 12, "A2": 16, "B1": 22}
MIN_SENT = {"A1-": 4, "A2": 5, "B1": 6}
FLAG_WORDS = {
    "A1-": ["may", "might", "if", "which", "whose", "who", "would", "could", "been",
            "should", "must", "although", "however", "while"],
    "A2": ["which", "whose", "might", "although", "whereas", "had been", "would have"],
    "B1": ["were i", "had i", "not only", "whereby"],
}

# ---------- 多义实词提醒（第 16 类，确定性，不判语境） ----------
# 同一个词在低级别容易被读成另一个义项，而"会不会读错"取决于语境 —— 那属于语义判断，
# 脚本做不了（实测：裁判在长输入下只有约一半概率发现）。所以这里只做**词形命中**：
# A1-/A2 里出现就提示人工确认。不算 error、不判对错；语境已经写清楚时属于误报，忽略即可。
# 清单刻意收窄：只放义项跨度大、且低级别读者最可能选错义项的词。**宁窄勿宽** —— 报得太密就没人看了。
POLYSEMY_WORDS = [
    "degree", "term", "state", "match", "order", "present", "figure",
    "charge", "board", "scale", "interest", "bank", "company", "class", "practice",
]
POLYSEMY_LEVELS = ["A1-", "A2"]

WORD = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")

# 专有名词启发式用的停用词：这些词虽然大写开头，但不是人名
PROPER_STOP = {
    "The", "A", "An", "In", "On", "At", "It", "He", "She", "They", "We", "You", "I",
    "This", "That", "These", "Those", "So", "But", "And", "Or", "Because", "When", "If",
    "For", "As", "Of", "To", "By", "With", "From", "His", "Her", "Their", "Our", "My",
    "Your", "Its", "There", "Then", "Now", "Today", "Tomorrow", "Yesterday", "Many",
    "Most", "Some", "All", "One", "Two", "Three", "First", "Second", "Third", "Last",
    "Next", "However", "Although", "While", "What", "Why", "How", "Who", "Which",
    "Where", "Do", "Does", "Did", "Is", "Are", "Was", "Were", "Be", "Been", "Being",
    "Have", "Has", "Had", "Can", "Could", "Will", "Would", "Shall", "Should", "May",
    "Might", "Must", "Not", "No", "Yes", "More", "Less", "Very", "Just", "Only", "Also",
    "Even", "Still", "Yet", "Such", "Other", "Another", "Each", "Every", "Both",
    "Either", "Neither", "Much", "Few", "Little", "According", "People", "Scientists",
    "Researchers", "American", "English", "Chinese", "British", "French", "German",
    "European", "Western", "Eastern", "Modern", "Science", "Scientists",
}


def norm(s):
    """统一引号与破折号，压缩空白。与老师脚本一致。"""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("—", "–")
    return re.sub(r"\s+", " ", s).strip()


def words(s):
    return WORD.findall(s)


def sentences(text):
    parts = re.split(r'(?<=[.?!])["\']?\s+(?=["\'A-Z0-9])', norm(text))
    return [p for p in parts if WORD.search(p)]


def quoted_english(s):
    """取出成对双引号里的纯英文片段（≥3 个词）。中文引语跳过。"""
    segs = norm(s).split('"')[1::2]
    return [q for q in segs if not re.search(r"[\u4e00-\u9fff]", q) and len(words(q)) >= 3]


def split_original(orig, starts):
    """按 b2_card_starts 把原文切成卡。行为与老师脚本一致，失败抛 ValueError。"""
    txt, pos, idx = norm(orig), 0, []
    for s in starts:
        i = txt.find(norm(s), pos)
        if i < 0:
            i = txt.lower().find(norm(s).lower(), pos)
        if i < 0:
            raise ValueError(f"原文里找不到卡片起始句：{s!r}")
        idx.append(i)
        pos = i + 1
    idx.append(len(txt))
    if idx[0] != 0:
        raise ValueError("第一张卡没有从原文开头开始，原文开头被漏掉了")
    return [txt[idx[k]:idx[k + 1]].strip() for k in range(len(starts))]


def proper_noun_candidates(text):
    """启发式提取疑似人名，返回姓氏列表。

    规则：句中连续两个首字母大写的词（跳过句首大写，过滤停用词），取第二个词作为姓。
    例：`Benjamin Franklin` → Franklin；`Philip Graves, a psychologist` → Graves。
    这条只用于新增的第 12 类检查，属启发式，可能有误判 —— 报告里会标注。
    """
    out = []
    for sent in sentences(text):
        ws = sent.split()
        for i in range(len(ws) - 1):
            a = re.sub(r"[^A-Za-z'\-]", "", ws[i])
            b = re.sub(r"[^A-Za-z'\-]", "", ws[i + 1])
            if len(a) < 3 or len(b) < 3:
                continue
            if not (a[0].isupper() and b[0].isupper()):
                continue
            if a.isupper() or b.isupper():        # 全大写多为缩写，跳过
                continue
            if i == 0 and a in PROPER_STOP:       # 句首普通词
                continue
            if a in PROPER_STOP or b in PROPER_STOP:
                continue
            if b not in out:
                out.append(b)
    return out


def _issue(rule, level, target, message, hint=None, hint_key=None, **params):
    """一条问题。

    message 是中文兜底文案（服务端内部、写入 fix_log、喂给重写模型时都用它）。
    params 是结构化参数，供前端按当前语言重新渲染 —— 同一份报告因此可以中英双语显示，
    而不必让脚本为每种语言各跑一遍。
    """
    item = {"rule": rule, "level": level, "target": target, "message": message}
    if params:
        item["params"] = params
    if hint:
        item["hint"] = hint
    if hint_key:
        item["hint_key"] = hint_key
    return item


def check(data, cards):
    """跑完整 16 类校验。cards 必须含四级（B2+ 由 split_original 得到）。"""
    errors, warnings, stats = [], [], []
    n_b2 = len(cards["B2+"])
    orig_wc = len(words(" ".join(cards["B2+"]))) or 1
    topic_words = data.get("topic_words") or []
    levels_data = (data.get("levels") or {})

    for lv in LEVELS:
        lv_cards = cards.get(lv) or []
        text = " ".join(lv_cards)
        wc = len(words(text))

        # 1. 卡片数对齐
        if len(lv_cards) != n_b2:
            errors.append(_issue("card_count_mismatch", lv, "article",
                                 f"{lv} 有 {len(lv_cards)} 张卡，B2+ 有 {n_b2} 张，卡片未对齐",
                                 "四个级别的卡片数必须相同，第 N 张卡讲同一件事",
                                 hint_key="card_count_mismatch",
                                 got=len(lv_cards), expected=n_b2))

        # 统计
        sents = sentences(text)
        L = [len(words(s)) for s in sents] or [0]
        stats.append({
            "level": lv,
            "words": wc,
            "ratio": round(wc / orig_wc, 4),
            "avg_sent": round(sum(L) / len(L), 1),
            "max_sent": max(L),
            "min_sent": min(L),
            "cards": len(lv_cards),
        })

        if lv in RATIO:
            # 2. 词数占比
            lo, hi = RATIO[lv]
            if not lo <= wc / orig_wc <= hi:
                errors.append(_issue(
                    "word_ratio", lv, "article",
                    f"{lv} 词数 {wc}（占原文 {wc / orig_wc:.0%}），目标 {lo:.0%}–{hi:.0%}"
                    f"，即 {int(lo * orig_wc)}–{int(hi * orig_wc)} 词",
                    words=wc, ratio=round(wc / orig_wc, 4), lo=lo, hi=hi,
                    min_words=int(lo * orig_wc), max_words=int(hi * orig_wc)))

            # 3 / 13. 句长
            for ci, c in enumerate(lv_cards):
                for s in sentences(c):
                    k = len(words(s))
                    if k > MAX_SENT[lv]:
                        errors.append(_issue(
                            "sentence_too_long", lv, f"card:{ci + 1}",
                            f"{lv} 卡{NUMS[ci]} 句子 {k} 词 > {MAX_SENT[lv]}：{s}",
                            card=ci + 1, n=k, max=MAX_SENT[lv], sentence=s))
                    elif k < MIN_SENT[lv]:
                        warnings.append(_issue(
                            "sentence_too_short", lv, f"card:{ci + 1}",
                            f"{lv} 卡{NUMS[ci]} 句子 {k} 词 < {MIN_SENT[lv]}：{s}",
                            card=ci + 1, n=k, min=MIN_SENT[lv], sentence=s))

            # 14. 超纲语法信号词（仅警告）
            low = " " + re.sub(r"[^a-z' ]", " ", norm(text).lower()) + " "
            for w in FLAG_WORDS.get(lv, []):
                if f" {w} " in low:
                    warnings.append(_issue(
                        "flag_word", lv, "article",
                        f"{lv} 出现可能超纲的 “{w}”，请人工确认",
                        word=w))

            # 16. 多义实词提醒（仅警告）—— 词形命中即提示，不判语境（详见文件头 POLYSEMY_WORDS 说明）
            if lv in POLYSEMY_LEVELS:
                for w in POLYSEMY_WORDS:
                    if re.search(rf"\b{w}(s|es|ed|ing)?\b", low):
                        warnings.append(_issue(
                            "polysemy_word", lv, "article",
                            f"{lv} 出现多义实词 “{w}”，请人工确认该级读者不会读成别的义项",
                            "多义实词在低级别容易被读成另一个义项（如 degree 被读成“30 度”）。"
                            "这条只按词形命中提示、不看语境 —— 语境已经写清楚时属于误报，可直接忽略。",
                            hint_key="polysemy_word", word=w))

        # 4. 主题词
        for tw in topic_words:
            if not re.search(rf"\b{re.escape(tw)}\b", text, re.I):
                errors.append(_issue(
                    "missing_topic_word", lv, "article",
                    f"{lv} 缺少主题词 “{tw}”",
                    "主题词在任何级别都不得替换成同义简单词",
                    hint_key="missing_topic_word", word=tw))

        # 题目
        qs = (levels_data.get(lv) or {}).get("questions") or []
        if len(qs) != 3:
            errors.append(_issue("question_count", lv, "article",
                                 f"{lv} 题目数量 {len(qs)}，应为 3",
                                 got=len(qs), expected=3))
        for qi, q in enumerate(qs, 1):
            # 6. 选项数
            if len(q.get("options") or []) != 4:
                errors.append(_issue("option_count", lv, f"q:{qi}",
                                     f"{lv} Q{qi} 选项不是 4 个",
                                     question=qi, expected=4))
            # 7. 答案字母
            if q.get("answer") not in list("ABCD"):
                errors.append(_issue("invalid_answer", lv, f"q:{qi}",
                                     f"{lv} Q{qi} 答案字母无效",
                                     question=qi))
            # 8. 解析引文必须逐字存在于本级正文
            for quote in quoted_english(q.get("explanation", "")):
                if quote.lower().strip(" .,") not in norm(text).lower():
                    errors.append(_issue(
                        "explanation_quote_missing", lv, f"q:{qi}",
                        f"{lv} Q{qi} 解析引用的句子在本级正文里找不到：\"{quote}\"",
                        question=qi, quote=quote))
            # 9. 题干引文同样
            for quote in quoted_english(q.get("q", "")):
                if quote.lower().strip(" .,") not in norm(text).lower():
                    errors.append(_issue(
                        "question_quote_missing", lv, f"q:{qi}",
                        f"{lv} Q{qi} 题干引用的内容在本级正文里找不到：\"{quote}\"",
                        question=qi, quote=quote))

        # 15. 三题答案字母全同（仅警告）
        answers = [q.get("answer") for q in qs]
        if len(answers) == 3 and len(set(answers)) == 1:
            warnings.append(_issue("same_answer_letters", lv, "article",
                                   f"{lv} 三道题答案都是 {answers[0]}",
                                   letter=answers[0]))

    # 12. 关键专有名词保留（新增）—— 只在 A1- 检查，因为它是最容易把人名泛化掉的一级
    a1_text = " ".join(cards.get("A1-") or [])
    candidates = proper_noun_candidates(" ".join(cards.get("B2+") or []))
    for name in candidates:
        if name not in a1_text:
            errors.append(_issue(
                "proper_noun_missing", "A1-", "article",
                f"A1- 未保留原文中的人名 “{name}”",
                "关键人名必须保留：可写成 “Graves, a scientist” 这种形态（原名 + 同位语说明身份），"
                "不能泛化成 “A scientist”。此条为启发式判断，如非关键人名可忽略。",
                hint_key="proper_noun_missing", name=name))

    return {"stats": stats, "errors": errors, "warnings": warnings}


def evaluate(article):
    """对一篇文章跑完整质检，返回 (报告, 四级卡片字典)。"""
    collected = []
    cards = {}
    for lv in GRADED:
        cards[lv] = ((article.get("levels") or {}).get(lv) or {}).get("cards") or []

    try:
        cards["B2+"] = split_original(article.get("original_text") or "",
                                      article.get("b2_card_starts") or [])
    except ValueError as e:
        cards["B2+"] = []
        collected.append(_issue("split_failed", "B2+", "article", str(e),
                                "检查 b2_card_starts 里每张卡开头的四个词，必须与原文逐字一致",
                                hint_key="split_failed", detail=str(e)))

    report = check(article, cards)
    report["errors"] = collected + report["errors"]
    report["passed"] = not report["errors"]
    report["error_count"] = len(report["errors"])
    report["warning_count"] = len(report["warnings"])
    return report, cards
