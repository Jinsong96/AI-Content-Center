"""V3 分级阅读内容工厂 · 服务端

零第三方依赖（仅 Python 标准库），因为质检内核与 docx 渲染都复用老师的纯标准库实现。

对外接口（对应规格文档 §4）：
    GET  /api/health                    健康检查
    GET  /api/config                    模型配置状态（不含密钥）
    POST /api/config/probe              连通性自检
    GET  /api/articles                  文章列表
    POST /api/articles                  提交原文，启动生产（返回 article_id + job_id）
    GET  /api/articles/{id}             完整文章
    PUT  /api/articles/{id}/cards       保存某张卡
    PUT  /api/articles/{id}/questions   保存某道题
    POST /api/articles/{id}/rewrite     人工触发局部重写
    POST /api/articles/{id}/fix         一键自动修复（跑自动修复循环）
    POST /api/articles/{id}/check       L1 重跑：形式质检
    POST /api/articles/{id}/judge       L2 重跑：语义裁判
    POST /api/articles/{id}/export      导出 docx
    GET  /api/articles/{id}/export/download  下载 docx
    GET  /api/jobs/{job_id}             轮询任务进度
    DELETE /api/articles/{id}           删除文章
"""
import json
import os
import re
import sys
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import llm, quality, render, store  # noqa: E402

PUBLIC = ROOT / "public"
PROMPTS = ROOT / "prompts"
ASSETS = ROOT / "assets"

MAX_CHECK_ROUNDS = 3      # 形式层自动修复上限
MAX_JUDGE_ROUNDS = 2      # 语义层自动修复上限

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain; charset=utf-8",
}

JOBS = {}
JOBS_LOCK = threading.Lock()

# /api/articles/{id}            读取
# /api/articles/{id}/cards      保存卡片
# /api/articles/{id}/questions  保存题目
# /api/articles/{id}/check      重跑形式质检
# /api/articles/{id}/judge      重跑语义裁判
# /api/articles/{id}/fix        自动修复
# /api/articles/{id}/rewrite    局部重写
# /api/articles/{id}/export     导出
# /api/articles/{id}/export/download  下载
ROUTE_ARTICLE = re.compile(r"^/api/articles/([A-Za-z0-9\-_.]+)(/[A-Za-z0-9\-_/]*)?$")


# ---------------------------------------------------------------- 配置

KEYS_FILE = ROOT / "server_keys.json"


def _load_local_keys():
    """把 server_keys.json 里的密钥补进环境变量。

    为什么需要它：发布到线上后没有注入环境变量的入口，而服务端密钥又必须存在，
    否则每位使用者都要自己填 key。**环境变量优先，文件只补空缺**，两者互不覆盖。
    该文件不进公开仓库（见 .gitignore），本机权限 600。"""
    if not KEYS_FILE.is_file():
        return
    try:
        data = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except Exception:
        traceback.print_exc()
        return
    for prefix, section in (("GEN", "generate"), ("JUDGE", "judge")):
        given = data.get(section) or {}
        for field in ("base_url", "api_key", "model"):
            name = f"{prefix}_{field.upper()}"
            if not os.environ.get(name) and given.get(field):
                os.environ[name] = str(given[field])


_load_local_keys()


def env_cfg(prefix):
    return {
        "base_url": os.environ.get(f"{prefix}_BASE_URL", ""),
        "api_key": os.environ.get(f"{prefix}_API_KEY", ""),
        "model": os.environ.get(f"{prefix}_MODEL", ""),
    }


def resolve_cfg(payload, key):
    """优先用请求里带来的配置（前端存在 localStorage，不落服务端），否则退回环境变量。"""
    given = (payload or {}).get(key) or {}
    env = env_cfg("GEN" if key == "generate" else "JUDGE")
    merged = {}
    for field in ("base_url", "api_key", "model"):
        merged[field] = (given.get(field) or "").strip() or env.get(field, "")
    return merged


def cfg_state(cfg, role=None):
    """对外汇报某个模型角色的可用状态。

    分两层：
      1) 字段层 —— base_url / api_key / model 是否填齐
      2) 实测层 —— 最近一次真实调用成功没有（llm.health）
    只有两层都过才算 ready。这事线上踩过：裁判账号余额耗尽、每次调用 402，
    但字段层是齐的，界面照样显示「已就绪」，点下去才炸。
    """
    filled = bool(cfg.get("base_url") and cfg.get("api_key") and cfg.get("model"))
    state = {
        "base_url": cfg.get("base_url") or "",
        "model": cfg.get("model") or "",
        "has_key": bool(cfg.get("api_key")),
        "filled": filled,
    }
    h = llm.health(role) if role else {}
    state["checked"] = bool(h)                 # 有没有被真实调用验证过
    state["last_ok"] = h.get("ok") if h else None
    state["last_at"] = h.get("at") if h else None
    if not filled:
        state["ready"] = False
        state["reason"] = "字段未填齐"
    elif h and not h.get("ok"):
        state["ready"] = False
        state["reason"] = h.get("message") or "最近一次调用失败"
    else:
        state["ready"] = True
        state["reason"] = None if h else "尚未验证（还没有真实调用过）"
    return state


# ---------------------------------------------------------------- 任务

def job_new(article_id, kind):
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id, "article_id": article_id, "kind": kind,
            "status": "pending", "step": "排队中", "round": 0,
            "progress": 0, "error": None, "started_at": store.now_iso(),
        }
    return job_id


def job_update(job_id, **kw):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(kw)


def job_get(job_id):
    with JOBS_LOCK:
        return dict(JOBS.get(job_id) or {})


# ---------------------------------------------------------------- 自动修复循环

def group_targets(problems, key_card="card", key_question="question"):
    """把问题清单聚成局部重写目标：article 级问题 → 整级重写；其余 → 精确到卡/题。"""
    whole, items, seen = set(), [], set()
    for p in problems:
        lv = p.get("level") or "A1-"
        card = p.get(key_card)
        question = p.get(key_question)
        if card:
            k = (lv, "card", int(card))
            if k not in seen:
                seen.add(k)
                items.append({"level": lv, "card": int(card)})
        elif question:
            k = (lv, "q", int(question))
            if k not in seen:
                seen.add(k)
                items.append({"level": lv, "question": int(question)})
        else:
            whole.add(lv)
    targets = [{"level": lv, "card": None, "question": None} for lv in sorted(whole)]
    targets += [i for i in items if i["level"] not in whole]
    return targets


def run_quality_loop(article, gen_cfg, job_id, max_rounds=MAX_CHECK_ROUNDS):
    """形式层：质检 → 有错就局部重写 → 再质检，直到通过或到上限。"""
    rounds = 0
    report, cards = quality.evaluate(article)
    store.save_report(article["id"], "check", report)

    while report["errors"] and rounds < max_rounds:
        rounds += 1
        targets = group_targets(report["errors"])
        job_update(job_id, status="auto_fixing", step=f"形式层自动修复（第 {rounds} 轮）",
                   round=rounds, progress=40 + rounds * 5)
        try:
            changed, _ = llm.rewrite(article, cards, targets, report["errors"], gen_cfg, PROMPTS,
                                     article.get("source_mode"))
        except llm.LLMError:
            raise
        store.append_fix_log(article["id"], {
            "layer": "check", "round": rounds,
            "targets": targets,
            "problems": [{"level": e["level"], "card": e["target"],
                          "message": e["message"]} for e in report["errors"]],
            "changed": changed,
        })
        store.save_article(article)
        report, cards = quality.evaluate(article)
        store.save_report(article["id"], "check", report)

    return report, cards, rounds


def run_judge_loop(article, cards, gen_cfg, judge_cfg, job_id, max_rounds=MAX_JUDGE_ROUNDS, lang="zh"):
    """语义层：裁判 → 有 P0 就局部重写 → 回形式层 → 再裁判。"""
    rounds = 0
    verdict = llm.judge(article, cards, judge_cfg, PROMPTS, lang=lang,
                        mode=article.get("source_mode"))
    store.save_report(article["id"], "judge", verdict)

    while verdict["p0_count"] > 0 and rounds < max_rounds:
        rounds += 1
        p0s = [f for f in verdict["findings"] if f["severity"] == "P0"]
        targets = group_targets(p0s)
        job_update(job_id, status="auto_fixing", step=f"语义层自动修复（第 {rounds} 轮）",
                   round=rounds, progress=70 + rounds * 5)
        try:
            changed, _ = llm.rewrite(article, cards, targets, p0s, gen_cfg, PROMPTS,
                                     article.get("source_mode"))
        except llm.LLMError:
            raise
        store.append_fix_log(article["id"], {
            "layer": "judge", "round": rounds,
            "targets": targets,
            "problems": [{"level": f["level"], "card": f.get("card"),
                          "message": f.get("why")} for f in p0s],
            "changed": changed,
        })
        store.save_article(article)

        report, cards = quality.evaluate(article)
        store.save_report(article["id"], "check", report)
        verdict = llm.judge(article, cards, judge_cfg, PROMPTS, lang=lang,
                        mode=article.get("source_mode"))
        store.save_report(article["id"], "judge", verdict)

    return verdict, cards, rounds


def job_produce(job_id, article_id, gen_cfg, judge_cfg, options):
    """完整生产链路：生成 → 形式层 → 语义层 → 完成。"""
    try:
        article = store.get_article(article_id)
        if not article:
            job_update(job_id, status="failed", error="文章不存在")
            return

        # ① 生成
        if options.get("skip_generate"):
            job_update(job_id, status="checking", step="跳过生成，直接质检", progress=35)
        else:
            job_update(job_id, status="generating", step="正在生成四级内容", progress=15)
            gen = llm.generate(article["original_text"], gen_cfg, PROMPTS,
                               article.get("source_mode"))
            article["title_en"] = gen["title_en"] or article.get("title_en", "")
            article["title_zh"] = gen["title_zh"] or article.get("title_zh", "")
            article["topic_words"] = gen["topic_words"]
            article["b2_card_starts"] = gen["b2_card_starts"]
            article["levels"] = gen["levels"]
            # 新闻模式下模型会自评原稿难度，落库后由质检给出「原稿偏易」提醒
            if gen.get("source_level"):
                article["source_level"] = gen["source_level"]
            store.save_article(article)
            job_update(job_id, status="checking", step="生成完成，开始形式质检", progress=35)

        # ② 形式层
        report, cards, check_rounds = run_quality_loop(article, gen_cfg, job_id)

        # ③ 语义层
        judge_rounds = 0
        verdict = None
        if options.get("run_judge", True):
            job_update(job_id, status="judging", step="语义裁判中", progress=70)
            verdict, cards, judge_rounds = run_judge_loop(
                article, cards, gen_cfg, judge_cfg, job_id,
                lang=options.get("lang") or "zh")

        # ④ 收尾
        job_update(job_id, status="rendering", step="渲染中", progress=95)
        try:
            render.render_article(article, cards)
        except Exception as e:                      # 渲染失败不影响文章已产出
            print("[render] 导出失败：", e, file=sys.stderr)

        unresolved = report["error_count"] > 0 or (verdict and verdict["p0_count"] > 0)
        final = "needs_human" if unresolved else "done"
        store.set_status(article_id, final)
        job_update(
            job_id, status="done", step="完成" if final == "done" else "达到修复上限，需要人工介入",
            progress=100, result={
                "article_id": article_id,
                "passed": report["passed"],
                "error_count": report["error_count"],
                "warning_count": report["warning_count"],
                "p0_count": verdict["p0_count"] if verdict else None,
                "p1_count": verdict["p1_count"] if verdict else None,
                "check_rounds": check_rounds,
                "judge_rounds": judge_rounds,
                "needs_human": unresolved,
            })
    except llm.LLMError as e:
        store.set_status(article_id, "failed")
        job_update(job_id, status="failed", error=str(e))
    except Exception as e:
        traceback.print_exc()
        store.set_status(article_id, "failed")
        job_update(job_id, status="failed", error=f"{type(e).__name__}: {e}")


def job_fix(job_id, article_id, gen_cfg, judge_cfg, run_judge, lang="zh"):
    """对已有文章重跑自动修复循环（不重新生成）。"""
    try:
        article = store.get_article(article_id)
        if not article:
            job_update(job_id, status="failed", error="文章不存在")
            return
        report, cards, check_rounds = run_quality_loop(article, gen_cfg, job_id)
        verdict = store.get_report(article_id, "judge")
        judge_rounds = 0
        if run_judge and judge_cfg.get("api_key"):
            job_update(job_id, status="judging", step="语义裁判中", progress=70)
            verdict, cards, judge_rounds = run_judge_loop(
                article, cards, gen_cfg, judge_cfg, job_id, lang=lang)
        unresolved = report["error_count"] > 0 or (verdict and verdict.get("p0_count", 0) > 0)
        store.set_status(article_id, "needs_human" if unresolved else "done")
        job_update(job_id, status="done",
                   step="完成" if not unresolved else "仍有未解决问题，需要人工介入",
                   progress=100, result={
                       "passed": report["passed"],
                       "error_count": report["error_count"],
                       "p0_count": verdict.get("p0_count") if verdict else None,
                       "check_rounds": check_rounds, "judge_rounds": judge_rounds,
                       "needs_human": unresolved})
    except llm.LLMError as e:
        job_update(job_id, status="failed", error=str(e))
    except Exception as e:
        traceback.print_exc()
        job_update(job_id, status="failed", error=f"{type(e).__name__}: {e}")


def job_judge(job_id, article_id, judge_cfg, lang="zh"):
    """重跑语义裁判（后台任务）。

    原先 /judge 是同步接口：前端点一下，HTTP 连接一直挂着等模型判完。
    本地直跑约 31s 没问题，但线上网关有约 60 秒硬超时 —— 四级齐全的大文章
    裁判要 60~90s，请求会被网关掐断（前端收到 504，裁判白跑）。
    改成后台任务后，前端轮询进度，判多久都不会被掐。
    """
    try:
        article = store.get_article(article_id)
        if not article:
            job_update(job_id, status="failed", error="文章不存在")
            return
        job_update(job_id, status="judging", step="语义裁判中", progress=30)
        _, cards = quality.evaluate(article)
        verdict = llm.judge(article, cards, judge_cfg, PROMPTS,
                            lang=lang, mode=article.get("source_mode"))
        store.save_report(article_id, "judge", verdict)
        job_update(job_id, status="done", step="完成", progress=100,
                   result={"p0_count": verdict.get("p0_count"),
                           "p1_count": verdict.get("p1_count"),
                           "conclusion": verdict.get("conclusion") or ""})
    except llm.LLMError as e:
        job_update(job_id, status="failed", error=str(e))
    except Exception as e:
        traceback.print_exc()
        job_update(job_id, status="failed", error=f"{type(e).__name__}: {e}")


def job_rewrite(job_id, article_id, targets, instruction, gen_cfg):
    """人工触发的局部重写。"""
    try:
        article = store.get_article(article_id)
        if not article:
            job_update(job_id, status="failed", error="文章不存在")
            return
        _, cards = quality.evaluate(article)
        problems = [{"level": t.get("level"), "card": t.get("card"),
                     "question": t.get("question"),
                     "message": instruction or "人工要求重写这一条"}] if instruction else []
        job_update(job_id, status="auto_fixing", step="局部重写中", progress=50)
        changed, _ = llm.rewrite(article, cards, targets, problems, gen_cfg, PROMPTS,
                                 article.get("source_mode"))
        store.append_fix_log(article_id, {
            "layer": "manual", "round": 0, "targets": targets,
            "problems": problems, "changed": changed})
        store.save_article(article)
        report, _ = quality.evaluate(article)
        store.save_report(article_id, "check", report)
        job_update(job_id, status="done", step="重写完成", progress=100,
                   result={"changed": changed, "passed": report["passed"],
                           "error_count": report["error_count"]})
    except llm.LLMError as e:
        job_update(job_id, status="failed", error=str(e))
    except Exception as e:
        traceback.print_exc()
        job_update(job_id, status="failed", error=f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "V3ContentFactory/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):          # 静音，避免刷屏
        pass

    # ---------- 基础工具

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _ok(self, data):
        self._send(200, {"ok": True, "data": data})

    def _err(self, code, message, extra=None):
        payload = {"ok": False, "error": {"code": code, "message": message}}
        if extra:
            payload["error"].update(extra)
        self._send(code, payload)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _query(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def _file(self, path):
        if not path.is_file():
            self._err(404, "文件不存在")
            return
        ext = path.suffix.lower()
        self._send(200, path.read_bytes(), MIME.get(ext, "application/octet-stream"))

    # ---------- 路由

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/" or path == "/index.html":
                return self._file(PUBLIC / "index.html")
            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                target = (PUBLIC / rel).resolve()
                if not str(target).startswith(str(PUBLIC.resolve())):
                    return self._err(403, "越权路径")
                return self._file(target)
            if path == "/api/health":
                return self._ok({"service": "v3-content-factory", "ready": True})
            if path == "/api/config":
                return self._ok({
                    "generate": cfg_state(env_cfg("GEN"), "generate"),
                    "judge": cfg_state(env_cfg("JUDGE"), "judge"),
                    "limits": {"max_check_rounds": MAX_CHECK_ROUNDS,
                               "max_judge_rounds": MAX_JUDGE_ROUNDS},
                })
            if path == "/api/articles":
                return self._ok(store.list_articles())
            if path.startswith("/api/jobs/"):
                job = job_get(path.rsplit("/", 1)[-1])
                if not job:
                    return self._err(404, "任务不存在")
                return self._ok(job)
            m = ROUTE_ARTICLE.match(path)
            if m:
                aid = m.group(1)
                rest = m.group(2) or ""
                if rest == "":
                    art = store.get_article(aid)
                    if not art:
                        return self._err(404, "文章不存在")
                    # b2 模式：B2+ 正文由原文按锚点切分得来，不进 cards.json，只在响应里补上
                    # news 模式：B2+ 本身就是模型产物、已存在 cards.json 里，不能覆盖
                    if art.get("source_mode") == "news":
                        art["levels"].setdefault("B2+", {}).setdefault("cards", [])
                    else:
                        try:
                            art["levels"]["B2+"]["cards"] = quality.split_original(
                                art.get("original_text") or "", art.get("b2_card_starts") or [])
                        except ValueError:
                            art["levels"]["B2+"]["cards"] = []
                    return self._ok(art)
                if rest == "/export/download":
                    art = store.get_article(aid)
                    if not art:
                        return self._err(404, "文章不存在")
                    name = render.safe_filename(art.get("title_en"), art.get("title_zh"))
                    f = ROOT / "data" / "articles" / aid / f"{name}.docx"
                    if not f.is_file():
                        _, cards = quality.evaluate(art)
                        render.render_article(art, cards)
                    return self._file(f) if f.is_file() else self._err(500, "导出失败")
                return self._err(404, "未知接口")
            if path == "/assets/template.docx":
                return self._file(ASSETS / "template.docx")
            return self._err(404, "未找到")
        except Exception as e:
            traceback.print_exc()
            self._err(500, f"{type(e).__name__}: {e}")

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        body = self._body()          # 先读完 body，否则 keep-alive 连接会错位
        try:
            # ---- 配置自检
            # 这是一次真实调用，结果会写进健康记录，之后 /api/config 就以它为准。
            # 例外：用户在自己浏览器里单独填了一整套 key —— 那只代表他这台机器，
            # 不该算到「服务端配置」头上，所以这种时候不写健康记录（role=None）。
            # 返回的 state 始终描述服务端那份配置。
            if path == "/api/config/probe":
                which = "judge" if body.get("which") == "judge" else "generate"
                prefix = "GEN" if which == "generate" else "JUDGE"
                cfg = resolve_cfg(body, which)
                given = body.get(which) or {}
                self_supplied = bool(given.get("base_url") and given.get("api_key")
                                     and given.get("model"))
                try:
                    reply = llm.probe(cfg, role=None if self_supplied else which)
                    # state 要在自检「之后」取 —— 这次调用的结果已经进了健康记录
                    return self._ok({"which": which, "reply": reply, "ok": True,
                                     "state": cfg_state(env_cfg(prefix), which)})
                except llm.LLMError as e:
                    return self._err(400, str(e),
                                     extra={"which": which,
                                            "state": cfg_state(env_cfg(prefix), which)})
                except Exception as e:
                    return self._err(400, f"{type(e).__name__}: {e}",
                                     extra={"which": which,
                                            "state": cfg_state(env_cfg(prefix), which)})

            # ---- 新建并生产
            if path == "/api/articles":
                text = (body.get("original_text") or "").strip()
                if len(text.split()) < 60:
                    return self._err(400, "原文太短（至少 60 个词），无法切卡与降级改写")
                # 来源模式：b2 = 原文即 B2+（原有流程）；news = 新闻原稿，四级全部生成
                source_mode = "news" if body.get("source_mode") == "news" else "b2"
                gen_cfg = resolve_cfg(body, "generate")
                judge_cfg = resolve_cfg(body, "judge")
                aid = store.new_id()
                store.create_article(aid, text,
                                     body.get("title_en", ""), body.get("title_zh", ""),
                                     source_mode)
                options = {
                    "run_judge": body.get("run_judge", True),
                    "skip_generate": bool(body.get("skip_generate")),
                    "lang": body.get("lang") or "zh",
                }
                jid = job_new(aid, "produce")
                threading.Thread(
                    target=job_produce, daemon=True,
                    args=(jid, aid, gen_cfg, judge_cfg, options)).start()
                return self._ok({"article_id": aid, "job_id": jid})

            m = ROUTE_ARTICLE.match(path)
            if not m:
                return self._err(404, "未找到")
            aid, rest = m.group(1), m.group(2) or ""

            # ---- L1 重跑质检
            if rest == "/check":
                art = store.get_article(aid)
                if not art:
                    return self._err(404, "文章不存在")
                report, _ = quality.evaluate(art)
                store.save_report(aid, "check", report)
                return self._ok(report)

            # ---- L2 重跑裁判
            # 默认走后台任务：线上网关有 ~60 秒硬超时，大文章同步等会被掐断。
            # body 带 sync=true 时保留原来的同步返回，方便脚本直接拿结果。
            if rest == "/judge":
                art = store.get_article(aid)
                if not art:
                    return self._err(404, "文章不存在")
                judge_cfg = resolve_cfg(body, "judge")
                lang = body.get("lang") or "zh"
                if body.get("sync"):
                    _, cards = quality.evaluate(art)
                    try:
                        verdict = llm.judge(art, cards, judge_cfg, PROMPTS,
                                            lang=lang, mode=art.get("source_mode"))
                    except llm.LLMError as e:
                        return self._err(400, str(e))
                    store.save_report(aid, "judge", verdict)
                    return self._ok(verdict)
                jid = job_new(aid, "judge")
                threading.Thread(
                    target=job_judge, daemon=True,
                    args=(jid, aid, judge_cfg, lang)).start()
                return self._ok({"job_id": jid, "article_id": aid})

            # ---- 一键自动修复
            if rest == "/fix":
                gen_cfg = resolve_cfg(body, "generate")
                judge_cfg = resolve_cfg(body, "judge")
                jid = job_new(aid, "fix")
                threading.Thread(
                    target=job_fix, daemon=True,
                    args=(jid, aid, gen_cfg, judge_cfg, body.get("run_judge", True),
                          body.get("lang") or "zh")).start()
                return self._ok({"job_id": jid, "article_id": aid})

            # ---- 人工局部重写
            if rest == "/rewrite":
                gen_cfg = resolve_cfg(body, "generate")
                targets = body.get("targets") or []
                if not targets:
                    return self._err(400, "缺少 targets")
                jid = job_new(aid, "rewrite")
                threading.Thread(
                    target=job_rewrite, daemon=True,
                    args=(jid, aid, targets, body.get("instruction", ""), gen_cfg)).start()
                return self._ok({"job_id": jid, "article_id": aid})

            # ---- 导出
            if rest == "/export":
                art = store.get_article(aid)
                if not art:
                    return self._err(404, "文章不存在")
                _, cards = quality.evaluate(art)
                f = render.render_article(art, cards)
                return self._ok({
                    "download_url": f"/api/articles/{aid}/export/download",
                    "filename": f.name})

            return self._err(404, "未知接口")
        except Exception as e:
            traceback.print_exc()
            self._err(500, f"{type(e).__name__}: {e}")

    def do_PUT(self):
        path = unquote(urlparse(self.path).path)
        body = self._body()          # 先读完 body，否则 keep-alive 连接会错位
        try:
            m = ROUTE_ARTICLE.match(path)
            if not m:
                return self._err(404, "未找到")
            aid, rest = m.group(1), m.group(2) or ""
            art = store.get_article(aid)
            if not art:
                return self._err(404, "文章不存在")

            if rest == "/cards":
                lv, idx, text = body.get("level"), body.get("index"), body.get("text")
                if lv not in quality.GRADED or not isinstance(idx, int):
                    return self._err(400, "参数错误：需要 level（A1-/A2/B1）与 index（从 1 开始）")
                cards = art["levels"][lv]["cards"]
                if not (1 <= idx <= len(cards)):
                    return self._err(400, f"index 超出范围（1–{len(cards)}）")
                before = cards[idx - 1]
                cards[idx - 1] = str(text or "")
                store.save_article(art)
                store.append_fix_log(aid, {
                    "layer": "manual_edit", "round": 0,
                    "targets": [{"level": lv, "card": idx}],
                    "problems": [], "changed": [{"level": lv, "card": idx,
                                                 "before": before, "after": cards[idx - 1]}]})
                return self._ok({"ok": True, "level": lv, "index": idx})

            if rest == "/questions":
                lv, idx = body.get("level"), body.get("index")
                if lv not in quality.LEVELS or not isinstance(idx, int):
                    return self._err(400, "参数错误：需要 level 与 index（从 1 开始）")
                qs = art["levels"][lv]["questions"]
                if not (1 <= idx <= len(qs)):
                    return self._err(400, f"index 超出范围（1–{len(qs)}）")
                before = dict(qs[idx - 1])
                for key in ("q", "options", "answer", "explanation"):
                    if key in body and body[key] is not None:
                        qs[idx - 1][key] = body[key]
                store.save_article(art)
                store.append_fix_log(aid, {
                    "layer": "manual_edit", "round": 0,
                    "targets": [{"level": lv, "question": idx}],
                    "problems": [], "changed": [{"level": lv, "question": idx,
                                                 "before": before, "after": dict(qs[idx - 1])}]})
                return self._ok({"ok": True, "level": lv, "index": idx})

            return self._err(404, "未知接口")
        except Exception as e:
            traceback.print_exc()
            self._err(500, f"{type(e).__name__}: {e}")

    def do_DELETE(self):
        path = unquote(urlparse(self.path).path)
        m = ROUTE_ARTICLE.match(path)
        if m and not (m.group(2) or ""):
            ok = store.delete_article(m.group(1))
            return self._ok({"deleted": ok})
        self._err(404, "未找到")


def main():
    port = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8801))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"V3 内容工厂已启动：http://127.0.0.1:{port}")
    print(f"数据目录：{ROOT / 'data' / 'articles'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
