#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把「多难度混排」的分级阅读 word，转成 ReadPal 内容后台导入格式。

产出（每篇一个输出目录）：
  <标题>_<难度>.docx          正文（无标题、无序号）
  <标题>_<难度>_母稿.docx      母稿正文（若该级标注了「母稿」）
  <标题>_题目.xlsx             题目（一个文件含全部难度，每难度一个工作表）

用法：
  python build_import_pack.py <源docx> <输出目录> [题目模板.xlsx]
只读源文件 + 另存新文件，绝不改源文件。
"""
import os
import re
import shutil
import sys
import zipfile
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS_DECL = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)

LEVEL_RE = re.compile(r"^(A1-|A1|A2|B1|B2\+|B2)\s*(?:版本)?\s*(?:[（(]\s*母稿[^）)]*[）)])?\s*$")
# 源文档写法 → 后台导入写法（Bryan 2026-09-24 确认：A1- 统一写成 A1）
LEVEL_OUT = {"A1-": "A1", "A1": "A1", "A2": "A2", "B1": "B1", "B2+": "B2+", "B2": "B2+"}
MOTHER_RE = re.compile(r"母稿")
QUIZ_LABEL_RE = re.compile(r"^(题目|练习题|Questions?)\s*([（(].*[）)])?\s*$")
CIRCLED = {c: i for i, c in enumerate("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳", 1)}
CIRCLED.update({c: i + 21 for i, c in enumerate("㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚", 0)})

NUM_PREFIX_RE = re.compile(r"^\s*[①-⑳㉑-㉚⑴-⒇]\s*")

# 段落引用：「卡片⑨」「card ⑦」「cards ⑦ to ⑨」，以及枚举式「卡片⑥、⑧和⑩」「卡片③⑤⑥」
# ⚠️ 2026-09-24 BBC 50篇实测：源文档里存在**复数 `cards`** 和 **`to` / `–` 作范围分隔符**
#    （`How do cards ⑦ to ⑨ relate to 第6段?`、`cards ③–⑥`），漏了就会留下裸圈号。
_CARD = r"(?:卡片|cards?|Cards?)"
_TOK = r"(?:[①-⑳㉑-㉚]|\d{1,2})"
# `to` 只在此处当范围词；不含半角 `-`（会误伤英文连字符）
_SEP = r"(?:和|及|与|到|至|to|~|、|，|,|/|and|–|—)"
CARD_REF_RE = re.compile(rf"{_CARD}\s*([①-⑳㉑-㉚]|\d{{1,2}})")
CARD_GROUP_RE = re.compile(
    rf"{_CARD}\s*({_TOK}(?:(?:\s*{_SEP}\s*|\s*){_TOK})*)", re.I
)

# ④ 无编号的泛指 `the last card` / `the last two cards` / `the cards about X`
#    ⚠️ 必须窄口径：**只认「the + [序数/数量] + card(s)」** 这一族。
#    源文里混杂着真实词义（`paying by card`、`People paid with cards instead of cash`、
#    `Cash is better than cards`、`credit and debit card transactions`），
#    它们都**不带定冠词 the**、也不带序数/数量词，因此天然落在白名单外、不会被误改。
_BARE_ORD = r"(?:last|first|second|third|fourth|fifth|final|next|other|remaining|previous|earlier|following|above)"
_BARE_CNT = r"(?:one|two|three|four|five)"
BARE_CARD_PARAGRAPH_RE = re.compile(
    rf"(?<![A-Za-z])(The|the)\s+((?:{_BARE_ORD}\s+)?(?:{_BARE_CNT}\s+)?)(cards?)(?![A-Za-z])"
)

OPT_MARK = re.compile(r"(?<![A-Za-z0-9])([A-H])\s*[.．、:：]\s*")
ANS_RE = re.compile(
    r"(?:答案|Answer|正确答案)\s*[:：]\s*([A-Ha-h](?:\s*[;；,，、]\s*[A-Ha-h])*)"
)
EXPL_RE = re.compile(r"(?:解析|Explanation)\s*[:：]\s*(.*)", re.S)
STEM_LABEL_RE = re.compile(
    r"^\s*(?:[（(][^）)]*[）)]\s*)?"
    r"|^\s*(?:语言|文本|逻辑|认知|Language|Text|Logic|Cognition)\s*(?:\([^)]*\)|·[^\s]*)*\s*"
)


def para_text(p):
    return "".join(t.text or "" for t in p.iter(W + "t"))


def load_paragraphs(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    body = ET.fromstring(xml).find(W + "body")
    out = []
    for el in body:
        if el.tag != W + "p":
            continue
        txt = para_text(el).strip()
        if not txt:
            continue
        pPr = el.find(W + "pPr")
        style = ""
        if pPr is not None:
            ps = pPr.find(W + "pStyle")
            if ps is not None:
                style = ps.get(W + "val") or ""
        out.append((txt, style))
    return out


def parse_docx(path):
    paras = load_paragraphs(path)
    title = None
    for txt, style in paras:
        if style.lower() in ("doctitle", "title"):
            title = txt
            break

    levels, order = {}, []
    cur = cur_kind = None
    for txt, style in paras:
        if title is not None and txt == title and style.lower() in ("doctitle", "title"):
            continue
        m = LEVEL_RE.match(txt)
        if m and style.lower() in ("doclevel", ""):
            lv = LEVEL_OUT[m.group(1)]
            if lv in levels:
                lv += "#2"
            levels[lv] = {"body": [], "quiz": [], "mother": bool(MOTHER_RE.search(txt))}
            order.append(lv)
            cur, cur_kind = lv, "body"
            continue
        if cur is None:
            if title is None:
                title = txt
            continue
        if QUIZ_LABEL_RE.match(txt) and len(txt) < 60:
            cur_kind = "quiz"
            if txt.startswith("练习题"):
                levels[cur]["quiz"].append((txt, style))
            continue
        levels[cur][cur_kind].append((txt, style))
    if title is None:
        title = os.path.splitext(os.path.basename(path))[0]
    # 母稿判定：优先用文档里显式标的「母稿」，没标就取最高等级（Bryan 2026-09-24 定）
    if order and not any(levels[lv]["mother"] for lv in order):
        levels[order[-1]]["mother"] = True
        levels[order[-1]]["mother_inferred"] = True
    return title, levels, order


def fix_refs(text):
    """卡片引用 → 段落引用。

    ① 枚举式先处理：「卡片⑥、⑧和⑩」→「第6段、第8段和第10段」（分隔符原样保留）
    ② 单个引用：「卡片⑨」/「card ⑦」→「第9段」/「第7段」
    ③ 零散说法：「前一张卡说」→「前一段说」
    ④ 英文泛指（不带编号）：「the last card」→「the last paragraph」
       （只认「the + 序数/数量 + card(s)」；`paying by card` 这类真实词义不动）
    """
    def num(tok):
        n = CIRCLED.get(tok)
        if n is None and tok.isdigit():
            n = int(tok)
        return n

    def rep_group(m):
        s = m.group(1)
        out, last = [], 0
        for t in re.finditer(_TOK, s):
            out.append(s[last:t.start()])
            n = num(t.group(0))
            out.append(f"第{n}段" if n else t.group(0))
            last = t.end()
        out.append(s[last:])
        return "".join(out)

    text = CARD_GROUP_RE.sub(rep_group, text)
    text = CARD_REF_RE.sub(lambda m: f"第{num(m.group(1))}段" if num(m.group(1)) else m.group(0), text)
    # ③ 零散说法：「同一张卡片里」→「同一段里」、「前一张卡说」→「前一段说」。
    #    顺序不能反：必须先吃下更长的「张卡片」，否则先替「卡片」会把
    #    「同一张卡片里」拆成「同一张段里」（2026-09-24 中国文化批实测踩到）。
    text = text.replace("张卡片", "段")
    text = text.replace("张卡", "段")
    text = text.replace("卡片", "段")

    # ④ 英文泛指：the last card → the last paragraph（保留 the 的原始大小写）
    def rep_bare(m):
        art, mid, w = m.group(1), m.group(2), m.group(3)
        return f"{art} {mid}{'paragraphs' if w[-1].lower() == 's' else 'paragraph'}"

    text = BARE_CARD_PARAGRAPH_RE.sub(rep_bare, text)
    return text


def clean_body(text):
    return NUM_PREFIX_RE.sub("", text).strip()


def split_inline_options(line):
    """把 'A. x B. y C. z D. w' 拆成 ['A. x', 'B. y', ...]"""
    pos = [m.start() for m in OPT_MARK.finditer(line)]
    if len(pos) < 2:
        return [line]
    return [line[a:b].strip() for a, b in zip(pos, pos[1:] + [len(line)])]


def parse_one(raw):
    """raw 是一道题的原文（可含换行）。返回 dict 或 None"""
    raw = raw.replace("*", "").strip()
    expl = ""
    m = EXPL_RE.search(raw)
    if m:
        expl = m.group(1).strip()
        raw = raw[: m.start()]
    ans = ""
    m = ANS_RE.search(raw)
    if m:
        ans = re.sub(r"\s+", "", m.group(1)).upper().replace("，", ";").replace(",", ";")
        raw = raw[: m.start()] + raw[m.end():]
    raw = raw.strip()
    m = re.match(r"^Q\s*\d*\s*[.．、:：]?\s*", raw)
    if m:
        raw = raw[m.end():]
    raw = STEM_LABEL_RE.sub("", raw).strip()
    if not raw or not ans:
        return None

    lines = [l for l in (x.strip() for x in raw.split("\n")) if l]
    opts, stem_parts = [], []
    for l in lines:
        pieces = split_inline_options(l)
        if pieces and OPT_MARK.match(pieces[0]):
            opts.extend(pieces)
        elif not opts:
            stem_parts.append(l)
        else:
            stem_parts.append(l)
    stem = " ".join(stem_parts).strip() if len(stem_parts) > 1 else (stem_parts[0] if stem_parts else "")

    letters, texts = [], []
    for o in opts:
        m = OPT_MARK.match(o)
        if not m:
            continue
        letters.append(m.group(1))
        texts.append(o[m.end():].strip())
    if len(texts) < 2:
        return None

    ans_letters = [a for a in ans.split(";") if a]
    if len(ans_letters) > 1:
        qtype = "多选题"
    elif len(texts) == 2 and all(t.lower() in ("true", "false", "正确", "错误") for t in texts):
        qtype = "判断题"
    else:
        qtype = "单选题"

    row = {"题型": qtype, "题干": fix_refs(stem), "正确答案": ans.replace(";", ";"), "解析": fix_refs(expl)}
    for i in range(4):
        row[f"选项{'ABCD'[i]}"] = fix_refs(texts[i]) if i < len(texts) else ""
    return row


def parse_questions(quiz_items):
    lines = [t for t, _ in quiz_items]
    lines = [l for l in lines if not l.startswith("练习题")]
    if not lines:
        return []
    has_q = any(re.match(r"^Q\s*\d", l) for l in lines)
    groups = []
    for l in lines:
        if has_q and not re.match(r"^Q\s*\d", l) and groups:
            groups[-1].append(l)
        else:
            groups.append([l])
    out = []
    for g in groups:
        r = parse_one("\n".join(g))
        if r:
            out.append(r)
    return out


# ---------------- 正文 docx ----------------

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_article_docx(src, out_path, body):
    with zipfile.ZipFile(src) as z:
        src_xml = z.read("word/document.xml").decode("utf-8")
        names = z.namelist()
        payload = {n: z.read(n) for n in names}
    root_open = re.search(r"<w:document\b[^>]*>", src_xml).group(0)
    if "xmlns:w=" not in root_open:
        root_open = root_open[:-1].rstrip() + " " + NS_DECL + ">"
    sm = re.search(r"<w:sectPr\b.*?</w:sectPr>", src_xml, re.S)
    sect = sm.group(0) if sm else ""
    parts = []
    for text in body:
        parts.append(
            '<w:p><w:pPr><w:pStyle w:val="Normal"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{esc(text)}</w:t></w:r></w:p>'
        )
    payload["word/document.xml"] = (
        root_open + "<w:body>" + "".join(parts) + sect + "</w:body></w:document>"
    ).encode("utf-8")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, payload[n])


# ---------------- 题目 xlsx ----------------

TEMPLATE_LEVELS = ["A1", "A2", "B1", "B2+"]
HEADER = ["题型", "题干", "选项A", "选项B", "选项C", "选项D", "正确答案", "解析"]


def write_quiz_xlsx(template, out_path, level_rows):
    import openpyxl
    wb = openpyxl.load_workbook(template)
    pool = [s for s in wb.sheetnames if s in TEMPLATE_LEVELS]
    used = set()
    for lv in level_rows:
        if lv in wb.sheetnames:
            used.add(lv)
            continue
        if not pool:
            wb.create_sheet(lv)
            pool.append(lv)
            continue
        pick = pool.pop(0)
        wb[pick].title = lv
        while pick in pool:
            pool.remove(pick)
        used.add(lv)
    for name in list(wb.sheetnames):
        if name not in used:
            del wb[name]
    for lv, rows in level_rows.items():
        ws = wb[lv]
        ws.delete_rows(2, ws.max_row)                     # 清掉示例行
        for r in rows:
            ws.append([r.get(k, "") for k in HEADER])
    order = [lv for lv in level_rows]
    wb._sheets = [wb[lv] for lv in order]
    wb.save(out_path)


# ---------------- 主流程 ----------------

def safe(name):
    """去掉文件名非法字符（半角 : / \\ * ? " < > |），再合并多余空格。
    去掉半角冒号后，'Whales: Swimming Mammals …' 会正好等于源文件名，避免引入新差异。"""
    name = re.sub(r'[/\\:*?"<>|]', "", name)
    name = re.sub(r"\s{2,}", " ", name)
    return name.strip()


def run(src, outdir, template, title_mode="full"):
    os.makedirs(outdir, exist_ok=True)
    title, levels, order = parse_docx(src)
    if title_mode == "en":
        t = re.sub(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+", "", title).strip()
        title = t or title
    title = safe(title)

    report = []
    for lv in order:
        d = levels[lv]
        base = lv.split("#")[0]
        suffix = base + ("_母稿" if d["mother"] else "")
        body = [clean_body(t) for t, _ in d["body"]]
        body = [b for b in body if b]
        f = os.path.join(outdir, f"{title}_{suffix}.docx")
        write_article_docx(src, f, body)
        tag = "（未标母稿，按最高级推断）" if d.get("mother_inferred") else ""
        report.append((f"{title}_{suffix}.docx", f"正文 {len(body)} 段{tag}"))

    level_rows = {}
    for lv in order:
        qs = parse_questions(levels[lv]["quiz"])
        if qs:
            level_rows[lv.split("#")[0]] = qs
    if level_rows:
        x = os.path.join(outdir, f"{title}_题目.xlsx")
        write_quiz_xlsx(template, x, level_rows)
        report.append((os.path.basename(x), "题目 " + " / ".join(f"{k}:{len(v)}题" for k, v in level_rows.items())))
    return title, report, level_rows


if __name__ == "__main__":
    src = sys.argv[1]
    outdir = sys.argv[2]
    tpl = sys.argv[3] if len(sys.argv) > 3 else "/Users/jinsongli/Downloads/ReadPal题目上传模板.xlsx"
    title, report, rows = run(src, outdir, tpl)
    print(f"标题：{title}")
    for f, d in report:
        print(f"  {f}   （{d}）")
