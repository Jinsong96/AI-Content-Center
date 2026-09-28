# 金标准 · example_honesty（《How honest are you?》）

> **这不是裁判的输出，是人工逐卡核对的结果。**
>
> 用途：拿 DeepSeek 跑 `裁判提示词-v0-无判据版.md`，用它的输出和本文对照，算出**漏报 / 误报**。
> 方法：把 A1- / A2 / B1 的每一张卡，与 B2+ 原文对应的卡逐句比对；题目单独核对。
> 核对人：AI（非教研）。**P0 项我确信；P1 项依赖教研口径，可能偏严。**

---

## 输入概况

- 原文 **450 词**，按 `b2_card_starts` 切成 **10 张卡**
- A1- 175 词（40%）· A2 242 词（55%）· B1 321 词（72%）
- 每级 3 道题，共 12 道

---

## 一、真问题（裁判应该报出来）

### 🔴 P0-1 · A1- 卡⑥ 改动了事实

| | |
|---|---|
| 原文（卡⑥） | `if we gain an advantage over the people around us, we have a greater chance of surviving` |
| A1- 卡⑥ | `Dishonest people get more than others. So they live longer.` |

**问题**：`a greater chance of surviving`（**存活概率更大**）被写成 `live longer`（**寿命更长**）。两者不等价——"更可能活下来"和"活得更久"不是一回事。

**加重情节**：A2 卡⑥ 保留得**正确** —— `we have a better chance to survive`。所以这个偏差是 **A1- 单独引入的**，不是原文的问题。

---

### 🔴 P0-2 · 这个错误传导进了题目（脚本查不出）

- A1- Q3 题干：`Why do dishonest people live longer, according to the text?`
- 答案：C `Because they get more than other people`

**问题**：题干和答案**都建立在 P0-1 的错误事实上**。一旦把 A1- 卡⑥ 改对，这道题直接作废。

**为什么这条特别重要**：脚本**抓不到它**。脚本只校验"解析里引用的英文是否逐字存在于本级正文"——而这句引用（`Dishonest people get more than others. So they live longer.`）**逐字都在**。**错误被格式合法性掩盖了。**

---

### 🔴 P0-3 · A1- 把人名泛化，跨级接不上

| 位置 | B2+ / A2 / B1 | A1- |
|---|---|---|
| 卡② | `Benjamin Franklin` | **`A man`** |
| 卡⑤ | `Philip Graves, a psychologist` | **`A scientist`** |

**问题**：
1. 读者从 B1 卡② 降到 A1- 卡② 时，接不上"这个人是谁"。
2. 违反佳阳老师已确认的规则——应写成 `Graves, a scientist` 这种形态，**保留名字 + 同位语说明身份**，而不是泛称替代。

---

## 二、次要问题（报出来算加分，不报不算漏）

### 🟡 P1-1 · A1- 卡⑦ 的 "balance" 没有说明平衡的是什么

- A1- 卡⑦：`A world of dishonest people is not nice. So we need a balance.`
- 对比 A2 卡⑦：`We can help ourselves, but we should not lose our place in the group.`
- 对比 B1 卡⑦：`we need to find a balance between helping ourselves and the risk of being rejected by the group`

**问题**：A1- 只说"需要平衡"，**没说平衡的两端是什么**。读者不知道在平衡什么。
**但注意**：这不属于"事实错误"，属于"可读性/信息完整度"。是否要修，取决于教研对 A1- 的要求。

### 🟡 P1-2 · A1- 和 A2 丢掉了 "another matter" 的对比关系

- 原文卡⑨：`Being trustworthy with money is ... crucial ... But being honest with words is **another matter**`
- B1 保留了对比：`But being honest with words is **a different matter**`
- A1- 卡⑨：`But true words can bring trouble.` ← 对比关系丢失
- A2 卡⑨：`But when we say what we really think, we can get into trouble.` ← 同样丢失

**问题**：原文的论证是"金钱上的诚实有法律保护 ✓ / 言语上的诚实会惹麻烦 ✗"的**对照**；A1-、A2 把转折简化掉了，只剩后半。**注意 B2+ 恰好有一道题考这个对比**（Q2），说明它在原文里是重点。

### 🟡 P1-3 · B2+ Q2 的解析把卡片编号写错了

- 解析原文：`**卡片⑧**说金钱上的诚实对社会至关重要且有法律保护；**卡片⑨**紧接着说"saying what we think to someone can get us into hot water"。`
- 实际：`Being trustworthy with money ... laws to protect us` 和 `hot water` **都在原文卡⑨里**。卡⑧讲的是"平衡"（`feather our own nest` / `ostracised`）。

**问题**：解析里的卡片编号错位，学生按编号去原文找会找不到。
**脚本抓不到**（编号不是"英文引用"，不在校验范围）。

### 🟡 P1-4 · A2 丢了 Franklin 的身份

- 原文卡②：`American statesman, Benjamin Franklin`
- A2 卡②：`Benjamin Franklin wrote these words in the 1700s.` ← 名字在，**身份没了**

**问题**：初中生读到"Benjamin Franklin"不知道他是谁。是否要保留身份，取决于教研口径。**我倾向"应该保留"**（用户明确要求保留关键信息），但不算硬伤。

---

## 三、容易被误报的地方（⚠️ 裁判报了 = 误报）

**这一节是专门用来测误报的。** 以下是"看起来像问题、其实不是"的项。

| 看起来像问题 | 为什么不是 |
|---|---|
| A1- 卡⑥ **把原文卡⑥+卡⑦合并了** | A2、B1 **在同一位置做了同样的合并**（都合并了"进化能力"+"为什么诚实重要"）→ 第 6 张卡在四级讲的仍是同一件事，**卡片没错位** |
| 卡⑨/卡⑩ 边界与原文切分不齐 | A1-、A2、B1 **三级处理完全一致**，跨级接得上 |
| `unscrupulous` → `cheat`（三级都改了） | 三级一致；且 `unscrupulous` 对 A1-/A2 确实超纲，**这是必要的降级** |
| `corruption and fraud` → `money crimes`（A2） | 合理解释性简化，符合"降级只能靠删细节、换词、拆句" |
| A1- 只留 1 个例子（抄作业），B1 留了 3 个 | 例子的取舍属细节，非核心事实；卡片数对齐 |
| A1- 卡② 把 `in the 1700s` 写成 `about 300 years ago` | 换算准确（1700s 距今约 300 年） |
| A1- 卡④ 只写 `shops`，原文是 `shops and car parks` | 细节删减，不影响大意 |

**裁判只要报了上面任何一条，就要在"误报"栏 +1。**

---

## 四、理想裁判应有的输出（标准答案 JSON）

把下面这份内容和 DeepSeek 的原始输出直接对比即可。

```json
{
  "findings": [
    {
      "level": "A1-",
      "location": "卡6",
      "type": "fact_altered",
      "original": "if we gain an advantage over the people around us, we have a greater chance of surviving",
      "rewritten": "Dishonest people get more than others. So they live longer.",
      "why": "原文说的是存活概率更大，改写成了寿命更长，两者不等价。A2 版保留了原文意思（a better chance to survive），说明是 A1- 单独引入的偏差。"
    },
    {
      "level": "A1-",
      "location": "题3",
      "type": "question_based_on_wrong_fact",
      "original": "（对应卡6的正确表述：we have a greater chance of surviving）",
      "rewritten": "Why do dishonest people live longer ...? 答案 C：Because they get more than other people",
      "why": "题干和答案都建立在卡6的错误事实上，改对正文后此题作废。"
    },
    {
      "level": "A1-",
      "location": "卡2 与 卡5",
      "type": "bridge_broken",
      "original": "Benjamin Franklin（卡2）／ Philip Graves, a psychologist（卡5）",
      "rewritten": "A man（卡2）／ A scientist（卡5）",
      "why": "人名被泛化。读者从 B1 降到 A1- 时无法知道这个人是谁，跨级接不上。"
    },
    {
      "level": "A1-",
      "location": "卡7",
      "type": "information_dropped",
      "original": "There is a balance to strike between ... feather our own nest ... and the risk of being ostracised by the group",
      "rewritten": "So we need a balance.",
      "why": "只说需要平衡，没说平衡的两端是什么，读者无法理解。"
    },
    {
      "level": "B2+",
      "location": "题2的解析",
      "type": "reference_error",
      "original": "Being trustworthy with money ... 与 saying what we think ... hot water 均在卡9",
      "rewritten": "解析写作“卡片⑧说金钱上的诚实……”",
      "why": "卡片编号错位，学生按编号找不到对应内容。"
    }
  ],
  "conclusion": "共发现 5 处问题"
}
```

---

## 五、计分表（跑完填这里）

| 指标 | 定义 | 结果 |
|---|---|---|
| **漏报** | 第一节 P0 共 3 条，裁判报出几条 | ___ / 3 |
| **加分** | 第二节 P1 共 4 条，裁判报出几条 | ___ / 4 |
| **误报** | 第三节共 7 条，裁判误报几条 | ___ / 7 |
| **新增发现** | 裁判报的、上面都没列到的（可能是真发现，也可能是新误报） | ___ 条，逐条人工判 |

**判定线（我的建议）**：
- 漏报 P0 = 0，且误报 ≤ 1 → v0 可用，直接进下一阶段
- 误报 ≥ 3 → 说明"只报确定的"这条约束不够，需要给 v0.2 加"双向引用"要求
- 漏报 P0 ≥ 2 → 说明需要 v0.1 的"事实逐条比对"流程约束
