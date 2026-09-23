#!/usr/bin/env node
/* 桥接层 wf 路由回归：证明「每个工作流名都能被代理转发」。

   为什么需要它（2026-09-23 踩坑）：
   新增工作流要改 **两处** —— `_serve_index()` 的 `_envs` 注入白名单 + `/api/dify/workflows/run`
   的 `keymap`。当时只改了前者，前端拿得到 key，但一点「生成」就被代理判 `unknown wf`。
   **本地探针没抓到**，因为桥接层没起 ⇒ `difyCall` 静默回退直连 `api.dify.ai`，压根没走代理。

   本脚本**真起一个桥接层**，对每个 wf 打一发空 inputs 的请求：
     · 已知 wf → Dify 回 400 invalid_param（= 转发成功，key 也拿到了）⇒ 断言「错误里不含 unknown wf」
     · 乱写 wf → 必须回 unknown wf（负向对照，证明这条断言真在测白名单）

   用法：node tools/probe_bridge_wf.mjs
*/
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = process.env.TEST_PORT || 8799;
const BASE = `http://127.0.0.1:${PORT}`;
const KNOWN = ['fact', 'gen', 'main', 'licprep', 'licgen', 'lite'];

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name}${extra ? '  → ' + extra : ''}`); }
};

/* BRIDGE_FILE 可覆盖被测文件（负向对照用：塞一份「去掉 lite」的变异体，本探针必须变红）。
   ⚠️ 变异体要放在 backend/ 下 —— _BASE_DIR 由 __file__ 往上退两级推导，
   换目录会导致 config.local.js / keys.fallback.json 都读不到，报错性质就变了。 */
const BRIDGE = process.env.BRIDGE_FILE || join(ROOT, 'backend', 'agent_reach_bridge.py');
const child = spawn(process.env.PYTHON || 'python3', [BRIDGE, String(PORT)], {
  cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, PORT: String(PORT) },
});
let bootLog = '';
child.stdout.on('data', d => { bootLog += d; });
child.stderr.on('data', d => { bootLog += d; });
const kill = () => { try { child.kill('SIGKILL'); } catch {} };
process.on('exit', kill);

const probe = async (wf) => {
  const r = await fetch(`${BASE}/api/dify/workflows/run`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ wf, inputs: {}, response_mode: 'blocking', user: 'probe-bridge' }),
  });
  const j = await r.json().catch(() => ({}));
  return { status: r.status, error: String(j.error || ''), detail: String(j.detail || '').slice(0, 160) };
};

// 等桥接层起来
let up = false;
for (let i = 0; i < 60; i++) {
  try { await fetch(`${BASE}/api/dify/workflows/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ wf: 'lite', inputs: {} }) }); up = true; break; }
  catch { await new Promise(r => setTimeout(r, 400)); }
}
if (!up) { console.error('✗ 桥接层没起来\n' + bootLog.slice(-600)); kill(); process.exit(1); }
console.log(`桥接层已起（端口 ${PORT}）\n`);

console.log('【1】已知 wf 必须能被代理转发（不是 unknown wf）');
for (const wf of KNOWN) {
  const o = await probe(wf);
  const isUnknown = /unknown wf/.test(o.error);
  const missingKey = /missing upstream api key/.test(o.error);
  ok(`${wf.padEnd(8)} 已登记`, !isUnknown, `error=${o.error} ${o.detail}`);
  if (!isUnknown) {
    ok(`${wf.padEnd(8)} 有 key（不是空 key 报错）`, !missingKey, `error=${o.error}`);
  }
}

console.log('\n【2】负向对照：乱写的 wf 必须被拒');
const bogus = await probe('totally_bogus_wf');
ok('未知 wf 返回 unknown wf', /unknown wf/.test(bogus.error), `error=${bogus.error}`);
ok('未知 wf 是 400', bogus.status === 400, `status=${bogus.status}`);
ok('错误文案列出了全部已登记 wf', KNOWN.every(k => bogus.error.includes(k)), bogus.error);

console.log(`\n${pass}/${pass + fail} 项通过`);
kill();
process.exit(fail ? 1 : 0);
