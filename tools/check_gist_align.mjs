// lite 骨架链路 · **大意一一对应**核对 —— 2026-09-24
//
// 为什么单独有这个检查：段数对齐（前后端代码能判）只是**必要条件**。
// Bryan 真正要的是「第 i 段大意对第 i 段」—— 这件事**代码判不了**（语义），
// 而 lite 链路本身没有 nodeSemCheck（那是授权链路图 B 的节点）。
// 这里借现成的「事实检查」图（DeepSeek Pro，判据里第 1 条 topic_swap 就是「讲成别的事」）
// 拿骨架当参照物，逐档核对 A1- / A2。
//
// 输入：probe_lite_skel_e2e.mjs 的产物（<out>.skeleton.json + <out>.summary.json，
//       summary 里存了每档逐段正文）。
// 用法：node tools/check_gist_align.mjs [--out=/tmp/lite_skel_e2e]
import fs from 'node:fs';
import { makeCtx } from './dify_console.mjs';
import { runWorkflowWith } from './dify_run_wf.mjs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => { const h = argv.find(a => a.startsWith(`--${k}=`)); return h ? h.slice(k.length + 3) : d; };
const OUT = arg('out', '/tmp/lite_skel_e2e');
const KEY_CHK = arg('chk_key', 'app-pwuyZh2e2VP48h9pjNCo1ylx');   // 事实检查（DeepSeek Pro）

const skel = JSON.parse(fs.readFileSync(`${OUT}.skeleton.json`, 'utf-8'));
const links = JSON.parse(fs.readFileSync(`${OUT}.summary.json`, 'utf-8'));
const numbered = arr => arr.map((p, i) => `${i + 1}. ${p}`).join('\n\n');

const ctx = await makeCtx(process.env.DIFY_CDP_PORT || String(arg('cdp', '9243')));
const rows = [];
try {
  for (const link of links) {
    if (!link.articles) continue;
    for (const lv of ['A1', 'A2']) {
      const cand = link.articles[lv] || [];
      const disp = lv === 'A1' ? 'A1-' : 'A2';
      const t0 = Date.now();
      const r = await runWorkflowWith(ctx, {
        appKey: KEY_CHK,
        inputs: { master_text: numbered(skel), candidate: numbered(cand), level: disp },
        user: 'readpal-gist-align',
      });
      const o = (r && r.data && r.data.data && r.data.data.outputs) || {};
      let j = null;
      try { j = JSON.parse(String(o.raw || '').replace(/^\s*```(?:json)?/i, '').replace(/```\s*$/, '')); } catch (e) { }
      const issues = (j && j.issues) || null;
      const ms = Date.now() - t0;
      const verdict = j ? String(j.verdict) : '(未解析)';
      console.log(`链路 ${link.rd} · ${disp}（${cand.length} 段 / 骨架 ${skel.length} 段）→ ${verdict} · ${(ms / 1000).toFixed(1)}s`);
      if (issues && issues.length) issues.forEach(x => console.log(`    ✗ 第 ${x.para} 段 [${x.type}] ${String(x.detail || '').slice(0, 160)}`));
      else if (j) console.log(`    ✓ ${String(j.summary || '').slice(0, 140)}`);
      if (!j) console.log(`    原始返回：${String(o.raw || '').slice(0, 300)}`);
      rows.push({ rd: link.rd, level: disp, segs: cand.length, verdict, issues, ms });
    }
  }
} finally {
  fs.writeFileSync(`${OUT}.gist.json`, JSON.stringify(rows, null, 1), 'utf-8');
  const bad = rows.filter(r => r.verdict !== 'pass').length;
  console.log(`\n[大意核对] ${rows.length - bad}/${rows.length} 档通过（判据 = 事实检查图第 1 条 topic_swap 等）`);
  console.log(`[产物] ${OUT}.gist.json`);
  ctx.close();
}
