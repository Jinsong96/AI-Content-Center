# 节拍（beat）最小验证脚手架

> 结论与数据见 `docs/13-节拍最小验证实测.md`。本目录只放**可复现的脚本**。

## 这是什么

验证「按内容节拍（beat）生成 12 档分级文章」是否可行。**全程离线，不改 Dify 任何图、不推 draft。**

## 三个脚本

| 文件 | 作用 |
|---|---|
| `run_beat.py` | 节拍驱动的单档生成器。直连硅基流动 `deepseek-ai/DeepSeek-V4-Flash`（**与线上 GEN 同模型**），temperature `0.45` |
| `grade_mech.py` | 机械层判定：词数 / 段数 / 句数 / 平均句长 / 锚点命中 / 数字溯源（**不依赖模型，可复现**） |
| `judge.py` | 裁判层：用 `deepseek-ai/DeepSeek-V4-Pro` 逐节拍判「是否覆盖 / 是否与原意一致 / 是否编造」 |

## 怎么跑

```bash
P=/Users/jinsongli/.workbuddy/binaries/python/versions/3.13.12/bin/python3

# 1) 基线：A1.1 与 B2+.3
$P run_beat.py --level=A1_1 --out=/tmp/out_A1_1.json
$P run_beat.py --level=B2P_3 --out=/tmp/out_B2P_3.json

# 2) 四种对照开关
$P run_beat.py --level=A1_1 --no-numbers --out=/tmp/a.json          # 低档不出现具体数字
$P run_beat.py --level=A1_1 --no-numbers --tight --out=/tmp/b.json  # + 句数预算（每节拍 1 句）
$P run_beat.py --level=B2P_3 --expand --out=/tmp/c.json             # + 线上同款「允许合理扩写」
$P run_beat.py --level=B2P_3 --expand --deep --out=/tmp/d.json      # + 每段词数预算（关键杠杆）
$P run_beat.py --level=A1_1 --no-numbers --subset=1,3,5,7 --out=/tmp/e.json  # 只覆盖 4 个节拍（=段数）

# 3) 判定
$P grade_mech.py                                   # 机械层
$P judge.py out_A1_1.json out_B2P_3.json           # 裁判层（可传任意多个文件）
```

## 关键结论速查

- **节拍可量化**：覆盖率算得出硬数字（实测 8/8），锚点命中率也算得出（B2+.3 进阶锚点 28/28）
- **不会改原意**：5 跑全部 8/8 语义一致、0 条编造
- **句长问题被节拍解决了**：B2+.3 首次达标（22.8 / 25.8），此前四轮全部够不到下限
- **但固定节拍数与 12 档词数规格互斥**：A1.1 需要 `K ≤ 4`，B2+.3 需要 `K ≥ 8` → **无解**
- **出路：节拍数 = 段数**（A1=4 / A2=5 / B1=6 / B2+=8），跨档用「细节拍 → 粗节拍」多对一映射

## 踩过的坑

1. **节拍定义必须把「语义」和「数字」分开**。把数字写进语义要点 → 低档被判"未覆盖"（见 docs/13 §3.1）
2. 模型偶发输出**尾逗号** → 严格 `json.loads` 会失败，解析层要加 `re.sub(r',(\s*[\]\}])', r'\1', s)` 容错
3. 只给"写长一点"的指令，模型会**加段落**或**拉长单句**，两条都是歧路 —— 必须给**每段词数预算**
