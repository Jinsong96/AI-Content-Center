---
name: cefr-card-rewrite
description: 把英文母稿改写成「分级阅读卡片」（逐卡阅读 + 自适应难度降级）并产出 Word 交稿。当用户提到「分级卡片」「阅读卡片」「卡片工具包」「母稿改写」「降级改写」「A1-/A2/B1 三级」「自适应阅读」或给出一篇英文原文要求按难度分级改写时使用。母稿为 B1 → 三级（A1-/A2/B1）；母稿为 B2 → 教研原版四级（A1-/A2/B1/B2）。覆盖：母稿基准与占比换算、切卡规则、build_cards.py 质检、docx 生成、答案字母分布校验、Word 混排母稿的原文提取，以及已踩过的 20 个坑。
agent_created: true
---

# 分级阅读卡片改写（B1 母稿基准）

## 一、这是什么活儿

把一篇英文母稿按难度拆成三级卡片，供学员**逐卡阅读**；学员在某张卡觉得难，下一张就换成低一级的版本，**内容大意不变、只降语言难度**。

- **输入**：英文母稿（本项目为 **B1**），**一字不改**
- **产出**：A1- / A2 / B1 三级卡片 + 每级 3 道题 → **每篇一个 docx**
- 关键机制：三级卡片数相同，**第 N 张卡在每一级讲的都是同一件事** —— 这是"换卡不断内容"的前提

> 教研原版工具包以 **B2+ 为母稿**、输出 A1-/A2/B1/B2+ 四级；本项目母稿是 **B1**，只有三级。口径差异见第四节。

## 二、工作区结构

```
<项目>/
  build_cards.py          # 改造后的脚本（B1 母稿基准）
  extract_from_docx.py    # 从教研《正文与译文汇编.docx》批量提取英文原文
  template.docx           # 教研模板（含 DocTitle / DocLevel / Normal 样式）
  改写规范.md             # 作业基线，改写前对照
  参考_教研项目说明.md    # 教研原始规格
  范本/                   # 教研给的标准范例（以 cards.json 为准）
  articles/j8_NN_<slug>/
    original.txt          # B1 母稿原文（从 docx 提取）
    meta.json             # 标题中英 / 课标主题 / 生词表 / 中译段
    cards.json            # 输出（含 b1_card_starts）
    <标题>.docx           # 脚本生成
    report.txt            # 脚本生成的质检报告
```

跑法：`python build_cards.py articles/<篇名>` 或 `python build_cards.py articles`
**交稿门槛：`report.txt` 必须显示 `✓ 通过`。**

## 三、硬指标（速查）

### 卡片尺寸（按教研范例实测，范例母稿 311–443 词 / 10 卡）
| 级别 | 占母稿 | 每卡词数 | 每卡句数 | 单句上限 | 平均句长 |
|---|---|---|---|---|---|
| A1- | 48–60% | 14–25 | 2–4 | **12** | ~6.5 |
| A2 | 68–80% | 20–32 | 2–3 | **16** | ~10 |
| B1 | 100%（原文） | 母稿字数÷卡数 | — | 只提示 | ~14 |

**约束是"每卡总词数"，不是句长。** 卡片要放进阅读卡片 UI，A1- 一张卡 14–25 词，多 2 倍就放不下。

### 语法白名单
- **A1-**：一般现在/过去、can（含过去式 **could**）、and/but/so/because/then。**禁**从句、被动、if、may/might/must、动名词作主语
- **A2**：+ 现在完成、will、should/must/have to、when/if/because 从句、who/that 短关系从句
- **B1**：原样
- ⚠️ **不要把 `could` 当成超纲词**：允许 `can` 又允许过去时，就等于允许 could。`was not able to` 反而更难（B1–B2），别用它替换 couldn't。

### 专有名词
A1- 全文 ≤3 个；A2 保留主要人名；B1 全保留。

### 保真（最重要）
原文核心观点和事实每一级都要保留；降级只能靠**删细节、换词、拆句**，不能换内容。
不得新增事实、不得改变主体、推测不能写成断言、反问不能写成肯定、作者立场不能改。
选 **3–5 个主题词**写进 `topic_words`，**每一级都必须出现**（不得换成同义简单词）。

### 题目结构（依范例；2026-09-24 补做，此前 4 篇全跑偏；Bryan 当日确认「按范例结构补」）

教研原话「格式和质量都以 `example_honesty/cards.json` 为准」。范例结构（**逐题对位**，不是有一个词义题就行）：

| 位置 | A1- | A2 | B1 |
|---|---|---|---|
| Q1 | **语境词义题** `What does "X" mean in card ⑥?` | **语境词义题** | 细节题（可用 NOT mentioned 型） |
| Q2 | 细节题 | 原因题 | 原因题 |
| Q3 | 原因题 | 细节题 | **作者态度题** `What is the writer's attitude...?` |

样本量 1，但 Bryan 已拍板照此执行。词义题选**正文里出现过、上下文能推断词义**的词（范例：`selfish` / `change`），不选专名。
`audit_a1.py` 已按整条序列校验题型，别再只看 Q1。

### 答案字母分布
每级 3 题、4 选项；**只能依据本级正文出题**，答案必须能在本级正文里找到。
干扰项至少一个来自文中其他位置。
解析固定两句式：`卡片X说"<本级正文原句>"，……所以X正确。X最容易误选，因为……`

**答案字母分布（Bryan 明确要求，脚本已加校验）**：
- 每级 3 题：不能三题同字母，也不能正好 `A/B/C` 字母递增
- 全篇 9 题：四个字母都要出现，单个字母 ≤4 次（参考分布 `C A D` / `D B A` / `B D C`）
- **改字母时必须同步改解析里的字母**（"所以X正确"、"X最容易误选"），选项位置跟着换；解析引用的英文句子不受影响

## 四、占比换算（母稿基准变了就必须重算）

教研原版占比的分母是 **B2+**；母稿换成 B1 后，A1-/A2 的占比必须换算，否则 A2/A1- 会被压得过短、信息大量丢失。

换算依据（教研范例实测）：B1 改写稿 321 词、A2 242 词、A1- 175 词
→ A2/B1 = **75.4%**，A1-/B1 = **54.5%**；且每降一级约 **×0.73–0.75**（B2+→B1 = 72.5%），规律一致。

| 层级 | 教研口径（分母=B2+） | B1 母稿口径 |
|---|---|---|
| A1- | 30–42% | **48–60%** |
| A2 | 48–60% | **68–80%** |
| B1 | 65–78% | **100%（原文不动）** |
| B2+ | 100% | 不存在 |

## 五、切卡

按原文的**信息单元**切 **10 张**（母稿很长时可到 12 张）。
**直接引语不能跨卡** —— 一句引语若跨了自然段，就把这两段合并成一张卡（本项目范例：卡⑨ = 母稿 P9+P10，导致该卡 54 词，属于原文结构决定的，接受）。
`b1_card_starts` = 每张卡开头 4 词，**必须与原文逐字一致**；脚本据此从原文切分并校验"第一张卡从原文开头开始"。

## 六、已踩过的坑（务必避开）

1. **"Mr." 会被当句号拆句。** 脚本的 `sentences()` 正则会在 `Mr. Worth` 处断句，导致句长统计错乱、刷一堆假警告。**已在 `build_cards.py` 加 `ABBR` 缩写保护**（Mr./Mrs./Ms./Dr./Prof./St./Jr./Sr./vs./etc.）。教研原版脚本没有这个保护 —— 换回原版脚本前先补上。
2. **B1 的题目解析只能引用母稿原句**，不能引用改写句。母稿换成 B1 后，原来引用"B1 改写稿"句子的解析会全部校验失败。
3. **引号必须成对**。质检用 `"..."` 切分提取英文引用，解析里引号数量为奇数会错配。每处引用都写成成对的双引号。
4. **解析引用的英文必须与正文逐字一致**（含标点后的空格差异），否则报"在本级正文里找不到"。
5. **占比是硬卡**。先在草稿上跑一遍脚本拿准确词数再调，不要凭感觉估 —— 手算和脚本口径（`[A-Za-z0-9]+(?:['’][A-Za-z]+)?`，`Doesn't` 算 1 词、`Mr.` 算 1 词）容易差几个词，而占比上限卡得很死。
6. **出题时别顺手写成 `A/B/C`**。默认习惯会导致每级都是 A、B、C，学员一眼看出规律。必须在写完 9 道题后回查分布，再按上面的规则调换选项顺序 + 改解析字母。
7. **`could` 在 A1- 是允许的，不是超纲词**（2026-09-24 纠正过一次错误做法）。教研文档 A1- 白名单明写允许 `can`、允许「一般过去时」；过去时叙事里的 can 就是 **could**，`couldn't` 是 A1 最基础的否定式。**相反 `was not able to` 更难** —— be able to 属 B1–B2（只有在 can 缺时态形式时才用它）。所以：
   - A1- 看到 `could not` 不要改；改写成 `was not able to` 是把难度写高了
   - 我只在「could 表推测/虚拟」（`It could rain.`）时才需要人工判断
   - 脚本 `FLAG_WORDS["A1-"]` 里**已删掉 could**，注释里写了不要加回来
8. **A2 单句 ≥5 词、A1- ≥4 词**（`MIN_SENT`，低于才记警告）。4 词的 "He could not walk." 在 A1- 是**合法边界**，不用扩写；A2 里出现 4 词句才要合并。
9. **A2 占比下限 68% 卡得很死**。首稿写到 66% 直接判错。删细节要留余量，**目标落在 72–76% 最稳**；A1- 目标 54–57%（上限 60% 同样紧）。
10. **解析里不要引用含内嵌引号的句子**。母稿常有 `The old man said only, "What will be, will be."`，直接引用会让 `quoted_english` 的引号配对错乱、校验误报。**只引用不含引号的句子**，内嵌引语用中文转述（如"老人只回了一句话"）。
11. 🔴 **`FLAG_WORDS` 是软警告，不是规则 —— 不得为消警告而改内容**（2026-09-24 犯过）。判断超纲的唯一依据是**教研文档白名单**（见上表），不是脚本。反例：把 `could not walk` 改成 `was not able to walk`，反而更难。
12. 🔴 **不得把「推测」写成「断言」**（教研保真条款明禁）。`You might expect this to be a big tree.` ❌ 不能写成 `It is not a big tree.`（既变断言又提前剧透下一卡）；✅ 写 `People think it is a big tree.`（用一般现在时保留悬念层，同时避开 may/might）。A2 的 `You may think...` 同样要换成 `Many people think...`。
13. 🔴 **不得跨卡搬移信息**。第 N 张卡只讲母稿第 N 张卡的内容，不许为凑词数把别卡信息挪过来（犯例：j8_02 A1- 卡⑤ 补了 `They live in groups.`，那是母稿卡③ 的）。跑 `python audit_a1.py` 自查。
14. ⚙️ **不要把"我推的软指引"当验收红线**。教研文档**没有**规定每卡词数/句数；14–25 / 20–32 词/卡是我从范例推的**参考值**，超了不必改内容，只要整篇占比达标。只有教研明文（占比、单句词数、语法白名单、专名数、题目结构）才是红线。
15. **母稿的 `may` 若无法用「人们以为」重构**，用**一般现在时 + not always** 保留模糊层（`things school does not always teach`），别写成断言 `school does not teach`。对应地，`audit_a1.py` 的 `HEDGE_OK` 里收了 `not always`。
16. **题型结构别只看 Q1**。范例是三级九题逐题对位（A1- 词义/细节/原因、A2 词义/原因/细节、B1 细节/原因/态度）；我第一版只补了"Q1 词义 + B1 态度"，A1- Q3、A2 Q2/Q3、B1 Q1/Q2 全跑偏。改完跑 `audit_a1.py`，它现在校验整条序列。
17. **换题型时优先"搬位"而不是"重写"**：现有题目若已是目标题型（如 A2 的原因题），直接移到对应位置保留原文，比新写一道更保真、更省事。只有位置对不上的才新写。
18. **`audit_a1.py` 的跨卡检查要容忍单复数 + 排除主题词**（2026-09-24 修）。原版 `x not in b` 会把两种**正常降级**误报成跨卡搬移：① 母稿 `the insect world`（单数）→ 改写 `insects`；② 母稿用代词 `They're different from us.` → A1-/A2 改成名词 `Insects are different.`（降级时必须把代词补成名词）。修法：加 `_present()`（复数去尾 s 再比）+ 从 `topic_words`（整篇反复出现）里排除关键词。**改完必须做负向测试**：临时把别卡独有的名词（如 `legs`）塞进第 1 卡，确认仍报 `[跨卡嫌疑]` —— 检查没被改坏才算修好。
19. **被动检查会误伤 `is made of`**。`BE_PASSIVE` 的过去分词清单里有 `made`，所以 `The fridge is made of metal.` 会被报被动。教研禁 A1-/A2 被动，直接在改写侧避开（改 `A fridge has a metal body.`），**不要**去放宽 `PASSIVE_OK`。
20. **`could` 在 A2 也合法**（同 A1- 的道理）。要表达母稿的虚拟/条件（`the sun's radiation would easily burn us`）时，A2 用 `could`（`could easily burn us`）比 `would` 安全 —— `would` 不在 A2 白名单里。`although/while/whenever` 同理避开（`although` 在 `FLAG_A2` 里）。
21. **`audit_a1.py` 判「词义题」只看题干措辞**：必须含 `" mean "`（前后带空格）或 `"mean in card"`。写成 `What does X suggest?` / `What can this tell us?` 一律被判成细节题，结构校验直接报错。**B2+ 那级也一样** —— 短语/习语语境义题要写成 `What does "..." mean in card ⑤?`。
22. **解析里的英文引用不许带省略号**。校验做的是「是不是正文的连续子串」，写 `"tooth decay ... has become the main reason"` 必报"在本级正文里找不到"。要引就引**一整段连续文字**。
23. **被动正则会把 `get + 以 en 结尾的词` 误抓**（`the sad feeling you get when the weekend is over` 里的 `get when`）。已把 `when / then / men / women` 加进 `ADJ_OK`（同 `is even` / `is often` 的处理）。遇到新误报先判断是不是「en 结尾的副词/连词」，是就补 `ADJ_OK`，**不要**动被动规则本身。
24. **新闻母稿的引述句几乎都带内嵌引号**（`Lucy Powell said, "These are once-in-a-generation changes ..."`），母稿级（B2+）的解析**不要引用这种句子**。做法：引用**本身不含引号**的句子（数据句、解释句、结尾句），要提引语就写中文转述 + 只截引语之外的连续片段。
25. **文体的连锁反应（新闻 = 被动密集 + 专名密集 + 数字密集）**：A1-/A2 必须把被动全改主动；国名/人名/机构名要做类别化（A1- 专名 ≤3，如英格兰/苏格兰/威尔士/北爱 → "not every part of the UK"）；数字（1,700 trials / 1.7 billion）在 A1- 直接删，A2 可留 1 个最关键的。

## 六之二、母稿来源是 Word（混着译文和注释）

### 已验证的文档骨架（教研《高级N_正文与译文汇编.docx》）

15 篇共享同一骨架，提取零风险：

```
Heading1「N. Title」
「正文」          → 英文段落（要的部分）
「语篇概览」 TABLE → 课标主题 / 文本类型
「难词释义」 TABLE → 生词表
「参考译文」       → 中文标题 + 中文段落
```

**提取规则**：只取「正文」与「语篇概览」之间的段落，**并丢弃含 CJK（中文）的段**。
- 踩过的坑：正文区里可能夹着教研**备注**（如第 13 篇说明"蜘蛛有 8 条腿不属于昆虫"），那是注释不是译文 —— 按 CJK 规则丢掉是对的。
- 成品脚本：`extract_from_docx.py`（读 `word/document.xml`，按 Heading1 分篇 → 落 `original.txt` + `meta.json` → 出 `提取校验.txt`）。
- **必须做独立复核**：统计每篇正文区段数，逐段比对落盘文件与源文档，并报告正文区丢弃了几段中文（正常应为 0 或极少数备注）。

### 通用提取铁律

1. **只取英文段落**：判据 = ASCII 字母占比高、**不含 CJK 字符**；含中文的一律丢
2. 段间用空行分隔，保留原文分段
3. 抽完**逐篇落盘 + 校验**（词数 / 首句 / 尾句 / 是否混入中文），先给 Bryan 一张校验表
4. **提取校验没过就不动笔** —— 结构坑（原文译文逐段交替、注释夹在段中、多篇并成一大段）必须先暴露
5. 提取不干净的少数几篇单独请 Bryan 重发，不连累其它篇
6. 判据优先级：有「原文 / 译文 / Notes」小标题 → 零风险；原文块与译文块整块前后分布 → 低风险；逐段交替 → 靠中英字符判据 + 必须过校验表

## 七、执行顺序

1. 收稿：Word 源先提取原文 → 校验表 → Bryan 确认（若直接给 txt 则跳过）
2. 母稿存 `articles/<篇名>/original.txt`，先统词数 → 定卡数（默认 10）
3. 划卡边界（避开引语跨界）→ 写 `b1_card_starts`
4. 逐卡写 A2 / A1-，逐卡对齐大意
5. 出题：**先看范例的九题结构表，按位出**（能搬位就搬位，别整篇重写）；三级各 3 题，引用句从**本级正文**里摘；写完全篇回查答案字母分布
6. 跑 `build_cards.py`，按 `report.txt` 修到 `✓ 通过`
7. **再跑 `audit_a1.py`**（结构/语义层，build_cards.py 管不到）：
   `python audit_a1.py articles`
   查：**题型结构（整条序列）** / 被动 / 推测语气词 / 推测语气变化 / 跨卡信息搬移 / FLAG 残留。
   脚本在 `scripts/audit_a1.py`。⚠️ 两类误报已加白名单：同义替换（`SYN`：class↔school、oceans↔water、crippled↔bad leg）；「推测语气」那条是**提示**不是判错（母稿的 probably 被删掉=可，被写成事实=需改）。
8. 交 docx；`cards.json` 留在工作区（后续接自适应要用）

## 八、相关脚本参数（`build_cards.py` 顶部）

```python
PROFILES = {
  "B1":  dict(levels=["A1-","A2","B1"],
              ratio={"A1-": (0.48,0.60), "A2": (0.68,0.80)},        # 分母 = B1 母稿
              starts_key="b1_card_starts"),
  "B2+": dict(levels=["A1-","A2","B1","B2+"],
              ratio={"A1-": (0.30,0.42), "A2": (0.48,0.60), "B1": (0.65,0.78)},  # 分母 = B2+ 母稿
              starts_key="b2_card_starts"),
}
MAX_SENT = {"A1-": 12, "A2": 16, "B1": 22}   # 硬判错；母稿那一级不判
MIN_SENT = {"A1-": 4, "A2": 5, "B1": 6}
```

**2026-09-24 起两个脚本都自动识别基准**：`build_cards.py` 与 `audit_a1.py` 看 `cards.json` 的 `levels` 里有没有 `B2+` —— 有就是四级（母稿 B2+），没有就是三级（母稿 B1）。切卡键名两个都认，不用改代码。
改过脚本后**必须双基准回归**：三级跑 `articles`（16 篇应仍全过、audit 0 问题）+ 用 `范本/example_honesty` 跑四级（应 0 问题）。范例是**现成的四级样本**，直接拿它当端到端测试，不要自己造。

## 九、母稿是 B2 时：回到教研原版四级口径（2026-09-24 Bryan 要求）

Bryan 2026-09-24 明确：*「现在我要给你新的文章，是 B2 难度的新闻。母稿如果是 B2 的话，那就按照刚刚教研的 zip 来，记住不要你自己乱加。」*
同日拍板：**最高层标签用「B2+」（跟教研）**、**做四级（每篇 12 题）**。

教研原版脚本 `build_cards_原版_B2+基准_备份.py` 本来就是**四级**，范例也是四级：

```python
LEVELS = ["A1-", "A2", "B1", "B2+"]
RATIO  = {"A1-": (0.30, 0.42), "A2": (0.48, 0.60), "B1": (0.65, 0.78)}  # 分母=母稿
```

范例 `example_honesty/report.txt` 实测：A1- 175 词 40%、A2 242 词 55%、B1 321 词 72%、B2+ 443 词 100%；
切卡键名 **`b2_card_starts`**（且 `levels["B2+"]` 只有 `questions`，没有 `cards` —— 原文从 `original.txt` 切）。

### 四级 vs 三级，只差两处

1. **多一级**：母稿那级（B2+）一字不改，只切卡
2. **母稿那级的题型不同**（教研原话：「A1-/A2 考语境词义和细节；B1 考细节、原因和作者态度；**B2+ 考比喻义推断、段落关系和写作意图**」）

| 位置 | A1- | A2 | B1 | B2+（母稿级） |
|---|---|---|---|---|
| Q1 | 单词语境义题 | 单词语境义题 | 细节题（可用 NOT mentioned 型） | **比喻义/短语语境义题**（范例：`What does the phrase "feather our own nest" most likely mean in card ⑦?`） |
| Q2 | 细节题 | 原因题 | 原因题 | **段落关系题**（范例：`Why does the writer describe being honest with words as "another matter"?` —— 考卡⑧与卡⑨的关系） |
| Q3 | 原因题 | 细节题 | 作者态度题 | **写作意图题**（范例：`What is the main purpose of the final question...?`） |

### ⚠️ B1 到第四级才变成「改写层」，但**不该查被动/FLAG**

教研原文的语法栏是**累加**的：

| 级别 | 语法（教研明文） |
|---|---|
| A1- | 一般现在/过去时、can、and/but/so/because/then；**禁用**从句、may/might/must、if、动名词作主语、**被动** |
| A2 | 加上现在完成、will、should/must/have to、when/if/because 从句、who/that 短关系从句 |
| B1 | 加上 **which/whose、第二类条件句、被动、间接引语、however/although** |

→ 所以 B1 层**允许被动、允许 which**。`audit_a1.py` 的被动/FLAG 检查已限定只跑 **A1- 与 A2**（`STRICT = ("A1-","A2")`）。
我改造时曾一度把检查扩到 B1，结果范例（B1 卡7 有 `being rejected`、卡10 有 `which`）被误报成 2 条问题 —— 用范例回归才发现。**别再把范围放大。**

### 答案分布（范例 12 题实测）

`A1- B/A/C` · `A2 D/A/C` · `B1 D/B/C` · `B2+ B/A/D` → **四个字母各出现 3 次**；
每级内部仍然：三题不同字母、不得 `A/B/C` 递增。脚本校验已扩到 12 题（12 题时要求四字母齐）。

### 其余全部不变

切卡规则、语法白名单、单句词数上限、专名数、主题词、保真四条硬禁忌、解析两句式 —— 与三级完全一致。

### 新闻文体的新增注意点（2026-09-24 实做第 1 篇后补）

- 新闻**被动语态密集**（`was killed` / `is expected to` / `has been sold`），降到 A1-/A2 必须全部改主动句（教研禁 A1-/A2 被动）
- 新闻**时态以一般过去时为主**，A1- 可用；但 `has/have + 过去分词` 只能出现在 A2 以上
- **A1- 要避开现在进行时**：白名单只给「一般现在/过去 + can」，所以 `are cutting` → `cut`、`will die` → `can die`（预测用 can）
- 新闻专名/机构名/地名多 → A1- 全文最多 3 个，其余用类别词替代（**国名类别化是常态**：France/Germany/Japan/UK/US → `rich countries` / `five of them`，这不算改事实）
- 引述句（`said the official` / `according to`）多，**直接引语仍不得跨卡**
- **数字取舍**：保留量级与关键值（`59 countries` / `3%` / `30 million` / `2030`），把次级精度（`24%` / `7.6 million` / `1.4 million`）留在 A2 以上或删掉 —— 属「删细节」，不算改事实
- **A1- 额度很紧**：母稿 345 词 → A1- 只有约 104–145 词（30–42%），每卡 12–14 词。落地写法是「每卡 1–2 个短句，句子 5–11 词」，不要试图塞满
- **新闻没有习语**，教研说的 B2+「比喻义推断」用**语境义推断**替代（如 `defunding`：上文说 cut development assistance，下文用 this level of defunding 指代）→ 需要 Bryan 点头，先按这个做

### 收稿：Bryan 的新闻 docx 骨架（`01 Tax the Super.docx` 系）

与教研《高级N_正文与译文汇编.docx》**不同**：这是**纯英文、无译文、无表格**，一个文件装全部篇目。

```
01 Tax the Super-Rich to Save Lives, Says Report   ← 标题段：数字开头、<90 字符、不以句号结尾
（正文段落，段间空段）
02 Risk of Large-Scale War Rising — UN Report      ← 下一篇标题
...
```

成品脚本：`extract_news.py`（判据：`^\d{1,2}\s+\S` + 长度 <90 + 不以 `.` 结尾 → 标题；其余非空段归入当前篇；含 CJK 的段丢弃）。
输出 `articles/news_NN_<slug>/original.txt` + `meta.json`，并打印校验表（段数/词数/丢中文数/首句）+ **缺号检测**。
⚠️ 该批实测**文件里只有 14 篇（缺第 11 号）**，Bryan 说 15 篇 —— 提取后一定跑缺号检测并当场报告。

---

## 高级7（B1 母稿 → 三级）批量实做补充 —— 坑 26–31（2026-09-24）

15 篇全部通过：`build_cards.py` 45/45 篇 ✓、`audit_a1.py` 问题 0 条。
占比落地区间：**A1- 49–57%、A2 69–80%**；卡数 10（j7_02 11、j7_04/12/14 11–12）。

### 26. A1- 的 FLAG 词表含 `would` 与 `if` —— 母稿整句要重写

`FLAG_A1 = may/might/if/which/whose/who/would/been/should/must/although/however/while`。
母稿常见的 `he would die` / `if he were free` / `who was considered` **不能只换主语**，整句降成一般现在/过去：

- `They thought you would die after eating one.` → `They were afraid to eat them.`
- `The reason is because ... if I were to let him out ... he would leave me.` →
  A1-：`He did not want the lion to leave.`（A2 才保留 `if` + `would`）
- `who will volunteer ...` → A1-：`But can you put the bell on the cat?`（`can` 可用）

### 27. 反被动要自己读一遍，不能只信「没报警」

会被正则抓的形态（都要改主动）：`was shocked`（**ADJ_OK 只放行了 surprised，没收 shocked**）、
`was named after`、`would be warned`、`was called`、`stars being born`（`being + born`）、`is made up of`、`was treated like`。
**抓不到**的：`was never locked`（`be + 副词 + 分词`，正则要求 be 后紧跟分词）→ 会漏。
结论：**A1-/A2 定稿前人工扫一遍被动，别把「脚本没报」当通过**。

### 28. 短句下限（最短句逐句卡）—— 高频踩坑清单

A1- ≥4 词、A2 ≥5 词。这一批实际撞到的：
`Not always.`(2) · `He said no.`(3) · `It is simple.`(3) · `There was silence.`(3) · `Not even Bill.`(3) · `The other mice agreed.`(4) · `The prince laughed again.`(4) · `He hated the lion.`(4)
→ 处理：**合并进邻句**（`No one knew the answer, not even Bill.`）或加一个实词（`The other mice all agreed.`）。

### 29. topic_words 必须按**原形**在本级文本出现

写 `galaxy` 时若本级只有 `galaxies`，脚本判「A1- 缺少主题词 galaxy」（`galax` 不算命中）。
→ 保证本级至少一处出现原形（A1- 卡③ 写成 `Our galaxy has a name.`）。

### 30. 引语密集的寓言/故事：卡长会很大，不要为压卡长而拆引语

「一段连续引语不跨卡」优先于卡长。j7_13/j7_15 出现 40–55 词的卡（母稿级只查**句长**不查**卡长**），
这是原文对话结构决定的，属正常。切卡顺序按「说话人 + 话题」分段，**不要在引语中间下刀**。

### 31. 「不得字母递增」是三题整体判 —— `A/B/D` 也算递增

脚本判 `A/B/D` 为「呈字母递增，规律可猜」（不是只看 `ABC`）。
三级安全排法示例：`A1- D/B/A` · `A2 C/A/B` · `B1 D/B/A`；全篇 9 题仍要四字母齐、单字母 ≤4。

### 32. 与早前篇目撞稿要去重（省钱省时）

j7_06 `Growing Lesson` 与 `articles/01_bean_plant` 是**同一篇母稿**（分段略不同）：
直接复用已有 `cards.json` 的改写内容，只换标题与切卡重挂即可。
→ 新批次开工前，先按 `original.txt` 的首句/主题**快速比对已有篇目**，命中就复用。
