"""JSON 落盘存储。

目录结构（沿用佳阳老师的 articles/{id}/ 约定）：
    data/articles/{id}/
        original.txt        原文（B2+）
        cards.json          title / topic_words / b2_card_starts / 四级卡片与题目
        meta.json           id / status / 时间戳 / 报告摘要
        check_report.json   形式质检结果
        judge_report.json   语义裁判结果
        fix_log.json        自动修复留痕
        *.docx              导出产物

之所以每篇独立成目录：零依赖、可肉眼查看、备份就是复制目录，后续换数据库迁移路径清晰。
"""
import json
import re
import secrets
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "articles"

_STATUSES = ["pending", "generating", "checking", "auto_fixing",
             "judging", "rendering", "done", "needs_human", "failed"]


def _dir(article_id):
    return DATA / article_id


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def new_id(slug=None):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tail = secrets.token_hex(2)
    if slug:
        slug = re.sub(r"[^a-zA-Z0-9\-]", "", slug.lower())[:24].strip("-")
        if slug:
            return f"{stamp}-{slug}-{tail}"
    return f"{stamp}-{tail}"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def create_article(article_id, original_text, title_en="", title_zh="", source_mode="b2"):
    d = _dir(article_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "original.txt").write_text(original_text or "", encoding="utf-8")
    cards = {
        "id": article_id,
        "title_en": title_en,
        "title_zh": title_zh,
        # b2 = 原文即 B2+；news = 原文是新闻原稿，B2+ 也由模型生成
        "source_mode": source_mode or "b2",
        "topic_words": [],
        "b2_card_starts": [],
        "levels": {
            "A1-": {"cards": [], "questions": []},
            "A2": {"cards": [], "questions": []},
            "B1": {"cards": [], "questions": []},
            "B2+": {"cards": [], "questions": []},
        },
        "original_text": original_text or "",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "pending",
    }
    _write_json(d / "cards.json", cards)
    _write_json(d / "meta.json", {
        "id": article_id, "status": "pending",
        "created_at": cards["created_at"], "updated_at": cards["updated_at"],
    })
    return cards


def get_article(article_id):
    """读取完整 article（cards.json + original.txt + 报告摘要）。不存在返回 None。"""
    d = _dir(article_id)
    if not d.is_dir():
        return None
    cards = _read_json(d / "cards.json")
    if cards is None:
        return None
    cards["original_text"] = (d / "original.txt").read_text(encoding="utf-8")
    meta = _read_json(d / "meta.json", {}) or {}
    cards["status"] = meta.get("status", cards.get("status", "pending"))
    cards["created_at"] = meta.get("created_at", cards.get("created_at"))
    cards["updated_at"] = meta.get("updated_at", cards.get("updated_at"))
    cards["check_report"] = _read_json(d / "check_report.json")
    cards["judge_report"] = _read_json(d / "judge_report.json")
    cards["fix_log"] = _read_json(d / "fix_log.json", []) or []
    return cards


def save_article(article):
    """写回 cards.json（原文与报告分文件，各自单独保存）。"""
    d = _dir(article["id"])
    d.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in article.items()
               if k not in ("original_text", "check_report", "judge_report",
                            "fix_log", "status", "updated_at")}
    payload["updated_at"] = now_iso()
    _write_json(d / "cards.json", payload)
    if "original_text" in article:
        (d / "original.txt").write_text(article["original_text"] or "", encoding="utf-8")
    meta = _read_json(d / "meta.json", {}) or {}
    meta.update({"id": article["id"], "updated_at": payload["updated_at"]})
    if "status" in article:
        meta["status"] = article["status"]
    meta.setdefault("created_at", payload.get("created_at") or now_iso())
    _write_json(d / "meta.json", meta)
    return payload


def set_status(article_id, status):
    d = _dir(article_id)
    meta = _read_json(d / "meta.json", {}) or {"id": article_id}
    meta["status"] = status
    meta["updated_at"] = now_iso()
    _write_json(d / "meta.json", meta)


def get_status(article_id):
    meta = _read_json(_dir(article_id) / "meta.json", {}) or {}
    return meta.get("status", "pending")


def save_report(article_id, kind, report):
    """kind: check | judge"""
    _write_json(_dir(article_id) / f"{kind}_report.json", report)


def get_report(article_id, kind):
    return _read_json(_dir(article_id) / f"{kind}_report.json")


def append_fix_log(article_id, entry):
    d = _dir(article_id)
    log = _read_json(d / "fix_log.json", []) or []
    entry = dict(entry)
    entry.setdefault("at", now_iso())
    log.append(entry)
    _write_json(d / "fix_log.json", log)
    return log


def list_articles():
    """列出全部文章（按创建时间倒序），只读元信息，保证列表接口足够快。"""
    if not DATA.is_dir():
        return []
    out = []
    for d in DATA.iterdir():
        if not d.is_dir():
            continue
        cards = _read_json(d / "cards.json")
        if not cards:
            continue
        meta = _read_json(d / "meta.json", {}) or {}
        chk = _read_json(d / "check_report.json") or {}
        jdg = _read_json(d / "judge_report.json") or {}
        src = d / "original.txt"
        out.append({
            "id": cards.get("id", d.name),
            "title_en": cards.get("title_en", ""),
            "title_zh": cards.get("title_zh", ""),
            "status": meta.get("status", "pending"),
            "created_at": meta.get("created_at") or cards.get("created_at"),
            "updated_at": meta.get("updated_at") or cards.get("updated_at"),
            "words": len(src.read_text(encoding="utf-8").split()) if src.exists() else 0,
            "passed": chk.get("passed"),
            "error_count": chk.get("error_count", 0),
            "p0_count": sum(1 for f in (jdg.get("findings") or [])
                            if (f.get("severity") or "P0") == "P0"),
            "is_seed": bool(meta.get("is_seed")),
        })
    out.sort(key=lambda a: a.get("created_at") or "", reverse=True)
    return out


def delete_article(article_id):
    d = _dir(article_id)
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False


def touch(article_id):
    d = _dir(article_id)
    meta = _read_json(d / "meta.json", {}) or {"id": article_id}
    meta["updated_at"] = now_iso()
    _write_json(d / "meta.json", meta)


def sleep_ms(ms):
    time.sleep(ms / 1000.0)
