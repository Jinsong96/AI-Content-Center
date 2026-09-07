# WorkBuddy AI 内容生产平台 · 接口文档

> 面向：后端工程师
> 版本：v1.0（demo 交接版）

---

## 0. 概览

本文档分两部分：

- **Part A｜现状接口**：demo 当前实际在调用的接口（前端直连 / 本地桥接层）。用于理解现有实现。
- **Part B｜目标接口设计**：工程化后「前端 ↔ 自家后端」的接口建议。这是后端需要实现的。

---

# Part A｜现状接口（demo 实际调用）

## A1. Dify 完整工作流

```
POST https://api.dify.ai/v1/workflows/run
Authorization: Bearer app-RVTU8kMk…（已轮换）
Content-Type: application/json
```

**请求体**
```json
{
  "inputs": {
    "material": "素材正文（前端截取前 4800 字符）",
    "level": "B1",
    "style": "default"
  },
  "response_mode": "blocking",
  "user": "frontend-demo"
}
```

**入参说明**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `material` | string | ✅ | 素材正文。前端 `material.slice(0, 4800)` |
| `level` | string | ✅ | `A2` / `B1` / `B2` |
| `style` | string | ✅ | `default` / `hemingway` / `zhuziqing` / `ohenry` / `twain` / `murakami` / `luxun` / `shakespeare` |

⚠️ `style` 为 Dify start 节点的 **select 枚举**，传未定义值会报 `invalid_param`（曾因漏加 `default` 导致全流程失败）。

**响应体（成功）**
```json
{
  "task_id": "...",
  "data": {
    "id": "...",
    "status": "succeeded",
    "outputs": {
      "article_a2": "A2 全文（含标题行 + 正文 + Words and Expressions 生词表）",
      "article_b1": "...",
      "article_b2": "...",
      "paras_a2": "[\"段落1\", \"段落2\", \"段落3\", \"段落4\"]",
      "paras_b1": "...",
      "paras_b2": "...",
      "para_count": 4,
      "title": "文章标题",
      "summary": "素材摘要",
      "angle": "选题角度",
      "level": "B1",
      "facts_text": "事实文本（供缓存）",
      "facts_raw": "事实 JSON 原文（供缓存）",
      "facts_json": "[{\"en\":\"...\",\"zh\":\"...\"}]",
      "validation_score": 7,
      "validation_pass": true,
      "validation_json": "{\"results\":[{\"level\":\"A2\",\"score\":7,\"word_count\":165,\"checks\":[...]}]}",
      "sensitive_level": "S1",
      "status": "ok"
    },
    "elapsed_time": 24.2
  }
}
```

**关键输出字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| `article_{a2,b1,b2}` | string | 三档文章全文。**首行为标题**，正文后接 `Words and Expressions` 生词表 |
| `paras_{a2,b1,b2}` | JSON string | **对齐后的段落数组**（需 `JSON.parse`）。三档长度一致（当前固定 4 段），同下标段落语义对应 |
| `para_count` | number | 段落数 |
| `facts_text` / `facts_raw` | string | 供前端缓存，换风格时复用（跳过抽取/排查/分级） |
| `validation_json` | JSON string | 8 项校验明细（长度、句长、语言纯净度、分级一致性、事实一致性、段落对齐、合规署名、敏感内容） |
| `status` | string | `ok` 或 `excluded`（素材被敏感排除） |
| `sensitive_level` | string | `S0`–`S3` |

**敏感排除场景**：`outputs.status === "excluded"` 时，前端终止流程，提示更换素材。

**失败响应**
```json
{ "code": "invalid_param", "message": "style must be one of [...]", "status": 400 }
```

⏱ **耗时**：约 22–30 秒（`blocking` 同步模式）

---

## A2. Dify 生成专用工作流（换风格提速）

```
POST https://api.dify.ai/v1/workflows/run
Authorization: Bearer app-SuBV84EA…（已轮换）
```

**请求体**
```json
{
  "inputs": {
    "summary": "首次生成时缓存的摘要",
    "facts_text": "首次生成时缓存的事实文本",
    "angle": "选题角度",
    "level": "B1",
    "style": "luxun",
    "facts_raw": "事实 JSON 原文"
  },
  "response_mode": "blocking",
  "user": "frontend-demo"
}
```

**与完整工作流的差异**：跳过了「事实抽取 / 敏感排查 / CEFR 分级」三个 LLM 步骤，只跑「生成 + 对齐 + 校验」。

**输出字段**：与 A1 完全一致（便于前端统一处理）。

⏱ **耗时**：约 15–20 秒（比完整流程快约 20–25%）

**前端触发逻辑**
```js
const fc = state.factsCache;
const useGen = !!(fc && fc.summary && fc.facts_text);
// useGen=true  → 走生成专用工作流（换风格）
// useGen=false → 走完整工作流（首次生成）
```

---

## A3. 硅基流动 · 文生图封面

```
POST https://api.siliconflow.cn/v1/images/generations
Authorization: Bearer sk-fsnxdacb…（已轮换）
Content-Type: application/json
```

```json
{
  "model": "Kwai-Kolors/Kolors",
  "prompt": "构图描述（英文，由主题元素拼装）",
  "image_size": "1024x1024",
  "batch_size": 1
}
```

**响应**：`data[0].image_url`（或 base64）。失败时前端回退到主题预置封面图 `covers/*.png` + 渐变。

---

## A4. 硅基流动 · 中文标题翻译

```
POST https://api.siliconflow.cn/v1/chat/completions
Authorization: Bearer sk-fsnxdac...
```

```json
{
  "model": "deepseek-ai/DeepSeek-V4-Flash",
  "messages": [{
    "role": "user",
    "content": "请把下面的中文新闻标题翻译成地道英文，并写一句客观的英文背景摘要...严格按 JSON 返回：{\"en\":\"...\",\"brief\":\"...\"}"
  }],
  "temperature": 0.2,
  "max_tokens": 200
}
```

⚠️ **性能**：单条约 9.5 秒。桥接层用 8 线程并发 + 磁盘缓存（`.toutiao_en_cache.json`）缓解。

---

## A5. 本地桥接层（Agent-Reach Bridge）

**Base URL**：`http://127.0.0.1:8787`
**启动**：`python3 output/backend/agent_reach_bridge.py [端口]`
**CORS**：已开 `Access-Control-Allow-Origin: *` 与 `Access-Control-Allow-Private-Network: true`

### GET /api/health
```json
{ "ok": true, "name": "agent-reach-bridge", "time": 1788163828 }
```

### GET /api/trends
| 参数 | 说明 |
|------|------|
| `theme` | `all` / `city` / `culture` / `travel` / `pop` / `mind` / `tech` |
| `sub` | 子主题（可选） |

**响应**
```json
{
  "ok": true, "theme": "tech", "sub": null,
  "items": [
    {
      "topic": "Will Unitree Become the Next Apple or Tesla?",
      "cn": "宇树会成为下一个苹果或特斯拉吗",
      "theme": "tech",
      "sub": "机器人",
      "source": "今日头条热搜",
      "url": "https://www.toutiao.com/trending/...",
      "summary": "英文背景摘要（头条无正文，AI 生成兜底）",
      "fulltext": "同 summary",
      "date": "2026-09-01",
      "ts": 1788163828,
      "hot": 4521000,
      "heat": 95,
      "srcs": 1,
      "lang": "zh"
    }
  ]
}
```

**字段说明**

| 字段 | 说明 |
|------|------|
| `topic` | 标题。中文热点为**翻译后的英文**；英文源为原文 |
| `cn` | 中文标题（仅中文热点有） |
| `theme` / `sub` | 分类标签（中文热点用中文 `cn` 字段分类，避免英文歧义） |
| `fulltext` / `summary` | 素材正文。**头条无正文，用 AI 摘要兜底** |
| `lang` | `zh` / `en` |
| `heat` | 热度 0–100（展示用） |

⏱ **耗时**：首次 20–40 秒（含翻译），缓存命中后约 19 秒。

### GET /api/scan
| 参数 | 说明 |
|------|------|
| `urls` | 逗号分隔的信源 URL（自定义信源抓取） |

自动发现 RSS（网页 `<link rel="alternate">`），抓不到则返回 `items: []`。

---

# Part B｜目标接口设计（后端需实现）

> 以下为**建议设计**，供后端参考。所有接口需鉴权（JWT），统一前缀 `/api/v1`。

## B1. 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/login` | 登录，返回 JWT |
| POST | `/auth/logout` | 登出 |
| GET | `/auth/me` | 当前用户 + 角色 + 权限范围 |

```json
// POST /auth/login
{ "username": "produce", "password": "..." }
→ { "token": "eyJ...", "user": { "id": 1, "role": "produce", "scope": [1,11] } }
```

## B2. 素材与热点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/trends?theme=&sub=&page=&size=` | 热点列表（后端抓取 + 缓存，前端不再直连桥接层） |
| POST | `/trends/refresh` | 手动触发刷新 |
| GET | `/sources` | 当前用户的自定义信源列表 |
| POST | `/sources` | 新增信源 `{ name, type, url }` |
| DELETE | `/sources/:id` | 删除信源 |
| POST | `/sources/:id/scan` | 扫描指定信源 |

## B3. 生成（**核心，必须异步化**）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/generations` | 提交生成任务，返回 `taskId` |
| GET | `/generations/:taskId` | 查询任务状态与结果 |
| GET | `/generations?status=&page=` | 生成历史 |
| POST | `/generations/:id/regenerate` | 换风格重生成（复用已缓存 facts） |

```json
// POST /generations
{
  "materialId": "可选，已有素材ID",
  "material": "素材正文（或直接传入）",
  "level": "B1",
  "style": "hemingway"
}
→ { "taskId": "gen_xxx", "status": "pending" }
```

```json
// GET /generations/:taskId
{
  "taskId": "gen_xxx",
  "status": "running",          // pending | running | succeeded | failed
  "progress": 60,               // 可选进度
  "result": {                   // succeeded 时返回
    "articles": { "A2": "...", "B1": "...", "B2": "..." },
    "paras":    { "A2": ["..."], "B1": ["..."], "B2": ["..."] },
    "paraCount": 4,
    "title": "...",
    "validation": { "score": 7, "pass": true, "details": [...] },
    "facts": [ { "en": "...", "zh": "..." } ],
    "coverUrl": "https://..."
  },
  "error": null
}
```

**实现要点**
- 后端内部调用 Dify（blocking 或 streaming），前端**不直连 Dify**。
- 生成耗时 20–30s，**必须异步**（任务队列 + 前端轮询或 SSE/WebSocket 推送）。
- 建议后端缓存 `facts`（对应 demo 的 `factsCache`），换风格时走"生成专用"工作流。
- Dify Key 只存服务端环境变量。

## B4. 文章与段落

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/articles/:id` | 文章详情（三档全文 + 段落） |
| PATCH | `/articles/:id/paras` | 人工校对，更新段落内容 |
| POST | `/articles/:id/confirm-align` | 对齐确认 |
| GET | `/articles?status=&page=` | 文章列表 |

## B5. 审核与内容库

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/reviews/pending` | 待审核列表 |
| POST | `/articles/:id/review` | 提交审核 `{ action: "approve" \| "reject", comment }` |
| GET | `/library?status=&page=` | 内容库（已入库文章） |
| DELETE | `/library/:id` | 删除 |
| POST | `/library/:id/push` | 推送至内容管理平台 |

```json
// POST /library/:id/push
→ { "pushed": true, "targetId": "外部平台ID", "pushedAt": "..." }
```

> ⚠️ 推送接口需内容管理平台侧提供对接规范（地址、鉴权、字段映射）。**当前 demo 为模拟推送**（仅改本地状态为"已推送"）。

## B6. 元数据

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/meta/themes` | 六大主题 + 子主题（对应前端 `DIRS`） |
| GET | `/meta/levels` | A2/B1/B2 分级规范（对应 `SPECS`） |
| GET | `/meta/styles` | 写作风格列表（默认 + 7 位名人） |
| GET | `/meta/kb?version=` | 知识库版本（分级标准 / 敏感规则） |

---

## 附录 A：统一错误码建议

| HTTP | code | 说明 |
|------|------|------|
| 400 | `INVALID_PARAM` | 参数错误 |
| 401 | `UNAUTHORIZED` | 未登录 / token 失效 |
| 403 | `FORBIDDEN` | 角色权限不足 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `CONFLICT` | 状态冲突（如已审核后重复审核） |
| 429 | `RATE_LIMITED` | 触发限流（生成任务尤需注意） |
| 500 | `INTERNAL` | 服务内部错误 |
| 502 | `UPSTREAM_ERROR` | 上游失败（Dify / 硅基流动 / 新闻源） |
| 504 | `UPSTREAM_TIMEOUT` | 上游超时（Dify 生成超时） |

**统一响应包裹**
```json
{ "code": "OK", "data": { ... }, "message": "" }
```

---

## 附录 B：工程化改造对照表

| demo 现状 | 目标 |
|-----------|------|
| 前端直连 Dify（key 在前端） | 前端 → 自家后端 → Dify（key 在服务端环境变量） |
| 同步 blocking 调用（20–30s 阻塞） | 异步任务 + 轮询/SSE |
| 前端直连硅基流动（key 在前端） | 后端代理 |
| 前端直连 `127.0.0.1:8787` | 后端服务化，部署公网 |
| 内容库存 localStorage | 数据库 |
| 无鉴权 | JWT + RBAC |
| 无分页 | 所有列表接口支持 `page` / `size` |
