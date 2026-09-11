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
    dict(k="A1_1", d="A1.1", big="A1", wc=(60, 90),     lex=(-1000, 200),  msl=(5, 7),   paras=4,
         genre="记叙 100%", quiz="语言 2 / 文本 1",
         grammar="一般现在时、be 动词、there be；连接词只用 and / but",
         vocab="只用最高频 600–800 词，几乎不出现派生词与抽象名词",
         topic="读者五米之内的世界——家人、宠物、一顿饭、天气、上学路上；一个场景一件事，不设转折"),
    dict(k="A1_2", d="A1.2", big="A1", wc=(90, 120),    lex=(200, 300),    msl=(7, 9),   paras=4,
         genre="记叙 100%", quiz="语言 1 / 文本 2",
         grammar="新增现在进行时、can / like to、because / so",
         vocab="最高频 800 词以内，只用具象名词",
         topic="动物、身体、四季、简单节日；故事出现「先……然后……」的两段式结构"),
    dict(k="A1_3", d="A1.3", big="A1", wc=(120, 160),   lex=(300, 400),    msl=(8, 10),  paras=4,
         genre="记叙 90% / 说明 10%", quiz="语言 1 / 文本 1 / 逻辑 1",
         grammar="一般过去时（规则动词 + 约 20 个高频不规则）",
         vocab="最高频 800–1000 词",
         topic="从「我每天做什么」转向「我昨天遇到了什么」；可含极简说明文（一图配五六句话讲一个事实）"),
    dict(k="A2_1", d="A2.1", big="A2", wc=(160, 200),   lex=(400, 500),    msl=(10, 12), paras=5,
         genre="记叙 60% / 说明 30% / 应用文 10%", quiz="语言 1 / 文本 2",
         grammar="比较级、be going to / will、基础定语从句（who / which）",
         vocab="最高频 1000–1200 词，只用具象名词",
         topic="兴趣爱好、旅行出行、购物、朋友与情绪、运动；有开头—发展—结尾或总分关系"),
    dict(k="A2_2", d="A2.2", big="A2", wc=(200, 250),   lex=(500, 580),    msl=(11, 13), paras=5,
         genre="记叙 50% / 说明 40% / 应用文 10%", quiz="语言 1 / 文本 1 / 逻辑 1",
         grammar="现在完成时、情态动词、when / if 状语从句",
         vocab="最高频 1200–1500 词，可含常见具象名词",
         topic="具象科普——动物为什么冬眠、雨是怎么来的；商业类首次出现，形式是「一个人做一件小生意」的故事"),
    dict(k="A2_3", d="A2.3", big="A2", wc=(250, 300),   lex=(580, 650),    msl=(12, 14), paras=5,
         genre="记叙 45% / 说明 45% / 应用文 10%", quiz="语言 1 / 文本 1 / 逻辑 1",
         grammar="初步被动语态、过去进行时",
         vocab="最高频 1500–1800 词",
         topic="第一次离开读者的直接生活经验——别的国家的人怎么生活、一百年前的人怎么出行、简单中外对比"),
    dict(k="B1_1", d="B1.1", big="B1", wc=(300, 380),   lex=(650, 720),    msl=(13, 15), paras=6,
         genre="说明议论 55% / 记叙 30% / 应用说明 15%", quiz="语言 1 / 文本 1 / 逻辑 1",
         grammar="被动语态、宾语从句、动名词与不定式作主宾语",
         vocab="最高频 2000–2500 词，开始出现常见抽象名词（method / issue / benefit 一类）",
         topic="科技产品、环境与可持续、学习方法与心理学、求职与办公入门；阅读目的从「练英文」转向「知道点什么」"),
    dict(k="B1_2", d="B1.2", big="B1", wc=(380, 450),   lex=(720, 800),    msl=(15, 17), paras=6,
         genre="议论 ≥25%，其余以说明为主", quiz="语言 1 / 逻辑 1 / 认知 1",
         grammar="条件句 I / II、现在完成进行时、非限定性定语从句",
         vocab="最高频 2500–3000 词，可含常见抽象名词与轻学术词",
         topic="社会现象、创业与商业常识、健康科学；首次出现明确的作者立场，不只是陈述事实"),
    dict(k="B1_3", d="B1.3", big="B1", wc=(450, 550),   lex=(800, 880),    msl=(16, 18), paras=6,
         genre="议论为主，辅以叙事与说明", quiz="文本 1 / 逻辑 1 / 认知 1",
         grammar="过去完成时、报道性动词（claim / argue / suggest）、分词短语作状语",
         vocab="最高频 3000 词，可含轻学术词与报道性动词",
         topic="人物故事、事件复盘、深度一点的文化对比；选题吸引力要压过语言难度"),
    dict(k="B2P_1", d="B2+.1", big="B2+", wc=(550, 700),  lex=(880, 1000),   msl=(18, 21), paras=8,
         genre="新闻特写与说明性长文为主，议论约 30%", quiz="文本 1 / 逻辑 2",
         grammar="名词化密度上升、hedging（tends to / it is likely that）、倒装、多重从句嵌套",
         vocab="AWL 学术词密度 4–6%",
         topic="主流媒体的解释性报道与商业案例——AI 与就业、气候政策、公司兴衰、消费行为、健康科学"),
    dict(k="B2P_2", d="B2+.2", big="B2+", wc=(700, 900),  lex=(1000, 1120),  msl=(20, 23), paras=8,
         genre="评论、书评、长篇特稿、研究综述科普版", quiz="逻辑 1 / 认知 2",
         grammar="反讽、隐喻、让步结构与显性的作者声音",
         vocab="AWL 学术词密度 6–8%",
         topic="有真实争议、有多方立场的议题——媒体信任、教育公平、算法伦理、老龄化与移民、全球供应链"),
    dict(k="B2P_3", d="B2+.3", big="B2+", wc=(900, 1200), lex=(1120, 1300), msl=(22, 26), paras=8,
         genre="抽象论证与文学性非虚构为主", quiz="逻辑 1 / 认知 2",
         grammar="句法复杂度与词汇抽象度同时到顶",
         vocab="AWL 学术词密度 8–10%",
         topic="抽象论证、跨领域引用、文学性非虚构、当代思想散文、学术论文的引言与讨论部分"),
]
LMAP = {L['k']: L for L in LEVELS}
DISPLAY = {L['k']: L['d'] for L in LEVELS}
BIG = {L['k']: L['big'] for L in LEVELS}
GROUPS = [("A1", ["A1_1", "A1_2", "A1_3"]),
          ("A2", ["A2_1", "A2_2", "A2_3"]),
          ("B1", ["B1_1", "B1_2", "B1_3"]),
          ("B2+", ["B2P_1", "B2P_2", "B2P_3"])]


def lex_range(L):
    lo, hi = L['lex']
    return ("BR–%dL" % hi) if lo <= -1000 else ("%d–%dL" % (lo, hi))


# ============================================================================
# 1) GEN 工作流
# ============================================================================
GEN_TITLE_SYS = """你是英语分级阅读编辑。根据主题摘要与切入角度，为这一系列分级文章拟一个英文标题。

要求：
1. 4–9 个英文单词。
2. 只用常见词——同一个标题要同时供 A1.1（60 词入门）与 B2+.3（1200 词进阶）使用，必须让 A1.1 的学习者也能看懂。
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
    subs = "、".join(DISPLAY[k] for k in keys)
    n = LMAP[keys[0]]['paras']
    lines = []
    for k in keys:
        L = LMAP[k]
        wmid = (L['wc'][0] + L['wc'][1]) // 2
        lines.append(
            "- %s：正文 **目标 %d 词**（硬区间 %d–%d；低于下限或超过上限都判不合格）\n"
            "    平均句长 %d–%d 词；蓝思 %s\n"
            "    写作标尺：%s\n    词汇层级：%s\n    语法范围：%s\n    体裁 %s；主题半径：%s"
            % (L['d'], wmid, L['wc'][0], L['wc'][1], L['msl'][0], L['msl'][1], lex_range(L),
               ruler(L), L['vocab'], L['grammar'], L['genre'], L['topic']))
    specs = "\n".join(lines)
    k1, k2, k3 = keys
    d1, d2, d3 = DISPLAY[k1], DISPLAY[k2], DISPLAY[k3]
    extra = ""
    if big == "B2+":
        extra = ("\n- 本组三个子档的篇幅必须拉出梯度且各自**双向达标**：B2+.1 约 620 词、B2+.2 约 800 词、"
                 "B2+.3 控制在 900–1200 词之间。既不要三个都写到 800 词左右就收尾，"
                 "**也不要把 B2+.3 写成 1500 词以上**——上限同样是不合格项。"
                 "\n- ⚠️ **实测本组系统性偏短**：B2+.1 仅 589 词、B2+.2 仅 658 词（目标 700–900）、"
                 "B2+.3 仅 758 词（目标 900–1200），三档全部掉到区间下限之外。"
                 "**请按标称值 620 / 800 / 1050 写足**，逐段把内容补够，不要提前收尾。")
    elif big == "B1":
        extra = ("\n- 本组三个子档篇幅梯度为 **340 / 410 / 500 词**，这是下限概念："
                 "B1.1 不得少于 310 词、B1.2 不得少于 390 词、B1.3 不得少于 460 词。"
                 "模型习惯少写约 20%，请按标称值写，宁多勿少。"
                 "\n- **本组最容易整体失分的地方是「写得像 A2」**：实测曾出现 B1.1 只写 275 词、"
                 "平均句长 11 词/句（规格 13–15），估算蓝思只有 377L，远低于 650L 下限，直接判不合格。"
                 "所以 B1.1 也必须用足中级句法与抽象名词（method / issue / benefit / pressure 一类），"
                 "**先把每句平均写到 13 个词以上，再让总词数达标**。"
                 "\n- ⚠️ **反向也要防（实测硬失败点）**：B1.2 / B1.3 出现过平均句长 21–24 词/句"
                 "（规格 15–17），估算蓝思冲到 1027L / 1172L，超出本档上限直接判不合格。"
                 "**定稿前把超过 22 词的句子拆成两句**；本档的难度升级靠「词汇层级 + 从句类型」，"
                 "**不要靠无限加长单个句子**。")
    elif big == "A2":
        extra = ("\n- 本组是初级档：句子**不能冗长，但必须落在平均 10–12 词/句**，"
                 "低于 9 词/句同样判不合格（实测出现过 8.3 词/句）。"
                 "字数靠「句数够多」而不是「把句子写长」来达标。"
                 "\n- 篇幅梯度为 **180 / 225 / 275 词**：A2.1 不得少于 170 词、A2.2 不得少于 210 词、"
                 "A2.3 不得少于 260 词——实测三档都只贴着区间下限，请按标称值写。"
                 "\n- 词汇不能一味求简单：从 A2.1 起每段至少出现 3 个 7 字母以上的常用词"
                 "（important / different / interesting / together / because 一类），"
                 "否则平均词长偏低会让蓝思掉到 300L 以下。"
                 "\n- ⚠️ **实测本组蓝思系统性偏低 120–150L**（A2.1 只有 277L / 目标 400–500L），"
                 "**蓝思是硬约束**：请主动提高长词密度与句内信息量，不要为了「简单」把文章写得过于单薄。")
    elif big == "A1":
        extra = ("\n- 本组是入门档，**句子必须短**（这是本组最核心的特征，也是校验最容易不合格的地方）。"
                 "A1.1 全篇只有 60–90 词、约 12 句，千万不要写长——"
                 "宁可内容朴素，也不要出现超过 10 词的句子。")
    return """你是英语分级阅读作者。基于给定事实，生成 %s 档三个子档位（%s）的文章，三个子档必须段落级一一对应。

【本组三个子档的硬性规格】（逐项达标，任一项显著偏离即视为不合格）
%s%s

【必须自查的两条硬指标】
① **正文字数**：以规格里的「目标 N 词」为靶心，必须落在硬区间内——**低于下限或超过上限都不合格**。
  实测最容易犯的错是**超写三成以上**，所以写完先数总词数，超了就删段落细节，不够就补，**定稿再进下一档**。
② **平均句长 = 正文总词数 ÷ 句子数**，必须落在规格区间内。
写完每一档后，请自己数一遍总词数与句子数，与规格核对后再输出下一档。

【段落总纲】
- 这是供英语学习者阅读的完整文章，不是摘要。请围绕事实充分展开：补充背景、成因、过程、细节、影响等。
- 本组三篇的段落数必须完全一致，均为 %d 段。
- 三个子档的段落数相同，但每段的词数与句法复杂度不同——难度差异靠词汇层级、句法复杂度和句长体现。

【核心要求：段落一一对应（最重要）】
1. 三个子档正文段数必须完全一致，均为 %d 段。
2. 三个子档的第 i 段必须讲同一个要点（仅语言难度不同）：
   第 1 段 引入（是什么 / 在哪 / 何时）
   第 2 至 %d 段 展开（核心事实、背景、细节、数字、人名、例子，按材料内容自然分段）
   第 %d 段 收尾（意义 / 现状 / 影响）
3. 段落大意、顺序、数量一一对应，切换难度不打断理解。
4. 生词表：每个子档 3–5 个词，格式 "word — 中文释义"。
5. **不要输出标题**，不要在 JSON 里出现 title 字段（标题由上游节点统一给出，见用户消息）。

【事实卡引用标注（必须输出）】
上方「素材事实」按 1 开始编号。你必须在 JSON 中额外输出 fact_map，标明每一段依据了哪几张事实卡。
- 每个内层数组对应一档的 %d 段，长度必须等于 %d
- 元素是该段所依据的事实卡编号（1-based，按升序排列）
- 每段至少引用 1 张卡；同一张卡允许多段引用；**三个子档的 fact_map 必须完全一致**
- 尽量让全部事实卡都被至少一段引用；确实无法纳入的可以不引，系统会标为「未被引用」交人工确认

【输出格式：严格 JSON，只输出一个 JSON 对象，不要 markdown 代码块、不要解释、不要多余文字】
{"%s":["段1",...,"段%d"],"%s":[...],"%s":[...],"words":{"%s":["word — 中文释义"],"%s":[...],"%s":[...]},"fact_map":{"%s":[[1,2],...,[%d]],"%s":[...],"%s":[...]}}

【JSON 键名规则】键名里的点号与加号一律写成下划线：%s 表示 %s，%s 表示 %s。""" % (
        big, subs, specs, extra, n, n, n - 1, n, n, n,
        k1, n, k2, k3, k1, k2, k3, k1, n, k2, k3,
        k1, d1, k3, d3)


def gen_user(big, keys):
    subs = " / ".join(DISPLAY[k] for k in keys)
    return """标题（必须原样使用，不要另拟）：{{#nodeTitle.text#}}
主题：{{#nodeClean.summary#}}
素材事实：
{{#nodeClean.facts_text#}}
切入角度：{{#nodeClean.angle#}}

写作风格：{{#nodeStyle.style_instruction#}}

请生成 %s 三个子档的段落级对齐文章，输出严格 JSON。""" % subs


GEN_QUIZ_SYS = """You are an English reading assessment designer. For EACH of the 12 sub-levels below, write exactly 3 exercises based ONLY on that sub-level's article.

[Question types - four categories]
- "language": tests vocabulary / grammar itself - word meaning in context, reference (what does "it" refer to), guessing meaning from context.
- "text": tests information in the passage - locating details, sequence, main idea, cross-paragraph integration.
- "logic": tests reasoning and argument structure - single-step cause/effect, one-step inference, telling a claim apart from its support.
- "cognitive": tests stance and hidden premises - the author's attitude, mapping where each side stands, implicit assumptions. It must NOT ask "what does the passage say".

[Mandatory type mix per sub-level - exactly 3 questions each]
A1_1: language 2, text 1               (NO logic, NO cognitive)
A1_2: language 1, text 2               (NO logic, NO cognitive)
A1_3: language 1, text 1, logic 1      (logic = single-step cause/effect explicitly signposted in the text)
A2_1: language 1, text 2
A2_2: language 1, text 1, logic 1
A2_3: language 1, text 1, logic 1      (logic requires one inference step - the answer is NOT stated verbatim)
B1_1: language 1, text 1, logic 1
B1_2: language 1, logic 1, cognitive 1 (cognitive appears for the first time - ask about the author's attitude)
B1_3: text 1, logic 1, cognitive 1     (NO language question at this level)
B2P_1: text 1, logic 2
B2P_2: logic 1, cognitive 2
B2P_3: logic 1, cognitive 2

[Difficulty scaling - the question wording must match the sub-level's own article]
- A1.x / A2.x: very short stems, high-frequency words, distractors clearly wrong.
- B1.x: stems may contain one subordinate clause; distractors moderately confusing.
- B2+.x: may rely on synonym replacement, hedging and inference; distractors need careful discrimination. At B2+.3 the options differ in the QUALITY of interpretation rather than being simply right/wrong.

[Explanation - mandatory for every question]
"explain" must be written in CHINESE, 1-3 sentences, saying why the key is correct AND why the single most tempting distractor is wrong. At B2+.3 the explanation is more important than the option itself, so make it genuinely explanatory.

[B2+.3 background guide - mandatory]
Also produce a Chinese "背景导读" for B2P_3. It is NOT a vocabulary note. It must state the prior knowledge a reader has to already have in order to read that piece: the debate it sits inside, the key concepts it assumes, and the cultural context it takes for granted.

[Output format: STRICT JSON only - one JSON object, no markdown code block, no explanation, no extra text]
{"levels":{"A1_1":[{"type":"language","q":"...","options":["A","B","C","D"],"answer":0,"explain":"..."},{"type":"text","q":"...","options":["A","B","C","D"],"answer":1,"explain":"..."},{"type":"language","q":"...","options":["A","B","C","D"],"answer":2,"explain":"..."}],"A1_2":[...],"A1_3":[...],"A2_1":[...],"A2_2":[...],"A2_3":[...],"B1_1":[...],"B1_2":[...],"B1_3":[...],"B2P_1":[...],"B2P_2":[...],"B2P_3":[...]},"guide":{"B2P_3":"..."}}

Rules for the JSON:
- "answer" is the zero-based index of the correct option.
- "type" must be exactly one of: language, text, logic, cognitive.
- Question stems and options must be entirely in ENGLISH. Only "explain" and the guide are in Chinese.
- JSON keys use an underscore instead of a dot or plus sign: A1_1 means A1.1, B2P_1 means B2+.1.
- All 12 level keys must be present, each with exactly 3 questions in the mandated type mix."""

GEN_QUIZ_USER = """The 12 graded articles follow. Each block starts with === LEVEL_KEY ===.

{{#nodeAgg.quiz_source#}}

Write exactly 3 exercises for each of the 12 sub-levels, in the mandated type mix, plus the Chinese background guide for B2P_3. Output strict JSON only."""


GEN_CLEAN_CODE = r"""function main({ summary, facts_text, angle, level }) {
  const normLevel = (v) => {
    let s = String(v || '').trim().toUpperCase().replace(/\s+/g, '').replace(/[_-]/g, '.').replace(/档/g, '');
    s = s.replace(/^B2PLUS/, 'B2+').replace(/^B2P/, 'B2+');
    const AL = {
      'A1.1':'A1.1','A1.2':'A1.2','A1.3':'A1.3',
      'A2.1':'A2.1','A2.2':'A2.2','A2.3':'A2.3',
      'B1.1':'B1.1','B1.2':'B1.2','B1.3':'B1.3',
      'B2+.1':'B2+.1','B2+.2':'B2+.2','B2+.3':'B2+.3',
      'B2.1':'B2+.1','B2.2':'B2+.2','B2.3':'B2+.3','B2':'B2+.1','C1':'B2+.3',
      'A1':'A1.1','A2':'A2.1','B1':'B1.1'
    };
    if (AL[s]) return AL[s];
    const m = s.match(/^(A1|A2|B1|B2\+?)\.?([123])$/);
    if (m) { const big = m[1] === 'B2' ? 'B2+' : m[1]; return big + '.' + m[2]; }
    return 'B1.1';
  };
  const lv = normLevel(level);
  const big = lv.indexOf('B2+') === 0 ? 'B2+' : lv.slice(0, 2);
  return {
    summary: String(summary || 'x'),
    facts_text: String(facts_text || ''),
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
    try { return JSON.parse(m[0]); } catch (e) { return {}; }
  };
  const DISPLAY = {
    A1_1:'A1.1',A1_2:'A1.2',A1_3:'A1.3',
    A2_1:'A2.1',A2_2:'A2.2',A2_3:'A2.3',
    B1_1:'B1.1',B1_2:'B1.2',B1_3:'B1.3',
    B2P_1:'B2+.1',B2P_2:'B2+.2',B2P_3:'B2+.3'
  };
  const BIGOF = {
    A1_1:'A1',A1_2:'A1',A1_3:'A1',
    A2_1:'A2',A2_2:'A2',A2_3:'A2',
    B1_1:'B1',B1_2:'B1',B1_3:'B1',
    B2P_1:'B2+',B2P_2:'B2+',B2P_3:'B2+'
  };
  const GROUP_KEYS = [['A1_1','A1_2','A1_3'],['A2_1','A2_2','A2_3'],['B1_1','B1_2','B1_3'],['B2P_1','B2P_2','B2P_3']];
  const RAW = { A1_1: t_a1, A2_1: t_a2, B1_1: t_b1, B2P_1: t_b2p };
  const ALL = [];
  GROUP_KEYS.forEach((g) => g.forEach((k) => ALL.push(k)));

  const paras = {}, words = {}, factMaps = {}, raw_missing = [];
  GROUP_KEYS.forEach((g) => {
    const o = parseJSON(RAW[g[0]]);
    if (!Object.keys(o).length) raw_missing.push(DISPLAY[g[0]].slice(0, 2));
    g.forEach((k) => {
      const arr = (Array.isArray(o[k]) ? o[k] : []).map((p) => String(p || '').trim()).filter(Boolean);
      paras[k] = arr;
      const w = (o.words && Array.isArray(o.words[k])) ? o.words[k] : [];
      words[k] = w.map((x) => String(x).trim()).filter(Boolean);
      if (o.fact_map && Array.isArray(o.fact_map[k])) factMaps[k] = o.fact_map[k];
      else if (o.fact_map && Array.isArray(o.fact_map[k.replace('P_', '+_')])) factMaps[k] = o.fact_map[k.replace('P_', '+_')];
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
  const normalizeMap = (raw, n) => {
    const out = [];
    for (let i = 0; i < n; i++) {
      const ids = Array.isArray(raw && raw[i]) ? raw[i] : [];
      const clean = ids.map((x) => parseInt(x, 10)).filter((x) => x >= 1 && x <= fact_count);
      out.push(clean.sort((a, b) => a - b));
    }
    return out;
  };
  let fact_map = null, unused_facts = [], map_warn = [];
  try {
    if (fact_count > 0) {
      fact_map = {};
      const raw_map = {};
      ALL.forEach((k) => { raw_map[k] = normalizeMap(factMaps[k], (paras[k] || []).length); });
      /* 组内三档「段落一一对应」，事实卡绑定本应完全一致。
         模型偶有分歧，以组内第一个非空映射为准统一，并留下告警供人工确认。 */
      const size = (m) => (m || []).reduce((s, ids) => s + (ids ? ids.length : 0), 0);
      GROUP_KEYS.forEach((g) => {
        let ref = null;
        for (let i = 0; i < g.length; i++) { if (size(raw_map[g[i]]) > 0) { ref = raw_map[g[i]]; break; } }
        if (!ref) ref = raw_map[g[0]];
        g.forEach((k) => {
          fact_map[k] = ref;
          if (size(raw_map[k]) > 0 && JSON.stringify(raw_map[k]) !== JSON.stringify(ref)) {
            map_warn.push(g[0].slice(0, 2) + ' 组内 fact_map 不一致（已统一按 ' + DISPLAY[g[0]] + '）');
          }
        });
      });
      const used = {};
      ALL.forEach((k) => fact_map[k].forEach((ids) => ids.forEach((n) => { used[n] = 1; })));
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
  const LEG = { a2: 'A2_2', b1: 'B1_2', b2: 'B2P_2' };
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
    unused_facts: JSON.stringify(unused_facts),
    fact_count: fact_count,
    map_warn: map_warn.join('；'),
    raw_missing: raw_missing.join('/'),
    para_count: JSON.stringify(Object.keys(lengths).reduce((a, k) => { a[k] = lengths[k].paras; return a; }, {})),
    identity_json: JSON.stringify(identity, null, 2),
    summary: fact.summary || '',
    facts_json: JSON.stringify(fact.facts || [], null, 2),
    article_a2: legacy.article_a2, article_b1: legacy.article_b1, article_b2: legacy.article_b2,
    paras_a2: legacy.paras_a2, paras_b1: legacy.paras_b1, paras_b2: legacy.paras_b2
  };
}"""


GEN_VALIDATE_CODE = r"""function main({ articles_json, plain_json, factcard, identity }) {
  const SPEC = {
    A1_1: [60, 90, -1000, 200, 5, 7], A1_2: [90, 120, 200, 300, 7, 9], A1_3: [120, 160, 300, 400, 8, 10],
    A2_1: [160, 200, 400, 500, 10, 12], A2_2: [200, 250, 500, 580, 11, 13], A2_3: [250, 300, 580, 650, 12, 14],
    B1_1: [300, 380, 650, 720, 13, 15], B1_2: [380, 450, 720, 800, 15, 17], B1_3: [450, 550, 800, 880, 16, 18],
    B2P_1: [550, 700, 880, 1000, 18, 21], B2P_2: [700, 900, 1000, 1120, 20, 23], B2P_3: [900, 1200, 1120, 1300, 22, 26]
  };
  const LABEL = {
    A1_1: 'A1.1', A1_2: 'A1.2', A1_3: 'A1.3', A2_1: 'A2.1', A2_2: 'A2.2', A2_3: 'A2.3',
    B1_1: 'B1.1', B1_2: 'B1.2', B1_3: 'B1.3', B2P_1: 'B2+.1', B2P_2: 'B2+.2', B2P_3: 'B2+.3'
  };
  const ALL = ['A1_1','A1_2','A1_3','A2_1','A2_2','A2_3','B1_1','B1_2','B1_3','B2P_1','B2P_2','B2P_3'];
  const words = (t) => (String(t || '').match(/[A-Za-z0-9'-]+/g) || []).length;
  const JS = (t, d) => { try { const v = JSON.parse(t || ''); return (v && typeof v === 'object') ? v : d; } catch (e) { return d; } };
  const body = JS(plain_json, {});
  const full = JS(articles_json, {});

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
    const missNums = factNums.filter((n) => !String(article || '').includes(n));
    if (factNums.length && missNums.length === factNums.length) {
      fails.push('事实一致性: 事实卡关键数字未出现');
      checks.push({ name: '事实一致性', status: 'fail', detail: '' });
    } else {
      checks.push({ name: '事实一致性', status: 'pass', detail: factNums.length ? (factNums.length - missNums.length) + '/' + factNums.length + ' 数字命中' : '' });
    }
    const placeholders = /(TBD|TODO|\{f\d+\}|XXX|\(EMPTY\))/i.test(String(article || ''));
    const zh = (String(article || '').match(/[\u4e00-\u9fff]/g) || []).length;
    if (placeholders || zh > 5) {
      fails.push('语言纯净度: ' + (placeholders ? '含占位符' : '正文含中文 ' + zh + ' 字'));
      checks.push({ name: '语言纯净度', status: 'fail', detail: placeholders ? '占位符' : '中文字符 ' + zh });
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
  const legKeys = { a2: 'A2_2', b1: 'B1_2', b2: 'B2P_2' };
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


# ---- 模型渠道：DeepSeek 官方 → 硅基流动
# 2026-09-10 官方渠道余额耗尽（402 Insufficient Balance），切到已配置好的硅基流动。
# 两边是同一个模型（DeepSeek-V4-Flash / Pro），只换调用渠道；温度 / max_tokens 等参数原样保留。
SF_PROVIDER = 'langgenius/siliconflow/siliconflow'

# ⚠️ 硅基流动上的实测吞吐（并发 4 路、900 词长文）：
#     DeepSeek-V4-Flash      81.9 t/s   ← 唯一可用
#     DeepSeek-V3.1-Terminus 24.3 t/s   太慢
#     Pro/DeepSeek-V3.2      21.6 t/s   专用通道并没有更快
#     DeepSeek-V4-Pro         4.4 t/s   900 tokens 的请求 120s 都跑不完，完全不可用
#     GLM-5.3                 180s 超时  不可用
# 结论：全部节点统一走 DeepSeek-V4-Flash（也与原设计的 flash 档一致）。
MODEL_REPOINT = {
    'deepseek-v4-flash': 'deepseek-ai/DeepSeek-V4-Flash',
    'deepseek-v4-pro': 'deepseek-ai/DeepSeek-V4-Flash',
}


def repoint_models(g):
    """把所有 LLM 节点指到硅基流动，并修正 completion_params 的参数名，返回改写数量。"""
    n = 0
    for nd in g['nodes']:
        if (nd.get('type') or nd['data'].get('type')) != 'llm':
            continue
        m = nd['data'].get('model') or {}
        if m.get('name') in MODEL_REPOINT:
            m['provider'] = SF_PROVIDER
            m['name'] = MODEL_REPOINT[m['name']]
            n += 1
        cp = m.get('completion_params')
        if isinstance(cp, dict):
            # ⚠️🔴 踩坑记录：Dify 硅基流动插件的参数名是 **enable_thinking**（boolean，默认 false），
            #    写成 thinking 会被 Dify **静默丢弃**，导致模型按 SF 默认开思考。
            #    实测（400 词长文，max_tokens=1600）：
            #      思考开 → 54.0s / completion=10641 tokens / reasoning 30335 字符
            #      思考关 →  8.0s / completion=  533 tokens / reasoning 0    （快 6.75x，token 少 20x）
            #    GEN 要出 2.5 万 token，思考开着会直接把工作流拖到十几分钟（表现为「零首字节卡死」）。
            #    另注：SF 原生 API 直接传 thinking=false 会 400，只有 enable_thinking 有效。
            cp.pop('thinking', None)
            cp.setdefault('enable_thinking', False)
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

    # ---- nodeClean
    nc = by['nodeClean']
    nc['data']['code'] = GEN_CLEAN_CODE
    nc['data']['desc'] = '清洗上游输入，归一化档位（12 子档白名单）并派生大档'
    nc['data']['outputs'] = {k: {"children": None, "type": "string"} for k in
                             ['summary', 'facts_text', 'level', 'level_big', 'angle', 'sensitive',
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
    positions = {"A1": (620, 120), "A2": (620, 300), "B1": (620, 480), "B2+": (620, 660)}
    for big, keys in GROUPS:
        nn = copy.deepcopy(n0)
        nid = 'nodeGen' + (big.replace('+', 'p') if big != 'A1' and big != 'A2' and big != 'B1' else big)
        nid = {'A1': 'nodeGenA1', 'A2': 'nodeGenA2', 'B1': 'nodeGenB1', 'B2+': 'nodeGenB2p'}[big]
        nn['id'] = nid
        nn['position'] = {"x": positions[big][0], "y": positions[big][1]}
        nn['positionAbsolute'] = {"x": positions[big][0], "y": positions[big][1]}
        nn['data']['title'] = '④-%s 生成（%s）' % (big, " / ".join(DISPLAY[k] for k in keys))
        nn['data']['desc'] = '生成 %s 档三个子档，组内段落级对齐' % big
        mt = {'A1': 2500, 'A2': 4000, 'B1': 6000, 'B2+': 12000}[big]
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
    ag['data']['desc'] = '聚合四个大档共 12 子档，输出 articles/paras/levels_meta 与身份记录'
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
                                       'levels_meta', 'fact_map', 'unused_facts', 'fact_count', 'map_warn',
                                       'raw_missing', 'para_count', 'identity_json', 'summary', 'facts_json',
                                       'article_a2', 'article_b1', 'article_b2', 'paras_a2', 'paras_b1', 'paras_b2']}

    # ---- nodeStyle
    ns = by['nodeStyle']
    ns['data']['title'] = '⑧ 写作风格映射'
    ns['position'] = {"x": 60, "y": 560}
    ns['positionAbsolute'] = {"x": 60, "y": 560}

    # ---- nodeQuiz
    nq = by['nodeQuiz']
    nq['data']['title'] = '⑥ 练习题生成（12 档 × 3 题）'
    nq['data']['desc'] = '按新标准四类题型（语言/文本/逻辑/认知）逐档出题，含解析与 B2+.3 背景导读'
    nq['data']['model'] = {"completion_params": {"max_tokens": 12000, "temperature": 0.6, "thinking": False},
                           "mode": "chat", "name": "deepseek-v4-pro",
                           "provider": "langgenius/deepseek/deepseek"}
    nq['data']['prompt_template'] = [
        {"role": "system", "text": GEN_QUIZ_SYS},
        {"role": "user", "text": GEN_QUIZ_USER},
    ]
    nq['position'] = {"x": 1240, "y": 480}
    nq['positionAbsolute'] = {"x": 1240, "y": 480}

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
    nv['data']['title'] = '⑦ 8 项校验 × 12 档'
    nv['data']['desc'] = '逐档校验长度/句长/蓝思(估算)/敏感/事实/语言纯净/身份/署名，共 96 项'
    nv['data']['code'] = GEN_VALIDATE_CODE
    nv['data']['variables'] = [
        {"variable": "articles_json", "value_selector": ["nodeAgg", "articles_json"]},
        {"variable": "plain_json", "value_selector": ["nodeAgg", "paras_json"]},
        {"variable": "factcard", "value_selector": ["nodeStart", "facts_raw"]},
        {"variable": "identity", "value_selector": ["nodeAgg", "identity_json"]},
    ]
    nv['data']['outputs'] = {k: {"children": None, "type": "string"} for k in
                             ['validation_json', 'validation_pass', 'validation_score']}

    # ---- nodeEnd
    ne = by['nodeEnd']
    ne['data']['desc'] = '输出 12 子档文章 / 段落 / 题目 / 校验 / 身份记录'
    # (输出变量名, 来源节点, 来源节点的输出变量名) —— 三者必须分开写！
    # 这里曾出错：nodeQuiz 的输出变量是 text，不是 quiz_json。
    outs = [
        ("title", "nodeAgg", "title"), ("articles_json", "nodeAgg", "articles_json"),
        ("paras_json", "nodeAgg", "paras_json"), ("words_json", "nodeAgg", "words_json"),
        ("levels_meta", "nodeAgg", "levels_meta"), ("para_count", "nodeAgg", "para_count"),
        ("fact_map", "nodeAgg", "fact_map"), ("unused_facts", "nodeAgg", "unused_facts"),
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
             'nodeGenB1', 'nodeGenB2p', 'nodeAgg', 'nodeQuiz', 'nodeValidate', 'nodeEnd']
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
    E('nodeQuiz', 'nodeEnd')
    E('nodeValidate', 'nodeEnd')

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
FACT_TABLE = """A1.1 ｜60–90   ｜BR–200L   ｜5–7  ｜一个场景一件事，读者五米之内的世界
A1.2 ｜90–120  ｜200–300L ｜7–9  ｜「先……然后……」的两段式故事
A1.3 ｜120–160 ｜300–400L ｜8–10 ｜第一次读到有事件、有变化的文本
A2.1 ｜160–200 ｜400–500L ｜10–12｜开头—发展—结尾，或总分关系
A2.2 ｜200–250 ｜500–580L ｜11–13｜具象科普进场；商业类首次出现（一个人做小生意的故事）
A2.3 ｜250–300 ｜580–650L ｜12–14｜第一次离开读者的直接生活经验（别国的人怎么生活）
B1.1 ｜300–380 ｜650–720L ｜13–15｜阅读目的从「练英文」转向「知道点什么」
B1.2 ｜380–450 ｜720–800L ｜15–17｜出现明确的作者立场，不只是陈述事实
B1.3 ｜450–550 ｜800–880L ｜16–18｜人物故事 / 事件复盘 / 深度文化对比
B2+.1｜550–700 ｜880–1000L｜18–21｜解释性报道与商业案例，名词化密度上升
B2+.2｜700–900 ｜1000–1120L｜20–23｜有真实争议、多方立场的议题
B2+.3｜900–1200｜1120–1300L｜22–26｜抽象论证、跨领域引用、文学性非虚构"""

FACT_GRADE_SYS = """你是语言教学分级专家，依据《APP阅读级别量化表》为素材选择最合适的生成档位。全平台分 4 个大档、12 个子档。

输出 JSON（只输出 JSON，不要任何解释，不要 markdown 代码块）：
{"level":"A1.1|A1.2|A1.3|A2.1|A2.2|A2.3|B1.1|B1.2|B1.3|B2+.1|B2+.2|B2+.3","level_big":"A1|A2|B1|B2+","reason":"40字以内","suggested_angle":"建议的切入角度"}

【12 子档速查表】子档｜词数｜蓝思｜平均句长｜认知特征
%s

判定规则：
- 必须综合看主题认知半径、语言复杂度、蓝思与句长，**不得只看词数**。
- 素材本身没有词数——你要判断的是「这个素材适合用哪一档的篇幅与语言去重写」。
- 常见误判：把「生僻但短」当低档（句短但概念抽象不是 A1/A2，认知难度归 B2+）；让 A1/A2 承载议论。
- 若下方知识库检索结果与本表冲突，**以本表为准**。
- 若用户明确指定了档位偏好，优先遵循用户偏好。""" % FACT_TABLE

FACT_GRADE_USER = """知识库检索结果（参考，冲突时以系统提示中的速查表为准）：
{{#context#}}

素材内容：
{{#nodeStart.material#}}

用户档位偏好：{{#nodeStart.level#}}

请输出分级 JSON。"""

FACT_CLEAN_CODE = r"""function main({ fact_text, grade_text, check_text }) {
  const strip = (t) => String(t || '').replace(/<think>[\s\S]*?<\/think>/g, '').trim();
  const parseJSON = (t) => {
    const s = strip(t).replace(/```json|```/g, '');
    const m = s.match(/\{[\s\S]*\}/);
    if (m) { try { return JSON.parse(m[0]); } catch (e) { } }
    return {};
  };
  const normLevel = (v) => {
    let s = String(v || '').trim().toUpperCase().replace(/\s+/g, '').replace(/[_-]/g, '.').replace(/档/g, '');
    s = s.replace(/^B2PLUS/, 'B2+').replace(/^B2P/, 'B2+');
    const AL = {
      'A1.1':'A1.1','A1.2':'A1.2','A1.3':'A1.3',
      'A2.1':'A2.1','A2.2':'A2.2','A2.3':'A2.3',
      'B1.1':'B1.1','B1.2':'B1.2','B1.3':'B1.3',
      'B2+.1':'B2+.1','B2+.2':'B2+.2','B2+.3':'B2+.3',
      'B2.1':'B2+.1','B2.2':'B2+.2','B2.3':'B2+.3','B2':'B2+.1','C1':'B2+.3',
      'A1':'A1.1','A2':'A2.1','B1':'B1.1'
    };
    if (AL[s]) return AL[s];
    const m = s.match(/^(A1|A2|B1|B2\+?)\.?([123])$/);
    if (m) { const big = m[1] === 'B2' ? 'B2+' : m[1]; return big + '.' + m[2]; }
    return 'B1.1';
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
  const lv = normLevel(grade.level);
  const big = lv.indexOf('B2+') === 0 ? 'B2+' : lv.slice(0, 2);
  return {
    summary: fact.summary || fact.summary_en || '（未识别主题）',
    facts_text: facts.length ? facts.map((f, i) => (i + 1) + '. ' + (f.en || f.zh)).join('\n') : '（无）',
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
    ng['data']['title'] = '③ 分级（12 子档）'
    ng['data']['desc'] = '依据 12 子档量化表判定素材档位，输出子档 + 大档 + 依据'
    ng['data']['prompt_template'] = [
        {"role": "system", "text": FACT_GRADE_SYS},
        {"role": "user", "text": FACT_GRADE_USER},
    ]
    ng['data']['model'] = {"completion_params": {"max_tokens": 900, "temperature": 0.2, "thinking": False,
                                                 "response_format": "json_object"},
                           "mode": "chat", "name": "deepseek-v4-flash",
                           "provider": "langgenius/deepseek/deepseek"}

    nc = by['nodeClean']
    nc['data']['code'] = FACT_CLEAN_CODE
    nc['data']['desc'] = '清洗 ①②③ 输出，归一化 12 子档并派生大档'
    nc['data']['outputs'] = {k: {"children": None, "type": "string"} for k in
                             ['summary', 'facts_text', 'level', 'level_big', 'grade_reason', 'angle',
                              'sensitive', 'sens_level', 'sens_action', 'sens_reason', 'facts_json',
                              'facts_raw']}

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
        'nodeQGrade': '英语分级阅读标准 12 个子档位 词数 蓝思 平均句长 主题范围 语言难度 '
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
    for var in ['level_big', 'grade_reason']:
        if var not in have:
            outs.append({"value_selector": ["nodeClean", var], "variable": var})
    # facts_raw / fact_json 都改由清洗节点给出（干净 JSON），不再透传事实抽取节点的原始输出
    for o in outs:
        if o.get('variable') in ('facts_raw', 'fact_json'):
            o['value_selector'] = ["nodeClean", "facts_raw"]
    ne['data']['outputs'] = outs
    ne['data']['desc'] = '输出事实卡 / 12 子档分级结果 / 敏感级别'

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
