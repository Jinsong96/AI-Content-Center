"""两类模型调用的封装。

约定：所有模型都走 OpenAI 兼容的 /chat/completions 接口，
所以只要填 base_url + api_key + model，就能对接 OpenAI / DeepSeek / 各类中转与本地服务。

设计要点（对应框架文档 §10）：
  - 生成只调一次，绝不串联
  - 裁判只判不改，严重度由系统按 type 映射，不让模型判断业务优先级
  - 局部重写只输出被点名的那部分，不整篇重跑
"""
import json
import re
import urllib.error
import urllib.request

from . import quality

# 严重度由系统按 type 决定，不让模型替业务定优先级（这是 P0/P1 的唯一来源）
P0_TYPES = {
    "fact_added", "fact_dropped", "fact_altered",
    "card_misaligned", "answer_unsupported",
    "ambiguous_word",
}
KNOWN_TYPES = P0_TYPES | {
    "bridge_broken", "topic_word_weak", "option_unfair",
}


class LLMError(RuntimeError):
    pass


def severity_of(type_name):
    return "P0" if (type_name or "") in P0_TYPES else "P1"


# ---------------------------------------------------------------- 底层调用

def chat(cfg, system, user, timeout=300, temperature=None, no_thinking=False,
         max_tokens=None):
    """OpenAI 兼容的一次对话调用，返回 assistant 文本。

    no_thinking=True 时在请求体里加 `thinking: {"type": "disabled"}`，
    让思考型模型跳过推理直接出正文（实测同一份输入 421s → 8~20s）。
    但这个字段不是 OpenAI 官方协议，多家实现不一致：
      - 硅基 Qwen 系：认 `thinking` 与 `enable_thinking`
      - DeepSeek 官方：认 `thinking` 与 `reasoning_effort`，**不认** `enable_thinking`
    所以默认关闭、只在明确需要低延迟的调用处（见 judge）显式打开。

    max_tokens 不传时用服务商默认值，各家口径不同。裁判输出会随 findings
    条数膨胀，撞过上限被硬截断（实测 `Unterminated string` 直接判失败），
    所以裁判侧显式给足。
    """
    if not cfg or not cfg.get("base_url"):
        raise LLMError("未配置模型：请在「模型设置」里填写接口地址、密钥与模型名")
    if not cfg.get("api_key"):
        raise LLMError("未配置密钥：请在「模型设置」里填写 API Key")
    if not cfg.get("model"):
        raise LLMError("未配置模型名")

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if no_thinking:
        payload["thinking"] = {"type": "disabled"}
    if max_tokens:
        payload["max_tokens"] = max_tokens

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")[:400]
        except Exception:
            pass
        raise LLMError(f"模型接口返回 HTTP {e.code}：{detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"无法连接模型接口（{cfg['base_url']}）：{e.reason}") from e
    except TimeoutError as e:
        raise LLMError(f"模型接口超时（>{timeout}s）") from e

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"模型返回格式异常：{json.dumps(data, ensure_ascii=False)[:400]}")


def probe(cfg):
    """连通性自检：发一条极短请求，确认地址/密钥/模型名三者都对。"""
    text = chat(cfg, "You reply with one word only.", "Reply with: OK",
                timeout=60, temperature=0)
    return (text or "").strip()[:80]


def extract_json(text):
    """从模型输出里抠出 JSON：兼容 ```json 代码块与前后多余说明。

    解析用 strict=False：模型在长文本字段（original / rewritten / why）里
    经常直接写裸换行而不转义成 \\n，严格模式会抛
    「Invalid control character」把整次裁判判失败（实测踩到过）。

    多候选依次尝试：**不能只信第一个代码块**。模型偶尔会在 `original`
    这类要引用原文的字段里再写一个 ```，非贪婪匹配就会在中间断掉，
    拿到半截 JSON（实测抛过 `Expecting ',' delimiter` / `Unterminated string`）。
    所以同时准备「首个 {...} 整段」作为备选，谁能解析就用谁。
    """
    if not text or not text.strip():
        raise LLMError("模型返回为空")
    t = text.strip()

    candidates = []
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        candidates.append(m.group(1).strip())
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        candidates.append(t[i:j + 1])
    if i >= 0:
        candidates.append(t[i:])

    last_err = None
    for c in candidates:
        if not c:
            continue
        try:
            return json.loads(c, strict=False)
        except json.JSONDecodeError as e:
            last_err = e
    raise LLMError(
        f"模型返回的内容不是合法 JSON（{last_err.msg if last_err else '空'}）。"
        f"原始开头：{t[:200]}"
    ) from last_err


# ---------------------------------------------------------------- 提示词

_PROMPT_CACHE = {}


def load_prompt(name, prompts_dir):
    key = (str(prompts_dir), name)
    if key not in _PROMPT_CACHE:
        _PROMPT_CACHE[key] = (prompts_dir / name).read_text(encoding="utf-8")
    return _PROMPT_CACHE[key]


# ---------------------------------------------------------------- 来源模式

# 两种来源决定 B2+ 从哪来、用哪份提示词：
#   b2   —— 原文本身就是 B2+，只向下生成三级（原有流程，行为一字不变）
#   news —— 原文是新闻原稿，四级全部生成（B2+ 是原稿的简化版）
SOURCE_B2 = "b2"
SOURCE_NEWS = "news"


def normalize_mode(mode):
    """未知/缺省一律回落到 b2，保证老文章走原路径。"""
    return SOURCE_NEWS if mode == SOURCE_NEWS else SOURCE_B2


def prompt_name(base, mode=SOURCE_B2):
    """按来源模式选提示词文件：b2 用原名，news 用 *_news.md。

    刻意分成两份文件、而不是在一份里分叉：生成与裁判都是非确定性的，
    提示词动一个字，原模式的结果就会变。分两份才能真正做到原流程零回归。
    """
    return f"{base}_news.md" if normalize_mode(mode) == SOURCE_NEWS else f"{base}.md"


# ---------------------------------------------------------------- ① 生成

LEVELS = quality.LEVELS
GRADED = quality.GRADED

# 新闻模式一次要吐出四级正文（B2+ 还是最长的一级），输出量约为原来的 1.7 倍。
# 生成侧原先不传 max_tokens、用服务商默认值 —— 撞上就被硬截断，等于整篇白跑。
#
# ⚠️ 实测（deepseek-flash / 285 词新闻稿）：这个模型的 max_tokens **把思考 token 也算在内**，
#    且思考用量极大 —— 同一次任务思考 27016 tokens、正文只有 12462 字符。
#    设成 16384 时思考还没跑完就被截断（finish_reason=length），正文输出 0 字符，
#    直接报「模型返回为空」。所以这个值必须**远大于正文长度**，而不是「够正文就行」。
#    换模型后要重新标定：用真实原稿跑一次，看 usage 里的 reasoning_tokens 再定。
# 只给 news 加限，b2 保持不传，确保原流程的请求体逐字不变。
NEWS_MAX_TOKENS = 65536


def build_generate_input(original_text, mode=SOURCE_B2):
    if normalize_mode(mode) == SOURCE_NEWS:
        return ("这是一篇英文新闻原稿，请按既定要求写出 B2+、B1、A2、A1- 四级内容，"
                "并为四个级别各出 3 道题。\n\n===== 新闻原稿开始 =====\n"
                f"{original_text.strip()}\n===== 新闻原稿结束 =====")
    return ("这是一篇英文原文，请按既定要求把它降级改写成 A1-、A2、B1 三级，"
            "并为四个级别各出 3 道题。\n\n===== 原文开始 =====\n"
            f"{original_text.strip()}\n===== 原文结束 =====")


def normalize_generated(data, mode=SOURCE_B2):
    """把模型产出的 JSON 规整成系统内部结构，并做基本结构校验。"""
    if not isinstance(data, dict):
        raise LLMError("生成结果不是 JSON 对象")

    mode = normalize_mode(mode)
    levels = data.get("levels") or {}
    for lv in GRADED:
        node = levels.get(lv) or {}
        if not node.get("cards"):
            raise LLMError(f"生成结果缺少 {lv} 的 cards")

    # 校验顺序刻意与改动前保持一致（b2：GRADED → B2+ 题 → b2_card_starts），
    # 免得原模式下报出的错误信息发生变化。
    if mode == SOURCE_NEWS and not (levels.get("B2+") or {}).get("cards"):
        raise LLMError("生成结果缺少 B2+ 的 cards")
    if not (levels.get("B2+") or {}).get("questions"):
        raise LLMError("生成结果缺少 B2+ 的 questions")
    if mode != SOURCE_NEWS and not data.get("b2_card_starts"):
        raise LLMError("生成结果缺少 b2_card_starts（B2+ 每张卡开头的四个词）")

    out = {
        "title_en": data.get("title_en") or "",
        "title_zh": data.get("title_zh") or "",
        "topic_words": data.get("topic_words") or [],
        "b2_card_starts": data.get("b2_card_starts") or [],
        "levels": {},
    }
    if mode == SOURCE_NEWS:
        out["source_level"] = (data.get("source_level") or "").strip()
    for lv in LEVELS:
        node = levels.get(lv) or {}
        questions = []
        for q in (node.get("questions") or []):
            questions.append({
                "q": q.get("q", ""),
                "options": (q.get("options") or [])[:4],
                "answer": (q.get("answer") or "").strip().upper()[:1],
                "explanation": q.get("explanation", ""),
            })
        # b2 模式下 B2+ 的正文由原文切分得到，不接受模型输出；
        # news 模式下 B2+ 就是模型产物，必须保留。
        keep_cards = lv in GRADED or mode == SOURCE_NEWS
        out["levels"][lv] = {
            "cards": list(node.get("cards") or []) if keep_cards else [],
            "questions": questions,
        }
    return out


def generate(original_text, gen_cfg, prompts_dir, mode=SOURCE_B2):
    """调用模型 A 生成内容。返回规整后的结构。"""
    mode = normalize_mode(mode)
    system = load_prompt(prompt_name("generate", mode), prompts_dir)
    user = build_generate_input(original_text, mode)
    raw = chat(gen_cfg, system, user, timeout=600,
               max_tokens=NEWS_MAX_TOKENS if mode == SOURCE_NEWS else None)
    return normalize_generated(extract_json(raw), mode)


# ---------------------------------------------------------------- ② 裁判

JUDGE_LABELS = {
    "zh": {"card": "卡{n}", "questions": "===== 题目 =====",
           "options": "选项", "answer": "答案", "explanation": "解析", "missing": "（缺失）"},
    "en": {"card": "Card {n}", "questions": "===== Questions =====",
           "options": "Options", "answer": "Answer", "explanation": "Explanation",
           "missing": "(missing)"},
}

# 裁判输出的自然语言部分（why / conclusion）跟随界面语言，
# 否则英文界面上会出现中文解释，对英文读者等于不可用。
JUDGE_LANG_NOTE = {
    "en": ("\n\n===== Output language =====\n"
           "Write every human-readable string in your JSON output "
           "(`why`, `conclusion`) in **English**. "
           "Quotations of the article text stay in the article's original language."),
}


def build_judge_input(article, cards, lang="zh", mode=SOURCE_B2):
    """按卡对齐组装裁判输入：第 N 张卡的四个级别并排，之后再给题目。

    news 模式下 B2+ 也是产物、不再等于原文，「事实保真」就失去基准，
    所以把新闻原稿一并附在开头（b2 模式不附，输入逐字不变）。
    """
    L = JUDGE_LABELS.get(lang) or JUDGE_LABELS["zh"]
    lines = []
    if normalize_mode(mode) == SOURCE_NEWS:
        lines.append("===== 新闻原稿 =====")
        lines.append((article.get("original_text") or "").strip())
        lines.append("")
    n = len(cards.get("B2+") or [])
    for i in range(n):
        lines.append(f"===== {L['card'].format(n=i + 1)} =====")
        for lv in LEVELS:
            arr = cards.get(lv) or []
            body = arr[i] if i < len(arr) else L["missing"]
            lines.append(f"[{lv}] {body}")
        lines.append("")

    lines.append(L["questions"])
    for lv in LEVELS:
        qs = (article.get("levels", {}).get(lv) or {}).get("questions") or []
        for qi, q in enumerate(qs, 1):
            opts = " / ".join(f"{'ABCD'[k]}. {o}" for k, o in enumerate(q.get("options") or []))
            lines.append(f"[{lv} Q{qi}] {q.get('q', '')}")
            lines.append(f"    {L['options']}: {opts}")
            lines.append(f"    {L['answer']}: {q.get('answer', '')}")
            lines.append(f"    {L['explanation']}: {q.get('explanation', '')}")
    return "\n".join(lines)


def normalize_findings(raw):
    """规整裁判输出：补 severity，过滤未知 type，统一卡号/题号字段。"""
    out = []
    for f in (raw.get("findings") or []):
        type_name = (f.get("type") or "").strip()
        level = (f.get("level") or "").strip()
        if level not in LEVELS:
            level = "A1-" if level == "" else level
        card = f.get("card")
        question = f.get("question")
        try:
            card = int(card) if card not in (None, "", "null") else None
        except (TypeError, ValueError):
            card = None
        try:
            question = int(question) if question not in (None, "", "null") else None
        except (TypeError, ValueError):
            question = None
        out.append({
            "level": level,
            "card": card,
            "question": question,
            "type": type_name or "unclassified",
            "known_type": type_name in KNOWN_TYPES,
            "severity": severity_of(type_name),
            "original": (f.get("original") or "").strip(),
            "rewritten": (f.get("rewritten") or "").strip(),
            "why": (f.get("why") or "").strip(),
        })
    return out


def judge(article, cards, judge_cfg, prompts_dir, lang="zh", mode=SOURCE_B2):
    """调用模型 B 做语义裁判，只判不改。lang 决定裁判输出的自然语言。

    裁判关思考（no_thinking=True）：裁判做的是「逐卡对照 + 按清单报问题」，
    属于比对而非推演；开思考时 99% 的输出 token 花在推理上（实测 421s/次），
    而正文只有 59 字符。关掉后同一份输入 8~20s 完成，且抓到了开思考漏掉的 P0。
    ⚠️ 代价：关思考后 JSON 语法错误率上升（已加重试兜底），判断质量需人工复核。
    要回退开思考，删掉下面的 no_thinking=True 即可。

    固定 temperature=0：裁判是「判定」不是「创作」，必须可复现。此前不传
    temperature 时，同一篇文章、同一提示词、同一模型会随机跑出「1 条 P0」
    与「0 条 P0」两个相反结论，测出来的分数没有意义。
    （注：加了 temperature=0 后仍观察到 0/1/2/9 条的抖动，服务商侧本身有非确定性。）
    """
    mode = normalize_mode(mode)
    system = load_prompt(prompt_name("judge", mode), prompts_dir) + JUDGE_LANG_NOTE.get(lang, "")
    user = build_judge_input(article, cards, lang, mode)

    # 裁判输出是自由文本，偶发 JSON 语法错误（漏逗号 / 被截断 / 短路）。
    # 关思考后概率明显上升 —— 但单次只要 2–20s，重试一次的成本
    # 远低于整篇生产白跑（实测一次失败 = 350–660s 全废）。
    data = None
    last_err = None
    for _ in range(2):
        raw = chat(judge_cfg, system, user, timeout=600,
                   temperature=0, no_thinking=True, max_tokens=8192)
        try:
            data = extract_json(raw)
            break
        except LLMError as e:
            last_err = e
    if data is None:
        raise last_err

    findings = normalize_findings(data)
    return {
        "findings": findings,
        "conclusion": data.get("conclusion") or "",
        "p0_count": sum(1 for f in findings if f["severity"] == "P0"),
        "p1_count": sum(1 for f in findings if f["severity"] == "P1"),
    }


# ---------------------------------------------------------------- ③ 局部重写

REWRITE_NOTE = """
===== 本次只做局部重写 =====
不要重新输出整篇。只输出需要修改的那一部分的 JSON 片段，格式如下：

```json
{
  "title_en": "若本次不涉及标题则省略该字段",
  "cards": { "A2": [{"index": 3, "text": "重写后的第 3 张卡正文，不带编号"}] },
  "questions": { "B1": [{"index": 2, "q": "题干", "options": ["","","",""], "answer": "B", "explanation": "解析"}] }
}
```

规则：
- `index` 从 1 开始，表示第几张卡 / 第几题。
- 只包含需要改动的级别与条目，其余一律省略。
- 重写必须与其他级别、与原文保持一致；不得改变主体、立场与事实。
- 如果改动会影响其他卡片（例如某句话是下一张卡的铺垫），同时把它们列出来。
"""


def build_rewrite_input(article, cards, targets, problems, mode=SOURCE_B2):
    """targets: [{"level": "A2", "card": 3}] 或 [{"level":"B1","question":2}]
    problems: 触发重写的问题清单（脚本质检项或裁判发现）"""
    if normalize_mode(mode) == SOURCE_NEWS:
        lines = ["===== 新闻原稿（保真基准）=====", article.get("original_text", "").strip(), ""]
    else:
        lines = ["===== 原文（B2+）=====", article.get("original_text", "").strip(), ""]
    lines.append("===== 当前四级内容 =====")
    n = len(cards.get("B2+") or [])
    for i in range(n):
        lines.append(f"--- 卡{i + 1} ---")
        for lv in LEVELS:
            arr = cards.get(lv) or []
            lines.append(f"[{lv}] {arr[i] if i < len(arr) else '（缺失）'}")
    lines.append("")
    lines.append("===== 题目 =====")
    for lv in LEVELS:
        for qi, q in enumerate((article.get("levels", {}).get(lv) or {}).get("questions") or [], 1):
            lines.append(f"[{lv} Q{qi}] {q.get('q','')} | 选项 {' / '.join(q.get('options') or [])} "
                         f"| 答案 {q.get('answer','')} | 解析 {q.get('explanation','')}")

    lines.append("")
    lines.append("===== 本次要修的地方 =====")
    for t in targets:
        if t.get("card"):
            lines.append(f"- {t['level']} 第 {t['card']} 张卡")
        elif t.get("question"):
            lines.append(f"- {t['level']} 第 {t['question']} 题")
        else:
            lines.append(f"- {t['level']} 全部卡片（整级重写）")
    lines.append("")
    lines.append("===== 发现的问题 =====")
    for p in problems:
        lines.append(f"- [{p.get('level','')}] "
                     f"{'卡' + str(p['card']) if p.get('card') else ('题' + str(p['question'])) if p.get('question') else '全篇'}"
                     f"：{p.get('message') or p.get('why') or ''}")
    return "\n".join(lines)


def apply_rewrite(article, patch, mode=SOURCE_B2):
    """把局部重写结果合并回 article。

    news 模式下 B2+ 也是产物，必须允许被修 —— 原先写死只在 GRADED 里改，
    裁判报了 B2+ 的问题会自动修复静默失效（说改了，其实没写进去）。
    """
    allow_b2 = normalize_mode(mode) == SOURCE_NEWS
    changed = []
    if patch.get("title_en") or patch.get("title_zh"):
        if patch.get("title_en"):
            article["title_en"] = patch["title_en"]
        if patch.get("title_zh"):
            article["title_zh"] = patch["title_zh"]
        changed.append("title")

    for lv, items in (patch.get("cards") or {}).items():
        if lv not in LEVELS:
            continue
        if lv not in GRADED and not allow_b2:
            continue
        arr = (article.get("levels") or {}).get(lv, {}).get("cards")
        if arr is None:
            continue
        for item in (items or []):
            idx = int(item.get("index") or 0) - 1
            if 0 <= idx < len(arr):
                before = arr[idx]
                arr[idx] = (item.get("text") or "").strip()
                changed.append({"level": lv, "card": idx + 1, "before": before, "after": arr[idx]})

    for lv, items in (patch.get("questions") or {}).items():
        if lv not in LEVELS:
            continue
        arr = article["levels"][lv]["questions"]
        for item in (items or []):
            idx = int(item.get("index") or 0) - 1
            if 0 <= idx < len(arr):
                before = dict(arr[idx])
                for key in ("q", "options", "answer", "explanation"):
                    if key in item and item[key] not in (None, ""):
                        arr[idx][key] = item[key]
                changed.append({"level": lv, "question": idx + 1,
                                "before": before, "after": dict(arr[idx])})
    return changed


def rewrite(article, cards, targets, problems, gen_cfg, prompts_dir, mode=SOURCE_B2):
    """调用模型 A 做局部重写，返回 (改动列表, 原始 patch)。"""
    mode = normalize_mode(mode)
    system = load_prompt(prompt_name("generate", mode), prompts_dir) + "\n" + REWRITE_NOTE
    user = build_rewrite_input(article, cards, targets, problems, mode)
    raw = chat(gen_cfg, system, user, timeout=600)
    patch = extract_json(raw)
    changed = apply_rewrite(article, patch, mode)
    return changed, patch
