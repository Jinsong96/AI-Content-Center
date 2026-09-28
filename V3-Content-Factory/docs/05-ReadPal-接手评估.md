# ReadPal 仓库接手评估（实测）

- 评估时间：2026-09-28
- 仓库：`github.com/Jinsong96/AI-Content-Center` @ `main` / `5b920f3`（最后推送 2026-09-24）
- 方式：全新克隆到本机 → 逐项实跑，不引用文档结论
- 结论：**可以接手，文档与工具链是我见过最完备的一档；但有 3 个必须先补的缺口、2 个需要你拍板的事**

---

## 一、已实测通过（可无缝的部分）

| # | 项 | 实测结果 |
|---|---|---|
| 1 | 文档完备度 | `AGENTS.md` 803 行（含 28 条踩坑记录）、`HANDOFF.md`、`README.md`、`docs/local-notes/` 47 篇逐次实测、`RAILWAY_DEPLOY.md` 395 行。换设备要做什么、坑在哪，全部落进了仓库 |
| 2 | 工具链开箱可用 | `tools/check_js.py` 实跑：V1 `index.html` 838,459 字符 → 全 ✅；V2 `card.html` 45,645 字符 → 全 ✅ |
| 3 | 本地服务能起 | `python3 start_railway_local.py 8793` 秒级起来。首页 200 / 915,977 字节；`/card`、`/card_check.js`、`/template.docx`、`/api/health` 全 200，content-type 正确 |
| 4 | 线上存活 | `web-production-2a16e.up.railway.app` HTTP 200；`/api/proxy-health` 返回 **7 个 key 全 true** |
| 5 | 真源一致性 | 本机克隆与 `origin/main` 完全一致（同为 `5b920f3`），工作区干净、无未提交改动 |
| 6 | 克隆可行性 | 我用 `git clone --depth 1` **秒级完成**。文档里「别 git clone，90MB 音频会超时」这条比实际严格 —— 网络正常时直接 clone 即可 |

### 结论修正（对文档）

`HANDOFF.md` / `AGENTS.md` 说「本地 git 与远程 main 历史已分叉，`git push` 会被拒，必须走 `tools/push_via_api.py`」。
**这是上一台电脑的本地仓库状态，不是仓库本身的问题。** 本机是全新克隆，历史与远端一致 ——
配上 token 后 **`git push` 可以直接用**，不必绕 GitHub API。API 直传仍可用于大文件重试场景。

---

## 二、必须先补的 3 个缺口

### 缺口 1（硬阻塞）：本机没有任何凭证

- 本机 `gh auth status` → **未登录任何 GitHub 账号**
- 无 GitHub token ⇒ 能读、能分析、能本地跑，**但推不了代码 = 交付不了**
- 还需要：Dify Cloud 控制台登录（改 Dify 图必须走「拉线上草稿 → 改 → 推 → 发布」，见 AGENTS.md 坑 18）
- SiliconFlow key **不需要你给**（仓库兜底文件里已有，见下节）

**需要你提供：** GitHub token（`ghp_` 开头，勾 `repo` 一项即可）

### 缺口 2：4 个技能一个都没装

仓库 `skills/` 是镜像，本机 `~/.workbuddy/skills/` 里 **readpal 相关的 0 个**。

| 技能 | 作用 | 本机状态 |
|---|---|---|
| `readpal-frontend` | 改 V1 前端（含步骤 4b / 4c 专项流程） | ❌ 未装 |
| `readpal-dify-workflow` | 改 Dify 图 | ❌ 未装 |
| `cefr-card-rewrite` | 改 V2 卡片链路 | ❌ 未装 |
| `readpal-import-pack` | 文档拆分 / 导入包 | ❌ 未装 |

不装回去，专项流程约束（如「改共享函数必须跑 sync_card_shared.mjs」）就没有载体。
装法见 `README.md` 第 4 节 / `HANDOFF.md` 第 3 步第 3 条。

### 缺口 3：代码里写死了上一台电脑的绝对路径

`/Users/bryan/...` 出现在 4 处，本机用户名是 `bryanlee`：

| 文件 | 行 | 影响 |
|---|---|---|
| `backend/agent_reach_bridge.py` | 1545 | `_detect_node_bin()` 的 glob 恒为空 → 退回 `"node"` |
| `backend/agent_reach_bridge.py` | 1555 | `_NODE_MODULES` 指向不存在的目录 |
| `backend/start_cdp.sh` | 24 | `PY` 默认值失效 |
| `tools/daily_sync.sh` | 14 | 同上（有 `command -v` 兜底，影响小） |

**实际后果**：`_detect_node_bin()` 返回 `"node"` 后，`render_dom_via_cdp()` 开头的
`os.path.exists(_NODE_BIN)` 判 **False** → **本地 CDP 渲染兜底静默失效**。
这与该函数自己的 docstring 记录的坑（曾导致今日头条 1290 条里 1140 条 `no_source`，88%）是同一个病根。
线上（Linux 容器）不走这条路径，所以**只影响本机调试**，但属于典型的「不报错、只是没效果」。
修法：改用 `Path.home()` / `~` 展开，2 行改完。

---

## 三、需要你拍板的 2 件事

### 拍板 1：密钥确实在公开仓库里 —— 建议轮换

**这不是文档里的推测，我实测确认了**：

| 证据 | 实测结果 |
|---|---|
| 仓库可见性 | `visibility: public`（匿名 API 访问 HTTP 200） |
| 线上首页 | `curl` 后 grep 到真实 `SF_API_KEY`（`sk-fsnx…`）+ `DEMO_PASS`，**任何人可取得** |
| `backend/keys.fallback.json` | **已提交进 public 仓库**，含 1 个 SiliconFlow key + 6 个 Dify app key + 演示密码 |
| bridge 行为 | `_load_cfg_cache()` 的三级兜底**会主动读这个文件**（802–810 行）⇒ 谁 clone 下来本地就自带可用密钥 |

`AGENTS.md` §5 写的是「Bryan 已知悉并**明确决定暂不处理**」。
**但那是 2026-09-10 的判断，当时的前提是"面向内部老师"；现在是 09-28，仓库是公开的、密钥确认可匿名取得 —— 前提已经变了。**
任何人不花一秒钟就能消耗你的 SiliconFlow 额度，Dify app key 同理。

**建议**：轮换这 7 个 key → 清空 `keys.fallback.json` 内容（保留空壳 + 注释）。
成本约 15 分钟。**我不会顺手动它 —— 这是你明确说过的边界，要动请先说。**
轮换前我会先把「改哪几处」列清楚（含线上 Railway 环境变量面板）。

### 拍板 2：文档落后于线上 —— 接手前必须先对齐

线上 `/api/proxy-health` 返回 **7 个 key**，前端还引用了另外几条链路：

| 文档说的 | 实测的 |
|---|---|
| `AGENTS.md` §6：4 个 key（FACT / GEN / MAIN / SF） | 线上 **7 个**：+ `LICPREP` / `LICGEN` / `CARD` |
| `README.md`：5 个（多了 `DIFY_WF_CARD`） | 前端还出现 `DIFY_WF_LITE` / `DIFY_WF_OBJ` / `DIFY_WF_CFG`，后端也读 `DIFY_WF_LITE` |
| `FUNCTION_AUDIT.md`（09-08）：「密钥不再暴露」 | 与 `AGENTS.md` §5 直接矛盾 —— **这份已过期**，09-08 早于 09-10 的发现 |

`docs/local-notes/46-lite骨架链路上线` 提到 lite 链路，但它**没有进入 AGENTS.md / README 的任何一张 key 表**。
这正是坑 18（改错链路）和坑 24（改了 GEN 忘了同步 FACT）会复发的土壤。
**建议在动第一行代码前，先花一次对话把「当前到底有几条链路、各自入口与 key」钉死，并更新 AGENTS.md §6。**

---

## 四、两个预期管理（不是缺陷，是现状）

1. **代码无缝 ≠ 数据无缝。** V1 的文章 / 素材 / 发布记录全在**浏览器 localStorage**（`wb_content_bank_v1` 等），
   换浏览器或清缓存就丢、多人之间不共享；V2 **完全不存历史**，刷新即丢。这些 git 同步不了，只有后端接数据库才能解决。
2. **本次评估是只读的。** 我没有调用任何 Dify / SiliconFlow 接口。
   本地起服务时 bridge 读到了仓库兜底文件里的密钥（所以 `/api/proxy-health` 本地也显示 true），
   但我只做了 `GET` 健康检查与静态路由探测，**没有消耗你的 API 额度**。

---

## 五、建议的下一步（按顺序）

1. 你给 GitHub token → 我重跑一次「本地改动 → 校验 → 推送 → 线上特征核验」的完整闭环，证明链路真的通
2. 我装回 4 个技能（`~/.workbuddy/skills/`）
3. 我修掉 4 处写死的本机路径（2 行 + 2 个 shell 默认值）
4. 你决定要不要轮换密钥 → 要就我先出改动清单
5. 花一次对话把「链路清单」对齐并更新 `AGENTS.md` §6
