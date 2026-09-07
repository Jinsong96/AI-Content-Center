# AI 内容生产平台 · Demo 本地运行指南

> 多角色 AI 英语分级阅读内容生产平台（CEFR A2/B1/B2）—— 素材采集 → 打标 → 事实抽取 → 内容生成 → 校对 → 逐段审核 → 内容管理平台，全流程可跑。
> 本包让每台电脑都能完整使用 demo（含 TTS 音频）：所有服务跑在**你本机**，`127.0.0.1` 指向的就是你自己的机器。

## 0、最简单方式（推荐给同事，无需懂命令）

把解压后的整个文件夹 `AI_Content_Platform_Demo/` 发给同事，里面有现成的启动文件：

- **macOS 电脑**：**双击 `StartDemo.command`**（首次如提示"无法打开"，请 右键 → 打开 一次即可）
- **Windows 电脑**：**双击 `StartDemo_Windows.bat`**

启动文件会自动做三件事：**① 检查 Python —— 没装会自动帮你安装**（macOS 走 Xcode 命令行工具 / Windows 走 winget，首次约 2–15 分钟，之后不用再装）→ ② 启动后端服务 → ③ 打开浏览器页面 http://localhost:8000。

想用"一条终端命令"也行（最常见情况：zip 解压在「下载」文件夹）——

**macOS**：打开「终端」，粘贴这一条，回车：
```bash
cd ~/Downloads/AI_Content_Platform_Demo && bash StartDemo.command
```

**Windows**：打开解压出的文件夹 → 在文件夹地址栏输入 `cmd` 回车 → 粘贴这一条，回车：
```cmd
cd /d %USERPROFILE%\Downloads\AI_Content_Platform_Demo && StartDemo_Windows.bat
```

如果文件解压在别的位置，把命令里的路径改一下即可；或者干脆直接双击启动文件，就不用碰终端了。

---
## 目录结构

```
AI_Content_Platform_Demo/
├── StartDemo.command        # ★ macOS：双击即启动（含自动装 Python）
├── StartDemo_Windows.bat            # ★ Windows：双击即启动（含自动装 Python）
├── start_demo.sh          # macOS/Linux 命令行一键启动脚本
├── README.md              # 本指南
├── frontend/              # 前端单文件应用（index.html + 封面 + 热点缓存）
└── backend/               # 本地桥接层（纯 Python 标准库，无需 pip install）
    ├── agent_reach_bridge.py   # 主服务：热点/标签词表/TTS音频/素材同步（端口 8787）
    ├── start_bridge.py         # 守护方式启动/停止桥接（macOS/Linux）
    ├── cdp_render.js           # （可选）Toutiao 等需 JS 渲染的信源，经 Chrome CDP 抓全文
    ├── start_cdp.sh            # （可选）启动无头 Chrome（端口 9222）
    ├── library.json            # 文章同步备份（运行后由桥接层维护）
    └── audio/                  # TTS 音频缓存（首次运行自动创建/按需合成）
```

## 环境要求

- **Python 3.9+**（后端只用标准库，无第三方依赖）
- **现代浏览器**（Chrome/Edge 推荐）
- **可访问外网**（内容生成走 Dify Cloud、TTS 走硅基流动、热点真实抓取）

## 一、macOS / Linux

```bash
# 解压后进入目录
cd AI_Content_Platform_Demo

# 方式 A：一键启动（后端守护 + 前端 8000 端口）
./start_demo.sh

# 方式 B：分步启动（推荐，两个终端各自看日志）
# 终端 1 —— 后端桥接层
python3 backend/start_bridge.py            # 守护方式启动
python3 backend/start_bridge.py --status   # 查看状态
# 终端 2 —— 前端静态服务
python3 -m http.server 8000 --bind 127.0.0.1 -d frontend
```

然后浏览器打开 **http://localhost:8000**，页面右上角后端状态应为「后端已连接」。

## 二、Windows（PowerShell）

`start_bridge.py` 的守护写法基于 Unix，Windows 请**前台运行**：

```powershell
# 终端 1 —— 后端桥接层（保持窗口开着）
cd AI_Content_Platform_Demo\backend
python agent_reach_bridge.py

# 终端 2 —— 前端静态服务
cd AI_Content_Platform_Demo
python -m http.server 8000 --bind 127.0.0.1 -d frontend
```

浏览器打开 **http://localhost:8000**。

## 三、登录账号（密码均为 123456）

| 角色 | 账号 | 职责与可见范围 |
|---|---|---|
| 市场老师 | collect | 素材管理平台：素材入口 01–04 + 素材库 |
| 教研老师 | produce | 素材管理平台全部 + 文章管理平台生产 05–09 + 文章库 |
| 审核老师 | review | 全流程（先进文章库审核草稿 → 逐段审核） |
| 运营老师 | ops | 内容管理平台：运营 / 发布 / 反馈 |

## 四、功能真实性边界（重要，演示前请先读）

- ✅ **内容生成 / 事实抽取 / AI 标签 / AI 校验**：真实调用 Dify Cloud 工作流（约 40–70s），无写死。
- ✅ **TTS 音频**：真实合成 MP3（硅基流动 CosyVoice）。同文本第二次起命中本地磁盘缓存，不再计费。
- ✅ **热点搜集**：真实抓取全网热点；部分海外源受网络限制可能为空（页面会显示降级横幅，属正常）。
- ✅ **素材归档 / 文章库 / 审核流转**：前端可真实跑通；数据存 **浏览器 localStorage**（每台机器各自独立，换浏览器/清缓存即清空）。
- ⚠️ **密钥内嵌**：前端含 Dify 三把 key，`backend/agent_reach_bridge.py` 第 283 行含硅基流动 `SF_KEY`。
  **仅限团队内部使用，请勿把本包外传 / 提交到公开仓库**。长期使用请迁移到团队 Dify 账号，替换前端常量与 `SF_KEY`。
- ⚠️ **桥接层监听 0.0.0.0 且无鉴权**：请只在可信内网运行，用完即停。

## 五、自定义信源全文抓取（可选）

热点与部分自定义信源（Toutiao 等需 JS 渲染的页面）需要本机 Chrome：

```bash
bash backend/start_cdp.sh    # 启动无头 Chrome（调试端口 9222），再在页面重试抓取
```

不配置也不影响主体流程（带正文的源不受影响）。

## 六、常见问题

- **页面提示「后端未连接」/ 无音频**：桥接层没起来。运行 `python3 backend/start_bridge.py --status` 检查，8787 未监听则重新启动。
- **07 内容生成要点几次？**：一次。素材若还没抽过事实，07 页显示「抽取并生成」按钮——点击后先跑事实抽取（约 5–10s），完成后**自动接续**生成三档文章（约 40–60s），进度条分阶段显示；若事实已抽取（如从敏感排除流程过来），页面直接显示「生成三档文章」，点一次即出文章。
- **文章/素材不见了**：数据在本浏览器 localStorage，换机器/清缓存会清空；正式使用请迁移到服务端存储。
- **TTS 计费疑问**：首次合成某段文本会真实调用一次（少量费用），之后命中缓存。

## 七、停止服务

```bash
python3 backend/start_bridge.py --stop     # 停桥接层（或 pkill -f agent_reach_bridge.py）
# 前端 http.server 所在终端按 Ctrl+C 即可
```

## 八、自检清单（拿到包后建议 3 分钟跑一遍）

1. 打开 http://localhost:8000 → 右上角「后端已连接」✓
2. 市场老师登录 → 01 素材入口 → 自有素材《用英文讲好中国故事》→ 点一个章节 → 「进入敏感排除并运行工作流」→ 04 打标 → 「存入素材库」→ 素材库出现该素材且带主题标签 ✓
3. 教研老师登录 → 素材库「选用生成」→ 07 点「抽取并生成」（事实抽取后自动接续）→ 出 A2/B1/B2 三档文章 + 音频 ✓ → 09 校对 → 「存入文章库」
4. 审核老师登录 → 文章库「文章草稿」→ 点「审核」→ 逐段审核 → 「审核通过」→ 回到文章库「已审核」✓
5. 运营老师登录 → 内容管理平台按主题看到已审核文章 ✓
