#!/usr/bin/env python3
"""把平铺的导入包按「篇」切成若干上传批（每批文件数 <= 100）。

后台规则：单批最多 100 个文件。BBC 50 篇 × 5 个文件 = 250 个，必须分 3 次上传。
切分保证**同一篇的 5 个文件落在同一批**，避免同标题跨批导致合并异常。

用法：
    python scripts/split_upload_batches.py "<平铺目录>" [每批篇数=20]
"""
import os
import re
import shutil
import sys

SUFFIX_RE = re.compile(r"_(A1|A2|B1|B2\+|B2)(_母稿)?$")


def group_key(f):
    """从文件名还原「篇」的 key。

    两类后缀要依次剥掉：
      正文 `<标题>_A1.docx` / `<标题>_B2+_母稿.docx`
      题目 `<标题>_题目.xlsx`（题目文件不带难度段，一个文件覆盖全篇）
    """
    k = re.sub(r"\.(docx|xlsx)$", "", f)   # 1. 去扩展名
    k = re.sub(r"_题目$", "", k)            # 2. 去「_题目」
    k = SUFFIX_RE.sub("", k)                # 3. 去难度（含 _母稿）
    return k


def group_files(d):
    groups = {}
    for f in sorted(os.listdir(d)):
        if f.startswith("~$"):
            continue
        p = os.path.join(d, f)
        if not os.path.isfile(p):
            continue
        groups.setdefault(group_key(f), []).append(f)
    return groups


def main():
    srcdir = sys.argv[1].rstrip("/")
    per = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    groups = group_files(srcdir)
    keys = sorted(groups)
    batches = [keys[i:i + per] for i in range(0, len(keys), per)]

    print(f"源目录：{srcdir}")
    print(f"共 {len(keys)} 篇 / {sum(len(v) for v in groups.values())} 个文件")
    print(f"按每批 {per} 篇切分 → {len(batches)} 批\n")

    for bi, batch in enumerate(batches, 1):
        out = f"{srcdir}_上传批{bi}"
        if os.path.exists(out):
            shutil.rmtree(out)
        os.makedirs(out)
        n = 0
        for k in batch:
            for f in groups[k]:
                shutil.copy2(os.path.join(srcdir, f), os.path.join(out, f))
                n += 1
        assert n <= 100, f"批 {bi} 超过 100 个文件（{n}）"
        print(f"  批 {bi}：{len(batch)} 篇 / {n} 个文件  →  {os.path.basename(out)}/")
        print(f"        第 1 篇：{batch[0]}")
        print(f"        末  篇：{batch[-1]}")
    print("\n上传提示：每次只上传一个批次目录里的全部文件（⌘A 全选），传完再传下一批。")


if __name__ == "__main__":
    main()
