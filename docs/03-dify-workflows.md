# WorkBuddy · Dify AI 工作流说明

> 面向：后端工程师
> ⚠️ **本文档是交接包中最关键的一份**——项目的核心 AI 编排逻辑在 Dify Cloud 上，**不在代码库里**。不读这份文档，你无法理解"三档文章是怎么生成的"。

---

## 0. 重要说明（请先读）

本文档基于项目开发过程中的实际操作记录整理。**生成文档时 Dify 后台无法自动访问**（浏览器调试端口未开启），因此：

- ✅ **输入输出、调用方式、业务语义**：已通过真实 API 调用验证，准确可靠
- ⚠️ **内部节点名称与提示词细节**：基于实现记录整理，**建议你在 Dify 后台打开工作流核对一遍**

请向产品经理索取 Dify 账号访问权限（或导出工作流 DSL）。

---

## 1. 工作流总览

项目共有 **2 个 Dify 工作流**，二者输出字段完全一致（便于前端统一处理）：

| # | 工作流 | App ID | App Key | 用途 | 耗时 |
|---|--------|--------|---------|------|------|
| 1 | **完整工作流** | `466e1815-c5bb-4d50-8437-2fc4768dd4f0` | `app-RVTU8kMk…（已轮换）` | 首次生成：素材 → 抽取 → 排查 → 分级 → 生成 → 校验 | 22–30s |
| 2 | **生成专用** | `f4462032-2919-49e0-b123-bb5160c96c28` | `app-SuBV84EA…（已轮换）` | 换风格重生成：跳过抽取/排查/分级 | 15–20s |

**为什么要拆成两个**：换写作风格时，事实抽取、敏感排查、CEFR 分级这三步的**结果与风格无关**，重跑是浪费。所以把这三步剥离出来，只缓存其结果（`facts`），换风格时直接喂给"生成专用"工作流。

> ⚠️ 实测提速有限（约 20–25%），因为主要耗时在"生成三篇长文"本身。但架构是对的，工程化应保留。

---

## 2. 完整工作流（主流程）

### 2.1 节点结构

```
nodeStart（material / level / style）
    │
    ▼
nodeClean（素材清洗，code 节点）
    │
    ▼
nodeKBSens（敏感知识库检索）
    │
    ▼
nodeCheck（敏感排查，LLM）──► nodeGate（条件分支）
    │                              │
    │                              ├─ S0 → nodeExcluded（终止，status=excluded）
    │                              │
    ▼                              └─ 通过 ↓
nodeKBGrade（分级知识库检索）
    │
    ▼
nodeGrade（CEFR 分级判定，LLM）
    │
    ├──────────────┬──────────────┐
    ▼              ▼              ▼
nodeFact       nodeStyle      （facts 汇总）
(事实抽取 LLM)  (风格映射 code)
    │              │
    └──────┬───────┘
           ▼
      nodeGenAll（三档一次生成，LLM）★核心
           │
           ▼
      nodeAgg（解析 JSON → 文章 + 段落，code）
           │
           ▼
      nodeValidate（8 项质量校验）
           │
           ▼
      nodeEnd（输出）
```

### 2.2 输入变量（nodeStart）

| 变量 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `material` | paragraph（多行文本） | ✅ | 素材正文 |
| `level` | string | ✅ | `A2` / `B1` / `B2` |
| `style` | **select** | ✅ | 见下表 |

**`style` 枚举（8 项）**

| 值 | 风格 |
|----|------|
| `default` | 默认（AI 原生标准分级文，不模仿名人） |
| `hemingway` | 海明威 · 短句克制 |
| `zhuziqing` | 朱自清 · 优美抒情 |
| `ohenry` | 欧·亨利 · 幽默反转 |
| `twain` | 马克·吐温 · 幽默讽刺 |
| `murakami` | 村上春树 · 平静意象 |
| `luxun` | 鲁迅 · 犀利深刻 |
| `shakespeare` | 莎士比亚 · 华丽诗意 |

> ⚠️ **踩过的坑**：`style` 是 select 枚举。新增风格键时，**必须同时修改两处**：① start 节点的 `options` ② `nodeStyle` 代码节点的映射分支。只改一处会导致 `invalid_param` 报错，全流程失败。

### 2.3 输出变量（nodeEnd）

| 变量 | 类型 | 说明 |
|------|------|------|
| `article_a2` / `article_b1` / `article_b2` | string | 三档文章全文 |
| `paras_a2` / `paras_b1` / `paras_b2` | string（JSON 数组） | **对齐段落**，需 `JSON.parse` |
| `para_count` | number | 段落数（当前固定 4） |
| `title` | string | 文章标题 |
| `summary` | string | 素材摘要（供缓存） |
| `angle` | string | 选题角度（供缓存） |
| `level` | string | 实际采用的分级（AI 可覆盖人工选择） |
| `facts_text` | string | 事实文本（供缓存） |
| `facts_raw` | string | 事实 JSON 原文（供缓存） |
| `facts_json` | string（JSON） | 事实卡数组 `[{en, zh}]` |
| `fact_map` | string（JSON） | **段落↔事实卡绑定**，见 §3.6 |
| `unused_facts` | string（JSON 数组） | **未被任何段落引用的事实卡编号**，如 `[4,7]` |
| `fact_count` | number | 事实卡总张数 |
| `validation_score` | number | 校验得分 /8 |
| `validation_pass` | boolean | 是否通过 |
| `validation_json` | string（JSON） | 8 项校验明细 |
| `sensitive_level` | string | `S0`–`S3` |
| `status` | string | `ok` / `excluded` |

---

## 3. ★ 核心：nodeGenAll（三档生成与段落对齐）

这是整个项目**技术含量最高、也最容易踩坑**的节点。

### 3.1 为什么是"一次生成三档"

**历史问题**：最初 A2/B1/B2 由三个独立的 LLM 节点分别生成，导致：

- 三档段落数量不一致（如 A2 3 段、B1 5 段）
- 同序号段落**语义不对应**（A2 第2段讲"规模"、B1 第2段讲"意义"）
- B1/B2 出现小标题而 A2 没有
- 前端展示出现空段

然后靠一个"机械对齐"代码节点去硬拆硬拼，**无法做到语义对齐**。

**当前方案**：合并为**单个 LLM 节点一次生成三档**，在提示词中强制：

1. 三档正文**都恰好 4 段**
2. 各段主题**固定顺序**：第1段引入 / 第2段主体 / 第3段细节 / 第4段收尾
3. **禁止正文内小标题**（标题只出现在首行）
4. 输出**严格 JSON**：`{ title, A2:[4段], B1:[4段], B2:[4段], words:[...] }`

这样段落天然一一对应，无需事后对齐。

### 3.2 模型配置

| 项 | 值 |
|----|----|
| 模型 | `deepseek-v4-pro` |
| max_tokens | `8000` |
| 温度 | 低（保证结构稳定） |

### 3.3 三档难度规范（写入提示词）

| 档位 | 词数 | 平均句长 | 词汇 | 语法 |
|------|------|---------|------|------|
| A2 | 120–250 词 | ≤12 词/句 | Top 2,000 | 简单时态，仅 that 从句 |
| B1 | 150–300 词 | ≤18 词/句 | Top 4,000 | + 被动/现在完成，which/who 从句 |
| B2 | 180–350 词 | ≤25 词/句 | Top 8,000 | + 虚拟/间接引语，名词性从句/分词 |

> **重要产品决策**：难度靠**词汇、语法、长难句**体现，**不靠字数**。三档篇幅相近即可，不必刻意拉开。（此前曾把 B2 设到 550–900 词，导致模型凑字数、质量下降，已下调。）

### 3.4 生词表规范

- 标题**必须**是 `Words and Expressions`（**不能用 `Glossary`**）
- 格式：词条 + 中文释义
- A2 5–8 条 / B1 8–12 条 / B2 12–18 条

> ⚠️ 校验节点的 `stripAux` 正则依赖这个标题来剥离生词表（否则中文释义会被误判为"正文混入中文"而校验失败）。

### 3.5 标题规范

文章**首行为标题**（纯文本或 `# 标题`），后续为正文。前端 `applyLive()` 会提取首行作为标题：

```js
const firstLine = raw.split(/\r?\n/).map(l => l.trim()).find(Boolean) || "";
const title = firstLine.replace(/^#+\s*/, "").replace(/^Title:\s*/i, "").trim() || o.title || "Untitled";
```

### 3.6 ★ 段落↔事实卡绑定（fact_map，2026-09-01 新增）

**背景**：改造前，全部 N 张事实卡整段拼进 `facts_text` 喂给 nodeGenAll，但**没有**「哪一段用了哪张卡」的记录。前端所谓「事实卡引用（自动溯源）」只是把卡池全量罗列一遍，不是真溯源。

**契约**：nodeGenAll 在输出 JSON 中额外输出 `fact_map`：

```json
{"title":"标题","A2":["段1",…],"B1":[…],"B2":[…],"words":{…},
 "fact_map":{"A2":[[1,2],[3],…],"B1":[[1,2],[3],…],"B2":[[1,2],[3],…]}}
```

| 约束 | 说明 |
|------|------|
| 内层数组长度 | 必须等于该档段落数 N |
| 元素 | 该段依据的事实卡编号，**1-based**，对应 `facts_text` 的编号顺序 |
| 每段 | 至少引用 1 张卡；同一张卡可多段引用 |
| 三档 | `fact_map` 必须完全一致（段落本就一一对应） |
| 段数与卡数 | **解耦**：N 仍须落在 8–10，卡多于 N 时一段引多张，**不能让段数等于卡数** |

**nodeAgg 负责**：解析 `fact_map` → 清洗（字符串编号转数字、过滤越界/非法编号、按段数对齐补空数组）→ 输出 `fact_map` / `unused_facts`（未被引用编号）/ `fact_count`。解析失败时 `fact_map` 输出空字符串，前端自动回退为全量罗列，不会中断流程。

**前端消费**：`applyLive()` 解析后写入 `state.factMap`，由 `paraFactIds / factCitedBy / unusedFactIds / factCiteHTML / factTraceHTML` 渲染——正文每段下方显示引用标签、侧栏按段分组溯源、未引用卡标灰告警、s4 卡池标注「被引用 P1/P3」。

> ⚠️ **踩过的坑**：只加「软上限 12 张」后，模型退化成**一卡一段**（12 张卡 → 12 段），违反 8–10 段规格且文章变成事实罗列。必须同时写入「段数 N 与事实卡数量无关」这条约束。实测修复后：11 张卡 → 10 段，校验 23/24。

### 3.7 事实卡数量（nodeFact，2026-09-01 新增）

`nodeFact` 的 system prompt 第 5 条规定 **facts 数量控制在 6–12 条**：超出 12 条时把同主题、同类的相邻事实合并为一条（多个同类数字可并成一句并列句），少于 6 条时把含多信息点的长句拆开。合并不得丢失数字、百分比、专名与时间。

实测：1261 字符的上海电影节稿，改造前抽 17 张，改造后 11 张；生成耗时与覆盖率无退化（关键数字命中 26/26）。

---

## 4. nodeStyle（写作风格映射）

**类型**：code 节点（JavaScript）
**作用**：把 `style` 键映射为一段**英文风格指令**，注入 `nodeGenAll` 的提示词。

**映射逻辑**（示意）
```javascript
function main({ style }) {
  const map = {
    default:     "Write in a clear, neutral editorial style...",
    hemingway:   "Use very short sentences. Few adjectives. State facts...",
    zhuziqing:   "Use lyrical, descriptive prose with vivid imagery...",
    ohenry:      "Build toward a surprising twist ending...",
    twain:       "Use humorous, colloquial, down-to-earth tone...",
    murakami:    "Use calm imagery, negative space, urban detachment...",
    luxun:       "Use sharp, critical, reflective tone with irony...",
    shakespeare: "Use rich, poetic, elevated language...",
  };
  return { style_instruction: map[style] || map.default };
}
```

**关键约束（所有风格共通，务必保留）**：

> 所有事实、人名、数字、结构（标题 / 段落 / 生词表）保持不变，**仅写作风格不同**。风格应随难度自适应：A2 用简单句式呈现风格，B2 完整呈现风格，避免因风格导致 A2 过难。

**前端使用方式**：`nodeGenAll` 的用户提示词中引用 `{{#nodeStyle.style_instruction#}}`。

---

## 5. nodeValidate（8 项质量校验）

| # | 校验项 | 规则 |
|---|--------|------|
| 1 | 长度 | A2 120–250 / B1 150–300 / B2 180–350 词 |
| 2 | 句长 | A2 ≤12 / B1 ≤18 / B2 ≤25 词 |
| 3 | 语言纯净度 | 正文不含中文（**需先剥离 `Words and Expressions` 生词表段**） |
| 4 | 分级一致性 | B2 需包含高阶词汇/句式 |
| 5 | 事实一致性 | 与事实卡一致，无编造 |
| 6 | 段落对齐 | 三档段落数一致且语义对应 |
| 7 | 合规署名 | **已改为 always pass**（原要求文章含"AI 辅助生成"标记，该标记已被产品要求移除） |
| 8 | 敏感内容 | 无敏感表述 |

**输出**
```json
{
  "results": [
    { "level": "A2", "score": 7, "word_count": 165,
      "checks": [ { "name": "长度", "status": "pass" }, ... ] }
  ]
}
```

### ⚠️ 两个已修复的坑（代码里有注释，勿回退）

1. **合规署名误判**：校验曾要求文章含"AI 辅助生成 / AI-assisted"，但该标记已被产品移除 → 8 项校验恒失败。已改为 always pass。
2. **语言纯净度误判**：`stripAux` 剥离生词表的正则只匹配 `Vocabulary|Glossary`，未包含改名后的 `Words and Expressions` → 生词表中文释义被误判为正文中文。已在正则中补入 `Words and Expressions|Words & Expressions`。

---

## 6. 生成专用工作流（换风格提速）

### 6.1 与完整工作流的差异

| 项 | 完整工作流 | 生成专用 |
|----|-----------|---------|
| 输入 | `material` / `level` / `style` | `summary` / `facts_text` / `angle` / `level` / `style` / `facts_raw` |
| 事实抽取 | ✅ 执行 | ❌ 跳过（用传入的 facts） |
| 敏感排查 | ✅ 执行 | ❌ 跳过 |
| CEFR 分级 | ✅ 执行 | ❌ 跳过 |
| 生成 / 校验 | ✅ | ✅ |
| 输出字段 | 完全一致 | 完全一致 |

### 6.2 输入变量

| 变量 | 说明 |
|------|------|
| `summary` | 首次生成时缓存的素材摘要 |
| `facts_text` | 首次生成时缓存的事实文本 |
| `angle` | 选题角度 |
| `level` | `A2`/`B1`/`B2` |
| `style` | 风格键（同完整工作流，8 项） |
| `facts_raw` | 事实 JSON 原文 |

### 6.3 前端触发逻辑（工程化需保留）

```js
const fc = state.factsCache;                       // 首次生成后缓存
const useGen = !!(fc && fc.summary && fc.facts_text);
```

- `useGen === true` → 调生成专用工作流（换风格）
- `useGen === false` → 调完整工作流（首次生成）

`factsCache` 的填充（在 `applyLive()` 中）：
```js
if (o.summary && o.facts_text) {
  state.factsCache = {
    summary: o.summary, facts_text: o.facts_text,
    angle: o.angle, level: o.level,
    facts_raw: o.facts_raw || o.fact_json || ""
  };
}
```

---

## 7. 知识库（Dify Knowledge）

| 知识库 | 内容 | 备份文件 |
|--------|------|---------|
| 敏感内容规则 | S0–S3 分级标准与红线 | `output/dify_kb_backup/敏感内容规则.md` |
| 分级标准 | A2/B1/B2 的词汇/句长/语法/篇幅规范 | `output/dify_kb_backup/分级标准.md` |

> 工程化建议：知识库也应**版本化管理**（当前前端有"KB 版本快照"概念，但为演示数据）。每次生成应记录所用的 KB 版本，便于追溯。

---

## 8. 工程化改造要点

| # | 事项 | 说明 |
|---|------|------|
| 1 | **迁移到团队/服务账号** 🔴 | 当前挂个人 Dify 账号，生产不可用 |
| 2 | **Key 移入服务端环境变量** 🔴 | 绝不能出现在前端 |
| 3 | **改异步调用** | `blocking` 模式 20–30s，生产建议 streaming 或后端任务化 |
| 4 | **加超时与重试** | Dify 偶发超时，需重试与降级 |
| 5 | **加限流** | 生成任务成本高，按用户/租户限流 |
| 6 | **记录调用日志** | 每次生成的输入、输出、耗时、token 消耗 |
| 7 | **导出 DSL 纳入版本管理** | 工作流变更需可追溯 |
| 8 | **保留 facts 缓存设计** | 换风格复用 facts，避免重复抽取 |

---

## 9. 验证方式（后端自测）

用 `app-RVTU8kMk…（已轮换）` 直接调用：

```bash
curl -X POST "https://api.dify.ai/v1/workflows/run" \
  -H "Authorization: Bearer app-RVTU8kMk…（已轮换）" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "material": "Longmen Grottoes: The stone carvings at Longmen near Luoyang were begun in 493 AD...",
      "level": "B1",
      "style": "default"
    },
    "response_mode": "blocking",
    "user": "test"
  }'
```

**预期**：
- HTTP 200，`data.status === "succeeded"`
- `para_count === 4`
- `paras_a2` / `paras_b1` / `paras_b2` 解析后长度均为 4，且**同下标段落语义对应**
- 文章含 `Words and Expressions` 标题
- `validation_score` ≥ 6
- 耗时 22–30s
