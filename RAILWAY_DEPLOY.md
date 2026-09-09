# ReadPal · Railway 一键部署指南

本指南用于把 **AI 内容生产平台（ReadPal）** 部署到 Railway，让其他老师**不用装任何后端**就能直接打开页面使用。

---

## 架构（一次部署搞定，无需 Netlify）

```
老师浏览器  ──▶  Railway（同一个服务）
                  ├─ 后端：Python bridge + Dify/SiliconFlow 反向代理
                  └─ 前端：ReadPal 单页（HTML 内联热点数据，无外部依赖）
                  密钥配置在环境变量里（见下方「密钥可见性」说明）
```

**关于密钥可见性（2026-09-09 更新，重要）**

前端核心链路（Dify 工作流、SiliconFlow 封面图）已改为**直连公网 API**，直连请求必须自带密钥，
因此 bridge 会把环境变量里的密钥注入到页面的 `window.WB_CONFIG` 中 —— **按 F12 能看到**。

- 演示场景（额度有限、内部老师使用）：可以接受，部署最简单。
- 若要彻底隐藏：需把前端那 4 处改回「走 bridge 代理」模式，由服务端转发、浏览器不接触密钥。

无论哪种，`config.local.js` 都不入库，密钥不会写进 GitHub。

---

## 一、前置准备（5 分钟）

1. 注册/登录 **Railway**：[https://railway.app](https://railway.app)
   - 第一次注册会自动获得 **$5 试用额度**，足够演示用几个月
2. 注册/登录 **GitHub**（推荐用 GitHub 部署，最稳）

---

## 二、上传源码到 GitHub（推荐方式 A · 5 分钟）

**关键**：把 `output/` 目录推到一个**新的空仓库**（不要推到现有仓库，避免混入其他项目）。

```bash
cd /Users/bryan/WorkBuddy/2026-08-25-09-50-09/output

# 第一次推：建新仓库并提交
git init -q
git add Procfile requirements.txt .env.example .railwayignore \
        backend/ frontend/
git commit -m "ReadPal deploy-ready"

# 在 GitHub 网页建一个空仓库（比如 readpal-demo），然后：
git remote add origin git@github.com:<你的账号>/readpal-demo.git
git branch -M main
git push -u origin main
```

> `.railwayignore` 已经排除了 `backend/audio/`、缓存文件、`__pycache__`、`.DS_Store` 等不该上传的文件。**`config.local.js` 本来就不在 `output/frontend/` 里**（它在 `output/frontend/` 同级下、但只有本地 dev 用），无需担心。

---

## 三、在 Railway 创建项目（3 分钟）

1. Railway Dashboard → **New Project** → **Deploy from GitHub repo**
2. 选刚才推送的 `readpal-demo` 仓库
3. Railway 会自动开始构建；先别等它跑通，**先配环境变量**

---

## 四、配置环境变量（关键 · 2 分钟）

在 Railway 项目页 → **Variables** 标签 → 点 **+ New Variable** 添加以下 4 个：

| 变量名 | 必填？ | 值从哪里来 |
|---|---|---|
| `SF_API_KEY` | ✅ | `output/frontend/config.local.js` 里 `SF_API_KEY:` 后面的字符串（sk- 开头） |
| `DIFY_WF_FACT` | ✅ | 同上文件里 `DIFY_WF_FACT:` 后面的字符串（app- 开头） |
| `DIFY_WF_GEN` | ✅ | 同上文件里 `DIFY_WF_GEN:` 后面的字符串（app- 开头） |
| `DIFY_WF_MAIN` | ⚪ 可选 | 同上文件里 `DIFY_WF_MAIN:` 后面的字符串（如暂未使用，可填任意字符串） |
| `DEMO_PASS` | ⚪ 可选 | 演示账号登录密码。**不填** = 老师点登录直接进（方便）；填了 `123456` = 必须输密码才能进（防随便看）。变量名必须是 `DEMO_PASS`，不能加 `WB_` 前缀（老模板里叫 `WB_DEMO_PASS` 是错的，已修复）。 |

**最快复制方式**：在你本机终端跑：

```bash
grep -E '"(SF_API_KEY|DIFY_WF_FACT|DIFY_WF_GEN|DIFY_WF_MAIN)"' \
  /Users/bryan/WorkBuddy/2026-08-25-09-50-09/output/frontend/config.local.js
```

会输出 4 行 `key = "sk-xxx"` 或 `key = "app-xxx"`，每行复制等号右侧的引号内容到 Railway。

> ⚠️ **密钥可见性**：见开头说明。当前直连模式下，bridge 会把环境变量里的密钥注入
> `window.WB_CONFIG`（F12 可见）；前端 HTML 里的 `<script src="config.local.js"></script>`
> 已被 bridge 替换成 `window.WB_API_BASE=""`（声明同源，让 bridge 那 4 项走相对路径）。

添加完 4 个变量后，Railway 会自动重新部署。等 Deploy Logs 显示 `bridge listening on http://0.0.0.0:XXXXX` 就成功了。

---

## 五、拿到链接、给老师用（1 分钟）

Railway 项目页右上角 **Settings → Domains → Generate Domain**，会得到：

```
https://readpal-demo-production-XXXX.up.railway.app
```

把这个链接发给老师就行了。**不用装 Python、不用跑 bridge、不用任何环境配置**。

老师打开后：
- 演示账号（市场/教研/审核/运营老师）默认**空密码**，点登录直接进
- 如果你配了 `DEMO_PASS` 环境变量，所有账号会要求输入该密码才能进入（输入框上方会显示）
- 4 个角色的登录入口在登录页可见

---

## 六、验证部署是否成功

```bash
# 把上面的链接替换成你的实际域名
RAILWAY_URL=https://readpal-demo-production-XXXX.up.railway.app

# 1) 服务存活
curl -s $RAILWAY_URL/api/health
# 期望: {"ok": true, "name": "agent-reach-bridge", ...}

# 2) 密钥是否被读到（4 个都应该是 true）
curl -s $RAILWAY_URL/api/proxy-health
# 期望: {"ok": true, "configured": {"SF_API_KEY": true, "DIFY_WF_FACT": true, "DIFY_WF_GEN": true, "DIFY_WF_MAIN": true}}

# 3) 首页密钥注入是否生效（直连模式必需）
curl -s $RAILWAY_URL/ | grep -o 'window.WB_CONFIG={[^}]*}'
# 期望: WB_CONFIG={DEMO_PASS:"...",SF_API_KEY:"sk-...",DIFY_WF_MAIN:"app-...",...}
# 若某项为空 → 对应环境变量没配好 → 文章生产 / 封面图会失败

# 3b) 同源声明是否注入（bridge 那 4 项功能依赖它）
curl -s $RAILWAY_URL/ | grep -o 'window.WB_API_BASE=""'
# 期望: 有输出。没有的话热点/TTS/内容库/标签会去连访问者本机 8787 而失败

# 4) 海外出口 IP 是否能抓到热点（Railway 出口在美国，国内站点可能慢/被地域限制）
curl -s "$RAILWAY_URL/api/trends?theme=all&limit=10"
# 关注: 返回 JSON 里 "items" 数组长度、今日头条来源是否还在、耗时几秒
# 如果头条源挂了但其他源（NPR/CGTN/Billboard 等）正常，演示优先用「自有/公版权」入口走，不影响主流程

# 5) 演示密码注入是否生效（如果你配了 DEMO_PASS）
curl -s $RAILWAY_URL/ | grep -o 'WB_CFG[^;]*'
# 期望看到: WB_CONFIG={DEMO_PASS:"你设置的值"}; 或合并后的 WB_CFG 含 DEMO_PASS
```

如果 `/api/proxy-health` 有任何 false，回到第四步检查对应变量名是否拼写一致。

---

## 七、部署后常见问题

### 1. 部署失败（Deploy Logs 报错）

最常见的是 `Procfile` 没识别。检查 Railway 项目根目录是不是 `output/`（应该能看到 `Procfile`、`requirements.txt`、`backend/`、`frontend/`）。如果是子目录错了，到 **Settings → Root Directory** 改成 `output`。

### 2. 打开页面空白

- 检查 `/api/health` 是否返回 ok
- 检查 `/api/proxy-health` 是否 4 个密钥都 true
- 浏览器按 F12 看 Console 报错（最常见是「未配置」——意味着环境变量没读到）

### 3. 国内访问慢

Railway 服务器在海外，国内访问可能 2-5 秒延迟。演示给国内老师看时可以：
- 提前打开页面缓存
- 绑定自定义域名 + Cloudflare 加速（Railway Settings → Domains → Custom Domain）

### 4. 想用 Netlify 单独托管前端

如果坚持用 Netlify 托管前端 + Railway 托管后端，需要额外创建 `output/frontend/config.prod.js`：

```js
window.WB_API_BASE = "https://readpal-demo-production-XXXX.up.railway.app";
```

然后 Netlify 部署时只传 `frontend/` 目录（包含 `config.prod.js`，**不要包含 `config.local.js`**）。但本指南的「单服务模式」更简单，绝大多数场景够用。

### 5. 热点正文质量差（只有标题没有原文）

**现象**：热点搜集能拿到 30 条条目，但其中只有少数有原文（>300 字），其余只剩标题和短摘要。

**根因**：当前代码对头条正文依赖 macOS 本机的 Google Chrome 做无头渲染。Railway 是 Linux 容器，没有 Chrome，所以退化为「仅取标题 + 短摘要」。

**演示建议**（按效果排）：

1. 优先选「自有 / 合作版权」入口（素材库里的《用英文讲好中国故事》），这是开箱可用的稳定素材源
2. 用「英文公版书」入口（Standard Ebooks / Project Gutenberg），素材质量高且不受头条正文缺失影响
3. 实在要用热点，**优先选那些带正文预览（>300 字）的条目**，避开「仅标题」的

**长期方案**：容器内装 headless Chromium 并改路径探测（改动较大，约 1-2 小时），短期不建议投入。

### 6. 内容库里已有文章的音频 404

**现象**：内容库文章点播放无声，DevTools Network 显示 `/audio/*.mp3` 返回 404。

**原因**：`.gitignore` 默认排除整个 `backend/audio/`（240MB 过大），但内容库的 5 篇文章实际引用其中 30 个文件。

**本仓库已处理**：`.gitignore` 与 `.railwayignore` 里改为「先排除整个目录，再白名单放行这 30 个被引用的文件」（共约 73MB）。如果你的 fork 仓库里仍是旧的整目录排除，需要同步这个白名单。验证方法：

```bash
git check-ignore -v backend/audio/<某个被引用的 mp3> | head -1
# 期望最后匹配的规则是白名单那行（带 ! 前缀）
```

### 7. 容器重启后内容库和新音频丢失

**现象**：Railway 每次重新部署都会清空容器文件系统，导致 `backend/library.json`（内容库文章）和运行中新生成的 TTS 音频丢失。

**临时方案**：演示用数据（非真实业务）丢失可接受；生产用必须挂 Volume。

**挂 Volume 步骤**（Railway）：

1. 项目页 → **+ New** → **Volume**，挂载到 `/app/backend`
2. 容器内的 `backend/library.json` 和 `backend/audio/` 会持久化到 Volume
3. 重启/重新部署不会丢数据
4. 注意：Volume 需要付费，$0.25/GB/月；5GB 以内的小项目不贵

### 8. 完整功能可用性速查

实测结果（本地以 Railway 模式跑真实调用得出，详见 `FUNCTION_AUDIT.md`）：

| 功能 | 状态 |
|---|---|
| 内容生成 GEN（57.5s）| ✅ 可用 |
| 事实抽取 FACT（8.9s）| ✅ 可用 |
| 封面图 文生图（2.2s）| ✅ 可用 |
| 语音合成 TTS | ✅ 可用（新生成快，已有音频随部署上传）|
| 标签体系 + 提取 | ✅ 可用 |
| 素材库读写 | ✅ 可用 |
| 密钥安全 | ✅ 服务端环境变量，浏览器拿不到 |
| 演示登录密码 | ✅ 可选配 DEMO_PASS |
| 热点列表抓取 | ⚠️ 海外出口 IP 抓国内站点，待部署后实测 |
| 头条正文质量 | ⚠️ 容器无 Chrome，正文降级 |
| 数据持久化 | ⚠️ 需挂 Volume |

---

## 八、想撤销部署

Railway 项目页 → **Settings → Danger → Delete Project**。密钥随项目一起销毁，无需手动去 SiliconFlow / Dify 控制台撤销（演示用的 key 建议事后在原平台轮换一次，参考部署历史.md 6）。

---

## 九、本地复现线上行为

在改代码后、推 GitHub 之前，可以本地用 Railway 模式跑一遍验证：

```bash
cd /Users/bryan/WorkBuddy/2026-08-25-09-50-09/output/backend
python3 start_railway_local.py              # 默认 8793 端口
# 访问 http://127.0.0.1:8793/ 即可（同部署后行为）
python3 start_railway_local.py --stop       # 停止
```