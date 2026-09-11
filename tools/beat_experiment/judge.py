#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判定层：用另一个模型（DeepSeek-V4-Pro）当裁判，逐节拍判「是否覆盖 / 是否与原意一致 / 有无编造」。

用不同模型做裁判，是为了避免「自己生成的自己评」的自偏好偏差。
"""
import json, os, sys, re, urllib.request, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "/Users/jinsongli/WorkBuddy/2026-09-10-10-51-04/readpal"
JUDGE = "deepseek-ai/DeepSeek-V4-Pro"

RUBRIC = """你是英语分级阅读内容的事实核查员。下面是【素材原文】、从素材提炼的【节拍表】、以及基于节拍表生成的【分级文章】。

请逐条判定，只输出严格 JSON，不要 markdown 代码块，不要解释。

对每一个节拍，判定三件事：
- covered：这篇文章**是否讲到了这个节拍的核心意思**（语言可以极简，只要意思在就算 covered=true）。
- consistent：如果讲到了，**是否与素材原意一致**。特别注意四类失真：
    * 方向被改反（增加↔减少、上升↔下降、有利↔不利）
    * 对象被换错（把 A 地区的事安到 B 地区、把甲机构的话安到乙机构）
    * 程度被夸大或缩水（"0.5%" 写成 "half of all cases"、"下降" 写成 "彻底消除"）
    * 因果被颠倒（把"气候导致分布移动"写成"防控导致气候变暖"之类）
  没有讲到则 consistent 填 null。
- anchors_missing：本应出现但文章里**确实没出现**的核心锚点（逐字比对，数字写成英文单词也算出现）。

另外判定：
- fabricated：文章里出现的、**素材中完全没有依据**的数字/百分比/年份/人名/机构名/地名（逐条列出原文片段；没有就给空数组）
- verdict：一句话总评，指出最需要修的问题

输出格式（严格 JSON）：
{"beats":[{"id":1,"covered":true,"consistent":true,"anchors_missing":[],"note":"..."}],
 "fabricated":[{"quote":"...","why":"..."}],
 "verdict":"..."}
"""


def call(prompt, max_tokens=3000, model=JUDGE):
    key = json.load(open(os.path.join(REPO, "backend/keys.fallback.json"), encoding="utf-8"))["SF_API_KEY"]
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.0, "max_tokens": max_tokens, "stream": False,
                       "enable_thinking": False}).encode("utf-8")
    req = urllib.request.Request("https://api.siliconflow.cn/v1/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                                 method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    return d["choices"][0]["message"].get("content") or "", d.get("usage") or {}, time.time() - t0


def extract_json(text):
    s = text.replace("```json", "").replace("```", "").strip()
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b < 0:
        return None
    frag = s[a:b + 1]
    for cand in (frag, re.sub(r",(\s*[\]\}])", r"\1", frag)):
        try:
            return json.loads(cand)
        except Exception:
            pass
    return None


def main():
    mat = open(os.path.join(HERE, "material.txt"), encoding="utf-8").read().strip()
    beats = json.load(open(os.path.join(HERE, "beats.json"), encoding="utf-8"))["beats"]
    bt = "\n".join("%d. %s\n   核心锚点: %s\n   进阶锚点: %s" % (
        b["id"], b["point"], "、".join(b["anchors_core"]), "、".join(b["anchors_adv"])) for b in beats)

    files = sys.argv[1:] or ["out_A1_1.json", "out_B2P_3.json"]
    for fn in files:
        p = os.path.join(HERE, fn) if not os.path.isabs(fn) else fn
        if not os.path.exists(p):
            print("!! 缺 %s" % p); continue
        d = json.load(open(p, encoding="utf-8"))
        obj = d.get("parsed") or extract_json(d.get("raw") or "")
        paras = (obj or {}).get("paras") or []
        article = "\n\n".join("[P%d] %s" % (i, x) for i, x in enumerate(paras, 1))
        prompt = "%s\n\n【素材原文】\n%s\n\n【节拍表（共 %d 个）】\n%s\n\n【分级文章（%s）】\n%s\n\n请判定。" % (
            RUBRIC, mat, len(beats), bt, d["level"], article)
        raw, usage, dt = call(prompt)
        res = extract_json(raw)
        json.dump({"file": fn, "level": d.get("level"), "judge_raw": raw, "judge": res, "elapsed": dt, "usage": usage},
                  open(os.path.join(HERE, "judge_%s.json" % fn), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("=" * 96)
        print("【%s / %s】裁判耗时 %.1fs" % (d.get("level"), fn, dt))
        if res is None:
            print("!! 裁判 JSON 解析失败：", raw[:400]); continue
        bs = res.get("beats") or []
        cov = sum(1 for b in bs if b.get("covered"))
        con = sum(1 for b in bs if b.get("consistent") is True)
        incon = [b for b in bs if b.get("consistent") is False]
        print("  节拍覆盖 %d/%d   语义一致 %d/%d   不一致: %s" % (
            cov, len(beats), con, cov, [b["id"] for b in incon] or "无"))
        for b in bs:
            flag = "✅" if (b.get("covered") and b.get("consistent") is not False) else "❌"
            print("   %s #%d covered=%s consistent=%s %s" % (
                flag, b["id"], b.get("covered"), b.get("consistent"),
                ("| 缺锚点:" + "、".join(b.get("anchors_missing") or [])) if b.get("anchors_missing") else ""))
            if b.get("note"):
                print("        note: %s" % str(b["note"])[:190])
        fab = res.get("fabricated") or []
        print("  编造事实 %d 条: %s" % (len(fab), json.dumps(fab, ensure_ascii=False)[:400] if fab else "无 ✅"))
        print("  总评: %s" % str(res.get("verdict"))[:300])


if __name__ == "__main__":
    main()
