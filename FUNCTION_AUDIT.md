# ReadPal 部署功能可用性审计报告

> 实测日期：2026-09-08
> 实测方式：以 Railway 模式（密钥走服务端环境变量、前后端同域）本地启动 bridge，逐个路由打真实调用
> 被测对象：`output/backend/agent_reach_bridge.py` + `output/frontend/index.html`
> 结论口径：**主流程可用**，6 项功能存在不同程度降级或风险

---

## 一、结论摘要

| 类别 | 数量 | 说明 |
|---|---|---|
| 实测通过 | 7 项 | 内容生产主链路全部跑通，密钥不再暴露 |
| 受影响（可修复） | 4 项 | 头条正文、热点速度、描述词耗时、已有音频 |
| 受影响（架构约束） | 2 项 | 数据持久化、演示密码 |

**一句话结论**：老师打开链接→选素材→生成三档文章→生成封面→语音朗读，**这条主链路完整可用**；
受影响的是「热点正文质量」「已有音频回放」「数据持久化」三项，均可通过配置或小幅改造解决。

---

## 二、实测通过（7 项）

| 功能 | 接口 | 实测结果 | 备注 |
|---|---|---|---|
| 内容生成（主流程） | `POST /api/dify/workflows/run`（wf=gen） | **200 · 57.5s · succeeded** | 返回 A2/B1/B2 三档文章 + 练习题 + 校验结果 |
| 事实抽取 | `POST /api/dify/workflows/run`（wf=fact） | **200 · 8.9s · succeeded** | summary/facts_text/angle/level/sens_level 全字段 |
| 封面图生成 | `POST /api/sf/images/generations` | **200 · 2.2s** | 返回 SiliconFlow 图片 URL |
| 语音合成 TTS | `POST /api/tts/batch` | **200 · 0.9s** | 音频生成后可直接访问播放（59KB） |
| 标签体系 | `GET /api/tags/taxonomy` | **200 · 6 个分类** | 词表单一真源 |
| 三层标签提取 | `POST /api/tags/extract` | **200 · 1.6s** | content / free / cognitive 三层齐备 |
| 素材库读写 | `POST|GET /api/library` | **200 · 6 条** | 按 id 去重写入，读取有损坏保护 |

**密钥安全性（额外验证通过）**：

- 前端 `AIWF.apiBase` / `AIWF_FACT.apiBase` / `AIWF_GEN.apiBase` 引用次数均为 **0** — 所有 AI 调用已改走同源代理
- 代理路由 `_proxy_post()` 的 key 来自 `self._env_key()` → `os.environ.get(name)`，**前端只传 `wf: fact|gen` 决定用哪个 key，不传密钥本身**
- 服务首页 HTML 时替换掉 `config.local.js` 引用 → 浏览器永远拿不到密钥文件

---

## 三、受影响项（6 项）

### 3.1 头条正文抓取 — 降级（影响生成质量）

**现象**：热点列表能出 30 条，但**只有 4 条有正文（>300 字）**。

**根因**（代码级已确认）：

```
agent_reach_bridge.py:1037  chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

头条正文走 `render_dom_with_chrome()` → `_chrome_available()` 检测的是 **macOS 本机 Chrome 绝对路径**。
Railway 是 Linux 容器，该路径不存在 → 返回 False → 回退逻辑生效，**正文取不到，只剩标题和摘要**。

CDP 兜底路径同样不可用：依赖用户本机开着 `--remote-debugging-port=9222` 的 Chrome。

**实测留痕**：`/api/errors` 返回两条 warn：

- `无头浏览器不可用：头条话题页无法渲染取原文，已回退中文源或如实标记`
- `原文缓存写入失败（不影响本次结果）`

**影响评估**：正文不足会直接影响后续「事实抽取 → 内容生成」的素材质量。演示时建议优先选**有正文的条目**（界面上正文 >300 字的那 4 条），或改用自有素材/公版书入口（不依赖抓取）。

---

### 3.2 热点列表抓取 — 慢（68.6s）

**现象**：`GET /api/trends` 实测 **68.6 秒**返回 30 条。

**原因**：逐源串行抓取（今日头条、CGTN、NPR、Variety、Billboard、Global News、Live Science 等），单源 timeout 累加。

**风险**：Railway 出口 IP 在海外，抓取今日头条（国内站点）的结果**未经实测验证**——可能更慢，也可能被地域策略限制。这是本次审计**唯一无法在本地验证**的项目，必须部署后实测。

---

### 3.3 封面描述词 LLM — 慢（86.6s）

**现象**：`POST /api/sf/chat/completions` 实测 **86.6 秒**（仅回复一个词 "OK"）。

**对比**：同平台的文生图只要 2.2s。说明是 SiliconFlow 该模型（`Qwen/Qwen2.5-7B-Instruct`）当前负载高，非代理问题。

**影响**：点「生成封面」需要等约 90 秒。Railway 无函数超时所以不会失败，但体验偏慢。

---

### 3.4 已有音频 240MB — 未随部署上传

**现象**：`.railwayignore` 中排除了 `backend/audio/`（116 个文件，240MB）。

**后果**：`library.json` 里 6 篇文章的 audio 字段指向 `/audio/xxx.mp3`，部署后这些链接**全部 404**，内容库点播放失败。

**好消息**：代码有 `os.makedirs(AUDIO_DIR, exist_ok=True)`（1585 行），新生成的 TTS 不受影响，会自动建目录写入。

---

### 3.5 数据持久化 — 架构约束

**现象**：Railway 容器文件系统默认不持久化。重启或重新部署后：

- `library.json`（内容库 6 篇文章）清空
- 运行中新生成的 TTS 音频丢失
- 各类缓存文件丢失

**解决方向**：Railway 挂载 Volume 并指向 `backend/` 下的数据目录，或接受「演示环境数据临时」的现状。

---

### 3.6 演示登录密码 — 为空

**现象**：`config.local.js` 不再加载 → `DEMO_PASS` 为空字符串 → `doLogin()` 中 `p !== r.pass` 判定空输入通过 → **点登录直接进入，任何人可进**。

**影响**：演示方便（不用输密码），但无访问控制。演示 Demo 场景一般可接受，若需密码必须让 bridge 在 `_serve_index()` 时注入。

---

## 四、分档修复方案

### A 档 — 必须做（否则演示会出明显问题）

| 项 | 修复动作 | 工作量 |
|---|---|---|
| 已有音频 404 | 二选一：① 把 `backend/audio/` 从 `.railwayignore` 移除（240MB 进 Git，较慢但最省事）；② 演示前在内容库点「重新生成音频」现场生成 | 5 分钟 |
| 演示密码 | 在 `_serve_index()` 注入 `window.WB_CFG={DEMO_PASS:"..."}`，密码走环境变量 | 15 分钟 |

### B 档 — 建议做（提升演示质量）

| 项 | 修复动作 | 工作量 |
|---|---|---|
| 头条正文 | 演示时优先用自有素材/公版书入口，或改用有正文的热点条目；长期方案是容器内装 headless Chromium 并改路径探测逻辑 | 视方案 |
| 封面描述词 86s | 换更快的小模型（如 `Qwen2.5-7B-Instruct` → 更短 max_tokens），或给前端加超时与「后台生成」提示 | 20 分钟 |
| 数据持久化 | Railway 挂载 Volume | 20 分钟 |

### C 档 — 可选优化

| 项 | 修复动作 |
|---|---|
| 热点 68s | 加并发抓取或减少源数量 |
| 热点抓取可观测 | 部署后跑一次 `/api/trends` 实测海外出口是否可用，结果决定是否移除头条源 |

---

## 五、待部署后验证（本地无法测）

```bash
# 1. 服务与密钥自检
curl https://<你的 Railway 域名>/api/proxy-health
# 期望：4 个密钥全 true

# 2. 热点抓取（验证海外出口 IP 能否抓国内站点）
curl "https://<你的 Railway 域名>/api/trends?theme=all&limit=10"
# 关注：耗时、条目数、今日头条来源是否还在

# 3. 错误留痕（看有无新增降级告警）
curl https://<你的 Railway 域名>/api/errors
```

---

## 六、复现本次审计

```bash
cd /Users/bryan/WorkBuddy/2026-08-25-09-50-09/output/backend

# 以 Railway 模式启动（自动注入 4 个密钥，端口 8795）
python3 start_railway_local.py 8795

# 停止
python3 start_railway_local.py --stop
```

审计脚本：`/tmp/probe_all.py`（全路由）、`/tmp/probe_gen_img.py`（GEN + 文生图）
