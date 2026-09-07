# WorkBuddy AI 内容生产平台 · 数据模型设计

> 面向：后端工程师
> 版本：v1.0（demo 交接版）

---

## 0. 说明

- 数据库建议：**PostgreSQL**（JSONB 支持好，适合存文章/段落/校验明细这类半结构化数据）
- 所有表建议含 `created_at` / `updated_at` / `deleted_at`（软删除）
- 金额/计数类字段用整型；时间统一 UTC 存储
- 本文档给出**建议设计**，字段基于 demo 中实际在用的数据结构推导

---

## 1. ER 概览

```
users ──┬──< sources              （用户自定义信源）
        ├──< materials            （素材）
        ├──< generations          （生成任务）
        │        └──< articles     （三档文章）
        │                 └──< paragraphs   （对齐段落）
        │                 └──< fact_cards   （事实卡）
        ├──< reviews              （审核记录）
        └──< push_logs            （推送记录）

materials ──< generations
kb_versions（知识库版本，独立表）
```

---

## 2. 表结构

### 2.1 users（用户）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | |
| `username` | VARCHAR(64) UNIQUE | 登录名 |
| `password_hash` | VARCHAR(255) | bcrypt/argon2，**禁止明文** |
| `display_name` | VARCHAR(64) | 如"教研老师" |
| `role` | VARCHAR(20) | `source` / `produce` / `review` |
| `scope_from` | SMALLINT | 权限起始步骤（1–13） |
| `scope_to` | SMALLINT | 权限结束步骤 |
| `entry_step` | SMALLINT | 登录后落地页步骤 |
| `status` | VARCHAR(20) | `active` / `disabled` |
| `last_login_at` | TIMESTAMPTZ | |

**demo 对应**：`ROLES` 数组
```js
{id:"source",  name:"市场老师", user:"collect", pass:"123456", from:0, to:4,  entry:0}
{id:"produce", name:"教研老师", user:"produce", pass:"123456", from:0, to:10, entry:5}
{id:"review",  name:"审核老师", user:"review",  pass:"123456", from:0, to:12, entry:11}
```

> ⚠️ demo 中 `from`/`to` 是 0-based 索引，入库建议改 1-based（1–13）便于理解。
> ⚠️ 密码明文 `123456` 必须在工程化时移除。

---

### 2.2 sources（自定义信源）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | |
| `user_id` | BIGINT FK → users | **按用户隔离** |
| `name` | VARCHAR(128) | 信源名称 |
| `type` | VARCHAR(32) | `rss` / `website` / `social` / `other` |
| `url` | VARCHAR(1024) | |
| `last_scan_at` | TIMESTAMPTZ | |
| `last_scan_status` | VARCHAR(20) | `ok` / `failed` / `empty` |
| `enabled` | BOOLEAN | |

**demo 对应**：前端 `SRC_TYPES` + localStorage 存储；抓取走 `/api/scan`。

---

### 2.3 materials（素材）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | |
| `source_type` | VARCHAR(20) | `trend`（热点）/ `owned`（自有版权）/ `public`（公版书） |
| `title` | TEXT | |
| `title_cn` | TEXT | 中文标题（热点为翻译前的原文） |
| `content` | TEXT | 素材正文 |
| `url` | VARCHAR(1024) | 原文链接 |
| `origin` | VARCHAR(128) | 来源名（如"今日头条热搜"、"Hacker News"、"China Daily"） |
| `lang` | VARCHAR(8) | `zh` / `en` |
| `published_at` | DATE | |
| `heat` | SMALLINT | 热度 0–100 |
| `theme` | VARCHAR(32) | 分类主题键 |
| `sub_theme` | VARCHAR(64) | 子主题 |
| `raw` | JSONB | 抓取原始数据（留痕） |

**demo 对应**：热点条目对象（`/api/trends` 返回的 item）

---

### 2.4 generations（生成任务）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | |
| `task_id` | VARCHAR(64) UNIQUE | 对外暴露的任务 ID |
| `user_id` | BIGINT FK | |
| `material_id` | BIGINT FK | |
| `level` | VARCHAR(4) | `A2`/`B1`/`B2`（用户选择） |
| `style` | VARCHAR(32) | 风格键 |
| `workflow_type` | VARCHAR(20) | `full` / `gen_only` |
| `status` | VARCHAR(20) | `pending`/`running`/`succeeded`/`failed` |
| `progress` | SMALLINT | 0–100（可选） |
| `result` | JSONB | Dify 原始输出 |
| `error` | TEXT | |
| `elapsed_ms` | INTEGER | 耗时 |
| `facts_cache` | JSONB | **缓存的 facts，供换风格复用** |
| `kb_version` | VARCHAR(32) | 所用知识库版本 |
| `dify_run_id` | VARCHAR(64) | Dify 运行 ID（追溯） |

**`facts_cache` 结构**（对应 demo `state.factsCache`）
```json
{
  "summary": "素材摘要",
  "facts_text": "事实文本",
  "angle": "选题角度",
  "level": "B1",
  "facts_raw": "事实 JSON 原文"
}
```

> 工程化建议：`facts_cache` 也可独立成表 `fact_bundles`，多个 generation 共享同一份 facts（换风格时复用）。

---

### 2.5 articles（三档文章）

一次生成产出 A2/B1/B2 三篇文章，可存一张表用 `level` 区分，或拆三张子表。建议**单表 + level 字段**。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | |
| `generation_id` | BIGINT FK | |
| `level` | VARCHAR(4) | `A2`/`B1`/`B2` |
| `title` | TEXT | |
| `content` | TEXT | 文章全文（含标题行 + 生词表） |
| `body` | TEXT | 纯正文（剥离标题与生词表，便于检索/统计） |
| `word_count` | INTEGER | |
| `sentence_count` | INTEGER | |
| `avg_sentence_len` | NUMERIC(4,1) | |
| `cover_url` | VARCHAR(1024) | 封面图（对象存储） |
| `validation_score` | SMALLINT | /8 |
| `validation_pass` | BOOLEAN | |
| `validation_detail` | JSONB | 8 项校验明细 |
| `identity` | JSONB | Content ID 与标签 |

---

### 2.6 paragraphs（对齐段落）★

**这张表是产品核心**：三档文章的段落按 `para_index` 一一对齐，读者可切换难度而不丢失阅读位置。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | |
| `article_id` | BIGINT FK | |
| `generation_id` | BIGINT FK | 冗余，便于按生成批次查询 |
| `level` | VARCHAR(4) | `A2`/`B1`/`B2` |
| `para_index` | SMALLINT | **段落序号（1-based），三档同序号语义对应** |
| `content` | TEXT | 段落原文 |
| `content_edited` | TEXT | 人工校对后的内容（NULL 表示未编辑） |
| `edited_by` | BIGINT FK → users | |
| `edited_at` | TIMESTAMPTZ | |
| `word_count` | INTEGER | |

**唯一索引**：`(generation_id, level, para_index)`

**查询"某生成批次第 N 段的三档内容"**：
```sql
SELECT level, content, content_edited
FROM paragraphs
WHERE generation_id = $1 AND para_index = $2
ORDER BY level;
```

**不变量（必须在应用层保证）**：
> 同一 `generation_id` 下，A2/B1/B2 的 `para_index` 集合必须完全一致（当前固定 1–4）。

---

### 2.7 fact_cards（事实卡）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | |
| `generation_id` | BIGINT FK | |
| `seq` | SMALLINT | 序号 |
| `type` | VARCHAR(20) | `EVENT`/`DATA`/`QUOTE`/`BACKGROUND` |
| `stmt_en` | TEXT | 英文事实 |
| `stmt_zh` | TEXT | 中文对照 |
| `confidence` | NUMERIC(3,2) | 置信度（0–1） |
| `anchor` | VARCHAR(255) | 原文锚点（如 "Para 1, Sentence 2"） |
| `cross_check` | VARCHAR(64) | 交叉验证结果 |
| `review_status` | VARCHAR(20) | `auto` / `pending` |

---

### 2.8 reviews（审核记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | |
| `generation_id` | BIGINT FK | |
| `reviewer_id` | BIGINT FK → users | |
| `stage` | VARCHAR(32) | `segment_review`（逐段审核）/ `final` |
| `action` | VARCHAR(20) | `approve` / `reject` |
| `comment` | TEXT | |
| `reviewed_at` | TIMESTAMPTZ | |

> demo 中审核通过后会写入内容库（见下）。

---

### 2.9 library_articles（内容库）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | |
| `content_id` | VARCHAR(64) UNIQUE | Content ID（来自 identity） |
| `generation_id` | BIGINT FK | |
| `title` | TEXT | |
| `level` | VARCHAR(4) | 主档位 |
| `style` | VARCHAR(32) | |
| `material_snapshot` | JSONB | 素材快照 `{label, source, url, text}` |
| `articles` | JSONB | `{A2: "...", B1: "...", B2: "..."}` 三档全文 |
| `paras` | JSONB | `{A2: [...], B1: [...], B2: [...]}` 对齐段落 |
| `facts` | JSONB | 事实列表 |
| `identity` | JSONB | `{contentId, tags}` |
| `reviewed_by` | BIGINT FK | |
| `reviewed_at` | TIMESTAMPTZ | |
| `status` | VARCHAR(20) | `待推送` / `已推送` / `推送失败` |
| `pushed_at` | TIMESTAMPTZ | |

**demo 对应**：`buildBankArticle()`
```js
{
  id: ID.contentId,
  title, level: state.lvl, style: state.style,
  material: { label, source, url, text },
  articles: arts,        // {A2, B1, B2}
  paras: paras,          // {A2, B1, B2}
  facts: [...],
  identity: { contentId, tags },
  createdAt: Date.now(),
  reviewedBy: "审核老师",
  status: "待推送"
}
```

> 💡 **设计建议**：`articles` / `paras` 用 JSONB 存快照（便于推送与归档），同时保留 `generation_id` 关联到规范化表（便于检索与统计）。两张皮，各取所长。

---

### 2.10 push_logs（推送记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | |
| `library_article_id` | BIGINT FK | |
| `target` | VARCHAR(64) | 目标平台标识 |
| `status` | VARCHAR(20) | `success` / `failed` |
| `request_payload` | JSONB | 推送内容（留痕） |
| `response` | JSONB | |
| `error` | TEXT | |
| `pushed_at` | TIMESTAMPTZ | |

> ⚠️ 推送接口的字段映射需内容管理平台侧提供规范。当前 demo 为**模拟推送**。

---

### 2.11 kb_versions（知识库版本）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGSERIAL PK | |
| `kind` | VARCHAR(32) | `grading`（分级标准）/ `sensitivity`（敏感规则） |
| `version` | VARCHAR(32) | 如 `v1.2` |
| `content` | TEXT | 规则原文 |
| `published_at` | TIMESTAMPTZ | |
| `is_active` | BOOLEAN | |

**demo 对应**：`output/dify_kb_backup/*.md`

> 生成时记录所用 KB 版本，保证结果可追溯（demo 中已有"KB 版本快照"概念，但为演示数据）。

---

## 3. 从 localStorage 迁移

demo 内容库存在 `localStorage` 键 `wb_content_bank_v1`，值为文章数组。迁移脚本思路：

```js
// 浏览器控制台执行，导出 JSON
JSON.parse(localStorage.getItem('wb_content_bank_v1') || '[]')
// → 复制结果，后端按 2.9 library_articles 结构入库
```

**字段映射**

| localStorage 字段 | 目标字段 |
|------------------|---------|
| `id` | `content_id` |
| `title` | `title` |
| `level` | `level` |
| `style` | `style` |
| `material` | `material_snapshot` |
| `articles` | `articles` |
| `paras` | `paras` |
| `facts` | `facts` |
| `identity` | `identity` |
| `createdAt`（毫秒时间戳） | `created_at` |
| `reviewedBy` | `reviewed_by`（需映射到 user_id） |
| `status` | `status` |

---

## 4. 枚举字典（供建表与前端下拉框共用）

### 主题 theme（六大主题）
| key | 中文 | 英文 |
|-----|------|------|
| `city` | 城市与日常生活 | City & Daily Life |
| `culture` | 文化与知识 | Culture & Knowledge |
| `travel` | 旅行与社会 | Travel & Society |
| `pop` | 流行文化 | Pop Culture |
| `mind` | 心理与行为 | Mind & Behavior |
| `tech` | 科技与未来 | Tech & Future |

### 子主题 sub_theme（按主题）
```
city:    本地商业 / 街头美食 / 夜生活 / 交通 / 住房
culture: 书籍机构 / 传统节日 / 科学常识 / 艺术 / 语言
travel:  季节迁徙 / 城市交通 / 乡村 / 人口变化 / 民生议题 / 商业思维
pop:     网络趋势 / 音乐 / 影视 / 名人 / 体育 / 游戏
mind:    社会心理 / 习惯养成 / 决策 / 情绪 / 心理健康 / 领导力 / 教育
tech:    AI / 太空 / 机器人 / 能源 / 科普故事 / 前沿科技 / 健康医疗
```

### 风格 style
`default` / `hemingway` / `zhuziqing` / `ohenry` / `twain` / `murakami` / `luxun` / `shakespeare`

### 分级 level
`A2` / `B1` / `B2`

### 敏感等级 sensitive_level
`S0`（排除）/ `S1` / `S2` / `S3`

---

## 5. 索引建议

```sql
-- 段落按生成批次 + 序号查（最高频：切换难度时取三档同序号段落）
CREATE UNIQUE INDEX idx_paras_gen_level_idx ON paragraphs(generation_id, level, para_index);

-- 生成任务：按用户 + 状态 + 时间
CREATE INDEX idx_gen_user_status ON generations(user_id, status, created_at DESC);

-- 内容库：按状态 + 时间
CREATE INDEX idx_lib_status ON library_articles(status, created_at DESC);

-- 素材：按主题 + 发布时间
CREATE INDEX idx_mat_theme ON materials(theme, published_at DESC);

-- 信源：按用户
CREATE INDEX idx_sources_user ON sources(user_id);
```

---

## 6. 数据一致性约束（应用层保证）

| # | 约束 | 说明 |
|---|------|------|
| 1 | **段落对齐不变量** | 同一 generation 下 A2/B1/B2 的 `para_index` 集合必须一致 |
| 2 | **风格枚举同步** | 新增风格键时，Dify start 节点 options 与 nodeStyle 映射必须同时更新 |
| 3 | **生词表标题固定** | 必须是 `Words and Expressions`（校验正则依赖） |
| 4 | **审核前置** | 只有 `reviews` 中存在 approve 记录的文章才可入库 |
| 5 | **推送幂等** | 同一 `library_article_id` 重复推送需幂等（靠 push_logs 判定） |
| 6 | **KB 版本留痕** | 每次生成记录所用 KB 版本，不可回溯修改 |
