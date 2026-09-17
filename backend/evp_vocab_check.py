#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ReadPal · 词汇分级校验原型（EVP 词表）

依据 English Vocabulary Profile (EVP) 对一篇英文文章做「词汇超纲」判定。
口径：对每个 Base Word 取「最低等级」；文章里的实词经词形还原后，若其
最低等级 > 目标档位，记为「超纲词」。

词表来源：wordlist.xlsx（EVP，15696 词条 → 9751 去重词头）
用法：
    python3 evp_vocab_check.py --file=文章.md --level=A1
    python3 evp_vocab_check.py --text="..." --level=B1
"""

import json
import os
import re
import sys

# 等级顺序（A1 最简单，C2 最难）
LV_ORDER = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}
# 目标档允许的累计词表边界：A1 档只允许 ≤A1，B2+ 档允许 ≤B2（可配少量 C1）
# 这里 B2 档默认允许到 B2（不含 C1/C2）。
LEVEL_CAP = {"A1": "A1", "A2": "A2", "B1": "B1", "B2": "B2"}
# 超纲率阈值（超了判 exceed，前端据此重试）——A1 词表很抠，阈值放宽
VOCAB_THRESHOLD = {"A1": 0.05, "A2": 0.04, "B1": 0.03, "B2": 0.02}

# ---------- 词表 ----------
_WORDLIST_PATH = os.path.join(os.path.dirname(__file__), "evp_wordlist.json")
_wordlist = None


def load_wordlist():
    global _wordlist
    if _wordlist is None:
        with open(_WORDLIST_PATH, encoding="utf-8") as f:
            _wordlist = json.load(f)
    return _wordlist


# ---------- 不规则变化表（词形 -> 词头）----------
# 覆盖高频不规则动词与不规则名词复数
_IRREGULAR = {
    # be 族
    "am": "be", "is": "be", "are": "be", "was": "be", "were": "be",
    "been": "be", "being": "be",
    # have 族
    "has": "have", "had": "have", "having": "have",
    # do 族
    "does": "do", "did": "do", "done": "do", "doing": "do",
    # go 族
    "went": "go", "gone": "go", "going": "go", "goes": "go",
    # 其他高频不规则动词
    "made": "make", "making": "make", "makes": "make",
    "took": "take", "taken": "take", "taking": "take", "takes": "take",
    "saw": "see", "seen": "see", "seeing": "see", "sees": "see",
    "came": "come", "coming": "come", "comes": "come",
    "knew": "know", "known": "know", "knowing": "know", "knows": "know",
    "got": "get", "gotten": "get", "getting": "get", "gets": "get",
    "gave": "give", "given": "give", "giving": "give", "gives": "give",
    "found": "find", "finding": "find", "finds": "find",
    "thought": "think", "thinking": "think", "thinks": "think",
    "told": "tell", "telling": "tell", "tells": "tell",
    "became": "become", "becoming": "become", "becomes": "become",
    "showed": "show", "shown": "show", "showing": "show", "shows": "show",
    "left": "leave", "leaving": "leave", "leaves": "leave",
    "felt": "feel", "feeling": "feel", "feels": "feel",
    "put": "put", "putting": "put", "puts": "put",
    "brought": "bring", "bringing": "bring", "brings": "bring",
    "began": "begin", "begun": "begin", "beginning": "begin", "begins": "begin",
    "kept": "keep", "keeping": "keep", "keeps": "keep",
    "held": "hold", "holding": "hold", "holds": "hold",
    "wrote": "write", "written": "write", "writing": "write", "writes": "write",
    "stood": "stand", "standing": "stand", "stands": "stand",
    "heard": "hear", "hearing": "hear", "hears": "hear",
    "meant": "mean", "meaning": "mean", "means": "mean",
    "met": "meet", "meeting": "meet", "meets": "meet",
    "ran": "run", "run": "run", "running": "run", "runs": "run",
    "paid": "pay", "paying": "pay", "pays": "pay",
    "sat": "sit", "sitting": "sit", "sits": "sit",
    "spoke": "speak", "spoken": "speak", "speaking": "speak", "speaks": "speak",
    "led": "lead", "leading": "lead", "leads": "lead",
    "grew": "grow", "grown": "grow", "growing": "grow", "grows": "grow",
    "lost": "lose", "losing": "lose", "loses": "lose",
    "fell": "fall", "fallen": "fall", "falling": "fall", "falls": "fall",
    "sent": "send", "sending": "send", "sends": "send",
    "built": "build", "building": "build", "builds": "build",
    "understood": "understand", "understanding": "understand", "understands": "understand",
    "drew": "draw", "drawn": "draw", "drawing": "draw", "draws": "draw",
    "broke": "break", "broken": "break", "breaking": "break", "breaks": "break",
    "spent": "spend", "spending": "spend", "spends": "spend",
    "rose": "rise", "risen": "rise", "rising": "rise", "rises": "rise",
    "drove": "drive", "driven": "drive", "driving": "drive", "drives": "drive",
    "bought": "buy", "buying": "buy", "buys": "buy",
    "wore": "wear", "worn": "wear", "wearing": "wear", "wears": "wear",
    "chose": "choose", "chosen": "choose", "choosing": "choose", "chooses": "choose",
    "taught": "teach", "teaching": "teach", "teaches": "teach",
    "caught": "catch", "catching": "catch", "catches": "catch",
    "fought": "fight", "fighting": "fight", "fights": "fight",
    "sold": "sell", "selling": "sell", "sells": "sell",
    "won": "win", "winning": "win", "wins": "win",
    "threw": "throw", "thrown": "throw", "throwing": "throw", "throws": "throw",
    "wore": "wear", "worn": "wear", "wearing": "wear", "wears": "wear",
    "flew": "fly", "flown": "fly", "flying": "fly", "flies": "fly",
    "swam": "swim", "swum": "swim", "swimming": "swim", "swims": "swim",
    "sang": "sing", "sung": "sing", "singing": "sing", "sings": "sing",
    "rang": "ring", "rung": "ring", "ringing": "ring", "rings": "ring",
    "ate": "eat", "eaten": "eat", "eating": "eat", "eats": "eat",
    "drank": "drink", "drunk": "drink", "drinking": "drink", "drinks": "drink",
    "slept": "sleep", "sleeping": "sleep", "sleeps": "sleep",
    "forgot": "forget", "forgotten": "forget", "forgetting": "forget", "forgets": "forget",
    # 不规则名词复数
    "children": "child", "men": "man", "women": "woman", "people": "person",
    "feet": "foot", "teeth": "tooth", "mice": "mouse",
    # 其他高频
    "said": "say", "saying": "say", "says": "say",
    "read": "read", "reading": "read", "reads": "read",
}


def _dedouble(w):
    """双写辅音还原：running->runn->run；stopped->stopp->stop"""
    if len(w) >= 3 and w[-1] == w[-2]:
        return w[:-1]
    return w


def lemmatize(word):
    """词形 -> 词头（还原优先：ing/ed/s 先还原，learning->learn 而非 learning(B2 名词)）。"""
    w = word.lower()
    wl = load_wordlist()
    # 1. 不规则表优先
    if w in _IRREGULAR:
        base = _IRREGULAR[w]
        return base, base in wl
    # 规则后缀剥离（逐个尝试，命中即止）
    candidates = []
    if w.endswith("ies") and len(w) > 4:
        candidates.append(w[:-3] + "y")           # studies -> study
    if w.endswith("ied") and len(w) > 4:
        candidates.append(w[:-3] + "y")           # studied -> study
    if w.endswith("es") and len(w) > 3:
        candidates.append(w[:-2])                 # boxes -> box
    if w.endswith("s") and len(w) > 2 and not w.endswith("ss"):
        candidates.append(w[:-1])                 # cats -> cat
    if w.endswith("ing") and len(w) > 4:
        candidates.append(w[:-3])                 # playing -> play
        candidates.append(_dedouble(w[:-3]))      # running -> run
        candidates.append(w[:-3] + "e")           # changing -> change / making -> make
    if w.endswith("ed") and len(w) > 3:
        candidates.append(w[:-2])                 # played -> play
        candidates.append(_dedouble(w[:-2]))      # stopped -> stop
        candidates.append(w[:-2] + "e")           # liked -> like
    if w.endswith("d") and len(w) > 2:
        candidates.append(w[:-1])                 # loved -> love
    if w.endswith("ly") and len(w) > 3:
        candidates.append(w[:-2])                 # quickly -> quick
        candidates.append(w[:-2][:-1] + "y")      # happily -> happy
    if w.endswith("er") and len(w) > 3:
        candidates.append(w[:-2])                 # bigger -> bigg
        candidates.append(_dedouble(w[:-2]))      # bigger -> big
        candidates.append(w[:-2][:-1] + "y")      # easier -> easy (easi -> easy)
    if w.endswith("est") and len(w) > 4:
        candidates.append(w[:-3])                 # biggest -> bigg
        candidates.append(_dedouble(w[:-3]))      # biggest -> big
        candidates.append(w[:-3][:-1] + "y")      # easiest -> easy (easi -> easy)
    for c in candidates:
        if c in wl:
            return c, True
    # 3. 原词兜底
    if w in wl:
        return w, True
    return w, False


# ---------- 校验 ----------
def tokenize(text):
    """提取英文单词 token（去标点、去数字）。返回 list[(token, is_capitalized)]"""
    toks = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)
    out = []
    for t in toks:
        low = t.lower()
        if low in ("s", "t", "re", "ll", "ve", "d", "m"):  # 缩写残留
            continue
        out.append((low, t[0].isupper()))
    return out


def check_vocab(text, level, topic_words=None):
    """
    校验一篇文章的词汇超纲情况。
    返回 dict: {over: [...], unknown: [...], over_rate, total_content_words}
    """
    cap_lv = LEVEL_CAP.get(level, "B2")
    wl = load_wordlist()
    toks = tokenize(text)
    # 首字母大写且不在句首的词，视为专名（人名/地名），排除
    # 简化处理：收集所有大写开头的词，若它们不在句首，当作专名
    over = []       # 超纲词
    unknown = []    # 表外词（不在词表，可能是专名/罕见词）
    seen = set()
    content_total = 0
    over_total = 0

    topic_set = set(t.lower() for t in (topic_words or []))

    # 句子切分，用于判断"句首词"（句首大写不算专名）
    sentences = re.split(r'(?<=[.!?])\s+', text)
    for si, sent in enumerate(sentences):
        stoks = tokenize(sent)
        for ti, (tok, is_cap) in enumerate(stoks):
            if tok in topic_set:
                continue  # topic words 豁免
            # 专名判定：大写开头 + 非句首 + 不在词表（专名通常不在 EVP）
            if is_cap and ti > 0 and tok not in wl:
                continue  # 视为专名，排除
            base, hit = lemmatize(tok)
            if not hit:
                unknown.append(tok)
                continue
            content_total += 1
            base_lv = wl[base]
            if LV_ORDER[base_lv] > LV_ORDER[cap_lv]:
                over_total += 1
                if base not in seen:
                    seen.add(base)
                    over.append((base, base_lv))

    over_rate = (over_total / content_total) if content_total else 0.0
    thr = VOCAB_THRESHOLD.get(level, 0.03)
    return {
        "level": level, "cap": cap_lv,
        "content_words": content_total,
        "over_count": over_total,
        "over_rate": round(over_rate, 4),
        "threshold": thr,
        "exceed": over_rate > thr,
        "over_words": over,
        "unknown_words": sorted(set(unknown)),
    }


def check_vocab_batch(articles, words_map=None):
    """批量校验：articles = {level: text}，返回 {level: result}。
    words_map 可选，{level: [topic_words]}，用于豁免生词表（不计超纲）。"""
    out = {}
    for lv, text in (articles or {}).items():
        if lv not in LEVEL_CAP or not text:
            continue
        tw = (words_map or {}).get(lv)
        out[lv] = check_vocab(text, lv, topic_words=tw)
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--text")
    ap.add_argument("--level", default="B1", choices=list(LV_ORDER.keys()))
    args = ap.parse_args()

    if args.file:
        text = open(args.file, encoding="utf-8").read()
    elif args.text:
        text = args.text
    else:
        ap.print_help()
        sys.exit(1)

    r = check_vocab(text, args.level)
    print(f"目标档位 {args.level}（允许 ≤{r['cap']}）")
    print(f"实词数 {r['content_words']} / 超纲 {r['over_count']} / 超纲率 {r['over_rate']*100:.1f}%")
    print(f"超纲词（top 30）: {[w for w, l in r['over_words'][:30]]}")
    print(f"表外词（top 20）: {r['unknown_words'][:20]}")
