# HANDOFF —— 交接快照

> 一页纸告诉你：现在在哪、东西在哪、下一步干什么。
> 快照时间：2026-10-01 16:05（GMT+8）

---

## 1. 一句话状态

**V3 已实现、已部署在「一鹿知」新应用上，代码与文档已同步到 `main` `96aee9f`。**
「新闻原稿」来源模式、服务端密钥 + 访问口令都已上线。
**未决的硬项两个**：① 月饼文的质量缺口（等 Bryan 拍板）② V4（等 CEFR 分级指南）。

---

## 2. 线上地址与应用管理

| 项 | 值 |
|---|---|
| **线上地址（在用）** | `https://yiluzhi-content-factory.app.workbuddy.host/` |
| appId（在用） | `wbapp_qjgd70pZpbr4URRBDYpC43` |
| **发布目录** | `<工作区>/AI-Content-Center/V3-Content-Factory`（**唯一副本**） |
| 访问口令 | `server_keys.json` 的 `access_code`（**不在仓库里**，新设备需另配） |
| 管理入口 | WorkBuddy「设置 → 数据管理 → 发布的应用」 |

> ⚠️ 旧应用 `graded-reading-factory.app.workbuddy.host`
> （`wbapp_ht8T4x4I5dDuv5iZhcZ8fT`）**已弃用**，不要再往那儿发。

**发布机制（实测出来的，很重要）**：发布工具按**目录的绝对路径**认应用 ——
`deployTargetId = sha256(绝对路径)[:16]`，映射记在 `.wbapp_<id>.genie`（工作区根）
与 `~/.workbuddy/cloudstudio-deploy-history/`。
所以**换目录发布 = 新建应用、换链接**；想让两台设备发到同一个应用，
两边的发布目录都要有指向**同一个 appId** 的记录。

---

## 3. 这次交接都做了什么

### 3.1 第一轮（2026-09-28 20:54 → 09-29 00:40）

- 克隆并实跑评估上一代仓库（ReadPal）→ `docs/05`
- 用 `grill-me` 深度追问需求 → `docs/00`
- **最重要的诊断**：V1 搭了 8 个工作流，效果**不如裸模型 + 老师 skill**。
  根因不是提示词，而是 **8 次串联 = 8 次信息损耗 + 0 次质量增益**，且**没有 evals**。
- 关键发现：佳阳老师的工具包强，不是因为提示词，而是**自带 14 类确定性校验**
- 新建干净项目 V3；实跑验证；两轮 UI 改版（浅色极简 + 浅深主题 + 中英双语）
- 改名「一鹿知 · 内容生产平台」；删顶栏重复按钮

### 3.2 第二轮（2026-09-29，另一台设备/模型）

详见 `docs/08-工作日志-2026-09-29.md`，共 12 个提交：

- **「新闻原稿」来源模式**（`source_mode=news`，四级全部生成）—— 最大改动
- **服务端密钥 + 访问口令**（线上没有环境变量入口 → `server_keys.json`）
- 生成模型换 `deepseek-flash`；裁判关闭思考 + 修 3 个稳定性缺陷
- 新增第 16 类（多义实词词形提醒）+ 第 17 类（原稿等级偏低）检查
- 新增裁判 `ambiguous_word` 类
- 文章库支持删除；左上角品牌可点击回工作台
- **月饼文质量诊断**（关键发现：规则有盲区，见第四节）

### 3.3 第三轮（2026-10-01，本机）

- 对齐代码到 `96aee9f`，冒烟验证通过（首页/health/config/articles 全通）
- **解决线上双应用问题**：确立唯一副本，补上指向在用 appId 的发布绑定
- 弃用旧的开发副本（改名归档，未删除）—— 它曾造成两份 README 内容漂移
- **补写本目录三份文档**（AGENTS / HANDOFF / README 在上一轮 12 个提交里一个字没更新）

---

## 4. 跨设备怎么恢复（换电脑/换模型时的清单）

### 4.1 代码

```bash
git clone https://github.com/Jinsong96/AI-Content-Center.git
cd AI-Content-Center/V3-Content-Factory
python3 app.py 8801          # 零第三方依赖
python3 seed.py              # 导入示例数据
```

**没有任何第三方依赖需要安装**（全 Python 标准库 + 原生 HTML/CSS/JS）。

### 4.2 技能（`~/.workbuddy/skills/` 不在 git 里，需单独恢复）

> ⚠️ `~/.workbuddy` **不是 git 仓库、无任何备份机制**。自建技能只存本机，换电脑即永久丢失。

本次用到的**市场技能**（重新装即可）：`grill-me`、`frontend-design`。
本机自建的技能清单与备份方案见 `docs/06-技能清单与跨设备恢复.md`。

### 4.3 凭证与配置

| 需要什么 | 用途 | 状态 |
|---|---|---|
| GitHub 推送凭据 | 推代码 | 需各自配。本机 09-29/10-01 用临时 PAT（**未落盘**）；另一台设备用 macOS 钥匙串 |
| `server_keys.json` | 线上模型密钥 + 访问口令 | **不在仓库**，新设备需另配 |
| 模型 API key | 生成 / 裁判 | 也可由各人在浏览器里填 |

**本机可用的推送命令**（直连 github 的 git 协议不通，**必须走 7890 代理且必须用小写变量**）：

```bash
GH_PAT='<token>' GIT_ASKPASS=/tmp/.ghaskpass GIT_TERMINAL_PROMPT=0 \
  http_proxy=http://127.0.0.1:7890 https_proxy=http://127.0.0.1:7890 \
  git -c credential.helper= push https://x-access-token@github.com/Jinsong96/AI-Content-Center.git main
```

或用 macOS 钥匙串一次性配好（更省事）：

```bash
printf 'protocol=https\nhost=github.com\nusername=x-access-token\npassword=<ghp_…>\n\n' \
  | git credential-osxkeychain store
```

---

## 5. 下一步（按优先级）

| # | 任务 | 说明 |
|---|---|---|
| 1 | **月饼文两个质量缺口** | **等 Bryan 拍板，可立即动手**，不需要任何外部依赖。详见 `docs/08` 第四节 |
| 1a | 加「单卡词数」上限 | 拟 A1- ≤25 / A2 ≤35 / B1 ≤45 / B2+ ≤60，超限进自动修复。真问题是**段落长度**不是句子长度；现有质检只卡单句上下限与整级总占比，**内部分布畸形是盲区** |
| 1b | 超纲词口径 | 现在**没有任何词汇表**，只有十几个语法信号词。要教研词表（最准）或先用公开 CEFR 词表搭一版 |
| 2 | **V4 内容生产平台** | **已暂缓，等 Bryan 的 CEFR 分级指南**。需求、Prompt 1/2 硬约束已完整记在 `docs/08` 第五节 |
| 3 | 裁判实测 | 第一轮就列的最高优先项，被新闻模式插队，**仍未做**。用真模型跑 `example_honesty`，对照 `docs/04` 金标准算漏报/误报 |
| 4 | A1- 词数超限 | 线上已复现：76 词 / 目标 48–67 |
| 5 | A1- 卡 5 自相矛盾 | 线上已复现 |
| 6 | `backend/keys.fallback.json` | **被 git 跟踪且含 7 个明文 key，仓库 public**。建议轮换 + 清空。Bryan 2026-10-01 明确说**这个先不用管** |

---

## 6. 不要做的事

- ❌ 不要给模型 A 加"判据"式硬限制 —— 先跑无细判据版，测误报率再决定
- ❌ 不要在裁判里重复脚本已拦的检查
- ❌ 不要让裁判自动触发重写（v0 阶段裁判与重写**解耦**，只标记）
- ❌ 不要把 `b2` 模式的原文重新生成一遍（B2+ = 原文本身）
- ❌ 不要把 A1- 的人名泛化成 `A scientist`
- ❌ 不要新增模式时直接改 `generate.md` / `judge.md` —— **另起 `*_news.md`**
- ❌ 不要引入第三方依赖（当前零依赖是刻意设计）
- ❌ **不要换发布目录** —— 会新建应用、换链接，现有分享链接上的内容不会更新
- ❌ 不要再往旧应用 `graded-reading-factory` 发东西（已弃用）
