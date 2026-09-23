#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReadPal · 「事实检查」Dify 图的单一真源（新建图的 DSL 生成器）。

用途
----
「轻提示词生成（GPT luna） + 严格事实检查（DeepSeek Pro） + 回炉循环」实验的**第二关**。
本图只做一件事：拿母稿 + 改写稿（单档），逐段核对事实与语义是否忠实。

为什么单档
----------
一次只检一档，输入更短、判定更聚焦。多档混检会稀释注意力（Bryan 明确要求检查端"必须严格"）。

用法
----
  python3 tools/build_factcheck_graph.py                    # 写 dify_graphs/factcheck.new.json
  python3 tools/build_factcheck_graph.py --out=/tmp/x.json

节点
----
  nodeStart(start) -> nodeJudge(llm) -> nodeEnd(end)
"""
from __future__ import annotations

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ── 模型：唯一真源在 tools/model_channels.py，这里只取常量 ────────────────────
import sys
sys.path.insert(0, HERE)
from model_channels import CHANNELS  # noqa: E402

PROV = CHANNELS['deepseek_pro']

# ── 判据（system）────────────────────────────────────────────────────────────
# 🔴 这份判据是整条链路的**软环节**：代码闸门是死的、循环是机械的，
#    只有它是「训练有素的模型 + 写死的清单」。判据宽一格，前面所有设计都白做。
#    与图 B 老版 nodeSemCheck 的关键差别：老版把「删细节、换例子」明确划进「不算错位」，
#    等于主动放弃事实层 → 这里把「主题被换」列为第 1 条、且要求从严。
SYS = """你是英语分级阅读内容的**事实与语义校对员**。上游把一篇母稿改写成了更简单的英语文章，交给你核对。

你的唯一职责：**逐段核对改写稿是否忠实于母稿**。
你不评价文笔、不评价语法、不评价难度是否合适 —— 那些不是你的事，一律不要报。

# 输入说明
【母稿】是权威原文。改写稿的每一段都必须能在母稿里找到对应段（第 i 段对第 i 段）。
【改写稿】是待检对象，已按段落切好，段号从 1 开始。

# 必须逐段检查的 6 条
1. **主题是否被换掉**（topic_swap）
   母稿第 i 段讲的是 A 事，改写稿第 i 段讲成了 B 事 —— 哪怕语言通顺、哪怕还沾着同一个领域，也算错。
   注意：用更简单的说法讲**同一件事**，不算错。

2. **核心实体/主题词是否丢失**（lost_topic）
   母稿第 i 段的核心名词（事件、对象、概念，如 malaria、mosquito net、vaccine），
   在改写稿第 i 段**完全不存在、也没有任何同义替代** —— 报错。
   注意：换成近义表达（malaria → the disease）算保留，不算丢失。

3. **专名是否与母稿不符**（wrong_name）
   人名、地名、机构名、品牌名、物种名。改写稿写错，或换成了母稿没有的另一个专名 —— 报错。
   改写稿**省略**某个专名 —— 不报（允许简化）。

4. **数字是否与母稿不符**（wrong_number）
   母稿出现的数字/年份/比例，改写稿若也给出数字，必须与母稿一致
   （约数表达 about / more than / nearly 允许，不算错）。
   改写稿写出母稿里**没有的**数字或年份 —— 报错。
   改写稿省略数字 —— 不报。

5. **因果/方向是否说反**（reversed）
   上升↔下降、增加↔减少、导致↔防止、原因↔结果 —— 说反了报错。

6. **是否凭空编造母稿没有的实质内容**（fabricated）
   母稿完全没有的事实、数据、观点、例子，改写稿里出现了 —— 报错。
   注意：连接词、语法改写、同义替换**不算**捏造。

# 严格度（务必区分）
- 第 1 条（主题被换）**从严**：这是本次最要紧的一项，有疑虑就报。
- 第 2–6 条**从严**：客观事实，在或不在、一样或不一样，有疑虑就报。
- 但**不要把「语言简化」当成错误**。低档文章必然更短、更简单、细节更少 —— 那是设计目标，不是缺陷。
  只要它讲的还是母稿那一段的同一件事，就放过。

# 输出格式
只输出一个 JSON 对象，不要解释文字，不要 markdown 代码围栏：

{"level":"<档位>","verdict":"pass 或 fail","issues":[{"para":3,"type":"topic_swap","detail":"母稿本段讲疟疾如何传播，改写稿讲的是蚊子有几种"}],"summary":"一句话总结（中文）"}

verdict 规则：issues 为空写 "pass"，否则写 "fail"。
detail 必须具体到「母稿说什么、改写稿说什么」，让人一看就知道该改哪里。
"""

USER = """【档位】{{#nodeStart.level#}}

【母稿】（逐段，段号从 1 开始）
{{#nodeStart.master_text#}}

【改写稿 · {{#nodeStart.level#}}】（第 i 段对应母稿第 i 段）
{{#nodeStart.candidate#}}

逐段核对，只输出 JSON。
"""


def node(nid, ntype, pos, width, height, data):
    return {
        "id": nid,
        "type": ntype,
        "position": pos,
        "positionAbsolute": dict(pos),
        "width": width,
        "height": height,
        "zIndex": 0,
        "data": data,
    }


def build() -> dict:
    start = node("nodeStart", "start", {"x": 80, "y": 300}, 244, 210, {
        "type": "start",
        "title": "开始",
        "selected": False,
        "desc": "接收母稿 + 单档改写稿 + 档位",
        "variables": [
            {
                "label": "母稿正文（逐段）",
                "variable": "master_text",
                "type": "paragraph",
                "required": True,
                "max_length": 20000,
                "options": [],
            },
            {
                "label": "改写稿（单档，逐段，第 i 段对应母稿第 i 段）",
                "variable": "candidate",
                "type": "paragraph",
                "required": True,
                "max_length": 20000,
                "options": [],
            },
            {
                "label": "档位",
                "variable": "level",
                "type": "text-input",
                "required": True,
                "max_length": 48,
                "options": [],
            },
        ],
    })

    judge = node("nodeJudge", "llm", {"x": 420, "y": 280}, 244, 110, {
        "type": "llm",
        "title": "① 事实与语义检（DeepSeek Pro）",
        "selected": False,
        "desc": "逐段核对：主题是否被换 / 专名数字是否失真 / 因果是否说反 / 是否编造",
        "model": {
            "provider": PROV["provider"],
            "name": PROV["name"],
            "mode": PROV["mode"],
            "completion_params": {
                "temperature": 0.1,
                "max_tokens": 8192,
                "thinking": False,
            },
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
        "desc": "输出检查原文（由外层脚本解析 JSON）",
        "outputs": [
            {"variable": "raw", "value_selector": ["nodeJudge", "text"]},
            {"variable": "level", "value_selector": ["nodeStart", "level"]},
        ],
    })

    edges = [
        {"id": "e-start-judge", "source": "nodeStart", "target": "nodeJudge",
         "sourceHandle": "source", "targetHandle": "target", "type": "custom", "zIndex": 0,
         "data": {"isInIteration": False, "sourceType": "start", "targetType": "llm"}},
        {"id": "e-judge-end", "source": "nodeJudge", "target": "nodeEnd",
         "sourceHandle": "source", "targetHandle": "target", "type": "custom", "zIndex": 0,
         "data": {"isInIteration": False, "sourceType": "llm", "targetType": "end"}},
    ]

    return {
        "graph": {"nodes": [start, judge, end], "edges": edges, "viewport": {}},
        "features": {
            "file_upload": {},
            "text_to_speech": {"enabled": False, "voice": "", "language": ""},
            "sensitive_word_avoidance": {"enabled": False},
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dify_graphs", "factcheck.new.json"))
    a = ap.parse_args()
    dsl = build()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(dsl, f, ensure_ascii=False, indent=2)
    n = len(dsl["graph"]["nodes"])
    print(f"✓ {a.out}  nodes={n} edges={len(dsl['graph']['edges'])}")
    print(f"  model={PROV['provider']} / {PROV['name']}")
    print(f"  system 判据 {len(SYS)} 字符 / user {len(USER)} 字符")


if __name__ == "__main__":
    main()
