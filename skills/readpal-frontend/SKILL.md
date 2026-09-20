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
| 项目约定 | 仓库根 `AGENTS.md`（**动工前必读**，含 6 个已踩坑） |

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
| 本地探针里 `AIWF_*.appKey` 为空、函数静默返回不报错 | 本地没有 `config.local.js`，`appKey` 空 → 函数**内部 `try/catch` 提前抛掉**，表现为「什么都没发生」 | 探针里先 `AIWF_FACT.appKey='app-PROBE'`（`const` 对象属性可改）再调用 |
| 以为「线上新字段全缺」 | `tools/dify_run_app.py --out=xxx.json` 写的文件**顶层就是 outputs 本身**，没有再套一层 `outputs` | 读 `d['align_map']`，**不要**读 `d['outputs']['align_map']` |
| `curl` 线上 `CONNECT tunnel failed, response 502`；`urllib` 直连超时 | 本机代理拦截 Railway 域；显式 `ProxyHandler({})` 绕代理后**仍超时** | **别在网络层绕** —— 用 CDP 从已登录的 Chrome 里 `Network.getResponseBody`（`Page.navigate` + 监听 `Network.responseReceived` 取 `requestId`）拿**原始响应体**，用 `Network.setCacheDisabled(true)` 防缓存 |
| 手写大段 `atomic_replace` spec 容易抄错 | 人肉复制长 `old` 必然出岔 | **从远端原版派生**：拉线上文件 → 用 `difflib` 定位差异块 / 用 `索引切片` 从**本地新文件**取 `new`、从**远端旧文件**取 `old` → 断言 `r.count(old)==1` → 跑 `atomic_replace` → **与本地文件比 sha256，逐字节一致才算通过** |
| 探针读到「FACT 没有 `level_lo`/`info_points`、`gist_len=0`」 | `runGeneration()` 结束时把 **`state.live.run` 换成 GEN 的响应**，事后读它其实读的是 GEN 的 outputs | 要么在 **FACT 刚结束、GEN 未启动**时读；要么改用**穿透式记录器**（记录请求体但照常转发请求），见 `scripts/probe_live_e2e.mjs` |
| **切到没有内容的大档后，大档切换条整条消失、点不回去** | `alignedViewHTML()` 开头的 `if(!has) return ""` —— 切换条就渲染在这一块里，被一起带走了。区间模型下（素材只到 A2.3）必然触发 | 改成 `if(!has) return h+emptyGroupHTML();`，切换条与空态卡片始终保留。**判据：任何状态下 `.bigtab` 恒为 4**。回归用 `scripts/probe_review_levels.mjs` |
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
| 4 档视图 | `alignModeBarHTML()` / `setAlignMode('grid'\|'single')` / `alignBodyHTML()`；`alignedViewHTML()` = `bigBarOnce()` + 模式条 + 正文。**判据：任何状态 `.bigtab` 恒为 4** |
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
| **文章导出** | 前端 `exportArticle(s)` / `buildDocxBlob()` | Markdown + Word(.docx)，按档位拆文件，打包 zip |
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

### 文章导出：依赖 CDN 的 JSZip

`exportArticles()` 第一件事是 `typeof JSZip === "undefined"` 检查 → 未加载则 toast
「导出组件未加载，请联网后刷新重试」。**zip 打包靠 CDN 上的 JSZip**，
所以「导出点了没反应」先看控制台有没有 JSZip 加载失败，而不是查导出逻辑。

- Word 导出是**手写最小 WordprocessingML**（`buildDocxBlob` / `mdToDocxBody`），零额外依赖，
  排版规格：标题居中 / 档位加粗 / 正文序号 / Times New Roman 12 号 / 1.5 倍行距 / 两端对齐。
- 文件名规则：`标题_档位` / `标题_档位_题目`（`safeFileName()` + `uniqueName()` 防重名）。

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
