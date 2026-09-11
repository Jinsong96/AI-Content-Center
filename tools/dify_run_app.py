#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ReadPal · 用 Dify service API 真实跑一个工作流并打印契约摘要

给后端对接用：这是前端/后端实际会走的同一条路径（api.dify.ai + app key），
不经过 Dify 控制台。跑完打印 status / 耗时 / 关键输出字段的形状。

用法
────
    python3 tools/dify_run_app.py --app=main
    python3 tools/dify_run_app.py --app=gen --in=level=B1.2
    python3 tools/dify_run_app.py --app=fact --material="..." --out=/tmp/r.json

    --app     main | fact | gen  （或直接给 app-xxxx 密钥）
    --in      k=v 形式，可重复；覆盖默认入参
    --material  素材正文（默认用内置的一段英文新闻）
    --out     把完整 outputs 写到文件
    --timeout 秒，默认 420

密钥来源（按优先级）
    --key=app-xxx  >  环境变量 DIFY_WF_{MAIN,FACT,GEN}  >  backend/keys.fallback.json

⚠️ 已知坑（都踩过）
 1. `select` 类型入参**不能传空字符串**，即使 required=false 也要**整个省略**，
    否则报 `xxx must be one of the following: [...]`。本脚本默认只传 material。
 2. 必须用 `response_mode: "streaming"`。blocking 会撞 Dify 网关约 120s 硬超时，
    而完整链路要 100~220s，实测会 504。
 3. api.dify.ai 偶发 Cloudflare `403 error code: 1010`，**不是密钥失效**，重试即可。
 4. 前端/后端拿到的 outputs 里，文章键是**下划线式**（`A1_1`/`B2P_3`），
    校验里的 `level` 是**点式**（`A1.1`/`B2+.3`）；两者要做归一化。

退出码：0 成功（status=succeeded）；1 失败
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(_HERE, '..', 'backend', 'keys.fallback.json')

APP_IDS = {
    'main': '466e1815-c5bb-4d50-8437-2fc4768dd4f0',
    'fact': '12e8c26d-cbcc-43c2-94bb-20926226cb3d',
    'gen':  'f4462032-2919-49e0-b123-bb5160c96c28',
}
ENV_KEY = {'main': 'DIFY_WF_MAIN', 'fact': 'DIFY_WF_FACT', 'gen': 'DIFY_WF_GEN'}

DEFAULT_MATERIAL = (
    'A new study from the University of Tokyo found that city trees can cool '
    'nearby streets by up to five degrees Celsius. Researchers measured air '
    'temperature around 200 trees in three districts over one summer. The '
    'cooling effect was strongest in narrow streets with little wind. The team '
    'says planting more trees could help cities adapt to hotter summers.'
)

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36')


def resolve_key(app):
    for a in sys.argv[1:]:
        if a.startswith('--key='):
            return a.split('=', 1)[1].strip()
    if app in ENV_KEY and os.environ.get(ENV_KEY[app]):
        return os.environ[ENV_KEY[app]].strip()
    if os.path.isfile(KEYS_FILE):
        with open(KEYS_FILE, encoding='utf-8') as f:
            k = json.load(f).get(ENV_KEY.get(app, ''), '')
        if k:
            return k.strip()
    return ''


def run(app, key, inputs, timeout):
    """发流式请求，返回 (status, outputs, elapsed, raw_events)"""
    body = json.dumps({'inputs': inputs, 'response_mode': 'streaming',
                       'user': 'readpal-verify'}).encode('utf-8')
    req = urllib.request.Request(
        'https://api.dify.ai/v1/workflows/run', data=body,
        headers={'Authorization': 'Bearer ' + key,
                 'Content-Type': 'application/json',
                 'User-Agent': UA})
    t0 = time.time()
    last_err = None
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                finished = None
                for raw in r:
                    line = raw.decode('utf-8', 'replace').strip()
                    if not line.startswith('data: '):
                        continue
                    try:
                        ev = json.loads(line[6:])
                    except Exception:
                        continue
                    if ev.get('event') == 'workflow_finished':
                        finished = ev.get('data') or {}
                if finished is None:
                    return 'failed', {}, time.time() - t0, {'error': '未收到 workflow_finished'}
                return (finished.get('status'), finished.get('outputs') or {},
                        finished.get('elapsed_time') or (time.time() - t0), finished)
        except urllib.error.HTTPError as e:
            msg = e.read().decode('utf-8', 'replace')[:200]
            last_err = 'HTTP %s %s' % (e.code, msg)
            # 403/1010 是 Cloudflare 偶发拦截，值得重试；401/400 直接失败
            if e.code in (403, 429, 502, 503, 504):
                time.sleep(3 * attempt)
                continue
            return 'failed', {}, time.time() - t0, {'error': last_err}
        except Exception as e:  # noqa: BLE001
            last_err = '%s: %s' % (type(e).__name__, e)
            time.sleep(3 * attempt)
    return 'failed', {}, time.time() - t0, {'error': last_err}


def summarize(app, outputs):
    print('\n── 输出契约 ──')
    print('  outputs 字段 %d 个' % len(outputs))
    if app == 'main':
        arts = json.loads(outputs.get('articles_json') or '{}')
        print('  12 档文章 %d 个：%s' % (len(arts), ', '.join(sorted(arts))))
        for k in sorted(arts):
            t = arts[k] if isinstance(arts[k], str) else ''
            print('    %-8s %5d 词' % (k, len(t.split())))
        quiz = json.loads(outputs.get('quiz_json') or '{}')
        lv = quiz.get('levels') or {}
        n = sum(len(v) for v in lv.values() if isinstance(v, list))
        print('  出题：%d 档 / %d 题   导读：%s' % (len(lv), n, list((quiz.get('guide') or {}).keys())))
        print('  分级：%s (大档 %s)' % (outputs.get('level'), outputs.get('level_big')))
        print('  校验：%s  (%s)' % (outputs.get('validation_pass'), outputs.get('validation_score')))
    elif app == 'fact':
        for k in ('facts_json', 'level', 'level_big', 'sens_level'):
            print('  %-12s %s' % (k, str(outputs.get(k))[:90]))
    elif app == 'gen':
        arts = json.loads(outputs.get('articles_json') or '{}')
        print('  12 档文章 %d 个' % len(arts))
        print('  校验：%s (%s)' % (outputs.get('validation_pass'), outputs.get('validation_score')))


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--app', default='main')
    ap.add_argument('--material', default=DEFAULT_MATERIAL)
    ap.add_argument('--out', default='')
    ap.add_argument('--timeout', type=float, default=420)
    ap.add_argument('--in', dest='kv', action='append', default=[])
    args, _ = ap.parse_known_args()

    app = args.app
    key = resolve_key(app)
    if not key:
        sys.exit('✗ 找不到 %s 的 app key（--key= / 环境变量 / backend/keys.fallback.json）' % app)

    inputs = {}
    if app in ('main', 'fact'):
        inputs['material'] = args.material
    for kv in args.kv:
        k, _, v = kv.partition('=')
        inputs[k] = v

    print('>> %s  入参: %s' % (app, {k: (v[:40] + '…' if len(str(v)) > 40 else v)
                                     for k, v in inputs.items()}))
    print('   走 https://api.dify.ai/v1/workflows/run  streaming …')
    status, outputs, elapsed, meta = run(app, key, inputs, args.timeout)
    print('\nstatus = %s   耗时 = %.1fs   tokens = %s' % (
        status, float(elapsed or 0), (meta or {}).get('total_tokens')))
    if (meta or {}).get('error'):
        print('error =', meta['error'])
    if outputs:
        summarize(app, outputs)
    if args.out and outputs:
        with open(args.out, 'w', encoding='utf-8') as f:
            json.dump(outputs, f, ensure_ascii=False, indent=1)
        print('\n完整 outputs 已写入', args.out)
    return 0 if status == 'succeeded' else 1


if __name__ == '__main__':
    sys.exit(main())
