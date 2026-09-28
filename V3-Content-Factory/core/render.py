"""关卡外的渲染层：把四级卡片渲染成 docx。

来源：移植自佳阳老师 build_cards.py 的 build_docx()。
完全复用老师提供的 assets/template.docx（含 Normal / DocTitle / DocLevel 三个样式），
产出格式与老师手工生成的成品一致。
"""
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from . import quality

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "assets" / "template.docx"

NUMS = quality.NUMS
LEVELS = quality.LEVELS


def _para(style, text):
    t = escape(text, {'"': "&quot;", "'": "&apos;"})
    return (f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
            f'<w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>')


def safe_filename(title_en, title_zh):
    raw = f"{title_en or 'untitled'} {title_zh or ''}".strip()
    return re.sub(r'[\\/:*?"<>|\n\r\t]', "", raw)[:80].strip() or "article"


def build_docx(data, cards, out_path):
    """渲染 docx。data 为 article dict，cards 为含 B2+ 的四级卡片字典。"""
    with zipfile.ZipFile(TEMPLATE) as z:
        files = {n: z.read(n) for n in z.namelist()}

    src = files["word/document.xml"].decode("utf-8")
    head = src[: src.index("<w:body>") + len("<w:body>")]
    tail = src[src.index("<w:sectPr"):]

    body = [_para("DocTitle", f'{data.get("title_en", "")} {data.get("title_zh", "")}'.strip())]
    for lv in LEVELS:
        body.append(_para("DocLevel", lv))
        body += [_para("Normal", f"{NUMS[i]} {c}") for i, c in enumerate(cards.get(lv) or [])]
        body.append(_para("DocLevel", "题目"))
        for qi, q in enumerate((data.get("levels", {}).get(lv) or {}).get("questions") or [], 1):
            body.append(_para("Normal", f"Q{qi}. {q.get('q', '')}"))
            body += [_para("Normal", f"{'ABCD'[i]}. {o}")
                     for i, o in enumerate(q.get("options") or [])]
            body.append(_para("Normal", f"答案：{q.get('answer', '')}"))
            body.append(_para("Normal", f"解析：{q.get('explanation', '')}"))

    files["word/document.xml"] = (head + "".join(body) + tail).encode("utf-8")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return out_path


def render_article(article, cards=None):
    """便捷入口：直接对 article 渲染，返回 docx 路径。"""
    if cards is None:
        _, cards = quality.evaluate(article)
    name = safe_filename(article.get("title_en"), article.get("title_zh"))
    return build_docx(article, cards, ROOT / "data" / "articles" / article["id"] / f"{name}.docx")
