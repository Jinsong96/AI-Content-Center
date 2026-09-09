# HANDOFF.md — 换设备 / 换 WorkBuddy 账号 交接包

> 给人读。目标是：**换任何电脑、任何 WorkBuddy 账号，复制粘贴一段文字就能开工。**
> 最后更新：2026-09-09

---

## 第 1 步：复制这段给新会话（开场面）

新电脑 / 新账号打开 WorkBuddy 后，把下面这段**整段粘贴**进去，然后把你手上的实际值填进 `[...]`，再写你要做的事即可。

```text
你要接手 ReadPal 内容生产平台（AI 英语分级阅读内容生产平台）。

【代码在哪】
仓库：https://github.com/Jinsong96/AI-Content-Center （main 分支）
- 前端真源：frontend/index.html（单文件，约 68 万字符）
- 后端真源：backend/agent_reach_bridge.py（零依赖 Python）
- 项目约定：仓库根目录 AGENTS.md，开工前请先完整读一遍，里面有 6 个已踩过的坑
- 部署文档：RAILWAY_DEPLOY.md（含 10 条故障排查）

【线上地址】
https://web-production-2a16e.up.railway.app
（推 GitHub 后 Railway 自动部署，约 90 秒生效）

【凭证】（下面是我给你的实际值）
GitHub token: [填 ghp_ 开头的 token]
SiliconFlow key: [填 sk- 开头的 key]
Dify 事实抽取 app key: [填 app- 开头]
Dify 内容生成 app key: [填 app- 开头]

【重要提醒】
1. 本地 git 与远程 main 历史已分叉，git push 会被拒 —— 推送请用 GitHub API 直传
   （先 GET 拿 sha 再 PUT base64，大文件加重试）。AGENTS.md 第 8 节有说明。
2. 改前端单文件大 HTML 后，必须抽出 <script> 块逐个 node --check 再推。
3. 改同一文件多处时必须串行 Edit，并发 Edit 会静默互相覆盖。

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

---

## 第 3 步：新设备环境准备

```bash
# 1) 拉代码（public 仓库可直接 clone，不用凭证）
git clone https://github.com/Jinsong96/AI-Content-Center.git
cd AI-Content-Center

# 2) 本地调试用的密钥文件（.gitignore 已排除，不会误提交）
cp frontend/config.local.js.example frontend/config.local.js
# 然后用你的实际值编辑它

# 3) 本地起服务（复现 Railway 行为，端口 8793）
cd backend && python3 start_railway_local.py
#   停止：python3 start_railway_local.py --stop

# 4) 验证
curl -s http://127.0.0.1:8793/api/proxy-health
#   应看到 4 个 key 全 true
```

> **注意**：新电脑上的项目目录路径会不一样（WorkBuddy 按时间戳命名工作区），
> 这没关系 —— **仓库是唯一真源**，`AGENTS.md` 里不含任何本机绝对路径。

---

## 第 4 步：验收（新会话干完活后照这个查）

```bash
# 1) 前端 JS 语法（单文件大 HTML 必做）
#    抽出所有 <script> 块 → 逐个 node --check

# 2) 线上首页特征核查
curl -s https://web-production-2a16e.up.railway.app/ -o /tmp/idx.html
grep -c 'typeof window.WB_API_BASE === "string"' /tmp/idx.html   # 应为 1
grep -c '127.0.0.1:8787' /tmp/idx.html                           # 应为 1（默认常量）

# 3) 桥接健康（4 个 key 全 true）
curl -s https://web-production-2a16e.up.railway.app/api/proxy-health

# 4) 浏览器实测（curl 证明不了运行时行为）
#    state.bridgeOk === true、16 个页面遍历 0 JS 报错、Dify FACT/GEN 真跑一次
```

---

## 常见问题

**Q：换账号后 AI 什么都不记得怎么办？**
A：正常。`AGENTS.md` 就是为这个写的 —— 粘贴第 1 步的开场白，AI 读完 `AGENTS.md` 就等价恢复记忆。

**Q：推送代码一定要 token 吗？**
A：是。不管仓库 public 还是 private，**推代码都需要 token**（public 仓库也只有协作者能推）。差别只在"读"：public 可匿名 clone，private 要凭证。

**Q：Railway 需要单独配置吗？**
A：推 GitHub 就自动部署，不需要碰 Railway。**只有改环境变量时才需要登录 Railway。**

**Q：备用 workbuddy 链接会自动更新吗？**
A：**不会**。要手动 `python3 tools/build_deploy_bundle.py` 再发布。只用 Railway 链接的话可以不理。
