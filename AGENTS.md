# AGENTS.md — ReadPal 内容生产平台 · AI 协作约定

> **本文件给 AI 助手读。任何新会话（换电脑 / 换 WorkBuddy 账号 / 新 agent）动工前请先读完。**
> 仓库即唯一真源，本文件不含任何本机绝对路径，换任何设备都适用。
> 最后更新：2026-09-10

---

## 0. 三十秒速览

| 项 | 值 |
|---|---|
| 项目 | **ReadPal**（**无空格**；写成 `Read Pal` 是错的）AI 英语分级阅读内容生产平台 |
| 形态 | 单文件前端 + 零依赖 Python 后端（bridge），前后端同域 |
| 代码仓库 | `https://github.com/Jinsong96/AI-Content-Center`（main 分支） |
| 线上站点 | Railway，推 GitHub 后**自动部署**（约 90 秒） |
| 前端真源 | `frontend/index.html`（约 68 万字符，所有页面/JS/CSS 全在里面） |
| 后端真源 | `backend/agent_reach_bridge.py` |
| 部署文档 | `RAILWAY_DEPLOY.md`（含 10 条故障排查） |
| 设计文档 | `docs/01` ~ `docs/09` |
| 自带工具 | `tools/`（源码镜像 / 原子替换 / JS 校验 / API 直传 / 端到端回归） |

**禁止**：复制 `index.html` 到别处改（会分叉）。所有会话都改仓库里那一份。

---

## 1. 目录结构

```
frontend/index.html              单文件前端（页面 + JS + CSS 全在里面）
backend/agent_reach_bridge.py    零依赖 Python（标准库），同时托管前端 + 提供 API
backend/library.json             内容库数据
backend/audio/*.mp3              TTS 音频（部分入库，见 .gitignore 白名单）
backend/start_railway_local.py   本地复现 Railway 行为（端口 8793）
tools/build_deploy_bundle.py     打备用部署包
tools/deploy_demo.py             密钥注入 / 清除（prepare / cleanup）
tools/fetch_sources.py           只拉源码镜像（跳过 90MB 音频，别用 git clone）
tools/atomic_replace.py          原子替换 + 命中断言（治坑 1）
tools/check_js.py                抽 <script> 逐个 node --check（治坑 6）
tools/push_via_api.py            GitHub API 直传（治坑 8）
tools/e2e_verify.mjs             端到端回归：登录 + 遍历 16 页 + 收集 JS 异常
docs/                            01-架构 02-API 03-Dify工作流 04-数据模型
                                 05-等级扩展 06-前端审计 07-工程化需求 08-风险清单 09-Git协作
RAILWAY_DEPLOY.md               部署指南 + 故障排查
AGENTS.md                        本文件
HANDOFF.md                       换设备交接清单（给人读）
```

---

## 2. 品牌与文案

- 品牌名固定 **`ReadPal`**（无空格）。全文件见到 `Read Pal`（带空格）一律是错的，改回 `ReadPal`。
- UI 规范：橙红 `#E65425`、页面底色 `#FFFDF9`、白卡片、无衬线字体、三栏布局。
- **侧边栏与登录页严禁 emoji**。菜单项对齐、不带数字编号。

### 设计大原则（Bryan 定 · 所有前端改动一律适用，不必每次复述）

> **简洁、干净、清爽，色调统一。**

推论要求（改前端时逐条对照）：

- 品牌色**只有一个真源**：`:root` 里的 `--grad-pri:linear-gradient(135deg,#E65425,#F79009)`。
  顶部 ReadPal 徽标 / 登录页大徽标 / 登录按钮 / 表单提交按钮等**一律写 `var(--grad-pri)`**，
  不要再写渐变色字面量；新增品牌色元素也必须引用它。
- **不要给卡片设固定 `min-height` 撑高度** —— 删文案后中间会留下一大片空白。
  等高交给 grid stretch，卡片高度贴合内容。
- 删文案要**连带清理配套 CSS**，不留死规则（如删了元素却留下 `.xxx{...}`）。
- 删除信息时优先「整块拿掉」，而不是留空占位。
- 改完必须**真实渲染截图看效果**，不能只看代码（见第 9 节）。

---

## 3. ⚠️ 已踩过的坑（动工前必读）

### 坑 1：并行 Edit 会静默互相覆盖

对**同一文件**并发发多个 Edit，每个 Edit 基于同一份初始快照各自写回、互相覆盖，最终只有 1–2 处真正落盘，**但工具仍返回成功**。症状是"明明改了却没生效"。

> **规则**：改同一文件多处时，**必须串行 Edit**（等上一个返回再发下一个），
> **或用 Python 脚本一次性原子替换**（脚本写到 `/tmp/*.py` 再执行，绕开 bash heredoc 的 `$` 转义）。

### 坑 2：`s12` 不是「库存管理」

函数名 `s12` 实为**「逐段审核」**（旧 step 9 保留的名字没跟着重排改名），而 **step 12 是「库存管理」(`sInventory`)**。功能正确，但**名字会骗人**。

同理 `s9` = 段落校对、`s4` = 事实抽取。
> **别按函数名推断它对应哪个 step，一律以 `fns` 数组下标为准。**

### 坑 3：localStorage 种子数据改了「看不见」

预填充数据写进 localStorage 后，初始化函数的「有缓存直接返回」逻辑会让新数据**永不生效**。
> **规则**：凡用 localStorage 预填充种子数据，改 schema/数据时必须同时做版本迁移或旧数据检测清除。
> 现有范例：`initFeedbackData()` 检测 `topicReads["daily_life"]` 判定旧版后清空重写。

### 坑 4：空串是合法的同源声明，判断必须用 `typeof`

服务端注入 `window.WB_API_BASE=""` 表示"同源部署"。前端若用真值判断 `if(window.WB_API_BASE)`，空串被判为假 → 错误回落到 `127.0.0.1:8787` → 云端所有桥接接口静默失败。

```js
// 错
if (window.WB_API_BASE) return norm(window.WB_API_BASE);
// 对
if (typeof window.WB_API_BASE === "string") return norm(window.WB_API_BASE);
```

> **规则**：凡服务端注入的、可空、有特定语义的全局变量，前端一律用 `typeof x === "string"` 判断，不要用 truthy。
> 同类坑：`window.WB_CONFIG = (window.WB_CONFIG || {})` 曾把注入的 `WB_CFG` 整个覆盖掉。

### 坑 5：从 git 还原文件会连带丢失未提交的其它改动

救语法错误时执行 `git show <sha>:frontend/index.html > frontend/index.html`，会把该 commit 之后的所有改动一起还原掉，且**不报错**。
> **规则**：从 git 还原后必须 diff 确认丢了什么（对比线上版本数特征字符串出现次数是有效手段）。

### 坑 6：单文件大 HTML 改完必须校验 JS 语法

用 Python 正则抽出所有 `<script>` 块 → 逐个 `node --check`。能挡住大部分白屏事故。
> 插入多层 `if/else` 时最容易少一个闭合 `}`，报错形如 `Unexpected token 'catch'`。

### 坑 7：本地静态服务 / 浏览器进程不能用 `&` 后台启动

`python3 -m http.server` 之类用 `&` 丢到后台，**进程会随所在 shell 结束被杀掉**。
随后截图全是 "This site can't be reached"，很容易误判成"前端被改坏了"。
> **规则**：本地静态服务、无头浏览器调试进程，都必须用工具提供的**后台常驻**方式启动，
> 不要用 `&`。`tools/e2e_verify.mjs` 已内置自己拉起 Chrome，无需手动起。

### 坑 8：截图文件名重复会被去重，读到旧图

同一路径重复截图，去重机制会直接返回上一次的图，**看起来像"改了没生效"**，
极易误导排查方向。
> **规则**：截图一律用**带时间戳的唯一文件名**。

### 坑 9：元素已有 `class` 时，再写一个 `class` 是无效的

`<div class="lrole" ... class="open">` —— HTML 重复属性**取第一个**，后面的 `open` 被静默忽略。
写"临时预览副本"（强制展开态 / 弹窗态）时最容易踩，表现为"类名明明加了却没生效"。
> **规则**：合并进同一个属性 —— `class="lrole open"`。

### 坑 10：SiliconFlow 模型名必须带厂商前缀

`Qwen2.5-7B-Instruct` → 400 `Model does not exist`；正确写法 `Qwen/Qwen2.5-7B-Instruct`。
> **规则**：调用前先确认完整模型名，别照记忆写。报 `Model does not exist` 时先怀疑名称格式。

### 坑 11：Dify FACT 工作流入参字段是 `material`

传 `{title, content}` 会报 `material is required in input form`。正确结构：

```json
{"material": "正文（前端 slice 到 4800 字符）", "level": "B1", "style": "default"}
```

> **规则**：改 Dify 调用前先用 curl 真跑一次拿到真实报错，别猜字段名（见第 10 节末条）。

---

## 4. 编号体系（改 step 相关逻辑必看）

当前体系（2026-09-04 全局重排后，已验证自洽）：

- `STAGES` 12 项占 idx **0–11**；`stepLabel` 的 `i<12` 走 STAGES，12–15 走内容管理四模块
- router `fns` 16 项：
  `[s0,s1,s2,s3,sMaterialBank,s4,s5,s6,s7,s9,s12,sArticleBank,sInventory,sPublish,sOps,sFeedback]`
- `RAIL`：侧边栏结构（5 项）
  `工作台` group steps=`[0,5]` · `素材库` item idx=4 · `内容库` item idx=11 · `发布管理` group steps=`[12,13,14,15]` · `团队成员` ph 占位
  > 📌 本文早期写的 `SECTIONS`（mat/art/ops 分组）**代码里并不存在**（2026-09-10 核实：
  > `SECTIONS` 仅在侧边栏标题文案 `板块 · SECTIONS` 里出现，不是 JS 常量）。
  > 语义分区约定保留为：mat=`[0,4]` · art=`[5,11]` · ops=`[12,13,14,15]`，但**要改就改 `RAIL`**。
- `STEP_OWNER`：0–4 source · 5–9 produce · 10–11 review · 12–13 review · 14–15 ops
- 内容管理四模块：12 库存 · 13 发布 · 14 运营看板 · 15 用户反馈

> ⚠️ 改动任何 step 相关逻辑时，
> **`STAGES` / `stepLabel` / `fns` / `RAIL` / `STEP_OWNER` / `ROLE_OPS` 六处必须同步**，否则错位白屏。

**权限判断只看 `ROLE_OPS`**：
- `canOperate(i)` → `ROLE_OPS[role].indexOf(i) >= 0`
- `roleSteps(r)` → 基于 `ROLE_OPS[r.id]` 动态生成登录卡片标签
- `entry` → `go(r.entry)`，控制登录后落脚点
- `STEP_OWNER` → 仅用于侧边栏 owner 圆点/只读提示的**视觉标注**

**注**：教研老师（`produce`）权限为 `[0-9, 11]`，**故意跳过 10（逐段审核）** —— 生产者不审核自己的产出，属内控合理设计，**勿改**。
> 改完 `ROLE_OPS` 必须回看 `ROLES[].scope` 文案（硬编码死字符串，极易忘记同步）。

---

## 5. 部署架构（Railway 单服务）

**单服务设计**（最重要）：
- `backend/agent_reach_bridge.py` 同时托管前端 + 提供 API，前后端**同域**
- `bridge._serve_index()` 服务 HTML 时，把 `<script src="config.local.js">` 替换为**服务端注入的一行**：
  `window.WB_API_BASE=""` 加上 `window.WB_CONFIG={DEMO_PASS, SF_API_KEY, DIFY_WF_MAIN, DIFY_WF_GEN, DIFY_WF_FACT}`
  > ⚠️ **实测（2026-09-10）**：这条注入把**真实密钥写进了公开可访问的 HTML** ——
  > 任何人 `curl` 首页并 `grep WB_CONFIG` 即可拿到 `SF_API_KEY` + 3 个 Dify key + 演示密码。
  > 另外仓库 `backend/keys.fallback.json` 里存着同一份明文密钥，而**仓库是 PUBLIC**。
  > Bryan 已知悉并**明确决定暂不处理**（面向内部老师、密钥有额度限制）。
  > **不要在改其它东西时"顺手修掉"** —— 要动请先确认。
- 前端所有 Dify / SiliconFlow 调用走 `AGENT_REACH_API + "/api/dify|api/sf"` 相对路径

**bridge 关键路由**：
- `GET /` → `_serve_index()`（注入 `WB_API_BASE=""`）
- `GET /api/proxy-health` → 部署自检，回 `{configured: {key: true/false}}`（**不回值**）
- `GET /api/health` `/api/trends` `/api/tags/taxonomy` `/api/scan` `/api/library` `/api/source-health` `/api/errors`
- `POST /api/dify/workflows/run` → 反代 Dify（body 的 `wf: fact|gen|main` 选 key）
- `POST /api/sf/chat/completions` `/api/sf/images/generations` → 反代 SiliconFlow
- `POST /api/tts` `/api/tts/batch` `/api/tags/extract` `/api/library`
- `GET /audio/*` → 静态音频

**本地复现线上行为**：
```bash
cd backend && python3 start_railway_local.py          # 端口 8793
python3 start_railway_local.py --stop
```

---

## 6. 密钥

4 个 key，**唯一真源 = Railway 环境变量**：

| 变量 | 用途 |
|---|---|
| `SF_API_KEY` | SiliconFlow（TTS + 封面图 + LLM） |
| `DIFY_WF_FACT` | Dify 事实抽取工作流 |
| `DIFY_WF_GEN` | Dify 内容生成工作流 |
| `DIFY_WF_MAIN` | **前端实际未使用**（`AIWF` 常量定义了但无任何 `fetch(AIWF.*)` 调用，是死资产，可不配） |

- 后端 `_env_key(name)` 从 `os.environ` 读；`_proxy_post()` 转发时**统一 UA**（Dify 的 Cloudflare 会拦 Python 默认 UA）
- 仓库里的 `frontend/index.html` **源码是干净的**（实测 0 个真实密钥）；
  但**线上运行时不是** —— `_serve_index()` 会把密钥注入页面（详见第 5 节 ⚠️）
- `.gitignore` 已排除 `frontend/config.local.js`；本机调试时把它放出来用

**⚠️ LLM 走的是 DeepSeek，不是 SiliconFlow**（2026-09-09 实测确认）：
- FACT `12e8c26d-...` 3 个 LLM 节点 → `langgenius/deepseek/deepseek` / `deepseek-v4-flash`
- GEN `f4462032-...` 2 个 LLM 节点 → `langgenius/deepseek/deepseek` / `deepseek-v4-pro`
- 硅基流动**没有** `deepseek-v4-*` 系列（实测 400 "Model does not exist"），别照着 SF 的模型列表改

---

## 7. 外部服务实测数据（选型/排障参考）

| 项 | 实测 |
|---|---|
| Dify FACT | 9.7 ~ 13.2s succeeded，8 个 outputs |
| Dify GEN | **50 ~ 61s** succeeded，三档文章 A2/B1/B2 |
| SiliconFlow 封面图（Kolors 512） | 可用，但 URL 带 `X-Amz-Expires=3600`（**1 小时失效**） |
| TTS | 1.9s |

**硬约束**：
- **封面图生成后必须立即转 base64** 存 `coverDataUrl`，存 URL 隔天全是裂图
- `pruneCoverQuota()` 做容量保护（512 图约 0.55MB/张，localStorage 约 5MB）
- **SiliconFlow 必须选带 `Instruct` 后缀的非推理模型**。`Qwen3.6` / `DeepSeek-V4` 是推理模型，输出落进 `reasoning_content` 而 `content` 为空（DeepSeek 还会吐 `</think>`）
- **Serverless 函数不可用**：Netlify 免费版 10s 上限、Pro 26s，GEN 必超时 → 只能容器平台（Railway / Fly.io）

---

## 8. 改完代码怎么上线

```
改 frontend/index.html 或 backend/*.py
        ↓
node --check 校验（单文件大 HTML 必做）
        ↓
推 GitHub main
        ↓
Railway 自动部署（约 90 秒）
        ↓
curl 线上首页 / 浏览器实测验证
```

**⚠️ 推送方式**：本地 git 与远程 `main` **历史已分叉**，`git push` 会被拒。
> 用 **GitHub API 直传**：`GET /repos/{o}/{r}/contents/{path}` 拿 `sha` → `PUT` 同路径带 `content`(base64) + `sha` + `branch:main`。
> 大文件（682KB）偶发 `IncompleteRead`，**加重试**（4 次 × 3s）即可成功。

### 用仓库自带脚本走完整流程（推荐，别手搓）

```bash
# 0) 首次/换设备：只拉源码镜像到本地（别用 git clone —— 仓库含 90MB 音频，浅克隆常超时）
python3 tools/fetch_sources.py ./readpal

# 1) 定位：先打印待改区域的字符偏移与上下文，不要凭猜

# 2) 改：同一文件多处修改用原子替换，每项写 expect 命中断言，不符则整体不写盘
python3 tools/atomic_replace.py frontend/index.html /tmp/spec.json

# 3) 必做：抽 <script> 块逐个 node --check
python3 tools/check_js.py frontend/index.html

# 4) 本地真实渲染截图（服务后台常驻 + 截图用唯一文件名）
# 5) 推送（自动重试）
python3 tools/push_via_api.py frontend/index.html frontend/index.html "commit message"

# 6) 等约 95 秒，核验线上特征串
curl -s https://web-production-2a16e.up.railway.app/ | grep -c "特征串"

# 7) 改了共享 CSS/JS 时：端到端回归（脚本自己拉起 Chrome，无需手动起进程）
node tools/e2e_verify.mjs
```

**令牌来源（按优先级）**：`--token=xxx` 参数 → 环境变量 `READPAL_GH_TOKEN` → `GITHUB_TOKEN` → `tools/.env.json`（**已 gitignore，勿提交**）。

**备用 workbuddy 链接不会自动跟**，需手动：
```bash
python3 tools/build_deploy_bundle.py   # 产出 deploy_bundle/
# 再用发布工具部署 deploy_bundle 目录
```

---

## 9. 验证清单（改完必跑）

1. **JS 语法**：抽出所有 `<script>` 块 → 逐个 `node --check`
2. **线上首页**：`curl -s https://web-production-2a16e.up.railway.app/ | grep` 特征字符串
3. **桥接健康**：`GET /api/proxy-health` → 4 个 key 全 `true`
4. **浏览器实测**（curl 只能证明代码在，证明不了运行时行为）：
   - 一条命令跑完：`node tools/e2e_verify.mjs`
     验收线 → **16 页遍历 0 条 JS 异常 + 0 条 console.error + `state.bridgeOk === true`**
   - 改样式时补一条：关键元素的 computed background 与品牌徽标一致（脚本里已含 `btnMatchesLogoBg` 断言）
   - Dify FACT / GEN 真跑一次
5. **特征字符串核查**：`127.0.0.1:8787` 在源码中应**只剩 1 处**（`DEFAULT_API_BASE` 默认常量）。

---

## 10. 协作习惯（Bryan 的偏好）

- **中文沟通**，称呼 Bryan，不要叫「用户」「您」。
- **结论先行 + 详细拆解 + 风险分析**。要真实跑过的验证结果，**不接受「应该可以」**。
- **动工前先复述需求并确认**（部署环节已豁免：改完验证通过直接上线，无需再问）。
- 提问很简短，按最有用的方向做，然后说明自己怎么理解的——他若不是这个意思会纠正。
- 关心工具的**覆盖边界**：不能只说能干什么，要说清干不了什么。
- 涉及外部服务**必须实际调用一次拿到响应**再写/改解析代码。状态字符串一律写成兼容集合。
- **前端设计统一遵循第 2 节的「设计大原则」**，不必每次复述。
- 交付前端改动时，附**改动前后的真实渲染截图**，并说明自己主动多做了什么、可否决。
- 跨设备 / 跨账号协作：**知识必须落进仓库**（本文件 + `tools/`），不要只留在某台机器的本地配置里。
