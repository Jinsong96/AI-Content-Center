#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReadPal · 「专名分档」Dify 图的单一真源（DSL 生成器）。

用途
----
「骨架锁定 + 轻提示词生成」链路里的**生成前准备**环节（Bryan 2026-09-24 定的规则）：

  专名与主题词是**两套体系**，必须分开：
    · 主题词（honesty / malaria 这类概念）：超纲也**必须出现**，不换不省。
    · 专名分两档：
        A 档 —— 必须原样保留：世界级知名公众人物 / 国家 / 国际组织 / 广为人知地标，
                以及**本文讨论的对象本身**（习近平不得降成 the Chinese leader）。
        B 档 —— 可省略、可泛化：只标来源的（研究者、某大学教授、某媒体主持人、次要机构）。
                例：Mary Johnson(MIT 教授) → a professor；McMaster University → a university。

本图输出：A 档名单 + 主题词。外层脚本再叠一层「代码词频 double check」
（骨架中出现 ≥2 次 → 强制归 A），**取并集**得最终「保留清单」——
任一判「要保留」就保留（Bryan 明确要求两者并行）。

为什么单独立图（而不是塞进事实检查图）
--------------------------------------
时机不同：本图在**生成之前**跑（要拿清单去约束生成端）；
事实检查在**生成之后**跑。混在一张图里会让入参语义变脏。

用法
----
  python3 tools/build_namesplit_graph.py                 # 写 dify_graphs/namesplit.new.json
  python3 tools/build_namesplit_graph.py --out=/tmp/x.json

节点
----
  nodeStart(start) -> nodeSplit(llm) -> nodeEnd(end)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from model_channels import CHANNELS  # noqa: E402

PROV = CHANNELS['deepseek_pro']

# ── 判据（system）────────────────────────────────────────────────────────────
# ⚠️ 这段判据本身就是「规则的可执行形态」。改它 = 改产品规则，务必与 Bryan 对齐。
SYS = """你是英语分级阅读内容生产流程里的**专名分档员**。

上游给你一篇母稿按大意切好的骨架（逐字保留原文，未改动一个字）。请把骨架里的
**专有名词** 与 **主题词** 分别找出来，并给出处理档位。

# 一、主题词（topic_words）
本文讨论的**核心概念**，不是专有名词。
判准：**这个词如果被换成别的词，文章讲的事情就变了。**
例：honesty、malaria、mood、diet、climate change、depression。
⚠️ 只要 2–5 个，取最核心的。不要贪多，不要罗列普通名词。

# 二、专有名词分两档

## A 档 · 必须原样保留
满足**任一**条件即归 A 档：
1. **世界级知名公众人物** —— 各国领导人、国际知名人物、著名历史人物。
   例：Xi Jinping、Donald Trump、Elon Musk、Albert Einstein
2. **国家 / 国际组织 / 广为人知的地标、城市、地区**。
   例：China、the United States、WHO、the United Nations、Africa、Paris
3. **本文讨论的对象本身** —— 这篇文章或这一段就是在讲它。
   例：讲疟疾的文章里 Plasmodium、Anopheles；讲某个国家疫情的文章里 Nigeria

## B 档 · 可以省略 / 可以泛化
只用来标注**信息来源**的次要专名：
研究者、某大学教授、某媒体主持人、某报告作者、只出现一次且拿掉不影响理解的次要机构。
例：Cyril Caminade（一位研究员）→ 可写成 a researcher
    Mary Johnson（MIT 教授）→ 可写成 a professor / Mary
    McMaster University → 可写成 a university in Canada
    Michael Mosley（BBC 主持人）→ 可写成 a BBC presenter

# 唯一的判准
**把这个名字从文章里拿掉，读者会不会不知道文章在讲谁、在讲哪儿？**
会 → A 档。不会 → B 档。

# 兜底
**拿不准的一律归 A 档**（宁保留、勿省略）。

# 输出格式
只输出一个 JSON 对象，不要解释文字，不要 markdown 代码围栏：

{"topic_words":["malaria"],"names":[{"name":"Plasmodium","tier":"A","reason":"本文讨论的对象"},{"name":"Cyril Caminade","tier":"B","reason":"仅标注信息来源"}]}

· name 必须是骨架里**原样出现**的写法（保留大小写），不要翻译、不要改写。
· reason 用中文，一句话。
· 如果骨架里没有专名，names 写空数组。
"""

USER = """【标题】{{#nodeStart.title#}}

【母稿骨架】（逐段，未改动原文）
{{#nodeStart.skeleton#}}

按上面的规则分档，只输出 JSON。
"""


def node(nid, ntype, pos, width, height, data):
    return {
        "id": nid, "type": ntype, "position": pos, "positionAbsolute": dict(pos),
        "width": width, "height": height, "zIndex": 0, "data": data,
    }


def build() -> dict:
    start = node("nodeStart", "start", {"x": 80, "y": 300}, 244, 170, {
        "type": "start",
        "title": "开始",
        "selected": False,
        "desc": "接收母稿骨架（逐段）+ 标题",
        "variables": [
            {"label": "母稿骨架（逐段，原文未改动）", "variable": "skeleton",
             "type": "paragraph", "required": True, "max_length": 20000, "options": []},
            {"label": "标题", "variable": "title", "type": "text-input",
             "required": False, "max_length": 200, "options": []},
        ],
    })

    split = node("nodeSplit", "llm", {"x": 420, "y": 280}, 244, 110, {
        "type": "llm",
        "title": "① 专名分档 + 主题词（DeepSeek Pro）",
        "selected": False,
        "desc": "A 档=必须原样保留；B 档=可省略/泛化；并抽出主题词",
        "model": {
            "provider": PROV["provider"],
            "name": PROV["name"],
            "mode": PROV["mode"],
            "completion_params": {"temperature": 0.1, "max_tokens": 4096, "thinking": False},
        },
        "prompt_template": [
            {"role": "system", "text": SYS},
            {"role": "user", "text": USER},
        ],
        "context": {"enabled": False, "variable_selector": []},
        "vision": {"enabled": False, "configs": {"detail": "low"}},
        "memory": None,
        "answer": "",
    })

    end = node("nodeEnd", "end", {"x": 760, "y": 280}, 244, 90, {
        "type": "end",
        "title": "结束",
        "selected": False,
        "desc": "输出分档原文（外层脚本解析 JSON）",
        "outputs": [{"variable": "raw", "value_selector": ["nodeSplit", "text"]}],
    })

    edges = [
        {"id": "e-start-split", "source": "nodeStart", "target": "nodeSplit",
         "sourceHandle": "source", "targetHandle": "target", "type": "custom", "zIndex": 0,
         "data": {"isInIteration": False, "sourceType": "start", "targetType": "llm"}},
        {"id": "e-split-end", "source": "nodeSplit", "target": "nodeEnd",
         "sourceHandle": "source", "targetHandle": "target", "type": "custom", "zIndex": 0,
         "data": {"isInIteration": False, "sourceType": "llm", "targetType": "end"}},
    ]

    return {
        "graph": {"nodes": [start, split, end], "edges": edges, "viewport": {}},
        "features": {
            "file_upload": {},
            "text_to_speech": {"enabled": False, "voice": "", "language": ""},
            "sensitive_word_avoidance": {"enabled": False},
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dify_graphs", "namesplit.new.json"))
    a = ap.parse_args()
    dsl = build()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(dsl, f, ensure_ascii=False, indent=2)
    print(f"✓ {a.out}  nodes={len(dsl['graph']['nodes'])} edges={len(dsl['graph']['edges'])}")
    print(f"  model={PROV['provider']} / {PROV['name']}")
    print(f"  system 判据 {len(SYS)} 字符 / user {len(USER)} 字符")


if __name__ == "__main__":
    main()
