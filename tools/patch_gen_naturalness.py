#!/usr/bin/env python3
"""GEN 图改造：生成文章的语言自然度（2026-09-20）

背景：Bryan 反馈生成的文章「内容没问题，但语言不够 natural / 不像 native」。
实测举例（线上产出）：
    生成：A study shows that good family help is not enough. People with good family help
          do not live long if they eat bad food and sleep at bad times.
    期望：A study shows that family help is not enough. People may not live long if they
          eat bad food and do not sleep well.

核查结论（一手实测，非推测）：**主因是提示词，不是模型**。
同一模型下 B2+ 输出明显最自然，A1-/A2 最生硬 —— 而提示词约束恰好也是
「B2+ 最松、A1-/A2 最紧」。锁死自然度的四条约束：

  1. 「禁用习语/隐喻」（A1-/A2 独有）  → 地道搭配被禁，只剩主谓宾直陈句
  2. 「实词重复鼓励」（A1-/A2 独有）    → 直接造出 Bryan 例句里重复的 good family help
  3. 语法表「假设/反事实意义的 would/could/might 禁用」→ 不敢写 may not live long，
     只能写 do not live long —— **把可能性写成确定，语义错误**
  4. 词表天花板 + 「平均音节 ≤1.4/1.5」  → 实测把 university 逼成 school

做四项改动（**幂等**，重复跑不会重复插入）：

  A. A1- / A2 词汇层：拆掉「禁用习语/隐喻」「实词重复鼓励」，改为
     「鼓励高频固定搭配 + 同段不得原样重复名词短语」；超纲率上限按产品拍板放宽
     （A1 5%→7% / A2 8.1%→10%），为地道搭配腾出空间。
  B. A1- / A2 语法表：把「假设/反事实」与「可能性」分开 —— may/might 表「可能」放行。
     这是**回归教研《语法 Construction 清单 v1.1》原意**（原文禁的是假设/反事实意义），
     不是擅自放宽。
  C. 四档插入【语言地道性】硬性要求（正向引导，与分级参数同等硬性）。
  D. nodeValidate 新增「自然度粗筛」（只 warn 不 fail）：段内重复名词短语 /
     已知中式搭配 / 收尾套话过量。

用法：
    # 1) 先从线上草稿拉完整对象（必须带 features，否则推送会清空应用特性）
    DIFY_CDP_PORT=9238 node tools/dump_full_draft.mjs <gen_app_id> /tmp/gen_full.json
    # 2) 改造
    python3 tools/patch_gen_naturalness.py /tmp/gen_full.json --out=/tmp/gen_nat.json
    # 3) 推送 + 发布
    node tools/dify_push_graph.mjs --app=<gen_app_id> --graph=/tmp/gen_nat.json --port=9238
    node tools/dify_publish.mjs    --app=<gen_app_id> --port=9238

⚠️ 与 patch_gen_graph.py（词汇回灌）**互不冲突**，但两者都改写提示词，
   顺序上先跑 patch_gen_graph.py 再跑本脚本（本脚本的锚点按回灌后的文案写的）。

退出码：0 成功；1 失败
"""

import json
import re
import sys

NAT_MARK = "【语言地道性"

# ── 改动 A：A1- / A2 词汇层 ────────────────────────────────────────────────
# 说明：同时把超纲率上限放宽（A1 5%→7% / A2 8.1%→10%）—— 产品侧拍板
#      「优先自然，超纲率可放宽」，理由是地道搭配几乎必然带超纲词。
VOCAB_FIX = {
    "nodeGenA1": (
        "超纲词率 ≤5%；每段新词 ≤1；topic words 3 个（豁免超纲，首次出现须有可推断语境）；"
        "平均音节 ≤1.4；8 字母以上词 ≤2%；短语动词仅限最高频 10 个；禁用习语/隐喻；实词重复鼓励。",
        "超纲词率 ≤7%；每段新词 ≤1；topic words 3 个（豁免超纲，首次出现须有可推断语境）；"
        "平均音节 ≤1.4；8 字母以上词 ≤2%；短语动词仅限最高频 10 个"
        "（get / take / look / live / eat 这类日常搭配鼓励用）；"
        "**鼓励日常固定搭配与常用语块**（如 live longer、sleep well、eat well、get enough rest）"
        "——这些正是母语者最自然的说法，不要为了「简单」而拆成生硬的字面表达；"
        "只禁生僻习语与文学性隐喻；实词允许自然复现（本档词表小，不要求换词），"
        "但**同一段内、以及相邻段落的首句，不得原样重复同一个名词短语**"
        "（第二遍改用代词、the + 概括词，或直接省略）。",
    ),
    "nodeGenA2": (
        "超纲词率 ≤8.1%；每段新词 ≤2；topic words 3–4 个（豁免超纲，首次出现须有可推断语境）；"
        "平均音节 ≤1.5；8 字母以上词 ≤4%；短语动词 ≤2 个/篇；禁用习语/隐喻；实词重复鼓励。",
        "超纲词率 ≤10%；每段新词 ≤2；topic words 3–4 个（豁免超纲，首次出现须有可推断语境）；"
        "平均音节 ≤1.5；8 字母以上词 ≤4%；短语动词 ≤2 个/篇；"
        "**鼓励日常固定搭配与常用语块**（如 live longer、sleep well、eat well、get enough rest）"
        "——这些正是母语者最自然的说法；只禁生僻习语与文学性隐喻；"
        "实词允许自然复现，但**同一段内、以及相邻段落的首句，不得原样重复同一个名词短语**"
        "（第二遍改用代词、the + 概括词，或直接省略）。",
    ),
}

# ── 改动 B：A1- / A2 语法表（假设 ≠ 可能性） ───────────────────────────────
PREF_FIX = {
    "nodeGenA1": (
        "can/can't+动词原形（能力·简单可能·允许）；",
        "can/can't+动词原形（能力·允许·简单可能）；"
        "may/might+动词原形（可能性——研究结论尚不确定时必须用它，"
        "例如 \"People may not live long\"）；",
    ),
    "nodeGenA2": (
        "to-不定式（简单目的）。",
        "to-不定式（简单目的）；may/might+动词原形（可能性——研究结论的不确定必须用它）。",
    ),
}

FORB_FIX = {
    "nodeGenA1": (
        "倒装/强调/虚拟语气；从句嵌套。",
        "倒装/强调/虚拟语气；从句嵌套。"
        "（⚠️ 口径澄清：这里禁的是「假设 / 反事实 / 虚拟语气」，**不是「可能性」**——"
        "may / might / can 表「可能」不在禁用之列，**必须保留使用**。）",
    ),
    "nodeGenA2": (
        "假设/反事实意义的 would/could/might；正式虚拟语气；",
        "假设/反事实意义的 would/could（即第二/三条件句那种「如果…就会…」）；正式虚拟语气；",
    ),
}

# A2 Forbidden 行末的补充澄清（与 PREF/FORB 同属改动 B）
A2_FORB_TAIL = (
    "倒装/强调/复杂名词化。",
    "倒装/强调/复杂名词化。"
    "（⚠️ 口径澄清：上面禁的是「假设 / 反事实」，**不是「可能性」**。"
    "may / might / can 表「可能」**必须保留使用**——研究结论不确定时写成 may/might。"
    "把 \"People may not live long\" 写成 \"People do not live long\" 是**语义错误**"
    "（把可能当成确定），不是简化。）",
)

# A2 Discouraged：原「新卡首句重复名词」是 good family help 重复的另一推手
A2_DISC_FIX = (
    "跨卡代词指代（新卡首句重复名词）。",
    "跨段代词指代（新段首句用话题词点明主语，但**不得原样照抄上一段的名词短语**"
    "——换用概括词或代词）。",
)

# ── 改动 C：四档共用的【语言地道性】 ────────────────────────────────────
NATURAL_SPEC = """
""" + NAT_MARK + """（与分级参数同等硬性，不得为了「简单」而牺牲自然）】
读者是英语学习者，产出必须是**母语者会说的话**，不是「把难词换成简单词」的字面直译。硬性要求：
① **优先用动词**：写 "People sleep badly"，不写 "People have bad sleep quality"。
② **搭配必须地道，禁止生造**：反面例子（本档已实测出现过，禁止再犯）——**"sleep at bad times"**（应为 "do not sleep well"）、"have bad sleep"。拿不准时，宁可换一个你确定地道的简单说法。
③ **禁止用定义句凑段**：连续两段都用 "X means Y. It means ..." 这种释义句式即不合格。要解释一个词，用一句自然的例子代替："Good habits, like eating well and sleeping well, help a lot."
④ **句式要有变化**：不要连续三句都是「主语 + 动词 + 宾语」的同一模板；相邻两句不要用同一个词开头。
⑤ **删冗余**：同一个名词短语不要在一段里原样出现两次。前句说过的，后句用代词（it / they / this）、概括词或直接省略。反面例子：**"People with good family help do not live long if ..." 紧跟在 "good family help is not enough" 之后 —— 应写成 "They may not live long if ..."**。
⑥ **不确定的事要写成不确定**：研究结论、可能性、推测必须用 may / might / can（"People **may** not live long if they eat badly"）。把 "may not live long" 写成 "do not live long" 是**语义错误**（把可能当成确定），不是简化。
⑦ **套话限量**："In the end," / "Small changes can help a lot." / "This is very important." 这类收尾套话，一篇里各自最多出现一次。"""

# ⑧ 是 v1 上线后补的，v3 又加强了一次：
#   v1 只堵了「用释义句凑段」这个凑数手段，却没交代替代方案 → 实测 A2 掉到 190 词（下限 240）；
#   v2 补了「不等于可以少写」→ 篇幅回来了，但 A1- 转而变成**每段只写 1 句**，
#   句长冲到 12.7（规格 7–9，判 fail）。⇒ 必须把「句数」也点明，并给出优先顺序。
NATURAL_TAIL = """
⑧ **本条不改变篇幅、句数、段数**：「删冗余、不写释义句」**不等于可以少写**。
- **写完必须逐段自检**：段落词数、每段句数、全篇段落数都要落在【本档硬性规格】的写作标尺区间内。
- **低档（A1- / A2）每段就是 2 句**：不得合成 1 句长句，也不得只写 1 句 —— 句数不足会同时造成篇幅偏短与句长超标，两项都判不合格。B1 / B2+ 按本档写作标尺给出的句数写足。
- 需要展开时，用**具体例子、具体动作、具体后果**来写（"A person who stays up late may feel tired even with a loving family."），不要退回 "X means Y" 的释义句。"""
NATURAL_SPEC = NATURAL_SPEC + NATURAL_TAIL
# 用于给「已推过 v1」的图补 ⑧（v1 的图里已经有 ⑦，不能整段重插）
NAT_T7_ANCHOR = '⑦ **套话限量**：'

# ── 改动 D：nodeValidate 新增「自然度粗筛」 ───────────────────────────────
NAT_CHECK_MARK = "自然度粗筛"
V_OLD_ANCHOR = "    let idKeys = [];"
V_NEW_BLOCK = """    /* 自然度粗筛（v2 · 2026-09-20，只 warn 不 fail）—— 针对实测「翻译腔」的可机械判定症状：
       ① 段内原样重复同一名词短语（实测 A2 首段 "good family help" 说两遍）；
       ② 已知的中式搭配硬凑（"sleep at bad times" 这类「介词 + 好/坏 + 时间」结构）；
       ③ 收尾套话过量（"In the end," 一篇里出现两次以上）。
       只告警不判 fail —— 自然度的最终判定权在教研，这里只负责把可疑项摆到审核台上。
       ⚠️ 不要往这里加需要语义理解的规则（那类问题交给 ⑨ 大意复核 + 人工审核）。 */
    {
      const nat = [];
      /* 取一句话里的「内容词对」（2 词窗口，剔除功能词） */
      const bgOf = (s) => {
        const ws = String(s || '').toLowerCase().replace(/[^a-z\\s']/g, ' ').split(/\\s+/).filter(Boolean);
        const out = [];
        for (let i = 0; i < ws.length - 1; i++) {
          if (STOP[ws[i]] || STOP[ws[i + 1]]) continue;
          const g = ws[i] + ' ' + ws[i + 1];
          if (out.indexOf(g) < 0) out.push(g);
        }
        return out;
      };
      /* 功能词表：只统计「内容词对」。必须够全 —— 实测漏掉助动词时会报出
         「句 22-23 重复「people should」」这类**正常写作**的噪音（v2 首跑实测），
         噪音一多这条 warn 就没人看了。 */
      const STOP = { the: 1, a: 1, an: 1, of: 1, to: 1, in: 1, on: 1, at: 1, and: 1, or: 1,
        for: 1, with: 1, is: 1, are: 1, was: 1, were: 1, be: 1, been: 1, being: 1, am: 1,
        it: 1, its: 1, this: 1, that: 1, these: 1, those: 1, they: 1, them: 1, their: 1,
        he: 1, she: 1, him: 1, his: 1, her: 1, you: 1, your: 1, we: 1, us: 1, our: 1,
        i: 1, me: 1, my: 1, as: 1, by: 1, from: 1, but: 1, not: 1, no: 1,
        do: 1, does: 1, did: 1, can: 1, may: 1, might: 1, will: 1, would: 1, could: 1,
        should: 1, must: 1, has: 1, have: 1, had: 1, more: 1, most: 1, much: 1, many: 1,
        very: 1, also: 1, than: 1, then: 1, when: 1, where: 1, why: 1, how: 1, who: 1,
        which: 1, what: 1, if: 1, so: 1, such: 1, other: 1, another: 1, same: 1,
        into: 1, out: 1, up: 1, down: 1, over: 1, after: 1, before: 1, between: 1,
        during: 1, while: 1, because: 1, although: 1, since: 1, until: 1, about: 1,
        there: 1, here: 1 };
      /* 🔴 v1 的教训（实测）：v1 是「先按换行切段，再在同一段内找重复」，但
         **不能假定 body[key] 里一定有换行** —— v1 上线实测把整篇当成一段，于是报出
         「第 1 段内重复：people live / family help / daily habits」这类**全篇级误报**
         （主题词在同一篇里重复出现是正常的英语写法）。
         ⇒ 判据必须对分段方式不敏感：改为**按句子切分 + 只看相邻句对**，有没有换行都成立。 */
      const sents = String(body[key] || '').split(/[.!?]+/).map((s) => s.trim()).filter(Boolean);
      const rep = [];
      for (let i = 0; i < sents.length - 1; i++) {
        const a = bgOf(sents[i]), b = bgOf(sents[i + 1]);
        const hit = a.filter((g) => b.indexOf(g) >= 0);
        if (hit.length) rep.push('句 ' + (i + 1) + '-' + (i + 2) + ' 重复「' + hit.slice(0, 2).join(' / ') + '」');
      }
      if (rep.length) nat.push(rep.slice(0, 3).join('；') + (rep.length > 3 ? ' 等 ' + rep.length + ' 处' : ''));
      const zhStyle = String(body[key] || '').match(/\\b(?:at|in|on)\\s+(?:bad|good|wrong|right)\\s+(?:time|times|moment|moments)\\b/gi) || [];
      if (zhStyle.length) {
        const uniq = [];
        zhStyle.forEach((s) => { const t = s.toLowerCase().replace(/\\s+/g, ' '); if (uniq.indexOf(t) < 0) uniq.push(t); });
        nat.push('疑似中式搭配：' + uniq.slice(0, 3).join(' / '));
      }
      const wrap = (String(body[key] || '').match(/\\bin the end\\s*,?/gi) || []).length;
      if (wrap > 1) nat.push('收尾套话 "In the end" 出现 ' + wrap + ' 次');
      if (nat.length) checks.push({ name: '"""+NAT_CHECK_MARK+"""', status: 'warn', detail: nat.join('；') });
      else checks.push({ name: '"""+NAT_CHECK_MARK+"""', status: 'pass', detail: '' });
    }
""" + V_OLD_ANCHOR

V_OLD_TOTAL = "total_checks: ALL.length * 9,"
V_NEW_TOTAL = "total_checks: ALL.length * 10,"


def fail(msg):
    print("✗ " + msg)
    return 1


def prompt_text(node):
    return "".join(s.get("text", "") for s in (node["data"].get("prompt_template") or [])
                   if isinstance(s, dict))


def set_prompt_text(node, new_text):
    node["data"]["prompt_template"] = [{"role": "system", "text": new_text}]


def sub_once(txt, node_id, pair, label, report):
    """锚点在整篇里必须恰好出现一次，否则拒绝盲改。

    🔴 幂等判据必须用 `new in txt`，**不能**写 `new in txt and old not in txt`：
    有两处替换的新文案是以旧文案**开头**再追加澄清句（Forbidden 行末口径澄清），
    旧文案在新文案里仍然存在 —— 那种写法第二次跑会再插一遍澄清句，
    得到「（⚠️ 口径澄清…）（⚠️ 口径澄清…）」的重复文案，且脚本回报"成功"。
    （实测踩到，靠幂等回归才发现。）
    """
    old, new = pair
    if new in txt:
        report.append("%-12s %s 已是新文案，跳过" % (node_id, label))
        return txt, False
    n = txt.count(old)
    if n != 1:
        raise RuntimeError("%s 的锚点「%s」在提示词里出现 %d 次（期望 1 次）—— 请人工核对线上图"
                           % (node_id, label, n))
    report.append("%-12s %s 已替换" % (node_id, label))
    return txt.replace(old, new, 1), True


def main():
    args = sys.argv[1:]
    if not args:
        return fail("用法: python3 tools/patch_gen_naturalness.py <draft.json> [--out=<out.json>]")
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

    try:
        # ---- A + B + C：四个生成节点 ----
        for nid in ("nodeGenA1", "nodeGenA2", "nodeGenB1", "nodeGenB2p"):
            node = by_id.get(nid)
            if not node:
                return fail("找不到节点 %s" % nid)
            txt = prompt_text(node)
            changed = False

            if nid in VOCAB_FIX:
                txt, c = sub_once(txt, nid, VOCAB_FIX[nid], "词汇层（搭配+重复+超纲率）", report)
                changed |= c
            if nid in PREF_FIX:
                txt, c = sub_once(txt, nid, PREF_FIX[nid], "Preferred 加 may/might", report)
                changed |= c
            if nid in FORB_FIX:
                txt, c = sub_once(txt, nid, FORB_FIX[nid], "Forbidden 拆开假设与可能", report)
                changed |= c
            if nid == "nodeGenA2":
                txt, c = sub_once(txt, nid, A2_FORB_TAIL, "Forbidden 行末口径澄清", report)
                changed |= c
                txt, c = sub_once(txt, nid, A2_DISC_FIX, "Discouraged 去重复推手", report)
                changed |= c

            # C：四档都插【语言地道性】（A1-/A2 插在【语篇层】之后）
            if NAT_MARK in txt:
                report.append("%-12s 【语言地道性】已存在，跳过" % nid)
            else:
                m = re.search(r"【语篇层】[^\n]*", txt)
                if not m:
                    return fail("%s 提示词里找不到【语篇层】，无法确定插入位置" % nid)
                txt = txt[:m.end()] + NATURAL_SPEC + txt[m.end():]
                report.append("%-12s 【语言地道性】+插入（%d 字符）" % (nid, len(NATURAL_SPEC)))
                changed = True

            if changed:
                set_prompt_text(node, txt)

        # ---- D：nodeValidate ----
        vnode = by_id.get("nodeValidate")
        if not vnode:
            return fail("找不到 nodeValidate")
        code = vnode["data"].get("code", "")
        if NAT_CHECK_MARK in code:
            report.append("%-12s 自然度粗筛 已存在，跳过" % "nodeValidate")
        else:
            if code.count(V_OLD_ANCHOR) != 1:
                return fail("nodeValidate 里 %r 出现 %d 次（期望 1 次）—— 拒绝盲改"
                            % (V_OLD_ANCHOR, code.count(V_OLD_ANCHOR)))
            if code.count(V_OLD_TOTAL) != 1:
                return fail("nodeValidate 里 %r 出现 %d 次（期望 1 次）—— 拒绝盲改"
                            % (V_OLD_TOTAL, code.count(V_OLD_TOTAL)))
            code = code.replace(V_OLD_ANCHOR, V_NEW_BLOCK, 1)
            code = code.replace(V_OLD_TOTAL, V_NEW_TOTAL, 1)
            vnode["data"]["code"] = code
            report.append("%-12s 自然度粗筛 +新增检查项（total_checks 9→10）" % "nodeValidate")

    except RuntimeError as e:
        return fail(str(e))

    with open(out, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=1)

    print("✓ 改造完成 → %s\n" % out)
    for line in report:
        print("   ", line)
    print()
    print("下一步：")
    print("    node tools/dify_push_graph.mjs --app=<gen_app_id> --graph=%s --port=9238" % out)
    print("    node tools/dify_publish.mjs    --app=<gen_app_id> --port=9238")
    return 0


if __name__ == "__main__":
    sys.exit(main())
