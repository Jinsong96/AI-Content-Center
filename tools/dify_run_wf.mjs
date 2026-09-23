// ReadPal · 借已登录 Chrome（CDP）在浏览器侧调用 Dify 工作流 service API
//
// 为什么不在 Node 侧直接 fetch：
//   沙箱内 cloud.dify.ai / api.dify.ai 被 DNS 污染 + SNI 阻断（直连必失败）。
//   浏览器侧 fetch 是同源请求，天然可达。
//
// 用法（模块）：
//   import { runWorkflow } from './dify_run_wf.mjs';
//   const out = await runWorkflow({ appKey, inputs, port });
//
// 也可直接当 CLI 冒烟：
//   node tools/dify_run_wf.mjs --app=app-xxx --app_id=<可选，用于选中页签> --inputs=<json文件>
import fs from 'node:fs';
import { makeCtx } from './dify_console.mjs';

export async function runWorkflowWith(ctx, { appKey, inputs, user = 'readpal-loop', timeoutMs = 600000, base = process.env.DIFY_API_BASE || 'https://api.dify.ai' }) {
  const payload = { inputs, response_mode: 'blocking', user };
  const expr = `(async()=>{try{
    const res = await fetch(${JSON.stringify(base)} + '/v1/workflows/run', {
      method:'POST',
      headers:{'Content-Type':'application/json','Authorization':'Bearer ' + ${JSON.stringify(appKey)}},
      body: ${JSON.stringify(JSON.stringify(payload))}
    });
    const txt = await res.text();
    return JSON.stringify({status: res.status, body: txt});
  }catch(e){ return JSON.stringify({status:-1, body:'ERR '+e.message}); }})()`;
  const t0 = Date.now();
  const raw = await ctx.evaluateWithTimeout(expr, timeoutMs);
  const ms = Date.now() - t0;
  const o = JSON.parse(raw);
  let j = null; try { j = JSON.parse(o.body); } catch (e) { }
  if (o.status !== 200) {
    const err = new Error(`Dify HTTP ${o.status}: ${String(o.body).slice(0, 400)}`);
    err.http = o.status; err.body = o.body; err.ms = ms;
    throw err;
  }
  return { data: j, ms, http: o.status };
}

// 简易入口（自己开 CDP 连接）
export async function runWorkflow({ appKey, inputs, port = process.env.DIFY_CDP_PORT || '9243', match = 'dify', timeoutMs = 600000, user = 'readpal-loop' }) {
  const ctx = await makeCtx(port, match);
  try {
    return await runWorkflowWith(ctx, { appKey, inputs, user, timeoutMs });
  } finally {
    ctx.close();
  }
}

// ── CLI 冒烟 ────────────────────────────────────────────────────────────────
if (import.meta.url === `file://${process.argv[1]}`) {
  const argv = process.argv.slice(2);
  const arg = (k, d = null) => { const h = argv.find(a => a.startsWith(`--${k}=`)); return h ? h.slice(k.length + 3) : d; };
  const appKey = arg('app');
  const f = arg('inputs');
  if (!appKey || !f) { console.error('用法: node tools/dify_run_wf.mjs --app=app-xxx --inputs=inputs.json'); process.exit(1); }
  const inputs = JSON.parse(fs.readFileSync(f, 'utf-8'));
  const r = await runWorkflow({ appKey, inputs, port: arg('port', process.env.DIFY_CDP_PORT || '9243') });
  console.log(`[ms] ${r.ms}`);
  console.log(JSON.stringify(r.data, null, 1).slice(0, 3000));
}
