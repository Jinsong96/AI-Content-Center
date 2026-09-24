---
name: readpal-frontend
description: 迭代 ReadPal（AI 英语分级阅读内容生产平台）单文件前端并安全上线。当需要在 ReadPal 项目里改 frontend/index.html（改文案 / 样式 / 交互）、改 backend/agent_reach_bridge.py，或者需要验证线上效果、部署上线时使用。覆盖：源码获取、原子化多处的安全替换、本地真实渲染截图、CDP 端到端回归（登录 + 遍历 12 页）、GitHub API 直传部署、线上生效核验。
agent_created: true
---

# ReadPal 前端迭代与上线

## 项目速览

| 项 | 值 |
|---|---|
| 品牌名 | **ReadPal**（无空格，写成 `Read Pal` 是错的） |
| 仓库 | `Jinsong96/AI-Content-Center`（**PUBLIC**，main 分支） |
| 线上 | `https://web-production-2a16e.up.railway.app` |
| 前端真源 | `frontend/index.html`（单文件，约 **78 万字符 / 763KB**，2026-09-17 起） |
| 后端真源 | `backend/agent_reach_bridge.py`（零依赖 Python）；另有 `backend/evp_vocab_check.py` + `evp_wordlist.json` |
| 部署 | 推 GitHub main → Railway 自动部署（约 90 秒） |
| 线上密钥 | `os.environ` > `frontend/config.local.js`（gitignore） > `backend/keys.fallback.json`。**云端只有第一条可用**（后两个线上不存在）⇒ 新 key 必须进 Railway Variables；新 key 也要同时进 `_serve_index()` 的 `_envs` 白名单，否则前端显示「未配置」而**不报错、不写日志** |
| 项目约定 | 仓库根 `AGENTS.md`（**动工前必读**，含 6 个已踩坑） |
| 🔵🔴 **只管 V1**（2026-09-24 定） | 本项目两套东西：🔵 **V1 智能体** = 本技能管的 `frontend/index.html`，入口 `/`；🟢 **V2 智能体** = 分级卡片 `frontend/card.html` + `frontend/card_check.js`，入口 `/card`，**归 `cefr-card-rewrite` 技能管**。两套独立前端文件、独立 Dify 图，后端 `/` 与 `/card` 两条独立路由。**改 V2 别走本技能**，且**只改文档命名、不许动文件路径**（路径被后端写死，改名直接打挂线上） |

## 关键约束（务必遵守）

1. **不能用 `git push`** —— 本地 git 与远程 main 历史已分叉。必须走 GitHub API 直传。
2. **同一文件多处修改**：绝不要并发 Edit（会静默互相覆盖）。用 `scripts/atomic_replace.py` 做一次性原子替换。
3. **改完必做 JS 语法校验**：抽出 `<script>` 块逐个 `node --check`。
4. **curl 只能证明代码在，证明不了运行时行为** —— 必须真实渲染验证。
5. `127.0.0.1:8787` 在源码中应**只剩 1 处**（`DEFAULT_API_BASE` 默认常量）。
6. 改 step 相关逻辑时 `STAGES`/`stepLabel`/`fns`/`STEP_OWNER`/`ROLE_OPS` 必须同步。
7. 权限判断只看 `ROLE_OPS`；教研老师（`produce`）故意跳过 step 10（逐段审核），**勿改**。
8. 名字会骗人：`s12` = 逐段审核（不是库存管理），`s9` = 段落校对，`s4` = 事实抽取，**以 `fns` 下标为准**。
9. **平台定位 = 内容生产平台**。2026-09-10 已删除「发布管理」四模块（库存 / 发布 / 运营看板 / 用户反馈）
   与「团队成员」占位 —— **新增功能不要往发布、分发、渠道方向加**（内容管理由另一平台承担）。
10. **当前骨架**：侧边栏 4 项且全部同级直达 —— `素材创建`(0) · `素材库`(4) · `文章生产`(5) · `文章库`(11)；
    `fns` 与 `STAGES` 均为 **12 项（idx 0–11）**；登录角色 **3 个**（`source` / `produce` / `review`）。
    > 侧边栏不再有可展开分组，`expandedSections` 为空集；`0`/`5` 的显示名在 `RAIL_OVERRIDE`。
    > ✅ 增删**尾部**步骤只需同步 `fns` + 对应函数，前面各步编号不受影响。
11. **返回按钮是全局注入的，不要在页面函数里另写** —— `render()` 统一注入 `backBarHTML()`；
    加新页面时只需在 `backTarget()` 里确认它的层级归属，否则要么该有不显示、要么落点算错。
    > ⚠️ `go()` 对 owned/public 路线有跳步改写（`1→2`、`5→6`）。算返回落点必须用
    > `goResolve()` 复刻同一规则，**直接写 `go(cur-1)` 会被改写成原地不动**（表现为"点了没反应"）。
12. **只读态验证要先换角色** —— `review` 的 `ROLE_OPS` 是 `0–11` 全量，**永远不会进只读态**。
    要触发只读得临时把 `state.user.role` 切成 `source`（或 `produce` + `cur=10`）。

## 设计原则（Bryan 定的全局大原则）

> **简洁、干净、清爽，色调统一。**

品牌色：主色 `#E65425`、页面底色 `#FFFDF9`、白卡片、无衬线字体。
品牌渐变 `--grad-pri:linear-gradient(135deg,#E65425,#F79009)` 是**唯一真源**，
顶部 ReadPal 徽标、登录按钮等所有品牌色元素都用它，不要再写渐变色字面量。

侧边栏与登录页**严禁 emoji**。

### 配色约定（2026-09-10 起全站已落地，新增颜色必须遵守）

**全站色相只有三系：黑 / 灰 / 品牌橙红。蓝、绿、紫、青一律不允许。**

- **分类色统一 `#E65425`**：6 选题大类 / CEFR 的 A2·B1·B2 / 3 角色 / 素材类型 /
  侧边栏分区 / 路径 —— 对应 6 个 JS 色板 `ROLES` `RAIL` `ROUTES` `SRC_TYPES`
  `LVL_META` `TOPIC_CATS`，以及 CSS `.pub-item-lvl.*`。色块不再承担区分功能。
- **状态色走品牌橙的深浅梯度**：成功/完成 `#F79009`、警告/部分 `#D04418`、
  失败/风险 `#A32D2D`（暖族深红，不算新色相）。
- 浅底 tint：`#FFF9F5` / `#FFF0EB` / `#FFEDE4`；浅边框 `#FFDFCF`。
- 冷调中性灰（`#101828` `#475467` `#98A2B3` `#EAECF0` `#D0D5DD` `#344054`）
  **属于「灰」，保留** —— 色相偏蓝但饱和低，视觉上就是灰。
- **验收**：`node tools/theme_audit.mjs` 必须 **12 页全 ✓** 才算过。
- ⚠️ 改配色别用逐处 Edit：色值散落 100+ 处且同一色值跨语境含义不同
  （如 `#12B76A` 既是 B1 等级色又是"答题正确"色）。做法是**先统一 JS 色板、
  再单遍映射散落色值**，脚本见本次提交历史；`theme_audit.mjs` 的审计阈值
  为 `sat>=26 && 12<=l<=90`，低于此视为灰阶。

## 工具链在哪（重要）

**真源在仓库 `tools/` 下**（2026-09-10 起随仓库分发，换设备自动带上）：

| 工具 | 作用 |
|---|---|
| `fetch_sources.py` | 只拉源码镜像（跳过 90MB 音频，替代 `git clone`） |
| `atomic_replace.py` | 原子替换 + 命中断言（治并发 Edit 静默覆盖） |
| `check_js.py` | 抽 `<script>` 逐个 `node --check` |
| `push_via_api.py` | GitHub API 直传（替代被拒的 `git push`） |
| `e2e_verify.mjs` | 端到端回归：登录 + 遍历 12 页 + 收集 JS 异常 |
| `theme_audit.mjs` | 配色合规审计：遍历 12 页揪出非「黑/灰/橙红」色相 |
| `cdp_shot.mjs` | CDP 精确视口截图：多尺寸一次出图，绕开 Chrome 最小窗口宽度限制 |
| `ui_audit.mjs` | **可用性 / 排版客观审计**（2026-09-15 新增）：逐页量横向溢出、文字截断、点击目标尺寸、无标签控件、过小字号，并收集 JS 异常 |
| `probe_lic_rerun_gate.mjs` | **授权链路「重跑期不许露出中间稿」回归**（2026-09-23 新增）：mock 生成/词汇校验造「超纲→超纲→通过」三轮，按帧采样 DOM，断言定稿前 0 帧文章预览，含负向对照。见硬约定 9 |
| `probe_fact_edit.mjs` | **事实卡可改 / 可删 / 可新增回归**（2026-09-23 新增，33 项）：**界面断言与下游入参断言分成两组**（改卡必须回写 `factsCache.facts_text` + `facts_raw.facts`），含 gist 不串位/不丢失、空卡不入参、删空拦截、编辑层不泄漏。见下方「事实卡人工编辑层」 |

> ⚠️ `cdp_shot.mjs` 每个尺寸只抓**一个**状态（navigate 一次 + 一次 `--eval` + 一张图）。
> 需要在一个会话里连拍 N 个状态（改了阅读器/弹窗等有状态 UI 时的自查），
> 用技能 `web-demo-teardown` 的 `scripts/drive_multi_state.mjs`：
> 传一份 `steps.json`（`[[名称, 页面内 JS, 截图前等待ms], ...]`），一次出 N 张图，
> 并顺带收集 `Runtime.exceptionThrown` / `console.error`。

本技能 `scripts/` 下是**同一份的离线副本**，用于「本地还没有仓库副本」的自举场景
（`fetch_sources.py` 本身就是用来拉仓库的，必须先于仓库存在）。
**两者若有出入，以仓库 `tools/` 为准**，并回填本技能。

仅本技能独有（仓库没有）：`verify_live.sh`（线上核验）、
`probe_toutiao_fulltext.py`（头条原文覆盖率 · **线上等价环境**：先把三条渲染路径全部 stub 掉，
强制走纯 HTTP 的 SSR 路径，与没装 Chrome 的 Railway 容器同构）。
> `screenshot.sh` 只适合**宽屏单图**快照；窄屏 / 移动端验证必须用 `cdp_shot.mjs` ——
> `chrome --window-size` 受 Chrome 最小窗口宽度限制，420px 会实际按 ~500px 布局再裁切。

**令牌来源（按优先级）**：`--token=xxx` → 环境变量 `READPAL_GH_TOKEN` → `GITHUB_TOKEN`
→ 脚本同级的 `.env.json`（格式 `{"gh_token": "..."}`，**已 gitignore，勿提交**）。
仓库里就是 `tools/.env.json`；本技能里是 `scripts/.env.json`（软链到技能根的 `.env.json`）。

---

## 标准工作流

### 步骤 0 · 准备本地工作副本

**不要 `git clone`** —— 仓库含约 90MB 音频（31 个 mp3），实测浅克隆跑 5 分钟都完不成；
走 API 只拉源码 **53 秒**拿到 47 个文件。

```bash
# 已有仓库副本 → 用仓库工具
python3 tools/fetch_sources.py "$WS/readpal"       # $WS = 当前 WorkBuddy 工作区目录

# 冷启动（本地还没有仓库副本）→ 用本技能的自举副本
python3 scripts/fetch_sources.py "$WS/readpal"      # 同上
```

只需在首次或怀疑本地副本过期时执行。

### 步骤 1 · 定位改动点

先用 Python 精确打印待改区域的字符偏移与上下文，**不要凭猜**：

```bash
python3 - <<'PY'
import re
s = open('readpal/frontend/index.html', encoding='utf-8').read()
for kw in ['要改的关键词']:
    print(kw, [m.start() for m in re.finditer(re.escape(kw), s)])
PY
```

### 步骤 2 · 原子替换（核心）

先写替换规格 JSON，再执行。规格里每项都要写 `expect`（期望命中次数），
**任何一项命中数不符就整体中止、不写盘**，避免"改了但没生效"。

```json
[
  {"type": "literal", "old": "…", "new": "…", "expect": 1, "label": "说明"},
  {"type": "regex",   "old": "\\n\\s*<p>.*?</p>", "new": "", "expect": 1, "label": "正则删段"}
]
```

```bash
python3 tools/atomic_replace.py frontend/index.html /tmp/spec.json
```

> 脚本必须用 `<<'PY'`（带引号）的 heredoc 或独立 .py 文件执行，
> 否则 bash 会展开 `$` 把模板字符串搞坏。

### 步骤 3 · JS 语法校验（必做）

```bash
python3 tools/check_js.py frontend/index.html
```

抽出所有 `<script>` 块逐个 `node --check`。能挡住大部分白屏事故。

### 步骤 4 · 本地真实渲染验证

起静态服务（**必须 `run_in_background=true`**，否则进程随 shell 退出被杀）：

```bash
cd readpal/frontend && python3 -m http.server 8899 --bind 127.0.0.1
```

截图 —— **首选 CDP 精确视口**（多尺寸一次出图，并回读 `vw` / `scrollWidth` / 容器矩形，
可直接判断是否水平溢出、是否垂直居中）：

```bash
node tools/cdp_shot.mjs --url=http://127.0.0.1:8899/index.html \
     --sizes=1440x900,1920x1080,1024x768,420x820 --out=/tmp/shot
# 需要登录后的页面：--eval="(async()=>{openLogin('review');doLogin('review');await new Promise(r=>setTimeout(r,2500));go(4);return 'ok';})()"
```

宽屏单图快照仍可用 `screenshot.sh`（务必用**唯一文件名**，否则会被去重）：

```bash
bash scripts/screenshot.sh http://127.0.0.1:8899/index.html /tmp/check_$(date +%s).png 1400 900
```

然后用 Read 工具看图，确认视觉效果。

验证"展开态""弹窗态"等非默认状态时，可临时改一份副本强制加类名 ——
⚠️ **注意合入已有 class**：`class="lrole"` 后面再写一个 `class="open"` 是无效的
（HTML 重复属性取第一个）。要写成 `class="lrole open"`。

### 步骤 4b · 运行时契约验证（改了 Dify 入参时**必做**）

**静态读代码只能证明「源码长这样」，证明不了「运行时真的这么发」。**
改了 `wfInputs` 这类入参，用 CDP stub 掉 `window.fetch` 把**真实请求体**抓出来看：

```js
// 在页面里执行（CDP Runtime.evaluate, awaitPromise）
window.fetch = function (u, opt) {
  const b = opt && opt.body ? JSON.parse(opt.body) : null;
  __cap.push({ url: String(u), inputs: b && b.inputs });
  return Promise.reject(new Error('STUB'));   // 立即失败，不发真网络
};
```

两个调用点都包在 `try{}catch{}` 里（`startLiveRun` L2278、`runGeneration` L2342），
reject 会被内部吞掉，**不会污染页面状态**，但请求体已经拿到手。

⚠️ 两个必须踩对的前提：
1. 本地没有 `config.local.js` → `AIWF_*.appKey` 为空 → 函数内部提前 throw，
   表现为「`captured: []` 什么都没发生」。**先补 key**：`AIWF_FACT.appKey='app-PROBE'`。
2. `runGeneration` 有守卫 `if(!fc || !fc.summary || !fc.facts_text)`，
   探针要自己造 `state.factsCache`（含 `gist`，见下）。

现成脚本（本技能 `scripts/`，2026-09-14 新增，仓库 `tools/` 暂无）：

| 脚本 | 用途 |
|---|---|
| `scripts/probe_contract.mjs` | stub fetch 抓真实请求体。`--url=` 本地或线上都行 |
| `scripts/probe_live_e2e.mjs` | 线上真实链路：登录 → FACT → GEN，轮询到结束并打印各档产出/校验/复核。`--fact-only` 只跑抽取（~20s，日常够用） |
| `scripts/probe_review_levels.mjs` | **分档视图回归**：造一条只含 A1/A2 的文章入库 → 连续切档，回读 `.bigbar` / `.bigtab` / `.pcard` / `.svempty` 计数与 tab 标识，并断言「切换条在 `.reviewparas` 之上」。本地 + 线上同一份 |

### 步骤 4c · 分档视图回归（改了 `bigBar` / `alignedViewHTML` / `plvlbar` / `setBig` 时**必做**）

**大档切换条是一个「一页只渲染一条」的一次性闸门**：

```js
let _bigBarUsed = false;
function bigBarHTML(){ _bigBarUsed = true; ... }
function bigBarOnce(){ return _bigBarUsed ? "" : bigBarHTML(); }
function render(){ _bigBarUsed = false; ... }   // 每次渲染复位
```

由此引出两条必须记住的规则：

1. **想把切换条挪到更显眼的位置，不要复制它，要在目标位置先调一次 `bigBarOnce()`** ——
   原位置那次会自动返回空串，**永远不会出两条**。
   （`s12()` 就是这么做的：`const bigBar = bigBarOnce();` 放在 `reviewContextHTML()` 之后。）
2. **不要写「整块 `return ""`」的守卫**：

   ```js
   // ✗ 错：切换条就在这一块里，会跟着一起消失
   const has = lvls.some(k => GEN[k] && GEN[k].paras && GEN[k].paras.length);
   if (!has) return "";
   ```

   结果：切到**区间外的大档**（素材只到 A2.3 时点 B1）整页 `.bigtab` 归零，
   **用户点不回有内容的大档，只能退出页面** —— 而区间模型下这是必然遇到的常态。
   正确写法是 `if(!has) return h + emptyGroupHTML();`，**切换条 + 空态卡片始终保留**。

> 📌 这类 bug 静态读代码看不出来（"没内容就不渲染"看起来完全合理），
> 必须用 `probe_review_levels.mjs` 数真实 DOM。
>
> **判据（2026-09-18 修正）**：4 档改造后 `bigBarHTML()` 会**按区间下界隐藏低档**
> （`minLevelKey()` 得到 `level_lo`，低于它的档直接 `return ''`），所以数量不再是恒定 4：
>
> - **`.bigbar`（容器）必须恒存在** ← 这才是真正的不变式，切换条消失就是那个 bug 复现了
> - `.bigtab` 数 = `4 − minIdx`（`level_lo=A1` → 4 个；`level_lo=B1` → 2 个），**恒 ≥ 1**
> - 判「有没有坏」看 `.bigbar` 在不在 + `.bigtab` 是否等于上式，**不要写死 4**
>   —— ⚠️ **lite（轻量提示词）另有收敛**：只产 3 档，`bigBarHTML()` 里多一条
>   `if(isLite() && shownKeys().indexOf(g.big) < 0) return ''`。见「对照组必须剔除的产线控件」

### 🔴 改档位数量（12→4 档）必须同步查 CSS grid 列数（2026-09-15 踩过两次）

改档位数量时，除了 JS 渲染（`subKeys()`→`allKeys()`），**CSS 里写死列数的对齐网格必须同步改**，
否则第 N 档卡片会溢出到塌陷的隐式列（宽度≈0），配合 `word-break:break-word` 文字竖排成「每行一个字母」的乱码。

涉及的「段号 + N 列」结构（`44px 1fr×N`）：

| class | 用途 | 4 档正确值 |
|---|---|---|
| `.alignrow` | 段落对齐行（s9 校对 / s10 人工校对 / s12 审核） | `44px 1fr 1fr 1fr 1fr` |
| `.qalign-hbar` / `.qalignrow` | 题目对齐（表头 + 行，quizAlignedHTML） | `44px 1fr 1fr 1fr 1fr` |

**排查口诀**：改档位数量后 `grep -nE "grid-template-columns:[^;]+"` 逐个核；
只数 DOM 卡片数量（28 张）不够，**必须量每张卡片的 `getBoundingClientRect().width`**（4 张应等宽，不是塌成 ~0）。
其余 `repeat(3,1fr)` 大多是档位无关的通用网格（热点卡/标签/登录角色 3 角色/单档规格 3 维度），逐个确认再决定改不改。

### 步骤 5 · 部署（验证通过后直接上线，无需再问）

```bash
python3 tools/push_via_api.py frontend/index.html frontend/index.html "commit message"
```

内部逻辑：`GET` 拿 sha → `PUT` base64 + sha + `branch:main`，失败自动重试 4 次 × 3s
（大文件偶发 `IncompleteRead`，重试即可成功）。

### 步骤 6 · 线上核验

等约 95 秒，然后：

```bash
bash scripts/verify_live.sh
```

比对删除项是否归零、新增特征是否存在。**注意线上 HTML 是 bridge 注入后的版本**，
与源码不同（会多出 `window.WB_API_BASE=""` 和 `window.WB_CONFIG={...}` 注入行）。

🔴 **「某段文案删没删掉」的核验串必须是「只在被删内容里出现」的唯一串。**
反例（2026-09-23 踩过）：「裸产出」在页面里共 4 处 —— 1 条 JS 注释、首页卡片 `desc`（L3965）、
流程说明（L4296）、被删的那句。拿它当判据 ⇒ 线上**永远 true**，误判「没上线」，白等两轮。
正确姿势：① 取被删句的**尾巴连续片段**（如「这一条链路要看的正是」）；② 交叉验证**页面总长度差**
（本次线上 `829006 → 828582`，−424 与 `atomic_replace` 报的删除字符数**完全吻合**）。

⚠️ **Railway 部署偶发慢到 2–3 分钟**（惯例 90s）。第一次核验命中旧内容**先别判「部署失败」**：
隔 ~50s 复查，看 `document.documentElement.outerHTML.length` **有没有变化**再下结论。

沙箱里也能直接拉线上页（curl 是 000，走 Chrome）：
```bash
node tools/cdp_shot.mjs --url="https://web-production-2a16e.up.railway.app/?v=$(date +%s)" \
  --eval="(async()=>{document.getElementById('loginOv').style.display='none';state.user={role:'produce',name:'x',sources:[]};buildRail();pickRoute('lite');await new Promise(r=>setTimeout(r,400));return document.getElementById('stage').innerText.slice(0,200);})()"
```
（`?v=<ts>` 防缓存；登录遮罩 id 是 `loginOv`，不藏起来截图只会拍到登录页。）

### 步骤 6b · 后端接口直连验证（改了 `backend/*.py` 时必做 · 两个沙箱坑）

```bash
# 起服务：必须用「后台任务」方式，`(cmd &)` 起的进程活不过一条命令就没了
cd readpal/backend && PORT=8799 exec python3 agent_reach_bridge.py   # run_in_background=true
# 再单独发请求验证，不要和起服务挤在同一条命令里
```

- 🔴 **`curl` 通、`python urllib` 报 502 Bad Gateway ⇒ 是沙箱的 `HTTP_PROXY` 在作祟**
  （环境里 `HTTP_PROXY=http://127.0.0.1:53005`，该代理不转发 127.0.0.1 的请求）。
  不是服务坏了。绕开方式：
  ```python
  op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
  op.open("http://127.0.0.1:8799/api/trends?theme=all&limit=120", timeout=300)
  ```
- 🔴 **`/api/trends` 是同步长请求**（首次 60–120s，命中缓存 ~55s），urllib/curl 的 timeout 要给到 300s，
  否则会被误判成「后端无响应」。
- ⚠️ 沙箱内**无法直连 Railway 域名**（curl / fetch 一律 000；`curl --noproxy '*'` 也 000）。
  线上核验走 `node tools/read_live_config.mjs` —— 借本机可见 Chrome（CDP 9243）读真实页面上的 `window.WB_CONFIG`，
  一眼看出哪个 key 是空的。这是核「Railway 环境变量有没有进容器」的最快路径。

### 步骤 7 · 端到端回归（改了共享 CSS/JS 时必做）

```bash
node tools/e2e_verify.mjs      # 脚本自己拉起 Chrome，无需手动起进程
```

脚本会：登录页结构核查 → 以 `review` 角色登录 → 校验 `state.bridgeOk`
→ 遍历 12 个页面收集 JS 异常 → 截图。

**验收线：12 页遍历 0 条 JS 异常、0 条 console.error。**

本地静态服务没有桥接层，`bridgeOk` 恒为 false 会把正常结果误判为「未通过」——
加 `REQUIRE_BRIDGE=0` 跳过该断言，其余指标同样有效。

### 步骤 8 · 配色审计（动了任何颜色时必做）

```bash
node tools/theme_audit.mjs                                                     # 查本地 8899
SITE=https://web-production-2a16e.up.railway.app/ node tools/theme_audit.mjs    # 查线上
```

遍历 12 页，把每个元素的 computed 颜色转 HSL，凡色相不在「橙红 0–48°」与
「红 345–360°」范围内、且 `sat>=26 && 12<=l<=90` 的色值全部列出。

**验收线：输出 `✅ 全部 12 页均无蓝/绿/紫色相`。**

---

### 步骤 9 · 可用性 / 排版审查（改了布局、文案、交互后建议跑）

```bash
node tools/ui_audit.mjs --url=http://127.0.0.1:8899/index.html --role=produce \
     --sizes=1440x900,1024x768,420x820 --json=/tmp/ui_audit.json
```

逐页输出：横向溢出元素、被截断且无 `title` 的文字、<32px 的点击目标、
无可读标签的可点元素、缺 placeholder/label 的输入框、<12px 的字号、运行时异常。

**两条必须记住的度量规则**：

1. 🔴 **量横向溢出必须用 `mobile:false`**（脚本已如此）。
   用 `mobile:true` 时 Chrome 会把**布局视口撑到内容最小宽度** —— 实测 420px 视口下
   `innerWidth` 直接变成 **557**，于是 `scrollWidth == innerWidth`，137px 的真实溢出被藏起来，
   看起来"完全没问题"。只有 `mobile:false` 才暴露真相。
2. 🔴 **空态看不出排版问题，必须注入 mock 数据再渲染**。
   素材/文章库为空时，三栏对照、段落卡片、题目对齐这些核心视图根本不渲染。
   注入 `state.live.run.data.outputs`（含 `articles_json` / `paras_json` / `quiz_json` /
   `validation_json` / `fact_map` / `facts_json`）后调 `applyLive()`，再 `go(i)` 截图。

**对比度审计写法**（判断"字太浅"的量化依据）：遍历叶子文本节点，取 `getComputedStyle().color`
与最近的不透明祖先 `backgroundColor` 算 WCAG 比值。⚠️ **遇到 `backgroundImage !== 'none'`
必须直接返回 null 跳过** —— 否则渐变背景（品牌 logo、主按钮）会被误判成"白字 on 白底 1:1"。

#### 2026-09-15 审查基线（29 条，**已全部修复并验证**）

| 档 | 条目（← 原始问题） | 修复手法（← 可复用） |
|---|---|---|
| A（会让老师卡住/白干） | 窄屏溢出 137px（`#body` 220px + 1fr，无 ≤700px 骨架）· 「修改自动保存」实为内存保存（无 localStorage/beforeunload）· 进度条按 `GEN_EST=90` 算而 GEN 实测 110–180s（卡 100%）且无取消 · 0 条时统计卡+空态+分页三者并存 · 未选素材时「运行抽取」可点（算了 `ready` 没用）· 「引用事实卡 F1」是裸 span 无 tooltip · 内部代号 E1–E9 / F1 / KB1–KB7 / V1-V13 直接暴露 | 骨架 `minmax(0,1fr)` + `#body > *{min-width:0}`，≤860px 侧栏改 `translateX(-100%)` 抽屉；顶栏另加收缩规则（**别以为改了骨架就完事，尤其 `#topbar`**）· `wb_para_draft_v1` 草稿键（`material.length + ":" + material.slice(0,80)` 指纹防串素材 + 700ms 防抖）+ `beforeunload` · `runPct()` 取「时间进度 / 节点进度」双因子取大、封顶 96%，`GEN_EST=150`、`FACT_NODE_EST=9`、`GEN_NODE_EST=21`，`AbortController` 真取消 · 空态直接 `return` 引导卡（不给统计卡/分页/暂无匹配）· 未就绪时按钮 `disabled` + 说明 + 直达按钮 · 事实卡改可点 `.fcref` chip + 抽屉 · 代号改业务语言（`FC-1` → `事实卡 1`） |
| B | 说明文字 `#98A2B3` 对比度 2.53（10–13px，每页 30–40 处）· 品牌橙作正文色 3.34–3.71、`#F79009` 序号 2.25 · 三套导航并存且 `wfStrip()` 12 步不可点（`artWorkflowBar()` 可点）· 一页两排档位条（`.plvlbar` 展示 + `bigBarHTML()` 切换）· 四栏各 ≈180px 一行 3–5 词 · `spellcheck="false"` · 登录页角色卡信息量不均/无主次 · `logout()` 无确认 · 无 Esc 关闭、`aria-*` 0 处 · EN 模式 TOPIC_CATS/STYLES 仍中文 | `--muted` → `#667085`（≈4.6:1）；**新增文字专用品牌色 `--pri-tx:#C2421C` / `--ok-tx`，色块与描边仍用 `--pri`** —— 这是绕开"品牌橙当正文对比度不够"的正解 · 展示版 `.plvlbar` 整块删除（`.plvl-pill` 保留给 quiz/bank 复用）· `spellcheck="true"` · `ROLES` 补 `duty/caps/primary` · `askConfirm()` 品牌弹窗替 `confirm()` · 全局 `keydown` 按优先级处理 Esc（confirmOv → drawer → rail） · `STYLES` 补 `descEn` 走 `L()` |
| C | 徽标与标题重复 · 引导用错误红 · 侧栏大片空白 · 假 chip · 删除按钮 24px 且预置源不可恢复 · 事实卡 4 类型仅 2 色值（`--teal/--purple` 名不符实）· 「AI · 待运行」语义不清 · 素材库 4 卡 vs 文章库 5 卡 · 筛选无清空 · `alert("No content")` 未本地化 · 敏感放行用原生 `confirm()` | 顶栏标题只留模块名 · `.nextbar .hint` 改中性色 + 虚线框 · `.railfoot` 挂快捷入口 + 版本号 · 假 chip 改纯文本「包含：…」 · 点击目标抬到 ≥32px（行内文字链接按 WCAG 2.5.8 豁免）+ `resetSources()` · `--teal → --tone-1`、`--purple → --tone-2` 语义改名（**防后人误加绿色**）· 徽标走 `L()` · 两库统一 5 张统计卡 + `bankFilterExtras()` / `clearBankFilter()` · `toast()` 替 `alert()` |

完整台账（含逐条证据 + 修复验证表）：`readpal/docs/14-前端排版与交互审查-20260915.html`
（`docs/assets/audit-*.png`）。**再改这些区域时按上面的"修复手法"列走，别把已修的坑重新踩回去。**


> 对照技巧：先拿**改动前**的副本跑一遍，确认它能抓出旧颜色 —— 否则无法
> 判断「0 违规」是真的干净，还是审计脚本失效了。

---

## 常见坑（实测踩过）

| 现象 | 原因 | 解法 |
|---|---|---|
| 截图全是 "This site can't be reached" | 本地 http.server 随 shell 退出被杀 | 用 `run_in_background=true` 启动 |
| 截图被去重、读到旧图 | 文件名相同，系统按内容哈希去重 | 用带时间戳的唯一文件名 |
| 强制加类名不生效 | 元素已有 `class`，再写一个 `class` 是重复属性，取第一个 | 合并进同一个 class 属性 |
| 改了没生效 | 并发 Edit 静默覆盖 | 用原子替换脚本 + 命中数断言 |
| SiliconFlow 报 `Model does not exist` | 模型名缺厂商前缀 | 写全 `Qwen/Qwen2.5-7B-Instruct` |
| Dify FACT 报 `material is required` | 入参字段名不对 | FACT 只传 `{material, style}`（**不要传 `level`**，见下条），material 必填 |
| Dify 报 `level in input form must be one of the following: ['A1.1',…]` | `start.level` 是 `select`，枚举值**只有点式**；前端 `state.lvl` 是**内部下划线键**（`A1_1`）→ 2.1s/0 token/0 节点被门口打回 | **FACT 不传 `level`**（标签本就写着「可选，空则由 nodeGrade 自动判」）；**GEN 传 `nkDisp(fc.level \|\| state.lvl)`** 转点式。⚠️ 若非要传 `select` 类入参，**空串也是非法值** —— 必须整个省略该键 |
| 以为「本地 ≠ 线上」要回拉源码 | 线上 HTML = 源码 + bridge 注入行（第 7 行 `<script>window.WB_API_BASE="";window.WB_CONFIG={…};</script>` 替换了本地的 `<script src="config.local.js"></script>`，差 234 字节） | **先归一化该行再逐行比**。归一化后若零差异 ⇒ 本地就是线上源码，别覆盖。把「部署产物」直接与源码做字节比会把注入误判成漂移 |
| 既有回归探针突然报红，以为是自己改坏了 | 探针断言写死了**旧口径**（界面文案/只读性/按钮），而需求早已反转 | **先做基线对照**：`curl -s -o /tmp/base/index.html https://raw.githubusercontent.com/Jinsong96/AI-Content-Center/main/frontend/index.html` → 另起端口跑同一探针。**两边失败项完全一致 ⇒ 与本次改动无关**，是断言过时；只把过时断言改成反向断言（并注明日期+原因），别去「修」代码 |
| 本地探针里 `AIWF_*.appKey` 为空、函数静默返回不报错 | 本地没有 `config.local.js`，`appKey` 空 → 函数**内部 `try/catch` 提前抛掉**，表现为「什么都没发生」 | 探针里先 `AIWF_FACT.appKey='app-PROBE'`（`const` 对象属性可改）再调用 |
| 以为「线上新字段全缺」 | `tools/dify_run_app.py --out=xxx.json` 写的文件**顶层就是 outputs 本身**，没有再套一层 `outputs` | 读 `d['align_map']`，**不要**读 `d['outputs']['align_map']` |
| `curl` 线上 `CONNECT tunnel failed, response 502`；`urllib` 直连超时 | 本机代理拦截 Railway 域；显式 `ProxyHandler({})` 绕代理后**仍超时** | **别在网络层绕** —— 用 CDP 从已登录的 Chrome 里 `Network.getResponseBody`（`Page.navigate` + 监听 `Network.responseReceived` 取 `requestId`）拿**原始响应体**，用 `Network.setCacheDisabled(true)` 防缓存 |
| 手写大段 `atomic_replace` spec 容易抄错 | 人肉复制长 `old` 必然出岔 | **从远端原版派生**：拉线上文件 → 用 `difflib` 定位差异块 / 用 `索引切片` 从**本地新文件**取 `new`、从**远端旧文件**取 `old` → 断言 `r.count(old)==1` → 跑 `atomic_replace` → **与本地文件比 sha256，逐字节一致才算通过** |
| 用「起止锚点 + 切片」生成 spec 时，删掉的**不是你想删的那块**（删完语法就错） | 锚点是**子串匹配**：想删 `  return head("09", …)`（2 空格）时，`if` 分支里 6 空格缩进的同名行**也会命中**，于是切片在分支内部就截断了，只删掉半个块 | **结束锚点必须带后面一两行**（用分支里不可能出现的后续行，如产线版才有的 `artWorkflowBar() +\n  \`<div class="validate">`），并断言 `切片.rstrip().endswith("}")`、含预期的起始特征。2026-09-23 删 s7 的 lite 分支时踩到，改完必须先 `check_js.py` |
| 新函数「插进去了、语法也过」，运行时却 `xxx is not defined`，而且那坨函数源码**当正文渲染出来了** | 插入点落在**模板字符串内部**（`return \`…\`` 里），JS 解析依旧通过，因为那就是一段普通文本 | 锚点要选在**函数外**（如 `function wfStrip(){` 之前），不要在 `return \`…\`` 与其内部标签之间插。**判据：`node --check` 过了不算数**，必须真渲染一遍看有没有冒出源码文本 |
| 探针读到「FACT 没有 `level_lo`/`info_points`、`gist_len=0`」 | `runGeneration()` 结束时把 **`state.live.run` 换成 GEN 的响应**，事后读它其实读的是 GEN 的 outputs | 要么在 **FACT 刚结束、GEN 未启动**时读；要么改用**穿透式记录器**（记录请求体但照常转发请求），见 `scripts/probe_live_e2e.mjs` |
| **切到没有内容的大档后，大档切换条整条消失、点不回去** | `alignedViewHTML()` 开头的 `if(!has) return ""` —— 切换条就渲染在这一块里，被一起带走了。区间模型下（素材只到 A2.3）必然触发 | 改成 `if(!has) return h+emptyGroupHTML();`，切换条与空态卡片始终保留。**判据：`.bigbar` 恒存在；`.bigtab` 数 = `4 − minIdx`（lite 走 `shownKeys()` ⇒ 3）。⚠️ 别再写「恒为 4」——2026-09-23 起 lite 是 3** |
| 想改切换条位置，怕出两条 | 它是 `_bigBarUsed` 一次性闸门 | **不必复制**：在目标位置先调一次 `bigBarOnce()` 占住闸门，原位置那次自动返回空串 |
| 大文件 PUT 失败 | 上传偶发 `IncompleteRead` | 重试 4 次 × 3s |
| 窄屏截图右侧被切、像布局溢出 | `chrome --window-size` 受最小窗口宽度限制（420 ⭢ 实际 vw≈500） | 用 `node tools/cdp_shot.mjs --sizes=...`（CDP Emulation） |
| 覆盖层内容贴顶、垂直居中失效 | `min-height:100%` 对 `position:fixed` 父元素无效；grid `place-items:center` 超高会裁顶 | 容器 `display:flex;flex-direction:column` + 子容器 `margin:auto`（并同步 JS 内联 `display`） |
| **头条热搜「无原文」，本地好线上挂** | `/trending/<id>` 普通 UA 只给 4.8KB JS 壳，原设计靠无头渲染取文章 id —— 而 **Railway 容器里没有 Chrome**，A2 整条静默降级 | **换搜索引擎爬虫 UA 走头条的 SSR 分支**（实测 Baiduspider/Googlebot/bingbot/Sogou 行为完全一致，取一个即可），纯 HTTP、0.3s/条、无需浏览器。见下「头条原文获取基线」 |
| 以为头条 SSR 命中率是概率问题（同批页面 6/11 ↔ 11/11 飘） | 实际**完全稳定**：对失败页连抓 10 次 = 0/10。差异来自**话题结构类型**，不是限流 | 别用「多试几次」当解法。先分型：块内 `/article/<id>`=文章型、`/w/<id>`=微头条型、都无=视频型（本身无正文） |
| 中文源兜底把**无关旧闻**当原配出处 | `cn_fallback_article` 的 `min_score=3` 失效。实测 4 分假匹配：热搜「国家卫健委：进一步营造生育友好环境」(2026) ↔「国家卫健委发布新冠病毒疫苗第二剂次加强免疫接种实施方案」(2022)，**只共有机构名** | `min_score` 提到 **6**（实测正经匹配最高只到 1–2 分）。**伪造溯源比缺原文更糟**，这是代码自己写明的原则 |
| 真实短简讯被当「抓取失败」，反而掉进兜底撞上假匹配 | 长度阈值卡在 150，而「上5休1…」133 字、「国家卫健委…」140 字**是真实完整简讯**（结尾有句号+来源署名） | 实测边界很干净：**视频文案 56–119 字，最短真实正文 133 字** → 阈值取 **125** |
| 给「主动筛掉内容」记 warn，结果整榜挂上「部分信源未抓到」横幅 | `_is_real_degradation()` 对**任何非渲染类错误**都返回 True（只白名单了 `_RENDER_SCOPES` 的 warn） | **正常业务筛选绝不写 `note_error`**。走独立台账（如 `filtered_video`）回传；也让被筛条目**不进 `_health_record`**（`continue` 要放它前面），否则源成功率被拉低 |
| 部署后首屏误报「部分信源未抓到，结果可能少于实际」，实际 0 个源失败 | 容器重建 → `/app/backend/.toutiao_en_cache.json` 丢失 → 首个批次 `_load_tr_cache()` 记 warn → `degraded=True`。该批次结束写回文件，**后续批次自愈**（实测第 2、3 次调用 errors=0） | 已知、一次性，**别按此排查真实故障**。根治＝让 `_load_tr_cache()` 对齐 `_load_tag_cache()` 的写法：**文件不存在属冷启动，不该告警**（现两处行为不一致，约 3 行） |
| 以为「第 2 次调用 3 秒返回」说明问题已修复 | `fetch()` 有 **5 分钟 UA 级缓存**，3 秒是缓存回放，什么都没跑 | 要验真实一轮，**等 >300s 再调**（或在探针里直接调函数、绕开服务端） |
| **`ui_audit.mjs --json` 里每页恒有「溢出 1~2」**，看着像没修好 | 它数的是 `getBoundingClientRect().right > clientWidth` 的元素，而离屏驻留的 `#drawer` / `#rail`（抽屉关闭态在画布左外侧）**必然命中** | 判据是 **`scrollWidth == innerWidth`**，不是"溢出计数=0"。改后 420px 下 12 页恒 `scrollW=420` 即为通过 |
| **只改骨架列的 `minmax(0,1fr)`，窄屏仍溢出** | `#topbar` 是**独立溢出源**：`.title`/`.userchip` 不可收缩、`.uout`（退出）被挤成两行 | 三件一起做：① 骨架列 `minmax(0,1fr)` + `#stage > *{min-width:0}` ② `#topbar` 子元素给 `flex-shrink` / `white-space:nowrap` / `text-overflow:ellipsis`，`≤560px` 隐藏平台名 ③ 多列栅格 `≤720px` 塌成 1~2 列（3~6 列硬撑会让卡片只剩 60–90px，每 2~3 字换行） |
| 量「顶栏按钮有没有换行」算错 | `getComputedStyle(el).lineHeight` 为 `normal` 时 `parseFloat` = `NaN`，`NaN \|\| 0` → 任何高度都判"换行" | 用 `document.createRange(); rg.selectNodeContents(el); rg.getClientRects().length` —— 行框数才是权威 |
| 想用 `drive_multi_state.mjs` 的 eval 步回传长测量结果，拿到的总是被截断 | 脚本对返回值**截断到约 40 字符**（`eval→p0 vw=420 scrollW=420 [.hotgri`） | 长结果**自带 CDP 探针**输出（探针的 `console.log` 不过截断）。见 `/tmp/grid_probe.mjs` 的写法可直接复用 |
| 想量「有内容时」的栅格/排版，探针里那些选择器全都量不到 | 空数据下 A4 引导空态会 **`return` 掉整块**，`.mat-stats` / `.dashstats` 根本不渲染 | 先注入 mock（写 `state.live.run.data.outputs` 的 `articles_json`/`paras_json`/`quiz_json`… 再 `applyLive()`）再量 |
| **「生成文章」按钮点了没反应**（其实抛错被 catch 吞了） | `runGeneration()` 里 `fetch(..., {signal: _abortSignal})` 在声明 `const _abortSignal = _runAbort.signal` **之前**就引用它 → **TDZ（暂时性死区）** `ReferenceError`，被 `catch` 吞成「网络错误：Cannot access '_abortSignal' before initialization」，用户只看到「没反应」 | `AbortController` / 它的 signal 必须在用到它的 `fetch` **之前**创建。改完用探针验证：设假 `appKey` + 假 `apiBase`（`127.0.0.1:9` 必失败地址）触发 `runGeneration()`，断言 `state.live.err` **不含** `_abortSignal`/`Cannot access`（即已越过 TDZ 走到 fetch） |
| **段落校对页「编辑了但没生效」**（界面文字变了、下游全是原文） | `paraEdit(this)` 收到的 `this` 是 `.pbody`，而 `data-k`/`data-i` 挂在父级 **`.pcard`** 上 → `el.getAttribute("data-k")` 恒为 `null` → `GEN[null]` undefined → **第二行静默 return**。`contenteditable` 是浏览器原生行为，字确实改了、连词数徽标都刷新（那行写对了），所以界面给的是「成功」的假信号；实际**内存/草稿/入库/审核四处全是原文**且零报错 | 从 `el.closest(".pcard")` 取属性；失败必须报错不能静默返回。回归探针 `node tools/probe_para_edit.mjs`（19 项断言；旧写法回退可复现 11 项失败），详见下方「编辑类回调」小节 |

## 段落对齐告警条（2026-09-20 上线 · 改 `applyLive` / `alignWarnHTML` / `s9` / `alignedViewHTML` 前必看）

**背景**：四档**恒为 12 段**（聚合层会把 >12 段截回 12），界面 `alignBodyHTML()` 纯按 `maxP` 索引铺行
→ 某档「拆段被静默截断」时**看起来仍是对齐的**，但内容已整体跳位。
**这是这类问题唯一能被用户察觉的入口，绝不能再静默。**

- **数据来源（3 个字段，缺一不可）**：
  - `align_map`：4 档折到同一 gist 轴后的映射，**正常恒等 `[[1],[2],…,[12]]`**；
  - `para_clean_count`：**截断前**段数 —— 段数信号**只在这里**（`para_count` 取自截断后数组，恒为 12）；
  - `map_warn`：后端告警文本。
- **`applyLive()`** 收成 `state.alignGuard = { warn, off, counts }`；**无告警时为 `null`**。
- **`alignWarnHTML()`**：**校验层「段落对齐」项判决优先**（更权威、带详情），
  前端从 `align_map` 自推的结果只作补位；两者都无 → 返回空串。
- **调用点只有两处**：`alignedViewHTML()`（一处覆盖 s12 等所有复用点）与 `s9()`。
  ⚠️ **不要**在 `s12()` 里再加一次 —— 它内部走 `alignedViewHTML()`，会出两条。
- **新一轮清空**：`startLiveRun()` 里 `state.alignGuard = null`（与 `factMap` / `unusedFacts` 同批），
  否则上一轮的告警会串到新素材上。
- 样式类 `.alignwarn`（`#FFFAEB` 底 + `#F79009` 左边框 + `.aw-h` / `.aw-ico` / `.aw-fix`）。
- **验证两步走**：① `/tmp/test_alignwarn.mjs` 用**真实线上 outputs** 构造 4 场景
  （正常→空串 / 截断→点名段数 / 错位→校验详情 / 老缓存→不崩）；
  ② 用 CDP 在真机 Chrome 里**真实渲染**，`getComputedStyle` 断言底色/边框 + 量 `getBoundingClientRect()`
  确认黄条真的可见（只看返回的 HTML 字符串不算验证）。

---

## 授权母稿链路（第四入口 · 2026-09-21/22 · 改 `licensedPanelHTML` / `licConfirmHTML` / `licRunGen` 前必看）

导入已授权 B1/B2 母稿 → 只往下生产（B2→B1+A2+A1-；B1→A2+A1-），母稿本身也入库，**不抽事实**。
两张独立 Dify 图：图 A 预处理（`licprep`）+ 人工确认分段 + 图 B 向下生成（`licgen`）。

**关键函数**：`licState()` 状态中枢 · `licensedPanelHTML()` 导入面板 · `licPrepOne()` 跑图 A ·
`licConfirmHTML()` 确认页 · `licRunGen()` 跑图 B · `licSegBad()` 每段是否算不合格 · `licTotalHTML()` 全文行。

### 🔴 硬约定（改这里之前逐条核）

1. **不勾精简 = 逐字保留原文**。正文由图 A 的 code 节点硬取原文，**前端不做任何"复原/拼接/兜底改写"**。
   分段只移动切分点 —— 所有段拼起来必须与原文逐字一致（`probe_graphA_band.mjs` 会验）。
2. **`need_simplify` 必须始终显式传 `'true'` / `'false'`** —— 不能"不勾整个省略该键"。
   （省略会让图 A 提示词里的 `{{#nodeStart.need_simplify#}}` 取不到值。）
3. **每段词数是分段的唯一依据**（2026-09-22 二次改口径）：
   - 合格带 = 该档每段规格 **±5 词** → B1 **23–40** / B2+ **36–55** —— 取法 `licBand(r)`；
     导入面板用 `LIC_PER_PARA` 算预估（与图 A/B 的 `PER_PARA` 同源）
   - **全文字数不参与决策**：导入面板不再摆「推荐字数区间」，改成只读的「**预计段数**」
     （`licEstSegs()` = 正文词数 ÷ 每段中点）
   - 「参考段数」输入框与 `licSet(id,'target',…)` 分支**已删**，别再按它算任何东西
4. **`licSegBad()` 是"每段词数是否标红"的唯一判据**：
   保留原文按 ±5 合格带判、精简按严格规格判。图 A 的质检程序会先把每段拉进带内，
   所以标红的基本只剩「一整句话超长、无处可切」这类真问题。
5. **段数只提示不阻断**：黄条**只在段数跑出 10–15 时**出现（`LIC_SEG_OK_LO=10` / `LIC_SEG_OK_HI=15`），
   配一颗「仍然继续生成」（`onclick="licRunGen()"`）；底部原本的「确认，生成 …」照旧可用。
   ⚠️ **下界 2026-09-22 由 8 收到 10** —— B1 硬区间 323–437 ÷ 每段 28–35 ⇒ 8 段最多 280 词，够不着下界。
   ⚠️ 段数现在由「词数 ÷ 每段目标」算出来（319 词 B1 → 10 段），**再喊「推荐 12 段」就是噪音**。
6. **精简模式的口径**（Bryan 2026-09-22 拍板，**取代「正好 12 段」**）：
   硬指标 = **全文字数落进该档硬区间**（B1 323–437 / B2 468–632）；段数按大意自然分，
   **10–15 段只是兜底判定区间**。`LIC_DEF_SEG` 只用于 `licRange()` 的**展示估算**，别拿它当契约。
7. 🔴 **`licSet()` 改完状态必须重绘**（2026-09-22 修的阻塞 bug，别再退回去）：
   它是本面板**唯一**不调 `render()` 的入口，于是「粘完正文 + 选完档位」后三处全部停在旧样子 ——
   ① 就绪红条 `.licneed` 仍写「第 01 篇还没选母稿档位」；② 行内仍写「先选母稿档位，才能预估段数」；
   ③ 底部 `licEmbarkBtn()` 返回的还是 **`waitBtn()`（不是 button，点不动）⇒ 进不了下一步**。
   现行实现：`if(key === "title") return;` 之后 `render()`，并用 `stage.scrollTop` 存还滚动位置。
   **标题输入框是唯一例外** —— 它逐字触发 `oninput`，重绘会丢光标；标题也不参与就绪判定。

   ⚠️ **回归用例里不许在 `licSet` 后面补 `render()`** —— 手动重绘会把这类 bug 整个盖住，
   这正是旧 51 项用例漏掉它的原因。改档位/勾精简一律走真实事件
   （`s.dispatchEvent(new Event("change",{bubbles:true}))`），见 `probe_lic_flow.mjs` 第 **1b / 1c** 组。

8. ⚠️ **展示类数字不许用 `licSegRange().n`** —— 那个 n 被 `LIC_REF_MIN/MAX`（6–30）夹过，
   只作 `licRange()` 防脏值用。段数跑出该范围时「N 段 × 每段词数 = 区间」会变成假话。
   `licTotalHTML()` 已改成按 `st.prep.segs.length` 现算（`lo/hi` 也一并现算）。

9. 🔴 **多轮重跑期间 UI 必须停在等待页，不许露出中间稿**（2026-09-23 修，Bryan 实测反馈）：
   生成后有三层校验（字数 / 句长 / 超纲），任一不达标就整篇重跑（`licRunGen` 的 `MAX_REGEN=2`）。
   旧实现每一轮都立刻 `state.live.status="done"` + `applyLive()` ⇒ 下一轮开头的
   `licSetBusy()+render()` 会把「马上要被替换掉的中间稿」渲染成完整文章预览页 ——
   用户能读、能点「进入 AI 校验」，读到一半才被告知「质量不达标，自动重跑」。
   **正确时序：等待页 →（全部重跑结束、版本定稿）→ 文章预览 → 分段/校对页。**
   现行做法：
   - 只有定稿（达标 / 用尽重跑次数）才 `status="done"`；
   - 重跑分支先清 `GEN = {}`（连带 `state.words12 / state.meta12`）、`state.live.run = null`、
     `status="running"`，并**重置 `t0/elapsed`**（不重置进度条会顶在 90% 像卡死）再 `continue`；
   - `licRunGen` **开跑处也清一次旧稿** —— 否则接第 2 篇母稿时 s6 会拿上一篇的文章冒充本次结果；
   - 普通链路 `runGeneration` 的超纲重跑分支同样处理；
   - 等待文案用 `licState().busy`（重跑时它是「质量不达标，自动重跑第 N 次（字数/句长/超纲原因）」），
     是**替换** s6 那句固定 runTxt，不新增 DOM 元素。
   **回归**：`tools/probe_lic_rerun_gate.mjs`（真跑 DOM，10 项断言 + 负向对照）。
   对照组实测：修复前 3 项失败、24 帧违规；修复后 10/10。
   ⚠️ 写这类断言别用「读代码顺不顺」判断 —— 泄漏只发生在「某一轮 render 的瞬间」，
   必须按帧采样（本探针 60ms 一帧 + 记录 `status` / `GEN` / `.gentabs` / `#s6run`）。

### 「母稿导入 → 文章生产」通审：历史问题清单（2026-09-22 记）

**已修（2026-09-22 下午，Bryan 拍板 A/A）**：
- ~~生成成功后没有「进入文章生产」出口~~ ⇒ `licRunGen` 成功路径现在**自动 `go(6)`** 跳「08 内容生成」结果页，
  跳转前把 `state.lvl` 指到本批真有内容的最高档（B1 母稿向下只产 A2/A1-，否则 s6 空白）。
- ~~预处理「点两次」~~ ⇒ 根因是 **busy 状态泄漏**（`st.busy` 字符串提示在某条路径漏清 ⇒ `if(st.busy)` 永真挡第一次）。
  已加看门狗：`licBusyBlocked(stage)` + `licSetBusy/licClearBusy` 带 `busyT0` 时间戳，
  超 `LIC_BUSY_WD_MS`(120s) 未清自动放行；未超时仍挡（防连点）。prep / gen / 读文件三处全换。

**仍未处理（等 Bryan 拍板）**：

| # | 问题 | 说明 |
|---|---|---|
| 1 | **生成成功后主按钮文案不变，再点会重跑图 B** | `licConfirmHTML` 只读 `st.prep`，不看是否已生成 ⇒ 重复扣一次额度。`st.gen` 更是**死字段**（仅写入，全文件从不读取） |
| 3 | **图 A 出结果后回不到导入面板** | 只渲染 `licConfirmHTML()`；`pickRoute('licensed')` **不清** `st.prep` ⇒ 只能刷新页面，而 `state.lic` 不落盘、全丢。建议加一颗「返回母稿列表」（清 `prep`、保留 `arts`） |

### 来自图 A 的四个信号（都要读，别只看 `warn`）

| 字段 | 含义 | 前端行为 |
|---|---|---|
| `ok` | **只有勾了精简**才会 false（词数越出该档硬区间，或段数跑出 10–15） | 红条 + 重跑出口 |
| `seg_note` | 段数跑出 10–15 的非阻断提示 | 黄条 + 继续按钮 |
| `fallback` | 勾了精简却没拿到精简稿 → 已自动回落为保留原文 | **必须显式提示** |
| `out_of_band` | 质检兜底后**仍**越界的段数（如整句 60 词，句末无处可切） | 图 A 同时写进 `warn`，界面照常显示 |
|  | ⚠️ `out_of_band` 的 warn **只在保留原文模式报** —— 精简稿跑的是段数兜底而非长度重排 |  |

### 来自图 B 的第六个信号：`sem_json`（逐段大意核对，2026-09-22 新增）

图 B 新增 `nodeSemCheck`（LLM）→ `nodeEnd.outputs.sem_json`。**这是提醒，不计入分数、不拦入库。**

| 函数 | 职责 |
|---|---|
| `semResult()` | 解析 `sem_json`：剥 markdown 包裹（取首 `{` 到末 `}`）、按 `LEVEL_BY_KEY` 过滤、算 `badTotal` |
| `semBadSegs()` | 返回 `{档位: [错位段号]}`，供行标记用 |
| `semWarnHTML()` | 三种态：**无法解析**（报原始片段）· 全过（`.semok` 虚线框）· 有错位（`.alignwarn` 黄条） |

三处挂载：`alignedViewHTML()`、`s9()`（正文上方）、`showVSum()`（校验面板，附一句
「不计入上面的分数 —— 它是提醒，不拦住入库」）。

**段落对照视图行标记**：`alignBodyHTML()` 给被点名的行加 `class="alignrow sembad"`
（`.arow-no` 变琥珀色 `#FFFAEB/#F79009/#B54708`）。

三条踩过的坑：
- `sem_json` **缺失不是错误**（老图 / 热点链路没有这个字段）⇒ 返回 `null`、不显示，别报红。
- 文案**不能用 markdown 星号** —— HTML 不解析 `**`，会原样显示。用 `<b>`。
- 行标记测试**不能依赖当前路由**已渲染对齐视图；直接
  `d.innerHTML = alignBodyHTML(false); document.body.appendChild(d)` 再 `querySelectorAll`。

✅ **判据已放宽（2026-09-22 二次迭代，已上线 hash `723fa03a`）**：改为「保留核心实体即对齐」，
删细节/删多余例子/相邻段 ±1 段平移都不算错位，只报「整段换主题 / 凭空新增 / 整段漏光」。
实测同一母稿 sem 误报 14 → 0。**「可对相关档位重新生成」这句当前不再误报时可保留**；
若日后再出现系统性误报，先改判据、别让用户去重跑合格档。

### 校验面板

校验分母用后端回传的 `vj.total_checks`，**不要写死**：12 段骨架时 **33**（3 档 × 11），
10 段骨架时 **22**（2 档 × 11）。母稿档不在结果里，
界面上要写一句「母稿档 X 不参与规格校验（长度不由我们控制）」。

### 热点搜集：「挑」与「跑」分离（2026-09-22，Bryan 拍板）

**点卡 ≠ 开跑。** 点热点卡只选中 + 右下预览，确认点才进流程；挑的阶段全程零 LLM 调用。

| 函数 | 职责 |
|---|---|
| `pickHot(i)` / `pickRealHot(h)` | **只选中**：写 `state.hot` / `state.realHot`（两者互斥）+ 高亮，`render()`。**不再调 `startLiveRun`、不跳页**。运行中（`status==="running"`）被拦截（Q1=B：不能边跑边挑） |
| `hotPeekHTML()` | 右下固定面板 `.hotpeek`：标题/中文/原文/来源链接/热度 + 「开始敏感排查」按钮 + 「✕ 取消选中」。**只在挑选阶段显示**：`cur==1`（热点页）+ `status==="idle"`（未开跑）+ 已选中，三者缺一即返回空 ⇒ 确认进入下一步后立刻消失 |
| `confirmHotRun()` | **唯一流程入口**：无正文热点此时才弹「粘贴原文」→ `startLiveRun` → 跳 02 |
| `cancelHotSel()` | 清空 `realHot`/`hot`/`hotTopic` |
| `mountHotPeek()` | 面板挂到 `body`（`stage` 每次 innerHTML 重建会清掉它），`render()` 里每次调用 |

- 三类卡（真实 realHots / 演示 HOTS / 自定义 customHots）都走这套，选中加 `.sel`、运行中加 `.locked`。
- `skipPasteHot()` 已改：**不再跳过粘贴就硬跑**（拿薄素材硬跑是 Bryan 反对的），改为取消选中。
- 底部按钮：选中后由「进入敏感排查」改为一句提示「点右下开始」，避免绕过 `confirmHotRun`。
- 🔴 **测试点卡要命中真正带处理器的节点**：演示卡的点击绑在**内层** `[style*='cursor:pointer']`
  的 div 上（容器 `hasOnclick=false`），真实/自定义卡绑在容器上。且卡片是**错峰 setTimeout 渲染**，
  点之前要等渲染完（≥1.6s）。实测脚本 `/tmp/probe_hot_peek.mjs`（13 项）。

### 回归

```bash
cd frontend && python3 -m http.server 8899 &   # 必须 run_in_background，(cmd &) 活不过一条命令
node tools/probe_lic_flow.mjs --url=http://127.0.0.1:8899/index.html --port=9242   # 62 项断言
node tools/probe_lic_rerun_gate.mjs --url=http://127.0.0.1:8899/index.html --port=9244  # 10 项断言（生成期 UI 闸门）
node tools/probe_fact_edit.mjs --url=http://127.0.0.1:8899/index.html --port=9250  # 33 项断言（事实卡可改/可删/可新增）
```

> ✅ **`probe_lic_flow.mjs` 基线已是 62/62**（2026-09-23 全部收敛完毕）。
>
> 2026-09-22/23 那轮「授权链路轻量化」改掉了一批界面元素，探针没跟着改，曾一度停在 **51/62**。
> 当时的判别法值得复用：把远端 `main` 的 `frontend/index.html` 拉一份到 `/tmp`、另起端口跑
> 同一个探针 —— **两边失败项完全一致** ⇒ 与本次改动无关，是断言自己过时了。
>
> 那 11 条的归因（**改断言前先照这张表对号，别当成真 bug 去改代码**）：
> - **纯文案过时（2 条）**：「开始预处理」→「开始分段」；确认页按钮 →「确认，进入下一步」。
>   `onclick` 目标（`licRunPrep` / `licGoGen`）都没变 —— 只改字面量，别动逻辑。
> - **功能按需求删除，断言要反转成「不该出现」（9 条）**：`.liccalc` 的「偏短/偏长/常规区间」
>   提示文字（只留 `warn` 黄底 class，`tooShort` 已作为死变量删除）；顶部红条 `.licneed`
>   现在只在 `st.err` 时渲染；「已就绪，可以开始预处理」—— `.licok` 只剩 CSS、零渲染引用；
>   20 段提示与「仍然继续生成」按钮（`grep 仍然继续生成` = 0）；大意核对全过时不报警。
>
> 🔴 **段数跑出常规区间 10–15：Bryan 2026-09-23 拍板「保持静默」** ——
> 不出提示、不给确认按钮、也不阻断生成。所以对应断言是**反向**的（「不该出现」）。
> 看到这条静默别当成 bug 去补提示，是有意为之。

其中 **1b / 1c 两组专治「改了状态不重绘」**（见硬约定 7），**全程不许调 `render()`**：
- **1b**：真实 `change` 事件改档位 / 勾精简 → 就绪红条、行内预估、底部按钮三处必须立刻变。
- **1c**：真实 `input` + `click` 走完 **粘贴 → 加入列表 → 移除**（Bryan 实际操作的前半段），
  断言列表条数、输入框清空、红条点名第几篇、底部是否回落到 `waitBtn`。

⚠️ **`waitBtn()` 渲染的不是 `<button>`** —— 断言「底部不可点」要用
`!!document.querySelector(".nextbar button") === false` + `.nextbar` 文案含「请先补全」，
抓 `.nextbar button` 的 `textContent` 只会拿到空串（踩过一次）。

## 轻量提示词链路（第五入口 · 2026-09-24 起 = **骨架锁定生产链路**）

**2026-09-24 定位变更**：原先是「裸跑图 C」的对照实验入口，实测**段数对齐率只有 62%**、
逐段词数完全不分级（A1- 19–59 词/段）⇒ Bryan 报障后拍板接骨架。现在这条链是：
**定骨架（图 A）→ 人工确认 → 逐段生成（图 C，提示词一字不改）→ 代码校验段数 + 不齐带差量回炉**。
对照实验的使命已完成（它证明了单次盲跑的天花板），不要再往回退。

图 = 图 C（`tools/build_graphC.py`）+ 借用的图 A（`licprep`，`need_simplify:"false"`）。

### 🔴 骨架注入块 = 三段拼装，**缺【逐段篇幅】就会每段写长一倍**

```js
/* liteRun() 里，骨架只作为**输入文本**拼进 master_text —— 图 C 的提示词一个字不改 */
skelBlock =
  "【段落骨架】下面是母稿按大意切好的 N 段（每段一行）。\n"
+ "你改写时必须严格沿用这 N 段：段数必须正好 N 段，第 i 段只讲骨架第 i 段的事，不得合并、不得拆分、不得调换顺序。\n\n"
+ "1. …\n2. …\nN. …\n\n"
+ perLine + "\n\n";        // ← 【逐段篇幅】A1- 每段 11–14 词；A2 每段 20–22 词。按段分别控制，不卡全文字数。
```

**真模型实测（`tools/probe_lite_skel_e2e.mjs`，母稿 311 词）**：

| 输入块 | 段数 | 每段词数 |
|---|---|---|
| 只有【段落骨架】 | 11/11/11 ✅ 对齐 | A1- `[20,14,19,25,27,30,26,27,28,25,23]` ❌ 只 1/11 落带 |
| 骨架 + 【逐段篇幅】 | 11/11/11 ✅ 对齐 | A1- 11/11 落带（13–14 词/段）、A2 11/11 落带 |

⇒ 模型默认按「压缩但不减段」处理；**不告诉它每段多长，它就不会压到位**。
`perLine` 的数值取自 `LIC_PER_PARA`（与图 B `nodeValidate` 的 PER 表同源），别另写死一份。

⚠️ **这两个探针里逐字复制了同一段拼装逻辑，改前端必须同步改，否则探针就失去意义**：
`tools/probe_lite_skel_e2e.mjs` 的 `skelBlock()`、`tools/probe_lite_skeleton.mjs` 的断言。

### 三个探针 + 一个大意核对（改 lite 后按顺序跑）

```bash
node tools/probe_lite_skeleton.mjs      # 本地静态服务 + stub，验前端逻辑（51 条）
node tools/probe_lite_route.mjs         # 旧回归，无骨架时的向后兼容退化路径（42 条）
node tools/probe_lite_skel_e2e.mjs --rounds=2   # 借真实 Chrome 直连 Dify，验真模型（段数/逐段词数）
node tools/probe_lite_skel_online.mjs   # 打开线上页真点按钮，走 Railway 桥接层（13 条）
node tools/check_gist_align.mjs         # 借事实检查图核对「第 i 段大意对第 i 段」（代码判不了语义）
```

### 🔴 判据只有一个：`isLicLike()` / `isLite()`

lite 与 licensed 是**同一种东西**——「吃一篇文章、吐几档改写稿」，所以共用 `state.lic`
状态机与生成后的全部渲染页（预览 / 校对 / 审核 / 入库）。全站判断入口**只准**写：

```js
function isLicLike(){ return state.route === "licensed" || state.route === "lite"; }
function isLite(){ return state.route === "lite"; }
```

❌ 不要再散写 `state.route === "licensed"`。**再加同类入口时，只改这两个 helper + 下面三处。**

### 加同类入口的必查清单（四处，少一处就是空白页 / 点了没反应 / 目标档位变错）

| 处 | licensed 的前提 | lite 的前提 |
|---|---|---|
| `s0()` 底部按钮分派 | `licState().prep`（分段已确认） | `licState().prep` **有骨架** ⇒ 骨架确认页；否则 ⇒ 导入面板（底按钮「定骨架」） |
| `s6()` 顶部「生成文章」分支 | `!!licState().prep` | 看 `liteHasText()`；lite 走完骨架页进来就该给「生成」按钮 |
| `s7()` AI 校验页 | 有 `validation_json` 渲染校验表 | **这一页在 lite 下整条不存在**（2026-09-23 起）：不再渲染任何说明，改由 `go()` 把 idx 8 改送到 9 |
| **档位收敛** | 恒 4 档 | **`shownKeys()`** ⇒ 3 档。不改 ⇒ 空 B2+ 列 / 空 tab / 空 pill，页头还写「4 档对照」 |

> 🔴 **新入口的档位范围若与产线四档不同，必须走 `shownKeys()`，不许在渲染函数里写死数字。**
> 四条产线链路与 lite **共用同一批渲染函数**（`bigBarHTML` / `alignBodyHTML` / `quizAlignedHTML` /
> `alignModeBarHTML` / `s12` 标题），写死 3 会把产线页面一起砍掉。

`artFlowSteps()` / `intakeBackBar()` / `pickRoute()` / `applyLive()` 的标题锁定 /
`updateLiveProgress()` 的进度分母，一律走 `isLicLike()`。

### 六个必须知道的实现细节

1. **母稿（B1）有骨架时 = 骨架段本身**：图 C 不返回母稿，`liteRun()` 把
   `articles_json.B1` / `paras_json.B1` 覆盖成骨架的 N 段（**不是另切一份**）—— 这样四档段数
   天然一致。只有**没骨架**（异常退化路径）才退回 `liteMasterParas()` 按原空行切。
   （理由：B1 有 3 道题，没有对应文章可看，用户看不懂题目指向哪里。）
2. **`state.live.licN` = 骨架段数**（有骨架时）。无骨架才退回模型实际段数（`paras_json.A1` 长度），
   最后兜底才是 `expectedParaCount()` 的默认 **12**。
   ⚠️ 曾经的口径是「一律取模型实际段数」—— 那等于**让模型自己当裁判**，正是段数不对齐那个 bug 的老口径。
3. **回炉是异常兜底，不是主路径**：生成后**用代码**比 A1- / A2 段数与骨架是否相等，
   不齐 → 把量出来的差量（「A1- 段数：现在是 2 段，必须正好 3 段」）拼进下一轮 `master_text`，
   首轮 + 2 轮共 **3 次**上限；仍不齐 → 写 `state.live.skelWarn` + `console.warn` + toast，
   **不阻断**（照常落 idx 7，让用户逐段审核时手动处理）。
   ❌ 绝不允许静默：段数不齐必须说出来。
4. **`liteInput()` 绝不能整页 `render()`** —— textarea 被重建，正在输入的人丢光标（同 `licSetSeg` 的教训）。
   要切底部按钮就调 `liteRefreshBar()`，它只 `replaceChild` 那一个节点。
5. **`parse_ok !== "true"` 必须显式拦下**（错误条 + 重试按钮），不能让它生成一篇「什么都没有」的空壳。
   `parse_warn` 里会带缺档 / 题数不对 / answer 越界 / 已知外的题型等具体原因。
6. **`GEN[k]` 没有 `text` 字段** —— 结构是 `{title, by, cover, paras: [[段落], …], metrics, used}`。
   正文只能由 `paras` 拼回来（`paras.map(p => Array.isArray(p) ? p.join(" ") : p).join(" ")`）。
   写断言时若习惯性取 `GEN.A1.text` ⇒ 恒为空 ⇒ 会误报「A1 与 A2 内容相同」这种假缺陷（踩过一次）。
7. **「返回改母稿」只清骨架，不清正文**（`liteBackToInput()`）：清 `prep` / `confirmed` / `err`，
   保留 `liteText` / `liteTitle` —— 用户改一两个词不用重贴几千字。

### 🔴 对照组必须剔除的产线控件（2026-09-23 实测 4 处泄漏）

Bryan 口径：*「这个极简版本，只有这些提示词，原来所有的分级标准、检验标准和字数约束等都不对它起作用，都不需要有。」*
**核查方法：不看代码下结论，生成完成态下逐页取真实 DOM。**

| # | 位置 | 症状 | 处理 |
|---|---|---|---|
| 1 | `s6()` 生成完成页 | **写作风格条漏进来了**。点它 → `setStyle()` → `runGeneration()`，跑的是**四档产线主链路**（不是图 C）⇒ 对照组用户点一下模型输出就被换掉。**这是功能性错误，不只是显示不对** | lite 下不渲染 `styleBarHTML()` |
| 2 | 同上 · 侧栏 4 指标 | 标签写死「AI 校验得分（本档 8 项）」「蓝思值 · 区间」「篇幅 · 目标 128–172 词」，前两个对 lite 恒为「—」/假区间 | 标签按 lite 口径出；`applyLive` 里 `metrics[0]` 换成「段数 · 实测」 |
| 3 | 同上 · 事实卡引用面板 | lite 不抽事实，面板却写「运行 AI 工作流后展示事实卡」——已经运行过了，等于骗人 | lite 下整块不渲染 |
| 4 | 档位条 / 对齐网格 / 题目对照 / 审核页标题 | 产线按四档铺 ⇒ 空 B2+ 列、空 tab、空 pill，「4 档对照」「4 档练习题」「逐段原文 · 4 档对齐」 | 走 `shownKeys()` |

```js
/* 本链路实际有产出的档位。非 lite 恒返回全 4 档 —— 产线行为一字不改。 */
function shownKeys(){
  if(!isLite()) return allKeys();
  const ks = allKeys().filter(function(k){ return GEN[k] && GEN[k].paras && GEN[k].paras.length; });
  return ks.length ? ks : allKeys();      /* 还没生成时仍给全档，避免空页 */
}
```

**有意不动的地方**（别顺手一起删）：
- **段数 / 段落对齐**：这不是「字数约束」，而是**提示词自己写明的核心要求**（「所有版本保持段落数和段落内容对齐」）。
  保留 3 档对齐视图与段落校对页，只把脚注从「AI 切分 + 人工校对」改成 lite 口径。
- **`expectedParaCount()`** 仍取模型实际段数（`state.live.licN`），不落回默认 12。

### 🔴 某一步在某个入口下「整条不存在」时，必须三处一起收口（2026-09-23 建）

lite 是对照组，不跑任何质量校验 —— Bryan 要求把 **AI 校验页连同「本链路不做质量校验」那句说明一起删掉**
（此前那句说明是为了防空白页而保留的，**口径已反转**）。删一个步骤**远不止删那段文案**：

| 处 | 改法 | 漏了会怎样 |
|---|---|---|
| `artFlowSteps()` | `if(!isLite()) steps.push({idx:8,…})` —— **不是**隐藏，是这一步不进列表 | 顶部步骤条仍写 5 步、还摆着一个点过去没东西的节点 |
| `go()` | `if(isLite() && i===8) i = 9;` | 任何入口（原底部按钮 / 底部工作流条）落到 8 ⇒ 渲染出产线版的空校验页（**空白页**，正是原来最想避免的） |
| `wfStrip()` → `wfStages()` | lite 过滤掉该节点 | 底部「完整工作流」里还留着它，点了被静默改送 —— 一句说不通的空跳转 |
| `s7()` | 删掉 lite 分支（**保留产线分支**） | 留着就是那段要删的文案 |

> ⚠️ **`artFlowSteps()` 会自动重编号**（`no:String(i+1)`），所以少一步不用手工改编号；
> 但**页头步骤号（`head("09",…)`）是硬编码的产线号**，lite 下本来就和步骤条不同名，别去同步它。
>
> **负向对照必须有**：`state.route="licensed"` 时 `go(8)` 必须仍停在 8 ——
> 否则说明「改送 9」被写成了全局规则，把产线的 AI 校验页一起干掉了（探针第 ⑪ 项就在测这个）。

### 🔴 页面索引 ≠ 步骤号（写探针取页面时必查）

`render()` 的分派数组是 `fns=[s0,s1,s2,s3,sMaterialBank,s4,s5,s6,s7,s9,s12,sArticleBank]`，
而各页 `head()` 里印的步骤号是另一套：

| 页面 | `go(idx)` 索引 | 页头步骤号 |
|---|---|---|
| 内容生成 | **7** | 08 |
| AI 校验 | **8** | 09 |
| 段落校对 | **9** | 10 |
| 逐段审核 | **10** | 11 |
| 文章库 | **11** | — |

另外**内容生成页没有 `.bigtab`**（它只有 `.gentab`），档位条只在段落校对 / 逐段审核出现。
第一版 e2e 探针就因为这两条取错页面，报了两个假失败。

### 硬约定 10 · 新增一个工作流（wf）必须同时改 **两处**

`backend/agent_reach_bridge.py` 里有两个**各自独立**的白名单，漏一个就出半死状态：

| 位置 | 作用 | 漏掉的症状 |
|---|---|---|
| `_serve_index()` 的 `_envs` | 把 key 注入首页 `window.WB_CONFIG` | 前端显示「服务端未配置 XXX 密钥」 |
| `/api/dify/workflows/run` 的 `keymap` | wf 名 → 环境变量名，代理转发用 | **前端拿得到 key，一点生成就 `unknown wf (expect …)` 400** |

🔴 **2026-09-23 踩的就是第二个**（加 `lite` 时只改了 `_envs`）。
**为什么本地探针没抓到**：桥接层没起（本地 8787 没跑）⇒ `difyCall` 静默回退直连 `api.dify.ai`，
**压根没走代理** ⇒ `keymap` 一行都没执行。
⇒ 教训：**「本地跑通了」不等于代理路径跑通了**；涉及代理的功能，回归必须真起桥接层。

```bash
node tools/probe_bridge_wf.mjs      # 真起后端 + 逐个 wf 打空 inputs
```
断言分两组：已知 wf 不许回 `unknown wf`、且不许回 `missing upstream api key`（= key 真的取到了）；
负向对照：乱写的 wf 必须回 `unknown wf` + 400。
用 `BRIDGE_FILE=backend/_mut_xxx.py` 可指一份变异体，验证探针真的会红（变异体**必须放 `backend/` 下**，
否则 `_BASE_DIR` 推导错、连 config 都读不到，报错性质就变了）。

### 回归

```bash
python3 tools/check_js.py frontend/index.html <node>
node tools/probe_lite_route.mjs        # 42 项（含 3 条负向，stub 掉网络 ⇒ 快、可反复跑）
node tools/probe_graphC_parse.mjs      # 24 项（解析节点单测，不依赖浏览器）
node tools/probe_lic_flow.mjs          # 64 项：改了 isLicLike 的覆盖面后必跑
node tools/probe_bridge_wf.mjs         # 15 项：真起桥接层，验每个 wf 都能被代理转发
                                       #   ⚠️ 新增/改名任何工作流**必跑**（见硬约定 10）
```

**真调 Dify 的端到端**（改完图 C / lite 链路后跑一次，验证「真的能出文章」而不只是 UI 不报错）：

```bash
# 前置：frontend/config.local.js 必须有 DIFY_WF_LITE
cd frontend && python3 -m http.server 8899 --bind 127.0.0.1 &   # 必须后台起
cd .. && node tools/probe_lite_e2e.mjs                          # 43 项 / ~30–40s，真跑图 C
```

它会验：密钥注入 → 5 个入口 → 三档文章建起来 → 段数一致 → B1 = 用户粘贴的原文 →
A1/A2 确实不同且 A1 更短 → 三档题配额（语言/文本/逻辑/认知）→ 后续每页非空白 →
**idx 8 AI 校验页已删除**（`go(8)` 落到 9、无旧说明、步骤条 4 步、底部条无该节点）→
**第 5 组「产线约束未泄漏」**（无 `.stylebar` / 无 `.factused` / 侧栏不提「AI 校验得分 / 蓝思 / 目标」/
档位条 3 个 / 无空 B2+ 列 / 文案写「3 档」）+ **1 条负向对照**（`state.route="licensed"` 时仍给 4 档）。
**注意它是「真花钱真耗时」的**，不要放进每次改动的必跑清单。

⚠️ **写负向对照前必须先把状态复位**：例如验证「抽掉 `liteRefreshBar` 后按钮不切换」，
要先把正文置空 + `render()` 让页面回到等待态，否则按钮停在上一次已经变可点的状态，
**抽不抽掉刷新函数都是 clickable=true** —— 对照测的是残留，不是变异（踩过一次）。

## 前端骨架速查（2026-09-10 现状）

| 项 | 值 |
|---|---|
| 侧边栏 `RAIL` | 4 项同级直达：`素材创建`(0) · `素材库`(4) · `文章生产`(5) · `文章库`(11)；**顶部无标题**（`rail-h` 已删）；**无底部区**（曾加 `.railfoot` 快捷入口，Bryan 2026-09-15 明确要求删除） |
| 窄屏骨架 | `#body{grid-template-columns:minmax(0,1fr)}`；`≤860px` `#rail` 改 `translateX(-100%)` 抽屉 + `#railOverlay` + `#railBtn` 汉堡；`toggleRail()` / `closeRail()`；`≤720px` 栅格塌列；`≤560px` 顶栏隐藏平台名 |
| 全局 Esc | `document.addEventListener('keydown')` 按优先级：`#confirmOv` → `#drawer` → `#rail` |
| 品牌弹窗 | 统一用 `askConfirm({title,body,okText,onOk})` / `confirmOk()` / `closeConfirm()`；**拒绝原生 `confirm()` / `alert()`**（另有 `toast()`） |
| `fns` / `STAGES` | 均 12 项（idx 0–11） |
| 登录角色 | 3 个：`source` / `produce` / `review`，`ROLES` 带 `duty` / `dutyEn` / `caps`（能力短语）；**登录按钮统一 `.rbtn`，无「常用」徽标、无主次**（曾加 `primary` 主按钮，Bryan 明确要求去掉） |
| 覆盖层居中 | `#loginOv` 用 `flex-direction:column` + `.lwrap{margin:auto}`；`display` 由 JS 赋 `flex` |
| 统计卡口径 | 素材库与文章库**同为 5 张**（素材库含「本月新增」→ `__month__` 筛选分支） |
| 文字对比度 | 正文灰用 `--muted:#667085`；**品牌色文字必须用 `--pri-tx:#C2421C` / `--ok-tx`**，`--pri:#E65425` 只给色块与描边 |
| 色变量语义名 | `--tone-1*`（原 `--teal*`）/ `--tone-2*`（原 `--purple*`）/ `--neutral-t:#F2F4F7`。**改名是为了防后人照名字加绿/紫** |
| 校对草稿 | `DRAFT_KEY='wb_para_draft_v1'`；`queueDraftSave()` 700ms 防抖 → `beforeunload` 兜底；`applyLive()` 末尾 `restoreParaDraft()`；指纹 = `material.length + ':' + material.slice(0,80)` |
| 运行进度 | `runPct(est,nodes,nodeEst)` 双因子取大、封顶 96%；`runOverdue(est)` 超 115% 提示；`GEN_EST=150` / `FACT_NODE_EST=9` / `GEN_NODE_EST=21`；`cancelLiveRun()`（`AbortController`，catch 识别 `AbortError`） |
| 4 档视图 | `alignModeBarHTML()` / `setAlignMode('grid'\|'single')` / `alignBodyHTML()`；`alignedViewHTML()` = `bigBarOnce()` + 模式条 + 正文。**判据：`.bigbar` 恒存在，`.bigtab` = `4 − minIdx`；档数/列数/pill 数一律走 `shownKeys()`（lite=3 / 产线=4），别写死 4** |
| 文章库导出 | JSZip CDN（jsdelivr 3.10.1，`exportArticles` 内 `typeof JSZip === "undefined"` 降级 toast）；一篇 = 1 个 zip，内含 `文章.md` + `题目.md`；批量 = 1 个 zip 平铺 2N 文件、标题重名加短 ID。**MD 格式**：文章 `# 标题` → 每档 `# A1/A2/B1/B2` + 段落空行分隔（后端按空行切段、按 `#` 切档）；题目每题「题干 + A/B/C/D + 答案 + 解析」。只对 `artStatus(a)==="approved"` 开放。后续加音频（`a.audio`）/封面（`a.coverDataUrl`）进 zip 即可 |
| 统一返回按钮 | 全站左上角，由 `render()` 注入 `backBarHTML()`；顶层页 `0/4/5/11` 不显示 |
| 返回落点 | `backTarget()` + `goResolve()` 复刻 `go()` 跳步 → 严禁直接写 `go(cur-1)` |
| 侧边栏点击 | `railGo(i)`：`i===0` 时先清 `state.route`，点「素材创建」回到三张入口卡 |
| 素材状态常量 | `MAT_STATUS` / `_ZH` / `_COLORS` 三处已无 `published`，改动须三处同步 |

## 外部服务实测基线

| 服务 | 预期 |
|---|---|
| `GET /api/proxy-health` | 4 个 key 全 `true` |
| SiliconFlow chat | 200，约 3～4s |
| Dify FACT | `status: succeeded`，**约 13s**（2026-09-18 复测），输出含 `summary` / `facts_text` / `gist` / `level`(**4 档：A1/A2/B1/B2**) / `level_lo` / `level_hi` / `info_points` / `sens_level` |
| Dify GEN | `succeeded`，**约 38s**（2026-09-18 复测；旧记录 110～180s 是 12 子档时代，已不适用）。输出 4 档 × **每档 12 段**，`levels_meta` 带展示名（`A1→"A1-"`、`B2→"B2+"`）与 `words`/`paras` |

### 头条原文获取基线（2026-09-14 建立 · 纯 HTTP，不依赖 Chrome）

链路：`/article/<id>` → 移动 JSON，不足 200 字再抓文章页 SSR；`/trending/<id>` → 爬虫 UA 抓 SSR →
限定「事件详情」区块解析。**A2a(SSR) 优先，无头渲染降为 A2b 兜底。**

```python
BOT_UA = "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)"
_TT_BLOCK_RE = re.compile(r'<div class="block-title">([^<]*)</div>', re.I)
_TT_MIN_TEXT = 125   # 低于此不当作正文（视频文案 56–119，最短真实正文 133）
```

话题页的三种结构（**决定能拿到什么，不是抓取运气**）：

| 类型 | 判据 | 实测正文量 | 占比（12 条样本） |
|---|---|---|---|
| 文章型 | 块内 `href="/article/<id>"` | 741–3730 字 | 6 |
| 微头条型 | 块内 `/w/<id>` → 抓 `/w/` 页 `<article>` | 292 字 | 1 |
| 视频型 | 无外链，只有 `/video/<id>` + 短视频文案 | 56–119 字（**不算正文**） | 4 |

要点：
- 解析必须**限定在「事件详情」区块内**（`_tt_event_block`），否则会抓到「网友讨论」/相关推荐里的别篇。
- `fetch()` 支持 `headers=` 且**缓存键带上 UA** —— 同一 URL 换 UA 内容完全不同，不隔离会互相顶掉。
- 话题页一旦解出「事件详情」块，答案即确定 → 置 `_ssr_conclusive`，**跳过 A2b 渲染**
  （否则无 Chrome 环境会白跑并刷误导告警）。
- 降级文案按 `kind` 分型，前端 tooltip 直接说清是「视频型/短文案/未附正文」。

**视频型 = 直接拦截，不纳入热点列表**（2026-09-14 Bryan 拍板）：

```python
TOUTIAO_DROP_VIDEO = True      # 置 False 即恢复「保留并标记 no_source」的旧行为
_TT_DROPPED_VIDEO = []         # 本批拦截台账，由 /api/trends 的 filtered_video 回传
```

判定依据（已实测无解，别再花时间抢救）：视频型块内只有 `/video/<id>`；抓 `/video/<id>` 页
（35–36KB）与移动 JSON，`extract_article_from_dom` **均为 0 字**，meta/description 只是视频标题
+ 样板文（「…发布在今日头条，已经收获了 N 个喜欢」）。**换 URL 救不回来。**

三个必须守住的实现细节：
- **不写错误日志、不置 `degraded`。** `_is_real_degradation()` 对任何非渲染类错误都返回 True ——
  给拦截记 warn 会让整榜挂上「部分信源未抓到」横幅，把主动筛选说成故障，是误导。
- **拦截条目不进 `_health_record`。** `continue` 必须在 `_health_record` **之前** ——
  源成功率要反映「交付内容的质量」，被筛掉的条目不该拉低它。
- **提前 `return` 顺带省钱省时**：跳过该条的「中文源兜底」+ 无头渲染尝试，
  实测整榜 68.5s → 17.6s（本地），线上 68.5s → 36.2s。

**验收口径（2026-09-14 起）**：线上等价环境跑整榜，头条交付条目应**全部有正文**
（ok+short，`no_source` = **0**），`filtered_video` 台账条数与拦截数一致，
`tt_kind` 无 `video` 残留；`source` 里不应出现「中文源兜底」。
注意：拦截后头条条数变少、腾出的槽位会由国际源补上（实测中文占比 15/30 → 13/30），属预期。


### 自定义信源实测基线（2026-09-14 建立 · 本地 + 线上逐源真打）

**链路**：`s1() 表单 → state.user.sources（仅会话内存，未持久化）→ runCustomScan()
→ GET /api/scan?urls=<逗号拼接> → fetch_scan(urls)`，逐源三步：
① `parse_feed()` 仅认 RSS 2.0 `<item>` / Atom `<entry>`（且条目必须**同时**有 title 和 link）
② `discover_rss()` 从 HTML 找 `<link rel="alternate" ... rss/atom/feed>`
③ 兜底：**只取网页 `<title>`**，标 `_degraded`。

**各类链接的真实产出（别凭直觉，这张表是打出来的）**

| 输入形态 | 例子 | 结果 |
|---|---|---|
| RSS/Atom 直链 | `feeds.simplecast.com/54nAGcIl` | ✅ OK-RSS 2975 条（播客） |
| RSS 直链（体育） | `espn.com/espn/rss/news`、`feeds.bbci.co.uk/sport/rss.xml` | ✅ 38 / 77 条 |
| 新闻首页（能自动发现 feed） | `nytimes.com` | ✅ 线上 OK-RSS 20 条 |
| 新闻/垂直站首页（无 feed） | 澎湃 / 人民网 / ChinaDaily / 懂球帝 | ⚠️ 只得到一句网页标题 |
| 播客平台页 | Apple Podcasts / 喜马拉雅专辑页 | ⚠️ 只得到网页标题 |
| YouTube 频道页 | `youtube.com/@TEDEd` | ⚠️ 线上可达、页面**带** autodiscovery RSS，但见下 |
| YouTube 原生 feed | `youtube.com/feeds/videos.xml?channel_id=…` | ❌ **HTTP 404（机房 IP 风控）** |
| 虎扑 首页/版块 | `hupu.com`、`bbs.hupu.com/bxj` | ⚠️ JS 重度渲染，HTML 内无文章链接 |
| 前端预置值 | `gutenberg.org`、`learningenglish.voanews.com` | ❌ 降级 / 超时 |

**四个必须记住的坑**

- **YouTube 的 404 不是 channel_id 错。** 线上抓频道页时后端 `discover_rss()` 读出的 feed URL
  与手工构造的完全一致，但直接请求仍 404 —— 这是**机房 IP 被区别对待**（已知结构性问题）。
  替代端点实测：openrss **404** / piped **降级** / `rsshub.app` 公共实例 **403** /
  **rss-bridge 公共实例 OK-RSS 15 条 ✅**（YouTube 单频道上限就是 15 条）。
  → 要支持 YouTube 必须过桥接层，且公共实例不可靠（生产需自建）；**不能靠通用启发式救**。
- **同一个站在本地与线上可能相反。** 澎湃本地可抓、**线上 403**（反爬按出口 IP 拒）；
  头条则是本地要 Chrome、线上换爬虫 UA 走 SSR。**任何「源能不能用」的结论都必须两边各测一次。**
- **🔴 「本地不通 ≠ 线上不通」，反向也成立 —— 判据只能是线上探针。**
  2026-09-20 实测：**BBC / Guardian / NYT / ABC 在本机全部超时，线上直连却全部 200、正文 3k–60k 字符。**
  原因：本机访问这些站需要代理，而桥接层 `fetch()` 用 `ProxyHandler({})` **显式禁用了系统代理**；
  线上（美国机房）直连即可，不需要代理。
  **2026-09-02 那次只看了本机结果**，把它们判成「源不可用」写进 `FEEDS` 注释、从此没加回来 ——
  代价是 48 个源的清单里当时**一个西方权威大站都没有**（2026-09-20 才纠正）。
  反向例子同样存在：**Reuters / AP 是线上 403、本地超时**。
  判据（**务必单源单独调** —— 这样 `SCAN_ENRICH_LIMIT` 才全给这一个源，看得出真实正文可抓性）：
  ```bash
  curl "$LIVE/api/scan?urls=<url>&limit=4"
  ```
  ⚠️ **整批扫描时大多数源「最长正文 = 0」是限额造成的假象**（`SCAN_ENRICH_LIMIT = 12` 是全批次共享的），
  别据此判源不可用；要看正文可抓性必须一次只传一个源。
  ⚠️ 同理，**付费墙站**（NYT / Forbes / Economist / HBR / WSJ / Inc.）能返回条目但只有 `summary_only`
  （正文 94–203 字符），过不了 `MIN_USABLE_TEXT=200` 闸门 —— 这类要判「可用」而不能只看 `count > 0`。
- **🔴 「源可用」不等于「源有内容」—— 还要看它最后更新是什么时候。**
  2026-09-20 实测四个**停更源**（feed 有效、能抓到条目，但内容陈旧）：
  **人民网 RSS 停更 15 个月**（最新 2025-06-05）· **新华网 RSS 连 `pubDate` 都没有**，内容是 **2022-12 新冠期** ·
  **BBC · Stories 的条目是 1380–1439 天前（近 4 年）** · **TED Blog 最新一条也在 15.9 天前**。
  判据是 `/api/trends` 的 **`filtered_stale`** 台账（每条带 `age_days`）：
  **某个源一次被整批拦掉 = 它已经停更** —— 这是最早、最省事的「源失效」信号，比等老师看到旧闻再反馈早得多。
  ```bash
  curl "$LIVE/api/trends?theme=all&limit=200" | python3 -c "import json,sys;[print(x['age_days'],x['source'],x['title'][:30]) for x in sorted(json.load(sys.stdin)['filtered_stale'],key=lambda y:-y['age_days'])]"
  ```
  ⚠️ **根因别找错**：时效门槛（`TRENDS_MAX_AGE_DAYS = 14`）**一直存在**，坏的是 `parse_ts` 只认 RFC822
  （`parsedate_to_datetime`）—— **Atom 的 ISO8601 和 `2025-06-05` 这类全解析失败返回 `0.0`**，
  而过滤写成 `if (not ts) or (now - ts <= 14d)` → **`0.0` 被当「无法判定」直接放行**
  ⇒ 这些源的时效过滤**一直完全失效**。
  **教训：「解析不出来」既不等于「源没给日期」，更不等于「放行」。**
  验收：`parse_ts("2025-06-05")` 必须 > 0；整榜「超过 14 天的条目」必须为 0。

**列表页抽取的上限（改造前的兜底就是上限所在）**

用通用启发式（同域 `<a>` + 锚文本 12–80 字）从首页抽候选，实测：
ChinaDaily **99** / 懂球帝 **29**（体育场景） / 人民网 **12** / 澎湃 **9** 条真标题；
虎扑抽到 49 条但全是「版块名 + 发帖数」（**假阳性**，页面 JS 渲染）。
另：`people.com.cn/rss/politics.xml` **100 条**、`xinhuanet.com/english/rss/worldrss.xml` **20 条** ——
喂对 feed 地址质量极高，但**用户不会知道要去哪找 feed 地址**。

### 冷启动缓存告警对齐原则（2026-09-14）

`_TR_CACHE_FILE` / `_TAG_CACHE_FILE` 这类**冷启动即不存在**的缓存，加载函数必须前置
`if not os.path.exists(...): return {}`，**不能靠 try/except 兜**：否则部署重建容器后首批次
会记 warn → `_is_real_degradation()` 判 True → 前端误挂「部分信源未抓到」横幅（实际 0 源失败）。
改的时候**保住可观测性**：文件存在但 JSON 损坏 / 权限问题时必须**照常告警**，
别把异常一起静默掉。验收三场景：不存在（0 条）/ 损坏（必告警）/ 对照 `_load_tag_cache`（0 条）。

**自定义信源至今的 5 处交付缺口（未修，动这块前先看）**
① 卡片点击 `state.hot = HOTS.length + i` **越界**，而 `curHot()` 读 `HOTS[state.hot]` → 返回 null
  → **点进去选不中、无法作为素材**（真实热点走的是 `pickRealHot(h)`）；
② `runCustomScan()` 映射丢 `url`/`summary`/用户标签（tag 被硬编码成「真实抓取」）；
③ 后端 `fetch_scan()` 里 `heat=60`/`srcs=1` 硬编码 → 界面「热度」「信源」是**假数据**；
④ `/api/scan` 无 `limit`（播客 RSS 实测 2975 条会全量渲染成卡片）；
⑤ 用户填的源名称未回传，后端用 `host_of(u)` 顶替。


### 前端 ↔ Dify 入参契约（2026-09-14 修正后的**正确形态**）

```js
// FACT —— start 入参：material(必填) / style。⚠️ 不要传 level
{ material: material.slice(0, 4800), style: state.style || "default" }

// GEN —— start 入参
{ summary, facts_text, angle,
  level: nkDisp(fc.level || state.lvl),   // 必须点式（select 枚举）
  style,
  gist: fc.gist || "",                    // ← 低档 A1/A2 的去数字大意拍基准，别漏
  facts_raw,
  avoid_words }                           // ← 2026-09-20 新增，见下
```

**`avoid_words`（2026-09-20 新增）** —— 超纲词回灌，治「产出难度偏高」的那一环。

```js
// 每轮重试时按档打包，只含超标的档；上限 20 词/档
avoid_words: JSON.stringify({ A1: ["medal","athlete"], A2: [...], ... })
```

🔴 **三个必须知道的前提，否则改坏**：

1. **`wfInputs` 必须在重试循环「内」构造**。
   2026-09-20 之前它在循环**外**算一次（原 `index.html:2662`）—— 三次重试传的入参
   **一字未改**，纯粹重掷骰子，白花约 150 秒。这是「校验在跑却没效果」的根因。
2. **必须分档**。各档 cap 不同，同一个词在 A1- 超纲但在 B2+ 未必。
   合成一份会把低档限制强加给高档，把高档次写简单。
3. **先推 Dify 图再上前端**。GEN 的 `nodeStart` 没声明 `avoid_words` 时前端传了它有报错风险。
   改图用 `readpal/tools/patch_gen_graph.py`（幂等）。反过来（图先改前端没跟）只是入参为空，无害。

**词表由后端给，前端不要自己筛**：`/api/vocab-check` 的返回值里每档带 `avoid_words`
（`backend/evp_vocab_check.py::pick_avoid_words()` 已剔除功能词 + 范文基线词，
详见 `readpal-dify-workflow` 技能）。
前端只做打包：`collectAvoidWords(v)` → 只收 `r.exceed` 为真的档。

> **`gist` 不能漏**：GEN 的 `nodeClean` 有兜底 `gist || facts_text`，
> 所以漏传**不会报错**，只会静默把低档基准从「去数字大意拍」换成完整事实卡。
> 实测代价（同素材同模型，唯一变量 = gist）：A1.2 119→149 词、A1.3 134→180 词、
> B2+.3 665→915 词；校验硬失败 3 个→0 个；低档 `gist_map` 只引用到第 4 条→1–8 条。
> ⇒ **这是「不报错的静默退化」，最难发现的一类。**
>
> **GEN 的 `level` 其实是装饰件**：全图检索 `nodeClean.level` / `nodeClean.level_big` /
> `nodeStart.level` 均 **0 次引用**。真正被消费的是 `nodeClean.gist`（→ nodeGenA1/A2/GistCheck）
> 和 `nodeClean.facts_text`（→ nodeGenB1/B2p）。保留传值只为字段语义；
> 想彻底免掉这类 400，把 `level` 也一起省掉即可（一行）。

> ⚠️ **2026-09-10 起 LLM 渠道已切到硅基流动**（DeepSeek 官方余额耗尽，402 Insufficient Balance）。
> 两个工作流的 **9 个 LLM 节点全部**是
> `langgenius/siliconflow/siliconflow` / `deepseek-ai/DeepSeek-V4-Flash`。
> （2026-09-09 那句「走 DeepSeek 官方、SF 没有该系列」**已过期**，SF 现在有 `deepseek-ai/DeepSeek-V4-Flash` / `-Pro`。）
>
> 🔴 **改 Dify LLM 参数时最容易踩的坑**：思考开关的参数名是 **`enable_thinking`**（boolean，默认 false）。
> 写成 `thinking` 会被 Dify **静默丢弃** → 模型按 SF 默认开思考 → 实测**慢 6.75 倍、token 多 20 倍**
> （400 词长文：54.0s/10641 tokens vs 8.0s/533 tokens）。
> 症状极具迷惑性：**service API 返回 200 但 SSE 几分钟零字节**，看起来像"网络问题/Dify 挂了"。
> 查插件支持的参数名（只读一条命令）：
> `GET /console/api/workspaces/current/model-providers/langgenius/siliconflow/siliconflow/models/parameter-rules?model=<模型名>`
>
> 🔴 **GEN 必须用 `response_mode: "streaming"`**：Dify 网关对 `blocking` 有约 120s 硬超时
> （GEN 早期 145s 时实测直接 **504 静默失败**）。前端已改 SSE，并按 `node_finished` 事件显示节点进度。

### 如何调用 Dify（**2026-09-16 已改为桥接层同源代理**）

前端统一走 `difyCall(wf, inputs, user, signal)`（`wf` ∈ `fact` / `gen` / `main`）：

```js
1) 首选 POST {AGENT_REACH_API}/api/dify/workflows/run   body: { wf, inputs, response_mode:"blocking", user }
2) 代理不可达或失败 → 回退直连 https://api.dify.ai/v1/workflows/run（带 AIWF_*.appKey）
```

> 🔴 **为什么改**：浏览器直连 `api.dify.ai` 会偶发 `Failed to fetch`
> （Dify 的 UA / 频率风控 + 网络抖动）。走同源代理稳定得多，且密钥不出浏览器。
> 三个 `AIWF` 常量**仍保留**（作为回退分支用），不是死代码了。
> 代理报 `missing upstream api key` 时，是 Railway 环境变量缺 `DIFY_WF_*`，不是密钥失效。
>
> 🔴 **Railway 变量编辑是「暂存」的**：改完左上角会出现 `Apply N changes`，**不点就不生效** ——
> 页面显示变量值已填好、但运行中的容器读到的仍是旧环境（2026-09-23 卡在这里：截图里值清清楚楚，线上却是空串）。
> 排查顺序：① 点 Apply / 看 Deployments 有没有新条目 → ② 变量名逐字符比对（大小写/首尾空格）
> → ③ 确认加在当前 service + 当前 environment → ④ `node tools/read_live_config.mjs` 复验。

**探测通路是否正常**：用空 inputs 打工作流，拿到 `400 invalid_param` 就说明**通路 + key 都正常**。

```python
import json, urllib.request, urllib.error
k = json.load(open('backend/keys.fallback.json'))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
body = json.dumps({"inputs":{},"response_mode":"blocking","user":"probe"}).encode()
req = urllib.request.Request("https://api.dify.ai/v1/workflows/run", data=body,
    headers={"Authorization":"Bearer "+k["DIFY_WF_FACT"],"Content-Type":"application/json","User-Agent":UA})
try: urllib.request.urlopen(req, timeout=30)
except urllib.error.HTTPError as e: print(e.code, e.read().decode())
# 期望：400 {"code":"invalid_param","message":"material is required in input form"}
```

> ⚠️ **裸测必须带浏览器 UA**。Python 默认 UA 会被 Dify 的 Cloudflare 拦下，返回
> `403 error code: 1010`，**极易误判成"密钥失效"**。后端 `_proxy_post()` 早已统一 UA。

### 如何读飞书文档（lark-cli · 2026-09-10 打通）

需求方常把标准/规则写在飞书 wiki 里。`WebFetch` 打不开（跳登录页）。正确姿势：

```bash
export PATH="$HOME/.workbuddy/binaries/node/cli-connector-packages/bin:$PATH"
# 1) 解析 wiki 节点 → 拿 obj_token（必须用 --as bot）
lark-cli wiki +node-get --node-token "<飞书URL>" --as bot
#    → {"title":"...","obj_token":"Zoz...","obj_type":"docx"}
# 2) 读正文
lark-cli api GET /open-apis/docx/v1/documents/<obj_token>/raw_content --as bot --jq '.data.content'
```

- **`--as bot` 是关键**：user 身份 token 只授了 `docx:*`，**没有 `wiki:*`**，用 user 会报
  `missing_scope: wiki:node:retrieve`；bot 身份反而能解析 wiki 节点。
- `LARK_CLI_NO_PROXY_WARN=1` 可静音代理告警。

---

## 分级体系：4 档（**2026-09-15 起现行** · 真源 = 飞书《APP阅读级别量化表》）

> 🔴 **2026-09-15 已把 12 子档收敛为 4 档**（提交 `27b29625566a` → `bce8e4835bb3`）。
> 旧的 `A1.1 / A2.3 / B2+.2` 这套 12 子档**已作废**，不要再按子档写代码。

```
A1（展示名 A1-）   A2        B1        B2（展示名 B2+）
```

- 常量仍是 `LEVELS12`（**名字没改，内容已换成 4 项**），key = `A1`/`A2`/`B1`/`B2`：
  ```js
  const LEVELS12 = [
    { key:"A1", d:"A1-", big:"A1" }, { key:"A2", d:"A2", big:"A2" },
    { key:"B1", d:"B1", big:"B1" },  { key:"B2", d:"B2+", big:"B2" },
  ];
  ```
- **`nkKey()` 仍做旧写法兼容**：`A1.1` / `A1-1` / `A1_1` / `B2+.1` / `B2P_1` / `b2p3`
  → 统一收敛到 `A1` / `A2` / `B1` / `B2`。展示名用 `nkDisp()`（得到 `A1-` / `B2+`），
  **业务代码里不要手写档位字符串**。
- ⚠️ **Dify 工作流图里仍是点式**（`gen.new.json` 里 `A1.1` 出现 19 次、`B2+.3` 25 次），
  靠前端 `nkKey`/`nkDisp` 映射，**不是后端漏改**。改动时别把两边都当点式或都当 4 档。
- 段落数**不再由前端 `nodeAgg` 强制同组一致**（子档概念消失）；段数以生成结果为准，
  展示在 `bigbar` 的计数徽标（如「B1 中级 · 7 段」）。`bigBarOnce()` 是「一页只渲染一条」的闸门，
  挪位置要在目标位置先调一次占位（详见下文「前端分档视图」）。
- 前端真源：`BIG_GROUPS`（档位定义）/ `LEVELS12`（4 档 key）。`bigBarHTML()` 是档位切换条（`setBig()`）。
  ⚠️ `nodeAgg` / `subKeys` 等「子档」概念的旧函数**已删除**（0 引用）——
  遇到讲「组内统一段数」的旧文档直接跳过，那是 12 子档时代的规则。
- GEN 输出契约（关键 7 个）：
  `articles_json` `paras_json` `words_json` `levels_meta` `quiz_json` `fact_map` `validation_json`；
  过渡期兼容别名 `article_a2/b1/b2`、`paras_a2/b1/b2` **只做兜底**。
- 每档 3 题，4 类题型 `language` / `text` / `logic` / `cognitive` 按档递进配比（**题数由 Dify 源头锁死为 3，前端不再截断**）。
- 蓝思是**生成时的硬约束**（写进提示词 + 校验节点判定，用估算公式、非官方 MetaMetrics 值）。

### Dify 工作流工具链（`readpal/tools/`，2026-09-10/11 新增）

| 工具 | 作用 |
|---|---|
| `dify_cdp.mjs` | attach 已登录的 Dify 控制台会话（`--eval` / `--text` / `--shot` / `--goto`） |
| `dify_push_graph.mjs` | `--app=<id> --graph=<json> [--dry]`：读 hash → 带 hash POST → 回读校验 |
| `dify_run_draft.mjs` | `--app --inputs=<json>`：跑 **draft**（不影响线上），解析 SSE 打印逐节点耗时 |
| `dify_publish.mjs` | `--app [--check] [--note=]`：把 draft 发布为线上版本；`--check` 只读比对 |
| `dify_kb_upload.mjs` | 往知识库灌文件（走 UI 的上传向导，自动塞 file input） |

**关键常量**：FACT `12e8c26d-cbcc-43c2-94bb-20926226cb3d`、
GEN `f4462032-2919-49e0-b123-bb5160c96c28`（MAIN `466e1815-…` 是死资产）；
知识库「分级标准」`79cb2c5c-66f5-41d1-934f-ce0678a49d0b`、敏感规则 `30d28341-8da6-42b5-a07a-71debda87081`。

**控制台 API 鉴权**：cookie `__Host-csrf_token`（`decodeURIComponent` 后放 `X-CSRF-Token` 头）。
**401「Invalid Authorization token」十有八九是漏了这个头**，不是登录过期 —— 别急着重登。
页面长时间不刷新会丢 token，`--goto` 重新加载即可恢复。

> ⚠️ `grep` 在 `frontend/index.html` 上会**静默返回空**（疑似编码/locale 问题），
> 必须用内置的 Grep 工具检索这个文件。

---

## 定制热点 / 自定义信源（2026-09-14 · 步 1 已上线）

方案文档 `readpal/docs/27`、`docs/28`（§8 步 1 落地记录）。**改这条链路前先读 docs/28 §8。**

### 🔴 交付配比：今日头条优先 / CGTN 30% / 其余补齐（2026-09-23 · 改 `fetch_trends` 前必看）

**真源**：`agent_reach_bridge.py` 的 `TRENDS_QUOTA` + `trend_group()` + `_pick_by_quota()`。

| 常量 | 值 | 为什么是这个值 |
|---|---|---|
| `TRENDS_QUOTA` | `{"toutiao":0.50,"cgtn":0.30}` | 其余 = 剩下的 20%，不单独配 |
| `TOUTIAO_HOTBOARD_LIMIT` | 50 | 头条热榜**总共只有 50 条**，全量取回才谈得上 ~32 条可用 |
| `TOUTIAO_FETCH_WORKERS` | 8 | A1(文章 JSON)/A2a(话题页 SSR) 都是纯 HTTP，串行 50 条实测 48s → 并发 16s |
| `CGTN_PER_SOURCE_LIMIT` | 12 | CGTN 只有 5 个栏目源，套用 `PER_SOURCE_LIMIT=4` 最多凑 20 条 < 36 条配额 |
| `QUOTA_POOL_FACTOR` | 1.35 | 候选池冗余；取 1.5 时首次耗时逼近 100s（超前端「约 50–90 秒」文案） |

**三条硬约束，缺一条配比就落不了地：**

1. **按源截断的上限必须按分组给**（`_SRC_CAP`）。`PER_SOURCE_LIMIT=4` 是为 40+ 个来源做的
   多样性保护，一并套给头条/CGTN 会**当场把自己的配额卡死** —— 实测头条被压到 8 条、
   CGTN 20 条，**配比改成多少都看不出效果**（这是改之前头条只占 7% 的真凶）。
2. **配额只能在「无可用正文筛选之后」施加**。提前到排序截断那一步，后面被无正文闸门筛掉的份额
   会凭空消失，最终比例必然漂掉。所以是两阶段：放大候选池 → 补正文 → 筛 → `_pick_by_quota()` 精挑。
3. **分组判据是信源前缀，不是内容类别** —— 一篇文章讲什么跟它由谁发布无关。
   头条条目的 `source` 会被补正文改写成「今日头条 · 各家媒体」，所以必须
   `startswith("今日头条")` 而非等值比较。

**头条做不到 50%，这是硬天花板**（Bryan 已知情，拍板「保总数 120 条」）：
热榜 50 条 → 拦掉视频型 + 无正文后实测 **32~33 条**。
缺的份额全部由「其余」补 —— **绝不拿别的源冒充头条，也不为了比例好看把列表截短**（那是拿假供给骗人）。

**块顺序 = 界面顺序**：头条块 → CGTN 块 → 其余块。前端 `state.realHots.filter(hasUsableText)`
**只过滤不重排**，所以后端返回什么顺序，老师就看到什么顺序。CGTN 块内走 `_round_robin()` 轮转，
让 5 个栏目交替出现（实测 8/7/7/7/7），而不是同一栏目连排十几条。

**实测（2026-09-23，limit=120）**：改前 8/18/81 条（7%/17%/76%）→ 改后 33/36/51 条（28%/30%/42%）。
CGTN 精确 30%。耗时：首次（清缓存）~120s / 命中缓存 ~54s。
旧的 `SOURCE_BOOST={"CGTN":10}` heat 加权已随配额制撤掉（硬配额下它只会影响组内顺序，等于失效）。

### 交付链路上有一条隐形闸门：`hasUsableText`

前端 `hasUsableText(h)` = `fulltext_len >= 200`。`pickRealHot()` 第一件事就是查它，
**不达标就弹「请粘贴原文」并中止**（不进生成流程）。

> 含义：**后端接口不给正文，卡片就是点不动的**。
> `/api/scan` 原先只回 RSS 级标题+摘要 → 每次点卡片都被拦。
> 改任何"热点/素材来源"接口（scan / trends / 未来的 GDELT 检索）时，
> **必须保证条目带 `fulltext` + `fulltext_len` + `fulltext_status`**，
> 否则老师会看到"有卡片但一步也走不到生成"。

两种正确做法：
- 复用 `enrich_fulltext(items, workers=8, timeout=N)`（就地写 `fulltext*` 四个字段，有磁盘缓存）；
- 或如实标 `fulltext_status = "summary_only"` 并留 `summary` 兜底 —— **不要谎报「无原文」**
  （`no_source` / `failed` 在界面上是红标"无原文"，会让人以为源坏了）。

### 后端正文抽取：别取第一个 `<article>`

`extract_main_text()` 原先 `re.search(r"<article…>(.*?)</article>")` 只取**第一个**匹配，
而新闻页常把「相关推荐」小卡放在前面 —— 实测 ESPN 首个 `<article>` 仅 **165 字符**、正文在第二个 **6141 字符**，
于是抽到空壳 → `fetch_article` 误报 `failed`（状态是 `failed`，但站点其实好得很）。
**改法：取最长的 `<article>`，且容器内无达标段落时回退整页。**

诊断口诀：先在 HTML 上数 `len(re.findall(r"<article", html))` 与每个匹配的长度，
**"抽不到正文"先分清是「站点不给」还是「我们取错容器」**。

### 🔴 正文里的 HTML 实体必须走标准库 `html.unescape`，别硬编码替换（2026-09-20）

**症状**：素材正文里出现 `&#x27;` `&#8217;` `&rsquo;` `&mdash;` 这类字面量，一路带进生成环节。

**根因**：`clean_html()` 原先只硬编码替换 **5 个命名实体**
（`&nbsp; &amp; &lt; &gt; &quot;`），漏掉两类：
- **数字实体** —— `&#x27;`(单引号) `&#8217;`(右单引号) `&#8220;/&#8221;`(弯引号) `&#34;` `&#8212;`
  `&#8234;/&#8236;`(bidi 控制符) …… **英国媒体（BBC 系）正文 HTML 主要用这种**；
- **其它命名实体** —— `&rsquo;` `&mdash;` `&ldquo;` `&aacute;` `&hellip;` ……

**范围不是某个源**：线上实测 **180 条里 79 条（44%）带残留，涉及 27 个源**
（BBC 9 个栏目 / Global News / Billboard / CNBC / ABC / Live Science / Mindful / Entrepreneur / 今日头条 …）。
`topic` / `cn` / `summary` 干净（走 XML 解析器，实体已被解码），**只有 `fulltext` 脏** ——
因为它是从原站 HTML 自己剥标签抽的。

**改法**（三处，缺一不可）：
1. `clean_html()` 用 `_htmllib.unescape()` —— 覆盖 2000+ 命名实体 + 全部数字实体，
   是原来那 5 条的**超集**（向后兼容）。
2. ⚠️ **导入必须用别名 `import html as _htmllib`**：本文件里 `html` 是**局部变量名**
   （`fetch_article()` 的 `html = data.decode(...)`、`extract_main_text(html)` / `extract_title(html)` 的形参），
   直接 `import html` 会被局部 str 遮蔽 → `AttributeError`。
3. **顺序必须是「先剥标签、再反转义」**：倒过来 `&lt;script&gt;` 会先变成真标签被连内容吃掉。
   且**只解一次**（`&amp;lt;` 原意是显示字面量 `&lt;`，反复解会错变成 `<`）。

**顺带清掉不可见控制字符**（`_CTRL_RE`）：`&#8234;` 反转义后是 U+202A 这类 bidi 控制符，
还有 U+00AD 软连字符、U+200B–200F 零宽、U+FEFF —— 肉眼看不见，只会在模型输入里悄悄占 token。

**🔴 只修 `clean_html` 不够 —— 磁盘缓存必须自愈。**
`backend/.article_cache.json` 存的是**已抽取好的纯文本**，而 `fetch_article()` 命中缓存时
**直接返回 `hit["text"]`，不会再走 `clean_html`** ⇒ 历史乱码会一直吐出来，看起来像「修了没用」。
做在 `_load_article_cache()` 首次加载时清洗 + 回写：
- 用**只解实体、不剥标签**的 `unescape_entities()`（缓存里已无标签，去标签正则反而会误伤 `less than 5 < 10`）。
- `text` 变了必须**同步 `len` 字段**（下游用它显示长度、判 `fulltext_status`）。
- ⚠️ **回写必须在锁外**：`_article_cache_lock` 是不可重入的 `threading.Lock`，
  锁内调 `_save_article_cache()` 会死锁。

**验收判据**：`/api/trends` 返回里 `fulltext` / `topic` / `cn` / `summary` 四个字段
正则 `&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]{1,9});` **命中数必须为 0**。

**另注**：此坑的教训与 `parse_ts`（见「四个必须记住的坑」第 4 条）同构 ——
**都是「手写枚举」扛不住格式多样性**。凡是解析外部格式，优先用标准库，别自己列清单。

### `renderHots()` 的卡片是错峰出来的 —— CDP 探针最容易在这里误判

```js
setTimeout(()=>{ …g.appendChild(d); }, 110*i);   // 30 张卡 → 最后一张 3.3 秒后才进 DOM
```

因此：

- **`render()` / `runCustomScan()` 刚 resolve 时，`#hotgrid` 里必然是 0 张卡。**
  探针必须等 **≥ `110 × 条数` ms** 再数，否则会把正常渲染误判成"渲染坏了"。
- 正例参考：`state.customHots` 20 条 → 等 3.5s 后应恰好 20 张 `.hotcard.custom`。
- **点完卡片会 `cur=2` 跳页，`#hotgrid` 随即不在 DOM** —— 跳页后再数格子的结果无意义
  （本轮因此白查了两轮，`cardsDuringScan: 0` 其实是这个原因）。

### 🔴 编辑类回调「改到哪」—— 定位属性在**卡片**上，不在正文上（2026-09-20 事故）

段落正文用 `contenteditable`，回调 `paraEdit(this)` 收到的 `this` 是 `.pbody`，
但定位属性挂在父级 **`.pcard`** 上：

```html
<div class="pcard" data-k="A1" data-i="0">                            <!-- 属性在这 -->
  <div class="pbody" contenteditable oninput="paraEdit(this)">…</div>  <!-- this 在这 -->
</div>
```

`el.getAttribute("data-k")` → `null` → `GEN[null]` 是 `undefined` → **第二行静默 return**，
改动从未被记录。

**为什么这是最阴的一类 bug**：`contenteditable` 是浏览器原生行为，**字确实变了**；
连段落词数徽标都会刷新（那行用的是 `el.closest(".pcard")`，写对了）。
界面因此给出「改成功了」的假信号，而 **内存 GEN / 本机草稿 / 存入文章库 / 审核页四处全是原文**，
全程零报错 —— 只有走到下游才暴露。静态读代码完全看不出问题。

**判据（必须逐项验证，光看输入框里的字不算验证）**：
① 内存 `GEN[k].paras[i]` 确实变了；② 草稿 `wb_para_draft_v1` 落盘且内容一致；
③ 逐段审核页（idx 10）显示编辑后、**不含**原文；④ `buildBankArticle()` 的
`paras` 与 `articles` 都含编辑、不含原文。

**回归探针**：`node tools/probe_para_edit.mjs`（19 项断言，自带 Chrome + CDP，本地/线上同一份；
其中 ⑧ 是**负向**断言 —— 故意删掉卡片的 `data-k` 制造异常态，要求必须 `console.error` + toast，
**且不写入半成品**。这条才是「以后不能再白改」的真正保证：修复目标不是「碰巧能改」，
而是「一旦改不动，用户立刻知道」）
```bash
cd <repo> && node tools/probe_para_edit.mjs                                   # 本地 8899
URL_=https://web-production-2a16e.up.railway.app/ node tools/probe_para_edit.mjs
```
> 已做过**旧代码对照**：把 `paraEdit` 回退成旧写法跑同一份探针 → **11 项失败**，
> 失败项正好指向「内存没变 / 草稿没落 / 审核显示原文 / 入库是原文」。
> ⚠️ 其中「词数徽标已刷新」在**旧代码下也是 ✓** —— 这正是它最阴的地方。

通用教训：**编辑类回调「落到哪」必须有断言，取不到宁可报错也不能静默返回。**
静默失败的代价是「用户以为改好了」，比直接报错严重得多。
（同族的还有 `runGeneration()` 的 TDZ —— 抛错被 `catch` 吞成「没反应」。）

### 🔴 事实卡人工编辑层（2026-09-23 · 改 `liveFacts` / `curFacts` / `s4` / `factsSyncToCache` 前必看）

需求（Bryan）：热点搜集的**事实分段抽完卡之后，教研要能就地改、删事实卡**。

**只改界面 = 改了没用**。GEN 真正吃的是 `state.factsCache` 里的三样东西：

| GEN 入参 | 谁在用 | 编辑后必须同步 |
|---|---|---|
| `gist` / `gist_lines` | A1 / A2 低档的段落骨架 | 不改（事实卡不涉及） |
| `facts_text` | 骨架兜底（`facts_raw` 缺失时） | ✅ `"N. <en>"` 逐行重建 |
| `facts_raw.facts[].en` | **B1 / B2+ 高档素材的真源** —— GEN 的 `nodeClean.buildGistSkeleton` 逐条读它现拼 | ✅ 必须回写 |

设计（三条硬约束，少一条就是静默失败）：

1. **编辑层是事实卡的唯一真源**：`liveFacts()` 优先返回 `state.factsEdit`，
   于是事实卡渲染、`factCiteHTML`（段落下方 F1/F2 引用标签）、s6 溯源面板一并生效 ——
   **只加一层渲染分支、不动 `liveFacts()` 的话，另外两处会继续显示旧事实**。
2. **编辑层与 `liveOut().facts_json` 同源同命**：`liveFacts()` 里必须带
   `if(state.factsEdit && o && o.facts_json)` 这个门。否则 `state.live` 被清空
   （换素材 / 切入口 / 打开文章库）后，编辑层会把**上一批的卡冒充成当前素材的事实卡**。
   另在 `startLiveRun()` 开跑时清 `factsEdit/factsEditOrig/factsDirty`（新一批卡不能套旧一批的改动）。
3. **删卡会让 1-based 编号整体前移** → 已产出的 `fact_map` / `unused_facts` 立刻失准，
   必须清掉（`factMap=null; unusedFacts=[]`）并置脏。**错的溯源比没有溯源更坏** ——
   校对页会继续按旧编号标「被引用 P1」。

三个易错点：

- **`gist` 归属号只存在于 `facts_raw`，`facts_json` 里没有**。编辑层每条要带 `gi`（从
  `facts_raw.facts[i].gist` 搬），回写时按 `gi` 重建；**不能按下标 `facts_raw.facts[i] = ed[i]`** ——
  删过卡之后下标已错位，会把细节挂到错的大意上（对应探针里「gist 不串位」那条断言）。
- **「是否被人工改过」要用 `oid`（AI 原稿下标）认身份，不能比位置**：删卡后下标前移，
  按位置比会把**没改过**的卡全标成「人工修订」。
- 改过的卡不能再显示 `AUTO` + 置信度（那是 AI 的产出），改显「人工修订」徽标；
  同理删掉 `senref`（锚点/交叉验证已不成立）——**别让人以为人改的东西是 AI 判的**。

#### 新增事实卡（2026-09-23 · Bryan：把一条过长的事实拆成两条）

入口 = 每张卡操作区的 `编辑 / ＋新增 / 删除`，`factInsertAfter(i)` 在**该卡后面**插入一张空卡。

🔴 两个都不能省的约束：

1. **新卡必须继承原卡的 `gi`（gist 归属号）**。GEN 侧 `nodeClean.buildGistSkeleton` 是
   `parseInt(f && f.gist, 10)` 把每张卡挂到第 N 条大意下，**NaN 不匹配任何大意** ⇒
   该卡既不进 `gist_fact_map`、也进不了高档「细节池」—— 界面上加得进去、生成时**被静默丢弃**。
   追加到列表末尾而不继承就是这下场。而本功能的真实用途是「拆一条过长的事实」，
   拆出来的两半本来就该挂在同一条大意下 ⇒ 继承即正确。
2. **插在中间 ⇒ 它后面所有编号 +1** ⇒ `factMap` / `unusedFacts` 作废。
   但**只在保存成功时清**（`factEditSave` 里看 `wasNew`）；不能在插入时就清 ——
   点了新增又取消，会把本来正确的溯源白清掉。

空卡清理（不清就会多出一条空事实、后面编号全错位）：

- `factsSyncToCache()` **只回写有内容的卡**（`filter(f => f.en || f.zh)`）—— 最后一道闸门；
- `_factCloseEditing()`：收编辑态时，若这张新卡还空着就 `splice` 掉；
- `factEditStart` / `factDelete` / `factInsertAfter` **都要先调它**，且必须
  **先抓 `target` 引用、再收、再用 `indexOf(target)` 重新定位** ——
  收的过程会摘掉空卡、下标会整体前移，直接沿用旧 `i` 会删错/编辑错一张卡。
- 新卡用 `isNew` 标记，**不能靠 `factIsEdited`**：新卡没有 AI 原稿，
  `factsEditOrig[oid]` 取不到，认不出来 → 徽标会错标成「人工修订」、meta 行会退回显示 `AUTO`。

**边界**：
- 编辑/删除入口只在 `hasLive && !running` 时给（兜底态是按句拆出来的假卡，改了没有下游可写）；
- 至少保留 1 张卡（删光 = 高档无米下锅，静默产出残次文章）；
- 已产出文章后再改卡 → `factsDirty` 置脏，s4 露黄条「已生成的文章不会自动更新」；
  `runGeneration` 成功一轮后自动清脏。

**回归探针**：`node tools/probe_fact_edit.mjs`（33 项，含负向对照）
```bash
cd frontend && python3 -m http.server 8899 --bind 127.0.0.1   # 另开终端
node tools/probe_fact_edit.mjs --url=http://127.0.0.1:8899/index.html --port=9250
```
> 负向对照已验证过灵敏度：把两处 `factsSyncToCache()` 调用去掉重跑 → **5 条「下游入参」断言全红**，
> 而所有界面断言照旧全绿 —— **这正是「只在渲染层叠加」的 bug 形态**，肉眼绝对看不出来。
> 写这类探针时，**「界面变了」和「入参变了」必须分成两组断言**，只测前者等于没测。
> 第二组对照（新增事实卡）：把 `gi: target.gi` 去掉重跑 → **只有「继承 gist」那 1 条红**（32/33）。
>
> ⚠️ 两个写探针的坑：
> - **转义层级**：`SETUP` 是 JS 模板串，里面必须写 `split("\\n")`。写成 `"\n"` 会被 Node
>   先展开成**真实换行**塞进字符串 → 浏览器侧 `SyntaxError: Invalid or unexpected token`。
>   症状是「探针一启动就报语法错、一条断言都没跑」，不是断言失败。
>   判别法：`node --check` 通过、但 CDP evaluate 报错 ⇒ 错的是**拼出来的那段代码**，不是文件本身。
> - **断言基准要算清**：连续两次「新增」时，第二次的基准是「第一次已保存后的状态」而非初始状态
>   （取消后应回到 `ai.n + 1`，不是 `ai.n`）。本探针就写错过一次，表现是**代码明明对、断言却红**。
>   看到断言红先怀疑自己的口径，但**必须先实测再下结论** —— 当时是用临时 CDP 脚本打印
>   `factEditIdx / isNew / editLen / gi` 才定案的，没有靠读代码猜。

### 「界面内容凭空消失」类问题的查法

不要只看最终态。**给目标函数打桩，记录每次调用时进出 DOM 的计数与关键 state**：

```js
const _orig = window.renderHots;
window.renderHots = function(){
  const g = document.getElementById("hotgrid");
  log.push("in grid=" + (g?g.children.length:-1) + " stamp=" + (g?g.dataset.custStamp:"-"));
  const r = _orig.apply(this, arguments);
  log.push("out custom=" + document.querySelectorAll("#hotgrid .hotcard.custom").length);
  return r;
};
```

本轮就是这样定出「`scanTimer` 每秒调 `renderHots`，扫描中分支每次重置 `#hotgrid`，
把自定义卡片一起清空」这个每秒一次的静默失败。

> ⚠️ 打桩**只能拦住 `window.renderHots`**。`render()` 内部若按词法名直接调用，
> 桩不会触发（log 里会出现时间空档）—— 有空档不等于"没调用"。

### 播客/自定义源的配额

`SCAN_PER_SOURCE_LIMIT = 20`（每源上限，播客类 RSS 实测单源 2975 条）、
`SCAN_ENRICH_LIMIT = 12` / `SCAN_ENRICH_TIMEOUT = 10`（扫描是同步等的交互，补正文必须限量）。
**调大前先算一遍最坏等待**：`ceil(n / 8) × timeout`。

---

## 热点列表的产品不变式：列表 = 可交付（2026-09-14 定）

**规则**：热点列表里能看到的每一条，点进去就必须能直接进入生成流程。
「无可用正文」的条目（抓不到正文 / 正文短于阈值 / 视频型）**一律不出现在列表里**。

判据常量：前端 `MIN_USABLE_TEXT` 与后端 `MIN_USABLE_TEXT` **必须同值**（当前 200）——
它就是 `hasUsableText()` 的闸门。**改一边必须改另一边**，否则会出现
「后端放行、前端弹粘贴」或反向的错位。

后端在 `fetch_trends` 里统一筛，位置**必须在 `enrich_fulltext` 之后、翻译之前**：
先补正文才判得准；放在翻译前能省掉给即将丢弃的条目做中英互译。
前端 `renderHots` / `renderCustomHots` 再兜一层。

被筛条目要走台账随响应回传（`filtered_no_text`），前端横幅写明
「已隐藏 N 条无可用原文的热点」——**条数对不上必须解释**，否则会被当成抓取坏了。

> ⚠️ **别再用「特例判定」拦不可交付内容。** 本轮的真根因是：后端只拦了「视频型」
> （`TOUTIAO_DROP_VIDEO`），而用户报的那条没被识别成视频
> （`_tt_event_block` 没解出「事件详情」块 → `kind="none"` → 渲染兜底跳过 → 中文源兜底失败 → `no_source`），
> 于是照样占位。**按「有没有可用正文」统一收口，比枚举特例可靠。**

### `HOTS` 是内置演示数据，绝不能冒充真实结果

前端有一份 `HOTS` 常量 = **20 条 2026 年 8 月的硬编码新闻**（原型期假数据）。
`state.realHots = []` 时原先会 fallthrough 到它 → 8 月的旧新闻冒充「本次抓取结果」。
**已修**：`realHots` 非 null 即进真实分支，空则显示空态 + 原因。

判断界面上是否用了演示数据时，**只查 `#hotgrid` 的 textContent**：
```js
const gridText = () => (document.getElementById("hotgrid") || {}).textContent || "";
gridText().indexOf("七夕：根植于传说") >= 0     // ✅ 正确
document.body.textContent.indexOf(...)          // ❌ 内联 <script> 源码也在 textContent 里 → 必误报
```

## CDP 探针两个高频坑（本轮各踩一次）

**① `--eval` 的结果对象只会打印成 `[object Object]`。**
`cdp_shot.mjs` 里是 `console.log(\`[${size}] eval → ${r}\`)`，模板字符串不会序列化对象。
**探针末尾必须 `return JSON.stringify(out);`**

**② 直接开 `/` 会停在登录/落地页**，`#hotgrid` 不存在（表现为 `gridFound:false`、
`body` 里却有 `HOTS` 的七夕文案）。CDP 每次都是全新 profile，没有 localStorage。
探针前置必须完整走一遍：
```js
document.getElementById("loginOv").style.display = "none";
state.user = { role: "produce", name: "curriculum_li", sources: initSources("produce") };
refreshUserChip(); buildRail(); render();
pickRoute("trend");
await sleep(1000);
```

**③ 等真实抓取要用轮询，不能只 `sleep` 固定值**：线上首次含中英互译约 50–90s。
```js
let t0 = Date.now();
while (Date.now() - t0 < 170000) {
  if (state.realScanning === false && state.realHots) break;
  await sleep(500);
}
await sleep(4000);   // 再等 90*i 的错峰动画落地
```

**④ 想做「空态 / 过滤边界」这类测试就得改 state 重绘**，改完页面会停在测试态。
要另抓一张凭证图，就用一个**纯展示、不改 state** 的探针（先抓图，再跑破坏性测试）。

---

## 任意新闻网址的信源发现链（2026-09-14 已上线 · docs/29 §11）

**老师填的一个 URL 有四种语义**，必须分流，不能只当 feed 解析：
订阅地址 / 站点首页 / 栏目页 / 单篇文章。

发现链（按成本从低到高，命中即止）：
```
L0 直接当 feed 解析
L1 网页 <link rel=alternate> 自动发现
L2 常见路径并发探测（/feed /rss /rss.xml /feed.xml /atom.xml /index.xml ...）
L3 SITE_FEED_INDEX 站点知识库（34 站，全部实测过）
L4 robots.txt → Sitemap → news sitemap
L5 单篇文章直接采集
```

### 三条铁律

**① 绝不用「降级成网页标题」兜底。**
旧实现发现不到 feed 时会把网页 `<title>` 当一条素材交出去 —— 结果 `topic` 直接是 URL、
`fulltext_len`=165，一条文章也生产不出。**发现不到就 `unsupported` + reason，不产出条目。**
(Bryan 定的原则：不为搜集而搜集；素材的下游是文章生产。)

**② 单个源抓不到，绝不 `note_error`。**
`_is_real_degradation()` 对任何非渲染类错误都返回 True（只豁免 `render.*` + warn）。
在发现层记 error，老师**加一个反爬站就会让整个热点榜挂上降级横幅**。
结果走 `sources` 报告（`/api/scan` 新增字段）回传，前端横幅以它为准。

**③ `SITE_FEED_INDEX` 里每一条都必须是实测通过的地址。** 不要凭记忆加。
本地网络受限时**可以把线上服务当代理实测**：
```bash
curl "$LIVE/api/scan?urls=<逗号分隔的候选地址>&limit=1"
# 看 items 的 origin 有没有它；errors 里出现 scan.degraded_to_title 的就是假 feed
```

### 判定「网页是文章还是列表页」：`looks_like_article`

按可靠性排序，**先用 URL 路径段数**：

1. **URL 路径段数 ≤ 1 → 列表页**（根路径/单段：站点首页、栏目页）。最可靠、零成本。
2. `og:type`：`article` → 文章；`website`/`blog`/`profile` → 列表页。
3. 一页里 `<article>` 容器 > 1 个 → 列表页（每张卡片一个；ESPN 首页有 21 个）。

> ⚠️ **不要用「链接密度」**。实测列表页 0.24~0.67 / 文章页 0.01~0.31，**完全重叠，分不开**。
> ⚠️ **不要只信 `og:type`**：ScienceDaily 首页自称 `og:type=article`（站点标注不严谨）。
> 判错两个方向都糟：首页被判成文章 → 只拿到一条首页碎片；文章被判成列表页 → 拿到整个 feed（几十条）。
> 后者更容易接受，所以判据整体偏保守。

### sitemap 兜底：必须按名字挑 news sitemap

`robots.txt` 的 `Sitemap:` 声明是**零猜测**的路径（实测 ABC/ESPN/ScienceDaily/Verge 四站全有）。
但**不能取第一个**：ABC 依次声明 `xmap` / `xmlLatestStories` / `xmlLatestVideos`，
只有 `xmlLatestStories` 是文章列表 —— `xmap` 给的全是 `/Live/`、`/Nightline/` 这类栏目页。
改为按名字优先 `latest` / `news` / `article` / `story` / `post` / `blog`，
并用 `_looks_like_article_url` 过滤掉首页、`about`、`advertise` 等站点页。

另：sitemap `.gz` 常不带 `Content-Encoding`，**要按魔数（`\x1f\x8b`）判断再 `gzip.decompress`**；
`ET.fromstring` 要传 **bytes**（带 encoding 声明的 XML 不接受 str）。

### `fetch_article` 的返回与缓存

返回 `{text, len, status, err, title}`。**没有 `fulltext_*`**（那是 `enrich_fulltext` 写的）——
直接调 `fetch_article` 后读 `fulltext_len` 会得到 `None`（踩过）。

⚠️ **给缓存加字段时要做自愈**。本轮加了 `title` 后，旧条目命中缓存 → 标题退化成 URL。
做法：`hit.get("title") is not None` 才认命中，缺字段的旧条目当未命中重抓一次即永久补上。

### 前端横幅：以逐源报告为准

`/api/scan` 的响应新增 `sources: [{input, kind, method, reason, count}]`。
`kind` ∈ `feed` / `sitemap` / `article` / `unsupported`；`reason` ∈
`site_blocks`（403，站点拒绝自动化） / `unreachable` / `http_error` / `no_feed` / `feed_empty` / `article_empty`。

- **报告里没有 `reason` 就不要挂通用降级横幅** —— 否则 ABC 这种完全成功的源，
  会因为某条视频页抽不到正文的内部 warn（`article.fetch`）被说成「部分信源未抓到」，把成功说成失败。
- 条数变少必须解释（「已抓到 12 条，另有 9 条抓不到正文已隐藏」）。

### 反爬站的对外说法（Bryan 指定）

前端面板固定一行说明，**必须强调是客观原因**：
> 美联社、路透社等站点出于自身的访问限制策略，会对来自自动化程序的访问返回拒绝响应 ——
> 这是站点方的策略限制，并非本服务故障，因此暂时无法采集。

实测：Reuters 在 Railway 容器上返回 403（本地是超时，**本地不通 ≠ 线上不通**）。

---

## 2026-09-15 ~ 09-17 大改（跨设备协作期间，务必先读）

> 这几天 Bryan 在**另一台设备 / 另一个账号**上做了大量改动（提交 `27b29625566a` → `07e3b21bb01c`）。
> 本机工作副本在 2026-09-18 已重新镜像到该版本，**下面这些是新增的、动手前必须知道的东西**。

### 新增模块一览

| 模块 | 位置 | 说明 |
|---|---|---|
| **EVP 词汇分级校验** | `backend/evp_vocab_check.py` + `evp_wordlist.json`（9751 词头） | 接口 `POST /api/vocab-check`，入参 `{articles:{A1:text,...}, words:{A1:[..]}}` |
| **档位区间门** | 前端 `genLevelGate()` / `minLevelKey()` | 素材 `level_lo` 高于 A1 时弹确认，跳过低档；`state.genSkipConfirmed` 记录已确认 |
| **文章导出** | 前端 `exportArticle(s)` / `buildDocxBlob()` / `buildArticleAllLevelsMD()` | 单 .docx（单篇一个 / 多选各自多个），4 档并列、每档先文章后题目 |
| **TTS / 封面图暂停** | 后端 `TTS_PAUSED = True`（约 2395 行） | `/api/tts` 与 `/api/tts/batch` 直接返回 503 `paused:true` |

### EVP 词汇校验：口径与阈值（改动前必看）

```python
LEVEL_CAP      = {"A1":"A1", "A2":"A2", "B1":"B1", "B2":"B2"}   # 各档允许的累计词表上界
VOCAB_THRESHOLD= {"A1":0.07, "A2":0.10, "B1":0.036, "B2":0.016}  # 超纲率阈值（2026-09-20 二次调整后）
```

- 口径：每个 Base Word 取**最低等级**；文章实词经**词形还原**后，最低等级 > 目标档 → 记为超纲词。
- 超纲 → 前端**自动重试**（`MAX_VOCAB_RETRY` 次），仍超纲则把超纲词记下来在界面展示。
- 返回结构：`{ok, results:{A1:{level,cap,content_words,over_count,over_rate,threshold,exceed,over_words,unknown_words}}, any_exceed}`。
- `words`（各档生词表）用于**豁免**，不计超纲 —— 传了才准确。
- ⚠️ 阈值是**按大档**给的。调阈值要三个方向一起想：「更严 → 更多重试 → 更慢」，别只改数字。
- ✅ **2026-09-20 双真源已合并，阈值改用范文标定值，当日又二次调整**：
  **最终值 `A1 7% / A2 10% / B1 3.6% / B2+ 1.6%`**。
  前端 `offCap()`（`index.html:1416`）与后端 `VOCAB_THRESHOLD` 现在**同值**，
  **GEN 提示词里的数字也必须同值**（三处一致；工具 `tools/patch_gen_naturalness.py`）。
  历史 bug：前端曾 1/2/3/5%、后端 5/4/3/2%，**方向相反**（B2+ 恰好反了）。
  第二次调整的原因：低档拆掉「禁用习语/隐喻」换回自然度后，**地道搭配必然带超纲词** ——
  故 A1 5%→7% / A2 8.1%→10%（产品拍板「优先自然，超纲率可放宽」）；B1/B2+ 不动。
  改任一处**必须同时改其余两处**，同 `MIN_USABLE_TEXT` 的教训。
- 🔴 **`A1` 那一档仍是「未标定」** —— 我们没有 A1- 范文。它真正的问题也不是阈值而是 **cap**：
  `EVP A1` 仅 **643 词族**，比教研的 A2 范文还低 ⇒ `top`/`win`/`fan`/`side`/`care`/`heavy`/`race`
  全被算「超纲」。**需要教研拍板是否放宽到 `A1–A2`（1721 词族）**，技术侧调阈值救不了。
- ⚠️ 仍未修：**功能词被当内容词统计**（超纲率理论上只应统计实词 —— 现在靠回灌侧过滤绕过，
  统计口径本身没改）；**表外词既不进分子也不进分母** → 越生僻越逃过校验。
- ✅ **「重试是空转」已修（2026-09-20）**：`wfInputs` 原本在重试循环**外**算一次，
  `MAX_VOCAB_RETRY` 次重试传的是**完全相同的入参** —— 约束没变化，必然仍失败，白花 ≈150 秒
  （实测 4 篇产出 × 4 档 = 16 个样本 15 个 `exceed`）。
  现在 `wfInputs` 挪进循环内，并按档打包 `avoid_words` 回灌给 GEN（回路已通，
  生成提示词里会出现【本轮禁用词】段）。⚠️ 改这块时**先推 GEN 图、再上前端** ——
  前端传了 Dify 未声明的入参有报错风险。

### 文章导出：单 .docx + 依赖 CDN 的 JSZip

`exportArticles()` 第一件事是 `typeof JSZip === "undefined"` 检查 → 未加载则 toast
「导出组件未加载，请联网后刷新重试」。**docx 打包靠 CDN 上的 JSZip**，
所以「导出点了没反应」先看控制台有没有 JSZip 加载失败，而不是查导出逻辑。

- 导出**改为单 .docx**（2026-09-22）：单篇导出 → 一个 .docx；多选 → 每篇各一个 .docx，一次下载多个。
  不再打 zip、不再出 .md、不再按档拆文件。
- 文档结构 = `# 标题` → 逐档 `# A1-/A2/B1/B2+`，**每档先文章段落（带 ①② 序号）、后该档题目**。
  题目靠 Q1/A/B/C/答案/解析自编号，`## 题目` 作加粗小标题（`mdToDocxBody` 遇 `## 题目` 进入 `inQuiz` 态，
  关闭段落序号，遇下一个 `# A1/A2/B1/B2` 复位）。
- Word 导出是**手写最小 WordprocessingML**（`buildDocxBlob` / `mdToDocxBody`），零额外依赖，
  排版规格：标题居中 / 档位加粗 / 正文序号 / Times New Roman 12 号 / 1.5 倍行距 / 两端对齐。
- 组装链路：`buildArticleAllLevelsMD(a)` 产 MD → `buildDocxBlob(md, true)` 产 blob → 下载。
- 文件名：`safeFileName(标题) + ".docx"`。已删死代码 `buildArticleMD/buildQuizMD/buildArticleLevelMD/buildQuizLevelMD/uniqueName`。

### 其它行为变化

- **写作风格换英美名家**：简奥斯汀 / 狄更斯 / 奥威尔（替换掉原先的风格集）。
- **自有素材改「书架」形式**：`ownedBooks()` / `ownedBookOpen()` / `bookCover()`，点书进章节。
- **敏感排查可人工放行**：`manualOverrideRun()`，被排除的素材在事实抽取页不再误报 0 张事实卡。
- **段落草稿落盘**：`saveParaDraft()` / `restoreParaDraft()` / `queueDraftSave()`（防刷新丢失）。
- **生成可真进度 + 可取消**：`runPct()` / `cancelLiveRun()` / `runOverdue()`。
- **确认弹窗组件**：`askConfirm()` / `confirmOk()` / `closeConfirm()`（替代原生 `confirm`）。
- 侧边栏可收起：`closeRail()` / `toggleRail()`。

### 跨设备协作的一条经验

**同一台机器上的 `~/.workbuddy/skills/` 是跨账号共享的**，
但**工作区目录（`~/WorkBuddy/<时间戳-会话>/`）是按会话隔离的**。
→ 换设备/换账号后，第一件事是**核对工作副本与远端的差异**，不要相信工作区里的旧副本：

```bash
python3 tools/fetch_sources.py /tmp/remote_latest          # 拉一份远端最新
# 逐个 sha256 比对 /tmp/remote_latest 与本地工作副本，列出 新增/修改/删除 三类
```

**别用「文件大小差不多」判断是否同步** —— 2026-09-18 这次的差异是
前端 +87166 字符（69.4 万 → 78.1 万），后端只 +1320，看起来「后端没动」但实际加了整个 EVP 模块。

---

## 📦 知识资产同步与跨设备验收（2026-09-18 建立 · 换设备前必做）

**问题**：代码推上了仓库，但 `docs/local-notes/`、`skills/`、实验脚本常常**滞留本地**。
2026-09-18 实测：共有文件 0 差异，却有 **33 个本地文件从未入库**（19 篇笔记 + 7 个实验脚本 + …）。
换设备后这些知识直接消失 —— 而它们才是「怎么安全改这个项目」的真正载体。

**判据**：**共有文件零差异 ≠ 仓库是完整的。** 必须做**全树比对**，别只比那几个代码文件。

### 一步到位：全量比对（blob sha，不用 git）

```bash
python3 - <<'PY'
import hashlib, json, os, urllib.request
tok = json.load(open("tools/.env.json"))["gh_token"]
H = {"Authorization": f"token {tok}", "User-Agent": "x"}
api = lambda u: json.load(urllib.request.urlopen(urllib.request.Request(u, headers=H)))
t = api("https://api.github.com/repos/Jinsong96/AI-Content-Center/git/trees/main?recursive=1")
remote = {e["path"]: e["sha"] for e in t["tree"] if e["type"] == "blob"}
def bs(p):
    d = open(p, "rb").read(); h = hashlib.sha1()
    h.update(b"blob %d\0" % len(d)); h.update(d); return h.hexdigest()
EX = {"tools/.env.json", "backend/.article_cache.json", "backend/.toutiao_en_cache.json"}
diff, only = [], []
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules"}]
    for f in files:
        p = os.path.relpath(os.path.join(root, f), ".")
        if p.startswith("backend/audio/") or p in EX: continue      # 音频 + gitignore 项
        if p not in remote: only.append(p)
        elif bs(p) != remote[p]: diff.append(p)
print("远端", len(remote), "| 内容不同", len(diff), "| 本地独有", len(only))
for p in only: print("   +", p)
for p in diff: print("   ~", p)
PY
```

- 排除清单必须含 **`tools/.env.json`（令牌）、两个 `backend/.*_cache.json`** —— 它们被 `.gitignore` 挡着，**不能推**。
- 推完再跑一次，应得「内容不同 0 / 本地独有 0」。

### 批量推送（`push_via_api.py` 一次只吃一个文件）

```bash
# 用同一段脚本把 only+diff 列表循环喂给 push_via_api.py（subprocess，注意中文文件名要按路径传）
MSG="chore(sync): 补齐仓库缺失的知识资产"
# 逐个：python3 tools/push_via_api.py <本地路径> <远端路径> "$MSG"
```

### 新设备验收（真拉一份，别只看网页）

```bash
python3 tools/fetch_sources.py /tmp/fresh_device_test   # 应成功 128（= 远端总数 − 音频数）
diff -r --brief /tmp/fresh_device_test . | head          # 只应差 .gitignore 排除的本地项（音频/缓存/密钥）
mkdir -p ~/.workbuddy/skills && cp -R skills/* ~/.workbuddy/skills/   # 装回技能
```

验收线：**拉取 0 失败 + 逐文件 sha 比对 0 问题 + `skills/` 能原样装回**。
`skills/README.md` 里写了 `.env.json` 要另外补（它不入库）。

### 🔴 同源漂移（每次同步都查一眼）

`skills/readpal-frontend/scripts/` 与仓库 `tools/` **内容重叠且已漂移过**：
2026-09-18 实测 6 个同源、`push_via_api.py` **不一致**。
→ **改任一侧脚本时两边都要看**，否则会重演 `MIN_USABLE_TEXT` 那类双真源事故。

### 🔴 判断「某功能有没有」必须三处都查

2026-09-18 的教训：只核了 **Dify 图**就断定「词汇层零校验」，
而 **桥接层 + 前端** 09-17 就接好了（`/api/vocab-check` + 自动重试 + 质检面板）。
**结论：Dify 图 / 桥接层 / 前端 —— 只查一处必然误判。**
