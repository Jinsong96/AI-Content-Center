# AGENTS.md —— 给接手这个仓库的 AI 的工作说明

> 这份文件是给**另一个设备、另一个模型**看的。目标：`git clone` 之后不靠口头交接就能继续干活。
> 最后更新：2026-10-01 21:20 · 状态：V3 已实现并部署，新增「新闻原稿」来源模式，支持服务端密钥；
> **视觉改版（校样台 · Press Proof）+ 拉丁字体自托管已同步上线**（见 §6.1）。
> **访问口令已于 2026-10-01 按要求整体移除**（内部 demo，不再设卡）。
> **待办：月饼文两个质量缺口（等 Bryan 拍板）、V4（等 CEFR 分级指南）。**

---

## 0. 30 秒速览

**一鹿知 · 内容生产平台**（代码代号 `V3-Content-Factory`）是一个**分级阅读内容工厂**：

```
原文（B2 母稿 或 新闻原稿）
   →  ① 生成（deepseek-flash）  →  ② 确定性脚本质检（17 类）
   →  ③ 异源语义裁判（Qwen3.8-27B @ siliconflow）  →  ④ 渲染（JSON + docx）  →  ⑤ 审校编辑
```

产出 = **四个难度的文章（B2+ / B1 / A2 / A1-）+ 一套题目（每级 3 题）+ 质检报告**。

**全链路只有 2 次模型调用**，其余全是确定性 Python 代码。零第三方依赖。

### 两种来源模式（`source_mode`）—— 搞不清这个一定会做错

| 模式 | 输入 | 怎么处理 B2+ |
|---|---|---|
| `b2`（默认） | **B2 母稿**（长度/难度已合格） | **B2+ = 原文本身，不重新生成**，只切卡 + 出题；只向下生成 B1/A2/A1- |
| `news` | **新闻原稿**（长度/难度都不符） | **四级全部生成**，B2+ 也是模型产物；保真基准 = 新闻原稿 |

原稿太简单时 **提示、不硬升**：`generate_news.md` 自评 `source_level` → 落库 → 质检第 17 类
`source_level_low` 出 warning → 界面建议换一篇更难的稿件。

---

## 1. 先读什么（顺序不能反）

| 顺序 | 文件 | 为什么 |
|---|---|---|
| 1 | `docs/00-需求澄清实录-grill-me.md` | **§4 已锁定的需求 = 唯一施工依据。** 不看这个你会做出错的东西 |
| 2 | 本文件 §2 §3 §4 | 硬约束 + 架构 + 坑 |
| 3 | `docs/01-智能体框架与逻辑-v1.md` | 完整设计总纲（17 章），含全局架构图与逐环说明 |
| 4 | `docs/08-工作日志-2026-09-29.md` | **最新一轮的工作日志**：新闻原稿模式、密钥/口令、月饼文质量诊断、V4 暂缓原因 |
| 5 | `README.md`（本目录） | 怎么跑、接口一览、质检规则清单 |
| 6 | `docs/07-工作日志-2026-09-28.md` | 第一轮的实测数据与踩坑（含 UI 两轮改版的根因测量） |
| 7 | `docs/04-金标准-example_honesty.md` | 人工金标准 —— 用来算裁判的漏报/误报 |
| 8 | `docs/05-ReadPal-接手评估.md` | 上一代项目（V1）的评估，含"为什么要推倒重来" |

---

## 2. 四条硬约束（改代码前必须知道）

### 2.1 两条质量主线（Bryan 亲定的最高优先级）

1. **四级文章内容大意保持一致**
2. **语言难度符合对应等级**

受众映射：**A1- = 小学 / A2 = 初中 / B1 = 高中 / B2+ = 高中以上**。

### 2.2 三条不可违反的内容约束

| # | 约束 | 落地位置 |
|---|---|---|
| 1 | **主题词不得因降级而丢失**（`honesty` 在 A1/A2 也必须保留） | 脚本规则 `missing_topic_word` |
| 2 | **A1- 关键人名/地名必须保留**，不受「≤3 个专有名词」限制；可写 `Graves, a scientist`，**不可**泛化成 `A scientist` | 脚本规则 `proper_noun_missing`（本项目新增） |
| 3 | **跨级降读必须接得上** —— 降级不得删掉承上启下的信息 | 裁判 `bridge_broken` |

### 2.3 改 `b2` 链路时的红线（最容易搞错）

- 输入原文的等级**由人工判定，系统不质疑、不校验**。
- **`b2` 模式下 B2+ = 原文本身，不重新生成。** 系统只向下生成 **B1 / A2 / A1- 三级**（不是四级！）。
- **改 public 模式时不得动 `b2` 的结果**。Bryan 的原话：
  「不是百分百不改，核心是**不要影响目前原流程的功能和生成质量**」。
- 新增模式的正确姿势是**另起提示词文件**（`*_news.md`），**不改正文件** ——
  生成与裁判都非确定性，原提示词改一个字旧结果就变。
- `normalize_mode()` 把未知值**一律回落 `b2`**（默认安全）。

### 2.4 人机分工

> **能机械验证的一律用脚本，不交给模型。口径问题不替人拍板。**
> P0（硬伤）自动修；**P1（口径问题）只标记，交人工**。

---

## 3. 架构与代码地图

```
V3-Content-Factory/
├── app.py              HTTP 服务（ThreadingHTTPServer）· 16 个接口 · 后台任务 · 自动修复循环
├── seed.py             导入佳阳老师的示例文章作种子数据（无密钥也能看完整形态）
├── server_keys.json    【本机文件，不进仓库】服务端模型密钥，见 §5.2
├── core/
│   ├── quality.py       关卡一：17 类确定性质检 → 结构化 issue(rule, level, target, params, hint_key)
│   │                    含 source_mode 分支：news 下 B2+ 取产物、人名基准换成新闻原稿
│   ├── llm.py           两类模型调用（生成/裁判）+ 局部重写；P0/P1 由系统按 type 映射
│   │                    SOURCE_B2/SOURCE_NEWS + normalize_mode() + prompt_name() 按模式切提示词
│   ├── render.py        docx 渲染，复用老师 template.docx 的 Normal/DocTitle/DocLevel 样式
│   └── store.py         JSON 落盘，沿用老师 articles/{id}/ 目录
├── prompts/
│   ├── generate.md      模型 A 系统提示词（b2 模式）—— 直接复用佳阳老师原文，未改一字
│   ├── judge.md         模型 B 裁判提示词（b2 模式）—— v0「无细判据版」+ 新增 ambiguous_word
│   ├── generate_news.md news 模式的生成提示词（含 source_level 自评）
│   └── judge_news.md    news 模式的裁判提示词
├── assets/template.docx 老师提供的 docx 模板
├── public/index.html    前端（单文件 · 浅/深双主题 · 中英双语 · hash 路由）
└── data/articles/{id}/  每篇一个目录：original.txt · cards.json · check_report.json
                         · judge_report.json · fix_log.json · meta.json · *.docx
```

### 3.1 两道关卡的职责边界（不要越界）

| | L1 确定性脚本（`core/quality.py`） | L2 语义裁判（`core/llm.py::judge`） |
|---|---|---|
| 管什么 | **形式**：数词、句长、引用逐字存在、题目结构、人名保留、多义实词词形 | **语义**：事实有没有增/删/改、四级是否对齐、跨级是否断裂、词义是否会被读错 |
| 成本 | 毫秒、免费 | 一次模型调用、花钱花时间 |
| 输出 | 结构化 issue（可点击定位） | 按 type 分类的问题列表 + evidence |
| 触发 | 每次生成后**自动**跑；手改后可按钮重跑 | 只在脚本 0 错后跑；手改后**单独按钮**重跑 |
| 语气 | 判错就是判错 | **宁可漏报，不要误报**（v0 原则） |

**裁判只做脚本做不了的判断。** 脚本已拦的不要在裁判里重复查 —— 只增 token，无增量。

### 3.2 质检规则全景（17 类：判错 12 + 警告 5）

**判错**：`card_count_mismatch` · `word_ratio` · `sentence_too_long` · `missing_topic_word` ·
`question_count` · `option_count` · `invalid_answer` · `explanation_quote_missing` ·
`question_quote_missing` · `split_failed`（切卡失败/首卡未从原文开头） · **`proper_noun_missing`（本项目新增）**

**警告**：`sentence_too_short` · `flag_word` · **`polysemy_word`（第 16 类，本项目新增）** ·
`same_answer_letters` · **`source_level_low`（第 17 类，本项目新增）**

- **第 16 类 `polysemy_word`**：多义实词词形命中（`POLYSEMY_WORDS`），只在 A1-/A2 提示。
  **只判词形、不判语境** —— 语境判断属语义，交给裁判。清单**宁窄勿宽**，报太密就没人看。
- **第 17 类 `source_level_low`**：仅 `news` 模式。原稿自评等级偏低时提示换稿。

### 3.3 裁判问题类型（9 类）

`fact_added` · `fact_dropped` · `fact_altered` · `card_misaligned` · `bridge_broken` ·
`topic_word_weak` · `answer_unsupported` · `option_unfair` · **`ambiguous_word`（本项目新增）**

其中 **P0（自动修）**= 前四项 + `answer_unsupported`；**P1（只报告）**= 其余。

### 3.4 自动修复循环（轮次上限是硬性要求）

```
生成 → L1 脚本质检 ─有错→ 局部重写（只重出报错的那张卡）→ 回 L1   [上限 3 轮]
          ↓ 0 错
        L2 语义裁判 ─有 P0→ 局部重写 → 回 L1 → 再 L2              [上限 2 轮]
          ↓ 无 P0
        渲染 → 完成
          ↓ 超轮次
       needs_human（把问题清单交给人）
```

- **只局部重写，不整篇重跑**（最省 token，也正是老师原设计「重写 B1」的用法）。
- **P1 不触发自动修复**，只标记。
- `fix_log` 必须留痕（否则无法追因"哪次修改让结果通过"）。

---

## 4. 已知的坑（别再踩一遍）

### 4.1 前端

| 坑 | 现象 | 解法 |
|---|---|---|
| `display:flex` 盖掉 `hidden` 属性 | 面板该隐藏时仍显示 | 补 `[hidden]{display:none!important}`，放在组件规则**之后** |
| ≤1040px 时 `.stage` 被压成 0 高 | 编辑区整块消失 | `.stage { flex: 0 0 auto; overflow: visible }` |
| 改默认值的代码必须先处理存量存储 | 把默认主题改成 light，老访客看不到效果（localStorage 里存着 "dark"） | **换 key**（`v3.theme.v2`）一次性作废旧值 |
| **门控只看本地字段** | 服务端 key 已配好（`/api/config` 返回 `ready:true`），点「新建生产」仍被拦回模型设置框 | 用 `modelReady(which)` = 前端填齐 **或** 服务端就绪。**改完前端必须走真实点击路径，只验 API 会漏** |
| headless Chrome `--window-size` 有 500px 下限 | 窄于此的截图右侧被裁 → 误判成"布局溢出" | 用 `documentElement.scrollWidth === clientWidth` 判断，**不要拿截图宽度当视口宽度** |

### 4.2 后端

- Python 标准库 `http.server` 用 `protocol_version = "HTTP/1.1"` 时，**所有响应必须带 Content-Length**，否则连接挂死。
- **`max_tokens` 把思考 token 也算在内**。实测（deepseek-flash / 285 词新闻稿）：
  设 16384 → 报「模型返回为空」，`finish_reason=length`，思考吃满 16383、**正文 0 字符**；
  不设限时思考 27016 + 正文 12462 字符。→ `NEWS_MAX_TOKENS = 65536`，**仅 news 模式传，换模型必须重新标定**。
- **新字段要记得落库**：`source_level` 没写进 `article` 时，第 17 类提醒永不触发。
- 前端 `<dialog open>`（非模态）会被 `main { z-index: 1 }` 盖住 —— 这是非模态的产物，不是 bug。
- ~~docx 下载走 `<a href>` 跳转，带不上自定义请求头 → 鉴权必须同时下发 Cookie~~
  **访问口令已于 2026-10-01 整体移除**（后端 `_guard` / Cookie `v3code` / 前端 `dlg-code` 全删）。
  **若日后要重新加鉴权，这条结论仍然成立**：docx 下载是浏览器跳转，带不上自定义请求头，只能靠 Cookie。

### 4.3 验证纪律（血泪教训）

- **做无头浏览器测量时，注入的探针必须与还原写在同一条命令里**，收尾断言 `count('<script>') == 1`。
  曾经两次把探针污染进待发布文件。
- 探针输出**不要用 `innerHTML`**（测量文本里的 `<<<OVERFLOW` 会被当成标签截断）→
  改用 `document.title = 'FIT::' + out`，最稳。
- **零回归验证法（可复用）**：用 `git show HEAD:` 导出**改动前**的 core，跑同一输入，逐字节 diff
  `gen_input / judge_input / rewrite_input / report / cards_len / prompt 名`。
  实际用过一次，34578 字节完全一致。
  ⚠️ **必须防假通过**：重跑前先 `rm -f` 上次输出，跑完 `ls -l` 确认文件**真实生成**。
  否则 diff 比的是残留文件，会显示"一致"（真踩到过）。
- 部署后核验：**线上截图与本地截图 md5 相同**才算真的一致。

---

## 5. 怎么跑、怎么验

```bash
cd V3-Content-Factory
python3 app.py 8801        # 零第三方依赖，只用标准库 → http://127.0.0.1:8801
python3 seed.py            # 首次启动后导入示例数据（无密钥也能看到完整成品形态）
```

### 5.1 模型密钥（两条路，互不覆盖）

**路 A · 前端填**：存浏览器 localStorage，随请求体转发，不落服务器磁盘。

**路 B · 服务端配**（线上必须走这条）：环境变量 `GEN_BASE_URL / GEN_API_KEY / GEN_MODEL`、
`JUDGE_BASE_URL / JUDGE_API_KEY / JUDGE_MODEL`。

### 5.2 `server_keys.json` —— 线上没有环境变量入口的解法

发布沙箱**没有注入环境变量的入口**，所以服务端 key 放在 `server_keys.json`：

- **本机文件权限 600，已 gitignore，绝不进公开仓库**
- `app.py` 启动时把它补进 `os.environ`：**环境变量优先，文件只补空缺**
- 新设备接手时需要**另配**（这个文件不在 git 里）；**缺了不影响启动**（直接跳过），
  只是本地要用就得自己填 key

### 5.3 访问口令 —— 已于 2026-10-01 移除

Bryan 明确：**这是内部 demo，只有几个人用，不需要口令。**

已删除：`server_keys.json` 的 `access_code` 读取 · 后端 `_guard()` / `_cookie_code()` ·
鉴权 Cookie `v3code` · 前端 `dlg-code` 对话框 / `LS_CODE` / `X-Access-Code` 请求头 / 401 分支。

> **不要再加回来。** 现在所有 `/api/*` 无鉴权直通 —— 只放内部 demo 用，**别往上面放敏感数据**。

### 5.4 默认模型（`public/index.html` 的 `DEFAULT_CONFIG`）

| 角色 | base_url | model |
|---|---|---|
| 生成 | `https://api.deepseek.com` | `deepseek-flash` |
| 裁判 | `https://api.siliconflow.cn/v1` | `Qwen/Qwen3.8-27B` |

**验收 6 项**（见 `docs/02-Demo规格-v1.1.md`）：
V1 能出内容 · V2 形式达标 · V3 内容达标 · V4 门槛低 · V5 可编辑 · V6 可交付。

---

## 6. 部署与发布（**本机改这里前必读**）

### 6.1 当前线上 —— 2026-10-01 起重定为**单一入口**

| 项 | 值 |
|---|---|
| **正式入口** | `https://graded-reading-factory.app.workbuddy.host/` |
| appId | `wbapp_ht8T4x4I5dDuv5iZhcZ8fT` |
| 由谁发布 | **本机 / 本工作区**（也只有这里能更新它） |
| 访问口令 | ❌ 无（2026-10-01 按要求移除） |
| 服务端密钥 | ✅ 由 `server_keys.json` 提供，随发布上传（本机 600 权限，已 gitignore，不入公开仓库） |
| 线上文章 | 1 篇（seed） |
| 线上版本 | **2026-10-01 21:20 · 视觉改版（校样台 · Press Proof）+ 拉丁字体自托管**，线上 `index.html` md5 与本地一致 |

**2026-10-01 21:20 重新发布实测**（这次是覆盖 `graded-reading-factory`）：

| 验证项 | 结果 |
|---|---|
| 首页 | 200，144336 B，md5 `22499aa1…` 与本地**完全一致** |
| 自托管字体 | 三个全 200，字节数 67388 / 34940 / 31340 与本地一致 |
| 类型 | `deployedAs: http-service` → **线上跑的是 app.py，不是纯静态托管** |
| 断网模拟（CDP 屏蔽 Google 双域） | 标题仍 `Fraunces`、数字仍 `JetBrains Mono` → 自托管生效，不依赖被墙域名 |
| 桌面 1440 / 移动 390 触屏 | 均无横向溢出；触屏命中区 <44px **归零** |
| API | `/api/articles` 200 |

> **改域名（想换成 yiluzhi 相关）唯一的路**：发布工具**只会覆盖**，没有「创建第二个应用」的参数，
> `domainPrefix` 也**只在新应用创建时生效**。所以改域名必须**用户自己去
> 「设置—数据管理—发布的应用」新建一个应用**，再从该应用发布。
> 实测（2026-10-01）：带着 `domainPrefix=yiluzhi-content-studio` 重新发布，
> 返回的 `shareLink` **仍然是** `graded-reading-factory`，域名不会因为重发布而改变。
> 顺带确认：**`unpublish` 也不删应用**（只让链接失效），所以「删掉再发」这条路同样换不到域名。

**已弃用**：`yiluzhi-content-factory.app.workbuddy.host`（`wbapp_qjgd70pZpbr4URRBDYpC43`）
—— 它由**另一台设备的工作区**创建，**本机发布不到它**（原因见 6.2）。
Bryan 确认**这个链接从未发出去**，所以换掉它没有成本。

> ⚠️ **切换的代价（必须知悉）**：`yiluzhi` 上有 `server_keys.json`（服务端模型密钥）与
> **4 篇线上文章**，本机两样都拿不到（口令未知、文件不在本机）。切到正式入口后：
> ① **使用者要各自在「模型设置」里填一次 key**；② 那 4 篇文章留在原应用，**没有迁过来**。
>
> 要救回来：去另一台设备取 `V3-Content-Factory/server_keys.json`（里面有 `access_code`），
> 或用**曾经成功打开过该应用的浏览器**，从 devtools → localStorage 的 `v3.accessCode` 读出口令。

### 6.2 发布工具到底怎么认应用（2026-10-01 实测，**上一版这里写错了**）

**能确定的事实**（本机连发两次，都打在 `graded-reading-factory` 上）：

| 记录 | 值 |
|---|---|
| `deployTargetId` | `sha256(目录绝对路径)[:16]` —— 只是**这次发布的目录标识**，不是应用标识 |
| 本次算出的 targetId | `1405f75c208f45b9`（目录 `…/AI-Content-Center/V3-Content-Factory`） |
| 实际写入的 appId | `wbapp_ht8T4x4I5dDuv5iZhcZ8fT`（旧应用） |

**两条被证伪的做法**（别再浪费时间）：

- ❌ **手写 `.wbapp_<appId>.genie` 不能指定目标应用。**
  2026-10-01 本机写过 `wbapp_qjgd…genie` 且 `localDir` 正确指向发布目录，
  发布仍然打到 `ht8T4x4`；工具还自己补写了一个 `ht8T4x4` 的 genie。
- ❌ **deploy 时传 `appId` 无效。** 传了 `appId=wbapp_qjgd70pZpbr4URRBDYpC43`，
  返回的 `shareLink` 依旧是 `graded-reading-factory`。

**推论（推测，但和两次实测一致）**：应用是**按「工作区」绑定**的 ——
工具拿本工作区（`workspaceKey = dda6f87f64e0bb4b`）去查它已经发布过的应用，
收敛到那一个，和你传哪个目录、哪个 appId 都无关。

**由此得到的硬结论**：

> **在另一个工作区里创建的应用，本机改不到。**
> `yiluzhi-content-factory` 是另一台设备（用户名 `jinsongli`、工作区路径不同）创建的，
> 所以**从本机发布，永远只会覆盖 `graded-reading-factory`**。

改代码不影响这点；要更新在用的那个应用，只有两条路：
① 回到创建它的那台设备发布；② 放弃它、另立一个本机能更新的链接作正式入口。

### 6.3 只有一份代码

`<工作区>/AI-Content-Center/V3-Content-Factory` 是**唯一副本**，改完直接发布，**不需要 rsync**。
（曾经的 `<工作区>/V3-Content-Factory` 开发副本已于 2026-10-01 弃用并改名归档，
它曾造成文档漂移 —— 两份 README 内容不一致、丢过一次内容。）

---

## 7. 当前状态与下一步

### 已完成

- ✅ 需求澄清（`docs/00`）· 设计总纲（`docs/01`）· Demo 规格 v1.1（`docs/02`）· 裁判 v0（`docs/03`）· 金标准（`docs/04`）
- ✅ V3 全量实现：17 类质检 / 2 次模型调用 / 自动修复循环 / 16 个接口 / docx 导出
- ✅ 前端：浅色极简风 · 浅深主题切换 · 中英双语 · 四级对照编辑台 · 结构化质检面板
- ✅ 种子数据实测：词数 175/242/321/443（40%/55%/72%），与老师 `report.txt` **完全一致**
- ✅ **新增的人名保留规则当场抓出 `Franklin` 和 `Graves` 两个人名丢失** —— 而老师原脚本判「✓ 通过」
- ✅ 「新闻原稿」来源模式上线（四级全部生成），线上端到端真跑通过
- ✅ 服务端密钥上线；`ready` 改为**字段层 + 实测层**双校验
- ✅ 文章库支持删除；生成模型换 `deepseek-flash`；裁判关闭思考

### 2026-10-01 追加（本轮）

- ✅ **访问口令整体移除**（后端 + 前端 + 中英 i18n）：`app.py` 809 → 767 行，`index.html` 少 26 行
- ✅ 线上入口**重定为 `graded-reading-factory`**（本机唯一能维护的应用），`yiluzhi` 弃用
- ✅ 发布绑定机制查清并写进 §6.2：应用**按工作区收敛**，手写 `.genie` / 传 `appId` 都无效
- ✅ 本地验收：4 个接口全 200、无 401 拦截、DOM 里 `口令` 出现 0 次、无 JS 报错、中英双语正常

### 2026-10-01 晚 · 视觉整体改版 + 拉丁字体自托管（**已上线**）

- ✅ 删掉首屏多余表述（「形式层由脚本判定，内容层由异源模型裁判」那段）
- ✅ 按 AWWWARDS / FWA 获奖级标准重做八个维度：排版 / 留白 / 层级 / 色彩 / 动效 / 微交互 / 响应式 / 原创性
- ✅ **P0 修复：拉丁字体改自托管**。原来 Fraunces / Archivo / JetBrains Mono / Noto Serif SC /
  Noto Sans SC 全套向 `fonts.googleapis.com` 请求 —— 该域**在中国大陆不可达，且失败是静默的**：
  浏览器沿 font-family 兜底回宋体，**本机看着正常、线上完全不同**。
  现在拉丁三款放 `public/fonts/*.woff2`，由 `app.py` 的 `/static/<rel>` → `public/<rel>` 提供；
  CJK 保留 Google 作异步增强，`--font-*` 兜底链点名系统字体（苹方 / 雅黑 / 宋体）。
- ✅ 新增原创性符号：套准十字品牌标（准线不穿圆心）、四角裁切角标、纸纹 `feTurbulence` 层、版心栏线
- ✅ 修 Chrome 原生控件残留（`accent-color` / `caret-color` 默认蓝）、`<code>` 无样式、
  `.dlg-head` sticky 遮挡对话框顶部角标
- ✅ **触屏兜底整段移到样式表末尾** —— 媒体查询不加权重，原来被后面同权重的普通规则覆盖
- ✅ 14 档视口回归（360/390/768/1280/1440/1680 × 明暗 × 桌面/触屏）：横向溢出 0、
  触屏 <44px 归零、真实渲染文字对比度 0 处不达标
- ✅ 已同步上线（状态见 §6.1），本地与线上 `index.html` md5 一致

> **字体排查的三个假象（血泪）**：
> ① `document.fonts.size === 0` 往往是样式表还没生效，不是 bug；
> ② `canvas.measureText` **必须同时跟 `serif` 和 `sans-serif` 比** —— 只跟 serif 比会把
> 「根本没加载」误判成「在用」（Fraunces 596.8 vs serif 521.76 看着像在用，
> 其实与 sans-serif 601 几乎相同 = 没加载）；
> ③ 判字体是否真在线上生效，最硬的办法是 CDP `Network.setBlockedURLs` **把
> `fonts.googleapis.com,fonts.gstatic.com` 整段屏蔽**，再看 `getComputedStyle` 的字体名。

### 下一步（按优先级）

1. **【最高】月饼文的两个质量缺口**（详见 `docs/08` 第四节，**等 Bryan 拍板**）：
   - **加「单卡词数」上限**（拟 A1- ≤25 / A2 ≤35 / B1 ≤45 / B2+ ≤60，超限进自动修复）
     —— 真问题是**段落长度**不是句子长度；现有质检只卡单句上下限与整级总占比，
     **内部分布畸形是盲区**（实测末卡爆掉：A1- 34 / A2 49 / B1 61 / B2+ 83 词）
   - **超纲词口径**：现在**没有任何词汇表**，只有十几个语法信号词 → 要么等教研词表，要么先用公开 CEFR 词表搭一版
2. **V4 内容生产平台**（已暂缓，等 Bryan 给 CEFR 分级指南）——
   需求与 Prompt 1/2 硬约束已完整记录在 `docs/08` 第五节；提示词原文在 `~/Desktop/Prompts V1.docx`
3. 线上已复现：A1- 词数超限（76 词 / 目标 48–67）
4. 裁判实测仍未做（第一轮就列的第一优先项，被新闻模式插队）

### 未决（卡在教研/业务侧，不阻塞开发）

- A1- 词数占比是否放宽下限（实测 40%，区间上限 42%，余量仅 2pp）
- 老师示例是否按「人名保留」新规则更新
- 8 + 1 类裁判问题的判据边界 + P0/P1 分级线

---

## 8. 做事方式（Bryan 的偏好，照做）

- **真实第一。** 不编造事实、数据、来源。不确定就标注，不知道就说不知道。他会拿输出去做真实决策。
- **直接、算账清楚、不吹捧。** 要明确判断和取舍，不要「都行」「看你自己」。
- **言简意赅。** 先给结论 + 关键取舍；细节放文件里，回复只做摘要。
- **说数字要能复现。** 报「余量 2pp」就要能说清是怎么量出来的。
- **不要糊弄。** 实测过才说通过；没实测的明说是推测。
