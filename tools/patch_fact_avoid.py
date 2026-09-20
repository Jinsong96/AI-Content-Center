#!/usr/bin/env python3
"""FACT 图改造：给 nodeClean 补「超纲词回灌」通路（2026-09-20）

背景（这是重拼 MAIN 时才暴露的真问题）：
    超纲词回灌（`avoid_words` → `avoid_a1/a2/b1/b2`）最初只加在 **GEN 图**上
    （见 `tools/patch_gen_graph.py`），四个生成节点的提示词因此引用了
    `{{#nodeClean.avoid_a1#}}` 这类变量。

    但 **MAIN 图不是独立一套提示词** —— 它是 `build_main_graph.py` 从
    FACT ⊕ GEN 拼出来的，而且 **nodeClean 取的是 FACT 版**（GEN 版因同 id 冲突被丢弃）。
    ⇒ FACT 版 nodeClean 没有 `avoid_*` 输出，MAIN 一重拼就会：
       ① `build_main_graph.py` 静态校验报 4 个「引用了不存在的变量」；
       ② 更要命的是**上线后 MAIN 会直接跑不起来**（Dify 运行时校验变量可达性，不报在静态层也要报在运行层）。

    修法：把同一条解析逻辑补到 **FACT 的 nodeClean + nodeStart** 上。
    FACT 自身用不到 `avoid_words`（前端调 FACT 时根本不传），缺省按空处理，
    对抽取链路零影响；补上之后 FACT / GEN / MAIN **三图口径一致**。

做五件事（**幂等**，重复跑不会重复插入）：
    1. nodeStart 加 avoid_words 入参（paragraph，非必填，max_length=4000）
    2. nodeClean 签名加 avoid_words 形参
    3. nodeClean 体内加 JSON 解析（非 JSON / 缺字段一律当空，绝不抛错）
    4. nodeClean 的 return 加 avoid_a1/a2/b1/b2 四个字段
    5. nodeClean.outputs 声明这四个字段 + variables 加 avoid_words 映射

用法：
    DIFY_CDP_PORT=9238 node tools/dump_full_draft.mjs <fact_app_id> /tmp/fact_full.json
    python3 tools/patch_fact_avoid.py /tmp/fact_full.json --out=/tmp/fact_patched.json
    node tools/dify_push_graph.mjs --app=<fact_app_id> --graph=/tmp/fact_patched.json --port=9238
    node tools/dify_publish.mjs    --app=<fact_app_id> --port=9238
    # 然后必须重跑 MAIN：
    python3 tools/build_main_graph.py

退出码：0 成功；1 失败
"""

import json
import sys

OLD_SIG = "function main({ fact_text, grade_text, check_text, override_sensitive }) {"
NEW_SIG = "function main({ fact_text, grade_text, check_text, override_sensitive, avoid_words }) {"

# 插在签名之后（紧跟函数第一行）
PARSE_BLOCK = """  /* 超纲词回灌通路（2026-09-20）：MAIN 图的 nodeClean 取自本图（FACT 版），
     而 4 个生成节点的提示词引用了 {{#nodeClean.avoid_a1#}} 这类变量 ——
     FACT 侧不补这段，MAIN 会因「变量不存在」跑不起来（重拼 MAIN 时静态校验抓到）。
     FACT 自身用不到 avoid_words（前端调 FACT 时不传），缺省按空处理，不影响抽取链路。
     容错原则与 GEN 侧一致：非 JSON / 缺字段 / 类型不对，一律当空，绝不抛错。 */
  let av = {};
  try { const o = JSON.parse(avoid_words || '{}'); if (o && typeof o === 'object') av = o; } catch (e) { }
  const fmtAvoid = (a) => (Array.isArray(a) && a.length)
    ? (a.join(', ') + '（共 ' + a.length + ' 个）')
    : '（本轮无 —— 上一稿本档已达标，请保持同样的用词水平）';"""

RET_OLD = "    sensitive: sensLevel + ' / ' + sensAction + ' / ' + sensReason,"
RET_NEW = RET_OLD + """
    avoid_a1: fmtAvoid(av.A1), avoid_a2: fmtAvoid(av.A2),
    avoid_b1: fmtAvoid(av.B1), avoid_b2: fmtAvoid(av.B2),"""

AVOID_MAX_LEN = 4000
SUFFIXES = ('a1', 'a2', 'b1', 'b2')


def fail(msg):
    print("✗ " + msg)
    return 1


def main():
    args = sys.argv[1:]
    if not args:
        return fail("用法: python3 tools/patch_fact_avoid.py <draft.json> [--out=<out.json>]")
    src = args[0]
    out = src
    for a in args[1:]:
        if a.startswith("--out="):
            out = a.split("=", 1)[1]

    with open(src, encoding="utf-8") as f:
        draft = json.load(f)

    nodes = (draft.get("graph") or {}).get("nodes")
    if not nodes:
        return fail("%s 里没有 graph.nodes —— 这是 dump_full_draft.mjs 的产物吗？" % src)

    by_id = {n.get("id"): n for n in nodes}
    report = []

    # ---- 1. nodeStart 加 avoid_words ----
    start = by_id.get("nodeStart")
    if not start:
        return fail("找不到 nodeStart")
    vars_ = start["data"].setdefault("variables", [])
    exist = next((v for v in vars_ if v.get("variable") == "avoid_words"), None)
    if exist is None:
        tpl = next((dict(v) for v in vars_ if v.get("type") == "paragraph"), None)
        if tpl is None:
            return fail("nodeStart 里没有 paragraph 类型变量可作模板")
        tpl["variable"] = "avoid_words"
        tpl["label"] = "上一稿超纲词（按档 JSON）"
        tpl["required"] = False
        tpl["max_length"] = AVOID_MAX_LEN
        vars_.append(tpl)
        report.append("nodeStart.avoid_words   +新增入参 (max_length=%d)" % AVOID_MAX_LEN)
    else:
        report.append("nodeStart.avoid_words   已存在，跳过")

    # ---- 2~5. nodeClean ----
    clean = by_id.get("nodeClean")
    if not clean:
        return fail("找不到 nodeClean")
    code = clean["data"].get("code", "")
    if "avoid_a1" in code:
        report.append("nodeClean.code         已改造，跳过")
    else:
        if code.count(OLD_SIG) != 1:
            return fail("nodeClean.code 签名出现 %d 次（期望 1 次），拒绝盲改" % code.count(OLD_SIG))
        if code.count(RET_OLD) != 1:
            return fail("nodeClean.code 里 return 锚点出现 %d 次（期望 1 次），拒绝盲改" % code.count(RET_OLD))
        code = code.replace(OLD_SIG, NEW_SIG + "\n" + PARSE_BLOCK, 1)
        code = code.replace(RET_OLD, RET_NEW, 1)
        clean["data"]["code"] = code
        report.append("nodeClean.code         签名 + 解析块 + return 四字段")

    outs = clean["data"].setdefault("outputs", {})
    added = [f"avoid_{s}" for s in SUFFIXES if f"avoid_{s}" not in outs]
    for name in added:
        outs[name] = {"children": None, "type": "string"}
    report.append("nodeClean.outputs      %s" % (("+声明 " + "/".join(added)) if added else "已齐备，跳过"))

    cins = clean["data"].setdefault("variables", [])
    if any(v.get("variable") == "avoid_words" for v in cins):
        report.append("nodeClean.variables    已存在，跳过")
    else:
        cins.append({"variable": "avoid_words", "value_selector": ["nodeStart", "avoid_words"]})
        report.append("nodeClean.variables    +映射 nodeStart.avoid_words")

    with open(out, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=1)

    print("✓ FACT 回灌通路改造完成 → %s\n" % out)
    for line in report:
        print("   ", line)
    print()
    print("下一步：")
    print("    node tools/dify_push_graph.mjs --app=<fact_app_id> --graph=%s --port=9238" % out)
    print("    node tools/dify_publish.mjs    --app=<fact_app_id> --port=9238")
    print("    python3 tools/build_main_graph.py     # 必须重拼 MAIN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
