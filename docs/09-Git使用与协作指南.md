# Git 使用与协作指南（ReadPal 内容生产平台）

> 面向：Bryan（产品侧）与对接的后端全栈同事
> 前提：本地 git 仓库**已经建好**（4 次提交、31 个文件、约 1.7MB），只差推到远程。
> 更新时间：2026-09-07

---

## 0. 先回答一个问题：是"上网站注册，然后复制上传"吗？

**不是。** 更准确的理解是这样：

| 你的想象 | 实际情况 |
|---|---|
| 上 GitHub 网站注册 | ✅ 对的，这一步要在网页做 |
| 把文件复制上传到网页 | ❌ 不用。网页上只建一个**空仓库**，然后本地敲一行命令把代码"推"上去 |

原因：你的代码不是一个文件，而是一整个有历史记录的仓库。用拖拽上传会丢掉历史，以后就没法回滚、没法看"某天改了什么"。

**git 的核心价值就一句话：记住每一次改动，随时能回退，多人不冲突。**

---

## 1. 注册与建库（网页操作，约 5 分钟）

### 1.1 注册

打开 https://github.com → Sign up → 填邮箱、密码、用户名。

- **用户名**很重要，会显示在仓库地址里（`github.com/你的用户名/readpal-platform`），建议简短好记，之后改起来麻烦。
- 免费版（Free）就够用，**私有仓库免费且不限数量**。

### 1.2 建一个空仓库

登录后右上角 `+` → `New repository`，按下面填：

| 字段 | 填什么 | 说明 |
|---|---|---|
| Repository name | `readpal-platform` | 建议就用这个 |
| Description | `ReadPal 英语分级阅读内容生产平台` | 选填 |
| **Public / Private** | **选 Private** | ⚠️ 必选私有 |
| Add a README file | **不勾** | ⚠️ 关键 |
| Add .gitignore | **不勾** | ⚠️ 关键 |
| Choose a license | **不勾** | 选填，内部项目可跳过 |

> **为什么这三个都要留空？**
> 因为你本地已经有一个仓库了（有 README、有 .gitignore、有 4 次提交）。
> 如果网页上也生成这些，两边历史对不上，推送会被拒绝，得先合并冲突——白白折腾。
> **建一个完全空的仓库，本地才能顺利推上去。**

填完点 `Create repository`。

建好后会看到一个"Quick setup"页面，上面有一串命令——**先别急着复制**，用下面的方式更省事。

---

## 2. 推送代码（终端操作，约 2 分钟）

### 方式 A：一键脚本（推荐）

打开终端，执行：

```bash
cd /Users/bryan/WorkBuddy/2026-08-25-09-50-09/output

# 第一步：登录（只需做一次）
gh auth login
```

`gh auth login` 会问你几个问题，一路这样选：

```
? What account do you want to log into?  → GitHub.com
? What is your preferred protocol?       → HTTPS
? Authenticate Git with your credentials? → Yes
? How would you like to authenticate?    → Login with a web browser
```

最后会给你一个 8 位验证码（如 `ABCD-1234`），复制它，回车后浏览器会自动打开，粘贴验证码点授权即可。

然后：

```bash
# 第二步：一键建库 + 推送（把 bryan 换成你的 GitHub 用户名）
./tools/git_setup_remote.sh bryan
```

脚本会自动做完 6 件事：检查登录 → 扫描密钥 → 提交未保存的改动 → 分支改名 main → 关联远程库 → 推送。

> **脚本内置了密钥检查**：如果 `index.html` 处于部署注入状态（含明文密钥），会**直接拒绝推送**，不会把密钥传上去。

### 方式 B：手动敲命令

如果你更想自己控制每一步：

```bash
cd /Users/bryan/WorkBuddy/2026-08-25-09-50-09/output

gh auth login                                    # 登录，同上

git branch -M main                               # 本地分支 master 改名为 main
git remote add origin https://github.com/你的用户名/readpal-platform.git
git push -u origin main                          # 推送
```

看到 `Branch 'main' set up to track 'origin/main'` 就成功了。

> **一个坑**：GitHub 从 2021 年起不再接受"账号密码"登录 git，必须用 token 或 SSH。
> 用 `gh auth login` 会自动把 token 配好，所以**别手动输密码**，会报
> `remote: Support for password authentication was removed`。

---

## 3. 日常怎么用

你每天的工作已经固化成两条命令，**提交（本地）和推送（远程）是分开的**：

```bash
cd /Users/bryan/WorkBuddy/2026-08-25-09-50-09/output

# 每天下班前：归档到本地仓库
./tools/daily_sync.sh "今天改了什么"

# 想把改动同步到 GitHub（换电脑前、要给人看时）
git push
```

### 为什么要分两步？

| 命令 | 作用 | 是否需要联网 | 频率 |
|---|---|---|---|
| `daily_sync.sh` | 把改动记进**本地**历史（commit） | 不需要 | 每天 |
| `git push` | 把本地历史**上传**到 GitHub | 需要 | 想同步时 |

分成两步的好处：飞机上、没网时照样能归档；改到一半不想给人看，就先不 push。

### 常用查询命令

```bash
git log --oneline          # 看提交历史
git status                 # 看当前改了什么
git diff                   # 看具体改动内容
git diff HEAD~1            # 看上一次提交改了什么
```

### 想撤回改动

```bash
git checkout -- frontend/index.html     # 丢弃某个文件未提交的改动（危险，不可恢复）
git revert HEAD                          # 撤销上一次提交（保留历史，安全）
```

---

## 4. 换台电脑 / 换个 WorkBuddy 账号怎么用

### 4.1 新电脑首次拉取

```bash
# 1. 安装 git（macOS 自带）和 gh
brew install gh

# 2. 登录
gh auth login

# 3. 克隆仓库
gh repo clone 你的用户名/readpal-platform
cd readpal-platform
```

### 4.2 ⚠️ 关键：密钥文件不会被同步

`frontend/config.local.js`（存 4 把 API key）已在 `.gitignore` 里，**永远不会进 git**。

所以新电脑上必须手动复制一次：

```bash
# 从旧电脑拷过来，或者按模板新建
cp frontend/config.local.js.example frontend/config.local.js
# 然后填入真实密钥
```

> **请务必通过安全渠道传这个文件**（AirDrop、公司内网、加密压缩包），别发微信群/邮件。

### 4.3 双 WorkBuddy 账号的注意事项

你目前有两个工作区目录：

```
~/WorkBuddy/2026-08-25-09-50-09/output/     ← git 仓库在这里（唯一真源）
~/WorkBuddy/2026-09-02-09-36-02/            ← 只有记忆日志，没有代码
```

git 仓库只建在第一个目录下。**另一个账号的会话要改代码时，务必指向这个路径**，
不要在别处复制一份改（会产生分叉，两边合并很痛苦）。

---

## 5. 给后端同事开权限

网页进入仓库 → `Settings` → `Collaborators` → `Add people` → 填他的 GitHub 用户名 → 选 **Write** 权限。

| 权限级别 | 能做什么 | 给谁 |
|---|---|---|
| Read | 只能看和 clone | 想让人看代码但不改 |
| **Write** | 能推送代码 | **后端同事选这个** |
| Admin | 能删库、改设置 | 你自己 |

他拿到权限后：

```bash
gh repo clone 你的用户名/readpal-platform
cd readpal-platform
cp frontend/config.local.js.example frontend/config.local.js   # 找你要真实密钥
```

---

## 6. 常见问题

### Q1: 推送时报 `Support for password authentication was removed`

说明你在用账号密码登录。执行 `gh auth login` 重新授权即可。

### Q2: 推送时报 `Updates were rejected because the remote contains work`

远程有你本地没有的内容（通常是建库时勾了 README）。解决：

```bash
git pull --rebase origin main
git push
```

更彻底的做法是删掉远程库重建一个**完全空的**（参考第 1.2 节）。

### Q3: `git push` 很慢 / 卡住

仓库只有 1.7MB，正常应该秒完成。如果卡住，多半是网络问题，试试：

```bash
gh auth refresh                  # 刷新登录态
GIT_TRACE=1 git push 2>&1 | tail -20    # 看详细日志
```

### Q4: 我不小心把含密钥的版本提交并推送了怎么办？

**立刻做三件事：**

1. 去 SiliconFlow / Dify 控制台**轮换密钥**（旧 key 视作已泄露）
2. 本地 `git revert` 那个提交
3. 联系 GitHub Support 清除缓存（私有库影响有限，但 key 必须换）

> **预防胜于补救**：`daily_sync.sh` 和 `git_setup_remote.sh` 都内置了密钥扫描，
> 正常流程下推不上去。别绕过它们手动 `git commit -am`。

### Q5: git 能同步我的文章数据吗？

**不能。** 文章、素材存在浏览器的 localStorage 里，不在文件系统上。

git 只同步**代码**。换台电脑打开页面会看到一个空系统——这个问题只有后端数据库能解决，
已在 `docs/07-工程化需求说明书.md` 中列为后端的核心任务。

---

## 7. 一分钟速查表

```bash
# ===== 一次性设置 =====
gh auth login
./tools/git_setup_remote.sh 你的用户名

# ===== 每天 =====
./tools/daily_sync.sh "改了什么"      # 归档到本地
git push                              # 同步到 GitHub

# ===== 查看 =====
git status                            # 改了什么
git log --oneline                     # 历史
git diff                              # 具体差异

# ===== 部署演示 =====
python3 tools/deploy_demo.py prepare  # 注入密钥（此时不能提交！）
#     → 通知部署 →
python3 tools/deploy_demo.py cleanup  # 还原（之后才能提交）
```

---

## 附：现在的仓库状态

```
位置:   /Users/bryan/WorkBuddy/2026-08-25-09-50-09/output
分支:   master（推送时会自动改为 main）
提交:   4 次
文件:   31 个，约 1.7 MB
远程:   尚未关联
密钥:   0 处（已扫描确认）
```
