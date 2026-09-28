#!/usr/bin/env python3
"""
分级卡片：JSON -> docx + 自动质检（只用 Python 标准库，无需安装任何包）

目录结构（每篇文章一个文件夹）：
    articles/
      01_honesty/
        original.txt   # B2+ 原文（纯文本，粘贴即可）
        cards.json     # Claude 输出的 JSON
    template.docx      # 你们的模板（含 DocTitle / DocLevel 样式）

用法：
    python build_cards.py articles/01_honesty      # 处理一篇
    python build_cards.py articles                 # 处理 articles 下所有文件夹
输出：每个文件夹里生成 <标题>.docx 和 report.txt；终端打印汇总。
"""
import json, re, sys, zipfile, shutil
from pathlib import Path
from xml.sax.saxutils import escape

TEMPLATE = Path(__file__).with_name("template.docx")
NUMS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
LEVELS = ["A1-", "A2", "B1", "B2+"]

# ---------- 质检参数（按需调整） ----------
RATIO = {"A1-": (0.30, 0.42), "A2": (0.48, 0.60), "B1": (0.65, 0.78)}   # 相对原文词数
MAX_SENT = {"A1-": 12, "A2": 16, "B1": 22}
MIN_SENT = {"A1-": 4, "A2": 5, "B1": 6}
FLAG_WORDS = {   # 超纲语法信号词：只警告，不判错
    "A1-": ["may", "might", "if", "which", "whose", "who", "would", "could", "been",
            "should", "must", "although", "however", "while"],
    "A2": ["which", "whose", "might", "although", "whereas", "had been", "would have"],
    "B1": ["were i", "had i", "not only", "whereby"],
}

WORD = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")

def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("—", "–")
    return re.sub(r"\s+", " ", s).strip()

def words(s): return WORD.findall(s)

def sentences(text):
    parts = re.split(r'(?<=[.?!])["\']?\s+(?=["\'A-Z0-9])', norm(text))
    return [p for p in parts if WORD.search(p)]

def quoted_english(s):
    """取出成对双引号里的纯英文片段（≥3 个词），中文引语跳过"""
    segs = norm(s).split('"')[1::2]
    return [q for q in segs if not re.search(r"[\u4e00-\u9fff]", q) and len(words(q)) >= 3]

def split_original(orig, starts):
    orig, pos, idx = norm(orig), 0, []
    for s in starts:
        i = orig.find(norm(s), pos)
        if i < 0:
            i = orig.lower().find(norm(s).lower(), pos)
        if i < 0:
            raise ValueError(f"原文里找不到卡片起始句：{s!r}")
        idx.append(i); pos = i + 1
    idx.append(len(orig))
    if idx[0] != 0:
        raise ValueError("第一张卡没有从原文开头开始，原文开头被漏掉了")
    return [orig[idx[k]:idx[k + 1]].strip() for k in range(len(starts))]

def check(data, cards_by_level):
    errs, warns = [], []
    n = len(cards_by_level["B2+"])
    orig_wc = len(words(" ".join(cards_by_level["B2+"])))
    stats = []
    for lv in LEVELS:
        cards = cards_by_level[lv]
        text = " ".join(cards)
        wc = len(words(text))
        if len(cards) != n:
            errs.append(f"{lv} 有 {len(cards)} 张卡，B2+ 有 {n} 张，卡片没对齐")
        L = [len(words(s)) for s in sentences(text)]
        stats.append(f"{lv:4} 词数 {wc:4}  占原文 {wc / orig_wc:5.0%}  平均句长 {sum(L) / len(L):4.1f}  最长 {max(L)}  最短 {min(L)}")
        if lv in RATIO:
            lo, hi = RATIO[lv]
            if not lo <= wc / orig_wc <= hi:
                errs.append(f"{lv} 词数 {wc}（{wc / orig_wc:.0%}），目标 {lo:.0%}–{hi:.0%}，即 {int(lo * orig_wc)}–{int(hi * orig_wc)} 词")
            for ci, c in enumerate(cards):
                for s in sentences(c):
                    k = len(words(s))
                    if k > MAX_SENT[lv]:
                        errs.append(f"{lv} 卡{NUMS[ci]} 句子 {k} 词 > {MAX_SENT[lv]}：{s}")
                    elif k < MIN_SENT[lv]:
                        warns.append(f"{lv} 卡{NUMS[ci]} 句子 {k} 词 < {MIN_SENT[lv]}：{s}")
            low = " " + re.sub(r"[^a-z' ]", " ", norm(text).lower()) + " "
            for w in FLAG_WORDS.get(lv, []):
                if f" {w} " in low:
                    warns.append(f"{lv} 出现可能超纲的 “{w}”，请人工确认")
        for tw in data.get("topic_words", []):
            if not re.search(rf"\b{re.escape(tw)}\b", text, re.I):
                errs.append(f"{lv} 缺少主题词 “{tw}”")
        # 题目
        qs = data["levels"][lv].get("questions", [])
        if len(qs) != 3:
            errs.append(f"{lv} 题目数量 {len(qs)}，应为 3")
        for qi, q in enumerate(qs, 1):
            if len(q.get("options", [])) != 4:
                errs.append(f"{lv} Q{qi} 选项不是 4 个")
            if q.get("answer") not in "ABCD" or not q.get("answer"):
                errs.append(f"{lv} Q{qi} 答案字母无效")
            # 解析里引用的英文原句，必须能在本级正文里找到
            for quote in quoted_english(q.get("explanation", "")):
                if quote.lower().strip(" .,") not in norm(text).lower():
                    errs.append(f"{lv} Q{qi} 解析引用的句子在本级正文里找不到：\"{quote}\"")
            for quote in quoted_english(q.get("q", "")):
                if quote.lower().strip(" .,") not in norm(text).lower():
                    errs.append(f"{lv} Q{qi} 题干引用的内容在本级正文里找不到：\"{quote}\"")
        answers = [q.get("answer") for q in qs]
        if len(set(answers)) == 1 and len(answers) == 3:
            warns.append(f"{lv} 三道题答案都是 {answers[0]}")
    return stats, errs, warns

def para(style, text):
    t = escape(text, {'"': "&quot;", "'": "&apos;"})
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'

def build_docx(data, cards_by_level, out_path):
    with zipfile.ZipFile(TEMPLATE) as z:
        files = {n: z.read(n) for n in z.namelist()}
    src = files["word/document.xml"].decode("utf-8")
    head = src[: src.index("<w:body>") + len("<w:body>")]
    tail = src[src.index("<w:sectPr"):]
    body = [para("DocTitle", f'{data["title_en"]} {data["title_zh"]}')]
    for lv in LEVELS:
        body.append(para("DocLevel", lv))
        body += [para("Normal", f"{NUMS[i]} {c}") for i, c in enumerate(cards_by_level[lv])]
        body.append(para("DocLevel", "题目"))
        for qi, q in enumerate(data["levels"][lv]["questions"], 1):
            body.append(para("Normal", f"Q{qi}. {q['q']}"))
            body += [para("Normal", f"{'ABCD'[i]}. {o}") for i, o in enumerate(q["options"])]
            body.append(para("Normal", f"答案：{q['answer']}"))
            body.append(para("Normal", f"解析：{q['explanation']}"))
    files["word/document.xml"] = (head + "".join(body) + tail).encode("utf-8")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)

def process(folder: Path):
    raw = (folder / "cards.json").read_text(encoding="utf-8")
    raw = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", raw.strip())   # 容忍直接粘贴的代码块
    data = json.loads(raw)
    orig = (folder / "original.txt").read_text(encoding="utf-8")
    cards = {lv: data["levels"][lv]["cards"] for lv in LEVELS[:3]}
    cards["B2+"] = split_original(orig, data["b2_card_starts"])
    stats, errs, warns = check(data, cards)
    safe = re.sub(r'[\\/:*?"<>|]', "", f'{data["title_en"]} {data["title_zh"]}').strip()
    build_docx(data, cards, folder / f"{safe}.docx")
    lines = [f"== {folder.name}: {safe}", *stats]
    lines += [f"  ✗ {e}" for e in errs] + [f"  ! {w}" for w in warns]
    lines.append("  ✓ 通过" if not errs else f"  需修改 {len(errs)} 处")
    (folder / "report.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines), "\n")
    return not errs

if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "articles")
    folders = [root] if (root / "cards.json").exists() else sorted(p for p in root.iterdir() if (p / "cards.json").exists())
    ok = 0
    for f in folders:
        try:
            ok += process(f)
        except Exception as e:
            print(f"== {f.name}\n  ✗ 处理失败：{e}\n")
    print(f"共 {len(folders)} 篇，通过 {ok} 篇")
