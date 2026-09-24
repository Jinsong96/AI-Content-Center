#!/usr/bin/env python3
"""
分级卡片「合规审计」—— 补齐 build_cards.py 不覆盖的教研规则。

build_cards.py 管的是数值指标（占比/句长/主题词/引用/答案分布）。
本脚本管的是它管不了的**语义与结构**问题：
  1. 题型结构（依范例：A1-/A2 Q1 语境词义、B1 Q3 作者态度）
  2. A1-/A2 里的被动语态（教研禁被动）
  3. A1-/A2 里的推测语气词（教研文档未列入白名单）
  4. 「推测写成断言」嫌疑（母稿有 may/might/assume，改写稿只剩断言）
  5. 跨卡信息搬移（A1-/A2 第 N 卡出现母稿第 N 卡没有的关键名词）
  6. FLAG 词残留

用法：  python audit_a1.py [articles]
输出：  只报问题；无问题则打印「未发现」。
"""
import json, re, sys
from pathlib import Path

# ---------- 判据 ----------
# ⚠️ 分词那一段必须是**小写**（去掉 re.I 的整串匹配）：否则 "His name was Beethoven."
#    里 Beethoven 以 en 结尾会被当成过去分词，报成假被动。
BE_PASSIVE = re.compile(
    r"\b((?i:is|are|was|were|be|been|being|get|gets|got))\s+"
    r"([a-z]+(?:ed|en)|born|built|cut|put|made|held|sent|told|found|shown|kept|"
    r"taken|given|grown|taught|known|seen|used)\b")
# be born 是 A1 唯一无法回避的被动，白名单放行
PASSIVE_OK = {"are born", "is born", "was born", "were born"}
# 情感形容词做表语时形如被动，实为形容词（He was excited.）——不算被动
# 另收「以 en 结尾但不是分词」的副词，它们会被分词正则误抓（is even / is often）
# 以及 get + 疑问副词（you get when the weekend is over）——「when」以 en 结尾，同属误抓
ADJ_OK = {"excited", "interested", "surprised", "tired", "worried", "scared",
          "amazed", "frightened", "bored", "pleased", "crowded",
          "even", "often", "open", "seven", "eleven", "children", "women",
          "when", "then", "men", "women"}

SPEC_A1 = ["might", "may", "perhaps", "probably", "maybe", "possibly",
           "seem", "seems", "i think", "you think", "assume", "expect"]
SPEC_A2 = ["might", "may", "perhaps", "probably", "maybe", "possibly",
           "seem", "seems", "you think", "i think"]
# 这些说法能保留母稿的「预设/悬念」层，等价于推测语气，不算写成断言
# 「not always」是我加的一条：母稿 may not be taught（可能学不到）无法用 may 复现时，
#   用一般现在时的 not always 保留"并非总是"的模糊层，比写成 does not teach（断言）更保真。
HEDGE_OK = ["people think", "many people think", "some people think",
            "people believe", "we think", "do you think", "not always"]

FLAG_A1 = ["may", "might", "if", "which", "whose", "who", "would", "been",
           "should", "must", "although", "however", "while"]
FLAG_A2 = ["which", "whose", "might", "may", "although", "whereas",
           "had been", "would have"]

B1_SPEC = ["might", "may", "assume", "expect", "seem", "perhaps", "probably"]

KEY_NOUN = re.compile(
    r"\b(groups?|milk|teeth|flippers|legs?|forest|soil|water|wind|horses?|king|"
    r"soldiers?|school|garden|seeds?|pot|window|paper|hobbies|hobby|stamps?|"
    r"photograph\w*|whales?|insect\w*|spider\w*|magnets?|money|app|phone)\b")
# 同义替换白名单：降级改写把母稿的词换成更常用的说法，不算跨卡搬移
SYN = {
    "water": ["ocean", "oceans", "sea", "seas", "river",    # 母稿 oceans → 改写 water
              "flood", "floods", "flooded"],              # 母稿 flooded lands → 改写 water
    "school": ["class", "classes", "teacher", "teachers",     # 母稿 class project → 改写 school project
               "childcare", "center", "centre", "nursery",   # 母稿 childcare center → 改写 school（新闻 03）
               "kindergarten", "university", "college"],
    "leg": ["crippled", "lame", "leg", "legs"],              # 母稿 the crippled boy → 改写 the boy with the bad leg
    "teeth": ["tooth", "baleen", "jaws"],
    "hobby": ["hobbies", "pastime"],
    "stamps": ["stamp", "collect"],
    "pot": ["stew", "soup", "cook"],                       # 母稿 stew → 改写补一句 cook ... in a pot（释义性补充）
    # 新闻：母稿的「$250 billion spent on development」「wealth distribution」降级成 money
    # （把金额、wealth 直白成 money 是正常降级，不是跨卡搬移）2026-09-24 加
    "money": ["billion", "billionaire", "spent", "spending", "wealth", "funding",
              "assistance", "dollars", "cash",
              # 新闻 05：母稿「comes at a high price」「$1,999」→ 改写 money
              "price", "prices", "expensive", "cost", "costs", "paid", "pays",
              # 新闻 07：母稿「As economic growth increased people's incomes」→ 改写 money
              "income", "incomes", "salary", "salaries", "wage", "wages",
              # 新闻 15：母稿「a "meme coin" is a cryptocurrency」→ 改写 money（2026-09-24 加）
              "cryptocurrency"],
}


def _present(x: str, b: str) -> bool:
    """关键词是否出现在母稿同卡中；容忍单复数差异
    （母稿 'the insect world' → 改写 'insects'，不是跨卡搬移。2026-09-24 修）"""
    if x in b:
        return True
    return x.endswith("s") and x[:-1] in b


def load_cards(folder: Path):
    """返回 (cards.json 对象, 母稿切卡列表)。母稿级 = 层级序列里最高的那一级。"""
    d = json.loads((folder / "cards.json").read_text(encoding="utf-8"))
    orig = re.sub(r"\s+", " ", (folder / "original.txt").read_text(encoding="utf-8")).strip()
    starts = d.get("b2_card_starts") or d.get("b1_card_starts")
    if not starts:
        raise ValueError("cards.json 里既没有 b1_card_starts 也没有 b2_card_starts")
    pos, idx = 0, []
    for s in starts:
        i = orig.find(s, pos); idx.append(i); pos = i + 1
    idx.append(len(orig))
    return d, [orig[idx[k]:idx[k + 1]].strip() for k in range(len(starts))]


def qtype(q: str) -> str:
    t = q.lower()
    if " mean " in t or 'mean in card' in t:
        return "词义"
    if "attitude" in t or "think of" in t or "feel about" in t:
        return "态度"
    # 母稿级（B2+）的 Q3 是主旨/写作目的题：What is the main purpose of ... ?
    if "purpose" in t or "main idea" in t or "mainly about" in t or "best title" in t:
        return "目的"
    # 只把真正的"为什么"问句算原因题：以 why 开头，或 why + 助动词。
    # 反例：「Which of these is NOT a reason why marbles are popular?」是细节题，
    #   不能因为句子里出现 why 就判成原因题（2026-09-24 修正）。
    if t.startswith("why") or re.search(r"\bwhy (did|do|does|was|were|is|are|has|have)\b", t):
        return "原因"
    return "细节"


# 题型结构（依范例 example_honesty，逐题对位）
# 三级：母稿 B1；四级：母稿 B2+（多出那一级的题型是范例实读，非推测）
WANT = {
    3: {"A1-": ["词义", "细节", "原因"], "A2": ["词义", "原因", "细节"],
        "B1": ["细节", "原因", "态度"]},
    4: {"A1-": ["词义", "细节", "原因"], "A2": ["词义", "原因", "细节"],
        "B1": ["细节", "原因", "态度"], "B2+": ["词义", "原因", "目的"]},
}


def audit(folder: Path) -> tuple:
    """返回 (问题列表, 提示列表)"""
    out, hints = [], []
    d, base_cards = load_cards(folder)
    LEVELS = [lv for lv in ("A1-", "A2", "B1", "B2+") if lv in d.get("levels", {})]
    base = LEVELS[-1]                      # 母稿那一级（原文，不查合规）
    n = len(base_cards)
    want = WANT[4 if base == "B2+" else 3]
    # 主题词（topic_words）：整篇反复出现的词，改写里用名词替换母稿的代词属正常降级，
    # 不算跨卡搬移，故从跨卡检查里排除（2026-09-24 修）
    topic = {w.lower().rstrip("s") for w in d.get("topic_words", [])}

    # 1. 题型结构（Bryan 2026-09-24 拍板：按范例 example_honesty 的结构，逐题对位，不只看 Q1）
    for lv in LEVELS:
        qs = d["levels"][lv].get("questions", [])
        got = [qtype(q["q"]) for q in qs]
        if len(got) != 3:
            out.append(f"[题型] {lv} 题目数量 {len(got)}，应为 3")
            continue
        if got != want[lv]:
            bad = [f"Q{i+1} 应为「{want[lv][i]}」，实为「{got[i]}」"
                   for i in range(3) if got[i] != want[lv][i]]
            out.append(f"[题型] {lv} 结构不符：{'；'.join(bad)}")

    # ⚠️ 被动 / FLAG 只对 **A1- 与 A2** 检查 —— 教研明文：
    #   A1-「禁用从句、may/might/must、if、动名词作主语、被动」
    #   A2 「加上现在完成、will、should/must/have to、when/if/because 从句、who/that 短关系从句」
    #   B1 「加上 which/whose、第二类条件句、**被动**、间接引语、however/although」← B1 允许被动与 which
    #   所以母稿是 B2+ 时（四级），B1 是改写层也**不该**查被动/FLAG；照查会误报范例。
    STRICT = ("A1-", "A2")
    for lv in LEVELS:
        if lv not in STRICT:
            continue                    # 母稿原文 / B1 层：不查被动与 FLAG
        cards = d["levels"][lv]["cards"]
        if len(cards) != n:
            out.append(f"[对齐] {lv} {len(cards)} 卡 / {base} {n} 卡")
            continue
        spec = SPEC_A1 if lv == "A1-" else SPEC_A2
        flag = FLAG_A1 if lv == "A1-" else FLAG_A2
        for i, c in enumerate(cards):
            low = " " + re.sub(r"[^a-z' ]", " ", c.lower()) + " "

            # 2. 被动
            for a, b in BE_PASSIVE.findall(c):
                if f"{a} {b}".lower() in PASSIVE_OK or b.lower() in ADJ_OK:
                    continue
                out.append(f"[被动-{lv} 卡{i+1}] {a} {b} → {c}")

            # 3. 推测语气词
            hit = [w for w in spec if f" {w} " in low]
            if hit:
                hints.append(f"[推测词-{lv} 卡{i+1}] {hit} → {c}")

            # 6. FLAG 残留
            fh = [w for w in flag if f" {w} " in low]
            if fh:
                out.append(f"[FLAG-{lv} 卡{i+1}] {fh} → {c}")

            # 4. 推测写成断言（母稿有推测词，改写稿既无推测词也无"预设/模糊"说法）
            #    这是**提示**不是判错：改写稿也可能只是删掉了这层意思（=允许），
            #    需要人工看一眼是"删细节"还是"把猜测写成了事实"。
            b = base_cards[i].lower()
            bw = [w for w in B1_SPEC
                  if f" {w} " in " " + re.sub(r"[^a-z' ]", " ", b) + " "]
            if bw:
                keep = any(f" {w} " in low for w in spec) or any(p in c.lower() for p in HEDGE_OK)
                if not keep:
                    hints.append(f"[推测语气-{lv} 卡{i+1}] 母稿有 {bw}，改写稿无对应模糊说法"
                               f"（删掉这层意思=可；写成事实=需改）：\n"
                               f"        {base} : {base_cards[i]}\n        {lv}: {c}")

            # 5. 跨卡搬移
            miss = sorted({x for x in KEY_NOUN.findall(c.lower())
                           if x.rstrip("s") not in topic
                           and not _present(x, b)
                           and not any(s in b for s in SYN.get(x, []))})
            if miss:
                out.append(f"[跨卡嫌疑-{lv} 卡{i+1}] 出现母稿同卡无的关键词 {miss} → {c}")
    return out, hints


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "articles")
    folders = [root] if (root / "cards.json").exists() else \
        sorted(p for p in root.iterdir() if (p / "cards.json").exists())
    total = n_hint = 0
    for f in folders:
        try:
            issues, hints = audit(f)
        except Exception as e:
            print(f"== {f.name}\n  ✗ 审计失败：{e}\n"); continue
        total += len(issues); n_hint += len(hints)
        print(f"== {f.name}")
        if issues:
            for s in issues:
                print("  ! " + s)
        else:
            print("  ✓ 未发现结构/语义问题")
        for h in hints:
            print("  · " + h)
        print()
    print(f"共 {len(folders)} 篇：问题 {total} 条，提示 {n_hint} 条")
