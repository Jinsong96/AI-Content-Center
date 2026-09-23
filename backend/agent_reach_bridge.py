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
import gzip
import math
import socket
# ⚠️ 必须用别名：本文件里 `html` 是**局部变量名**（`fetch_article()` 的 `html = data.decode(...)`、
# `extract_main_text(html)` / `extract_title(html)` 的形参）—— 直接 `import html` 会在这些函数里
# 被局部 str 遮蔽，`html.unescape` 直接 AttributeError。
import html as _htmllib
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 词汇分级校验（EVP 词表）：backend/evp_vocab_check.py + backend/evp_wordlist.json
try:
    from evp_vocab_check import check_vocab_batch
except ImportError:  # 模块缺失时降级，接口返回错误而非崩溃
    check_vocab_batch = None

PORT = int(os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else 8787))

# 前端单页路径：Railway 单服务部署时由 bridge 一并托管，前后端同域。
# 默认 ../frontend/index.html；可用环境变量 FRONTEND_HTML 覆盖。
FRONTEND_HTML = os.environ.get("FRONTEND_HTML") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "index.html")

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
    # 2026-09-20 修正：此前误标成 world —— 教研点「商业」永远空白。
    ("CGTN · Business", "https://www.cgtn.com/subscribe/rss/section/business.xml", ["business"]),
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
    # ===== 2026-09-20 新增：主流国际大站 + 补齐 business / growth / story 三个空类 =====
    # 🔴 为什么 BBC 这些站以前没接：2026-09-02 那次「源可用性实测」是在**本机**跑的。
    #    本机直连这些站全部超时（抓取层用 `ProxyHandler({})` 主动禁用了系统代理），
    #    于是被当成「源不可用」写进注释、从此再没加回来 —— 是**误判**。
    #    2026-09-20 改用**线上 Railway 容器**复测：全部 200，正文 3k–60k 字符。
    #    ⇒ 判据必须是线上探针；**本地不通 ≠ 线上不通**（Reuters/AP 恰好相反：本地超时、线上 403）。
    #
    # 🔴 为什么 business / growth / story 之前是空的：FEEDS 里**从来没有**任何一个源的
    #    类别标签是这三类 —— 连 `CGTN · Business` 都被误标成了 `["world"]`。
    #    所以老师点这三个大类永远是空白页，不是抓不到，是根本没去抓。
    #
    # ---- world（补权威大站）----
    ("BBC · World", "https://feeds.bbci.co.uk/news/world/rss.xml", ["world"]),
    ("BBC · Top Stories", "https://feeds.bbci.co.uk/news/rss.xml", ["world"]),
    ("Guardian · World", "https://www.theguardian.com/world/rss", ["world"]),
    ("ABC News · US", "https://abcnews.go.com/abcnews/topstories", ["world"]),
    ("ABC News · World", "https://abcnews.go.com/abcnews/internationalheadlines", ["world"]),
    # ---- science ----
    ("BBC · Science", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", ["science"]),
    ("BBC · Health", "https://feeds.bbci.co.uk/news/health/rss.xml", ["science"]),
    ("BBC · Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml", ["science"]),
    ("Smithsonian", "https://www.smithsonianmag.com/rss/latest_articles/", ["science", "culture"]),
    ("New Scientist", "https://www.newscientist.com/feed/home/", ["science"]),
    ("SciTechDaily", "https://scitechdaily.com/feed/", ["science"]),
    # ---- culture ----
    ("BBC · Arts", "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml", ["culture"]),
    ("Guardian · Culture", "https://www.theguardian.com/culture/rss", ["culture"]),
    ("Atlas Obscura", "https://www.atlasobscura.com/feeds/latest.rss", ["culture", "story"]),
    ("Smithsonian · Arts", "https://www.smithsonianmag.com/rss/arts-culture/", ["culture"]),
    # ---- business（2026-09-20 新建，此前 0 个源）----
    ("BBC · Business", "https://feeds.bbci.co.uk/news/business/rss.xml", ["business"]),
    ("CNBC · Business", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147", ["business"]),
    ("CNBC · Top News", "https://www.cnbc.com/id/100003114/device/rss/rss.html", ["business"]),
    ("Guardian · Business", "https://www.theguardian.com/uk/business/rss", ["business"]),
    ("Guardian · Money", "https://www.theguardian.com/money/rss", ["business"]),
    ("Business Insider", "https://www.businessinsider.com/rss", ["business"]),
    ("Entrepreneur", "https://www.entrepreneur.com/latest.rss", ["business"]),
    # ---- growth（2026-09-20 新建，此前 0 个源）----
    ("BBC · Education", "https://feeds.bbci.co.uk/news/education/rss.xml", ["growth"]),
    ("Guardian · Education", "https://www.theguardian.com/education/rss", ["growth"]),
    ("Psychology Today", "https://www.psychologytoday.com/us/front/feed", ["growth"]),
    ("Greater Good", "https://greatergood.berkeley.edu/rss", ["growth"]),
    ("Fast Company", "https://www.fastcompany.com/rss", ["growth"]),
    ("Mindful", "https://www.mindful.org/feed/", ["growth"]),
    ("TED Blog", "https://blog.ted.com/feed/", ["growth"]),
    # ---- story（2026-09-20 新建，此前 0 个源）----
    ("BBC · Stories", "https://feeds.bbci.co.uk/news/stories/rss.xml", ["story"]),
    ("Guardian · Life", "https://www.theguardian.com/lifeandstyle/rss", ["story"]),
    ("New Yorker", "https://www.newyorker.com/feed/news", ["story"]),
    ("Narratively", "https://narratively.com/feed/", ["story"]),
    ("Longreads", "https://longreads.com/feed/", ["story"]),
    ("Smithsonian · History", "https://www.smithsonianmag.com/rss/history/", ["story"]),
    #
    # ---- 实测不可用，不要加回来（2026-09-20 线上探针证据）----
    #   NYT 全系（World / Arts / Business）、Sky News、Forbes、Economist、HBR、WSJ Markets、Inc.
    #     → 付费墙 / 反爬，只回 summary_only（正文 94–203 字符），过不了 MIN_USABLE_TEXT=200 闸门
    #   Space.com            → 只有 sitemap、没有 feed
    #   BBC · Magazine       → feed 返回 0 条
    #   Edutopia / Verywell Mind / YouTube 原生 feed → 线上 0 条（机房 IP 风控）
    #   Reuters / AP         → Railway 容器返回 403（站点方策略，非本服务故障）
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

def fetch(url, timeout=12, headers=None):
    now = time.time()
    # 同一 URL 换 UA 抓到的内容可能完全不同（头条对爬虫返回 SSR 完整页、对浏览器返回 JS 壳），
    # 缓存键必须带上 UA，否则先抓的那版会把后一版顶掉，出现「明明改了却拿到旧结果」。
    key = url if not headers else "%s|%s" % (url, headers.get("User-Agent", ""))
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    hdr = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, headers=hdr)
    if url.startswith("https://"):
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_SSL_CTX),
            urllib.request.ProxyHandler({})
        )
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as r:
        data = r.read()
    _CACHE[key] = (now, data)
    return data


# 文本里的「不可见控制字符」：反转义之后才会现形（如 `&#8234;` → U+202A）。
# · U+00AD 软连字符：BBC 等会在长词里插，复制/朗读时会变成怪符号
# · U+200B–U+200F 零宽空格 / ZWNJ / ZWJ / LRM / RLM
# · U+202A–U+202E、U+2066–U+2069 bidi 嵌入 / 覆盖 / 隔离（阿拉伯语版页面残留）
# · U+FEFF 字节序标记
# 这些在正文里全是噪音，且**肉眼看不见** —— 只会在模型输入里悄悄占 token、干扰分词。
_CTRL_RE = re.compile("[\u00ad\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def unescape_entities(s):
    """只做「HTML 实体反转义 + 控制字符清理」，**不剥标签**。

    用于本身已是纯文本的场景（磁盘缓存自愈、二次清洗），避免去标签正则
    误伤正文里真实的 `<`（例如 `less than 5 < 10`）。

    🔴 只解一次，不循环：`&amp;lt;` 的原意是「显示字面量 `&lt;`」，
    反复解会把它错变成 `<`。
    """
    if not s:
        return s
    s = _htmllib.unescape(s)
    s = _CTRL_RE.sub("", s)
    return s.replace("\xa0", " ")          # &nbsp; 系（含 &#160;）解出的不换行空格


def clean_html(s):
    """HTML 片段 → 纯文本。

    🔴 2026-09-20 修：此前只硬编码替换 5 个**命名实体**
    （`&nbsp; &amp; &lt; &gt; &quot;`），漏掉了两类：
      · **数字实体** —— `&#x27;`(单引号) `&#8217;`(右单引号) `&#8220;/&#8221;`(弯引号)
        `&#34;` `&#8212;` `&#8234;/&#8236;`(bidi) …… 英国媒体（BBC 系）正文 HTML 主要用这种；
      · **其它命名实体** —— `&rsquo;` `&mdash;` `&ldquo;` `&aacute;` `&hellip;` ……
    于是这些字面量原样漏进正文，一路带到生成环节。线上实测 **179 条里 79 条（44%）带残留**，
    涉及 **27 个源**（不是 BBC 独有）。
    改用标准库 `html.unescape` —— 它覆盖 2000+ 命名实体 + 全部数字实体，是原来那 5 条的**超集**，
    行为向后兼容（原来那 5 个的结果完全一致）。

    ⚠️ 顺序必须是「**先剥标签、再反转义**」，不能反过来：
    倒过来正文里的 `&lt;script&gt;` 会先变成真标签，再被去标签正则连内容一起吃掉。
    """
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape_entities(s)
    return re.sub(r"\s+", " ", s).strip()


def parse_ts(date_str):
    """解析 RSS / Atom 的发布时间戳；返回 0.0 表示「拿不到可用日期」。

    🔴 2026-09-20 修：此前只走 `parsedate_to_datetime`（只认 RFC822 / RFC2822），
    而 **Atom feed 给的是 ISO 8601**（`2026-09-19T08:30:00Z`）、人民网给的是 `2025-06-05`
    —— 两者都解析失败返回 0.0。而时效过滤写的是
    `if (not ts) or (now - ts <= 14d)`，**0.0 被当作「无法判定」直接放行**：
    于是这些源的时效过滤**完全失效**，线上实测人民网 12 条 2025-05/06 的旧闻
    （该 RSS 已停更 15 个月）照进列表，排在末尾 #155–#164。
    教训：**「解析不出来」既不等同于「源没给日期」，更不等同于「放行」**。
    兼容性：`datetime.fromisoformat` 在 Py<3.11 不认 `Z` 后缀 → 先替换为 `+00:00`。
    """
    s = (date_str or "").strip()
    if not s:
        return 0.0
    try:
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:            # `2025-06-05` 这类无时区：按 UTC 解释，只影响边界 8 小时内
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
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
# 判定为「可交付」的最少字符数：低于此值的条目一律不进热点列表。
# ⚠️ 必须与前端 hasUsableText() 的 MIN_USABLE_TEXT 严格一致 —— 那是生成流程的闸门：
# 低于阈值的条目点进去只会弹「请粘贴原文」并中止。留在列表里 = 制造
# 「有卡片、但一步也走不到生成」的假供给，比列表短更伤信任。
MIN_USABLE_TEXT = 200

# /api/trends 的默认返回条数。取 120 而不是 30，是因为流程是
# 「排序 → 截断 → 补正文 → 再筛掉无正文的」，必须给足冗余：
# 老默认 30 时线上最终只剩 25 条可见（2026-09-20 实测）。
TRENDS_DEFAULT_LIMIT = 120
# 热点时效上限（天）：发布日期早于「now - 此值」的条目一律不进列表（2026-09-20 新增）。
# ⚠️ 判据是 RSS/Atom 自报的 pubDate / updated，**解析失败（ts=0）的条目不在其列** —— 见 parse_ts 注释。
TRENDS_MAX_AGE_DAYS = 14
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


def _heal_article_cache(cache):
    """就地清洗磁盘缓存里「带 HTML 实体 / 控制字符」的历史正文与标题。

    为什么必须做：磁盘缓存存的是**已抽取好的纯文本**（不是原始 HTML），而 `fetch_article()`
    命中缓存时**直接返回 `hit["text"]`，不会再走 `clean_html`** —— 所以只修 `clean_html`
    的话，**历史缓存里的乱码会一直吐出来**，看起来像「修了没用」。
    实测（2026-09-20 修复前落盘的缓存）：211 条里 84 条正文、35 条标题带实体。

    做成「首次加载时一次性自愈 + 回写」：之后不再有额外开销，也不需要手工删缓存。

    返回 True 表示有改动 —— 调用方据此决定是否回写，且**必须在锁外回写**：
    `_article_cache_lock` 是不可重入的 `threading.Lock`，锁内调 `_save_article_cache()` 会死锁。
    """
    fixed = 0
    for v in (cache or {}).values():
        if not isinstance(v, dict):
            continue
        for fld in ("text", "title"):
            old = v.get(fld)
            if not isinstance(old, str) or not old:
                continue
            new = unescape_entities(old)
            if new != old:
                v[fld] = new
                if fld == "text":
                    # len 是下游用来显示正文长度、判 fulltext_status 的，必须同步
                    v["len"] = len(new)
                fixed += 1
    return fixed > 0


def _load_article_cache():
    global _article_mem
    dirty = False
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
            dirty = _heal_article_cache(_article_mem)
        mem = _article_mem
    if dirty:
        _save_article_cache()          # ⚠️ 锁外回写，见 _heal_article_cache 注释
    return mem


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
    # <article> 往往不止一个：首个常是「相关推荐」小卡（实测 ESPN 只有 165 字符），
    # 正文在另一个里面。原先只取第一个匹配，于是抽到空壳 → fetch_article 误报「抓取失败」。
    # 改为在所有 <article> 中取最长的那个作为正文容器。
    _cands = [mm.group(1) for mm in re.finditer(r"(?is)<article\b[^>]*>(.*?)</article>", s)]
    _cands = [c for c in _cands if c.strip()]
    body = max(_cands, key=len) if _cands else s

    def _paras_of(scope):
        got = []
        for pm in re.finditer(r"(?is)<p\b[^>]*>(.*?)</p>", scope):
            t = clean_html(pm.group(1))
            if len(t) < MIN_PARA_CHARS:
                continue
            low = t.lower()
            if any(b.lower() in low for b in _BOILERPLATE):
                continue
            got.append(t)
        return got

    paras = _paras_of(body)
    if not paras and body is not s:
        # 选中的容器里没有达标段落 → 退回整页重试：别把「选错容器」误报成「没有正文」
        paras = _paras_of(s)
    if not paras:
        # 没有 <p> 结构（部分站点用 <div> 承载），退化为容器去标签文本
        t = clean_html(body) or clean_html(s)
        return (t, 1) if t else ("", 0)
    return "\n\n".join(paras), len(paras)


def extract_title(html):
    """取文章标题：og:title 优先，其次 <h1>，最后 <title>。
    不优先用 <title>：它常带站名后缀（"… | ABC News"），拿它当素材标题很脏。"""
    if not html:
        return ""
    pats = [
        r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']og:title["\']',
        r"<h1[^>]*>(.*?)</h1>",
        r"<title[^>]*>(.*?)</title>",
    ]
    for p in pats:
        m = re.search(p, html, re.I | re.S)
        if m:
            t = clean_html(m.group(1))
            if t:
                return t[:200]
    return ""


def fetch_article(url, timeout=15, use_cache=True):
    """抓取并抽取一篇文章的正文。返回 dict：
       {text, len, status, err}
       status: ok(正文达标) / short(抓到但偏短) / failed(抓不到或抽取为空)
    结果写入磁盘缓存，同一 URL 不重复抓取。"""
    out = {"text": "", "len": 0, "status": "failed", "err": "", "title": ""}
    if not url:
        out["err"] = "empty url"
        return out
    cache = _load_article_cache()
    key = hashlib.md5(url.encode("utf-8")).hexdigest()
    if use_cache:
        hit = cache.get(key)
        # 缓存自愈：title 是后加的字段，早先落盘的条目没有它 —— 若直接返回，
        # 标题会退化成 URL（实测过）。把「缺 title」当未命中，重抓一次即永久补上。
        if hit and isinstance(hit, dict) and hit.get("len") and hit.get("title") is not None:
            return {"text": hit.get("text", ""), "len": hit.get("len", 0),
                    "status": hit.get("status", "failed"), "err": hit.get("err", ""),
                    "title": hit.get("title", "")}
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
    out["title"] = extract_title(html)
    if n >= MIN_ARTICLE_CHARS:
        out["status"] = "ok"
    elif n > 0:
        out["status"] = "short"
        out["err"] = "正文仅 %d 字符（低于 %d），可能未抓完整" % (n, MIN_ARTICLE_CHARS)
    else:
        out["err"] = "未能抽取到正文"
    if out["status"] in ("ok", "short") and len(html) <= MAX_CACHE_BYTES:
        cache[key] = {"text": out["text"], "len": n, "status": out["status"],
                      "err": out["err"], "title": out["title"], "ts": int(time.time())}
        _save_article_cache()
    return out


def enrich_fulltext(items, workers=8, only_missing=True, timeout=15):
    """批量为一批热点补齐原文。就地写入 fulltext / fulltext_len / fulltext_status / fulltext_err。
    抓不到时保留原有 summary 作为兜底，绝不伪造。
    timeout：单篇抓取上限（秒）。扫描接口是同步等待的交互，需要比默认更短的上限。"""
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
        r = fetch_article(it["url"], timeout=timeout)
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
            # sitemap 只给 URL，标题先是路径片段；抓到正文后用页面真实标题覆盖
            if it.get("_topic_from_url") and (r.get("title") or "").strip():
                it["topic"] = r["title"]
                it.pop("_topic_from_url", None)
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
# ---------- 密钥来源：环境变量优先，回落到 config.local.js ----------
# Railway 等平台有环境变量面板，优先用环境变量（密钥不落盘、不随源码分发）。
# 但部分托管（如 workbuddy 单端口沙箱）没有配置环境变量的入口，此时把
# frontend/config.local.js 一起上传即可 —— 它由服务端读取，HTTP 路由是
# 白名单制（只暴露 / 与 /audio/），不会被当成静态文件下载。
# 第三级兜底是随仓库分发的 backend/keys.fallback.json，用于云端部署时
# 环境变量面板不可用的情况（详见 _load_cfg_cache 的三级说明）。
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CFG_LOCAL_PATH = os.path.join(_BASE_DIR, "frontend", "config.local.js")
_KEYS_FALLBACK_PATH = os.path.join(_BASE_DIR, "backend", "keys.fallback.json")
_CFG_LOCAL_CACHE = None


def _load_cfg_cache():
    """按优先级收集密钥：先读随仓库分发的兜底文件，再用本地 config.local.js 覆盖。

    三级来源（越靠前优先级越高）:
      1. os.environ           —— Railway / Fly.io 等有变量面板的平台（密钥不落盘）
      2. frontend/config.local.js  —— 本机 & 无变量面板的托管（被 .gitignore 排除）
      3. backend/keys.fallback.json —— 随仓库分发，云端部署的最后兜底
    """
    cache = {}
    # 3) 随仓库分发的兜底（JSON）
    try:
        with open(_KEYS_FALLBACK_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str) and not k.startswith("_"):
                    cache[k] = v
    except Exception:
        pass
    # 2) 本地 config.local.js（JS 对象字面量），覆盖兜底值
    try:
        with open(_CFG_LOCAL_PATH, "r", encoding="utf-8") as f:
            body = f.read()
        for k, v in re.findall(r'(\w+)\s*:\s*"([^"]*)"', body):
            cache[k] = v
    except Exception:
        pass
    return cache


def cfg_local_get(name):
    """读取非环境变量来源的密钥；找不到返回空串。"""
    global _CFG_LOCAL_CACHE
    if _CFG_LOCAL_CACHE is None:
        _CFG_LOCAL_CACHE = _load_cfg_cache()
    return _CFG_LOCAL_CACHE.get(name, "")


SF_KEY = os.environ.get("SF_API_KEY") or cfg_local_get("SF_API_KEY")   # 密钥不入库：从环境变量读取，见 .env.example
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
    if not os.path.exists(_TR_CACHE_FILE):
        # 冷启动（含 Railway 部署重建容器、缓存文件随旧容器一起没了）属正常情况，
        # 不该每次都告警 —— 否则部署后首批次会记一条 warn，把界面误挂上
        # 「部分信源未抓到」横幅（实际 0 个源失败）。对齐 _load_tag_cache() 的行为。
        return {}
    try:
        with open(_TR_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        # 文件存在但读不动（损坏 / 权限），有兜底（未命中就重新翻译，结果仍正确，
        # 只是慢且费钱）→ warn 级，这种情况才值得报警
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
#   /trending/<id> → 普通 UA 只给 4.8KB JS 壳（无正文）；
#                    **换搜索引擎爬虫 UA 则返回 SSR 完整 HTML**，其中「事件详情」区块
#                    就是该热点的正文来源（实测 2026-09-14：纯 HTTP、0.3s/条）：
#                      · 文章型   → 块内有 /article/<id> → 取文章全文（实测 741–3730 字）
#                      · 微头条型 → 块内有 /w/<id>     → 取微头条正文（实测 292 字）
#                      · 视频型   → 只有几十字视频文案，本身无文章正文 → 诚实标记 no_source
#                    无头 Chrome 渲染只作兜底（本地可用，Railway 容器里没有 Chrome）。
_TT_ART_RE = re.compile(r"/article/(\d{6,})")
_TT_TREND_RE = re.compile(r"/trending/(\d{6,})")
_TT_W_RE = re.compile(r"/w/(\d{6,})")

# 头条对搜索引擎爬虫放行 SSR —— 这是线上（容器内无 Chrome）取头条原文的唯一可行路径
BOT_UA = "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)"
_TT_BLOCK_RE = re.compile(r'<div class="block-title">([^<]*)</div>', re.I)
# 低于此长度不当作「正文」（实测边界：视频型事件文案 56–119 字，最短的真实简讯 133 字；
# 取 125 可放行真实简讯、挡住视频文案，避免把视频标题送去事实抽取）
_TT_MIN_TEXT = 125

# 视频型事件（话题页「事件详情」块只有 /video/<id> + 几十字视频文案）→ 直接拦截，不进热点列表。
# 依据（2026-09-14 实测）：这类事件全链路都没有文章正文 —— 块内无 /article/ 与 /w/，
# /video/<id> 页与移动 JSON 抽取正文均为 0 字，meta 描述只是视频标题 + 样板文。
# 留着只会在界面显示「无原文」，对下游事实抽取毫无价值。
# 置 False 可恢复旧行为（保留条目并如实标记 no_source）。
TOUTIAO_DROP_VIDEO = True

# 本批被拦截的视频型热搜（随 /api/trends 响应回传，说明条数变少是预期而非故障）
_TT_DROPPED_VIDEO = []


def tt_take_dropped_video():
    """取出并清空本批被拦截的视频型热搜。供接口回传，避免「条数变少」被当成抓取失败。"""
    out = list(_TT_DROPPED_VIDEO)
    del _TT_DROPPED_VIDEO[:]
    return out


# 本批因「拿不到可用正文」被筛掉的条目（含视频型之外的情况：话题页无正文、
# 正文短于 MIN_USABLE_TEXT、RSS 抓取失败只剩短摘要）。
# 统一走这一个台账，接口就能一次说清「少了多少条、为什么少」。
_TR_DROPPED_NO_TEXT = []


def tt_take_dropped_no_text():
    """取出并清空本批被筛掉的「无可用正文」条目。供接口回传。"""
    out = list(_TR_DROPPED_NO_TEXT)
    del _TR_DROPPED_NO_TEXT[:]
    return out


# 本批因「发布日期超过 TRENDS_MAX_AGE_DAYS」被筛掉的条目（2026-09-20 新增）。
# 为什么要单独记：条数变少必须解释得清；且**某个源一次被整批筛掉 = 那个源已经停更**，
# 这是发现「源失效」最早的信号 —— 比等老师看到旧闻再反馈要早得多。
_TR_DROPPED_STALE = []


def tt_take_dropped_stale():
    """取出并清空本批因超期被筛掉的条目。供接口回传。"""
    out = list(_TR_DROPPED_STALE)
    del _TR_DROPPED_STALE[:]
    return out


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


def _tt_page_source(html):
    """从文章页 SSR 的 meta 行取来源名（形如「标题  2026-09-14 10:32 · 新华社」）"""
    m = re.search(r'class="[^"]*article-content[^"]*"[^>]*>([\s\S]{0,600}?)</div>', html or "", re.I)
    if not m:
        return ""
    t = clean_html(m.group(1))
    mm = re.search(r"[·•]\s*([^·•\s]{2,20})", t)
    return mm.group(1).strip() if mm else ""


def toutiao_article_ssr_text(art_id, timeout=15):
    """爬虫 UA 抓文章页 → SSR 里的 <article> 就是完整正文（无需 Chrome）。

    实测：同一篇 7685205245144482350，移动 JSON 只给 145 字，文章页 SSR 有 1303 字。"""
    try:
        html = fetch("https://www.toutiao.com/article/%s/" % art_id, timeout=timeout,
                     headers={"User-Agent": BOT_UA}).decode("utf-8", "ignore")
    except Exception as e:
        note_error("toutiao.article.ssr", e, severity="warn", art_id=str(art_id))
        return {"text": "", "source": "", "title": ""}
    title = ""
    m = re.search(r"<title>([^<]*)</title>", html, re.I)
    if m:
        title = re.sub(r"\s*[-_]\s*今日头条\s*$", "", clean_html(m.group(1))).strip()
    return {"text": extract_article_from_dom(html), "source": _tt_page_source(html), "title": title}


def toutiao_article_full(art_id):
    """文章正文取全：移动 JSON 优先（快），不足 200 字再上文章页 SSR。"""
    r = toutiao_article_text(art_id)
    if len(r["text"]) >= 200:
        return r
    ssr = toutiao_article_ssr_text(art_id)
    if len(ssr["text"]) > len(r["text"]):
        return {"text": ssr["text"], "source": ssr["source"] or r["source"],
                "title": ssr["title"] or r["title"]}
    return r


def toutiao_micro_text(wid, timeout=15):
    """微头条（/w/<id>）正文：SSR 里的 <article> 即正文。返回 {text, source}"""
    try:
        html = fetch("https://www.toutiao.com/w/%s/" % wid, timeout=timeout,
                     headers={"User-Agent": BOT_UA}).decode("utf-8", "ignore")
    except Exception as e:
        note_error("toutiao.micro", e, severity="warn", wid=str(wid))
        return {"text": "", "source": ""}
    return {"text": extract_article_from_dom(html), "source": _tt_page_source(html)}


def _tt_event_block(html):
    """截出话题页「事件详情」区块的 HTML —— 只在这一块里找正文，
    避免抓到「网友讨论」和相关推荐里的别的文章。"""
    if not html:
        return ""
    marks = [(m.start(), m.group(1)) for m in _TT_BLOCK_RE.finditer(html)]
    for i, (pos, t) in enumerate(marks):
        if "事件详情" in t:
            end = marks[i + 1][0] if i + 1 < len(marks) else len(html)
            return html[pos:end]
    return ""


def _tt_block_text(seg):
    """「事件详情」区块的内嵌文案（微头条/视频型没有外链时可当作正文）"""
    t = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", seg, flags=re.I)
    t = clean_html(t)
    # 去掉区块自带的固定 UI 噪声词，剩下才是正文
    for w in ("事件详情", "关注", "分享", "转发到头条", "复制链接", "微信扫码分享",
              "微信", "新浪微博", "QQ空间", "请先", "登录", "后发表评论～", "评论",
              "换一换", "举报"):
        t = t.replace(w, " ")
    return re.sub(r"\s{2,}", " ", t).strip()


def toutiao_topic_ssr_text(topic_url, timeout=12):
    """话题聚合页 → 爬虫 UA 走 SSR → 解出该热点正文。**纯 HTTP，无需 Chrome**。

    这是线上（Railway 容器无 Chrome）取头条原文的主力路径。
    返回 {text, source, url, kind}；kind ∈ {article, micro, video, none}"""
    try:
        html = fetch(topic_url, timeout=timeout,
                     headers={"User-Agent": BOT_UA}).decode("utf-8", "ignore")
    except Exception as e:
        note_error("toutiao.topic.ssr", e, severity="warn", url=topic_url)
        return {"text": "", "source": "", "url": "", "kind": "none"}
    seg = _tt_event_block(html)
    if not seg:
        return {"text": "", "source": "", "url": "", "kind": "none"}
    # ① 文章型：块内有 /article/<id> → 取全文（正文本身可能很短，如新华社简讯 133 字，
    #    那是真实全文而非抓取失败，长度交上层用 _TT_MIN_TEXT 判，这里不改写 kind）
    m = re.search(r'href="/article/(\d{6,})/', seg)
    if m:
        r = toutiao_article_full(m.group(1))
        return {"text": r["text"], "source": r["source"],
                "url": "https://www.toutiao.com/article/%s" % m.group(1), "kind": "article"}
    # ② 微头条型：块内有 /w/<id> → 取微头条正文；取不到就退回块内文案
    w = _TT_W_RE.search(seg)
    if w:
        r = toutiao_micro_text(w.group(1))
        if len(r["text"]) < _TT_MIN_TEXT:
            inline = _tt_block_text(seg)
            if len(inline) > len(r["text"]):
                return {"text": inline, "source": "", "url": topic_url, "kind": "micro"}
        return {"text": r["text"], "source": r["source"],
                "url": "https://www.toutiao.com/w/%s" % w.group(1), "kind": "micro"}
    # ③ 无外链：只剩块内文案。够长算微头条文案，过短则确属视频型（本身无文章正文）
    inline = _tt_block_text(seg)
    if len(inline) >= _TT_MIN_TEXT:
        return {"text": inline, "source": "", "url": topic_url, "kind": "micro"}
    return {"text": inline, "source": "", "url": topic_url, "kind": "video"}


_CHROME_OK = None   # None=尚未探测；True/False=探测结果（只探一次，避免每条目都白等 10 秒）


def _chrome_path():
    """返回可用的 headless Chrome 可执行文件路径；找不到返回 None。

    跨平台：macOS 找 Applications 下的 Chrome，Linux 依次找 chromium / google-chrome。
    也可用环境变量 CHROME_PATH 显式指定 —— 在 Railway 等容器里装了 Chromium 后，
    把它配成 /usr/bin/chromium 就能启用 JS 渲染；不配则依赖渲染的抓取源静默降级。"""
    env = (os.environ.get("CHROME_PATH") or "").strip()
    if env:
        return env
    for c in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/usr/bin/chromium", "/usr/bin/chromium-browser",
              "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"):
        if os.path.exists(c):
            return c
    return None


def _chrome_available():
    """探测本机 Chrome headless 是否可用，结果缓存。
    在受限沙箱内 Chrome 会以 Abort trap 6 退出，此时必须快速判定不可用并整体回退，
    否则 15 条热搜 × 10 秒 = 2 分多钟，用户会以为卡死。"""
    global _CHROME_OK
    if _CHROME_OK is not None:
        return _CHROME_OK
    import subprocess
    chrome = _chrome_path()
    if not chrome:
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
        chrome = _chrome_path()
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
# ⚠️ 2026-09-20 清空（原 4 条：人民网 文化/时政/国际 + 新华网 时政）。
# 实测这两个 RSS **早已停更，且都是静态文件**（探针直取原始 feed 确认）：
#   · 人民网 culture.xml 最新 2025-05-25、politics/world.xml 最新 2025-06-05 → **停更 15 个月**
#   · 新华网 news_politics.xml **连 pubDate 字段都没有**，内容是 2022-12 新冠政策期 → **近 4 年**
# 它们贡献的 15 条（线上 190 条里 #155–#169）全是陈旧内容，对「找今天的素材」毫无价值。
# 两层修复：`parse_ts` 已补上 ISO8601 解析（见该函数注释），人民网那类**带日期的**旧闻
# 现在会被 14 天时效过滤拦住；但**新华网没有日期可判**，只能靠下线解决。
# 保留空列表而不删掉本常量与 `cn_fallback_article()`：
#   ① 中文源兜底链路（给头条热搜找原配出处）结构保持完整，**换上有真实时效的中文源即自动复活**；
#   ② 实测该兜底在 min_score=6 下**当前 0 命中**（这两家的 editorial 内容与突发热搜几乎无重合），
#      清空不损失任何现有交付内容。
# 补源方向（待定，需 Bryan 定）：要的是「带 pubDate、日更」的中文新闻 / 文化源。
CN_FEEDS = []


def _cn_bigrams(s):
    s = re.sub(r"[^\u4e00-\u9fa5]", "", s or "")
    return set(s[i:i + 2] for i in range(max(0, len(s) - 1)))


def cn_fallback_article(title, min_score=6):
    """按热点标题在中文 RSS 里找最相关的原文。返回 {text, source, url, score}。
    ⚠️ min_score 默认 6 是刻意的。实测人民网/新华网 RSS 偏 editorial（文博会、地质公园
    一类），与热搜的突发新闻几乎无重合，正经匹配最高只到 1–2 分。
    2026-09-14 抓到一次 4 分的**假匹配**：热搜「国家卫健委：进一步营造生育友好环境」(2026)
    被配上「国家卫健委发布新冠病毒疫苗第二剂次加强免疫接种实施方案」(2022) —— 两边只是
    共有一个机构名「国家卫健委」。可见 3 分并不安全，故提到 6 分。
    宁可诚实标记无原文，也不给错的出处（伪造溯源比缺原文更糟）。"""
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
    原文链路：/article/<id> → 移动 JSON / 文章页 SSR；/trending/<id> → 爬虫 UA 走 SSR 取「事件详情」；
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
    rows = []
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
        rows.append({"topic": en_title or title, "cn": title, "source": "今日头条热搜",
                     "url": it.get("Url") or "", "summary": "", "fulltext": "",
                     "fulltext_status": "no_source", "fulltext_len": 0, "fulltext_err": "",
                     "date": time.strftime("%Y-%m-%d"), "ts": time.time(),
                     "hot": hot_num, "heat": max(50, 98 - i), "srcs": 1, "lang": "zh"})
    if want_fulltext and rows:
        # 正文抓取分两步，因为两条链路的并发特性完全不同：
        #   ① A1(文章 JSON) / A2a(话题页 SSR) 是纯 HTTP。50 条串行实测 48s，是整榜耗时的大头，必须并发。
        #   ② A2b(无头渲染) 每调一次要拉起一个 Chrome 进程，**并发会同时起十几个**，
        #      所以并发只用于 ①；② 留给「排名靠前、纯 HTTP 没拿到正文」的少数条目串行兜底。
        def _one(r):
            _fill_toutiao_fulltext(r, r.get("cn") or "", allow_render=False)
        with concurrent.futures.ThreadPoolExecutor(max_workers=TOUTIAO_FETCH_WORKERS) as ex:
            list(ex.map(_one, rows))
        # 渲染兜底：线上容器没有 Chrome（render_dom_with_chrome 直接返回 None），这段等于空转 —— 与原设计一致。
        for r in rows[:TOUTIAO_RENDER_LIMIT]:
            if (r.get("fulltext_len") or 0) >= MIN_USABLE_TEXT:
                continue
            if r.get("fulltext_status") == "video_dropped":
                continue
            if not _TT_TREND_RE.search(r.get("url") or ""):
                continue
            _fill_toutiao_fulltext(r, r.get("cn") or "", allow_render=True)
    out = []
    for row in rows:
        if want_fulltext:
            _st = row.get("fulltext_status") or "failed"
            # 视频型已按规则拦截：整条不进结果列表（列表变短是预期行为，不是抓取失败）。
            # 拦截条目不进 _health_record —— 源成功率要反映「交付出去的内容质量」，
            # 被主动筛掉的条目不该把成功率拉低；它另由 filtered_video 台账回传。
            if _st == "video_dropped":
                _TT_DROPPED_VIDEO.append({"title": row.get("cn") or "",
                                          "url": row.get("url") or ""})
                continue
            _health_record("今日头条热搜", _st, 0)
        out.append(row)
    return out


# 话题页渲染较慢（CDP 路径实测约 7 秒/条），限制每批最多渲染几条，避免整榜卡死。
# 实测（2026-09-03）：设为 5 时只覆盖前 5 条头条，后面的都落 no_source；
# 头条在整榜里通常占 5–12 条，且渲染成功率很高（5/5 全中），故放宽到 12 覆盖全部头条。
TOUTIAO_RENDER_LIMIT = 12


def _fill_toutiao_fulltext(row, title, allow_render=True):
    """给单条头条热点补原文：
    A1(直达文章) → A2a(话题页 SSR，纯 HTTP) → A2b(无头渲染兜底) → B(中文 RSS) → C(如实标记)"""
    url = row.get("url") or ""
    _ssr_short = ""              # 话题页拿不到可用正文时的具体原因，最终降级文案要说清
    _ssr_conclusive = False      # 话题页已解析出「事件详情」块 → 答案已确定，不必再走渲染兜底
    m = _TT_ART_RE.search(url)
    if m:
        r = toutiao_article_full(m.group(1))
        if len(r["text"]) >= 200:
            row["fulltext"] = r["text"]
            row["fulltext_status"] = "ok" if len(r["text"]) >= MIN_ARTICLE_CHARS else "short"
            row["fulltext_len"] = len(r["text"])
            if r["source"]:
                row["source"] = "今日头条 · %s" % r["source"]
            row["tt_kind"] = "article"
            row["url"] = "https://www.toutiao.com/article/%s" % m.group(1)
            return
    # A2a：话题聚合页 → 爬虫 UA 走 SSR（纯 HTTP，线上唯一可行路径，实测 0.3s/条）
    if _TT_TREND_RE.search(url):
        sr = toutiao_topic_ssr_text(url)
        _ssr_conclusive = (sr["kind"] != "none")
        row["tt_kind"] = sr["kind"]
        # 视频型：事件本身是短视频，全链路无文章正文 → 按规则拦截。
        # 提前 return 可顺带省掉「中文源兜底」与本条的无头渲染尝试。
        if sr["kind"] == "video" and TOUTIAO_DROP_VIDEO:
            row["fulltext_status"] = "video_dropped"
            row["fulltext_err"] = ("视频型事件（事件详情为短视频，无文章正文），"
                                   "已按规则拦截，不纳入热点列表")
            return
        if len(sr["text"]) >= _TT_MIN_TEXT:
            row["fulltext"] = sr["text"]
            row["fulltext_status"] = "ok" if len(sr["text"]) >= MIN_ARTICLE_CHARS else "short"
            row["fulltext_len"] = len(sr["text"])
            if sr["source"]:
                row["source"] = "今日头条 · %s" % sr["source"]
            row["url"] = sr["url"]
            if row["fulltext_status"] == "short":
                row["fulltext_err"] = ("话题原文本身较短（%d 字，%s）"
                                       % (len(sr["text"]),
                                          "文章型简讯" if sr["kind"] == "article" else "微头条文案"))
            return
        if sr["kind"] == "video":
            _ssr_short = "该热搜为视频型事件，事件详情本身是短视频、没有文章正文"
        elif sr["text"]:
            _ssr_short = "话题页仅有简短文案（%d 字），无长文正文" % len(sr["text"])
        else:
            _ssr_short = "话题页未附文章正文"
    # A2b：SSR 没解出 → 无头渲染兜底（本地有 Chrome 时可用；线上容器无 Chrome，会整体跳过）
    if allow_render and not _ssr_conclusive and _TT_TREND_RE.search(url):
        dom = render_dom_with_chrome(url)
        if dom:
            ids = []
            for aid in _TT_ART_RE.findall(dom):
                if aid not in ids:
                    ids.append(aid)
            for aid in ids[:3]:
                r = toutiao_article_full(aid)
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
                    row["tt_kind"] = "article"
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
    row["fulltext_err"] = ("%s，且无匹配中文源，请手动粘贴素材" % _ssr_short if _ssr_short else
                           "未能获取原文（话题页未附文章正文，且无匹配中文源），请手动粘贴素材")


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


# ==================== 交付配比（2026-09-23 Bryan 指定）====================
# 今日头条 50% / CGTN 30% / 其余 20%。
# ⚠️ 「50%」是**目标配额**，不是保证值 —— 今日头条热榜总共只有 50 条，实测能拿到可用正文的
#    上限约 32 条，120 条里的 50%（= 60 条）它给不出来。头条拿不满时，缺口**全部由「其余」补**：
#    绝不用别的源冒充头条，也不为了让比例好看把列表截短 —— 那是拿假供给骗人。
# 分组判据是**信源**（source 前缀），不是内容类别：一篇文章讲什么，跟它由谁发布无关。
TRENDS_QUOTA = {"toutiao": 0.50, "cgtn": 0.30}
# 三组在最终列表里的块顺序。后端返回什么顺序，前端就按什么顺序渲染（只做 filter，不重排），
# 所以这个顺序 = 老师在界面上看到的顺序：头条永远在最上面。
TRENDS_QUOTA_ORDER = ("toutiao", "cgtn", "rest")

# 头条热榜一次取多少条。原先在 fetch_trends 里是**无参调用**（默认 15 条），
# 实测那 15 条里只有 8 条能拿到正文 ⇒ 头条在最终列表里只占 7%，与「主力源」定位完全不符。
# 热榜本身总共 50 条，全量取回才谈得上 32 条可用。
TOUTIAO_HOTBOARD_LIMIT = 50
# 头条正文抓取的并发度：A1(文章 JSON) / A2a(话题页 SSR) 都是纯 HTTP，50 条串行实测 48s，
# 是整个 /api/trends 的耗时大头。实测 5 线程 → 16.3s，8 线程 → 更快；
# 再往上收益递减且容易触发风控，8 是「够快」与「别把头条惹毛」之间的折中。
TOUTIAO_FETCH_WORKERS = 8

# CGTN 的按源上限单独放宽。PER_SOURCE_LIMIT=4 是为 40+ 个来源做的多样性保护，
# 但 CGTN 只有 5 个栏目源，4 条上限把它压死在最多 20 条，够不到 30% 配额（120 条时 = 36 条）。
# 实测 CGTN 正文可交付率 92%（55/60），放宽到 12 条/源是安全的（5×12 = 60 条候选）。
CGTN_PER_SOURCE_LIMIT = 12
# 候选池相对配额的放大系数：补正文之后还会筛掉一批「无可用正文」的条目，
# 不留冗余就会在最后一步凑不满 limit —— 表现是列表莫名变短，最容易被当成抓取故障。
# 取 1.35 而不是更大：候选池每多一条都要真金白银地抓正文 + 翻译，实测 1.5 时
# 首次耗时逼近 100s（超出前端「约 50–90 秒」的预估文案）；实测 1.35 的冗余仍然够用
# （CGTN 可交付率 92%、其余组实测用 52 条 / 池 71 条）。
QUOTA_POOL_FACTOR = 1.35


# 渲染器（headless Chrome / CDP）不可用只是「次要路径失效」：
# 头条正文有 A1 直达文章 JSON 兜底，实测 30/30 条目仍有完整正文（均值 1727 字）。
# 因此这类 warn 不应触发界面「部分信源未抓到」的降级提示，避免误导使用者。
_RENDER_SCOPES = ("render.chrome", "render.cdp", "render.dom", "render.article")

# 「明确不影响本批交付结果」的 warn 白名单。这类失败只影响体验/性能，
# 结果一条不少，**不该让整个热点榜挂上「部分信源未抓到」的横幅** —— 那是在说「有源坏了」，属误导。
# 🔴 2026-09-20：源从 17 个扩到 52 个后，补正文次数大增，线上 `article.cache.save`
#    开始成批失败（Railway 容器磁盘写入受限），一次请求就攒出 15 条 warn →
#    degraded=True。而实测交付条目 114 条、一个源都没少 —— 纯误报。
#    ⚠️ 判据很窄：只有 warn 级 + 明确写「不影响本次结果」的 scope 才进这个名单。
_BENIGN_WARN_SCOPES = _RENDER_SCOPES + ("article.cache.save",)


def _is_real_degradation(errs):
    """只有「真正影响结果完整性」的错误才算降级；渲染器缺失、缓存写入失败不计。"""
    for e in errs or []:
        scope = e.get("scope") or ""
        if scope.startswith(_BENIGN_WARN_SCOPES) and (e.get("severity") or "") == "warn":
            continue
        return True
    return False


def trend_group(it):
    """交付配比分组：toutiao / cgtn / rest。判据是信源前缀，不是内容类别。"""
    src = it.get("source") or ""
    if src.startswith("今日头条"):
        return "toutiao"
    if src.startswith("CGTN"):
        return "cgtn"
    return "rest"


def _quota_targets(limit):
    """按配比算出三组的目标条数：(头条, CGTN, 其余)。"""
    tt = int(round(limit * TRENDS_QUOTA["toutiao"]))
    cg = int(round(limit * TRENDS_QUOTA["cgtn"]))
    return tt, cg, max(0, limit - tt - cg)


def _round_robin(rows, n):
    """按信源轮转取前 n 条。

    CGTN 有 5 个栏目源，纯按热度排会让同一个栏目连排十几条；轮转让 5 个栏目交替出现。
    信源内部的相对顺序仍保持热度降序。"""
    piles = {}
    for r in rows:
        piles.setdefault(r.get("source") or "?", []).append(r)
    out, i = [], 0
    while len(out) < n:
        added = False
        for p in piles.values():
            if i < len(p):
                out.append(p[i])
                added = True
                if len(out) >= n:
                    break
        if not added:
            break
        i += 1
    return out


def _pick_by_quota(pool, limit):
    """从**已确认有可用正文**的候选池里，按交付配比选出最终列表。

    块顺序固定为 头条 → CGTN → 其余（头条是主力源，永远排最前）。
    头条 / CGTN 拿不满各自的配额时，缺口全部由「其余」补 —— 而不是把列表截短。
    配额只在这里施加，不能提前到「截断」那一步：那时还没有补正文，
    条目后面被无正文闸门筛掉多少是未知的，提前按配额选会让最终比例漂掉。"""
    tgt_tt, tgt_cg, _ = _quota_targets(limit)
    groups = {g: [] for g in TRENDS_QUOTA_ORDER}
    for it in pool:
        groups[trend_group(it)].append(it)
    picked = list(groups["toutiao"][:tgt_tt])
    picked += _round_robin(groups["cgtn"], tgt_cg)
    need = limit - len(picked)
    if need > 0:
        picked += groups["rest"][:need]
    if len(picked) < limit:
        # 「其余」也不够（极罕见）：按热度从落选池补齐，绝不空手而归。
        used = set(id(x) for x in picked)
        for it in pool:
            if len(picked) >= limit:
                break
            if id(it) not in used:
                picked.append(it)
                used.add(id(it))
    return picked[:limit]


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

    # 1) 中文全网热搜（全量取回：它是配比里的主力源，默认 15 条根本不够分）
    for it in fetch_toutiao(limit=TOUTIAO_HOTBOARD_LIMIT):
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
    # 每个信源最多保留若干条，保证源多样性（国际源不被单一源挤掉）。
    # ⚠️ 上限必须按**交付分组**给：头条 / CGTN 是配比里的主力，一并套用 4 条会把它们自己的配额
    #    当场卡死（实测头条被压到 8 条、CGTN 压到 20 条 —— 配比改成多少都落不了地）。
    PER_SOURCE_LIMIT = 4
    _SRC_CAP = {"toutiao": TOUTIAO_HOTBOARD_LIMIT,
                "cgtn": CGTN_PER_SOURCE_LIMIT,
                "rest": PER_SOURCE_LIMIT}
    by_src = {}
    for it in items:
        src = it.get("source", "?")
        if len(by_src.setdefault(src, [])) < _SRC_CAP[trend_group(it)]:
            by_src[src].append(it)
    items = [x for v in by_src.values() for x in v]
    # 统一补 heat / theme / sub / srcs
    for it in items:
        if "heat" not in it:
            recency = max(0.0, 1.0 - (now - it.get("ts", 0)) / (7 * 86400)) if it.get("ts") else 0.5
            it["heat"] = int(min(98, 50 + recency * 40))
        # 旧的信源加权（SOURCE_BOOST）已随配额制一起撤掉：CGTN 的份额不再靠 heat 加权去争，
        # 而是由 _pick_by_quota 按配比直接留位 —— 加权在硬配额下只会影响组内顺序，等于失效。
        if not it.get("theme"):
            it["theme"] = classify_theme(it.get("topic", "") + " " + it.get("summary", ""))
        if not it.get("sub"):
            _, ms, _ = match_entry(it.get("topic", "") + " " + it.get("summary", ""), it["theme"], None)
            it["sub"] = ms
        it.setdefault("srcs", 1)
        it.setdefault("lang", "en")
    # 时间过滤：超过 TRENDS_MAX_AGE_DAYS 天的内容丢弃（RSS 历史条目 / 已停更的源会污染今日榜）。
    # ⚠️ ts == 0（源没给日期，或日期格式仍解析不了）**当前放行**，仅靠排序键 `-ts` 自然沉底。
    #    理由：「源没给日期」不等于「内容是旧的」—— Greater Good 等源正常更新但不带 pubDate，
    #    一律剔除会误杀好源。**代价是「完全不给日期的停更源拦不住」**：
    #    新华网那条 2022 年新冠内容正属此类（该源已于 2026-09-20 下线，见 CN_FEEDS 注释）。
    #    被筛条目走独立台账，不写 note_error（正常业务筛选不该让整榜挂降级横幅）。
    _max_age = TRENDS_MAX_AGE_DAYS * 86400
    _kept_age = []
    for it in items:
        _ts = it.get("ts") or 0
        if _ts and (now - _ts > _max_age):
            _TR_DROPPED_STALE.append({
                "title": it.get("cn") or it.get("topic") or "",
                "source": it.get("source") or "",
                "url": it.get("url") or "",
                "age_days": round((now - _ts) / 86400, 1),
            })
            continue
        _kept_age.append(it)
    items = _kept_age
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
    # 截断：按配额把候选池**放大**取回（补正文还会筛掉一批），
    # 等确认有正文之后才在最后一步按配额精确选最终 limit 条。
    # 顺序不能颠倒 —— 提前按配额选，会让后面被无正文闸门筛掉的份额凭空消失。
    _tgt_tt, _tgt_cg, _tgt_rest = _quota_targets(limit)
    _by_group = {g: [] for g in TRENDS_QUOTA_ORDER}
    for it in ranked:
        _by_group[trend_group(it)].append(it)
    # 头条 / CGTN 的实际供给 ≤ 配额（热榜总共 50 条，实测可用 ~32 条），
    # 缺掉的份额由「其余」顶上，所以「其余」的候选量要按**补位后的需求**估，而不是它自己的 20%。
    _rest_need = max(_tgt_rest,
                     limit - min(len(_by_group["toutiao"]), _tgt_tt)
                           - min(len(_by_group["cgtn"]), _tgt_cg))
    ranked = (_by_group["toutiao"][:_tgt_tt]
              + _by_group["cgtn"][:int(math.ceil(_tgt_cg * QUOTA_POOL_FACTOR))]
              + _by_group["rest"][:int(math.ceil(_rest_need * QUOTA_POOL_FACTOR))])
    # 第一层：为英文/中文 RSS 条目补齐原文（头条条目已在 fetch_toutiao 里按 A→B→C 处理过）
    try:
        enrich_fulltext(ranked, workers=8)
    except Exception as e:
        note_error("trends.enrich_fulltext", e, severity="error",
                   msg="原文补齐失败，条目将只带摘要（不影响主流程）")
    # 第二层：无可用正文的条目一律不进列表 —— 列表里能看到的，点进去就能直接进入生成流程。
    # 判据与前端 hasUsableText 严格对齐（fulltext_len >= MIN_USABLE_TEXT）。
    # 这一步必须放在 enrich_fulltext 之后：抓取失败的条目会被回填成摘要（summary_only），
    # 摘要短于阈值时同样点不动 —— 不能因为「好歹有个摘要」就当它可用。
    # 也放在翻译之前：省掉给即将丢弃的条目做中英互译。
    # 拦截条目不进 _health_record：源成功率要反映「交付出去的内容质量」，
    # 被主动筛掉的条目不该把它拉低；条数变少的原因由 filtered_no_text 台账回传，界面明说。
    _kept = []
    for it in ranked:
        _len = it.get("fulltext_len")
        if _len is None:
            _len = len(it.get("fulltext") or "")
        if _len < MIN_USABLE_TEXT:
            _TR_DROPPED_NO_TEXT.append({
                "title": it.get("cn") or it.get("topic") or "",
                "url": it.get("url") or "",
                "lang": it.get("lang") or "en",
                "status": it.get("fulltext_status") or "unknown",
                "len": _len,
            })
            continue
        _kept.append(it)
    # 最后一步才按交付配比精挑：到这里的条目都已经确认有可用正文，
    # 配额落在这个位置上才不会被后面的筛选吃掉。
    ranked = _pick_by_quota(_kept, limit)
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


# ==================== 信源发现层（docs/29）====================
# 老师填的一个 URL 有四种可能：订阅地址 / 站点首页 / 栏目页 / 单篇文章。
# 此前只处理第一种，其余靠「降级成网页标题」兜底 —— 那会产出一条以 URL 当标题、正文一两百字符的
# 伪素材，生产不出任何档位的文章。按「热点搜集服务于文章生产」的原则（docs/29 §7）：
# **发现不到可用内容就如实报告，绝不产出条目充数。**

DISCOVER_TIMEOUT = 6        # 发现阶段单次探测超时。扫描是同步交互，必须控住总时长
DISCOVER_WORKERS = 6        # L2 常见路径并发探测的线程数
SITEMAP_MAX_URLS = 40       # sitemap 最多取多少条（只要最新的；892KB 的 sitemap 不能整棵解析）
_DISCOVER_TTL = 7 * 86400   # 发现成功的缓存时长
_DISCOVER_FAIL_TTL = 86400  # 发现失败的缓存时长（短一些）：否则每个扫描都为同一个站重跑 10 次探测
DISCOVER_CACHE = {}         # host → (ts, feed_url, method)；feed_url 为空串表示「最近确认过没有」

# L2：常见 feed 路径。对 WordPress / 自建站命中率不错；对大厂 SPA 无效（ABC 实测这些路径全 404）。
FEED_GUESS_PATHS = [
    "/feed", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml",
    "/feed/atom", "/feeds/all.rss", "/rss/index.xml", "/.rss",
]

# L3：站点知识库 —— host → 已知可用的 feed 地址。
# ⚠️ 表里每一条都是 2026-09-14 经线上服务逐个实测通过的，**不要凭记忆往里加**。
# 它只用于「发现」，不是内置信源，不会出现在界面上；维护成本约每站 1–2 分钟。
# 为什么需要它：ABC / ESPN 这类站的 feed 路径（/abcnews/topstories、/espn/rss/news）
# 既不在首页 HTML 里，也猜不出来（通用路径全 404）—— 没有这张表就永远发现不到。
SITE_FEED_INDEX = {
    "abcnews.com":          ["https://abcnews.go.com/abcnews/topstories"],
    "abcnews.go.com":       ["https://abcnews.go.com/abcnews/topstories"],
    "bbc.com":              ["https://feeds.bbci.co.uk/news/rss.xml",
                             "https://www.bbc.com/news/rss.xml"],
    "bbc.co.uk":            ["https://feeds.bbci.co.uk/news/rss.xml"],
    "theguardian.com":      ["https://www.theguardian.com/world/rss",
                             "https://www.theguardian.com/international/rss"],
    "nytimes.com":          ["https://www.nytimes.com/services/xml/rss/nyt/HomePage.xml"],
    "nbcnews.com":          ["https://feeds.nbcnews.com/nbcnews/public/news"],
    "washingtonpost.com":   ["https://feeds.washingtonpost.com/rss/world"],
    "wsj.com":              ["https://feeds.a.dj.com/rss/RSSWorldNews.xml"],
    "aljazeera.com":        ["https://www.aljazeera.com/xml/rss/all.xml"],
    "news.sky.com":         ["https://feeds.skynews.com/feeds/rss/world.xml"],
    "npr.org":              ["https://feeds.npr.org/1001/rss.xml"],
    "politico.com":         ["https://rss.politico.com/politics-news.xml"],
    "newyorker.com":        ["https://www.newyorker.com/feed/everything"],
    "theatlantic.com":      ["https://www.theatlantic.com/feed/all/"],
    "time.com":             ["https://time.com/feed/"],
    "vox.com":              ["https://www.vox.com/rss/index.xml"],
    "cnbc.com":             ["https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"],
    "bloomberg.com":        ["https://feeds.bloomberg.com/markets/news.rss"],
    "fortune.com":          ["https://fortune.com/feed/"],
    "sciencedaily.com":     ["https://www.sciencedaily.com/rss/all.xml"],
    "phys.org":             ["https://phys.org/rss-feed/"],
    "nasa.gov":             ["https://www.nasa.gov/rss/dyn/breaking_news.rss"],
    "smithsonianmag.com":   ["https://www.smithsonianmag.com/rss/latest_articles/"],
    "technologyreview.com": ["https://www.technologyreview.com/feed/"],
    "wired.com":            ["https://www.wired.com/feed/rss"],
    "arstechnica.com":      ["https://feeds.arstechnica.com/arstechnica/index"],
    "theverge.com":         ["https://www.theverge.com/rss/index.xml"],
    "techcrunch.com":       ["https://techcrunch.com/feed/"],
    "cnet.com":             ["https://www.cnet.com/feeds/news/"],
    "readwrite.com":        ["https://readwrite.com/feed/"],
    "economist.com":        ["https://www.economist.com/the-world-this-week/rss.xml"],
    "espn.com":             ["https://www.espn.com/espn/rss/news"],
    "news.ycombinator.com": ["https://news.ycombinator.com/rss"],
}


def _kb_host(u):
    """查知识库用的 host：小写、去 www.、去端口。"""
    h = (urllib.parse.urlparse(u).netloc or "").lower()
    h = h.split("@")[-1].split(":")[0]
    return h[4:] if h.startswith("www.") else h


def _site_root(u):
    p = urllib.parse.urlparse(u)
    return "%s://%s" % (p.scheme or "https", p.netloc)


def _fetch_text(url, timeout=DISCOVER_TIMEOUT):
    """抓文本。sitemap 常见 .gz 且往往不带 Content-Encoding，需按魔数手动解压。"""
    data = fetch(url, timeout=timeout)
    if data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except Exception:
            pass
    return data.decode("utf-8", "ignore")


def discover_feeds_from_html(html_bytes, base_url):
    """从网页 HTML 里自动发现 feed 地址，返回候选列表（可多个）。

    修掉旧实现的三个坑（docs/29 §3）：
      ① 只返回第一个匹配 —— 第一个可能不是主 feed（可能是评论/分类 feed），应全部返回再逐个验；
      ② 相对路径只处理 "/" 开头 —— href="feed.xml" 这种会被原样返回、抓取必失败（漏掉一整类站点）；
      ③ 强制要求 rel 含 alternate —— 有些站只写 type="application/rss+xml"。
    """
    try:
        text = html_bytes.decode("utf-8", "ignore")
    except Exception:
        return []
    out = []
    for m in re.finditer(r'<link[^>]+>', text, re.I):
        tag = m.group(0)
        low = tag.lower()
        if not ("rss" in low or "atom" in low or "feed" in low):
            continue
        href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if not href:
            continue
        rel = re.search(r'rel=["\']?([^"\'\s>]+)', tag, re.I)
        rel_v = rel.group(1).lower() if rel else ""
        typed = ("application/rss+xml" in low or "application/atom+xml" in low
                 or "application/feed+json" in low)
        if not typed and "alternate" not in rel_v and "feed" not in rel_v:
            continue
        cand = href.group(1).strip()
        if not cand or cand.startswith(("data:", "javascript:")):
            continue
        # urljoin 能正确处理 "/x"、"x"、"//host/x" 三种写法（修坑 ②）
        cand = urllib.parse.urljoin(base_url, cand)
        if cand not in out:
            out.append(cand)
    return out[:5]


def looks_like_article(html, url=""):
    """判断一个网页是「单篇文章」还是「列表页」。纯结构特征，不用 LLM。

    判错的代价很大，两个方向都糟：
      · 首页/栏目页被当成文章 → 老师只拿到一条首页碎片正文；
      · 文章被当成列表页 → 老师拿到整个 feed（几十条），而不是他点的那一篇。
    后者更容易接受，所以判据整体偏保守（宁可判成列表页）。

    三条判据，按可靠性排序：
      ① URL 路径段数 —— 根路径/单段路径（站点首页、栏目页）不可能是文章。最可靠且零成本；
      ② og:type 显式声明；
      ③ 一页里有几个 <article> 容器。
    ⚠️ 不要用「链接密度」：实测列表页 0.24–0.67 / 文章页 0.01–0.31，完全重叠，分不开。
    ⚠️ 也不能只信 og:type：ScienceDaily 首页自称 og:type=article（站点标注不严谨）。
    """
    if not html:
        return False
    if url:
        segs = [s for s in (urllib.parse.urlparse(url).path or "").split("/") if s]
        if len(segs) <= 1:
            return False
    head = html[:300000]
    og = re.search(r'<meta[^>]+property=["\']og:type["\'][^>]*content=["\']([^"\']+)', head, re.I)
    ogv = og.group(1).strip().lower() if og else ""
    if ogv == "article":
        return True
    if ogv in ("website", "blog", "profile"):
        return False          # 站点自己声明了这不是文章页，别用弱信号去推翻它
    n_art = len(re.findall(r"<article[\s>]", head, re.I))
    if n_art > 1:
        # 一页里多个 <article> 容器 = 列表页（每张内容卡一个），实测 ESPN 首页有 21 个
        return False
    if n_art == 1 and re.search(
            r"(?i)(article:published_time|og:updated_time|itemprop=[\"']datePublished)", head):
        return True
    return False


def robots_sitemaps(u):
    """从 robots.txt 读 Sitemap 声明 —— 找 sitemap 的**零猜测**路径（标准约定，站方自己声明）。
    实测 ABC / ESPN / ScienceDaily / The Verge 四站全部有声明。"""
    root = _site_root(u)
    try:
        txt = _fetch_text(root + "/robots.txt")
    except Exception:
        return []
    out = []
    for m in re.finditer(r"(?im)^\s*sitemap:\s*(\S+)", txt):
        v = m.group(1).strip()
        if v and v not in out:
            out.append(v)
    return out[:5]


def sitemap_article_urls(raw, limit=SITEMAP_MAX_URLS):
    """从 sitemap XML 取文章 URL。返回 (urls, 子sitemap列表)。
    sitemapindex 只递归一层，避免 sitemap 套娃；.gz 按魔数判断，不靠扩展名。"""
    data = raw or b""
    if data[:2] == b"\x1f\x8b":
        try:
            data = gzip.decompress(data)
        except Exception:
            return [], []
    try:
        root = ET.fromstring(data)          # 传 bytes：带 encoding 声明的 XML 不接受 str
    except Exception:
        return [], []
    tg = root.tag.split("}")[-1].lower()
    locs = []
    for e in root.iter():
        if e.tag.split("}")[-1].lower() == "loc" and (e.text or "").strip():
            locs.append(e.text.strip())
    if tg == "sitemapindex":
        return [], locs[:5]
    return locs[:limit], []


def _is_feed(url, timeout=DISCOVER_TIMEOUT):
    """探测一个地址是不是可用 feed：能解析出条目才算。"""
    try:
        d = fetch(url, timeout=timeout)
    except Exception:
        return False
    try:
        return bool(parse_feed(d, host_of(url)))
    except Exception:
        return False


def _title_from_url(u):
    """sitemap 只给 URL、没有标题。先用人可读的路径片段顶上，
    补正文时会被页面真实标题覆盖（见 enrich_fulltext 的 _topic_from_url）。"""
    try:
        seg = [s for s in (urllib.parse.urlparse(u).path or "").split("/") if s]
        if not seg:
            return u
        slug = seg[-1] if len(seg[-1]) > 3 else (seg[-2] if len(seg) > 1 else seg[-1])
        slug = re.sub(r"\.(html?|php|aspx|amp)$", "", slug, flags=re.I)
        words = urllib.parse.unquote(re.sub(r"[-_]+", " ", slug)).strip()
        return (words or u)[:120]
    except Exception:
        return u


def _discovery_chain(data, u, timeout=DISCOVER_TIMEOUT):
    """列表页 → feed。按成本从低到高，命中即止：L1 复用已抓 HTML → L3 查知识库 → L2 猜路径。
    返回 (feed_url, method)，找不到返回 (None, "")。"""
    host = _kb_host(u)
    hit = DISCOVER_CACHE.get(host)
    if hit:
        age = time.time() - hit[0]
        if age < (_DISCOVER_TTL if hit[1] else _DISCOVER_FAIL_TTL):
            return (hit[1], hit[2]) if hit[1] else (None, "")

    def _remember(url, method):
        DISCOVER_CACHE[host] = (time.time(), url, method)
        return url, method

    # L1：HTML 自动发现（复用上面已抓到的 HTML，零额外请求）
    for cand in discover_feeds_from_html(data, u):
        if _is_feed(cand, timeout):
            return _remember(cand, "autodiscover")

    # L3：站点知识库（零网络成本，且每条都是实测过的）
    for cand in SITE_FEED_INDEX.get(host, []):
        if _is_feed(cand, timeout):
            return _remember(cand, "index")

    # L2：常见路径并发探测，第一个命中的胜出
    root = _site_root(u)
    if root and not root.endswith("://"):
        with concurrent.futures.ThreadPoolExecutor(max_workers=DISCOVER_WORKERS) as ex:
            futs = {ex.submit(_is_feed, root + p, timeout): root + p for p in FEED_GUESS_PATHS}
            for f in concurrent.futures.as_completed(futs):
                try:
                    if f.result():
                        return _remember(futs[f], "guess")
                except Exception:
                    continue
    DISCOVER_CACHE[host] = (time.time(), "", "fail")
    return None, ""


# sitemap 里混着首页 / 栏目页 / 关于我们 —— 按路径特征滤掉明显不是文章的
_NON_ARTICLE_SEGS = {
    "about", "contact", "advertise", "privacy", "terms", "subscribe", "login",
    "signup", "help", "faq", "careers", "jobs", "sitemap", "rss", "feed",
    "tags", "tag", "categories", "category", "authors", "author", "search",
    "live", "video", "videos", "photos", "gallery", "shop", "store",
    "podcasts", "podcast", "newsletter",
}


def _looks_like_article_url(u):
    """判断 sitemap 里的一条 URL 像不像文章（排除首页、栏目页、关于我们这类）。"""
    try:
        segs = [s for s in (urllib.parse.urlparse(u).path or "").split("/") if s]
        if len(segs) < 2:
            return False                      # 根路径 / 单段 = 站点页或栏目页
        if any(s.lower() in _NON_ARTICLE_SEGS for s in segs):
            return False
        last = segs[-1].lower()
        if "." in last and not re.search(r"\.(html?|php|aspx|amp)$", last):
            return False                      # 静态资源（图片/PDF 等）
        return len(last) >= 4
    except Exception:
        return False


def _sitemap_priority(url):
    """news / 最新文章类 sitemap 优先。
    实测 ABC 的 robots 依次声明 xmap / xmlLatestStories / xmlLatestVideos，
    只有 xmlLatestStories 给的是文章列表 —— xmap 给的全是栏目页。必须按名字挑，不能取第一个。"""
    low = url.lower()
    for i, k in enumerate(("latest", "news", "article", "story", "post", "blog")):
        if k in low:
            return i
    return 9


def _discovery_sitemap(u, timeout=DISCOVER_TIMEOUT):
    """最后一招：robots.txt → sitemap → 文章 URL 列表。
    只有 URL、没有标题，质量最低，所以排在 feed 发现之后。"""
    sms = sorted(robots_sitemaps(u), key=_sitemap_priority)
    if not sms:
        root = _site_root(u)
        sms = [root + "/news-sitemap.xml", root + "/sitemap.xml"]
    for sm in sms:
        try:
            urls, subs = sitemap_article_urls(fetch(sm, timeout=timeout))
        except Exception:
            continue
        for sub in sorted(subs, key=_sitemap_priority)[:2]:
            if len(urls) >= SITEMAP_MAX_URLS:
                break
            try:
                more, _ = sitemap_article_urls(fetch(sub, timeout=timeout))
                urls.extend(more)
            except Exception:
                continue
        # 只留像文章的；若这个 sitemap 全是站点页，就换下一个
        urls = [x for x in dict.fromkeys(urls) if _looks_like_article_url(x)]
        if urls:
            return urls[:SITEMAP_MAX_URLS]
    return []


def discover_source(u, timeout=DISCOVER_TIMEOUT):
    """把一个老师填的 URL 解析成「可采集的来源」。

    返回 {kind, feed_url, feed_data, urls, method, reason}，kind ∈
      feed         —— 找到订阅地址（method: direct / autodiscover / index / guess）
      sitemap      —— 只拿到文章 URL 列表（method: robots-sitemap）
      article      —— 这个 URL 本身是一篇文章（method: article）
      unsupported  —— 发现不到可用内容；reason 是给老师看的**客观原因**：
                      site_blocks(站点拒绝自动化访问) / unreachable(站点无法访问)
                      / http_error / no_feed(没找到订阅地址)

    ⚠️ 这里**不记 error**：单个源抓不到是「这个源的客观结果」，不是系统故障。
    _is_real_degradation() 对任何非渲染类错误都返回 True —— 若在此记 error，
    老师加一个反爬站就会让整个热点榜挂上「降级」横幅。结果由 sources 报告承载并回传前端。
    """
    res = {"kind": "unsupported", "feed_url": "", "feed_data": None,
           "urls": [], "method": "", "reason": ""}
    try:
        data = fetch(u, timeout=timeout)
    except urllib.error.HTTPError as e:
        # 401/403/407/429 = 站点主动拒绝自动化访问。这是对方的访问策略，不是我们的故障 ——
        # 必须原样告诉老师，别让她反复试（docs/29 §6）。
        res["reason"] = "site_blocks" if e.code in (401, 403, 407, 429) else "http_error"
        res["http"] = e.code
        return res
    except Exception:
        res["reason"] = "unreachable"
        return res

    # ① 直接就是 feed
    if parse_feed(data, host_of(u)):
        res.update(kind="feed", feed_url=u, feed_data=data, method="direct")
        return res

    # ② 这个 URL 本身是一篇文章 → 直接当一条素材采集，不去找列表
    if looks_like_article(data.decode("utf-8", "ignore"), u):
        res.update(kind="article", method="article")
        return res

    # ③ 当成列表页（首页 / 栏目页）→ 找订阅地址
    feed_url, method = _discovery_chain(data, u, timeout)
    if feed_url:
        res.update(kind="feed", feed_url=feed_url, method=method)
        return res

    # ④ 兜底：sitemap 的最新文章列表
    urls = _discovery_sitemap(u, timeout)
    if urls:
        res.update(kind="sitemap", urls=urls, method="robots-sitemap")
        return res

    res["reason"] = "no_feed"
    return res


SCAN_PER_SOURCE_LIMIT = 20
# 扫描期补正文的条数上限与单篇超时：扫描是用户按了按钮就同步等的交互，
# 不能像 /api/trends 那样敞开抓。超出配额的条目状态标为「仅摘要」，不谎报「无原文」。
SCAN_ENRICH_LIMIT = 12
SCAN_ENRICH_TIMEOUT = 10


def _collect_from(res, u, limit):
    """按发现结果取条目。返回 (items, reason)。"""
    kind = res.get("kind")
    if kind == "article":
        # 老师直接贴了一篇文章的链接 —— 它就是一条素材，不需要找列表
        art = fetch_article(u, timeout=SCAN_ENRICH_TIMEOUT)
        if art.get("status") not in ("ok", "short"):
            return [], "article_empty"
        return [{"topic": art.get("title") or u, "source": "自定义信源", "url": u,
                 "summary": "", "date": "", "ts": time.time(),
                 "fulltext": art.get("text") or "", "fulltext_len": art.get("len") or 0,
                 "fulltext_status": art.get("status"), "fulltext_err": art.get("err") or ""}], ""
    if kind == "feed":
        try:
            data = res.get("feed_data") or fetch(res["feed_url"], timeout=DISCOVER_TIMEOUT)
        except Exception as e:
            note_error("scan.feed_fetch", e, severity="error", url=res.get("feed_url") or u)
            return [], "unreachable"
        got = parse_feed(data, host_of(res["feed_url"]))[:limit]
        return got, ("" if got else "feed_empty")
    if kind == "sitemap":
        urls = (res.get("urls") or [])[:limit]
        return [{"topic": _title_from_url(x), "source": "自定义信源", "url": x,
                 "summary": "", "date": "", "ts": time.time(), "_topic_from_url": True}
                for x in urls], ("" if urls else "sitemap_empty")
    return [], (res.get("reason") or "no_feed")


def fetch_scan(urls, limit=None):
    """逐源扫描，返回 (items, reports)。

    每个源都产出一份**发现报告**：成功要说清是怎么找到的，失败要说清客观原因
    （站点拒绝访问 / 无法访问 / 没找到订阅地址）。这比「界面上什么都没有、也不知道为什么」有用得多。

    ⚠️ 绝不降级造假：发现不到内容就如实报告，不产出任何条目。
    旧实现会把网页 <title> 当一条素材交出去 —— 那是以 URL/站名当标题、正文一两百字符的伪素材
    （实测 `https://abcnews.com/` → topic 直接是 URL、fulltext_len=165），生产不出任何文章。

    limit：每个源的条数上限（默认 SCAN_PER_SOURCE_LIMIT）。播客类 RSS 实测单源 2975 条，
    不限量会把界面淹掉；截断属预期行为，不记错误日志。"""
    if limit is None:
        limit = SCAN_PER_SOURCE_LIMIT
    items = []
    reports = []
    seen_urls = set()
    for u in urls:
        u = (u or "").strip()
        if not u:
            continue
        if not u.startswith("http://") and not u.startswith("https://"):
            u = "https://" + u
        rep = {"input": u, "kind": "unsupported", "method": "", "reason": "", "count": 0}
        try:
            res = discover_source(u)
            rep["kind"] = res.get("kind") or "unsupported"
            rep["method"] = res.get("method") or ""
            got, reason = _collect_from(res, u, limit)
            rep["reason"] = reason
        except Exception as e:
            # 只有「预期之外」的异常才记 error：单个源抓不到属于客观结果，走 rep.reason，
            # 否则 _is_real_degradation 会给整个榜单挂上降级横幅。
            note_error("scan.source", e, severity="error", url=u)
            got, rep["reason"] = [], "unreachable"
        added = 0
        for g in got:
            # 不回假热度：heat / srcs 原先是写死的 60 / 1，界面上的「热度 60 · 信源 1」是假指标。
            # 自定义源本来就没有热度口径，与其造一个，不如不回传（前端改显示来源与时间）。
            # origin 回传输入的那个 URL，前端据此把条目对回老师自己填的源名与标签。
            g["origin"] = u
            _gu = (g.get("url") or "").strip()
            if _gu:
                if _gu in seen_urls:
                    continue
                seen_urls.add(_gu)
            items.append(g)
            added += 1
        rep["count"] = added
        reports.append(rep)

    # 打通交付链路：只回 RSS 级的标题+摘要时，前端的 hasUsableText（fulltext_len>=200）一定不过，
    # 于是每次点卡片都被「请粘贴原文」拦住 —— 看起来有卡片，实际一步也走不到生成，等于没交付。
    # 这里与 /api/trends 保持一致，补抓正文；fetch_article 有磁盘缓存，重复扫同一源不再付成本。
    try:
        enrich_fulltext(items[:SCAN_ENRICH_LIMIT], workers=8, timeout=SCAN_ENRICH_TIMEOUT)
    except Exception as e:
        note_error("scan.enrich_fulltext", e, severity="error",
                   msg="扫描期补正文失败，条目仍可用（前端会标为仅摘要）")
    # 未补到正文的条目（含超出配额的）：如实标为「仅摘要」。
    # 这里不再有「降级成网页标题」产出的伪条目 —— 那种连摘要都没有，已由发现层直接拦掉。
    for it in items:
        if it.get("fulltext_status"):
            continue
        if (it.get("summary") or "").strip():
            it.setdefault("fulltext", it["summary"])
            it["fulltext_status"] = "summary_only"
        else:
            it.setdefault("fulltext", "")
            it["fulltext_status"] = "no_source"
            it["fulltext_err"] = it.get("fulltext_err") or "该来源未解析出可用的文章条目"
        it["fulltext_len"] = len(it.get("fulltext") or "")
    return items, reports



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
TTS_PAUSED = True   # 暂停硅基流动语音合成；恢复改回 False

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
    # 12 子档体系（2026-09-10 起）：按传入 articles 的**实际档位键**生成，
    # ⚠️ 不能再硬编码 ("A2","B1","B2") —— 前端现在传的是「当前大档的 3 个子档」
    #    （如 A1_1/A1_2/A1_3 或 B2P_1/B2P_2/B2P_3），硬编码会导致一个都匹配不上、
    #    **静默生成 0 条音频**。键兼容下划线式（A1_1/B2P_1）与点式（A1.1/B2+.1）。
    for lv in (articles or {}).keys():
        txt = (articles or {}).get(lv) or ""
        if isinstance(txt, (list, tuple)):
            txt = " ".join(str(x) for x in txt)
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

    # ---------- 反向代理：Dify / SiliconFlow ----------
    # 密钥只存在于服务端环境变量，不下发到前端；统一 UA 避免被上游 WAF 当 bot 拦截。
    def _env_key(self, name):
        # 环境变量优先；缺失时回落到 frontend/config.local.js（无环境变量面板的托管）
        return (os.environ.get(name) or cfg_local_get(name) or "").strip()

    def _proxy_post(self, upstream, api_key, payload, timeout=180):
        """原样转发到上游并把响应原样回给前端，前端解析逻辑不必改动。"""
        if not api_key:
            return self._send({"ok": False, "error": "missing upstream api key on server"}, 500)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(upstream, data=data, headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "User-Agent": UA,
            "Accept": "application/json",
        })
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "ignore")
            try:
                obj = json.loads(raw)
            except Exception:
                return self._send({"ok": False, "error": "upstream returned non-json",
                                   "detail": raw[:400]}, 502)
            if isinstance(obj, dict):
                obj["_proxy_ms"] = int((time.time() - t0) * 1000)
            return self._send(obj, 200)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "ignore")[:400]
            except Exception:
                pass
            return self._send({"ok": False, "error": "upstream http %s" % e.code,
                               "detail": detail}, 502)
        except Exception as e:
            return self._send({"ok": False, "error": "upstream error: %s" % e}, 502)

    def _proxy_licgen(self, api_key, payload):
        """授权母稿「向下生成」（图 B）代理：带「段落错位整条自动重跑」。

        Bryan（2026-09-22）拍板：nodeSemCheck 判出某档段落「信息点串位」时，
        **自动整条重跑该工作流**（Dify 图内无法单独重跑某一档，只能整条重来）。

        策略（避免死循环 / 成本失控）：
        - 最多重跑 **1 次**（即最多调用图 B 两次）。
        - 第一次跑完解析 outputs.sem_json 的 bad_total；>0 则重跑一次。
        - 第二次仍 >0 则回**第二次**结果（不无限重试），并附 `_sem_reprompted=True`
          告知前端「已自动重跑过、仍有错位，需人工介入」。
        - sem_json 解析失败（模型没吐合法 JSON）不触发重跑 —— 判不出错位就放行，
          避免因解析问题误重跑烧钱。
        """
        def _parse_bad_total(obj):
            try:
                outs = (obj or {}).get("data", {}).get("outputs", {}) or {}
                sem = outs.get("sem_json")
                if isinstance(sem, str):
                    sem = sem.strip()
                    # 剥掉可能的 markdown 代码块包裹
                    i, j = sem.find("{"), sem.rfind("}")
                    if i >= 0 and j > i:
                        sem = sem[i:j + 1]
                    sem = json.loads(sem)
                if isinstance(sem, dict):
                    return int(sem.get("bad_total") or 0)
            except Exception:
                pass
            return None  # None = 解析不出，视为「拿不准」，不触发重跑

        def _run_once_raw(p):
            """向上游跑一次并返回解析后的 dict（不落到 _send，便于判错位后决定重跑）。"""
            if not api_key:
                return {"_err": "missing upstream api key on server"}
            data = json.dumps(p, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request("https://api.dify.ai/v1/workflows/run", data=data, headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
                "User-Agent": UA,
                "Accept": "application/json",
            })
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    raw = r.read().decode("utf-8", "ignore")
                return json.loads(raw)
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "ignore")[:400]
                except Exception:
                    pass
                return {"_err": "upstream http %s" % e.code, "_detail": detail}
            except Exception as e:
                return {"_err": "upstream error: %s" % e}

        first_raw = _run_once_raw(payload)
        if "_err" in first_raw:
            detail = first_raw.get("_detail", "")
            code = 502
            m = re.match(r"upstream http (\d+)", first_raw["_err"])
            if m:
                code = int(m.group(1))
            return self._send({"ok": False, "error": first_raw["_err"], "detail": detail}, code)

        bad = _parse_bad_total(first_raw)
        if bad is None or bad <= 0:
            # 无错位（或判不出）→ 直接回第一次结果
            first_raw["_sem_reprompted"] = False
            return self._send(first_raw, 200)

        # 有错位 → 整条重跑一次
        note_error("licgen.sem", "bad_total=%s 触发整条重跑" % bad, severity="warn",
                   path="/api/dify/workflows/run")
        second_raw = _run_once_raw(payload)
        if "_err" in second_raw:
            detail = second_raw.get("_detail", "")
            code = 502
            m = re.match(r"upstream http (\d+)", second_raw["_err"])
            if m:
                code = int(m.group(1))
            return self._send({"ok": False, "error": second_raw["_err"], "detail": detail}, code)
        bad2 = _parse_bad_total(second_raw)
        second_raw["_sem_reprompted"] = True
        second_raw["_sem_bad_before"] = bad
        second_raw["_sem_bad_after"] = (bad2 if bad2 is not None else -1)
        return self._send(second_raw, 200)

    def _serve_index(self):
        """托管前端单页。Railway 单服务部署时前后端同域，API 走相对路径即可。
        密钥来自环境变量；环境变量缺失时回落到 frontend/config.local.js
        （见 cfg_local_get），以兼容没有环境变量配置面板的托管平台。"""
        try:
            with open(FRONTEND_HTML, "r", encoding="utf-8") as f:
                html = f.read()
        except Exception as e:
            return self._send({"ok": False, "error": "frontend index.html unavailable: %s" % e}, 500)
        # 注到 WB_CONFIG 而不是 WB_CFG：原 HTML 第 11 行有
        # `window.WB_CFG = (window.WB_CONFIG || {})`，会把我们的注入同步到 WB_CFG。
        # 若直接写 WB_CFG，会被这条语句覆盖成空对象（这是原代码的一个老 bug）。
        # json.dumps 保证引号/反斜杠安全，再把 < 转义成 \u003c 防止 </script> 提前闭合。
        demo_pass = self._env_key("DEMO_PASS")
        # 前端核心链路（Dify 工作流 / SiliconFlow 封面图）已改直连公网 API，
        # 直连必须带真实密钥；Railway 上密钥只存在于环境变量，故在此注入 WB_CONFIG。
        # 代价：密钥会随 HTML 下发到浏览器（F12 可见）。演示环境可接受；
        # 若要彻底隐藏，需把前端这 4 处改回「走 bridge 代理」模式。
        _envs = {
            "DEMO_PASS": demo_pass,
            "SF_API_KEY": self._env_key("SF_API_KEY"),
            "DIFY_WF_MAIN": self._env_key("DIFY_WF_MAIN"),
            "DIFY_WF_GEN": self._env_key("DIFY_WF_GEN"),
            "DIFY_WF_FACT": self._env_key("DIFY_WF_FACT"),
            "DIFY_WF_LICPREP": self._env_key("DIFY_WF_LICPREP"),
            "DIFY_WF_LICGEN": self._env_key("DIFY_WF_LICGEN"),
        }
        _pairs = ",".join("%s:%s" % (k, json.dumps(v).replace("<", "\\u003c"))
                          for k, v in _envs.items())
        cfg = 'window.WB_API_BASE="";window.WB_CONFIG={%s};' % _pairs
        inject = "<script>%s</script>" % cfg
        tag = '<script src="config.local.js"></script>'
        if tag in html:
            html = html.replace(tag, inject, 1)      # 替换掉密钥配置，改为声明同源
        elif "<head>" in html:
            html = html.replace("<head>", "<head>" + inject, 1)
        else:
            html = inject + html
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        if path == "/api/tts":
            if TTS_PAUSED:
                return self._send({"ok": False, "error": "语音合成已暂停（TTS paused）", "paused": True}, 503)
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
            if TTS_PAUSED:
                return self._send({"ok": False, "error": "语音合成已暂停（TTS paused）", "paused": True}, 503)
            # 批量：{ articles:{A2,B1,B2}, accents:["us","uk"] }
            articles = body.get("articles") or {}
            accents = tuple(body.get("accents") or ["us", "uk"])
            audio, meta = gen_tts_batch(articles, accents)
            return self._send({"ok": True, "audio": audio, "meta": meta})
        if path == "/api/vocab-check":
            # 词汇分级校验：{ articles: {A1: text, A2: text, ...}, words: {A1: [..], ...} }
            # words 为各档生词表，用于豁免（不计超纲）
            if check_vocab_batch is None:
                return self._send({"ok": False, "error": "词汇校验模块未部署（缺 evp_vocab_check.py）"}, 503)
            articles = body.get("articles") or {}
            words_map = body.get("words") or {}
            results = check_vocab_batch(articles, words_map)
            any_exceed = any(r.get("exceed") for r in results.values())
            return self._send({"ok": True, "results": results, "any_exceed": any_exceed})
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
        # ---- 代理：Dify 工作流（body.wf 决定使用哪个 app key）----
        if path == "/api/dify/workflows/run":
            wf = (body.get("wf") or "").strip().lower()
            # licprep / licgen = 授权母稿向下改写的两条独立工作流（预处理 / 向下生成）
            keymap = {"fact": "DIFY_WF_FACT", "gen": "DIFY_WF_GEN", "main": "DIFY_WF_MAIN",
                      "licprep": "DIFY_WF_LICPREP", "licgen": "DIFY_WF_LICGEN"}
            kn = keymap.get(wf)
            if not kn:
                return self._send({"ok": False, "error": "unknown wf (expect fact|gen|main|licprep|licgen)"}, 400)
            # 授权链路两条都比 fact/gen 长：图 B 要连做 3 档改写 + 压缩 + 出题，给足 300s
            pf = {"inputs": body.get("inputs") or {},
                  "response_mode": body.get("response_mode") or "blocking",
                  "user": body.get("user") or "frontend-demo"}
            # licgen（图 B）走「段落错位整条自动重跑」代理；其余仍纯透传
            if wf == "licgen":
                return self._proxy_licgen(self._env_key(kn), pf)
            return self._proxy_post(
                "https://api.dify.ai/v1/workflows/run", self._env_key(kn), pf,
                timeout=300 if wf in ("licprep", "licgen") else 180)
        # ---- 代理：SiliconFlow（LLM / 文生图），请求体原样透传 ----
        if path.startswith("/api/sf/"):
            ep = path[len("/api/sf/"):].strip("/")
            allow = {"chat/completions": "chat/completions",
                     "images/generations": "images/generations"}
            if ep not in allow:
                return self._send({"ok": False, "error": "unknown sf endpoint"}, 404)
            return self._proxy_post("https://api.siliconflow.cn/v1/" + allow[ep],
                                    self._env_key("SF_API_KEY"), body, timeout=180)
        return self._send({"ok": False, "error": "not found"}, 404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        q = dict(urllib.parse.parse_qsl(parsed.query))
        if path in ("/", "/index.html"):
            return self._serve_index()
        if path.startswith("/audio/"):
            return self._serve_audio(path[len("/audio/"):])
        if path == "/api/tags/taxonomy":
            # 标签词表单一真源：前端从这里拉，不再内置副本
            return self._send({"ok": True, **taxonomy_payload()})
        if path == "/api/proxy-health":
            # 部署自检：只回「是否已配置」，绝不回密钥值
            ks = ["SF_API_KEY", "DIFY_WF_MAIN", "DIFY_WF_GEN", "DIFY_WF_FACT",
                  "DIFY_WF_LICPREP", "DIFY_WF_LICGEN"]
            return self._send({"ok": True,
                               "configured": dict((k, bool(self._env_key(k))) for k in ks),
                               "hint": "true=已配置；false=缺环境变量，对应功能会失败"})
        if path == "/api/health":
            return self._send({"ok": True, "name": "agent-reach-bridge", "time": int(time.time()),
                               "port": PORT, "recent_errors": len(ERROR_LOG)})
        if path == "/api/trends":
            theme = q.get("theme", "all")
            sub = q.get("sub") or None
            # 支持前端指定条数（默认 TRENDS_DEFAULT_LIMIT）。上限 300 防滥用。
            try:
                _lim = int(q.get("limit") or TRENDS_DEFAULT_LIMIT)
            except Exception:
                _lim = TRENDS_DEFAULT_LIMIT
            _lim = max(10, min(300, _lim))
            t0 = int(time.time() * 1000)
            items = fetch_trends(theme, sub, _lim)
            errs = drain_errors(t0)
            # degraded=True 表示「结果不完整」：用户必须知道这不是"没有热点"，而是"有源失败"
            return self._send({"ok": True, "theme": theme, "sub": sub, "items": items,
                               "errors": errs, "degraded": _is_real_degradation(errs),
                               "filtered_video": tt_take_dropped_video(),
                               "filtered_no_text": tt_take_dropped_no_text(),
                               "filtered_stale": tt_take_dropped_stale()})
        if path == "/api/scan":
            urls = [u for u in (q.get("urls") or "").split(",")]
            try:
                limit = max(1, min(200, int(q.get("limit") or SCAN_PER_SOURCE_LIMIT)))
            except Exception:
                limit = SCAN_PER_SOURCE_LIMIT
            t0 = int(time.time() * 1000)
            items, reports = fetch_scan(urls, limit)
            errs = drain_errors(t0)
            # sources：逐源的发现报告。「哪个源抓到了 / 怎么找到的 / 为什么没抓到」
            # 必须在响应里说清 —— 只回一个 items 数组，老师只能看到内容变少却不知原因。
            return self._send({"ok": True, "items": items, "sources": reports,
                               "requested_sources": len([u for u in urls if u.strip()]),
                               "per_source_limit": limit,
                               "errors": errs, "degraded": _is_real_degradation(errs)})
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
