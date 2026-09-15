# -*- coding: utf-8 -*-
"""ReadPal 12 子档分级标准 —— Dify 工作流重建
读 <BK>/{fact,gen}.graph.json → 输出 <BK>/{fact,gen}.new.json（BK 默认 = 仓库 dify_graphs/）
"""
import json, copy, os, re

# 图备份目录：默认为仓库内 dify_graphs/（可用环境变量 DIFY_BACKUP_DIR 覆盖）。
#   gen.graph.json / fact.graph.json = **原始备份**（图的输入，别删）
#   gen.new.json  / fact.new.json    = 生成结果（推送给 Dify 的就是这两个）
_HERE = os.path.dirname(os.path.abspath(__file__))
BK = os.path.abspath(os.environ.get('DIFY_BACKUP_DIR') or os.path.join(_HERE, '..', 'dify_graphs'))

# ============================================================================
# 12 子档规格表（唯一真源，对应飞书《APP阅读级别量化表》）
# ============================================================================
LEVELS = [
    dict(k="A1", d="A1", big="A1", wc=(60, 160),    lex=(-1000, 400),  msl=(5, 10),  paras=7,
         genre="记叙 90–100% / 说明 0–10%", quiz="语言 1–2 / 文本 1–2 / 逻辑 0–1",
         grammar="一般现在时、be 动词、there be → 现在进行时、can / like to、because / so → 一般过去时（规则动词 + 约 20 个高频不规则）；连接词只用 and / but",
         vocab="最高频 800 词以内，只用具象名词",
         topic="读者五米之内的世界（家人、宠物、天气、上学路上）→ 动物、身体、四季、节日 →「我昨天遇到了什么」"),
    dict(k="A2", d="A2", big="A2", wc=(160, 300),   lex=(400, 650),    msl=(10, 14), paras=7,
         genre="记叙 45–60% / 说明 30–45% / 应用文 10%", quiz="语言 1 / 文本 1–2 / 逻辑 0–1",
         grammar="比较级、be going to / will、定语从句（who / which）→ 现在完成时、情态动词、when / if 状语从句 → 初步被动语态、过去进行时",
         vocab="最高频 1500–1800 词，可含常见具象名词",
         topic="兴趣爱好、旅行出行、购物 → 具象科普（动物为什么冬眠）→ 别国生活、中外对比"),
    dict(k="B1", d="B1", big="B1", wc=(300, 550),   lex=(650, 880),    msl=(13, 18), paras=7,
         genre="说明议论 55% / 记叙 30% / 应用说明 15%（议论比重升至 25%）", quiz="语言 0–1 / 文本 1 / 逻辑 1 / 认知 0–1",
         grammar="被动语态、宾语从句、动名词不定式 → 条件句 I / II、现在完成进行时、非限定性定语从句 → 过去完成时、报道性动词、分词短语作状语",
         vocab="最高频 2000–3000 词，出现常见抽象名词与轻学术词",
         topic="科技产品、环境可持续、学习心理 → 社会现象、创业商业、健康科学 → 人物故事、事件复盘、文化对比"),
    dict(k="B2", d="B2", big="B2", wc=(550, 700),   lex=(880, 1000),   msl=(18, 21), paras=7,
         genre="新闻特写与说明性长文为主，议论约 30%", quiz="文本 1 / 逻辑 2",
         grammar="名词化密度上升、hedging（tends to / it is likely that）、倒装、多重从句嵌套",
         vocab="AWL 学术词密度 4–6%",
         topic="主流媒体的解释性报道与商业案例——AI 与就业、气候政策、公司兴衰、消费行为、健康科学"),
]
LMAP = {L['k']: L for L in LEVELS}
DISPLAY = {L['k']: L['d'] for L in LEVELS}
BIG = {L['k']: L['big'] for L in LEVELS}
GROUPS = [("A1", ["A1"]),
          ("A2", ["A2"]),
          ("B1", ["B1"]),
          ("B2", ["B2"])]


def lex_range(L):
    lo, hi = L['lex']
    return ("BR–%dL" % hi) if lo <= -1000 else ("%d–%dL" % (lo, hi))


# ============================================================================
# 1) GEN 工作流
# ============================================================================
GEN_TITLE_SYS = """你是英语分级阅读编辑。根据主题摘要与切入角度，为这一系列分级文章拟一个英文标题。

要求：
1. 4–9 个英文单词。
2. 只用常见词——同一个标题要同时供 A1（60 词入门）与 B2（700 词进阶）使用，必须让 A1 的学习者也能看懂。
3. 可用一个冒号做成「主标题: 副标题」。
4. 具体、有信息量，不要写成 "The Importance of ..." 这类空泛句式。
5. 不要引号、不要句末句号、不要 Markdown 标题符号、不要换行。

只输出标题本身，不要输出任何其他文字。"""

GEN_TITLE_USER = """主题：{{#nodeClean.summary#}}
切入角度：{{#nodeClean.angle#}}

请给出英文标题。"""


def ruler(L):
    """把「全篇词数 + 平均句长」换算成模型可直接执行的「每段多少词 / 多少句」标尺。
    这是本工作流里对达标率影响最大的一条指令：模型无法凭感觉控全局字数，
    但能精确控制每段几句。"""
    n = L['paras']
    lo, hi = L['wc']
    slo, shi = L['msl']
    p_lo, p_hi = round(lo / n), round(hi / n)
    s_mid = (slo + shi) / 2
    k = max(2, round(((p_lo + p_hi) / 2) / s_mid))
    return "全篇 %d 段；每段约 %d–%d 词（约 %d 句，平均句长约 %d 词）" % (n, p_lo, p_hi, k, round(s_mid))


def gen_sys(big, keys):
    L = LMAP[keys[0]]
    k = keys[0]
    d = DISPLAY[k]
    n = L['paras']
    wmid = (L['wc'][0] + L['wc'][1]) // 2
    spec = ("- %s：正文 **目标 %d 词**（硬区间 %d–%d；低于下限或超过上限都判不合格）\n"
            "    平均句长 %d–%d 词；蓝思 %s\n"
            "    写作标尺：%s\n    词汇层级：%s\n    语法范围：%s\n    体裁 %s；主题半径：%s"
            % (d, wmid, L['wc'][0], L['wc'][1], L['msl'][0], L['msl'][1], lex_range(L),
               ruler(L), L['vocab'], L['grammar'], L['genre'], L['topic']))
    extra = ""
    if big == "B2":
        extra = ("\n- 本档是中高级档，篇幅必须双向达标：550–700 词。既不要写到 500 词就收尾，也不要超过 750 词。"
                 "\n- ⚠️ 实测本档容易整体偏短。把区间折算成每段硬指标（固定 7 段）：**每段约 79–100 词**，"
                 "每一段都按这个下限起笔，写不到就不许进入下一段。"
                 "\n- 平均句长 18–21 词/句，靠名词化、hedging、多重从句提难度，**不要靠无限加长单句**（超过 26 词会冲高蓝思）。")
    elif big == "B1":
        extra = ("\n- 本档是中级档：篇幅 300–550 词，每段约 43–79 词（固定 7 段）。"
                 "\n- 最容易失分的是「写得像 A2」：平均句长必须落在 13–18 词/句，"
                 "用足中级句法与抽象名词（method / issue / benefit / pressure 一类）。"
                 "\n- 反向也要防：句长别超过 22 词（蓝思会冲到 880L 上限之外）。")
    elif big == "A2":
        extra = ("\n- 本档是初级档：句子不冗长，但平均句长必须 10–14 词/句，低于 9 词判不合格。"
                 "\n- 字数靠「句数够多」达标，每段约 23–43 词（固定 7 段）。"
                 "\n- 只能依据「素材大意」写，正文不得出现数字、百分比、年份、机构名、人名、地名。")
    elif big == "A1":
        extra = ("\n- 本档是入门档：句子必须短（5–10 词/句），单句不超过 12 词。"
                 "\n- 全篇 60–160 词、固定 7 段，每段约 9–23 词。"
                 "\n- 只能依据「素材大意」写，正文不得出现数字、百分比、年份、机构名、人名、地名。")
    if big in ("A1", "A2"):
        mapkey = "gist_map"
        map_sec = ("【大意引用标注（必须输出）】\n"
                   "上方「素材大意」按 1 开始编号。你必须在 JSON 中额外输出 gist_map，"
                   "标明每一段依据了哪几条大意。\n"
                   "- 内层数组对应 %d 段，长度必须等于 %d\n"
                   "- 元素是该段所依据的大意条号（1-based，按升序排列）\n"
                   "- 每段至少引用 1 条；7 条大意应尽量都被讲到（允许多对一）") % (n, n)
    else:
        mapkey = "fact_map"
        map_sec = ("【事实卡引用标注（必须输出）】\n"
                   "上方「素材事实」按 1 开始编号。你必须在 JSON 中额外输出 fact_map，"
                   "标明每一段依据了哪几张事实卡。\n"
                   "- 内层数组对应 %d 段，长度必须等于 %d\n"
                   "- 元素是该段所依据的事实卡编号（1-based，按升序排列）\n"
                   "- 每段至少引用 1 张卡；尽量让全部事实卡都被至少一段引用") % (n, n)
    return """你是英语分级阅读作者。基于给定素材，生成 %s 档（%s）的文章，共 %d 段。

【本档硬性规格】（逐项达标，任一项显著偏离即视为不合格）
%s%s

【必须自查的三条硬指标（篇幅是分级的一半，与语言难度同等重要）】
① **正文字数**：以「目标 %d 词」为靶心，**必须落在硬区间 %d–%d**——低于下限或超过上限都不合格。
  **先按「写作标尺」把每一段铺满，再数总词数；不够就补，超了才删。宁可靠近区间中点，也不要低于下限。**
② **每段句数**：按写作标尺给出的「约 M 句」写足。
③ **平均句长 = 正文总词数 ÷ 句子数**，必须落在 %d–%d 词区间内。
写完请自己数一遍总词数、句子数与段数，与规格核对。

【素材不足时怎么办（关键，直接决定达标率）】
- 若素材不足以支撑本档下限词数，**优先保证下限**：允许做**不引入新数字、新人名、新机构、新事件的合理背景扩写**。
- **绝对不得编造**具体的百分比、年份、机构名、人名、地名。
- **不允许以「怕编造」为理由把文章写短**：写不到下限同样判不合格。

【素材过多时怎么办】
- 素材很长时，本档只取与认知半径匹配的要点，其余细节宁可不写，也必须守住本档上限。

【段落总纲】
- 这是供英语学习者阅读的完整文章，不是摘要。围绕素材充分展开：补充背景、成因、过程、细节、影响。
- 本文固定 %d 段。

【核心要求：段落一一对应（最重要）】
1. 本文必须恰好 %d 段。
2. 段落顺序必须严格遵循「素材大意」的顺序：
   第 1 段 引入（是什么 / 在哪 / 何时）
   第 2 至 %d 段 展开（核心内容、背景、细节、例子，按大意条自然分段）
   第 %d 段 收尾（意义 / 现状 / 影响）
3. 每一段只讲与该段对应的大意条，不要跨段混讲——这样读者切换难度档位时，第 i 段的内容大意保持不变，只是语言难度不同。
4. 生词表：3–5 个词，格式 "word — 中文释义"。
5. **不要输出标题**，不要在 JSON 里出现 title 字段。

%s

【输出格式：严格 JSON，只输出一个 JSON 对象，不要 markdown 代码块、不要解释、不要多余文字】
{"%s":["段1",...,"段%d"],"words":{"%s":["word — 中文释义"]},"%s":{"%s":[[1,2],...,[%d]]}}

【JSON 键名规则】键名用 %s（即 %s）。""" % (
        big, d, n,
        spec, extra,
        wmid, L['wc'][0], L['wc'][1],
        L['msl'][0], L['msl'][1],
        n, n, n - 1, n,
        map_sec,
        k, n, k,
        mapkey, k, n,
        k, d)



def gen_user(big, keys):
    if big in ("A1", "A2"):
        # 低档只吃「大意拍」：7 条去数字、去专名的语义骨架。
        # 目的是让 A1/A2 与高档共享同一条主线（跨档段落级对齐、动态换档无缝），
        # 同时天然规避低档文章里出现数字/专名。
        src = ("素材大意（本档**只能依据下面这 7 条大意来写**，不得引入大意之外的信息）：\n"
               "{{#nodeClean.gist#}}\n\n"
               "⚠️ 本档是入门档：**正文里不得出现任何数字、百分比、年份、机构名、人名、地名**——\n"
               "这些属于细节层，由更高档位承载。请把它们写成具象的日常表达。\n")
    else:
        src = "素材事实：\n{{#nodeClean.facts_text#}}\n"
    return """标题（必须原样使用，不要另拟）：{{#nodeTitle.text#}}
主题：{{#nodeClean.summary#}}
""" + src + """
切入角度：{{#nodeClean.angle#}}

写作风格：{{#nodeStyle.style_instruction#}}

请生成 %s 档的文章（共 7 段，段落严格对应素材大意顺序），输出严格 JSON。""" % DISPLAY[keys[0]]



GEN_QUIZ_SYS = """You are an English reading assessment designer. For EACH of the 4 levels below, write exactly 3 exercises based ONLY on that level's article.

[Question types - four categories]
- "language": tests vocabulary / grammar itself - word meaning in context, reference (what does "it" refer to), guessing meaning from context.
- "text": tests information in the passage - locating details, sequence, main idea, cross-paragraph integration.
- "logic": tests reasoning and argument structure - single-step cause/effect, one-step inference, telling a claim apart from its support.
- "cognitive": tests stance and hidden premises - the author's attitude, mapping where each side stands, implicit assumptions. It must NOT ask "what does the passage say".

[Mandatory type mix per level - exactly 3 questions each]
A1: language 1-2, text 1-2, logic 0-1   (logic = single-step cause/effect explicitly signposted; NO cognitive)
A2: language 1, text 1-2, logic 0-1     (logic requires one inference step - answer NOT stated verbatim; NO cognitive)
B1: language 0-1, text 1, logic 1, cognitive 0-1  (cognitive appears - ask about the author's attitude)
B2: text 1, logic 2                       (logic targets argument structure - which is the claim, which is support)

[Difficulty scaling - the question wording must match the level's own article]
- A1 / A2: very short stems, high-frequency words, distractors clearly wrong.
- B1: stems may contain one subordinate clause; distractors moderately confusing.
- B2: may rely on synonym replacement, hedging and inference; distractors need careful discrimination.

[Explanation - mandatory for every question]
"explain" must be written in CHINESE, 1-3 sentences, saying why the key is correct AND why the single most tempting distractor is wrong.

[Output format: STRICT JSON only - one JSON object, no markdown code block, no explanation, no extra text]
{"levels":{"A1":[{"type":"language","q":"...","options":["A","B","C","D"],"answer":0,"explain":"..."},{"type":"text","q":"...","options":["A","B","C","D"],"answer":1,"explain":"..."},{"type":"language","q":"...","options":["A","B","C","D"],"answer":2,"explain":"..."}],"A2":[...],"B1":[...],"B2":[...]}}

Rules for the JSON:
- "answer" is the zero-based index of the correct option.
- "type" must be exactly one of: language, text, logic, cognitive.
- Question stems and options must be entirely in ENGLISH. Only "explain" is in Chinese.
- All 4 level keys must be present (A1, A2, B1, B2), each with exactly 3 questions in the mandated type mix."""
GEN_QUIZ_USER = """The 4 graded articles follow. Each block starts with === LEVEL_KEY ===.

{{#nodeAgg.quiz_source#}}

Write exactly 3 exercises for each of the 4 levels, in the mandated type mix. Output strict JSON only."""


# ⑨ 大意复核（新增节点）
# 目的：判「主线有没有走样」，与 ⑦ 的机械校验（判「规格达没达标」）是**粒度不同的两道闸**，
#       不能互相替代。机械校验拦不住「方向讲反」「主体张冠李戴」「凭空加结论」。
# 设计取舍：只加 1 个 LLM 节点、把结论以严格 JSON 文本输出（与 quiz_json 同一模式），
#          不在工作流内部做失败重试回路 —— 重试由后端依据 gist_check 的 pass 字段触发整条重跑。
GEN_GIST_SYS = """你是英语分级阅读流水线上的「主线一致性审核员」。上游已抽出一份**素材大意基准**（若干条，已去掉数字与专名），并把同一条素材改写成 4 个难度档位的文章。你的任务：逐档核对，判断这一档的正文**是否仍在讲同一件事、同一条主线**。

你判的是「主线有没有走样」，**不是**「细节全不全」：
- 低档（A1/A2）本来就只讲大意、更简略 —— **简略不算走样**。
- 高档（B1/B2）细节更丰富 —— **更详细也不算走样**。
- 只有下列情况才算走样：把主线换成了另一件事；把因果或方向讲反（增加写成减少、上升写成下降、有利写成有害）；主体张冠李戴（国家、机构、人物错位）；凭空增加了素材里不存在的新事件或新结论。

输出严格 JSON（只输出 JSON，不要 markdown 代码块，不要任何解释）：
{"levels":[{"level":"A1","main_ok":true,"covered":[1,2,3,4,5,6,7],"drift":""}],"pass":true,"fail_levels":"","summary":"一句话结论"}

字段说明：
- `levels`：4 个档位各一条，顺序必须是 A1 A2 B1 B2。
- `covered`：该档正文实际覆盖到的大意基准条号（1-based，升序）。低档覆盖不全**不算失败**，但必须如实报告。
- `main_ok`：主线是否一致，true / false。
- `drift`：仅当 `main_ok` 为 false 时填写，用中文说明「哪一条主线偏了、偏成什么」，40 字以内；正常时留空字符串。
- `pass`：4 档 `main_ok` 全为 true 时才为 true。
- `fail_levels`：`main_ok` 为 false 的档位，用逗号连接（如 "B1,B2"）；全过则为空字符串。
- `summary`：一句话中文结论，说明整体是否一致、低档覆盖情况如何。"""
GEN_GIST_USER = """【素材大意基准】
{{#nodeClean.gist#}}

【4 档文章的正文段落】（JSON：键为档位，值为该档的段落数组）
{{#nodeAgg.paras_json#}}

请逐档核对主线一致性，输出严格 JSON。"""


GEN_CLEAN_CODE = r"""function main({ summary, facts_text, angle, level, gist }) {
  const normLevel = (v) => {
    let s = String(v || '').trim().toUpperCase().replace(/\s+/g, '').replace(/[_-]/g, '.').replace(/档/g, '');
    s = s.replace(/^B2PLUS/, 'B2').replace(/^B2P/, 'B2');
    const AL = {
      'A1':'A1','A2':'A2','B1':'B1','B2':'B2',
      'A1.1':'A1','A1.2':'A1','A1.3':'A1',
      'A2.1':'A2','A2.2':'A2','A2.3':'A2',
      'B1.1':'B1','B1.2':'B1','B1.3':'B1',
      'B2.1':'B2','B2.2':'B2','B2.3':'B2',
      'B2+.1':'B2','B2+.2':'B2','B2+.3':'B2',
      'C1':'B2'
    };
    if (AL[s]) return AL[s];
    const m = s.match(/^(A1|A2|B1|B2\+?)/);
    if (m) { return m[1] === 'B2+' ? 'B2' : m[1]; }
    return 'B1';
  };
  const lv = normLevel(level);
  const big = lv;
  return {
    summary: String(summary || 'x'),
    facts_text: String(facts_text || ''),
    /* gist 为空时退回 facts_text：GEN 可能被单独调用（不经抽取链路）而没传 gist，
       此时低档生成不应拿不到素材，宁可退回细节事实也不要产出空文。 */
    gist: String(gist || '').trim() || String(facts_text || ''),
    level: lv,
    level_big: big,
    angle: String(angle || ''),
    sensitive: 'S3 / ok', sens_level: 'S3', sens_action: 'ok', sens_reason: ''
  };
}"""


GEN_AGG_CODE = r"""function main({ t_a1, t_a2, t_b1, t_b2p, title_in, fact_json, clean_level, clean_level_big, clean_angle, clean_sensitive }) {
  const strip = (t) => String(t || '').replace(/<think>[\s\S]*?<\/think>/g, '').trim();
  const parseJSON = (t) => {
    const s = strip(t).replace(/```json|```/g, '');
    const m = s.match(/\{[\s\S]*\}/);
    if (!m) return {};
    try { return JSON.parse(m[0]); } catch (e) {
      /* 模型偶发输出尾逗号（实测 A1 组每段数组末尾带 ","），严格 JSON.parse 直接抛错，
         会让整组被静默降级成「0 段」（raw_missing 里只留一个 A1）。这里做一次容错重试。 */
      try { return JSON.parse(m[0].replace(/,(\s*[\]}])/g, '$1')); } catch (e2) { return {}; }
    }
  };
  const DISPLAY = { A1:'A1', A2:'A2', B1:'B1', B2:'B2' };
  const BIGOF = { A1:'A1', A2:'A2', B1:'B1', B2:'B2' };
  /* 规格段数（与 Python 侧 LEVELS[*]['paras'] 保持一致）。
     下游契约要求「组内三档段落级一一对应」，所以段数是硬结构，必须在这里兜住。 */
  const PARAS = { A1:7, A2:7, B1:7, B2:7 };
  /* 生词表行形如 "flood — 洪水" / "runoff: 径流"，单行、短、以「英文词 + 分隔符 + 中文」开头。
     实测模型偶有把生词表当成正文段落追加到数组末尾（B1 三档段数 11 / 规格 6），
     一旦透传就会污染 paras_json / para_count / levels_meta，必须在这里剔除。 */
  const isVocabLine = (p) => {
    const s = String(p || '').trim();
    if (!s || s.length > 60) return false;
    if (/[\n\r]/.test(s)) return false;
    return /^[A-Za-z][A-Za-z' \-\.]*\s*[:：—–-]{1,2}\s*[\u4e00-\u9fff]/.test(s);
  };
  /* 兜底网：正文段落不应出现成串中文（阈值与校验节点一致）。
     放它进来只会让「语言纯净度」判 fail，所以在聚合层就先挡掉，并留下告警。 */
  const isDirtyPara = (p) => ((String(p || '').match(/[\u4e00-\u9fff]/g) || []).length > 5);
  const GROUP_KEYS = [['A1'],['A2'],['B1'],['B2']];
  const RAW = { A1: t_a1, A2: t_a2, B1: t_b1, B2: t_b2p };
  const ALL = [];
  GROUP_KEYS.forEach((g) => g.forEach((k) => ALL.push(k)));

  const paras = {}, words = {}, factMaps = {}, raw_missing = [], para_warn = [];
  GROUP_KEYS.forEach((g) => {
    const o = parseJSON(RAW[g[0]]);
    if (!Object.keys(o).length) raw_missing.push(DISPLAY[g[0]].slice(0, 2));
    g.forEach((k) => {
      const raw = (Array.isArray(o[k]) ? o[k] : []).map((p) => String(p || '').trim()).filter(Boolean);
      /* 捞出被误当段落的生词表行——它本来该在 o.words[k] 里 */
      const salvaged = raw.filter(isVocabLine);
      /* 含中文的「正文段」单独计数：整篇中文是独立的失败模式（模型偶发，JSON 与段数都合法），
         与「生词表混进正文」成因不同、处置也不同，告警里必须能区分，否则人工审核会误判。 */
      const dirtyParas = raw.filter((p) => !isVocabLine(p) && isDirtyPara(p));
      const dirty = dirtyParas.length;
      let arr = raw.filter((p) => !isVocabLine(p) && !isDirtyPara(p));
      const dropped = raw.length - arr.length;
      const want = PARAS[k] || arr.length;
      let cut = 0;
      if (arr.length > want) { cut = arr.length - want; arr = arr.slice(0, want); }
      if (dirty >= 2 && dirty >= Math.ceil(want * 0.5)) {
        /* 报到「不可恢复」级别，不要只写「剔除杂质」——那会让人误以为只是轻微污染 */
        para_warn.push(DISPLAY[k] + ' 疑似整篇非英文产出（' + raw.length + ' 段中有 ' + dirty
          + ' 段含中文已丢弃）→ 该档产出无效，需重新生成');
      } else if (dropped || cut) {
        /* 注意：告警条目之间用「；」拼接，所以条目内部不能再出现「；」，否则后端切不干净 */
        para_warn.push(DISPLAY[k] + ' 段数 ' + raw.length + ' → ' + arr.length
          + '（规格 ' + want + '，剔除生词表/杂质 ' + dropped + ' 段，截断 ' + cut + ' 段）');
      } else if (arr.length < want) {
        para_warn.push(DISPLAY[k] + ' 段数不足 ' + arr.length + ' 段（规格 ' + want + '），无法补齐，已原样保留');
      }
      paras[k] = arr;
      /* 生词表：优先用模型给的 words；若为空而正文里捞到了，就救回来，避免丢数据 */
      let w = (o.words && Array.isArray(o.words[k])) ? o.words[k] : [];
      w = w.map((x) => String(x).trim()).filter(Boolean);
      if (!w.length && salvaged.length) {
        w = salvaged;
        para_warn.push(DISPLAY[k] + ' 生词表原本混在正文里，已救回 words 字段（' + w.length + ' 条）');
      }
      words[k] = w;
      /* 引用标注：B1/B2+ 组输出 fact_map（基准=事实卡），A1/A2 组输出 gist_map（基准=大意条）。
         两者编号基准不同，必须分别记 basis —— 否则「未被引用」的审计会算错。 */
      const pickMap = (obj) => {
        if (!obj) return null;
        if (Array.isArray(obj[k])) return obj[k];
        const alt = k.replace('P_', '+_');
        return Array.isArray(obj[alt]) ? obj[alt] : null;
      };
      const fm = pickMap(o.fact_map);
      const gm = pickMap(o.gist_map);
      if (fm) factMaps[k] = { basis: 'fact', arr: fm };
      else if (gm) factMaps[k] = { basis: 'gist', arr: gm };
    });
  });

  const title = (function () {
    const t = String(title_in || '').split(/\r?\n/).map((x) => x.trim()).filter(Boolean)[0] || '';
    return t.replace(/^#+\s*/, '').replace(/^Title:\s*/i, '').replace(/^["'\u201c\u201d\u2018\u2019]+|["'\u201c\u201d\u2018\u2019.]+$/g, '').trim() || 'Graded Reading';
  })();

  const articles = {}, plain = {};
  ALL.forEach((k) => {
    const vocab = (words[k] || []).join('\n');
    plain[k] = (paras[k] || []).join('\n\n');
    articles[k] = '# ' + title + '\n\n' + plain[k] + (vocab ? '\n\nWords and Expressions\n' + vocab : '');
  });
  const quiz_source = ALL.map((k) => '=== ' + k + ' ===\n' + (plain[k] || '(EMPTY)')).join('\n\n');

  const fact = parseJSON(fact_json);
  const factList = Array.isArray(fact.facts) ? fact.facts : [];
  const fact_count = factList.length;
  const gistList = Array.isArray(fact.gist) ? fact.gist : [];
  const gist_count = gistList.length;
  const BASIS = {};
  const normalizeMap = (raw, n, cap) => {
    const out = [];
    for (let i = 0; i < n; i++) {
      const ids = Array.isArray(raw && raw[i]) ? raw[i] : [];
      const clean = ids.map((x) => parseInt(x, 10)).filter((x) => x >= 1 && x <= cap);
      out.push(clean.sort((a, b) => a - b));
    }
    return out;
  };
  let fact_map = null, unused_facts = [], map_warn = [];
  try {
    if (fact_count > 0 || gist_count > 0) {
      fact_map = {};
      const raw_map = {};
      ALL.forEach((k) => {
        const info = factMaps[k];
        const basis = (info && info.basis === 'gist' && gist_count) ? 'gist' : 'fact';
        BASIS[k] = basis;
        raw_map[k] = normalizeMap(info ? info.arr : null, (paras[k] || []).length,
                                  basis === 'gist' ? gist_count : fact_count);
      });
      /* 组内三档「段落一一对应」，事实卡绑定本应完全一致。
         模型偶有分歧，以组内第一个非空映射为准统一，并留下告警供人工确认。 */
      const size = (m) => (m || []).reduce((s, ids) => s + (ids ? ids.length : 0), 0);
      GROUP_KEYS.forEach((g) => {
        /* 4 档体系：每组 1 档，无需组内统一，直接采用各档自身的引用映射 */
        fact_map[g[0]] = raw_map[g[0]];
      });
      /* 「未被引用」只对以事实卡为基准的档位有意义：A1/A2 引的是大意条，混进来会把审计算错 */
      const used = {};
      ALL.forEach((k) => { if (BASIS[k] === 'fact') fact_map[k].forEach((ids) => ids.forEach((n) => { used[n] = 1; })); });
      for (let i = 1; i <= fact_count; i++) { if (!used[i]) unused_facts.push(i); }
    }
  } catch (e) { fact_map = null; unused_facts = []; }

  const lengths = {};
  ALL.forEach((k) => {
    const t = plain[k] || '';
    lengths[k] = { display: DISPLAY[k], big: BIGOF[k], words: (t.match(/[A-Za-z0-9'-]+/g) || []).length, paras: (paras[k] || []).length };
  });

  const identity = {
    theme: fact.summary || '', angle: clean_angle || '', level: clean_level || '', level_big: clean_level_big || '',
    sensitive: clean_sensitive || '', shelf: '30天', fit: '泛听/精读',
    provenance: (fact.sources || []).join('; ') || '用户提供素材',
    generated_at: new Date().toISOString(), model: 'deepseek-v4-pro', reviewer: '待人工审核'
  };

  /* ── 过渡期兼容别名：老前端只认 article_a2/b1/b2 与 paras_a2/b1/b2，
        取各档中间子档（A2.2 / B1.2 / B2+.2）顶上，前端切档后即可移除 ── */
  const LEG = { a2: 'A2', b1: 'B1', b2: 'B2' };
  const legacy = {};
  Object.keys(LEG).forEach((k) => {
    legacy['article_' + k] = articles[LEG[k]] || '';
    legacy['paras_' + k] = JSON.stringify(paras[LEG[k]] || []);
  });

  return {
    title: title,
    articles_json: JSON.stringify(articles),
    paras_json: JSON.stringify(paras),
    words_json: JSON.stringify(words),
    quiz_source: quiz_source,
    levels_meta: JSON.stringify(lengths),
    fact_map: fact_map ? JSON.stringify(fact_map) : '',
    map_basis: JSON.stringify(BASIS),
    unused_facts: JSON.stringify(unused_facts),
    fact_count: fact_count,
    map_warn: map_warn.concat(para_warn).join('；'),
    raw_missing: raw_missing.join('/'),
    para_count: JSON.stringify(Object.keys(lengths).reduce((a, k) => { a[k] = lengths[k].paras; return a; }, {})),
    identity_json: JSON.stringify(identity, null, 2),
    summary: fact.summary || '',
    facts_json: JSON.stringify(fact.facts || [], null, 2),
    article_a2: legacy.article_a2, article_b1: legacy.article_b1, article_b2: legacy.article_b2,
    paras_a2: legacy.paras_a2, paras_b1: legacy.paras_b1, paras_b2: legacy.paras_b2
  };
}"""


GEN_VALIDATE_CODE = r"""function main({ articles_json, plain_json, factcard, identity, map_basis }) {
  const SPEC = {
    A1: [60, 160, -1000, 400, 5, 10],
    A2: [160, 300, 400, 650, 10, 14],
    B1: [300, 550, 650, 880, 13, 18],
    B2: [550, 700, 880, 1000, 18, 21]
  };
  const LABEL = { A1: 'A1', A2: 'A2', B1: 'B1', B2: 'B2' };
  const ALL = ['A1','A2','B1','B2'];
  const words = (t) => (String(t || '').match(/[A-Za-z0-9'-]+/g) || []).length;
  const JS = (t, d) => { try { const v = JSON.parse(t || ''); return (v && typeof v === 'object') ? v : d; } catch (e) { return d; } };
  const body = JS(plain_json, {});
  const full = JS(articles_json, {});
  /* 每档的引用基准：'fact' = 用完整事实卡生成（B1/B2+）；'gist' = 用不含数字的大意拍生成（A1/A2）。
     这个分流是必须的 —— 低档按设计就不该出现素材数字，用高档口径去校验会系统性误判。 */
  const BASISOBJ = JS(map_basis, {});

  /* 蓝思估算：est = 45×平均句长 + 1500×长词占比(≥7字符) − 350
     系数由 12 档真实生成文本对目标区间做最小二乘标定得到（RMSE ≈ 45L，覆盖 100–1300L）。
     仍非 MetaMetrics 官方值，仅作档位一致性参考。 */
  const estLexile = (t) => {
    const ws = String(t || '').match(/[A-Za-z'-]+/g) || [];
    if (!ws.length) return 0;
    const n = ws.length;
    const lng = ws.filter((w) => w.length >= 7).length;
    const st = Math.max(1, (String(t).match(/[.!?]+/g) || []).length);
    return Math.round(45 * (n / st) + 1500 * (lng / n) - 350);
  };

  const validate = (key, article) => {
    const checks = [], fails = [];
    const [lo, hi, lxlo, lxhi, slo, shi] = SPEC[key];
    const basis = BASISOBJ[key] === 'gist' ? 'gist' : 'fact';
    const wc = words(article);
    if (wc < lo * 0.75 || wc > hi * 1.35) {
      fails.push('长度校验: 词数 ' + wc + '，' + LABEL[key] + ' 应为 ' + lo + '-' + hi);
      checks.push({ name: '长度校验', status: 'fail', detail: wc + ' 词' });
    } else {
      const okIn = (wc >= lo * 0.95 && wc <= hi * 1.1);
      checks.push({ name: '长度校验', status: okIn ? 'pass' : 'warn', detail: wc + ' 词（' + lo + '-' + hi + '）' });
    }
    const st = Math.max(1, (String(article || '').match(/[.!?]+/g) || []).length);
    const msl = wc / st;
    if (msl < slo * 0.75 || msl > shi * 1.3) {
      fails.push('句长校验: 平均句长 ' + msl.toFixed(1) + ' 词，' + LABEL[key] + ' 应为 ' + slo + '-' + shi);
      checks.push({ name: '句长校验', status: 'fail', detail: msl.toFixed(1) + ' 词/句' });
    } else {
      const okIn = (msl >= slo * 0.9 && msl <= shi * 1.1);
      checks.push({ name: '句长校验', status: okIn ? 'pass' : 'warn', detail: msl.toFixed(1) + ' 词/句（' + slo + '-' + shi + '）' });
    }
    const lex = estLexile(article);
    const pLo = (lxlo > 0 ? lxlo * 0.80 : lxlo) - 80, pHi = lxhi * 1.20 + 80;
    if (lex < pLo || lex > pHi) {
      fails.push('蓝思校验: 估算 ' + lex + 'L，' + LABEL[key] + ' 应为 ' + (lxlo > 0 ? lxlo + '-' + lxhi : 'BR-' + lxhi) + 'L');
      checks.push({ name: '蓝思校验', status: 'fail', detail: '估算 ' + lex + 'L' });
    } else {
      const okIn = (lxlo <= 0 || lex >= lxlo * 0.90) && lex <= lxhi * 1.10;
      checks.push({ name: '蓝思校验', status: okIn ? 'pass' : 'warn', detail: '估算 ' + lex + 'L（' + (lxlo > 0 ? lxlo + '-' + lxhi : 'BR-' + lxhi) + 'L）' });
    }
    const sensWords = ['分裂', '血腥', '赌博', '毒品', '色情', '种族歧视', '遇难者隐私'];
    const hits = sensWords.filter((w) => String(article || '').includes(w));
    if (hits.length) {
      fails.push('敏感排查: 命中 ' + hits.join('/'));
      checks.push({ name: '敏感排查', status: 'fail', detail: hits.join('/') });
    } else {
      checks.push({ name: '敏感排查', status: 'pass', detail: '' });
    }
    let factNums = [];
    try { factNums = (JSON.stringify(JSON.parse(factcard || '{}')).match(/\d[\d,.]*%?/g) || []).slice(0, 6); } catch (e) { }
    /* 低档（gist 基准）按设计只用「不含数字与专名的大意拍」生成，所以「素材数字未出现」
       是**预期结果**，不是缺陷 —— 用高档口径判它 fail 会让 A1/A2 六档被系统性误判。
       低档真正该防的是相反方向：凭空编出数字。所以这里改成「出现数字就告警」。 */
    if (basis === 'gist') {
      const anyNum = String(article || '').match(/\d[\d,.]*%?/g) || [];
      if (anyNum.length) {
        checks.push({ name: '事实一致性', status: 'warn',
          detail: '低档出现数字 ' + anyNum.slice(0, 4).join('/') + '（本档按设计不含数字，请核实来源）' });
      } else {
        checks.push({ name: '事实一致性', status: 'pass', detail: '低档无数字（符合大意拍口径）' });
      }
    } else {
      const missNums = factNums.filter((n) => !String(article || '').includes(n));
      if (factNums.length && missNums.length === factNums.length) {
        fails.push('事实一致性: 事实卡关键数字未出现');
        checks.push({ name: '事实一致性', status: 'fail', detail: '' });
      } else {
        checks.push({ name: '事实一致性', status: 'pass', detail: factNums.length ? (factNums.length - missNums.length) + '/' + factNums.length + ' 数字命中' : '' });
      }
    }
    const placeholders = /(TBD|TODO|\{f\d+\}|XXX|\(EMPTY\))/i.test(String(article || ''));
    const zh = (String(article || '').match(/[\u4e00-\u9fff]/g) || []).length;
    /* 语言闸门必须能区分三种截然不同的成因，否则人工审核会被误导：
       (a) 残留占位符；
       (b) 生词表被当成段落混进了正文数组（实测过，见 docs/11）；
       (c) 模型整篇输出中文（实测短素材 S2 的 B1.3 首跑：JSON 合法、段数正确、正文却全中文）。
       (c) 在聚合层已把含中文的段丢弃，所以走到这里通常表现为「正文为空」。 */
    if (!String(body[key] || '').trim()) {
      fails.push('语言纯净度: 该档正文为空（模型未产出英文段落，或产出被判为非英文后丢弃）→ 需重新生成');
      checks.push({ name: '语言纯净度', status: 'fail', detail: '正文为空 / 非英文产出' });
    } else if (placeholders || zh > 5) {
      const zhLines = String(article || '').match(/[^\n]*[\u4e00-\u9fff][^\n]*/g) || [];
      const snippet = zhLines.slice(0, 3).map((s) => s.trim().slice(0, 36)).join(' ｜ ');
      const zhHeavy = (zh > 30 && zh > wc * 2);
      fails.push('语言纯净度: ' + (placeholders
        ? '含占位符'
        : (zhHeavy
          ? '模型未输出英文（中文 ' + zh + ' 字 / 英文 ' + wc + ' 词）→ 需重新生成'
          : '正文段落疑似混入生词表/中文 ' + zh + ' 字 → ' + snippet)));
      checks.push({ name: '语言纯净度', status: 'fail',
        detail: placeholders ? '占位符' : (zhHeavy ? '整篇非英文（' + zh + ' 中文字）' : '疑似生词表混入：' + snippet) });
    } else {
      checks.push({ name: '语言纯净度', status: 'pass', detail: '' });
    }
    let idKeys = [];
    try { idKeys = Object.keys(JSON.parse(identity || '{}')); } catch (e) { }
    const need = ['theme', 'angle', 'shelf', 'fit', 'provenance'];
    const miss = need.filter((k) => idKeys.indexOf(k) < 0);
    if (miss.length) {
      fails.push('身份完整性: 缺少 ' + miss.join('/'));
      checks.push({ name: '身份完整性', status: 'fail', detail: miss.join('/') });
    } else {
      checks.push({ name: '身份完整性', status: 'pass', detail: '' });
    }
    checks.push({ name: '合规署名', status: 'pass', detail: '人工审核标记由发布环节补充' });
    return {
      level: LABEL[key], level_key: key, word_count: wc, word_range: lo + '-' + hi,
      msl: Math.round(msl * 10) / 10, msl_range: slo + '-' + shi,
      lexile_est: lex, lexile_range: (lxlo > 0 ? lxlo + '-' + lxhi : 'BR-' + lxhi),
      has_body: !!(body[key] && String(body[key]).trim()),
      score: checks.filter((c) => c.status === 'pass').length,
      pass: fails.length === 0, checks: checks, fail_reasons: fails
    };
  };

  const results = ALL.map((k) => validate(k, body[k]));
  const legKeys = { a2: 'A2', b1: 'B1', b2: 'B2' };
  const legacy = Object.keys(legKeys).map((k) => {
    const r = results.filter((x) => x.level_key === legKeys[k])[0];
    if (!r) return null;
    const c = JSON.parse(JSON.stringify(r)); c.level = k.toUpperCase(); c.level_key_legacy = legKeys[k]; return c;
  }).filter(Boolean);
  const overall = {
    total_checks: ALL.length * 8,
    total_pass: results.reduce((s, r) => s + r.score, 0),
    all_pass: results.every((r) => r.pass),
    levels: ALL.length,
    lexile_note: '蓝思为按平均句长 + 长词占比 + 平均词长估算，非 MetaMetrics 官方值，仅作档位一致性参考',
    results: results,
    results_legacy: legacy
  };
  return {
    validation_json: JSON.stringify(overall),
    validation_pass: String(overall.all_pass),
    validation_score: overall.total_pass + '/' + overall.total_checks
  };
}"""


# ---- 模型渠道：DeepSeek 官方（2026-09-15 官方 API 已更新可用）
# 2026-09-10 官方渠道曾余额耗尽（402 Insufficient Balance），临时切到硅基流动；
# 现已切回 DeepSeek 官方。所有 LLM 节点的 model 定义本就是官方渠道
# （deepseek-v4-flash / deepseek-v4-pro，参数含 thinking:False），无需再改指渠道。
DS_PROVIDER = 'langgenius/deepseek/deepseek'


def repoint_models(g):
    """保持 DeepSeek 官方渠道，仅修正 completion_params 参数名，返回改写数量。"""
    n = 0
    for nd in g['nodes']:
        if (nd.get('type') or nd['data'].get('type')) != 'llm':
            continue
        m = nd['data'].get('model') or {}
        # 防御：历史图若残留硅基流动定义则改回官方（SF 模型名带 deepseek-ai/ 前缀）
        if m.get('provider') != DS_PROVIDER:
            m['provider'] = DS_PROVIDER
            nm = m.get('name', '').lower()
            m['name'] = 'deepseek-v4-pro' if 'pro' in nm else 'deepseek-v4-flash'
            n += 1
        cp = m.get('completion_params')
        if isinstance(cp, dict):
            # DeepSeek 官方渠道的思考参数名是 thinking（不是硅基流动的 enable_thinking）。
            # 统一显式关思考：实测开思考慢 6.75x、token 多 20x（GEN 会拖到十几分钟）。
            cp.pop('enable_thinking', None)
            cp.setdefault('thinking', False)
    return n


def build_gen():
    d = json.load(open(os.path.join(BK, 'gen.graph.json'), encoding='utf-8'))
    g = d['graph']
    by = {n['id']: n for n in g['nodes']}
    n0 = by['nodeGenAll']

    # ---- nodeStart: level 选项 3 → 12
    st = by['nodeStart']
    for v in st['data']['variables']:
        if v.get('variable') == 'level':
            v['options'] = [L['d'] for L in LEVELS]
            v['label'] = '档位偏好（可选，空则由分级节点判定）'
    # 新增 gist：分层大意基准（8 条，去数字去专名）。可选——
    # MAIN 里由抽取链路自动提供；GEN 被单独调用时若为空，nodeClean 会退回 facts_text。
    if not any(v.get('variable') == 'gist' for v in st['data']['variables']):
        st['data']['variables'].append({
            "variable": "gist",
            "label": "素材大意基准（可选，7 条，不含数字与专名）",
            "type": "paragraph", "required": False, "max_length": 4000,
        })

    # ---- nodeClean
    nc = by['nodeClean']
    nc['data']['code'] = GEN_CLEAN_CODE
    nc['data']['desc'] = '清洗上游输入，归一化档位（12 子档白名单）并派生大档；透传大意基准 gist'
    nc['data']['variables'] = [
        {"variable": "summary", "value_selector": ["nodeStart", "summary"]},
        {"variable": "facts_text", "value_selector": ["nodeStart", "facts_text"]},
        {"variable": "angle", "value_selector": ["nodeStart", "angle"]},
        {"variable": "level", "value_selector": ["nodeStart", "level"]},
        {"variable": "gist", "value_selector": ["nodeStart", "gist"]},
    ]
    nc['data']['outputs'] = {k: {"children": None, "type": "string"} for k in
                             ['summary', 'facts_text', 'gist', 'level', 'level_big', 'angle', 'sensitive',
                              'sens_level', 'sens_action', 'sens_reason']}

    # ---- nodeTitle（新增，克隆自 nodeGenAll）
    nt = copy.deepcopy(n0)
    nt['id'] = 'nodeTitle'
    nt['position'] = {"x": 300, "y": 560}
    nt['positionAbsolute'] = {"x": 300, "y": 560}
    nt['data']['title'] = '④-0 统一标题'
    nt['data']['desc'] = '用 flash 统一生成一个全档共用标题，避免四组各写各的'
    nt['data']['model'] = {"completion_params": {"max_tokens": 300, "temperature": 0.6, "thinking": False},
                           "mode": "chat", "name": "deepseek-v4-flash",
                           "provider": "langgenius/deepseek/deepseek"}
    nt['data']['prompt_template'] = [
        {"role": "system", "text": GEN_TITLE_SYS},
        {"role": "user", "text": GEN_TITLE_USER},
    ]
    by['nodeTitle'] = nt

    # ---- nodeGenA1 / A2 / B1 / B2p
    gen_nodes = {}
    positions = {"A1": (620, 120), "A2": (620, 300), "B1": (620, 480), "B2": (620, 660)}
    for big, keys in GROUPS:
        nn = copy.deepcopy(n0)
        nid = 'nodeGen' + (big.replace('+', 'p') if big != 'A1' and big != 'A2' and big != 'B1' else big)
        nid = {'A1': 'nodeGenA1', 'A2': 'nodeGenA2', 'B1': 'nodeGenB1', 'B2': 'nodeGenB2p'}[big]
        nn['id'] = nid
        nn['position'] = {"x": positions[big][0], "y": positions[big][1]}
        nn['positionAbsolute'] = {"x": positions[big][0], "y": positions[big][1]}
        nn['data']['title'] = '④-%s 生成（%s）' % (big, " / ".join(DISPLAY[k] for k in keys))
        nn['data']['desc'] = '生成 %s 档文章（7 段，段落对应素材大意）' % big
        mt = {'A1': 2000, 'A2': 3000, 'B1': 4500, 'B2': 6000}[big]
        nn['data']['model'] = {"completion_params": {"max_tokens": mt, "temperature": 0.45, "thinking": False},
                               "mode": "chat", "name": "deepseek-v4-pro",
                               "provider": "langgenius/deepseek/deepseek"}
        nn['data']['prompt_template'] = [
            {"role": "system", "text": gen_sys(big, keys)},
            {"role": "user", "text": gen_user(big, keys)},
        ]
        gen_nodes[big] = nn
        by[nid] = nn

    # ---- nodeAgg
    ag = by['nodeAgg']
    ag['data']['code'] = GEN_AGG_CODE
    ag['data']['desc'] = '聚合四个档位（A1/A2/B1/B2），输出 articles/paras/levels_meta 与身份记录'
    ag['data']['title'] = '⑤ 聚合+身份记录'
    ag['data']['variables'] = [
        {"variable": "t_a1", "value_selector": ["nodeGenA1", "text"]},
        {"variable": "t_a2", "value_selector": ["nodeGenA2", "text"]},
        {"variable": "t_b1", "value_selector": ["nodeGenB1", "text"]},
        {"variable": "t_b2p", "value_selector": ["nodeGenB2p", "text"]},
        {"variable": "title_in", "value_selector": ["nodeTitle", "text"]},
        {"variable": "fact_json", "value_selector": ["nodeStart", "facts_raw"]},
        {"variable": "clean_level", "value_selector": ["nodeClean", "level"]},
        {"variable": "clean_level_big", "value_selector": ["nodeClean", "level_big"]},
        {"variable": "clean_angle", "value_selector": ["nodeClean", "angle"]},
        {"variable": "clean_sensitive", "value_selector": ["nodeClean", "sensitive"]},
    ]
    # 输出类型必须与代码实际返回值一致：Dify 在运行时强校验（string 输出返回 int 会直接失败）
    NUM_OUT = {'fact_count'}     # 其余（含 para_count，现为按档 JSON 对象）都是 string
    ag['data']['outputs'] = {k: {"children": None, "type": ("number" if k in NUM_OUT else "string")}
                             for k in ['title', 'articles_json', 'paras_json', 'words_json', 'quiz_source',
                                       'levels_meta', 'fact_map', 'map_basis', 'unused_facts', 'fact_count',
                                       'map_warn', 'raw_missing', 'para_count', 'identity_json', 'summary',
                                       'facts_json', 'article_a2', 'article_b1', 'article_b2',
                                       'paras_a2', 'paras_b1', 'paras_b2']}

    # ---- nodeStyle
    ns = by['nodeStyle']
    ns['data']['title'] = '⑧ 写作风格映射'
    ns['position'] = {"x": 60, "y": 560}
    ns['positionAbsolute'] = {"x": 60, "y": 560}

    # ---- nodeQuiz
    nq = by['nodeQuiz']
    nq['data']['title'] = '⑥ 练习题生成（4 档 × 3 题）'
    nq['data']['desc'] = '按四类题型（语言/文本/逻辑/认知）逐档出题，含中文解析'
    nq['data']['model'] = {"completion_params": {"max_tokens": 12000, "temperature": 0.6, "thinking": False},
                           "mode": "chat", "name": "deepseek-v4-pro",
                           "provider": "langgenius/deepseek/deepseek"}
    nq['data']['prompt_template'] = [
        {"role": "system", "text": GEN_QUIZ_SYS},
        {"role": "user", "text": GEN_QUIZ_USER},
    ]
    nq['position'] = {"x": 1240, "y": 480}
    nq['positionAbsolute'] = {"x": 1240, "y": 480}

    # ---- nodeGistCheck（新增）：⑨ 大意复核
    #      为什么必须有：⑦ 是机械校验（词数/段数/句长/蓝思/敏感…），
    #      它拦不住「方向讲反」「主体张冠李戴」「凭空加结论」这类**语义级**失败。
    #      大意复核与它互补：大意管「主线偏没偏」，机械校验管「规格漏没漏」。
    ngc = copy.deepcopy(nq)
    ngc['id'] = 'nodeGistCheck'
    ngc['position'] = {"x": 1240, "y": 40}
    ngc['positionAbsolute'] = {"x": 1240, "y": 40}
    ngc['data']['title'] = '⑨ 大意复核（4 档 × 主线一致性）'
    ngc['data']['desc'] = '把每档正文与分层大意基准比对，判定主线是否走样（方向 / 主体 / 因果 / 新增事件）'
    ngc['data']['model'] = {"completion_params": {"max_tokens": 2400, "temperature": 0.1, "thinking": False},
                            "mode": "chat", "name": "deepseek-v4-flash",
                            "provider": "langgenius/deepseek/deepseek"}
    ngc['data']['prompt_template'] = [
        {"role": "system", "text": GEN_GIST_SYS},
        {"role": "user", "text": GEN_GIST_USER},
    ]
    ngc['data']['variables'] = []
    ngc['data']['context'] = {"enabled": False, "variable_selector": []}
    by['nodeGistCheck'] = ngc

    # ---- nodeValidate
    nv = by['nodeValidate']
    nv.pop('sourcePosition', None)
    nv.pop('targetPosition', None)
    nv['type'] = 'code'
    nv['width'] = 150
    nv['height'] = 22
    nv['zIndex'] = 0
    nv['position'] = {"x": 1240, "y": 260}
    nv['positionAbsolute'] = {"x": 1240, "y": 260}
    nv['data']['title'] = '⑦ 8 项校验 × 4 档'
    nv['data']['desc'] = '逐档校验长度/句长/蓝思(估算)/敏感/事实/语言纯净/身份/署名，共 96 项'
    nv['data']['code'] = GEN_VALIDATE_CODE
    nv['data']['variables'] = [
        {"variable": "articles_json", "value_selector": ["nodeAgg", "articles_json"]},
        {"variable": "plain_json", "value_selector": ["nodeAgg", "paras_json"]},
        {"variable": "factcard", "value_selector": ["nodeStart", "facts_raw"]},
        {"variable": "identity", "value_selector": ["nodeAgg", "identity_json"]},
        # 每档的引用基准（fact / gist）—— 校验器据此对低档换口径，否则 A1/A2 会被系统性误判
        {"variable": "map_basis", "value_selector": ["nodeAgg", "map_basis"]},
    ]
    nv['data']['outputs'] = {k: {"children": None, "type": "string"} for k in
                             ['validation_json', 'validation_pass', 'validation_score']}

    # ---- nodeEnd
    ne = by['nodeEnd']
    ne['data']['desc'] = '输出 4 档文章 / 段落 / 题目 / 校验 / 身份记录'
    # (输出变量名, 来源节点, 来源节点的输出变量名) —— 三者必须分开写！
    # 这里曾出错：nodeQuiz 的输出变量是 text，不是 quiz_json。
    outs = [
        ("title", "nodeAgg", "title"), ("articles_json", "nodeAgg", "articles_json"),
        ("paras_json", "nodeAgg", "paras_json"), ("words_json", "nodeAgg", "words_json"),
        ("levels_meta", "nodeAgg", "levels_meta"), ("para_count", "nodeAgg", "para_count"),
        ("fact_map", "nodeAgg", "fact_map"), ("unused_facts", "nodeAgg", "unused_facts"),
        ("map_basis", "nodeAgg", "map_basis"),
        ("fact_count", "nodeAgg", "fact_count"), ("map_warn", "nodeAgg", "map_warn"),
        ("identity_json", "nodeAgg", "identity_json"), ("summary", "nodeAgg", "summary"),
        ("facts_json", "nodeAgg", "facts_json"),
        ("article_a2", "nodeAgg", "article_a2"), ("article_b1", "nodeAgg", "article_b1"),
        ("article_b2", "nodeAgg", "article_b2"), ("paras_a2", "nodeAgg", "paras_a2"),
        ("paras_b1", "nodeAgg", "paras_b1"), ("paras_b2", "nodeAgg", "paras_b2"),
        ("quiz_json", "nodeQuiz", "text"),
        ("validation_json", "nodeValidate", "validation_json"),
        ("validation_pass", "nodeValidate", "validation_pass"),
        ("validation_score", "nodeValidate", "validation_score"),
        ("gist_check_json", "nodeGistCheck", "text"),
        ("level", "nodeClean", "level"), ("level_big", "nodeClean", "level_big"),
        ("sens_level", "nodeClean", "sens_level"), ("sens_reason", "nodeClean", "sens_reason"),
        ("facts_text", "nodeClean", "facts_text"), ("angle", "nodeClean", "angle"),
        ("facts_raw", "nodeStart", "facts_raw"),
    ]
    ne['data']['outputs'] = [{"value_selector": [src, svar], "variable": var}
                             for var, src, svar in outs]
    ne['position'] = {"x": 1560, "y": 380}
    ne['positionAbsolute'] = {"x": 1560, "y": 380}

    # ---- 节点顺序
    order = ['nodeStart', 'nodeClean', 'nodeStyle', 'nodeTitle', 'nodeGenA1', 'nodeGenA2',
             'nodeGenB1', 'nodeGenB2p', 'nodeAgg', 'nodeQuiz', 'nodeValidate', 'nodeGistCheck', 'nodeEnd']
    new_nodes = [by[i] for i in order]
    for n in new_nodes:
        n['positionAbsolute'] = dict(n['position'])

    # ---- 边
    edges = []
    z = [10]

    def E(src, tgt):
        z[0] += 1
        edges.append({
            "id": "e-%s-%s" % (src.replace('node', '').lower(), tgt.replace('node', '').lower()),
            "source": src, "target": tgt, "type": "custom",
            "sourceHandle": "source", "targetHandle": "target", "zIndex": z[0],
            "data": {"isInIteration": False, "sourceHandle": "source", "targetHandle": "target",
                     "sourceType": by[src]['type'] or by[src]['data']['type'],
                     "targetType": by[tgt]['type'] or by[tgt]['data']['type'], "isInLoop": False},
        })

    for t in ['nodeClean', 'nodeStyle']:
        E('nodeStart', t)
    # nodeTitle 引用 nodeClean 的 summary/angle，必须排在 nodeClean 之后
    E('nodeClean', 'nodeTitle')
    for t in ['nodeGenA1', 'nodeGenA2', 'nodeGenB1', 'nodeGenB2p']:
        E('nodeClean', t)
        E('nodeStyle', t)
        E('nodeTitle', t)
        E(t, 'nodeAgg')
    E('nodeAgg', 'nodeQuiz')
    E('nodeAgg', 'nodeValidate')
    # 大意复核与练习/校验并行从 aggregate 出发：它只依赖 12 档正文与大意基准，
    # 挂在 nodeAgg 后面可与 nodeQuiz 同时跑，不额外拉长总时长。
    E('nodeAgg', 'nodeGistCheck')
    E('nodeQuiz', 'nodeEnd')
    E('nodeValidate', 'nodeEnd')
    E('nodeGistCheck', 'nodeEnd')

    g['nodes'] = new_nodes
    repoint_models(g)
    g['edges'] = edges
    d['graph'] = g
    for k in ['hash', 'version_number', 'marked_name', 'marked_comment', 'updated_at', 'updated_by']:
        d.pop(k, None)
    return d


# ============================================================================
# 2) FACT 工作流
# ============================================================================
FACT_TABLE = """A1 ｜60–160  ｜BR–400L  ｜5–10 ｜读者五米之内的世界 / 动物身体四季 / 昨天遇到了什么
A2 ｜160–300 ｜400–650L ｜10–14｜兴趣爱好 / 具象科普 / 别国生活与中外对比
B1 ｜300–550 ｜650–880L ｜13–18｜科技环境 / 社会现象 / 人物故事与文化对比
B2 ｜550–700 ｜880–1000L｜18–21｜解释性报道与商业案例，名词化密度上升"""

FACT_GRADE_SYS = """你是语言教学分级专家，依据《APP阅读级别量化表》判定这篇素材**能支撑的档位区间**。全平台分 4 个档位（A1 / A2 / B1 / B2）。

输出 JSON（只输出 JSON，不要任何解释，不要 markdown 代码块）：
{"lo":"A1|A2|B1|B2","hi":"A1|A2|B1|B2","info_points":8,"level":"A1|A2|B1|B2","level_big":"A1|A2|B1|B2","reason":"40字以内","suggested_angle":"建议的切入角度"}

字段含义：
- `lo` / `hi`：这篇素材**能支撑的最低档 / 最高档**。区间必须**连续**，且 `lo` 不高于 `hi`。
- `info_points`：这篇素材能被拆出的**独立信息点条数**（整数）。
- `level`：前端默认打开的档位，建议取 `lo`。
- `level_big`：`level` 所属档位（A1 / A2 / B1 / B2）。

【4 档速查表】档位｜词数｜蓝思｜平均句长｜认知特征
%s

判定规则：
- 必须综合看主题认知半径、语言复杂度、蓝思与句长，**不得只看词数**。
- 素材本身没有词数——你要判断的是「这个素材适合用哪一档的篇幅与语言去重写」。
- **`hi` 由信息点条数决定**：信息点少（4 条上下）的素材，`hi` 不宜超过 A2；信息点 7 条以上才可能支撑到 B2。
- **`lo` 由概念可具象性决定**：概念无法具象化（宏观政策、抽象论证）时 A1/A2 写不出来，`lo` 相应抬高。
- 常见误判：把「生僻但短」当低档；让 A1/A2 承载议论。
- 若下方知识库检索结果与本表冲突，**以本表为准**。
- 若用户明确指定了档位偏好，优先遵循用户偏好。""" % FACT_TABLE

FACT_GRADE_USER = """知识库检索结果（参考，冲突时以系统提示中的速查表为准）：
{{#context#}}

素材内容：
{{#nodeStart.material#}}

用户档位偏好：{{#nodeStart.level#}}

请输出分级 JSON。"""

# ① 事实抽取：原先只存在于备份图 dify_graphs/fact.graph.json 里，代码不覆盖它。
# 接入区间模型后必须「接管」——因为它正是产出「分层大意基准（gist）」的地方，
# 而 gist 是低档生成 + 全档大意复核的共同基准。接管后这里成为唯一真源。
FACT_FACT_SYS = """你是教育内容生产流水线中的"素材事实抽取器"。输入一段素材（可能是热点新闻、YouTube 字幕或网页内容），抽取其中的客观事实，并同时产出一份「分层大意基准」，输出严格的 JSON。

输出格式（只输出 JSON，不要任何解释，不要 markdown 代码块）：
{"summary": "30字以内的中文主题概括", "summary_en": "English topic summary (within 15 words)", "facts": [{"en": "English atomic fact, keep numbers/dates/names exactly", "zh": "对应中文事实"}], "gist": [{"en": "Coarse one-sentence story beat, NO numbers and NO proper names", "zh": "对应中文大意"}], "numbers": ["3 million", "2025", "45%"], "sources": ["原始信源名称"]}

【facts —— 细节事实，供 B1 / B2+ 高档使用】
1. 只抽取素材中明确出现的事实，禁止推断或补充。
2. 数字、百分比、专名必须原样保留（英文事实里尤其要保持数字精度），这是后续事实一致性校验的依据。
3. facts 每一条都必须同时给出 en（英文事实，供英文文章生成直接引用）和 zh（中文对照翻译）两个字段，一一对应。
4. 若素材包含观点性内容，放入 summary 中注明"观点"。
5. facts 数量必须控制在 6-12 条。若自然抽取多于 12 条，请把同主题、同类的相邻事实合并为一条（例如把多个同类的数字事实并成一句并列句），确保最终不超过 12 条；少于 6 条时，把含多个信息点的长句拆成多条。合并时不得丢失任何数字、百分比、专名与时间。

【gist —— 分层大意基准，恰好 7 条，供 A1 / A2 低档使用】
6. gist 恰好 7 条，每条一句话，描述素材的一个"故事节拍"（谁做了什么 / 发生了什么变化），按时间或逻辑顺序排列。
7. gist 里**禁止出现任何数字、百分比、年份、机构名、人名、地名**——这些属于细节，由 facts 承载。把"上升了 40%"写成"上升很多"，把"世界卫生组织"写成"国际卫生机构"，把"2025 年"写成"最近"。
8. gist 必须完整覆盖素材主线：把 7 条连起来读，应当能还原素材讲了什么。不得引入素材中不存在的信息。
9. gist 的 7 条与 facts 之间是多对一关系（多条细节对应一条大意），但**任何一条事实所属的语义块都不得在大意中缺席**。

【两者的关系】facts 与 gist 是同一条素材的两种粒度，不是两份不同的内容：gist 就是 facts 去掉数字与专名之后的语义骨架。"""

FACT_FACT_USER = """{{#nodeStart.material#}}"""

FACT_CLEAN_CODE = r"""function main({ fact_text, grade_text, check_text }) {
  const strip = (t) => String(t || '').replace(/<think>[\s\S]*?<\/think>/g, '').trim();
  const parseJSON = (t) => {
    const s = strip(t).replace(/```json|```/g, '');
    const m = s.match(/\{[\s\S]*\}/);
    if (m) {
      try { return JSON.parse(m[0]); } catch (e) {
        /* 尾逗号容错（与 GEN 聚合节点同一坑，见该处注释） */
        try { return JSON.parse(m[0].replace(/,(\s*[\]}])/g, '$1')); } catch (e2) { }
      }
    }
    return {};
  };
  const normLevel = (v) => {
    let s = String(v || '').trim().toUpperCase().replace(/\s+/g, '').replace(/[_-]/g, '.').replace(/档/g, '');
    s = s.replace(/^B2PLUS/, 'B2').replace(/^B2P/, 'B2');
    const AL = {
      'A1':'A1','A2':'A2','B1':'B1','B2':'B2',
      'A1.1':'A1','A1.2':'A1','A1.3':'A1',
      'A2.1':'A2','A2.2':'A2','A2.3':'A2',
      'B1.1':'B1','B1.2':'B1','B1.3':'B1',
      'B2.1':'B2','B2.2':'B2','B2.3':'B2',
      'B2+.1':'B2','B2+.2':'B2','B2+.3':'B2',
      'C1':'B2'
    };
    if (AL[s]) return AL[s];
    const m = s.match(/^(A1|A2|B1|B2\+?)/);
    if (m) { return m[1] === 'B2+' ? 'B2' : m[1]; }
    return 'B1';
  };
  const fact = parseJSON(fact_text);
  const grade = parseJSON(grade_text);
  const check = parseJSON(check_text);
  const rawFacts = Array.isArray(fact.facts) ? fact.facts : [];
  const facts = rawFacts.map(f => {
    if (typeof f === 'string') return { en: f, zh: f };
    return { en: String((f && f.en) || '').trim(), zh: String((f && f.zh) || '').trim() };
  }).filter(f => f.en || f.zh);
  const sensLevel = String(check.level || 'S3').toUpperCase().trim();
  const sensAction = String(check.action || 'ok').toLowerCase().trim();
  /* 分层大意基准（gist）：去数字、去专名的语义骨架，恰好 8 条。
     用途有二：① 供 A1/A2 低档生成（低档只讲大意拍）；② 作为全链路「主线是否走样」的比对基准。 */
  const rawGist = Array.isArray(fact.gist) ? fact.gist : [];
  const gist = rawGist.map(g => {
    if (typeof g === 'string') return { en: String(g).trim(), zh: String(g).trim() };
    return { en: String((g && g.en) || '').trim(), zh: String((g && g.zh) || '').trim() };
  }).filter(g => g.en || g.zh);

  /* 档位区间：由分级节点判出 lo / hi，这里只做归一化与顺序纠正。
     区间是**元数据**（前端据此限制档位控件范围），不改变「照常生成 12 档」。 */
  const ORD = { 'A1':1, 'A2':2, 'B1':3, 'B2':4 };
  let lvLo = normLevel(grade.lo || grade.level);
  /* hi 缺失时回退到 lo，而不是让 normLevel 的默认值（B1.1）把区间撑大 ——
     否则模型漏写 hi 会静默产出一个明显失真的区间。 */
  let lvHi = normLevel(grade.hi || grade.lo || grade.level);
  if (ORD[lvLo] > ORD[lvHi]) { const tmp = lvLo; lvLo = lvHi; lvHi = tmp; }
  let infoPoints = parseInt(grade.info_points, 10);
  if (!(infoPoints > 0)) infoPoints = facts.length;

  const lv = normLevel(grade.level);
  const big = lv;
  return {
    summary: fact.summary || fact.summary_en || '（未识别主题）',
    facts_text: facts.length ? facts.map((f, i) => (i + 1) + '. ' + (f.en || f.zh)).join('\n') : '（无）',
    gist: gist.length ? gist.map((g, i) => (i + 1) + '. ' + (g.en || g.zh)).join('\n') : '',
    level_lo: lvLo,
    level_hi: lvHi,
    info_points: String(infoPoints),
    level: lv,
    level_big: big,
    grade_reason: grade.reason || '',
    angle: grade.suggested_angle || '（无特殊角度）',
    sensitive: sensLevel + ' / ' + sensAction + ' / ' + (check.reason || ''),
    sens_level: sensLevel,
    sens_action: sensAction,
    sens_reason: check.reason || '',
    facts_json: JSON.stringify(facts),
    // facts_raw 必须是「干净 JSON」：硅基流动的模型默认会把思考过程写进 text，
    // 原样透传会让下游 GEN 多吞约 3.5 倍 token，前端也会读到思考文本。
    facts_raw: (function () {
      const s = strip(fact_text).replace(/```json|```/g, '');
      const m = s.match(/\{[\s\S]*\}/);
      return m ? m[0] : '';
    })()
  };
}"""


def build_fact():
    d = json.load(open(os.path.join(BK, 'fact.graph.json'), encoding='utf-8'))
    g = d['graph']
    by = {n['id']: n for n in g['nodes']}

    st = by['nodeStart']
    for v in st['data']['variables']:
        if v.get('variable') == 'level':
            v['options'] = [L['d'] for L in LEVELS]
            v['label'] = '档位偏好（可选，空则由分级节点判定）'

    ng = by['nodeGrade']
    ng['data']['title'] = '③ 分级（4 档）'
    ng['data']['desc'] = '依据 4 档量化表判定素材档位区间，输出 lo/hi + 依据'
    ng['data']['prompt_template'] = [
        {"role": "system", "text": FACT_GRADE_SYS},
        {"role": "user", "text": FACT_GRADE_USER},
    ]
    ng['data']['model'] = {"completion_params": {"max_tokens": 900, "temperature": 0.2, "thinking": False,
                                                 "response_format": "json_object"},
                           "mode": "chat", "name": "deepseek-v4-flash",
                           "provider": "langgenius/deepseek/deepseek"}

    # ---- nodeFact：接管（原先由备份图定义，代码不覆盖）
    #      新增 gist（8 条分层大意）；facts 上限 12 条，故 max_tokens 从 2000 提到 3200。
    nf = by['nodeFact']
    nf['data']['title'] = '① 事实抽取（事实卡 + 分层大意基准）'
    nf['data']['desc'] = '抽取客观事实（6-12 条）与分层大意基准 gist（恰好 7 条，去数字去专名）'
    nf['data']['prompt_template'] = [
        {"role": "system", "text": FACT_FACT_SYS},
        {"role": "user", "text": FACT_FACT_USER},
    ]
    nf['data']['model'] = {"completion_params": {"max_tokens": 3200, "temperature": 0.2, "thinking": False,
                                                 "response_format": "json_object"},
                           "mode": "chat", "name": "deepseek-v4-flash",
                           "provider": "langgenius/deepseek/deepseek"}

    nc = by['nodeClean']
    nc['data']['code'] = FACT_CLEAN_CODE
    nc['data']['desc'] = '清洗 ①②③ 输出，归一化 4 档并派生区间'
    nc['data']['outputs'] = {k: {"children": None, "type": "string"} for k in
                             ['summary', 'facts_text', 'level', 'level_big', 'grade_reason', 'angle',
                              'sensitive', 'sens_level', 'sens_action', 'sens_reason', 'facts_json',
                              'facts_raw', 'gist', 'level_lo', 'level_hi', 'info_points']}

    # ---- KB 检索词节点（新增）
    # 背景：知识库语料是中文标准表，而检索 query 原本是英文素材原文。
    #       实测英文 query 对中文语料的向量相似度极低（top_k=8 仍然 0 命中），
    #       所以两个 KB 节点一直在返回空数组 —— 知识库形同虚设。
    #       改为「固定中文检索意图」后，top_k=8 可稳定召回 0.68–0.75 分的标准段落。
    KB_JOBS = [
        ('nodeQRule', 'nodeKBSens', 5, (600, 20), 'KB 敏感规则检索词',
         '输出固定的中文检索意图，让中文的敏感规则语料被稳定召回'),
        ('nodeQGrade', 'nodeKBGrade', 8, (900, 20), 'KB 分级标准检索词',
         '输出固定的中文检索意图，让中文的 12 档分级标准被稳定召回'),
    ]
    KB_QUERY_TEXT = {
        'nodeQRule': '敏感内容判定与处置规则 四档定义 S0 红线 S1 S2 S3 处理动作 '
                     '政治 宗教 暴力 色情 违禁 分级 处置方式 排除 软处理 降级表述',
        'nodeQGrade': '英语分级阅读标准 4 个档位 词数 蓝思 平均句长 主题范围 语言难度 '
                      '体裁配比 题目分布 判定规则 常见误判 快速对照表 A1 A2 B1 B2',
    }
    KB_QUERY_JS = "function main() {\n  return { query: %s };\n}"
    for qid, kbid, topk, pos, qtitle, qdesc in KB_JOBS:
        qn = copy.deepcopy(nc)
        qn['id'] = qid
        qn['position'] = {"x": pos[0], "y": pos[1]}
        qn['positionAbsolute'] = {"x": pos[0], "y": pos[1]}
        qn['data']['title'] = qtitle
        qn['data']['desc'] = qdesc
        qn['data']['variables'] = []
        qn['data']['outputs'] = {"query": {"children": None, "type": "string"}}
        qn['data']['code'] = KB_QUERY_JS % json.dumps(KB_QUERY_TEXT[qid])
        by[qid] = qn
        g['nodes'].append(qn)
        kb = by[kbid]
        kb['data']['query_variable_selector'] = [qid, 'query']
        kb['data']['multiple_retrieval_config'] = {
            "top_k": topk, "score_threshold": 0.3, "reranking_enable": False,
        }
        g['edges'].append({
            "data": {"isInIteration": False, "sourceHandle": "1", "targetHandle": "2",
                     "sourceType": "code", "targetType": "knowledge-retrieval",
                     "isInLoop": False},
            "id": "e-%s-%s" % (qid, kbid),
            "source": qid, "target": kbid, "type": "custom",
            "sourceHandle": "source", "targetHandle": "target", "zIndex": 0,
        })
        # 必须从 start 连一条边过来：Dify 的执行是从 start 出发的可达性驱动，
        # 没有入边的非 start 节点永远不会被触发（会静默截断整条链路）。
        g['edges'].append({
            "data": {"isInIteration": False, "sourceHandle": "1", "targetHandle": "2",
                     "sourceType": "start", "targetType": "code", "isInLoop": False},
            "id": "e-nodeStart-%s" % qid,
            "source": "nodeStart", "target": qid, "type": "custom",
            "sourceHandle": "source", "targetHandle": "target", "zIndex": 0,
        })

    ne = by['nodeEnd']
    outs = [o for o in ne['data']['outputs']]
    have = {o['variable'] for o in outs}
    for var in ['level_big', 'grade_reason', 'level_lo', 'level_hi', 'info_points', 'gist']:
        if var not in have:
            outs.append({"value_selector": ["nodeClean", var], "variable": var})
    # facts_raw / fact_json 都改由清洗节点给出（干净 JSON），不再透传事实抽取节点的原始输出
    for o in outs:
        if o.get('variable') in ('facts_raw', 'fact_json'):
            o['value_selector'] = ["nodeClean", "facts_raw"]
    ne['data']['outputs'] = outs
    ne['data']['desc'] = '输出事实卡 / 4 档分级结果 / 敏感级别'

    d['graph'] = g
    repoint_models(g)
    for k in ['hash', 'version_number', 'marked_name', 'marked_comment', 'updated_at', 'updated_by']:
        d.pop(k, None)
    return d


# ============================================================================
# 3) 静态图校验：推送到 Dify 之前必须全绿
# ============================================================================
# 输出变量名的推断规则（Dify 各节点类型暴露的输出）
LLM_OUT = {'text', 'reasoning_content', 'usage', 'finish_reason'}
FIXED_OUT = {'knowledge-retrieval': {'result'}, 'if-else': {'result'},
             'template-transform': {'output'}, 'variable-aggregator': {'output'}}


def node_outputs(n):
    t = n.get('type') or n['data'].get('type')
    if t == 'start':
        return {v['variable'] for v in n['data'].get('variables') or []}
    if t == 'code':
        return set((n['data'].get('outputs') or {}).keys())
    if t == 'llm':
        return set(LLM_OUT)
    if t in FIXED_OUT:
        return set(FIXED_OUT[t])
    return None      # 未知类型 → 跳过校验


# LLM 节点的变量引用写在 prompt_template 文本里（不在 variables 数组），必须单独解析
REF_RE = re.compile(r'\{\{#([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)#\}\}')


def prompt_refs(n):
    refs = set()
    for p in n['data'].get('prompt_template') or []:
        for m in REF_RE.finditer(p.get('text', '')):
            refs.add((m.group(1), m.group(2)))
    return refs


def validate_graph(d, name):
    g = d['graph']
    errs = []
    ids = {n['id'] for n in g['nodes']}
    types, outs = {}, {}
    for n in g['nodes']:
        t = n.get('type') or n['data'].get('type')
        types[n['id']] = t
        outs[n['id']] = node_outputs(n)
        if n['position'] != n.get('positionAbsolute'):
            errs.append('%s: positionAbsolute 与 position 不一致' % n['id'])
        if t == 'end' and not n['data'].get('outputs'):
            errs.append('%s: end 节点没有任何输出' % n['id'])

    # 每个节点引用到的 (节点, 变量) 集合 —— 三个来源都要看
    def refs_of(n):
        r = set()
        # knowledge-retrieval 的检索 query 也来自某个节点，同样必须可达
        qvs = n['data'].get('query_variable_selector')
        if isinstance(qvs, list) and len(qvs) == 2:
            r.add(tuple(qvs))
        for v in n['data'].get('variables') or []:
            sel = v.get('value_selector')
            if isinstance(sel, list) and len(sel) == 2:
                r.add(tuple(sel))
        for o in n['data'].get('outputs') or []:
            if isinstance(o, dict):
                sel = o.get('value_selector')
                if isinstance(sel, list) and len(sel) == 2:
                    r.add(tuple(sel))
        r |= prompt_refs(n)
        return r

    def chk(nid, dep, var, where):
        if dep not in ids:
            errs.append('%s: 引用了不存在的节点 %s' % (where, dep)); return
        if types.get(dep) == 'start':
            if outs.get(dep) is not None and var not in outs[dep]:
                errs.append('%s: 引用了 start 节点不存在的入参 "%s"' % (where, var))

    # 边合法性
    for e in g['edges']:
        for k in ('source', 'target'):
            if e[k] not in ids:
                errs.append('边 %s: %s=%s 不存在' % (e.get('id'), k, e[k]))

    # 变量存在性
    for n in g['nodes']:
        is_start = types[n['id']] == 'start'
        for (dep, var) in refs_of(n):
            where = '%s → %s.%s' % (n['id'], dep, var)
            if is_start:
                continue
            if dep not in ids:
                errs.append('%s: 引用了不存在的节点' % where); continue
            if types.get(dep) == 'start' or dep == n['id']:
                continue
            if outs.get(dep) is not None and var not in outs[dep]:
                errs.append('引用了 %s 不存在的输出变量 "%s"（%s 实际输出：%s）'
                            % (where, var, dep, ', '.join(sorted(outs[dep])) or '无'))

    # 可达性（DAG + BFS）
    adj = {i: [] for i in ids}
    indeg = {i: 0 for i in ids}
    for e in g['edges']:
        if e['source'] in adj and e['target'] in adj:
            adj[e['source']].append(e['target'])
            indeg[e['target']] += 1
    q = [i for i, v in indeg.items() if v == 0]
    seen = 0
    while q:
        cur = q.pop(); seen += 1
        for nxt in adj[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                q.append(nxt)
    if seen != len(ids):
        cyc = [i for i, v in indeg.items() if v > 0]
        errs.append('图中存在环，涉及节点: %s' % ', '.join(cyc))
        e_ids = [e['id'] for e in g['edges']]
        g['edges'] = [e for e in g['edges'] if e['source'] not in cyc or e['target'] not in cyc]
        adj = {i: [] for i in ids}
        for e in g['edges']:
            if e['source'] in adj: adj[e['source']].append(e['target'])

    reach = {}
    for i in ids:
        seen2, stack = set(), list(adj[i])
        while stack:
            x = stack.pop()
            if x in seen2: continue
            seen2.add(x); stack.extend(adj.get(x, []))
        reach[i] = seen2

    for n in g['nodes']:
        if types[n['id']] == 'start':
            continue
        for (dep, var) in refs_of(n):
            if dep not in ids or types.get(dep) == 'start' or dep == n['id']:
                continue
            if n['id'] not in reach.get(dep, set()):
                errs.append('%s 引用了 %s.%s，但没有从 %s 到 %s 的路径 → 执行时该变量还不存在'
                            % (n['id'], dep, var, dep, n['id']))

    # 从 start 出发的可达性：Dify 的执行引擎从 start 节点开始推进，
    # 没有入边（或入边链断了）的非 start 节点会被静默跳过，整条链路提前结束。
    starts = [i for i, t in types.items() if t == 'start']
    if starts:
        s0 = starts[0]
        for n in g['nodes']:
            if n['id'] == s0:
                continue
            if n['id'] not in reach.get(s0, set()):
                errs.append('%s 从开始节点 %s 不可达 → 运行时永远不会被触发' % (n['id'], s0))

    if errs:
        print('\n✗ %s 静态校验失败 %d 处：' % (name, len(set(errs))))
        for e in sorted(set(errs)):
            print('    - ' + e)
    else:
        print('✓ %s 静态校验通过（节点 %d / 边 %d / 无环 / 变量均存在且可达）'
              % (name, len(g['nodes']), len(g['edges'])))
    return sorted(set(errs))


if __name__ == '__main__':
    gj = build_gen()
    json.dump(gj, open(os.path.join(BK, 'gen.new.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('gen.new.json: %d nodes / %d edges' % (len(gj['graph']['nodes']), len(gj['graph']['edges'])))
    for n in gj['graph']['nodes']:
        print('   ', n['id'], '|', n['data'].get('title'))

    fj = build_fact()
    json.dump(fj, open(os.path.join(BK, 'fact.new.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('fact.new.json: %d nodes / %d edges' % (len(fj['graph']['nodes']), len(fj['graph']['edges'])))
    for n in fj['graph']['nodes']:
        print('   ', n['id'], '|', n['data'].get('title'))

    print('\n--- 静态校验 ---')
    bad = validate_graph(gj, 'GEN') + validate_graph(fj, 'FACT')
    print('\n--- GEN 边 ---')
    for e in gj['graph']['edges']:
        print('   %s -> %s' % (e['source'], e['target']))
    raise SystemExit(1 if bad else 0)
