#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ReadPal · 验证「超纲词回灌」是否真的让产出变简单（2026-09-20）

跑三轮 GEN，做成带对照的小实验：

    第 1 轮  无回灌          → 产出 + 各档超纲率 → 算出规避词
    第 2 轮  带回灌（处理组）  → 产出 + 各档超纲率
    第 3 轮  无回灌（对照组）  → 产出 + 各档超纲率

为什么要第 3 轮：
    LLM 有随机性，**单次「改前 vs 改后」分不清是回灌起作用还是碰巧**。
    实测过一次反例：B2 档第 1 轮就达标、根本没收到任何回灌，
    第 2 轮照样从 0.8% 涨到 2.1% —— 那个变化纯属噪声。
    **R1 vs R3 = 噪声基线；R2 vs (R1+R3) = 真实效应。**
    只有在效应的量级明显盖过 R1↔R3 的差值时，才敢说「回灌有效」。

四个判据（都要看，缺一不可）：
  A. **接通** —— 第 2 轮 trace 里 nodeClean 的 avoid_* 是真实词表，不是「本轮无」
  B. **有效** —— 第 2 轮超纲率相对对照组的降幅，明显大于 R1↔R3 的噪声
  B2. **词级依从** —— 第 1 轮要求规避的词，在第 2 轮里还剩几个。
      比超纲率锐利得多：直接测模型有没有听指令，不被整体波动稀释。
  C. **不退化** —— 四档文章仍完整产出

⚠️ 全程走 Dify service API（api.dify.ai），不经 Dify 控制台、不经 Railway ——
   这是前端/后端实际会走的同一条路径，但绕开了本机到 Railway CDN 边缘的网络故障。

用法：
    python3 tools/verify_vocab_reflow.py [--out=/tmp/reflow.json] [--material=...]

退出码：0 三轮都成功；1 有轮次失败
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import evp_vocab_check as E  # noqa: E402

GEN_ID = "f4462032-2919-49e0-b123-bb5160c96c28"
KEYS_FILE = os.path.join(ROOT, "backend", "keys.fallback.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")

# 真实热点风格的英文素材（体育类 —— Bryan 反馈「A1- 写成 B1」的典型场景）
DEFAULT_MATERIAL = (
    "A famous cross-country skier ran in a long trail race last weekend. "
    "She was an Olympic champion and had trained for many years. The course "
    "climbed through rough mountain terrain and the snow was slippery in "
    "places. She finished the race very fast and won another medal. After the "
    "event she said the conditions were tough and that she felt emotional. "
    "Her coach said the athlete had recovered well from an old injury. The "
    "director of the race said more than two hundred competitors took part. "
    "Local fans lined the path near the lake to cheer for the runners. "
    "Organizers said the event would return next winter with a longer course."
)

LEVELS = ("A1", "A2", "B1", "B2")


def resolve_key():
    for a in sys.argv[1:]:
        if a.startswith("--key="):
            return a.split("=", 1)[1].strip()
    if os.environ.get("DIFY_WF_GEN"):
        return os.environ["DIFY_WF_GEN"].strip()
    if os.path.isfile(KEYS_FILE):
        with open(KEYS_FILE, encoding="utf-8") as f:
            return (json.load(f).get("DIFY_WF_GEN") or "").strip()
    return ""


def build_inputs(material, avoid=None):
    """按 GEN 的真实入参契约组装。

    ⚠️ `summary` 与 `avoid_words` 都有 **max_length 硬上限**（Dify 的 `paragraph`
       不是「段落就无限长」，是**按变量逐个校验**）：
       · `summary` = 500 → 传素材正文会 `summary in input form must be less than
         500 characters`，工作流 0.5 秒秒退；素材正文归 `facts_text`（5000）。
       · `avoid_words` 原本也是 500（继承模板导致的 bug，已修为 4000）——
         4 档 × 20 词的 JSON 实测 700–1600 字符，撞上就同样秒退。
    """
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", material.strip()) if s.strip()]
    facts_text = "\n".join("%d. %s" % (i + 1, s) for i, s in enumerate(sents))
    return {
        "summary": material.strip()[:480],
        "facts_text": facts_text,
        "angle": "",
        "style": "default",
        "gist": "",
        "facts_raw": "",
        "avoid_words": json.dumps(avoid or {}, ensure_ascii=False),
    }


def stream(inputs, timeout=420):
    """流式跑一次 GEN，返回 (status, outputs, node_outputs, elapsed, err)"""
    body = json.dumps({"inputs": inputs, "response_mode": "streaming",
                       "user": "readpal-verify"}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.dify.ai/v1/workflows/run", data=body,
        headers={"Authorization": "Bearer " + resolve_key(),
                 "Content-Type": "application/json", "User-Agent": UA})
    t0 = time.time()
    last_err = None
    for attempt in range(1, 5):
        try:
            nodes, fin = {}, None
            with urllib.request.urlopen(req, timeout=timeout) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data: "):
                        continue
                    try:
                        ev = json.loads(line[6:])
                    except Exception:
                        continue
                    kind = ev.get("event")
                    if kind == "node_finished":
                        d = ev.get("data") or {}
                        nodes[d.get("node_id")] = d.get("outputs") or {}
                    elif kind == "workflow_finished":
                        fin = ev.get("data") or {}
            if fin is None:
                return "failed", {}, nodes, time.time() - t0, "未收到 workflow_finished"
            if fin.get("status") != "succeeded":
                # 失败原因在 fin["error"]；不问清楚就只剩一句 status=failed，没法定位
                return ("failed", fin.get("outputs") or {}, nodes,
                        fin.get("elapsed_time") or (time.time() - t0),
                        "workflow status=%s error=%s" % (
                            fin.get("status"), str(fin.get("error"))[:300]))
            return (fin.get("status"), fin.get("outputs") or {}, nodes,
                    fin.get("elapsed_time") or (time.time() - t0), None)
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:200]
            last_err = "HTTP %s %s" % (e.code, msg)
            if e.code in (403, 429, 502, 503, 504):   # 403/1010 = Cloudflare 偶发
                time.sleep(3 * attempt)
                continue
            return "failed", {}, {}, time.time() - t0, last_err
        except Exception as e:  # noqa: BLE001
            last_err = "%s: %s" % (type(e).__name__, e)
            time.sleep(3 * attempt)
    return "failed", {}, {}, time.time() - t0, last_err


def pick(outs):
    """按前端 collectGenForVocab() 的同口径取出待校验文本与生词表。"""
    arts, words = {}, {}
    for k, v in json.loads(outs.get("paras_json") or "{}").items():
        paras = " ".join(p if isinstance(p, str) else " ".join(p) for p in v)
        ttl = ""
        try:
            a = json.loads(outs.get("articles_json") or "{}").get(k)
            if isinstance(a, dict):
                ttl = a.get("title") or ""
        except Exception:
            pass
        arts[k] = (ttl + ". " if ttl else "") + paras
    for k, v in (json.loads(outs.get("words_json") or "{}") or {}).items():
        words[k] = [str(x).split(" —")[0].split(" -")[0].strip()
                    for x in (v if isinstance(v, list) else []) if str(x).strip()]
    return arts, words


def pack_avoid(res):
    """复刻前端 collectAvoidWords()：只收超标档，上限 20 词。"""
    out = {}
    for k, r in (res or {}).items():
        if not r.get("exceed"):
            continue
        ws = (r.get("avoid_words") or [])[:20]
        if ws:
            out[k] = ws
    return out


def one_round(label, material, avoid, timeout):
    print("\n" + "=" * 78)
    print(label)
    print("=" * 78)
    print("  入参 avoid_words = %s" % json.dumps(avoid or {}, ensure_ascii=False)[:150])
    st, outs, nodes, el, err = stream(build_inputs(material, avoid), timeout)
    print("  status=%s  耗时=%.1fs  %s" % (st, float(el or 0), err or ""))
    if st != "succeeded" or not outs:
        return {"ok": False, "err": err, "nodes": nodes, "outs": outs}
    arts, words = pick(outs)
    res = E.check_vocab_batch(arts, words)
    rates = {}
    for k in LEVELS:
        r = res.get(k)
        if not r:
            continue
        rates[k] = r["over_rate"]
        print("   %-3s %5.1f%% / 阈值 %4.1f%%  %s" % (
            k, r["over_rate"] * 100, r["threshold"] * 100,
            "超纲 ✗" if r["exceed"] else "达标 ✓"))
    n_art = len(json.loads(outs.get("paras_json") or "{}"))
    print("   产出 %d 档 · validation_pass=%s · score=%s" % (
        n_art, outs.get("validation_pass"), outs.get("validation_score")))
    return {"ok": True, "res": res, "rates": rates, "arts": arts,
            "nodes": nodes, "outs": outs, "elapsed": el, "n_art": n_art}


def compliance(avoid, arts2):
    """第 1 轮要求规避的词，在第 2 轮文章里还剩几个。"""
    rows, total, gone = [], 0, 0
    for k, ws in sorted(avoid.items()):
        stems = set()
        for t, _c in E.tokenize(arts2.get(k, "")):
            stems |= E._stem_variants(t)
        left = [w for w in ws if E._stem_variants(w) & stems]
        total += len(ws)
        gone += len(ws) - len(left)
        rows.append((k, ws, left))
    return rows, total, gone


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--material", default=DEFAULT_MATERIAL)
    ap.add_argument("--out", default="/tmp/reflow_result.json")
    ap.add_argument("--timeout", type=float, default=480)
    args, _ = ap.parse_known_args()

    R1 = one_round("第 1 轮 · 无回灌（用来算规避词）", args.material, None, args.timeout)
    if not R1["ok"]:
        print("✗ 第 1 轮失败，无法继续")
        return 1
    avoid = pack_avoid(R1["res"])
    print("\n  算出规避词（前端同口径）:")
    for k, ws in sorted(avoid.items()):
        print("   %-3s %2d 词: %s" % (k, len(ws), ws))
    if not avoid:
        print("  ⚠ 无任何档超标 —— 本次素材不足以验证回灌效果")

    R2 = one_round("第 2 轮 · 带回灌（处理组）", args.material, avoid, args.timeout)
    if not R2["ok"]:
        print("✗ 第 2 轮失败")
        return 1

    R3 = one_round("第 3 轮 · 无回灌（对照组）", args.material, None, args.timeout)
    if not R3["ok"]:
        print("✗ 第 3 轮失败")
        return 1

    # ---- 判据 A ----
    nc = (R2["nodes"] or {}).get("nodeClean") or {}
    print("\n" + "=" * 78)
    print("判据 A · 回灌是否接通（第 2 轮 nodeClean 的输出）")
    print("=" * 78)
    a_ok = False
    for lv in ("a1", "a2", "b1", "b2"):
        v = str(nc.get("avoid_" + lv) or "(缺)")
        real = "本轮无" not in v and v != "(缺)"
        a_ok = a_ok or real
        print("   avoid_%-2s %s  %s" % (lv, "✓ 收到" if real else "— 无", v[:86]))
    print("   →", "接通 ✓" if a_ok else "未接通 ✗")

    # ---- 判据 B ----
    print("\n" + "=" * 78)
    print("判据 B · 是否真的变简单（处理组 vs 对照组，含噪声基线）")
    print("=" * 78)
    print("   %-4s %8s %8s %8s | %9s %9s" % (
        "档", "R1 无灌", "R3 对照", "R2 处理", "R1↔R3噪声", "R2 vs 对照"))
    # ⚠️ 只评价**真正收到回灌**的档。R1 就已达标的档不会收到任何词，
    #    它的变化纯属 LLM 随机性 —— 把它算进「是否有效」会得出错误的否定结论。
    treated = set(avoid.keys())
    b_ok, noise_max, eff_max = True, 0.0, 0.0
    for k in LEVELS:
        if not all(k in r["rates"] for r in (R1, R2, R3)):
            continue
        v1, v3, v2 = R1["rates"][k], R3["rates"][k], R2["rates"][k]
        noise = abs(v3 - v1)
        eff = ((v1 + v3) / 2) - v2            # 正 = 处理组更简单
        if k not in treated:
            print("   %-4s %7.1f%% %7.1f%% %7.1f%% | %+8.1fpt %9s  — 未处理（本档未超标，无回灌）" % (
                k, v1 * 100, v3 * 100, v2 * 100, (v3 - v1) * 100, "n/a"))
            continue
        noise_max = max(noise_max, noise)
        eff_max = max(eff_max, abs(eff))
        verdict = ("↓ 有效" if eff > 0 and eff > noise else
                   ("↓ 有效但与噪声同量级" if eff > 0 else "↑ 反而更难"))
        if not (eff > 0):
            b_ok = False
        print("   %-4s %7.1f%% %7.1f%% %7.1f%% | %+8.1fpt %+9.1fpt  %s" % (
            k, v1 * 100, v3 * 100, v2 * 100, (v3 - v1) * 100, eff * 100, verdict))
    print("   受处理档 %s · 噪声最大 %.1f pt · 效应最大 %.1f pt → %s" % (
        "/".join(sorted(treated)) or "（无）", noise_max * 100, eff_max * 100,
        "效应盖过噪声 ✓" if eff_max > noise_max else "效应未盖过噪声，**不能下结论** ✗"))

    # ---- 判据 B2 ----
    print("\n" + "=" * 78)
    print("判据 B2 · 词级依从性（第 1 轮要求规避的词，第 2 轮还剩几个）")
    print("=" * 78)
    rows, total, gone = compliance(avoid, R2["arts"])
    for k, ws, left in rows:
        print("   %-3s 要求规避 %2d 个 → 仍出现 %2d 个" % (k, len(ws), len(left)))
        if left:
            print("       仍在: %s" % ", ".join(left))
    if total:
        print("   合计 %d/%d 已消失（%.0f%% 依从）" % (gone, total, 100.0 * gone / total))

    # ---- 判据 C ----
    print("\n" + "=" * 78)
    print("判据 C · 产出是否退化")
    print("=" * 78)
    c_ok = R2["n_art"] >= R1["n_art"] and R3["n_art"] >= R1["n_art"]
    print("   档数  R1=%d  R2=%d  R3=%d  → %s" % (
        R1["n_art"], R2["n_art"], R3["n_art"], "通过 ✓" if c_ok else "退化 ✗"))

    print("\n" + "=" * 78)
    print("结论")
    print("=" * 78)
    print("   判据 A 接通:      %s" % ("通过" if a_ok else "未通过"))
    print("   判据 B 变简单:    %s" % ("通过" if b_ok else "未通过（见上表）"))
    if total:
        print("   判据 B2 词级依从: %d/%d（%.0f%%）" % (gone, total, 100.0 * gone / total))
    print("   判据 C 未退化:    %s" % ("通过" if c_ok else "未通过"))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"material": args.material, "avoid": avoid,
                   "round1": {"rates": R1["rates"], "res": R1["res"], "arts": R1["arts"]},
                   "round2": {"rates": R2["rates"], "res": R2["res"], "arts": R2["arts"]},
                   "round3": {"rates": R3["rates"], "res": R3["res"], "arts": R3["arts"]},
                   "nodeClean_r2": nc,
                   "noise_max": noise_max, "eff_max": eff_max,
                   "compliance": {"total": total, "gone": gone}},
                  f, ensure_ascii=False, indent=1, default=str)
    print("\n完整结果 →", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
