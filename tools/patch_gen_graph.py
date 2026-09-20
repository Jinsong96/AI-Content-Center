#!/usr/bin/env python3
"""GEN 图改造：词汇回灌 + 阈值对齐（2026-09-20）

背景：产出难度偏高，但「生成 → 校验 → 回灌重写」这条回路是断的。
前端会在超纲时重试，可入参一字未改（wfInputs 在循环外算一次）→ 纯掷骰子。
本脚本给 GEN 图补上「接收超纲词并定向重写」的能力，并把提示词里的阈值
对齐到后端校验器（此前提示词写 1/2/3/5%、后端判 5/4/3/2% —— 方向相反）。

做四件事（**幂等**，重复跑不会重复插入）：

  1. nodeStart 加 avoid_words 入参（paragraph，非必填）
  2. nodeClean 解析成按档的可读字符串：avoid_a1 / avoid_a2 / avoid_b1 / avoid_b2
  3. nodeClean.outputs 声明这 4 个字段（Dify 靠 outputs 决定可引用的变量）
  4. 4 个生成节点：
     · 【词汇层】的阈值数字 → 与后端 VOCAB_THRESHOLD 一致
     · 插入【本轮禁用词】段，引用本档的 avoid_* 变量

用法：
    # 1) 先从线上草稿拉完整对象（必须带 features，否则推送会清空应用特性）
    DIFY_CDP_PORT=9237 node tools/dump_full_draft.mjs <gen_app_id> /tmp/gen_full.json
    # 2) 改造
    python3 tools/patch_gen_graph.py /tmp/gen_full.json --out=/tmp/gen_patched.json
    # 3) 推送 + 发布
    node tools/dify_push_graph.mjs --app=<gen_app_id> --graph=/tmp/gen_patched.json --port=9237
    node tools/dify_publish.mjs --app=<gen_app_id> --port=9237

退出码：0 成功；1 失败
"""

import json
import re
import sys

# 节点 id → 该档的禁用词变量后缀
AVOID_VAR = {
    "nodeGenA1": "a1",
    "nodeGenA2": "a2",
    "nodeGenB1": "b1",
    "nodeGenB2p": "b2",
}

# 节点 id → (旧阈值文案, 新阈值文案)
# 新值 = 后端 VOCAB_THRESHOLD 的口径（范文标定 P75），A1- 无范文沿用 5%。
# 同时去掉「且全文 ≤N 个」—— 绝对个数与百分比是两套判据，后端只按百分比判，
# 留着会让模型去优化一个没人在查的指标。
THRESHOLD_FIX = {
    "nodeGenA1": ("超纲词率 ≤1% 且全文 ≤3 个", "超纲词率 ≤5%"),
    "nodeGenA2": ("超纲词率 ≤2% 且全文 ≤6 个", "超纲词率 ≤8.1%"),
    "nodeGenB1": ("超纲词率 ≤3% 且全文 ≤12 个", "超纲词率 ≤3.6%"),
    "nodeGenB2p": ("超纲词率 ≤5% 且全文 ≤25 个", "超纲词率 ≤1.6%"),
}

AVOID_MARK = "【本轮禁用词】"
AVOID_LINE = (
    "【本轮禁用词】上一稿下列词超出本档上限，本次**必须换成更简单的表达**"
    "（国家名/机构名/人名等专有名词、以及无法替换的固定搭配可保留）：{{#nodeClean.avoid_%s#}}"
)

CLEAN_OLD_SIG = "function main({ summary, facts_text, angle, level, gist }) {"
CLEAN_NEW_SIG = "function main({ summary, facts_text, angle, level, gist, avoid_words }) {"

CLEAN_OLD_HEAD = "  const lv = normLevel(level);"
CLEAN_NEW_HEAD = """  /* 超纲词回灌（2026-09-20）：前端把上一稿每档的超纲词按档打包成 JSON 传进来。
     容错原则 —— 非 JSON、缺字段、类型不对，一律当空处理，绝不抛错中断生成。 */
  let av = {};
  try { const o = JSON.parse(avoid_words || '{}'); if (o && typeof o === 'object') av = o; } catch (e) { }
  const fmtAvoid = (a) => (Array.isArray(a) && a.length)
    ? (a.join(', ') + '（共 ' + a.length + ' 个）')
    : '（本轮无 —— 上一稿本档已达标，请保持同样的用词水平）';
  const lv = normLevel(level);"""

CLEAN_OLD_RET = "    sensitive: 'S3 / ok', sens_level: 'S3', sens_action: 'ok', sens_reason: ''"
CLEAN_NEW_RET = """    sensitive: 'S3 / ok', sens_level: 'S3', sens_action: 'ok', sens_reason: '',
    /* 空值必须给明确文案：渲染成空字符串的话，提示词里会剩下一句
       「必须换成更简单的表达：（空）」的断头话，模型无从判断这是「没有」还是「漏传」。 */
    avoid_a1: fmtAvoid(av.A1), avoid_a2: fmtAvoid(av.A2),
    avoid_b1: fmtAvoid(av.B1), avoid_b2: fmtAvoid(av.B2)"""


def fail(msg):
    print(f"✗ {msg}")
    return 1


def prompt_text(node):
    return "".join(s.get("text", "") for s in (node["data"].get("prompt_template") or [])
                   if isinstance(s, dict))


def set_prompt_text(node, new_text):
    """只保留一个 text 段，避免插入多段后 Dify 渲染出重复内容。"""
    node["data"]["prompt_template"] = [{"role": "system", "text": new_text}]


def main():
    args = sys.argv[1:]
    if not args:
        return fail("用法: python3 tools/patch_gen_graph.py <draft.json> [--out=<out.json>]")
    src = args[0]
    out = src
    for a in args[1:]:
        if a.startswith("--out="):
            out = a.split("=", 1)[1]

    with open(src, encoding="utf-8") as f:
        draft = json.load(f)

    nodes = (draft.get("graph") or {}).get("nodes")
    if not nodes:
        return fail(f"{src} 里没有 graph.nodes —— 这是 dump_full_draft.mjs 的产物吗？")

    by_id = {n.get("id"): n for n in nodes}
    report = []

    # ---- 1. nodeStart 加 avoid_words ----
    start = by_id.get("nodeStart")
    if not start:
        return fail("找不到 nodeStart")
    vars_ = start["data"].setdefault("variables", [])
    if any(v.get("variable") == "avoid_words" for v in vars_):
        report.append("nodeStart.avoid_words  已存在，跳过")
    else:
        tpl = next((dict(v) for v in vars_ if v.get("type") == "paragraph"), None)
        if tpl is None:
            return fail("nodeStart 里没有 paragraph 类型变量可作模板")
        tpl["variable"] = "avoid_words"
        tpl["label"] = "上一稿超纲词（按档 JSON）"
        tpl["required"] = False
        vars_.append(tpl)
        report.append("nodeStart.avoid_words  +新增入参")

    # ---- 2/3. nodeClean 解析 + 声明输出 ----
    clean = by_id.get("nodeClean")
    if not clean:
        return fail("找不到 nodeClean")
    code = clean["data"].get("code", "")
    if CLEAN_NEW_SIG in code:
        report.append("nodeClean.code        已改造，跳过")
    else:
        if CLEAN_OLD_SIG not in code:
            return fail("nodeClean.code 签名与预期不符，拒绝盲改（先人工核对线上图）")
        if CLEAN_OLD_HEAD not in code:
            return fail("nodeClean.code 里找不到 `const lv = normLevel(level);` 锚点")
        if CLEAN_OLD_RET not in code:
            return fail("nodeClean.code 里找不到 return 锚点")
        code = code.replace(CLEAN_OLD_SIG, CLEAN_NEW_SIG, 1)
        code = code.replace(CLEAN_OLD_HEAD, CLEAN_NEW_HEAD, 1)
        code = code.replace(CLEAN_OLD_RET, CLEAN_NEW_RET, 1)
        clean["data"]["code"] = code
        report.append("nodeClean.code        解析 avoid_words → avoid_a1/a2/b1/b2")

    outs = clean["data"].setdefault("outputs", {})
    added = [f"avoid_{s}" for s in AVOID_VAR.values() if f"avoid_{s}" not in outs]
    for name in added:
        outs[name] = {"children": None, "type": "string"}
    report.append(f"nodeClean.outputs     {('+声明 ' + '/'.join(added)) if added else '已齐备，跳过'}")

    # nodeClean 的 inputs 映射
    cins = clean["data"].setdefault("variables", [])
    if any(v.get("variable") == "avoid_words" for v in cins):
        report.append("nodeClean.variables   已存在，跳过")
    else:
        cins.append({"variable": "avoid_words", "value_selector": ["nodeStart", "avoid_words"]})
        report.append("nodeClean.variables   +映射 nodeStart.avoid_words")

    # ---- 4. 4 个生成节点 ----
    for nid, suffix in AVOID_VAR.items():
        node = by_id.get(nid)
        if not node:
            return fail(f"找不到节点 {nid}")
        txt = prompt_text(node)
        changed = []

        old_thr, new_thr = THRESHOLD_FIX[nid]
        if old_thr in txt:
            txt = txt.replace(old_thr, new_thr, 1)
            changed.append(f"阈值 {old_thr} → {new_thr}")
        elif new_thr not in txt:
            return fail(f"{nid} 里既找不到旧阈值「{old_thr}」也找不到新阈值「{new_thr}」——请人工核对")

        if AVOID_MARK in txt:
            changed.append("禁用词段已存在")
        else:
            m = re.search(r"【词汇层】[^\n]*", txt)
            if not m:
                return fail(f"{nid} 提示词里找不到【词汇层】，无法确定插入位置")
            line = AVOID_LINE % suffix
            txt = txt[:m.end()] + "\n" + line + txt[m.end():]
            changed.append(f"插入【本轮禁用词】→ avoid_{suffix}")

        if changed:
            set_prompt_text(node, txt)
        report.append(f"{nid:12s} {node['data'].get('title','')[:14]:16s} " + "；".join(changed))

    with open(out, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=1)

    print(f"✓ 改造完成 → {out}\n")
    for line in report:
        print("   ", line)
    print()
    print("下一步：")
    print(f"    node tools/dify_push_graph.mjs --app=<gen_app_id> --graph={out} --port=9237")
    print("    node tools/dify_publish.mjs    --app=<gen_app_id> --port=9237")
    return 0


if __name__ == "__main__":
    sys.exit(main())
