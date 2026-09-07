# ReadPal · AI 内容生产平台

英语分级阅读内容生产平台。从热点 / 自有版权 / 公版书采集英文素材，经敏感筛查、事实抽取、CEFR 分级改写（A2/B1/B2）、人工逐段审核后，产出可发布的分级阅读文章，配套封面、音频与阅读题。

产品原则：**AI-assisted · Human-verified** —— AI 负责生产，人负责把关。

---

## 快速开始（换电脑时看这里）

### 1. 配置密钥（首次必做）

仓库**不含任何密钥**。克隆后需要自己建一份本地配置：

```bash
cp frontend/config.local.js.example frontend/config.local.js
# 然后编辑 config.local.js，填入真实值
```

需要的 4 个值：

| 变量 | 用途 | 获取位置 |
|---|---|---|
| `SF_API_KEY` | 文生图 + LLM + TTS | SiliconFlow 控制台 |
| `DIFY_WF_MAIN` | 主工作流 | Dify 工作流 → API 密钥 |
| `DIFY_WF_GEN` | 生成工作流 | 同上 |
| `DIFY_WF_FACT` | 事实抽取工作流 | 同上 |
| `DEMO_PASS` | 演示账号统一密码 | 任意自设 |

> ⚠️ `config.local.js` 已被 `.gitignore` 排除，**不会**被提交。请勿强行 `git add -f`。

### 2. 打开页面

```bash
open frontend/index.html
```

纯前端单文件，无需构建。直接双击也能打开。

### 3. 启动本地桥接层（可选）

素材抓取、标签提取、TTS 需要本地桥接层：

```bash
cd backend
python3 agent_reach_bridge.py        # 默认监听 8787
```

后端若需密钥，复制 `.env.example` 为 `.env` 后填写。

---

## 日常工作流（重要）

这个项目有个特殊矛盾：**线上演示需要密钥，但 git 仓库不能有密钥**。
解决办法是「部署时临时注入，部署完立刻还原」，由两个脚本完成。

### 平时改代码

直接改 `frontend/index.html`。仓库里的版本永远干净，随时可以提交。

### 部署演示（密钥临时注入）

```bash
python3 tools/deploy_demo.py prepare    # 把 config.local.js 内联进 index.html
# ... 执行部署 ...
python3 tools/deploy_demo.py cleanup    # 部署完立刻还原成干净版
python3 tools/deploy_demo.py status     # 随时查看当前是干净版还是注入版
```

- `prepare` 会先把干净版备份到 `/tmp/index.clean.html`，`cleanup` 从备份还原，**不依赖 git**，所以不会误伤你还没提交的改动。
- 密钥在磁盘上的暴露窗口只有部署那几十秒。
- 忘记 `cleanup` 也进不了 git，但**线上会留着密钥**，所以还是记得执行。

### 每天下班前归档

```bash
./tools/daily_sync.sh                    # 默认提交信息「chore: YYYY-MM-DD 日常更新」
./tools/daily_sync.sh "修复封面生成"       # 或自定义说明
```

脚本会**先检查 index.html 是否含密钥**，如果发现还处于注入版就直接拒绝提交，避免密钥误入 git。

### 状态速查

| 场景 | 命令 | index.html 含密钥？ | 能提交 git？ |
|---|---|---|---|
| 平时开发 | — | 否 | ✅ |
| 部署中 | `prepare` 之后 | 是 | ❌ |
| 部署后 | `cleanup` 之后 | 否 | ✅ |

---

## 目录结构

```
output/                       ← git 仓库根目录
├── frontend/
│   ├── index.html            ★ 前端唯一真源（694KB 单文件，含全部 UI/逻辑/样式）
│   ├── config.local.js         本地密钥（不入库）
│   └── config.local.js.example 密钥配置模板（入库）
├── backend/
│   ├── agent_reach_bridge.py   桥接层：10 个 /api 接口的可运行参考实现
│   ├── start_bridge.py         启动脚本
│   ├── start_cdp.py / .sh      Chrome 调试端口守护（真守护，双 fork + setsid）
│   ├── cdp_render.js           CDP 渲染脚本
│   ├── sync_to_feishu.py       飞书同步
│   ├── .env.example            后端环境变量模板
│   └── audio/                  TTS 产物（不入库，可重新生成）
├── docs/                       ★ 文档
│   ├── 07-工程化需求说明书.md       完整需求（给工程化承接方）
│   ├── 08-工程化风险与改动清单.md    风险台账与改动点（对接会用）
│   └── 01–06                      架构 / 接口 / Dify / 数据模型 / 审计
├── dify_kb_backup/             Dify 知识库备份（分级标准、敏感规则）
├── audio_samples/              示例音频
└── README_本地运行指南.md
```

**不在仓库内**（位于上层目录，有版权 / 体积大）：`material/`（592MB 版权书籍 PDF）。

---

## 重要约定

### 唯一真源

前端只有 `frontend/index.html` 一份。**禁止复制副本改**，会分叉。所有会话 / 所有电脑都改这一份。

### 路由与 step 编号

16 个模块，编号 0–15。改动任何 step 相关逻辑时，以下六处**必须同步**，否则错位白屏：

`STAGES` / `stepLabel` / 路由数组 / `SECTIONS` / `STEP_OWNER` / `ROLE_OPS`

> ⚠️ 别按函数名推断它对应哪个 step：历史遗留导致 `s12` 实际是「逐段审核」，`s9` 是「段落校对」，`s4` 是「事实抽取」。以路由数组下标为准。

### 权限

权限唯一真源是 `ROLE_OPS`。`STEP_OWNER` 仅用于侧边栏视觉标注，不作权限判断。

| 角色 | 可操作 step |
|---|---|
| 市场老师 `source` | 0–4 |
| 教研老师 `produce` | 0–9, 11（**不含 10**，生产者不自审） |
| 审核老师 `review` | 0–15 |
| 运营老师 `ops` | 12–15 |

---

## 数据在哪？（重要）

**业务数据（文章 / 素材 / 发布记录）目前存在浏览器 localStorage 里，不是文件。**

| Key | 内容 |
|---|---|
| `wb_content_bank_v1` | 内容库文章 |
| `wb_material_bank_v1` | 素材库 |
| `wb_publish_history_v1` | 发布记录 |
| `wb_feedback_data_v1` | 用户反馈 |

→ **git 同步不了这些数据**。换浏览器或清缓存就会丢，多人之间也不共享。
→ 这个问题只有后端接入数据库后才能解决，详见 `docs/07-工程化需求说明书.md`。

---

## 已知重要约束（改代码前先看）

1. **Dify 输出 schema 双轨**：通过分支返回 `sens_level`，排除分支返回 `status:"exclude"` + `sensitive_level`。判断状态一律用兼容集合 `exclude|excluded|block|reject`，不要只判一个值。
2. **SiliconFlow 必须用非推理模型**：`Qwen3.6` / `DeepSeek-V4` 是 thinking model，输出落进 `reasoning_content`、`content` 为空。选带 `Instruct` 后缀的。
3. **图床 URL 1 小时失效**（返回带 `X-Amz-Expires=3600`），必须立即转 base64 或上传对象存储。
4. **localStorage 约 5MB 上限**：封面 base64 约 0.55MB/张，约 9 张就写满。
5. **绝不伪造内容**：抓取失败就如实标记降级，不许用 AI 编造的摘要冒充原文。

---

## 相关文档

| 文档 | 用途 |
|---|---|
| `docs/07-工程化需求说明书.md` | 完整需求：架构、数据模型、接口契约、验收标准 |
| `docs/08-工程化风险与改动清单.md` | P0/P1/P2 台账、改动点、待拍板决策 |
| `docs/06-工程化交接_前端现状审计.md` | 现状审计与三个部署方案 |
| `README_本地运行指南.md` | 本机运行细节 |
