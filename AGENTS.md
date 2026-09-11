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
| 前端真源 | `frontend/index.html`（约 63 万字符，所有页面/JS/CSS 全在里面） |
| 后端真源 | `backend/agent_reach_bridge.py` |
| 部署文档 | `RAILWAY_DEPLOY.md`（含 10 条故障排查） |
| 设计文档 | `docs/01` ~ `docs/09` |
| 自带工具 | `tools/`（源码镜像 / 原子替换 / JS 校验 / API 直传 / 端到端回归 / 精确视口截图） |

**禁止**：复制 `index.html` 到别处改（会分叉）。所有会话都改仓库里那一份。

### 分级体系（2026-09-10 起 · **唯一真源 = 飞书《APP阅读级别量化表》**）

**4 大档 / 12 子档**，旧的三档标准（A2/B1/B2）**全部作废**：

```
A1 入门   A1.1 A1.2 A1.3      段落数 4   4/5/6 段
A2 初级   A2.1 A2.2 A2.3      段落数 5   5/6/7 段
B1 中级   B1.1 B1.2 B1.3      段落数 6   6/7/8 段
B2+ 中高级 B2+.1 B2+.2 B2+.3   段落数 8   8/9/10 段
```

- **两套命名都要处理**：Dify 返回的 JSON key 是**下划线式**（`A1_1` / `B2P_1`），
  对外展示用**点式**（`A1.1` / `B2+.1`）。前端用 `nkKey()` / `nkDisp()` 归一化，
  **不要在业务代码里手写档位字符串**。
- 每档 7 个量化维度：词数 / 蓝思 / 平均句长 / 主题范围 / 语言难度 / 体裁配比 / 题目分布。
- **蓝思是「生成时的硬约束」**：写进生成提示词 + 由校验节点参与判定（用估算公式，非官方值）。
- 题目 4 类：`language`（语言基础）/ `text`（文本理解）/ `logic`（逻辑推理）/ `cognitive`（认知思辨），
  每档 3 题，按档位递进配比；**只有 B2+.3 有中文背景导读**（`quiz_json.guide.B2P_3`）。
- 前端骨架：`BIG_GROUPS` / `LEVELS12` 是唯一真源（在 `const SPECS` 之前），
  三栏视图按**当前大档**显示该档 3 个子档，顶部有 `bigBarHTML()` 大档切换条。
- Dify 知识库「分级标准」已替换为 12 档语料（旧文档已删，备份在 `dify_kb_backup/legacy/`）。

---

## 1. 目录结构

```
frontend/index.html              单文件前端（页面 + JS + CSS 全在里面）
backend/agent_reach_bridge.py    零依赖 Python（标准库），同时托管前端 + 提供 API
backend/library.json             文章库数据
backend/audio/*.mp3              TTS 音频（部分入库，见 .gitignore 白名单）
backend/start_railway_local.py   本地复现 Railway 行为（端口 8793）
tools/build_deploy_bundle.py     打备用部署包
tools/deploy_demo.py             密钥注入 / 清除（prepare / cleanup）
tools/fetch_sources.py           只拉源码镜像（跳过 90MB 音频，别用 git clone）
tools/atomic_replace.py          原子替换 + 命中断言（治坑 1）
tools/check_js.py                抽 <script> 逐个 node --check（治坑 6）
tools/push_via_api.py            GitHub API 直传（治坑 8）
tools/e2e_verify.mjs             端到端回归：登录 + 遍历 12 页 + 收集 JS 异常
tools/theme_audit.mjs            配色合规审计：遍历 12 页揪出非「黑/灰/橙红」色相
tools/cdp_shot.mjs               CDP 精确视口截图（多尺寸一次出图，治坑 12）
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
- **全站色相只有三系：黑 / 灰 / 品牌橙红**（2026-09-10 Bryan 定，已全量落地）。
  蓝、绿、紫、青**一律不许出现** —— 状态色、CEFR 等级色、选题大类色、图表色都算在内。
  - **分类色统一 `#E65425`**：6 个选题大类 / CEFR 的 A2·B1·B2 / 3 个角色 /
    素材类型 / 侧边栏分区 / 路径（对应 JS 色板 `ROLES` `RAIL` `ROUTES` `SRC_TYPES`
    `LVL_META` `TOPIC_CATS`）。色块不再承担区分功能，靠文字标签区分。
  - **状态色走品牌橙的深浅梯度**：成功/完成 `#F79009`、警告/部分 `#D04418`、
    失败/风险 `#A32D2D`（暖族深红，不是新色相）。
  - 浅底 tint：`#FFF9F5` / `#FFF0EB` / `#FFEDE4`；浅边框 `#FFDFCF`。
  - 冷调中性灰（`#101828` `#475467` `#98A2B3` `#EAECF0` `#D0D5DD` `#344054`）
    **属于「灰」，保留** —— 它们色相偏蓝但饱和低、视觉上就是灰。
  - 加新颜色前先想清楚挂哪一档；改完跑 `node tools/theme_audit.mjs`，
    **必须 12 页全 ✓** 才算过。
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

函数名 `s12` 实为**「逐段审核」**（旧 step 9 保留的名字没跟着重排改名），而它落在 `fns` 下标 10。功能正确，但**名字会骗人**。

同理 `s9` = 段落校对、`s4` = 事实抽取。
> **别按函数名推断它对应哪个 step，一律以 `fns` 数组下标为准。**
> （曾经的 `sInventory` = 库存管理，2026-09-10 随发布管理一起删除。）

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

### 坑 12：`chrome --window-size` 受最小窗口尺寸限制，做不了窄屏验证

headless Chrome 的 `--window-size=420,820` **不会**得到 420px 视口 —— 受 Chrome 最小窗口
宽度约束，实际视口约 500px，而截图仍按 420 裁切。表现是「移动端布局溢出、右侧被切」，
极容易误判成前端写坏了（实测 420 尺寸下 `vw` 报 500、卡片撑出屏幕）。

> **规则**：窄屏 / 移动端验证一律走 CDP `Emulation.setDeviceMetricsOverride`，用
> `node tools/cdp_shot.mjs --sizes=1440x900,1024x768,420x820` 出图；该脚本同时回读
> `vw` / `scrollWidth` / 容器矩形，可直接判断**是否水平溢出**与**是否垂直居中**。

### 坑 13：`min-height:100%` 对 `position:fixed` 父元素无效

覆盖层（如 `#loginOv`）用 `position:fixed;inset:0` 时高度来自 top/bottom 定位而**不是**
`height` 属性，子元素写 `min-height:100%` 会 resolve 到 `auto` → 失效，表现为
「内容死贴在顶部、垂直居中没生效」；若改用 grid `place-items:center`，内容超高时
顶部又会被裁掉（负溢出）。

> **规则**：覆盖层垂直居中用 **flex + `margin:auto`**：
> 容器 `display:flex;flex-direction:column`，子容器 `margin:auto`。
> `margin:auto` 会吸收剩余空间实现完美居中，内容溢出时自动退化为 0，**既不裁切也不溢出**。
> ⚠️ 若 `display` 由 JS 内联赋值（`ov.style.display="grid"`），记得同步改成 `"flex"`。

---

### 坑 14：Dify 硅基流动插件的思考开关叫 `enable_thinking`，写 `thinking` 会被**静默丢弃**

把 `completion_params` 写成 `{"thinking": false}` 时，Dify **不报错、不提示**，
直接丢弃这个键 → 模型按 SF 平台默认**开着思考**跑。

实测（`DeepSeek-V4-Flash`，400 词长文，`max_tokens=1600`）：

| 参数 | 耗时 | completion tokens | reasoning |
|---|---|---|---|
| 无参数（SF 默认） | 54.0s | 10641 | 30335 字符 |
| **`enable_thinking: false`** | **8.0s** | **533** | 0 |

→ 差 **6.75 倍耗时、20 倍 token**。GEN 要出 2.5 万 token，开着思考会拖到十几分钟，
表现为 **service API 返回 200 但 SSE 连续几分钟零字节**，极易误判成"网络问题/Dify 卡住"。

查参数名的正确姿势（只读）：
```bash
GET /console/api/workspaces/current/model-providers/langgenius/siliconflow/siliconflow/models/parameter-rules?model=<模型名>
```
该插件只认这 9 个参数：`temperature` `max_tokens` `top_p` `top_k` `frequency_penalty`
`response_format` `json_schema` **`enable_thinking`** `reasoning_effort`。
> 顺便：SF 原生 API 直接传 `thinking=false` 会 **HTTP 400** —— 只有 `enable_thinking` 有效。

### 坑 15：知识库检索「英文素材 → 中文标准文档」会 0 命中

`nodeKBGrade` / `nodeKBSens` 的 `query_variable_selector` 原来指向**英文素材文本**，
而知识库里是**中文分级标准** —— 向量检索跨语言失配，`result` 恒为空数组，
**整条知识库参考路径是死的**（而且不报错，只是静默返回空）。

解法：在检索节点前插一个 code 节点，输出**固定中文检索意图词**（如"分级标准 词数 蓝思 句长 对照表"），
检索质量立刻正常（实测 8 段，score 0.68–0.73）。

> ⚠️ 新增检索/LLM 节点后**必须补一条从 `start` 可达的入边** —— Dify 的执行是
> 「从 start 出发的可达性驱动」，没有入边的节点**永远不会被执行**，
> 而且工作流可能直接跑完不报错。`build_dify.py` 的 `validate_graph()` 已加这条断言。

### 坑 16：Dify 网关对 `blocking` 有约 120s 硬超时，长工作流必须走 `streaming`

GEN 早期用 DeepSeek 官方渠道耗时 145s，`response_mode: "blocking"` **实测直接 504**；
换 `streaming` 后同样 184.7s 的工作流正常返回（首字节 1.1s）。

前端已把 GEN 调用改成 SSE（`response_mode: "streaming"`），并按 `node_finished`
事件显示「已完成 N 个节点」的进度；FACT 只要 ~10–26s，仍走 `blocking`。

---

## 4. 编号体系（改 step 相关逻辑必看）

当前体系（2026-09-04 全局重排后，已验证自洽）：

- `STAGES` 12 项占 idx **0–11**；`stepLabel` 的 `i<12` 走 `STAGES`，越界返回空标签
- router `fns` 12 项（与 `STAGES` 一一对齐）：
  `[s0,s1,s2,s3,sMaterialBank,s4,s5,s6,s7,s9,s12,sArticleBank]`
- `RAIL`：侧边栏结构（**4 项，全部同级直达**）
  `素材创建` idx=0 · `素材库` idx=4 · `文章生产` idx=5 · `文章库` idx=11
  > `0` / `5` 的显示名来自 `RAIL_OVERRIDE`（`STAGES` 里它们的名字是「素材选择」「事实抽取」）。
  > 侧边栏**不再有可展开分组**，`expandedSections` 现为空集；`buildRail` 的分组分支作为通用能力保留。
  > 侧边栏**顶部没有标题**（2026-09-10 已删除 `rail-h` 占位，第一项直接置顶）——
  > **要改侧边栏就改 `RAIL`**；文档早期提到的 `SECTIONS` 是废弃旧名，不存在这个常量。
- `STEP_OWNER`：0–4 source · 5–9 produce · 10–11 review
- **2026-09-10 剪枝**：已删除「发布管理」四模块（12 库存 · 13 发布 · 14 运营看板 · 15 用户反馈）
  与「团队成员」占位。平台定位为**内容生产平台**（内容管理由另一平台承担），
  **新增功能不要往发布/分发方向加**。

> ⚠️ 改动任何 step 相关逻辑时，
> **`STAGES` / `stepLabel` / `fns` / `RAIL` / `STEP_OWNER` / `ROLE_OPS` 六处必须同步**，否则错位白屏。
> ✅ 好消息：新增/删除**尾部**步骤只需同步 `fns` + 对应函数，前面各步编号不受影响。

**权限判断只看 `ROLE_OPS`**：
- `canOperate(i)` → `ROLE_OPS[role].indexOf(i) >= 0`
- `roleSteps(r)` → 基于 `ROLE_OPS[r.id]` 动态生成登录卡片标签
- `entry` → `go(r.entry)`，控制登录后落脚点
- `STEP_OWNER` → 仅用于侧边栏 owner 圆点/只读提示的**视觉标注**

**注**：教研老师（`produce`）权限为 `[0-9, 11]`，**故意跳过 10（逐段审核）** —— 生产者不审核自己的产出，属内控合理设计，**勿改**。

### 统一返回按钮（2026-09-10 新增 · 全站统一）

**位置**：内容区左上角、`stagehead` 上方（即顶栏「AI · 待运行」chip 正下方）。
由 `render()` 统一注入 `backBarHTML()` —— **不要在各页面函数里单独写返回按钮**。

**显示规则**：侧边栏直达的顶层页 `0 / 4 / 5 / 11` **不显示**（它们没有上一级，模块切换靠侧边栏）。

**落点规则**（`backTarget()`，按「模块内层级」推算，**不是简单 `cur-1`**）：

| 当前 | 返回落点 |
|---|---|
| `cur=0` 且已选入口 | `resetRoute()` → 清空入口，回到三张入口卡 |
| `cur=1` 热点搜集 | `go(0)` |
| `cur=2` 敏感排除 | trend → `go(1)`；**owned/public → `go(0)`**（该路线跳过热点） |
| `cur=3` 选题标签 | `go(2)` |
| `cur=6` 分级标准 | trend → `go(5)`；**owned/public → 不显示**（它是该路线首步） |
| `cur=7..10` | `go(cur-1)` |

> ⚠️ **必须用 `goResolve()` 复刻 `go()` 的跳步改写**（owned/public 下 `1→2`、`5→6`）。
> 直接写 `go(cur-1)` 会被 `go()` 改写成原地不动，表现为「点了没反应」。
> 回退范围限制在本模块内（素材创建 `0–4` / 文章生产 `5–11`），**绝不跨模块** —— 跨模块用侧边栏。

**侧边栏直达项 = 模块入口页**：`railGo(i)` 在 `i===0` 时先清 `state.route`，
所以点「素材创建」**永远回到三张入口卡**，而不是停在上次选的那个入口的第二步。

**只读态**：`.wrap.ro *` 会禁用整个 stage 的交互，故 CSS 有白名单
`.wrap.ro .backbar,.wrap.ro .backbar *{pointer-events:auto!important;opacity:1}` —— 返回按钮在只读态下仍可用。
> 验证只读态时注意：`review` 的 `ROLE_OPS` 是 `0–11` **全量，永远不进只读态**；
> 要触发得临时把 `state.user.role` 切成 `source`（或 `produce` + `cur=10`）。

回归覆盖：`node tools/e2e_verify.mjs` 内含 **16 条返回按钮断言**（显示规则 / 落点 / 路线跳步 / 只读态 / 旧按钮已删）。
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

**⚠️ LLM 渠道已于 2026-09-10 切到硅基流动**（DeepSeek 官方账户余额耗尽，402 Insufficient Balance）：
- FACT `12e8c26d-...` 3 个 LLM 节点、GEN `f4462032-...` 6 个 LLM 节点
  → **全部** `langgenius/siliconflow/siliconflow` / `deepseek-ai/DeepSeek-V4-Flash`
- 硅基流动**有** `deepseek-ai/DeepSeek-V4-Flash` 与 `-Pro`（2026-09-09 的"没有该系列"结论已过期）
- ⚠️ **模型名必须带厂商前缀**，且用 `deepseek-ai/…` 而不是 `deepseek/…`
- 渠道改写集中在 `build_dify.py` 的 `MODEL_REPOINT` + `repoint_models()`，
  改渠道请改那里再重建，**不要手改 Dify 图**（9 个节点容易漏）

---

## 7. 外部服务实测数据（选型/排障参考）

| 项 | 实测 |
|---|---|
| Dify FACT | 8 ~ 26s succeeded，输出含 `summary` / `facts_text` / `level`(12 子档) |
| Dify GEN | **77s** succeeded，12 子档文章 + 12×3 题，`validation_pass=true` |
| SiliconFlow 封面图（Kolors 512） | 可用，但 URL 带 `X-Amz-Expires=3600`（**1 小时失效**） |
| TTS | 1.9s |

### 硅基流动模型吞吐（2026-09-11 实测 · 4 路并发 + 900 词长文）

| 模型 | 吞吐 | 结论 |
|---|---|---|
| `deepseek-ai/DeepSeek-V4-Flash` | **81.9 t/s** | ✅ 唯一可用，9 个节点统一用它 |
| `deepseek-ai/DeepSeek-V3.1-Terminus` | 24.3 t/s | ❌ 太慢 |
| `Pro/deepseek-ai/DeepSeek-V3.2` | 21.6 t/s | ❌ 专用通道并没更快 |
| `deepseek-ai/DeepSeek-V3.2` | 21.6 t/s | ❌ 太慢 |
| `deepseek-ai/DeepSeek-V4-Pro` | 4.4 t/s | ❌ 不可用（120s 跑不完 900 tokens） |
| `zai-org/GLM-5.3` | 180s 超时 | ❌ 不可用 |

> ⚠️ **测吞吐必须用「并发 + 长输出」的负载**。拿单次小请求测会得到严重乐观的数字
> （实测同一模型小请求 69 t/s、并发长文只有 21.6 t/s），据此选型会翻车。

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
SITE=http://127.0.0.1:8899/index.html REQUIRE_BRIDGE=0 node tools/e2e_verify.mjs

# 8) 改了布局/响应式时：多尺寸真实截图（窄屏必须走 CDP —— `--window-size` 做不了，见坑 12）
node tools/cdp_shot.mjs --url=http://127.0.0.1:8899/index.html \
     --sizes=1440x900,1920x1080,1024x768,420x820 --out=/tmp/shot
# 需要登录后的页面，用 --eval 预置状态：
#  --eval="(async()=>{openLogin('review');doLogin('review');await new Promise(r=>setTimeout(r,2500));go(4);return 'ok';})()"
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
     验收线 → **12 页遍历 0 条 JS 异常 + 0 条 console.error + `state.bridgeOk === true`**
     （本地静态服务没有桥接层，加 `REQUIRE_BRIDGE=0` 跳过 `bridgeOk` 校验，其余指标同样有效）
   - 改样式时补一条：关键元素的 computed background 与品牌徽标一致（脚本里已含 `btnMatchesLogoBg` 断言）
   - **改布局/响应式时**：`node tools/cdp_shot.mjs` 出多尺寸图，逐张看图确认；
     重点看 `scrollWidth === vw`（无水平溢出）与容器矩形是否居中（治坑 12 / 坑 13）
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
