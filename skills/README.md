# skills/ — 本机 WorkBuddy 技能的仓库镜像

> **为什么有这个目录**：技能运行副本在 `~/.workbuddy/skills/`，
> 它**只存在于装了它的那台机器上** —— 换电脑就没了。
> 而这两份技能（约 1,800 行）承载的正是「怎么安全改这个项目」的全部经验。
> 按 `AGENTS.md` §10 的原则「**知识必须落进仓库**」，这里放一份镜像。

## 换设备 / 换账号怎么用

```bash
# 1) 拉源码镜像（别 git clone —— 仓库含 90MB 音频）
python3 tools/fetch_sources.py "$WS/readpal"          # $WS = 当前 WorkBuddy 工作区

# 2) 装回技能
mkdir -p ~/.workbuddy/skills
cp -R "$WS/readpal/skills/readpal-frontend"       ~/.workbuddy/skills/
cp -R "$WS/readpal/skills/readpal-dify-workflow"  ~/.workbuddy/skills/

# 3) 补本机令牌（.env.json 不入库，见下）
cp "$WS/readpal/tools/.env.json" ~/.workbuddy/skills/readpal-frontend/scripts/.env.json
```

## ⚠️ 两条维护约定

1. **`.env.json` 永远不入库。** 镜像里已剔除；`~/.workbuddy/skills/readpal-frontend/scripts/.env.json`
   与 `tools/.env.json` 是同一份令牌，属本地文件（`.gitignore` 已排除）。
2. **`scripts/` 与仓库 `tools/` 有重叠，且已经出现过漂移。**
   2026-09-18 实测：`atomic_replace.py` `check_js.py` `fetch_sources.py` `e2e_verify.mjs`
   `theme_audit.mjs` `cdp_shot.mjs` 六项**同源**，但 `push_via_api.py` **已不一致**。
   → **改任一侧脚本时，两边都要看**，别只改一处（同 `MIN_USABLE_TEXT` 那类双真源教训）。
   `scripts/` 下另有 6 个 `tools/` 里没有的探针：
   `probe_contract.mjs` `probe_live_e2e.mjs` `probe_review_levels.mjs`
   `probe_toutiao_fulltext.py` `screenshot.sh` `verify_live.sh` —— 它们只在这里。

## 谁是真源

| 内容 | 真源 |
|---|---|
| 项目约定 / 踩过的坑 | 仓库根 `AGENTS.md` |
| 逐次改动的实测记录 | `docs/local-notes/` |
| 工作流经验（步骤 / 探针用法） | 技能 `SKILL.md`（本目录） |
| 运行时代码 | `frontend/` `backend/` |

> 首次接手的朋友：**先读 `AGENTS.md`，再读 `HANDOFF.md`**，技能是查手册不是入门读物。
