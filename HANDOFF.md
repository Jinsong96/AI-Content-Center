# HANDOFF.md — 换设备 / 换 WorkBuddy 账号 交接包

> 给人读。目标是：**换任何电脑、任何 WorkBuddy 账号，复制粘贴一段文字就能开工。**
> 最后更新：2026-09-18 · 适用仓库状态：`main` @ 4 档体系（A1- / A2 / B1 / B2+）

---

## 第 1 步：复制这段给新会话（开场面）

新电脑 / 新账号打开 WorkBuddy 后，把下面这段**整段粘贴**进去，然后把你手上的实际值填进 `[...]`，再写你要做的事即可。

```text
你要接手 ReadPal 内容生产平台（AI 英语分级阅读的内容生产后台）。

【代码在哪】
仓库：https://github.com/Jinsong96/AI-Content-Center （main 分支，PUBLIC）
- 前端真源：frontend/index.html（单文件，约 78 万字符）
- 后端真源：backend/agent_reach_bridge.py（零依赖 Python，标准库，同时托管前端 + 提供 API）
- 项目约定：仓库根 AGENTS.md —— 开工前请【完整读一遍】，里面有设计大原则 + 19 个已踩过的坑
- 换设备步骤：仓库根 HANDOFF.md（本文件）
- 逐次改动的实测记录：docs/local-notes/
- 部署与排障：RAILWAY_DEPLOY.md

【线上地址】
https://web-production-2a16e.up.railway.app
（推 GitHub 后 Railway 自动部署，约 90 秒生效）

【先拉一份源码镜像，别 git clone】
仓库含 90MB 音频，浅克隆常超时 ——
    python3 tools/fetch_sources.py "$WS/readpal"     # $WS = 当前 WorkBuddy 工作区目录

【凭证】（下面是我给你的实际值）
GitHub token: [填 ghp_ 开头的 token]
SiliconFlow key: [填 sk- 开头的 key]
Dify 事实抽取 app key: [填 app- 开头]
Dify 内容生成 app key: [填 app- 开头]

【重要提醒】
1. 本地 git 与远程 main 历史【已分叉】，`git push` 会被拒 —— 推送必须走 GitHub API 直传
   （python3 tools/push_via_api.py <本地> <远端路径> "commit message"）。AGENTS.md 第 8 节有说明。
2. 改前端单文件大 HTML 后，必须先抽 <script> 块逐个 node --check（tools/check_js.py）再推。
3. 改同一文件多处时必须用 tools/atomic_replace.py 原子替换，并发 Edit 会静默互相覆盖。
4. 判断「某个功能有没有实现」时，【Dify 图 / 桥接层 / 前端三处都要查】——
   只查一处会误判（2026-09-18 我就把已上线的词汇校验误报成了待做项）。
5. workflow 技能装在 ~/.workbuddy/skills/readpal-frontend 与 readpal-dify-workflow，
   仓库 skills/ 是它们的镜像 —— 新设备先装回去。

【我这次要做的事】
[这里写你的需求]
```

---

## 第 2 步：准备这 4 样东西

| # | 东西 | 去哪拿 | 必须吗 |
|---|---|---|---|
| 1 | **GitHub token**（`ghp_` 开头） | GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate。勾选 **`repo`** 一项即可 | ✅ 推代码必需 |
| 2 | **SiliconFlow key**（`sk-` 开头） | https://cloud.siliconflow.cn → API 密钥 | ✅ 线上已有，但新设备本地调试要 |
| 3 | **Dify FACT app key**（`app-` 开头） | Dify Cloud → 事实抽取工作流 → 访问 API → API 密钥 | ✅ 同上 |
| 4 | **Dify GEN app key**（`app-` 开头） | Dify Cloud → 生成专用工作流 → 访问 API → API 密钥 | ✅ 同上 |

> `DIFY_WF_MAIN` **不用准备** —— 前端实际没有任何调用，是死资产。

**建议把这 4 个值存在你自己的密码管理器里**，标题写 `ReadPal 凭证包`，换设备时直接复制出来粘给新会话。

### 令牌放哪（三个都行，按优先级）

```bash
python3 tools/push_via_api.py --token=xxx ...        # 1) 参数
export READPAL_GH_TOKEN=xxx                          # 2) 环境变量（或 GITHUB_TOKEN）
echo '{"gh_token":"ghp_xxx"}' > tools/.env.json      # 3) 本地文件（.gitignore 已排除，勿提交）
```

---

## 第 3 步：新设备环境准备

```bash
# 1) 拉源码镜像（public 仓库可直接读，不用凭证）
#    ⚠️ 别用 git clone —— 仓库含 90MB 音频，浅克隆常超时
python3 tools/fetch_sources.py "$WS/readpal"          # $WS = 当前 WorkBuddy 工作区目录
cd "$WS/readpal"

# 2) 写令牌（推代码用）
echo '{"gh_token":"ghp_你的token"}' > tools/.env.json

# 3) 装回技能（仓库 skills/ 是 ~/.workbuddy/skills/ 的镜像，见 skills/README.md）
mkdir -p ~/.workbuddy/skills
cp -R skills/readpal-frontend       ~/.workbuddy/skills/
cp -R skills/readpal-dify-workflow  ~/.workbuddy/skills/
cp tools/.env.json ~/.workbuddy/skills/readpal-frontend/scripts/.env.json

# 4) 本地调试用的密钥文件（.gitignore 已排除，不会误提交）
cp frontend/config.local.js.example frontend/config.local.js   # 然后用实际值编辑它

# 5) 本地起服务（复现 Railway 行为，端口 8793）
cd backend && python3 start_railway_local.py
#   停止：python3 start_railway_local.py --stop

# 6) 验证
curl -s http://127.0.0.1:8793/api/proxy-health      # 应看到 4 个 key 全 true
```

> **注意**：新电脑上的项目目录路径会不一样（WorkBuddy 按时间戳命名工作区），
> 这没关系 —— **仓库是唯一真源**，`AGENTS.md` 里不含任何本机绝对路径。

### 开工前先核对「工作副本 vs 远端」

工作区目录是**按会话隔离**的，你拿到的副本可能已经过期：

```bash
python3 tools/fetch_sources.py /tmp/remote_latest
# 逐个 sha256 比对 /tmp/remote_latest 与本地工作副本，列出 新增/修改/删除 三类
```

> ⚠️ **别用「文件大小差不多」判断是否同步** —— 2026-09-18 实测：
> 前端 +87166 字符、后端只 +1320，看起来「后端没动」，实际加了整个 EVP 词汇校验模块。

---

## 第 4 步：验收（新会话干完活后照这个查）

```bash
# 1) 前端 JS 语法（单文件大 HTML 必做）
python3 tools/check_js.py frontend/index.html

# 2) 线上首页特征核查
curl -s https://web-production-2a16e.up.railway.app/ -o /tmp/idx.html
grep -c 'typeof window.WB_API_BASE === "string"' /tmp/idx.html   # 应为 1
grep -c '127.0.0.1:8787' /tmp/idx.html                           # 应为 1（默认常量）

# 3) 桥接健康（4 个 key 全 true）
curl -s https://web-production-2a16e.up.railway.app/api/proxy-health

# 4) 浏览器实测（curl 证明不了运行时行为）
SITE=http://127.0.0.1:8899/index.html REQUIRE_BRIDGE=0 node tools/e2e_verify.mjs
#   验收线：12 个页面遍历 0 条 JS 异常 + 0 条 console.error（本地无桥接时跳过 bridgeOk）
```

**动了颜色** → 追加 `node tools/theme_audit.mjs`，必须 **12 页全 ✓**。
**动了 Dify 入参 / 分档视图** → 见 `~/.workbuddy/skills/readpal-frontend/SKILL.md` 的步骤 4b / 4c。

---

## 常见问题

**Q：换账号后 AI 什么都不记得怎么办？**
A：正常。`AGENTS.md` 就是为这个写的 —— 粘贴第 1 步的开场白，AI 读完 `AGENTS.md` 就等价恢复记忆。

**Q：技能（skill）会跟着仓库走吗？**
A：**不会自动跟。** 技能只在装了它的机器上；仓库 `skills/` 是镜像，需要手动拷回 `~/.workbuddy/skills/`（第 3 步第 3 条）。同一台机器上 `~/.workbuddy/skills/` 是**跨账号共享**的，所以换账号不用重装，换电脑才要。

**Q：推送代码一定要 token 吗？**
A：是。不管仓库 public 还是 private，**推代码都需要 token**（public 仓库也只有协作者能推）。差别只在"读"：public 可匿名读，private 要凭证。

**Q：为什么不能 `git push`？**
A：本地 git 与远程 `main` **历史已分叉**，会被拒。统一走 `tools/push_via_api.py`（GitHub API 直传，大文件带 4 次重试）。想用原生 git 得先 `tools/git_setup_remote.sh` 重建本地仓库。

**Q：Railway 需要单独配置吗？**
A：推 GitHub 就自动部署，不需要碰 Railway。**只有改环境变量时才需要登录 Railway。**

**Q：备用 workbuddy 链接会自动更新吗？**
A：**不会**。要手动 `python3 tools/build_deploy_bundle.py` 再发布。只用 Railway 链接的话可以不理。

**Q：模型渠道现在是什么？**
A：2026-09-15 起切回 **DeepSeek 官方**（`langgenius/deepseek/deepseek`），FACT 用 `deepseek-v4-flash`、GEN 用 `deepseek-v4-pro`。渠道改写集中在 `tools/dify_build_graphs.py`，**不要手改 Dify 图**。
