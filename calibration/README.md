# calibration/ · 范文标定

用教研认可的分级读物范文，量出「各档合格文章到底长什么样」，给阈值和各项闸门一个**实测依据**。

## 数据从哪来

`~/Desktop/教研/书籍/` 下的 23 册扫描版分级读物（初级→A2 / 中级→B1 / 高级→B2，缺高级第 2 册）。
**全部零文本层**，必须 OCR。一册 32 个 PDF 页 = 15 篇，每篇占 2 页：

- 偶数索引页 = 英文正文（对开跨页：左页文字 + 右页插图）
- 奇数索引页 = 中文「语篇概览 + 阅读检测 + 课标主题 + 文本类型」
- 最后 2 页 = 答案

共 **345 篇**（A2 120 / B1 120 / B2 105）。

## 三个脚本，按顺序跑

| 脚本 | 干什么 | 产出 |
|---|---|---|
| `ocr_sources.py` | 渲染 PDF 页 → macOS Vision OCR（逐块带坐标） | `raw/<档>/<册>_p<页>.jsonl` |
| `build_corpus.py` | 按坐标清洗分区 → 分篇纯文本 | `text/<档>/<册>_<篇>.txt` + `manifest.json` |
| `calibrate.py` | 量指标 → 出报告 | `report.md` + `metrics.csv` |

```bash
PY=~/.workbuddy/binaries/python/envs/default/bin/python   # 需要 pymupdf
cp ~/.workbuddy/skills/macos-vision-ocr/scripts/ocr_tsv.swift /tmp/

$PY calibration/ocr_sources.py --list          # 先看册子清单
$PY calibration/ocr_sources.py --workers 6     # 全量 345 页约 70 秒
$PY calibration/build_corpus.py
$PY calibration/calibrate.py
```

## 踩过的四个坑

**1. 坐标方向反了（2026-09-20）**
`ocr_tsv.swift` 输出的 MINY 是 **Vision 原生方向：0 = 页面底部**（技能文档说已翻转，实测没有）。
按 y 升序读会把**整篇文章读反** —— 第一句跑到最后一句。必须按 y **降序**。
`build_corpus.py` 里已注明；症状是清洗出来的文本「倒着念才通顺」。

**2. 别用 `ocr_lines.swift`**
它会把同一行的多段文字用 `|` 拼起来 —— 而页面是「对开跨页」，
左页正文会和右页插图气泡拼成一行，只剩一个 x 坐标，事后没法区分谁是谁。
必须用 `ocr_tsv.swift` 逐块输出（带独立的 MINX / MINY / W / H）。

**3. 插图区文字要按 x 切掉**
正文列固定在 x ≈ 0.06–0.24（左页）与 x ≈ 0.55（右页）；
插图里的文字在 x ≥ 0.70（如 `This piece goes here.`）。→ 只保留 **x < 0.70**。

**4. 全角标点**
OCR 在中文识别模式下会把英文标点识别成 `，！？：`，必须转半角。
另有两个高频错字：`lt` → `It`（大写 I 误识成小写 l）、句末标点被识别成 `_`。

## 口径与局限

见 `report.md` 第五章。一句话：**词数不可比**（2 页绘本 vs 12 段新闻改写），
**超纲率最可靠**（比率指标，受篇幅影响小），**句长 / 蓝思谨慎用**。

## 数据是否入库

`text/` 里的 345 篇纯文本**已入库**（Bryan 2026-09-20 确认可放）。
23 个 PDF 原件（约 400MB）**不入库** —— 体积过大，且随时可从本机重跑 OCR（约 70 秒）。
