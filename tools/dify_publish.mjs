// ReadPal · 把 Dify 应用的 draft 工作流发布为线上版本
//
// 用法：
//   node tools/dify_publish.mjs --app=<app_id> [--port=9224] [--check] [--note="说明"]
//
//   --check  只对比 draft / published 的 hash，不发布
//   --note   版本备注（写进 marked_comment，便于回溯）
//
// 原理：POST /console/api/apps/{app}/workflows/publish  body = {marked_comment}
//       发布后线上 API 立即跑新版本；draft 不受影响。
//
// 退出码：0 成功；1 失败

import fs from 'node:fs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => {
  const hit = argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const has = k => argv.includes(`--${k}`);
const APP = arg('app');
const PORT = Number(arg('port', process.env.DIFY_CDP_PORT || 9224));
if (!APP) { console.error('用法: --app=<app_id> [--check] [--note=说明]'); process.exit(1); }
const note = arg('note', '');

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const pages = list.filter(t => t.type === 'page' && !(t.url || '').startsWith('devtools://'));
const t = pages.find(p => (p.url || '').includes('dify')) || pages[0];
if (!t) { console.error('✗ 没有可用页签'); process.exit(1); }
console.log(`[attach] ${t.title}`);

const ws = new WebSocket(t.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id = 0;
const pending = new Map();
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
});
const send = (method, params = {}) => new Promise(res => {
  const mid = ++id; pending.set(mid, res);
  ws.send(JSON.stringify({ id: mid, method, params }));
});
const evaluate = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true, userGesture: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text);
  return r.result?.result?.value;
};
await send('Runtime.enable');

const H = `var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');var h={'X-CSRF-Token':t,'Content-Type':'application/json'};`;

// 1) 读 draft / published 信息
const info = await evaluate(`(async function(){${H}
  var a=await (await fetch('/console/api/apps/${APP}',{credentials:'include',headers:h})).json();
  var d=await (await fetch('/console/api/apps/${APP}/workflows/draft',{credentials:'include',headers:h})).json();
  return JSON.stringify({name:a.name,mode:a.mode,draft_hash:d.hash,draft_nodes:(d.graph&&d.graph.nodes||[]).length,workflow:a.workflow||null});
})()`);
const j = JSON.parse(info);
console.log(`[app] ${j.name} (${j.mode})  draft.nodes=${j.draft_nodes}  draft.hash=${String(j.draft_hash).slice(0, 16)}…`);
if (j.workflow) {
  console.log(`[published] version=${j.workflow.version}  updated_at=${new Date((j.workflow.updated_at || 0) * 1000).toISOString()}`);
}

if (has('check')) { console.log('[check] 仅比对，未发布'); ws.close(); process.exit(0); }

// 2) 发布
const res = await evaluate(`(async function(){${H}
  return fetch('/console/api/apps/${APP}/workflows/publish',{method:'POST',credentials:'include',headers:h,
    body:JSON.stringify({marked_comment:${JSON.stringify(note)}})})
    .then(function(r){return r.text().then(function(x){return r.status+' ||| '+x.slice(0,300);});});
})()`);
console.log('[publish] ' + res);
if (!String(res).startsWith('200')) { console.error('✗ 发布失败'); ws.close(); process.exit(1); }

// 3) 回读确认
const after = await evaluate(`(async function(){${H}
  var a=await (await fetch('/console/api/apps/${APP}',{credentials:'include',headers:h})).json();
  var d=await (await fetch('/console/api/apps/${APP}/workflows/draft',{credentials:'include',headers:h})).json();
  return JSON.stringify({draft_hash:d.hash,version:(a.workflow||{}).version,updated_at:(a.workflow||{}).updated_at});
})()`);
console.log('[verify] ' + after);
ws.close();
process.exit(0);
