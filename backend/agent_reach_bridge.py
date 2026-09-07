#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent-Reach 桥接层（后端）—— 让前端「热点搜集」真实运转。

通过 RSS/Atom 抓取真实英文新闻，按「主题 / 子主题」关键词过滤、打分，
返回结构化热点给前端；自定义信源则按其 URL 抓取 RSS/网页。

零第三方依赖（仅 Python 标准库）。运行：
    python3 agent_reach_bridge.py [端口]        # 默认 8787

前端默认调用 http://127.0.0.1:8787/api/...
"""
import json
import os
import re
import sys
import time
import threading
import concurrent.futures
import urllib.request
import urllib.error
import socket
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8787

# 真实新闻源（均验证可用），每项 = (源名, RSS 地址, 覆盖的主题)
# 信源清单。判定标准（2026-09-02 实测）：必须可达且条目带摘要——
# 只有标题的源（Hacker News、Global Times）撑不起生成链路，已弃用。
# ⚠️ AP / Reuters / Guardian / Al Jazeera / DW / Time / NBC / SCMP 等主流国际源
#    在本网络（桥接层直连）均 403 或超时，不可用；要接需换网络/换宿主抓取。
FEEDS = [
    # 中国与国际时事（world）—— 用户指定：国际源加码 CGTN。
    # ⚠️ China Daily 的 /rss/*_rss.xml 是僵尸源：首条还是 2017 年的文章、且无日期字段，
    #    100 条全是 >14 天旧闻，无法支撑「今日热点」，故已移除（2026-09-02 实测确认）。
    #    若要恢复 China Daily，需要另找它的活源（当前 RSS 已停更）。
    ("CGTN · China", "https://www.cgtn.com/subscribe/rss/section/china.xml", ["world", "culture"]),
    ("CGTN · World", "https://www.cgtn.com/subscribe/rss/section/world.xml", ["world"]),
    ("CGTN · Politics", "https://www.cgtn.com/subscribe/rss/section/politics.xml", ["world"]),
    ("CGTN · Culture", "https://www.cgtn.com/subscribe/rss/section/culture.xml", ["culture"]),
    ("CGTN · Business", "https://www.cgtn.com/subscribe/rss/section/business.xml", ["world"]),
    ("NPR", "https://feeds.npr.org/1001/rss.xml", ["world"]),
    ("Global News", "https://globalnews.ca/feed/", ["world"]),
    # 科学与科技（science）
    ("The Verge", "https://www.theverge.com/rss/index.xml", ["science"]),
    ("ScienceDaily", "https://www.sciencedaily.com/rss/all.xml", ["science"]),
    ("Science News", "https://www.sciencenews.org/feed", ["science"]),
    ("Live Science", "https://www.livescience.com/feeds/all", ["science"]),
    # 文化与流行（culture）
    ("Variety", "https://variety.com/feed/", ["culture"]),
    ("Billboard", "https://www.billboard.com/feed/", ["culture"]),
    # 已移除（用户指定 / 实测不可用）：
    #   Wired     —— RSS 变成优惠券/联盟营销页（Priceline、NordVPN 折扣等），纯噪音
    #   Phys.org  —— 抓正文被拦截（成功率 0%）
    #   ESPN      —— 抓正文 4/4 失败（成功率 0%）
    #   China Daily —— RSS 僵尸源（2017 旧闻、无日期），无法支撑今日热点
]

# 主题 → 子主题 → 关键词（英文，命中即计分）
THEME_KEYWORDS = {
    "culture": {
        "传统节日": ["festival", "qixi", "new year", "spring festival", "lantern", "dragon boat",
                 "mid-autumn", "shoton", "torch", "valentine", "holiday", "celebration", "reunion", "calendar"],
        "艺术": ["porcelain", "ceramic", "brocade", "heritage", "intangible", "craft", "artisan",
             "thangka", "painting", "sculpture", "embroidery", "weav", "pottery", "handmade", "opera", "calligraphy", "ink"],
        "书籍机构": ["book", "library", "museum", "archive", "novel", "literature", "reading",
                "classic", "poem", "poetry", "manuscript", "author"],
        "科学常识": ["science", "physics", "chemistry", "astronomy", "biology", "scientist", "experiment", "research"],
        "语言": ["language", "english", "grammar", "vocabulary", "bilingual", "linguist", "translation"],
    },
    "tech": {
        "AI": ["artificial intelligence", "machine learning", "chatbot", "llm", "deep learning", "algorithm", " ai"],
        "太空": ["space", "rocket", "satellite", "astronaut", "moon", "mars", "telescope", "orbit"],
        "机器人": ["robot", "robotics", "automation"],
        "能源": ["energy", "solar", "battery", "power grid", "electric vehicle", "renewable", "wind power"],
        "前沿科技": ["chip", "semiconductor", "quantum", "breakthrough", "innovation", "5g", "6g", "supercomputer"],
        "健康医疗": ["health", "medical", "disease", "medicine", "hospital", "vaccine", "nutrition", "drug"],
    },
    "city": {
        "街头美食": ["food", "cuisine", "street food", "snack", "restaurant", "dish", "flavor", "dining"],
        "交通": ["traffic", "metro", "subway", "commute", "highway", "road", "rail", "airport"],
        "住房": ["housing", "rent", "apartment", "real estate", "property", "home"],
        "本地商业": ["business", "shop", "mall", "store", "market", "commerce", "retail", "consumer"],
    },
    "travel": {
        "乡村": ["rural", "countryside", "village", "farm", "harvest", "agriculture"],
        "人口变化": ["population", "demographic", "migrant", "immigrant", "birth rate", "aging"],
        "季节迁徙": ["tourism", "travel", "journey", "migration", "seasonal", "scenery"],
        "民生议题": ["livelihood", "pension", "employment", "public service", "welfare", "income"],
        "商业思维": ["business model", "company strategy", "industry", "economy", "market"],
    },
    "pop": {
        "网络趋势": ["viral", "meme", "social media", "hashtag", "short video", "trending", "online"],
        "音乐": ["music", "song", "concert", "singer", "melody", "album"],
        "影视": ["film", "movie", "drama", "tv series", "cinema", "actor", "director"],
        "名人": ["celebrity", "superstar", "famous", "star", "idol"],
        "体育": ["sport", "match", "athlete", "olympic", "football", "basketball", "champion"],
        "游戏": ["game", "gaming", "esports", "video game"],
    },
    "mind": {
        "教育": ["education", "learning", "school", "campus", "student", "teacher", "exam"],
        "心理健康": ["mental health", "stress", "wellbeing", "emotion", "psychology", "anxiety"],
        "习惯养成": ["habit", "routine", "self-discipline", "behavior"],
        "社会心理": ["social behavior", "psychology", "public opinion", "society"],
        "领导力": ["leadership", "management", "team", "career", "workplace"],
    },
}

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151 Safari/537.36"

_CACHE = {}
_CACHE_TTL = 300  # 5 分钟内复用已抓取结果，避免每次点主题都重新抓源（首次较慢，之后秒回）

# SSL 兼容：桥接层只抓公开 RSS/HN/头条热榜（明文可信内容），无需证书验证。
# 避免系统 Python 自带证书库不全时抓取失败；改用未校验 ctx。
import ssl as _ssl_mod
try:
    _SSL_CTX = _ssl_mod.create_default_context()
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = _ssl_mod.CERT_NONE
except Exception:
    _SSL_CTX = None

def fetch(url, timeout=12):
    now = time.time()
    hit = _CACHE.get(url)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    if url.startswith("https://"):
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_SSL_CTX),
            urllib.request.ProxyHandler({})
        )
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        data = r.read()
    _CACHE[url] = (now, data)
    return data


def clean_html(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"\s+", " ", s).strip()


def parse_ts(date_str):
    try:
        return parsedate_to_datetime(date_str).timestamp()
    except Exception:
        return 0.0


def parse_feed(data, source):
    items = []
    try:
        root = ET.fromstring(data)
    except Exception:
        return items
    for item in root.iter("item"):
        title = clean_html(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        desc = clean_html(item.findtext("description") or "")
        date = (item.findtext("pubDate") or "").strip()
        if title and link:
            items.append({"topic": title, "source": source, "url": link,
                          "summary": desc[:600], "date": date, "ts": parse_ts(date)})
    if not items:  # Atom
        ATOM = "{http://www.w3.org/2005/Atom}"
        for e in root.iter(ATOM + "entry"):
            title = clean_html(e.findtext(ATOM + "title") or "")
            link_el = e.find(ATOM + "link")
            link = link_el.get("href") if link_el is not None else ""
            desc = clean_html(e.findtext(ATOM + "summary") or "")
            date = (e.findtext(ATOM + "updated") or "").strip()
            if title and link:
                items.append({"topic": title, "source": source, "url": link,
                              "summary": desc[:600], "date": date, "ts": parse_ts(date)})
    return items


# ==================== 原文抓取层（第一层）====================
# 背景：此前英文 RSS 只取 description（截断 600 字符），中文热点甚至用 LLM 编造的
# 摘要冒充原文，导致「事实抽取」建立在摘要甚至幻觉之上。这一层统一负责：
#   按 URL 抓网页 → 抽取正文 → 标记可信状态 → 磁盘缓存
# 原则：抓不到就用摘要兜底并如实标记，绝不伪造。

# 注意：此处不能用 _CACHE_DIR —— 它定义在本文件更靠后的位置，模块级引用会 NameError
_ARTICLE_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".article_cache.json")
_article_cache_lock = threading.Lock()
_article_mem = None

# 判定为「正文完整」的最少字符数（实测正常新闻正文在 2k–7k 字符）
MIN_ARTICLE_CHARS = 800
# 超过此大小的页面不进磁盘缓存，避免缓存膨胀（实测 LiveScience 单页 2.2MB）
MAX_CACHE_BYTES = 1024 * 1024
# 正文抽取时长度低于此值的段落视为噪音丢弃
MIN_PARA_CHARS = 30

# 样板文字特征：命中即丢弃该段落（中英文兼收）
_BOILERPLATE = (
    "cookie", "privacy policy", "terms of use", "terms of service", "all rights reserved",
    "subscribe", "newsletter", "sign up", "sign in", "log in", "follow us", "share this",
    "read more", "continue reading", "related article", "advertisement", "enable javascript",
    "please enable", "your browser", "© ", "get the world", "delivered straight to your inbox",
    "同意", "隐私", "版权所有", "订阅", "登录", "注册", "Cookie", "Cookies", "请开启", "浏览器",
)


def _load_article_cache():
    global _article_mem
    with _article_cache_lock:
        if _article_mem is None:
            try:
                with open(_ARTICLE_CACHE_FILE, "r", encoding="utf-8") as f:
                    _article_mem = json.load(f)
            except FileNotFoundError:
                _article_mem = {}
            except Exception as e:
                # 解析失败当作空缓存，但必须留痕：否则会静默重复抓取，用户以为在缓存
                note_error("article.cache.load", e, severity="warn",
                           msg="原文缓存解析失败，已按空缓存处理，本次将重新抓取")
                _article_mem = {}
        return _article_mem


def _save_article_cache():
    with _article_cache_lock:
        try:
            tmp = _ARTICLE_CACHE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_article_mem, f, ensure_ascii=False)
            os.replace(tmp, _ARTICLE_CACHE_FILE)
        except Exception as e:
            note_error("article.cache.save", e, severity="warn", msg="原文缓存写入失败（不影响本次结果）")


# ============ 源健康度（第四层）============
# 正文抓取是启发式的，网站改版会静默失效。这里按信源累计成功率与耗时，
# 让「一直在降级」变得可见，而不是看起来一切正常。
_SOURCE_HEALTH = {}
_sh_lock = threading.Lock()


def _health_record(source, status, ms):
    if not source:
        return
    with _sh_lock:
        h = _SOURCE_HEALTH.setdefault(source, {"ok": 0, "short": 0, "failed": 0,
                                               "no_source": 0, "summary_only": 0, "n": 0, "ms": 0})
        h[status] = h.get(status, 0) + 1
        h["n"] += 1
        h["ms"] += int(ms)


def source_health_payload():
    with _sh_lock:
        out = []
        for s, h in sorted(_SOURCE_HEALTH.items()):
            n = h["n"] or 1
            good = h.get("ok", 0) + h.get("short", 0)
            out.append({"source": s, "n": h["n"], "ok": h.get("ok", 0), "short": h.get("short", 0),
                        "failed": h.get("failed", 0), "no_source": h.get("no_source", 0),
                        "success_rate": round(good / n, 3), "avg_ms": int(h["ms"] / n)})
        return out


def extract_main_text(html):
    """从 HTML 抽取正文主体。返回 (正文文本, 段落数)。

    策略：优先取 <article> 容器，否则用整页；再收集长度达标的 <p> 段落，剔除样板文字。
    这是启发式抽取，网站改版会失效 —— 失败率由 fetch_article 的状态标记暴露，不静默。"""
    if not html:
        return "", 0
    try:
        s = html
    except Exception:
        return "", 0
    # 先去掉脚本/样式与结构性噪音区块
    s = re.sub(r"(?is)<script\b.*?</script>", " ", s)
    s = re.sub(r"(?is)<style\b.*?</style>", " ", s)
    s = re.sub(r"(?is)<noscript\b.*?</noscript>", " ", s)
    for tag in ("nav", "header", "footer", "aside", "form", "figure"):
        s = re.sub(r"(?is)<%s\b.*?</%s>" % (tag, tag), " ", s)
    m = re.search(r"(?is)<article\b[^>]*>(.*?)</article>", s)
    body = m.group(1) if m else s
    paras = []
    for pm in re.finditer(r"(?is)<p\b[^>]*>(.*?)</p>", body):
        t = clean_html(pm.group(1))
        if len(t) < MIN_PARA_CHARS:
            continue
        low = t.lower()
        if any(b.lower() in low for b in _BOILERPLATE):
            continue
        paras.append(t)
    if not paras:
        # 没有 <p> 结构（部分站点用 <div> 承载），退化为整页去标签文本
        t = clean_html(body)
        return (t, 1) if t else ("", 0)
    return "\n\n".join(paras), len(paras)


def fetch_article(url, timeout=15, use_cache=True):
    """抓取并抽取一篇文章的正文。返回 dict：
       {text, len, status, err}
       status: ok(正文达标) / short(抓到但偏短) / failed(抓不到或抽取为空)
    结果写入磁盘缓存，同一 URL 不重复抓取。"""
    out = {"text": "", "len": 0, "status": "failed", "err": ""}
    if not url:
        out["err"] = "empty url"
        return out
    cache = _load_article_cache()
    key = hashlib.md5(url.encode("utf-8")).hexdigest()
    if use_cache:
        hit = cache.get(key)
        if hit and isinstance(hit, dict) and hit.get("len"):
            return {"text": hit.get("text", ""), "len": hit.get("len", 0),
                    "status": hit.get("status", "failed"), "err": hit.get("err", "")}
    try:
        data = fetch(url, timeout=timeout)
        html = data.decode("utf-8", "ignore")
    except Exception as e:
        out["err"] = "%s: %s" % (type(e).__name__, e)
        note_error("article.fetch", e, severity="warn", url=url, msg="原文抓取失败，已回退为摘要")
        return out
    try:
        text, paras = extract_main_text(html)
    except Exception as e:
        note_error("article.extract", e, severity="warn", url=url, msg="正文抽取异常")
        text, paras = "", 0
    n = len(text)
    out["text"] = text
    out["len"] = n
    if n >= MIN_ARTICLE_CHARS:
        out["status"] = "ok"
    elif n > 0:
        out["status"] = "short"
        out["err"] = "正文仅 %d 字符（低于 %d），可能未抓完整" % (n, MIN_ARTICLE_CHARS)
    else:
        out["err"] = "未能抽取到正文"
    if out["status"] in ("ok", "short") and len(html) <= MAX_CACHE_BYTES:
        cache[key] = {"text": out["text"], "len": n, "status": out["status"],
                      "err": out["err"], "ts": int(time.time())}
        _save_article_cache()
    return out


def enrich_fulltext(items, workers=8, only_missing=True):
    """批量为一批热点补齐原文。就地写入 fulltext / fulltext_len / fulltext_status / fulltext_err。
    抓不到时保留原有 summary 作为兜底，绝不伪造。"""
    targets = []
    for it in items:
        # no_source = 已经按 A→B→C 链路试过并确认拿不到，不重复浪费时间
        if it.get("fulltext_status") == "no_source":
            continue
        if only_missing and (it.get("fulltext") or "").strip():
            continue
        if not it.get("url"):
            continue
        targets.append(it)

    def one(it):
        t0 = time.time()
        r = fetch_article(it["url"])
        _health_record(it.get("source"), r["status"], (time.time() - t0) * 1000)
        return it, r

    if not targets:
        return items
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for it, r in ex.map(one, targets):
            it["fulltext_status"] = r["status"]
            it["fulltext_err"] = r["err"]
            if r["status"] in ("ok", "short") and r["len"] > len(it.get("fulltext") or ""):
                it["fulltext"] = r["text"]
            it["fulltext_len"] = len(it.get("fulltext") or "")
            if r["status"] == "failed":
                # 保留摘要兜底，但状态如实标记，前端必须能看出来
                it.setdefault("fulltext", it.get("summary", ""))
                it["fulltext_len"] = len(it.get("fulltext") or "")
                it["fulltext_status"] = "summary_only"
    for it in items:
        it.setdefault("fulltext_status", "unknown")
        it.setdefault("fulltext_len", len(it.get("fulltext") or ""))
    return items


def match_entry(text, theme, sub=None):
    """返回 (是否命中, 命中的子主题, 命中次数)"""
    if theme not in THEME_KEYWORDS:
        return False, "", 0
    t = text.lower()
    subs = THEME_KEYWORDS[theme]
    if sub and sub in subs:
        kws = subs[sub]
        hit = sum(1 for kw in kws if kw in t)
        return hit > 0, sub, hit
    best_sub, best_hit = "", 0
    for s, kws in subs.items():
        hit = sum(1 for kw in kws if kw in t)
        if hit > best_hit:
            best_hit, best_sub = hit, s
    return best_hit > 0, best_sub, best_hit


# 热点粗分类关键词（仅用于第 02 步按大类筛选，不做内容过滤）。
# 精确的 74 个内容标签由第 04 步的 /api/tags/extract 用 LLM 判定，这里只做便宜的大类归属。
NEUTRAL_KEYWORDS = {
    "world": ["国际", "外交", "联合国", "峰会", "制裁", "谈判", "停火", "边境", "难民", "地震", "洪水",
              "台风", "救援", "灾难", "法规", "立法", "法案", "判决", "诉讼", "权利", "平权", "公益",
              "慈善", "地铁", "公交", "出行", "拥堵",
              "united nations", "summit", "sanction", "ceasefire", "border", "refugee",
              "earthquake", "flood", " hurricane", "typhoon", "relief", "lawsuit", "verdict",
              "policy", "rights", "charity", "transit"],
    "science": ["科技", "人工智能", "AI", "大模型", "模型", "芯片", "半导体", "量子", "航天", "火箭", "卫星",
                "太空", "月球", "火星", "探测器", "气候", "碳排放", "新能源", "光伏", "储能", "电池",
                "电力", "电网", "供电", "发电", "用电", "核能",
                "基因", "疫苗", "医学", "临床", "天文", "物理", "化学", "物种", "实验",
                "artificial intelligence", "machine learning", "chatgpt", "claude", "gpt", "llm",
                "openai", "deepseek", "chip", "semiconductor", "quantum", "model",
                "space", "rocket", "satellite", "nasa", "climate", "emission", "gene", "vaccine",
                "physics", "research", "scientists", "study finds"],
    "culture": ["电影", "票房", "剧集", "综艺", "音乐", "演唱会", "专辑", "明星", "艺人", "偶像",
                "足球", "篮球", "奥运", "赛事", "动漫", "游戏", "时尚", "美妆", "美食", "餐厅",
                "旅行", "景区", "博物馆", "展览", "非遗", "传统节日", "民俗", "方言", "汉字",
                "movie", "film", "music", "album", "concert", "celebrity", "football", "olympics",
                "anime", "gaming", "fashion", "food", "travel", "museum", "exhibition", "heritage",
                "festival", "language"],
    "business": ["公司", "企业", "上市", "融资", "并购", "营收", "财报", "股价", "市值", "裁员",
                 "创业", "初创", "投资", "基金", "消费", "零售", "品牌", "营销", "职场", "招聘",
                 "薪资", "行业", "供应链", "关税",
                 "startup", "funding", "ipo", "merger", "revenue", "earnings", "stock", "market cap",
                 "layoff", "invest", "consumer", "retail", "brand", "hiring", "supply chain", "tariff"],
    "growth": ["教育", "学校", "学生", "高考", "考研", "留学", "课程", "教师", "心理", "情绪",
               "焦虑", "习惯", "自律", "拖延", "沟通", "人际", "亲子", "育儿", "健身", "运动",
               "冥想", "职场成长", "领导力",
               "education", "school", "student", "university", "study abroad", "learning",
               "psychology", "mental health", "anxiety", "habit", "productivity", "parenting",
               "fitness", "mindfulness", "leadership"],
    "story": ["小说", "短篇", "名著", "科幻", "悬疑", "推理", "奇幻", "童话", "寓言", "散文",
              "诗歌", "演讲", "连载", "改编",
              "novel", "short story", "classic", "sci-fi", "mystery", "fantasy", "fairy tale",
              "poetry", "essay", "speech"],
}



# 中文子主题关键词（头条中文热点 → 主题内的具体子主题；与前端 DIRS.subs 对齐）
ZH_SUB_KEYWORDS = {
    "tech": {
        "机器人": ["宇树", "机器人", "人形机器人", "机械臂", "robotics"],
        "能源": ["特斯拉", "比亚迪", "新能源", "电动车", "电池", "充电", "光伏", "储能", "新能源车", "马斯克", "汽车", "电网"],
        "前沿科技": ["苹果", "华为", "小米", "芯片", "半导体", "自动驾驶", "大模型", "AI", "人工智能", "deepseek", "openai", "英伟达", "gpt", "算法", "算力", "数据中心", "科技", "互联网", "手机", "无人机", "5g", "6g", "量子"],
        "太空": ["航天", "火箭", "卫星", "月球", "火星", "太空", "宇航员", "空间站"],
        "健康医疗": ["医疗", "健康", "医院", "疾病", "疫苗", "药", "基因", "生物科技", "脑机"],
        "AI": ["人工智能", "AI", "大模型", "机器学习", "聊天机器人", "chatgpt"],
    },
    "pop": {
        "影视": ["电影", "电视剧", "剧集", "演员", "导演", "票房", "综艺"],
        "音乐": ["音乐", "歌曲", "演唱会", "歌手", "专辑"],
        "名人": ["明星", "偶像", "名人", "绯闻", "八卦"],
        "体育": ["体育", "赛事", "运动员", "奥运", "足球", "篮球", "比赛", "冠军"],
        "游戏": ["游戏", "电竞", "电子游戏"],
        "网络趋势": ["网红", "短视频", "热搜", "梗", "主播"],
    },
    "mind": {
        "教育": ["教育", "学校", "学生", "老师", "考试", "校园", "高考", "开学"],
        "心理健康": ["心理健康", "心理", "压力", "情绪", "焦虑", "抑郁"],
        "社会心理": ["社会", "公众", "舆论", "从众"],
        "领导力": ["管理", "领导", "团队", "职场"],
    },
    "city": {
        "街头美食": ["美食", "小吃", "餐厅", "餐饮", "夜宵"],
        "交通": ["交通", "地铁", "通勤", "公交", "道路"],
        "住房": ["住房", "租房", "房价", "房产", "楼盘"],
        "本地商业": ["商铺", "商圈", "集市", "零售", "商业"],
    },
    "travel": {
        "乡村": ["乡村", "农村", "村庄", "田园"],
        "人口变化": ["人口", "移民", "出生率", "老龄化"],
        "民生议题": ["民生", "养老", "就业", "公共服务", "工资", "社保"],
        "商业思维": ["企业", "公司", "商业模式", "行业", "产业", "经济"],
    },
    "culture": {
        "传统节日": ["节日", "春节", "中秋", "端午", "七夕", "过年"],
        "艺术": ["艺术", "非遗", "工艺", "美术", "陶瓷", "剪纸", "文物", "展览", "博物馆"],
        "科学常识": ["科学", "常识", "天文", "物理", "化学", "生物", "科普"],
        "语言": ["语言", "英语", "词汇", "语法", "双语"],
        "书籍机构": ["书", "图书馆", "博物馆", "书籍", "经典", "小说", "阅读", "文学", "典籍"],
    },
}

def match_entry_zh(text, theme):
    """中文子主题匹配：返回 (是否命中, 子主题)。中文标题用，英文走 match_entry。"""
    if theme not in ZH_SUB_KEYWORDS:
        return False, ""
    t = text or ""
    subs = ZH_SUB_KEYWORDS[theme]
    best_sub, best_hit = "", 0
    for sname, kws in subs.items():
        hit = sum(1 for kw in kws if kw in t)
        if hit > best_hit:
            best_hit, best_sub = hit, sname
    return best_hit > 0, best_sub


def classify_theme(text):
    """按关键词命中数给热点做大类归属，返回新体系的类别键（world/science/culture/business/growth/story）。
    只用于第 02 步筛选；第 04 步的精确标签走 /api/tags/extract。"""
    t = (text or "").lower()
    best_theme, best_hit = "world", 0
    for theme, kws in NEUTRAL_KEYWORDS.items():
        hit = sum(1 for kw in kws if kw.lower() in t)
        if hit > best_hit:
            best_hit, best_theme = hit, theme
    return best_theme

def classify_among(text, allowed):
    """只在允许的类别里选最贴合的（用于多类别信源，如 China Daily 同时标 world/culture）。
    避免全局分类把已知信源的内容误归到毫不相干的类别（实测 Variety/ESPN 曾被归到 world）。"""
    t = (text or "").lower()
    best_hit, best_key = -1, (allowed[0] if allowed else "world")
    for k in allowed:
        hit = sum(1 for kw in NEUTRAL_KEYWORDS.get(k, []) if kw.lower() in t)
        if hit > best_hit:
            best_hit, best_key = hit, k
    return best_key



# 硅基流动：中文标题 → 英文标题 + 英文背景摘要（头条无正文，摘要作为素材兜底）
SF_KEY = os.environ.get("SF_API_KEY", "")   # 密钥不入库：从环境变量读取，见 .env.example
SF_URL = "https://api.siliconflow.cn/v1/chat/completions"
SF_MODEL = "deepseek-ai/DeepSeek-V4-Flash"

# ============ 错误处理：任何失败都必须留痕 ============
# 原则：
#   1) 内部有正确兜底的失败（如读缓存失败→重新计算）只记录，不打断流程；
#   2) 会让用户看到错误结果的失败（如抓取源挂了→界面显示"没有内容"），
#      必须由接口随响应带回前端，显式告诉用户"这是失败，不是没数据"。
# 绝不出现 except: pass 之后无人知晓的情况。
ERROR_LOG = []          # 近期错误（有界环形缓冲）
ERROR_LOG_MAX = 200

def _redact(s):
    """错误信息脱敏：任何地方都不允许把 API Key 带出去。"""
    out = str(s or "")
    if SF_KEY:
        out = out.replace(SF_KEY, "***")
    return re.sub(r"(sk-[A-Za-z0-9]{8})[A-Za-z0-9]+", r"\1***", out)

def note_error(scope, exc=None, msg=None, severity="error", **ctx):
    """记录一次失败。severity: error=影响用户看到的结果 / warn=内部已兜底"""
    e = {
        "ts": int(time.time() * 1000),
        "scope": str(scope),
        "severity": severity,
        "type": type(exc).__name__ if exc is not None else "Error",
        "msg": _redact(msg if msg is not None else (exc if exc is not None else "")),
    }
    if ctx:
        e["ctx"] = {k: _redact(v) for k, v in ctx.items()}
    ERROR_LOG.append(e)
    if len(ERROR_LOG) > ERROR_LOG_MAX:
        del ERROR_LOG[0:len(ERROR_LOG) - ERROR_LOG_MAX]
    try:
        sys.stderr.write("[%s] %s: %s\n" % (severity, e["scope"], e["msg"]))
        sys.stderr.flush()
    except Exception:
        pass
    return e

def drain_errors(since_ts, severity=None):
    """取 since_ts 之后记录的错误，供接口随响应带回前端"""
    out = [e for e in ERROR_LOG if e["ts"] >= since_ts]
    if severity:
        out = [e for e in out if e["severity"] == severity]
    return out

# ============ 内容标签体系（三层） ============
# 单一真源：前端不再内置副本，改为 GET /api/tags/taxonomy 拉取。
# 之前前后端各存一份子主题词表，已经分叉（后端中文词典比前端少 7 个子主题），
# 导致中文热点永远匹配不到那些子主题。改为后端唯一持有，杜绝再次分叉。
TAXONOMY_VERSION = "2026.09.02"

CONTENT_TAGS = [
    ("world", "世界", "World", [
        ("全球热点", "Global headlines"), ("国际局势", "International affairs"),
        ("社会观察", "Society"), ("法律法规", "Law & policy"),
        ("公平权利", "Rights & equity"), ("战争冲突", "War & conflict"),
        ("灾难救援", "Disaster & relief"), ("城市出行", "Urban mobility"),
        ("慈善公益", "Charity"), ("环境环保", "Environment"),
    ]),
    ("science", "科学", "Science", [
        ("前沿科技", "Frontier tech"), ("人工智能", "AI"),
        ("宇宙太空", "Space"), ("自然地理", "Nature & geography"),
        ("动物世界", "Animals"), ("人体奥秘", "Human body"),
        ("心理探索", "Psychology"), ("气候能源", "Climate & energy"),
        ("农业科技", "Agricultural tech"), ("科学史话", "History of science"),
        ("科普冷知识", "Science trivia"), ("数码科技", "Consumer tech"),
        ("医学健康", "Medicine & health"), ("社会科学", "Social sciences"),
    ]),
    ("culture", "文化", "Culture", [
        ("影视娱乐", "Film & TV"), ("音乐", "Music"),
        ("体育竞技", "Sports"), ("动漫二次元", "Anime & comics"),
        ("游戏世界", "Games"), ("时尚美妆", "Fashion & beauty"),
        ("饮食文化", "Food culture"), ("旅行故事", "Travel stories"),
        ("历史故事", "History"), ("节日民俗", "Festivals & folklore"),
        ("文化现象", "Cultural trends"), ("艺术设计", "Design"),
        ("语言文字", "Language"), ("网络热梗", "Internet memes"),
        ("宠物生活", "Pets"), ("名人明星", "Celebrities"),
        ("中国文化", "Chinese culture"),
    ]),
    ("business", "商业", "Business", [
        ("商业故事", "Business stories"), ("创业故事", "Startups"),
        ("职场生存", "Workplace"), ("团队管理", "Team management"),
        ("财经观察", "Finance"), ("消费观察", "Consumer trends"),
        ("投资理财", "Investing"), ("品牌营销", "Brand & marketing"),
        ("行业趋势", "Industry trends"), ("职业探索", "Careers"),
        ("办公方式", "Ways of working"), ("领导力", "Leadership"),
        ("企业文化", "Company culture"),
    ]),
    ("growth", "成长", "Growth", [
        ("校园升学", "School & admissions"), ("教育观察", "Education"),
        ("学习方法", "Study methods"), ("高效思维", "Thinking skills"),
        ("自我驱动", "Self-motivation"), ("习惯养成", "Habits"),
        ("沟通表达", "Communication"), ("人际关系", "Relationships"),
        ("情绪调节", "Emotional regulation"), ("运动健身", "Fitness"),
        ("人物故事", "Personal stories"), ("家庭亲子", "Family & parenting"),
        ("人生思考", "Life reflections"), ("留学海外", "Studying abroad"),
        ("发展创造", "Creativity & growth"), ("亲密关系", "Intimate relationships"),
        ("家居生活", "Home life"),
    ]),
    ("story", "故事", "Stories", [
        ("短篇故事", "Short stories"), ("经典名著", "Classics"),
        ("科幻故事", "Sci-fi"), ("悬疑推理", "Mystery"),
        ("奇幻冒险", "Fantasy & adventure"), ("成长励志", "Coming-of-age"),
        ("童话寓言", "Fairy tales"), ("幽默喜剧", "Humor"),
        ("诗歌散文", "Poetry & essays"), ("演讲名篇", "Speeches"),
    ]),
]
COGNITIVE_TAGS = [("全年龄", "All ages"), ("青少年向", "Teen"), ("成人向", "Adult")]

_CAT_ZH = {c: z for c, z, e, _t in CONTENT_TAGS}
_CAT_EN = {c: e for c, z, e, _t in CONTENT_TAGS}
_TAG_EN = {(c, t): te for c, z, e, tags in CONTENT_TAGS for t, te in tags}
_COGNITIVE_ZH = [c for c, _e in COGNITIVE_TAGS]

def taxonomy_payload():
    return {
        "version": TAXONOMY_VERSION,
        "categories": [
            {"key": c, "zh": z, "en": e, "tags": [{"zh": t, "en": te} for t, te in tags]}
            for c, z, e, tags in CONTENT_TAGS
        ],
        "cognitive": [{"zh": z, "en": e} for z, e in COGNITIVE_TAGS],
    }

# 翻译缓存（磁盘持久化，头条标题短期不变，命中后秒回）
_CACHE_DIR = os.path.dirname(os.path.abspath(__file__))
_TR_CACHE_FILE = os.path.join(_CACHE_DIR, ".toutiao_en_cache.json")

def _load_tr_cache():
    try:
        with open(_TR_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        # 有兜底（未命中就重新翻译，结果仍然正确，只是慢且费钱）→ warn 级
        note_error("cache.translation.load", e, severity="warn", file=_TR_CACHE_FILE)
        return {}


L_EMPTY_TAGS = "AI 未给出有效的一级内容标签，请手动选择或点重新提取"

# ============ 内容标签提取（第一层 / 第二层 / 第三层）============
_TAG_CACHE_FILE = os.path.join(_CACHE_DIR, ".content_tags_cache.json")

def _load_tag_cache():
    if not os.path.exists(_TAG_CACHE_FILE):
        return {}          # 冷启动属正常情况，不该每次都告警
    try:
        with open(_TAG_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        note_error("cache.tags.load", e, severity="warn", file=_TAG_CACHE_FILE)
        return {}

def _save_tag_cache(d):
    try:
        with open(_TAG_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        note_error("cache.tags.save", e, severity="warn", file=_TAG_CACHE_FILE)

def _tags_prompt(material, title):
    vocab = "\n".join(
        "- %s（键 %s / %s）：%s" % (z, c, e, "、".join(t for t, _te in tags))
        for c, z, e, tags in CONTENT_TAGS
    )
    return (
        "你是内容标签专家。请为一篇面向英语学习者的分级阅读文章打三层标签。\n\n"
        "【第一层 内容标签】闭集，只能从下面这些里选，不得自造：\n" + vocab + "\n\n"
        "【第三层 认知标签】只能从这三个里选一个：" + " / ".join(_COGNITIVE_ZH) + "\n\n"
        "文章内容：\n" + (str(title or "").strip() or "（无标题）") + "\n" + str(material or "")[:3000] + "\n\n"
        "严格按下面这个 JSON 返回，不要任何解释文字：\n"
        '{"content":[{"cat":"类别键","tag":"中文标签"}],'
        '"free":[{"tag":"马斯克","src":"Elon Musk said at a tech conference"}],'
        '"cognitive":"全年龄",'
        '"reason":"一句话说明为什么选这些标签"}\n\n'
        "要求：\n"
        "1. content 选 1–3 个最贴切的（多个都贴切时就都给，不要只给一个）；"
        "cat 必须是上面给的类别键，tag 必须**逐字照抄**上面列表里的中文标签名，"
        "一个字都不要改，也不要自造新标签——自造的会被丢弃导致这一层为空；"
        "如果找不到完全贴切的，就选最接近的类别下相对最贴切的那个；"
        "cat 必须是上面给的类别键（world/science/culture/business/growth/story），"
        "tag 必须属于该类别下的闭集，否则会被丢弃；\n"
        "2. free 给 5 个自由标签，每个都要带上**原文依据片段**："
        '写成 {"tag":"中文标签","src":"原文中真实出现的英文/中文原句片段"}。'
        "tag 应是正文中真实出现的具体实体/专有名词：人名、机构名、地名、产品名、事件名"
        "（如 马斯克、ChatGPT、敦煌、NASA、苹果发布会）。"
        "src 必须是从正文里原样摘出的片段，用于后端核验——摘不出来就说明这个标签不该给。"
        "⚠️ 严禁推断或编造正文里没有的内容，编造项会被后端检测并丢弃。"
        "不要抽象概念词，不要使用第一层词表里出现过的任何词；\n"
        "3. cognitive 按内容受众判断；\n"
        "4. 只输出 JSON。"
    )

def _has_cjk(s):
    return any("\u4e00" <= c <= "\u9fff" for c in str(s or ""))

# 标签反查表：中文名、英文名（小写）、带 # 前缀都能命中。
# 模型经常返回英文名或写成「#人工智能」，严格按中文名比对会把有效结果全丢掉。
_TAG_LOOKUP = {}
for _c, _z, _e, _tags in CONTENT_TAGS:
    for _t, _te in _tags:
        _TAG_LOOKUP[_t] = (_c, _t, _te)
        _TAG_LOOKUP.setdefault(_te.lower(), (_c, _t, _te))

def resolve_content_tag(cat, tag):
    """把模型返回的 (cat, tag) 归一到词表内的 (cat, zh, en)。命中不了返回 None。
    cat 与 tag 冲突时以 tag 为准——模型经常把类别键写错，但标签名是对的。"""
    key = str(tag or "").strip()
    if not key:
        return None
    for cand in (key, key.lower(), key.lower().lstrip("#").strip(), key.lstrip("#").strip()):
        if cand in _TAG_LOOKUP:
            return _TAG_LOOKUP[cand]
    return None

def tag_grounded(tag, material, src=None):
    """自由标签是否能在原文中找到依据。

    LLM 会编造正文里没有的实体（实测出现过 Slack / YC Combinator 这类凭空产物），
    用于可行性验证的 demo 里不可接受，故做硬性校验：找不到依据就丢弃。

    2026-09-03 修复误杀（Bryan 反馈「李月汝」被当编造丢弃，而它正是主角）：
    旧实现 src 优先且 src 比对失败即 return False —— 模型给 src 时若 src 是
    改写句/翻译句（跟原文有出入），会把「标签本身明明在原文里」的真标签也误杀。
    新顺序：① 标签直接命中原文 → 放行（最强证据，不看 src）；
    ② 标签没命中（典型：中文标签 vs 英文正文的跨语种）→ 才用 src 核验；
    ③ 无 src 且跨语种 → 无法核验，宁可漏检放行（保持原语义）。
    编造实体在第 ① 步就过不了，后续照旧被拦，安全性不放松。
    """
    t = str(tag or "").strip()
    m = str(material or "")
    if not t or not m:
        return False
    s = str(src or "").strip()
    low_m = m.lower()
    low_t = t.lower()

    # ① 标签直接命中原文（同语种最强证据）—— 即使 src 对不上也应放行
    if t in m or low_t in low_m:
        return True
    # 中日韩：容忍简称/译名差异，>=3 字连续窗口匹配
    if len(t) >= 3:
        for i in range(len(t) - 2):
            if t[i:i + 3] in m:
                return True

    # ② 标签没直接命中，借助 src 核验（主要是跨语种：中文标签 vs 英文正文，
    #    直接拿中文标签比对英文正文必然误判，需模型回传的原文片段）
    if s:
        # 原文片段：先整段比对，再退化为较长子串（容忍模型摘取时带轻微改动）
        if s in m or s.lower() in low_m:
            return True
        core = max(re.split(r"[\s，。,.、；;：:]", s), key=len) if re else s
        if len(core) >= 4 and (core in m or core.lower() in low_m):
            return True
        return False

    # ③ 无 src 且标签没命中：跨语种时无法可靠核验，放行
    if _has_cjk(t) != _has_cjk(m):
        return True
    # 拉丁字母：>=5 字符时再放宽到小写 4 字子串，避免 a/an 之类误命中
    if len(t) >= 5 and any("a" <= c <= "z" or "A" <= c <= "Z" for c in t):
        for i in range(len(t) - 3):
            if low_t[i:i + 4] in low_m:
                return True
    return False

def normalize_tags(obj, material=None):
    """按闭集校验 LLM 输出：不在词表内的一律丢弃，认知标签非法则回落全年龄，
    自由标签无法在原文中找到依据的一律丢弃。宁可少给，也不透传模型编造的内容。"""
    content, seen = [], set()
    for c in (obj.get("content") or []):
        if not isinstance(c, dict):
            continue
        hit = resolve_content_tag(c.get("cat"), c.get("tag"))
        if not hit:
            continue
        cat, tag, tag_en = hit
        if tag in seen:
            continue
        seen.add(tag)
        content.append({"cat": cat, "tag": tag, "tagEn": tag_en,
                        "catZh": _CAT_ZH.get(cat, cat), "catEn": _CAT_EN.get(cat, cat)})
    content = content[:3]

    # 自由标签必须与第一层闭集互斥：不能只靠模型自觉，后端强制过滤
    vocab_zh = {t for _c, _z, _e, tags in CONTENT_TAGS for t, _te in tags}
    free, dup_free, ungrounded = [], [], []
    for f in (obj.get("free") or []):
        if isinstance(f, dict):
            tag = str(f.get("tag") or "").strip()
            src = str(f.get("src") or "").strip()
        else:
            tag, src = str(f or "").strip(), ""
        if not tag or len(tag) > 24 or tag in free:
            continue
        if tag in vocab_zh:
            dup_free.append(tag)
            continue
        if material is not None and not tag_grounded(tag, material, src):
            ungrounded.append(tag)
            continue
        free.append(tag)
    free = free[:8]

    cog = str(obj.get("cognitive") or "").strip()
    if cog not in _COGNITIVE_ZH:
        cog = "全年龄"

    dropped = []
    raw_content = obj.get("content") or []
    if isinstance(raw_content, list) and len(raw_content) > len(content):
        dropped.append("内容标签丢弃 %d 个（不在闭集内）" % (len(raw_content) - len(content)))
    if dup_free:
        dropped.append("自由标签去重丢弃 %d 个（与第一层词表重复）：%s" % (len(dup_free), "、".join(dup_free[:5])))
    if ungrounded:
        dropped.append("自由标签丢弃 %d 个（正文中找不到依据，判定为模型编造）：%s"
                       % (len(ungrounded), "、".join(ungrounded[:5])))

    return {
        "content": content,
        "free": free,
        "cognitive": cog,
        "reason": str(obj.get("reason") or "")[:200],
        "dropped": dropped,
        "grounded": material is not None,
    }

def extract_tags(material, title=""):
    """三层标签提取。返回 (result, err)。带磁盘缓存（同一素材不重复计费）。

    2026-09-03 修复两个连带问题（用户反馈「AI 未给出有效一级内容标签且重试无效」）：
    ① 空结果不再写缓存 —— 旧实现无条件 cache[key]=result，模型偶发抽风产生的
       空结果也被缓存，点「重新提取」命中同一个空缓存，永远救不回来；
    ② 抽空自动重试最多 2 次 —— 模型偶发不守「逐字照抄」指令自创词表外标签时，
       多数一次重试即恢复。三次仍空才提示手动选择，且绝不入缓存。
    """
    if not material:
        return None, "missing material"
    key = hashlib.md5((str(title) + "\n" + str(material)).encode("utf-8")).hexdigest()[:16]
    cache = _load_tag_cache()
    if key in cache:
        r = dict(cache[key])
        r["cached"] = True
        r["elapsed_ms"] = 0
        return r, None

    t0 = time.time()
    last_err = None
    for attempt in range(3):
        try:
            resp = _sf_chat([{"role": "user", "content": _tags_prompt(material, title)}], 700)
            content = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
            m = re.search(r"\{.*\}", content, re.S)
            if not m:
                last_err = "供应商未按 JSON 返回"
                note_error("tags.extract", msg=last_err, severity="warn",
                           raw=_redact(content)[:200], title=title)
                continue
            obj = json.loads(m.group(0))
        except Exception as e:
            last_err = _redact(e)
            note_error("tags.extract", e, severity="error", title=title)
            continue

        result = normalize_tags(obj, material)
        result["model"] = SF_MODEL
        result["provider"] = "siliconflow"
        result["elapsed_ms"] = int((time.time() - t0) * 1000)
        if result["content"]:
            # 只缓存有效结果；空结果/失败一律不写，保证「重新提取」真正重新调模型
            result["cached"] = False
            cache[key] = result
            _save_tag_cache(cache)
            return result, None
        last_err = None
        note_error("tags.extract", severity="warn", title=title,
                   msg="LLM 返回的内容标签不在闭集内（第 %d 次尝试），自动重试" % (attempt + 1),
                   raw=_redact(str(obj.get("content"))[:200]))

    # 连续 3 次未抽到有效内容标签：不写缓存（避免重试命中空缓存），
    # 返回带 warning 的空结果，让前端引导用户手动选择
    empty = {
        "content": [], "free": [], "cognitive": [],
        "warning": L_EMPTY_TAGS, "cached": False,
        "model": SF_MODEL, "provider": "siliconflow",
        "elapsed_ms": int((time.time() - t0) * 1000), "retried": True,
    }
    if last_err:
        return None, last_err
    return empty, None

def _save_tr_cache(d):
    try:
        with open(_TR_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception as e:
        note_error("cache.translation.save", e, severity="warn", file=_TR_CACHE_FILE)

def _sf_chat(messages, max_tokens=4000, thinking=False):
    # DeepSeek-V4 默认开"思考模式"，思维链会吃掉大量耗时与 token 预算；
    # 标签提取 / 翻译这类结构化任务不需要推理过程，显式关闭（实测可显著提速）。
    payload = {"model": SF_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
    if not thinking:
        payload["thinking"] = {"type": "disabled"}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(SF_URL, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + SF_KEY,
        "User-Agent": UA,
        "Accept": "*/*",
    })
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_SSL_CTX), urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))

def _sf_translate_one(title):
    """单条：翻译标题 + 一句英文摘要。失败返回 None。"""
    try:
        prompt = ("你是新闻编辑。请把下面的中文新闻标题翻译成地道英文，并写一句客观的英文背景摘要（说明大致内容，不编造具体数字）。\n"
                  "严格按 JSON 返回：{\"en\":\"英文标题\",\"brief\":\"一句英文摘要\"}\n标题：" + title)
        resp = _sf_chat([{"role": "user", "content": prompt}], 200)
        content = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            # 供应商没按 JSON 返回 → 会让用户看到空标题，必须留痕
            note_error("translate.zh2en", msg="供应商未按 JSON 返回", severity="error", title=title,
                       raw=_redact(content)[:200])
            return None
        obj = json.loads(m.group(0))
        en = (obj.get("en") or "").strip()
        brief = (obj.get("brief") or "").strip()
        if not en and not brief:
            note_error("translate.zh2en", msg="解析结果为空", severity="error", title=title)
            return None
        return (en, brief)
    except Exception as e:
        note_error("translate.zh2en", e, severity="error", title=title)
        return None

def enrich_zh_titles(titles):
    """并发翻译中文标题（带磁盘缓存）。返回 {中文标题: (en_title, brief)}。"""
    if not titles:
        return {}
    cache = _load_tr_cache()
    todo = [t for t in titles if t not in cache]
    if todo:
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
            for title, res in zip(todo, ex.map(_sf_translate_one, todo)):
                if res:
                    results[title] = res
        cache.update(results)
        _save_tr_cache(cache)
    return {t: cache[t] for t in titles if t in cache}


# ============ 今日头条原文获取（第二层 A）============
# 实测：热榜 50 条里 /article/<id> 仅约 2%（直达文章），/trending/<id> 约 98%（话题聚合）。
#   /article/<id>  → m.toutiao.com/i<id>/info/ 直接返回 JSON 正文（纯 HTTP 可用）
#   /trending/<id> → PC 页与移动页都是 JS 壳 / 404，必须渲染后才能拿到文章 id
_TT_ART_RE = re.compile(r"/article/(\d{6,})")
_TT_TREND_RE = re.compile(r"/trending/(\d{6,})")


def toutiao_article_text(art_id):
    """/article/<id> → 移动端 JSON 接口取真实正文。返回 {text, source, title}"""
    try:
        data = fetch("https://m.toutiao.com/i%s/info/" % art_id, timeout=12)
        d = (json.loads(data.decode("utf-8", "ignore")) or {}).get("data") or {}
        text = clean_html(d.get("content") or "")
    except Exception as e:
        note_error("toutiao.article", e, severity="warn", art_id=str(art_id),
                   msg="头条文章正文获取失败")
        return {"text": "", "source": "", "title": ""}
    return {"text": text, "source": (d.get("source") or "").strip(),
            "title": (d.get("title") or "").strip()}


_CHROME_OK = None   # None=尚未探测；True/False=探测结果（只探一次，避免每条目都白等 10 秒）


def _chrome_available():
    """探测本机 Chrome headless 是否可用，结果缓存。
    在受限沙箱内 Chrome 会以 Abort trap 6 退出，此时必须快速判定不可用并整体回退，
    否则 15 条热搜 × 10 秒 = 2 分多钟，用户会以为卡死。"""
    global _CHROME_OK
    if _CHROME_OK is not None:
        return _CHROME_OK
    import subprocess
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome):
        _CHROME_OK = False
    else:
        try:
            p = subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox",
                                "--user-data-dir=/tmp/wb-chrome-probe", "--dump-dom",
                                "data:text/html,<h1>wb-ok</h1>"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40)
            _CHROME_OK = b"wb-ok" in (p.stdout or b"")
        except Exception as e:
            _CHROME_OK = False
            note_error("render.chrome.probe", e, severity="warn", msg="无头浏览器探测失败，将整体回退")
    if not _CHROME_OK:
        note_error("render.chrome", None, severity="warn",
                   msg="无头浏览器不可用：头条话题页无法渲染取原文，已回退中文源或如实标记")
    return _CHROME_OK


def _detect_node_bin():
    """探测 node 可执行文件，避免写死版本目录。

    踩过的坑：原先写死 .../node/versions/22.22.2/bin/node，实际目录已变成 22.22.2-2，
    于是 render_dom_via_cdp() 开头的 os.path.exists(_NODE_BIN) 恒为 False，
    CDP 兜底整条路径静默失效；而 subprocess 直接拉 Chrome 在本机又 Abort trap: 6，
    两条渲染路径同时死掉 —— 直接后果是今日头条热搜 1290 条里 1140 条 no_source（88%），
    前端只能拿到一行标题，事实抽取抽不出卡。这里改为动态探测，版本再变也不会失效。"""
    import glob
    try:
        cands = sorted(glob.glob("/Users/bryan/.workbuddy/binaries/node/versions/*/bin/node"), reverse=True)
        for c in cands:
            if os.path.exists(c):
                return c
    except Exception:
        pass
    return "node"          # 最后退回 PATH 里的 node


_NODE_BIN = _detect_node_bin()
_NODE_MODULES = "/Users/bryan/.workbuddy/binaries/node/workspace/node_modules"


def render_dom_via_cdp(url, timeout=60):
    """通过用户已开启的调试 Chrome（CDP 9222）渲染页面，返回 DOM。

    存在理由：某些受限执行环境里，subprocess 直接拉起 Chrome 会以
    `Abort trap: 6`（exit 134）崩溃，导致无头渲染完全不可用。
    此时若用户开着 `--remote-debugging-port=9222` 的 Chrome，就直接复用它。
    仅用于本地 demo；正常部署环境下 subprocess 路径可用，不会走到这里。"""
    js = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cdp_render.js")
    if not (os.path.exists(_NODE_BIN) and os.path.exists(js)):
        return None
    try:
        probe = urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3)
        probe.close()
    except Exception:
        return None                      # 调试浏览器没开，静默跳过
    import subprocess
    env = dict(os.environ)
    env["NODE_PATH"] = _NODE_MODULES
    last_err = ""
    # 实测 CDP 渲染会间歇性失败（连续调用时偶发返回空），重试一次能救回大部分
    for attempt in range(2):
        try:
            p = subprocess.run([_NODE_BIN, js, url, str(int(timeout * 1000))],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=timeout + 15, env=env)
            html = (p.stdout or b"").decode("utf-8", "ignore")
            if html:
                return html
            last_err = ((p.stderr or b"").decode("utf-8", "ignore")[:120]) or "空输出"
        except Exception as e:
            last_err = repr(e)[:120]
        if attempt == 0:
            time.sleep(1.5)
    note_error("render.cdp", None, severity="warn", url=url,
               msg="CDP 渲染失败（已重试 1 次）：%s" % last_err)
    return None


def render_dom_with_chrome(url, timeout=45):
    """渲染页面并返回 DOM。返回 None 表示所有渲染路径都不可用。

    两条路径：① subprocess 拉起本机 Chrome（正常环境）；
    ② 复用用户已开启的调试 Chrome（受限沙箱内的兜底）。"""
    import subprocess, tempfile, shutil
    tmp = None
    if _chrome_available():
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        tmp = tempfile.mkdtemp(prefix="wb-hl-")
        try:
            p = subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox",
                                "--user-data-dir=" + tmp, "--virtual-time-budget=10000",
                                "--dump-dom", url],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            html = (p.stdout or b"").decode("utf-8", "ignore")
            if html:
                return html
        except Exception as e:
            note_error("render.chrome", e, severity="warn", url=url, msg="无头渲染失败，尝试调试浏览器兜底")
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
    # subprocess 路径不可用或返回空 → 复用用户开着的调试 Chrome
    html = render_dom_via_cdp(url, timeout=max(30, timeout))
    if html:
        return html
    note_error("render.chrome", None, severity="warn", url=url,
               msg="渲染不可用（Chrome 无法启动且无调试浏览器），头条话题页无法取原文")
    return None


_ARTICLE_TAG_RE = re.compile(r"<article\b[^>]*>([\s\S]*?)</article>", re.I)
_SCRIPT_RE = re.compile(r"<script[\s\S]*?</script>", re.I)
_STYLE_RE = re.compile(r"<style[\s\S]*?</style>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _dom_to_text(chunk):
    """把一段渲染后的 HTML 转成干净正文文本"""
    if not chunk:
        return ""
    t = _SCRIPT_RE.sub(" ", chunk)
    t = _STYLE_RE.sub(" ", t)
    t = clean_html(t)                        # 去标签 + 反转义 + 压缩空白
    t = re.sub(r"https?://\S+", " ", t)      # 去掉正文里夹的外链
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


def extract_article_from_dom(html):
    """从渲染后的文章页 DOM 里提取正文。

    实测（2026-09-03，CDP 渲染头条文章页）：
      - <article> 元素里就是完整正文，509 / 1102 / 2744 字符，远好于移动 JSON 接口的 176 字符
      - 移动 JSON(m.toutiao.com/i<id>/info/) 只返回摘要，多数不足 200 字符，无法用于生成
    <article> 缺失或过短时返回空串，由上层决定是否回退。"""
    if not html:
        return ""
    m = _ARTICLE_TAG_RE.search(html)
    if not m:
        return ""
    return _dom_to_text(m.group(1))


def render_article_text(article_id, timeout=40):
    """渲染头条文章页并取正文。返回 (text, source_name)。"""
    url = "https://www.toutiao.com/article/%s/" % article_id
    dom = render_dom_with_chrome(url, timeout=timeout)
    if not dom:
        return "", ""
    text = extract_article_from_dom(dom)
    return text, ""


# ============ 中文源兜底（第二层 B）============
# 实测可用：人民网三个频道各 100 条，文章页可抽到 1k–5k 字符；新华网可用但偏短
CN_FEEDS = [
    ("人民网 · 文化", "http://www.people.com.cn/rss/culture.xml", ["culture"]),
    ("人民网 · 时政", "http://www.people.com.cn/rss/politics.xml", ["world"]),
    ("人民网 · 国际", "http://www.people.com.cn/rss/world.xml", ["world"]),
    ("新华网 · 时政", "http://www.xinhuanet.com/politics/news_politics.xml", ["world"]),
]


def _cn_bigrams(s):
    s = re.sub(r"[^\u4e00-\u9fa5]", "", s or "")
    return set(s[i:i + 2] for i in range(max(0, len(s) - 1)))


def cn_fallback_article(title, min_score=3):
    """按热点标题在中文 RSS 里找最相关的原文。返回 {text, source, url, score}。
    ⚠️ min_score 默认 3（有意义重合）是刻意的：实测人民网/新华网 RSS 偏 editorial
    （文博会、地质公园一类），与热搜的突发新闻几乎无重合，最高只到 1 分。
    若放宽到 1–2 分，就会把一篇无关报道当作该热点的「原文」——那是伪造溯源，
    比「没有原文」更糟。宁可诚实标记无原文，也不给错的出处。"""
    want = _cn_bigrams(title)
    if not want:
        return {"text": "", "source": "", "url": "", "score": 0}
    cands = []

    def grab(su):
        s, u, _t = su
        try:
            return s, u, parse_feed(fetch(u, timeout=12), s)
        except Exception as e:
            note_error("cn_fallback.feed", e, severity="warn", url=u, source=s)
            return s, u, []

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for s, u, items in ex.map(grab, CN_FEEDS):
            for it in items[:25]:
                sc = len(want & _cn_bigrams(it.get("topic", "")))
                if sc >= min_score:
                    cands.append((sc, s, it))
    cands.sort(key=lambda x: -x[0])
    if not cands:
        return {"text": "", "source": "", "url": "", "score": 0}
    best = None
    for sc, s, it in cands[:3]:
        r = fetch_article(it.get("url", ""), timeout=15)
        if r["status"] in ("ok", "short") and r["len"] > 300:
            best = {"text": r["text"], "source": s, "url": it.get("url", ""), "score": sc}
            break
    return best or {"text": "", "source": "", "url": "", "score": 0}


def fetch_toutiao(limit=15, want_fulltext=True):
    """今日头条热榜：真实中文全网热搜。
    ⚠️ 不再用 LLM 摘要冒充原文 —— 那会让「事实抽取」建立在幻觉之上。
    原文链路：/article/<id> → 移动 JSON；/trending/<id> → 无头渲染取文章 → JSON；
    均失败 → 中文 RSS 兜底(B)；再失败 → 如实标记 no_source(C)，绝不伪造。"""
    try:
        data = fetch("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc", timeout=12)
        arr = (json.loads(data.decode("utf-8", "ignore")) or {}).get("data") or []
    except Exception as e:
        # 抓不到 ≠ 没有热点。必须记录，否则界面显示"暂无热点"会让用户误以为今天真没内容
        note_error("fetch.toutiao", e, severity="error",
                   url="https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc")
        return []
    arr = arr[:limit]
    titles = [(it.get("Title") or "").strip() for it in arr]
    titles = [t for t in titles if t]
    # 仅用于「标题英译」——翻译真实标题是合法的，编造正文不是
    enriched = enrich_zh_titles(titles)
    out = []
    for i, it in enumerate(arr):
        title = (it.get("Title") or "").strip()
        if not title:
            continue
        hv = it.get("HotValue")
        try:
            hot_num = int(hv) if hv else 0
        except Exception:
            hot_num = 0
        en_title = (enriched.get(title, ("", "")) or ("", ""))[0]
        row = {"topic": en_title or title, "cn": title, "source": "今日头条热搜",
               "url": it.get("Url") or "", "summary": "", "fulltext": "",
               "fulltext_status": "no_source", "fulltext_len": 0, "fulltext_err": "",
               "date": time.strftime("%Y-%m-%d"), "ts": time.time(),
               "hot": hot_num, "heat": max(50, 98 - i), "srcs": 1, "lang": "zh"}
        if want_fulltext:
            _fill_toutiao_fulltext(row, title, allow_render=(i < TOUTIAO_RENDER_LIMIT))
            _health_record("今日头条热搜", row.get("fulltext_status") or "failed", 0)
        out.append(row)
    return out


# 话题页渲染较慢（CDP 路径实测约 7 秒/条），限制每批最多渲染几条，避免整榜卡死。
# 实测（2026-09-03）：设为 5 时只覆盖前 5 条头条，后面的都落 no_source；
# 头条在整榜里通常占 5–12 条，且渲染成功率很高（5/5 全中），故放宽到 12 覆盖全部头条。
TOUTIAO_RENDER_LIMIT = 12


def _fill_toutiao_fulltext(row, title, allow_render=True):
    """给单条头条热点补原文：A1(直达文章JSON) → A2(渲染话题页取文章) → B(中文RSS) → C(如实标记)"""
    url = row.get("url") or ""
    m = _TT_ART_RE.search(url)
    if m:
        r = toutiao_article_text(m.group(1))
        if len(r["text"]) >= 200:
            row["fulltext"] = r["text"]
            row["fulltext_status"] = "ok" if len(r["text"]) >= MIN_ARTICLE_CHARS else "short"
            row["fulltext_len"] = len(r["text"])
            if r["source"]:
                row["source"] = "今日头条 · %s" % r["source"]
            row["url"] = "https://www.toutiao.com/article/%s" % m.group(1)
            return
    # A2：话题聚合页 → 渲染 → 提取文章 id → 逐篇取正文（受 TOUTIAO_RENDER_LIMIT 限制）
    if allow_render and _TT_TREND_RE.search(url):
        dom = render_dom_with_chrome(url)
        if dom:
            ids = []
            for aid in _TT_ART_RE.findall(dom):
                if aid not in ids:
                    ids.append(aid)
            for aid in ids[:3]:
                r = toutiao_article_text(aid)
                text = r["text"]
                src = r["source"]
                # 移动 JSON 往往只给摘要（实测 176-183 字符，且 /w/ 格式直接返回 0）。
                # 不足 200 时改为渲染文章页取 <article> 正文 —— 实测可达 509 / 1102 / 2744 字符。
                if len(text) < 200:
                    rendered, _ = render_article_text(aid)
                    if len(rendered) > len(text):
                        text = rendered
                if len(text) >= 200:
                    row["fulltext"] = text
                    row["fulltext_status"] = "ok" if len(text) >= MIN_ARTICLE_CHARS else "short"
                    row["fulltext_len"] = len(text)
                    if src:
                        row["source"] = "今日头条 · %s" % src
                    row["url"] = "https://www.toutiao.com/article/%s" % aid
                    return
    # B：中文 RSS 兜底
    fb = cn_fallback_article(title)
    if fb.get("text"):
        row["fulltext"] = fb["text"]
        row["fulltext_status"] = "ok" if len(fb["text"]) >= MIN_ARTICLE_CHARS else "short"
        row["fulltext_len"] = len(fb["text"])
        row["source"] = "%s（中文源兜底）" % fb["source"]
        row["url"] = fb["url"]
        row["fulltext_err"] = "头条原文不可得，已用相关中文报道替代（匹配度 %d）" % fb["score"]
        return
    # C：诚实降级
    row["fulltext"] = ""
    row["fulltext_status"] = "no_source"
    row["fulltext_len"] = 0
    row["fulltext_err"] = "未能获取原文（头条话题页需渲染，且无匹配中文源），请手动粘贴素材"


def fetch_hackernews(limit=15):
    """Hacker News：英文科技趋势（并发抓取详情）"""
    try:
        data = fetch("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10)
        ids = (json.loads(data.decode("utf-8", "ignore")) or [])[:limit]
    except Exception as e:
        note_error("fetch.hackernews", e, severity="error",
                   url="https://hacker-news.firebaseio.com/v0/topstories.json")
        return []

    def one(sid):
        try:
            it = json.loads(fetch("https://hacker-news.firebaseio.com/v0/item/%s.json" % sid, timeout=7).decode("utf-8", "ignore"))
        except Exception as e:
            # 单条详情失败只丢这一条，不中断；但整体丢多了要能看出来
            note_error("fetch.hackernews.item", e, severity="warn", sid=str(sid))
            return None
        title = (it.get("title") or "").strip()
        if not title:
            return None
        url = it.get("url") or ("https://news.ycombinator.com/item?id=%s" % sid)
        return {"topic": title, "source": "Hacker News", "url": url,
                "summary": "", "fulltext": "", "date": "", "ts": it.get("time") or time.time(),
                "hot": it.get("score") or 0, "heat": 90, "srcs": 1, "lang": "en"}

    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(one, ids):
            if r:
                out.append(r)
    out.sort(key=lambda x: -x["hot"])
    for i, it in enumerate(out):
        it["heat"] = max(50, 98 - i)
    return out


def fetch_one(source_url):
    source, url = source_url
    try:
        data = fetch(url)
        return parse_feed(data, source)
    except Exception as e:
        # 单个源失败不应中断整体抓取，但必须留痕，由接口汇总后告知用户
        note_error("fetch.feed", e, severity="error", url=url, source=source)
        return []


# 信源编辑加权：CGTN 是主力中国源，适度加权避免被西方源按纯时间排序淹没
SOURCE_BOOST = {"CGTN": 10}


def fetch_trends(theme="all", sub=None, limit=30):
    """合并真实热点：今日头条热搜(中文全网) + Hacker News(英文科技) + RSS(英文最新)。
    不做「讲好中国故事」内容过滤；主题仅用于分类标签与可选筛选。"""
    now = time.time()
    items = []

    def tag(it):
        # 新体系只有大类 + 内容标签两层；热点只归大类，子主题留给第 04 步的 LLM 判定
        text = (it.get("cn") or "") + " " + (it.get("topic") or "") + " " + (it.get("summary") or "")
        it["theme"] = classify_theme(text)
        it["sub"] = ""
        return it

    # 1) 中文全网热搜
    for it in fetch_toutiao():
        items.append(tag(it))
    # 2) 英文最新新闻（RSS，按类别取源，避免政治源污染分类）
    #    ⚠️ 已移除 Hacker News：该源只返回标题、无正文/摘要，无法支撑后续生成链路与标签提取
    def fetch_assigned(src_url_themes):
        """抓取并给已知信源的条目直接打上其声明的类别，不做全局关键词分类——
        全局分类会误伤（实测 Variety/ESPN 的娱乐条目被归到 world/science）。"""
        s, u, themes = src_url_themes
        got = fetch_one((s, u))
        for it in got:
            if themes:
                if len(themes) == 1:
                    it["theme"] = themes[0]
                else:
                    it["theme"] = classify_among(
                        (it.get("topic") or "") + " " + (it.get("summary") or ""), themes)
            it["sub"] = ""
        return got

    rss_targets = [(s, u, themes) for (s, u, themes) in FEEDS if (theme == "all" or theme in themes)]
    # 中文源：作为「自带真原文的中文素材」独立来源。
    # 注意不是拿它给热搜条顶替原文 —— 实测 editorial 内容与突发热搜几乎无重合，
    # 硬凑会变成伪造溯源。这里只把它自己的条目（含可抓取正文）放进候选池。
    cn_targets = [(s, u, themes) for (s, u, themes) in CN_FEEDS if (theme == "all" or theme in themes)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        for got in ex.map(fetch_assigned, rss_targets):
            items.extend(got)
        for got in ex.map(fetch_assigned, cn_targets):
            for it in got:
                it["lang"] = "zh"
                it["cn"] = it.get("topic", "")
            items.extend(got)
    # 每个信源最多保留 PER_SOURCE_LIMIT 条，保证源多样性（国际源不被单一源挤掉）
    PER_SOURCE_LIMIT = 4
    by_src = {}
    for it in items:
        src = it.get("source", "?")
        if len(by_src.setdefault(src, [])) < PER_SOURCE_LIMIT:
            by_src[src].append(it)
    items = [x for v in by_src.values() for x in v]
    # 统一补 heat / theme / sub / srcs
    for it in items:
        if "heat" not in it:
            recency = max(0.0, 1.0 - (now - it.get("ts", 0)) / (7 * 86400)) if it.get("ts") else 0.5
            it["heat"] = int(min(98, 50 + recency * 40))
        # 信源编辑加权：CGTN 是「讲好中国故事」的主力中国源，适度加权，
        # 避免被同刻度的西方娱乐/新闻（Billboard/Variety/NPR）按纯时间排序淹没。
        for prefix, boost in SOURCE_BOOST.items():
            if (it.get("source") or "").startswith(prefix):
                it["heat"] = min(98, it.get("heat", 0) + boost)
        if not it.get("theme"):
            it["theme"] = classify_theme(it.get("topic", "") + " " + it.get("summary", ""))
        if not it.get("sub"):
            _, ms, _ = match_entry(it.get("topic", "") + " " + it.get("summary", ""), it["theme"], None)
            it["sub"] = ms
        it.setdefault("srcs", 1)
        it.setdefault("lang", "en")
    # 时间过滤：超过 14 天的内容丢弃（RSS 历史条目会污染今日榜）
    _14d = 14 * 86400
    items = [it for it in items if (not it.get("ts")) or (now - it["ts"] <= _14d)]
    # 主题筛选（指定且非 all 时）
    if theme and theme != "all":
        items = [it for it in items if it["theme"] == theme]
        if sub:
            items = [it for it in items if it["sub"] == sub]
    # 去重 + 排序
    seen, ranked = set(), []
    for it in items:
        u = it.get("url") or it.get("topic")
        if u in seen:
            continue
        seen.add(u)
        ranked.append(it)
    ranked.sort(key=lambda x: (-x.get("heat", 0), -x.get("ts", 0)))
    ranked = ranked[:limit]
    # 第一层：为英文/中文 RSS 条目补齐原文（头条条目已在 fetch_toutiao 里按 A→B→C 处理过）
    try:
        enrich_fulltext(ranked, workers=8)
    except Exception as e:
        note_error("trends.enrich_fulltext", e, severity="error",
                   msg="原文补齐失败，条目将只带摘要（不影响主流程）")
    # 为英文热点补中文翻译，实现"所有热点统一英文 + 中文"双语格式
    try:
        en_titles = [it.get("topic", "") for it in ranked if it.get("lang") != "zh" and it.get("topic")]
        zh_map = translate_en_titles(en_titles)
        for it in ranked:
            if it.get("lang") != "zh" and not it.get("cn"):
                it["cn"] = zh_map.get(it.get("topic", ""), "") or ""
    except Exception as e:
        # 翻译失败 → 英文热点的中文标题留空，界面上用户能直接看到，必须记录
        note_error("trends.translation", e, severity="error",
                   msg="英文热点补中文翻译失败，界面将显示空中文标题")
    return ranked


def host_of(u):
    return urllib.parse.urlparse(u).netloc or u


def discover_rss(html_bytes, base_url):
    """从普通网页 HTML 中自动发现 RSS/Atom feed 链接。失败返回 None（调用方会降级），但需留痕"""
    try:
        text = html_bytes.decode("utf-8", "ignore")
    except Exception as e:
        note_error("discover_rss.decode", e, severity="warn", url=base_url)
        return None
    for m in re.finditer(r'<link[^>]+>', text, re.I):
        tag = m.group(0)
        rel = re.search(r'rel=["\']?([^"\'\s>]+)', tag, re.I)
        href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if not rel or not href:
            continue
        if "alternate" in rel.group(1) and ("rss" in tag.lower() or "atom" in tag.lower() or "feed" in tag.lower()):
            url = href.group(1)
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                url = urllib.parse.urljoin(base_url, url)
            return url
    return None


def fetch_scan(urls):
    """逐源扫描。单个源失败只跳过该源（不应中断整体），但每一个失败都必须留痕，
    否则界面显示"没抓到内容"时，用户无法区分是源真的没内容还是网络/解析失败。"""
    items = []
    for u in urls:
        u = u.strip()
        if not u:
            continue
        if not u.startswith("http://") and not u.startswith("https://"):
            u = "https://" + u
        # 尝试当作 RSS/Atom 抓取；失败则从网页自动发现 RSS；再失败则抓网页标题
        try:
            data = fetch(u)
            got = parse_feed(data, host_of(u))
            if not got:
                rss_url = discover_rss(data, u)
                if rss_url:
                    try:
                        data2 = fetch(rss_url)
                        got = parse_feed(data2, host_of(rss_url))
                    except Exception as e:
                        note_error("scan.discovered_feed", e, severity="error", url=rss_url, origin=u)
                        got = []
            if not got:  # 兜底：网页标题（降级，需记录：结果质量低于 RSS）
                text = clean_html(data.decode("utf-8", "ignore"))
                m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I)
                title = clean_html(m.group(1)) if m else u
                note_error("scan.degraded_to_title", severity="warn", url=u,
                           msg="未能解析为 RSS/Atom，已降级为网页标题（内容较单薄）")
                got = [{"topic": title, "source": "自定义信源", "url": u, "summary": "", "date": "", "ts": time.time(),
                        "_degraded": True}]
            for g in got:
                g["heat"] = 60
                g["srcs"] = 1
                items.append(g)
        except Exception as e:
            # 这里原来是裸 continue：源不可达时返回空列表，界面表现为"没有内容"。
            # 现在记录原因，由 /api/scan 汇总回传，用户能看到"哪个源失败、为什么"。
            note_error("scan.source", e, severity="error", url=u)
            continue
    return items



# ============ TTS：文章音频（英音 / 美音）============
# demo 阶段用硅基流动 CosyVoice2；工程化可替换为微软 Azure TTS 等
import hashlib
import urllib.parse as _up

AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

TTS_MODEL = "FunAudioLLM/CosyVoice2-0.5B"
TTS_URL = "https://api.siliconflow.cn/v1/audio/speech"
TTS_VOICE = "FunAudioLLM/CosyVoice2-0.5B:alex"
TTS_TIMEOUT = 90

# 口音 → instruct 指令（美音为默认，不加指令）
ACCENT_INSTRUCT = {
    "us": "",
    "uk": "Speak with a British accent",
}

def _strip_for_tts(text):
    """剥离标题行与生词表，只朗读正文"""
    if not text:
        return ""
    lines = [l.strip() for l in str(text).split("\n") if l.strip()]
    body, in_gloss = [], False
    for l in lines:
        if re.match(r"^#+\s*", l):
            continue
        if re.match(r"^Words\s*(and|&|\+)\s*Expressions", l, re.I) or re.match(r"^(Glossary|Vocabulary)\s*[:：]?", l, re.I):
            in_gloss = True
            continue
        if in_gloss:
            continue
        body.append(l)
    return " ".join(body)

def _tts_path(level, accent, text):
    h = hashlib.md5((str(level) + "|" + str(accent) + "|" + text).encode("utf-8")).hexdigest()[:16]
    return os.path.join(AUDIO_DIR, "%s_%s_%s.mp3" % (level, accent, h))

def gen_tts_one(text, level, accent):
    """生成单个音频，返回 (相对URL, 状态, 错误)。状态：cached / generated / failed / skipped"""
    clean = _strip_for_tts(text)
    if not clean:
        return None, "skipped", "正文为空（标题与生词表被剥离后无内容）"
    fp = _tts_path(level, accent, clean)
    rel = "/audio/" + os.path.basename(fp)
    if os.path.exists(fp) and os.path.getsize(fp) > 1024:
        return rel, "cached", None      # 缓存命中，未产生费用
    payload = {
        "model": TTS_MODEL,
        "input": clean,
        "voice": TTS_VOICE,
        "response_format": "mp3",
    }
    ins = ACCENT_INSTRUCT.get(accent, "")
    if ins:
        payload["instruct"] = ins
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(TTS_URL, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + SF_KEY,
            "Accept": "*/*",
        })
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_SSL_CTX), urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=TTS_TIMEOUT) as r:
            data = r.read()
        if not data or len(data) < 1024:
            return None, "failed", "供应商返回内容为空或过小（%d 字节）" % len(data or b"")
        with open(fp, "wb") as f:
            f.write(data)
        return rel, "generated", None
    except Exception as e:
        # 明确区分超时与网络不可达，便于前端给出可执行的提示
        if isinstance(e, socket.timeout):
            return None, "failed", "请求供应商超时（>%ss）" % TTS_TIMEOUT
        if isinstance(e, urllib.error.HTTPError):
            return None, "failed", "供应商返回 HTTP %s：%s" % (getattr(e, "code", "?"), _redact(getattr(e, "reason", "")))
        return None, "failed", _redact(e)

def _sf_translate_en2zh_one(title):
    """单条：英文标题 → 中文翻译。失败返回 None。"""
    try:
        prompt = ("你是新闻编辑。请把下面的英文新闻标题翻译成简洁准确的中文标题。\n"
                  "严格按 JSON 返回：{\"zh\":\"中文标题\"}\n标题：" + str(title))
        resp = _sf_chat([{"role": "user", "content": prompt}], 150)
        content = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            note_error("translate.en2zh", msg="供应商未按 JSON 返回", severity="error", title=title,
                       raw=_redact(content)[:200])
            return None
        obj = json.loads(m.group(0))
        zh = (obj.get("zh") or "").strip()
        if not zh:
            note_error("translate.en2zh", msg="解析结果为空", severity="error", title=title)
            return None
        return zh
    except Exception as e:
        note_error("translate.en2zh", e, severity="error", title=title)
        return None


def translate_en_titles(titles):
    """批量：英文标题 → 中文。带磁盘缓存。返回 {英文标题: 中文标题}"""
    if not titles:
        return {}
    cache = _load_tr_cache()
    prefix = "en2zh::"
    todo = [t for t in titles if (prefix + t) not in cache]
    if todo:
        results = {}
        failed = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
            for t, zh in zip(todo, ex.map(_sf_translate_en2zh_one, todo)):
                if zh:
                    results[prefix + t] = zh
                else:
                    failed.append(t)
        if failed:
            # 翻译失败的数量必须可见：界面上会表现为这些热点缺中文标题
            note_error("translate.en2zh.batch", severity="error",
                       msg="%d/%d 条英文标题翻译失败，界面将缺中文标题" % (len(failed), len(todo)),
                       failed=("; ".join(failed[:5]) + (" …" if len(failed) > 5 else "")))
        cache.update(results)
        _save_tr_cache(cache)
    return {t: cache.get(prefix + t) for t in titles if cache.get(prefix + t)}

def gen_tts_batch(articles, accents=("us", "uk")):
    """批量生成：articles={A2:B1:B2} × accents，并发。
    返回 (audio, meta)。meta 记录本次真实执行情况，供前端展示与追溯——
    「谁在什么时间用什么模型合成了几条、命中了几条缓存、失败原因是什么」全部由后端如实上报，
    前端不再自行推断。"""
    t0 = time.time()
    jobs, out = [], {}
    levels = []
    for lv in ("A2", "B1", "B2"):
        txt = (articles or {}).get(lv) or ""
        if not txt:
            continue
        levels.append(lv)
        out[lv] = {}
        for ac in accents:
            jobs.append((lv, ac, txt))
    meta = {
        "model": TTS_MODEL,
        "voice": TTS_VOICE,
        "provider": "siliconflow",
        "accents": list(accents),
        "levels": levels,
        "requested": len(jobs),
        "cached": 0, "generated": 0, "failed": 0, "skipped": 0,
        "succeeded": 0,
        "errors": [],
        "elapsed_ms": 0,
        "generated_at": int(time.time() * 1000),
    }
    if not jobs:
        meta["elapsed_ms"] = int((time.time() - t0) * 1000)
        return out, meta

    def work(job):
        lv, ac, txt = job
        return (lv, ac) + gen_tts_one(txt, lv, ac)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        for lv, ac, url, status, err in ex.map(work, jobs):
            if status in meta:
                meta[status] += 1
            if url:
                out[lv][ac] = url
                meta["succeeded"] += 1
            if err:
                meta["errors"].append({"level": lv, "accent": ac, "error": _redact(err)})
    meta["elapsed_ms"] = int((time.time() - t0) * 1000)
    return out, meta


# ===== 内容库：生产平台文章暂存（供同步飞书多维表格）=====
LIBRARY_FILE = os.path.join(_CACHE_DIR, "library.json")
_LIB_LOCK = threading.Lock()


_LIB_LOAD_ERROR = None

def _load_library():
    """读取内容库。必须区分两种情况，否则前端会把「读取失败」误当成「内容库是空的」：
         - 文件不存在  → 确实为空，返回 []，无错误
         - 文件存在但读取/解析失败 → 返回 []，同时记录错误供接口回传"""
    global _LIB_LOAD_ERROR
    _LIB_LOAD_ERROR = None
    if not os.path.exists(LIBRARY_FILE):
        return []
    try:
        with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, list) else []
    except Exception as e:
        note_error("library.load", e, severity="error", file=LIBRARY_FILE,
                   msg="内容库文件读取/解析失败，不可当作空库处理")
        _LIB_LOAD_ERROR = _redact(e)
        return []

def library_last_error():
    """最近一次读取内容库的错误（None 表示读取正常）"""
    return _LIB_LOAD_ERROR


def _save_library(rows):
    tmp = LIBRARY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    os.replace(tmp, LIBRARY_FILE)


def library_upsert(art):
    """按 id 去重写入，返回 (stored_id, total_count, error)。

    ⚠️ 读取失败时必须拒绝写入：损坏的文件会被读成空列表，
       若照常写回就会把内容库整个抹掉。宁可报错也不能静默丢数据。"""
    if not isinstance(art, dict) or not art.get("id"):
        return None, 0, "invalid article (missing id)"
    with _LIB_LOCK:
        rows = _load_library()
        if _LIB_LOAD_ERROR:
            return None, 0, "内容库读取失败，已拒绝写入以免覆盖：%s" % _LIB_LOAD_ERROR
        idx = next((i for i, r in enumerate(rows) if r.get("id") == art["id"]), -1)
        if idx >= 0:
            rows[idx] = art
        else:
            rows.insert(0, art)
        try:
            _save_library(rows)
        except Exception as e:
            note_error("library.save", e, severity="error", file=LIBRARY_FILE)
            return None, 0, "内容库写入失败：%s" % _redact(e)
        return art["id"], len(rows), None


def library_list():
    with _LIB_LOCK:
        return _load_library()


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send({})

    def _read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8", "ignore"))
        except Exception as e:
            # 请求体解析失败会被当成空对象继续处理，容易被误判为"参数没传"；留下记录便于排查
            note_error("request.body", e, severity="warn", path=getattr(self, "path", ""))
            return {}

    def _serve_audio(self, relpath):
        """静态音频文件服务"""
        fp = os.path.join(AUDIO_DIR, os.path.basename(relpath))
        if not os.path.exists(fp):
            return self._send({"ok": False, "error": "audio not found"}, 404)
        try:
            with open(fp, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            return self._send({"ok": False, "error": "read failed"}, 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        if path == "/api/tts":
            # 单条：{ text, level, accent }
            text = body.get("text") or ""
            level = body.get("level") or "B1"
            accent = body.get("accent") or "us"
            url, status, err = gen_tts_one(text, level, accent)
            if not url:
                # 失败必须带上原因，前端才能给出可执行的提示，而不是让用户猜
                return self._send({"ok": False, "error": _redact(err) or "tts failed",
                                   "status": status}, 502)
            return self._send({"ok": True, "url": url, "level": level, "accent": accent,
                               "status": status, "model": TTS_MODEL, "provider": "siliconflow"})
        if path == "/api/tts/batch":
            # 批量：{ articles:{A2,B1,B2}, accents:["us","uk"] }
            articles = body.get("articles") or {}
            accents = tuple(body.get("accents") or ["us", "uk"])
            audio, meta = gen_tts_batch(articles, accents)
            return self._send({"ok": True, "audio": audio, "meta": meta})
        if path == "/api/tags/extract":
            # 三层标签提取：{ material, title }
            material = body.get("material") or body.get("text") or ""
            title = body.get("title") or ""
            if not material:
                return self._send({"ok": False, "error": "missing material"}, 400)
            r, err = extract_tags(material, title)
            if err:
                return self._send({"ok": False, "error": err, "degraded": True}, 502)
            return self._send({"ok": True, **r})
        if path == "/api/library":
            # 生产平台入库：body = 文章对象（buildBankArticle 输出）
            stored_id, total, err = library_upsert(body)
            if not stored_id:
                # 写入失败必须明确回错误码与原因，前端才能标出「后端未同步」
                return self._send({"ok": False, "error": err or "invalid article (missing id)"}, 400)
            return self._send({"ok": True, "id": stored_id, "library_count": total})
        return self._send({"ok": False, "error": "not found"}, 404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        q = dict(urllib.parse.parse_qsl(parsed.query))
        if path.startswith("/audio/"):
            return self._serve_audio(path[len("/audio/"):])
        if path == "/api/tags/taxonomy":
            # 标签词表单一真源：前端从这里拉，不再内置副本
            return self._send({"ok": True, **taxonomy_payload()})
        if path == "/api/health":
            return self._send({"ok": True, "name": "agent-reach-bridge", "time": int(time.time()),
                               "port": PORT, "recent_errors": len(ERROR_LOG)})
        if path == "/api/trends":
            theme = q.get("theme", "all")
            sub = q.get("sub") or None
            t0 = int(time.time() * 1000)
            items = fetch_trends(theme, sub)
            errs = drain_errors(t0)
            # degraded=True 表示「结果不完整」：用户必须知道这不是"没有热点"，而是"有源失败"
            return self._send({"ok": True, "theme": theme, "sub": sub, "items": items,
                               "errors": errs, "degraded": bool(errs)})
        if path == "/api/scan":
            urls = [u for u in (q.get("urls") or "").split(",")]
            t0 = int(time.time() * 1000)
            items = fetch_scan(urls)
            errs = drain_errors(t0)
            return self._send({"ok": True, "items": items, "requested_sources": len([u for u in urls if u.strip()]),
                               "errors": errs, "degraded": bool(errs)})
        if path == "/api/library":
            items = library_list()
            err = library_last_error()
            if err:
                # 读取失败 ≠ 内容库为空，必须让前端区分
                return self._send({"ok": False, "error": "内容库读取失败：%s" % err,
                                   "items": items, "degraded": True}, 500)
            return self._send({"ok": True, "items": items, "degraded": False})
        if path == "/api/source-health":
            # 信源健康度：正文抓取是启发式的，网站改版会静默失效，这里让它可见
            rows = source_health_payload()
            return self._send({"ok": True, "items": rows,
                               "hint": "success_rate 持续偏低说明该源正文抓不到，应降级或换源"})
        if path == "/api/errors":
            # 供诊断：近期错误列表（含 warn 级），便于排查"看起来正常但其实降级了"的情况
            sev = q.get("severity") or None
            lim = int(q.get("limit") or 50)
            out = drain_errors(0, severity=sev)
            return self._send({"ok": True, "count": len(ERROR_LOG), "items": out[-lim:]})
        return self._send({"ok": False, "error": "not found"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Agent-Reach bridge listening on http://127.0.0.1:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
