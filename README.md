# ReadPal · AI 英语分级阅读平台

**一个仓库，两套东西，各自独立运行。**

| | 名称 | 线上入口 | 前端入口文件 | 干什么 |
|---|---|---|---|---|
| 🔵 | **V1 智能体**<br>内容生产后台 | `/` | `frontend/index.html` | 从热点 / 自有版权 / 公版书采集英文素材 → 敏感筛查 → 事实抽取 → 四档分级改写 → 人工逐段审核 → 文章库。产出可发布的文章，配套封面、音频、阅读题。用户是教研 + 市场运营，驱动是「内容库缺什么」。 |
| 🟢 | **V2 智能体**<br>分级卡片 | `/card` | `frontend/card.html` | 贴一篇英文原文（B2+ 母稿）→ 一次产出 **A1- / A2 / B1 / B2+ 四档分级卡片**，每档 3 道题 + 解析 → 纯代码质检 → 不达标自动带差量回炉重跑 → 导出 Word。 |

线上地址：

- V1 → `https://web-production-2a16e.up.railway.app`
- V2 → `https://web-production-2a16e.up.railway.app/card`

> **两套互不影响。** V2 是独立链路：独立前端文件、独立 Dify 图、独立样式与质检模块。
> 后端 `backend/agent_reach_bridge.py` 里 `/` 与 `/card` 是两条独立路由，改一边不会碰另一边。

产品原则：**AI-assisted · Human-verified** —— AI 负责生产，人负责把关。

---

## 快速开始（换电脑 / 换账号时看这里）

### 1. 拉源码

```bash
# 别 git clone —— 仓库含约 90MB 音频
python3 tools/fetch_sources.py "<工作区>/readpal"
```

### 2. 配置密钥（首次必做）

仓库**不含任何密钥**。克隆后需要自己建一份本地配置：

```bash
cp frontend/config.local.js.example frontend/config.local.js
# 然后编辑 config.local.js，填入真实值
```

| 变量 | 用途 | 获取位置 |
|---|---|---|
| `SF_API_KEY` | 文生图 + LLM + TTS | SiliconFlow 控制台 |
| `DIFY_WF_MAIN` | V1 主工作流 | Dify 工作流 → API 密钥 |
| `DIFY_WF_GEN` | V1 生成工作流 | 同上 |
| `DIFY_WF_FACT` | V1 事实抽取工作流 | 同上 |
| `DIFY_WF_CARD` | **V2 分级卡片工作流** | 同上（独立 App，与上面三个不同） |
| `DEMO_PASS` | 演示账号统一密码 | 任意自设 |

> ⚠️ `config.local.js` 已被 `.gitignore` 排除，**不会**被提交。请勿强行 `git add -f`。

**线上是怎么拿到密钥的**：部署平台（Railway）环境变量优先；服务端读密钥后在返回 HTML 时**内联注入**，
把页面里 `<script src="config.local.js">` 换成内联配置。所以线上页面自带密钥，任何设备打开都能用。

### 3. 打开页面 / 起服务

```bash
open frontend/index.html          # V1：纯前端单文件，无需构建，双击也能开
open frontend/card.html           # V2：同样单文件（另需同目录的 card_check.js）
```

需要素材抓取、TTS、Dify 代理时起本地桥接层：

```bash
cd backend
python3 agent_reach_bridge.py     # 默认监听 8787
```

后端若需密钥，复制 `.env.example` 为 `.env` 后填写。

### 4. 装回技能（换设备必做）

技能运行副本在 `~/.workbuddy/skills/`，**只存在于装了它的那台机器上**，换电脑就没了。
仓库 `skills/` 下有四份镜像，按需复制回去：

```bash
WS="<你的工作区>"; mkdir -p ~/.workbuddy/skills
cp -R "$WS/readpal/skills/readpal-frontend"      ~/.workbuddy/skills/   # 改 V1 前端
cp -R "$WS/readpal/skills/readpal-dify-workflow" ~/.workbuddy/skills/   # 改 Dify 图
cp -R "$WS/readpal/skills/cefr-card-rewrite"     ~/.workbuddy/skills/   # 改 V2 卡片链路
cp -R "$WS/readpal/skills/readpal-import-pack"   ~/.workbuddy/skills/   # 文档拆分 / 导入包
cp "$WS/readpal/tools/.env.json" ~/.workbuddy/skills/readpal-frontend/scripts/.env.json
```

---

## 两套东西分别是什么

### 🔵 V1 智能体 · 内容生产后台（`/`）

| 项 | 值 |
|---|---|
| 前端 | `frontend/index.html`（单文件，含全部 UI / 逻辑 / 样式） |
| 后端 | `backend/agent_reach_bridge.py`（`/api` 接口 + 页面托管） |
| Dify 图 | `dify_graphs/main.*.json`、`gen.*.json`、`fact.*.json`、`factcheck.*.json` |
| 授权母稿链路 | `dify_graphs/graphA.*.json`（母稿预处理）+ `graphB.*.json`（向下生成） |
| 技能 | `readpal-frontend`、`readpal-dify-workflow` |
| 分级 | 4 档 `A1- / A2 / B1 / B2+`；常规链路每篇 **12 段** |

链路：素材创建（含热点）→ 素材库 → 文章生产 → 文章库 → APP。
**发布 / 分发不做**；主平台只负责把内容生产出来。

### 🟢 V2 智能体 · 分级卡片（`/card`）

| 项 | 值 |
|---|---|
| 前端 | `frontend/card.html` |
| 质检 | `frontend/card_check.js`（**纯代码判定，零 AI 调用**） |
| 样式模板 | `frontend/template.docx`（导出 Word 用） |
| Dify 图 | `dify_graphs/card.new.json`（Dify 上独立 App） |
| 技能 | `cefr-card-rewrite` |
| 工具 | `tools/build_card_graph.py`（建图）、`tools/probe_card_*.mjs`（回归）、`tools/sync_card_shared.mjs` |

**它跟 V1 的根本区别**：V1 是「母稿 → 12 段文章」，V2 是「母稿 → 四档卡片」。

- **母稿 = B2+ 那一档**，不受分级标准限制，由代码从原文**逐字硬取**（模型碰不到），所以 B2+ 永远是原文。
- **A1- / A2 / B1 由模型向下改写**，每档卡片数**与母稿段落数一致**，第 N 张卡讲同一件事。
- **字数靠「句数」控，不靠「句长」** —— 模型自然句长只有约 12 词，压字数只能靠少写几句。
- **质检全是代码判的**：卡片数四档一致 · 词数占原文比例 · 句数硬上限 · 句长上下限 ·
  主题词每档必现 · 题数 3 / 选项 4 / 答案字母 · 题干与解析引用的英文**必须逐字能在本级正文里找到**。
- **回炉**：不达标就带**结构化差量**重跑没过的档（最多 5 轮），已通过的档锁定不动，改不坏。
  单次生成达标率实测 60–70%，靠回炉收敛。

> ⚠️ 判「回炉有没有真的在跑」只看面板轮次与 `state.rounds` —— 界面看着永远是对齐的。
> 踩过的坑：跨侧传文本时按位置解析档位名，导致整轮作废且**不报错**。

---

## 日常工作流（重要）

这个项目有个特殊矛盾：**线上演示需要密钥，但 git 仓库不能有密钥**。
解决办法是「部署时临时注入，部署完立刻还原」，由两个脚本完成。

### 平时改代码

直接改 `frontend/index.html`（V1）或 `frontend/card.html`（V2）。仓库里的版本永远干净，随时可以提交。

### 部署演示（密钥临时注入）

```bash
python3 tools/deploy_demo.py prepare    # 把 config.local.js 内联进 index.html
# ... 执行部署 ...
python3 tools/deploy_demo.py cleanup    # 部署完立刻还原成干净版
python3 tools/deploy_demo.py status     # 随时查看当前是干净版还是注入版
```

- `prepare` 会先把干净版备份到项目内 `.deploy_backup/`（已 gitignore），`cleanup` 从备份还原，**不依赖 git**，所以不会误伤你还没提交的改动。
- 密钥在磁盘上的暴露窗口只有部署那几十秒。
- 忘记 `cleanup` 也进不了 git，但**线上会留着密钥**，所以还是记得执行。

### 每天下班前归档

```bash
./tools/daily_sync.sh                    # 默认提交信息「chore: YYYY-MM-DD 日常更新」
./tools/daily_sync.sh "修复封面生成"       # 或自定义说明
```

脚本会**先检查 index.html 是否含密钥**，如果发现还处于注入版就直接拒绝提交，避免密钥误入 git。

### 推送到 GitHub（换电脑 / 给同事看时）

```bash
gh auth login                          # 只需做一次，浏览器点一下授权
./tools/git_setup_remote.sh 你的用户名   # 一键建私有库并推送

git push                               # 之后每次想同步就这一条
```

> 🔴 **本机 `git push` 会被拒绝**（本地与远程 `main` 历史已分叉）。
> 本机统一走 GitHub API 直传：`python3 tools/push_via_api.py <本地> <仓库路径> "说明"`。
> ⚠️ 推 `main` 会**触发 Railway 自动重新部署**（约 90 秒），期间线上短暂不可用。

> 详见 `docs/09-Git使用与协作指南.md`（含注册、建库必留空的勾选项、邀请同事、常见问题）。

### 状态速查

| 场景 | 命令 | index.html 含密钥？ | 能提交 git？ |
|---|---|---|---|
| 平时开发 | — | 否 | ✅ |
| 部署中 | `prepare` 之后 | 是 | ❌ |
| 部署后 | `cleanup` 之后 | 否 | ✅ |

---

## 目录结构

```
readpal/                      ← 仓库根目录
├── frontend/
│   ├── index.html            ★ V1 入口（约 915KB 单文件，含全部 UI/逻辑/样式）
│   ├── card.html             ★ V2 入口（分级卡片）
│   ├── card_check.js           V2 质检模块（纯代码判定）
│   ├── template.docx           V2 导出 Word 的版式模板
│   ├── config.local.js         本地密钥（不入库）
│   └── config.local.js.example 密钥配置模板（入库）
├── backend/
│   ├── agent_reach_bridge.py   桥接层 + 页面托管（/、/card 两条路由）
│   ├── start_bridge.py         启动脚本
│   ├── start_cdp.py / .sh      Chrome 调试端口守护（真守护，双 fork + setsid）
│   ├── cdp_render.js           CDP 渲染脚本
│   ├── evp_vocab_check.py      超纲词校验（阈值需与前端 offCap() 同步）
│   ├── sync_to_feishu.py       飞书同步
│   ├── .env.example            后端环境变量模板
│   └── audio/                  TTS 产物（不入库，可重新生成）
├── dify_graphs/               ★ 所有 Dify 工作流图 JSON（V1 与 V2 各一份）
├── docs/                      ★ 文档
│   ├── local-notes/                逐次改动的实测记录（最真实的一手记录）
│   ├── 07-工程化需求说明书.md       完整需求（给工程化承接方）
│   └── 08-工程化风险与改动清单.md    风险台账与改动点（对接会用）
├── skills/                    ★ 本机技能的仓库镜像（换设备靠它装回去）
├── tools/                      全部脚本（建图 / 推送 / 端到端探针）
├── calibration/                范文标定语料（345 篇）
├── dify_kb_backup/             Dify 知识库备份（分级标准、敏感规则）
├── AGENTS.md                  ★ 项目约定与踩过的坑（**动手前先读这个**）
└── README_本地运行指南.md
```

**不在仓库内**（位于上层目录，有版权 / 体积大）：`material/`（592MB 版权书籍 PDF）。

---

## 重要约定

### 唯一真源

V1 前端只有 `frontend/index.html` 一份，V2 只有 `frontend/card.html` 一份。**禁止复制副本改**，会分叉。
所有会话 / 所有电脑都改这两份。

### 路由与 step 编号（V1）

16 个模块，编号 0–15。改动任何 step 相关逻辑时，以下六处**必须同步**，否则错位白屏：

`STAGES` / `stepLabel` / 路由数组 / `SECTIONS` / `STEP_OWNER` / `ROLE_OPS`

> ⚠️ 别按函数名推断它对应哪个 step：历史遗留导致 `s12` 实际是「逐段审核」，`s9` 是「段落校对」，`s4` 是「事实抽取」。以路由数组下标为准。

### 权限（V1）

权限唯一真源是 `ROLE_OPS`。`STEP_OWNER` 仅用于侧边栏视觉标注，不作权限判断。

| 角色 | 可操作 step |
|---|---|
| 市场老师 `source` | 0–4 |
| 教研老师 `produce` | 0–9, 11（**不含 10**，生产者不自审） |
| 审核老师 `review` | 0–15 |
| 运营老师 `ops` | 12–15 |

---

## 数据在哪？（重要）

**V1 业务数据（文章 / 素材 / 发布记录）存在浏览器 localStorage 里，不是文件。**

| Key | 内容 |
|---|---|
| `wb_content_bank_v1` | 内容库文章 |
| `wb_material_bank_v1` | 素材库 |
| `wb_publish_history_v1` | 发布记录 |
| `wb_feedback_data_v1` | 用户反馈 |

→ **git 同步不了这些数据**。换浏览器或清缓存就会丢，多人之间也不共享。
→ 这个问题只有后端接入数据库后才能解决，详见 `docs/07-工程化需求说明书.md`。

> ⚠️ **V2 不存任何历史。** 生成结果只活在当前页面，刷新即丢，换设备当然也不带过去。
> V2 是「一次生成一次拿」，要留存请及时导出 Word。

---

## 已知重要约束（改代码前先看）

1. **Dify 输出 schema 双轨**：通过分支返回 `sens_level`，排除分支返回 `status:"exclude"` + `sensitive_level`。判断状态一律用兼容集合 `exclude|excluded|block|reject`，不要只判一个值。
2. **SiliconFlow 必须用非推理模型**：`Qwen3.6` / `DeepSeek-V4` 是 thinking model，输出落进 `reasoning_content`、`content` 为空。选带 `Instruct` 后缀的。
3. **图床 URL 1 小时失效**（返回带 `X-Amz-Expires=3600`），必须立即转 base64 或上传对象存储。
4. **localStorage 约 5MB 上限**：封面 base64 约 0.55MB/张，约 9 张就写满。
5. **绝不伪造内容**：抓取失败就如实标记降级，不许用 AI 编造的摘要冒充原文。
6. **V2 的字数口径与 V1 不同**：V2 用「占母稿词数的百分比 + 句数硬上限」，不是 V1 的固定词数区间。两套别混用。

---

## 相关文档

| 文档 | 用途 |
|---|---|
| `AGENTS.md` | **项目约定与全部踩坑记录 —— 接手第一份读这个** |
| `docs/local-notes/` | 逐次改动的实测记录（含每次真跑的输出） |
| `docs/07-工程化需求说明书.md` | 完整需求：架构、数据模型、接口契约、验收标准 |
| `docs/08-工程化风险与改动清单.md` | P0/P1/P2 台账、改动点、待拍板决策 |
| `docs/06-工程化交接_前端现状审计.md` | 现状审计与三个部署方案 |
| `skills/README.md` | 技能镜像的维护约定（含「改哪一侧都要看两边」的漂移教训） |
| `README_本地运行指南.md` | 本机运行细节 |
