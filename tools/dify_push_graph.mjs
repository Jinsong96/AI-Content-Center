// ReadPal · 把本地改好的工作流图推送到 Dify 的 draft（不影响 published 线上版本）
//
// 用法：
//   node tools/dify_push_graph.mjs --app=<app_id> --graph=<新图.json> [--port=9224]
//        [--dry]        只读当前 hash，不提交
//
// 原理：Dify 控制台 API 的 draft 接口带乐观锁，必须回传当前 hash。
//   POST /console/api/apps/{app}/workflows/draft
//   body = { graph, features, conversation_variables, hash }
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
const GRAPH = arg('graph');
const PORT = Number(arg('port', process.env.DIFY_CDP_PORT || 9224));
const CDP = `http://127.0.0.1:${PORT}`;

if (!APP || !GRAPH) { console.error('用法: --app=<app_id> --graph=<file.json> [--dry]'); process.exit(1); }
const payload = JSON.parse(fs.readFileSync(GRAPH, 'utf-8'));
console.log(`[load] ${GRAPH}  nodes=${(payload.graph?.nodes || []).length} edges=${(payload.graph?.edges || []).length}`);

const list = await (await fetch(`${CDP}/json/list`)).json();
const pages = list.filter(t => t.type === 'page' && !(t.url || '').startsWith('devtools://'));
const t = pages.find(p => (p.url || '').includes('dify')) || pages[0];
if (!t) { console.error('✗ 没有可用页签'); process.exit(1); }
console.log(`[attach] ${t.title} | ${t.url}`);

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

// ── 1) 读当前 draft 的 hash / features / conversation_variables
const cur = await evaluate(`(function(){
  var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');
  return fetch('/console/api/apps/${APP}/workflows/draft',{credentials:'include'})
    .then(function(r){return r.json();})
    .then(function(d){return JSON.stringify({hash:d.hash||'',ok:!!d.graph});});
})()`);
const curObj = JSON.parse(cur);
if (!curObj.ok) { console.error('✗ 读不到 draft，会话可能已失效'); process.exit(1); }
console.log(`[draft] 当前 hash=${String(curObj.hash).slice(0, 16)}…`);

if (has('dry')) { console.log('[dry] 不提交'); ws.close(); process.exit(0); }

// ── 2) 带 hash 提交新图
const payloadJson = JSON.stringify(payload);
const expr = `(function(){
  var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');
  var h={'X-CSRF-Token':t,'Content-Type':'application/json'};
  var PL=${JSON.stringify(payloadJson)};
  var p=JSON.parse(PL);
  return fetch('/console/api/apps/${APP}/workflows/draft',{method:'POST',credentials:'include',headers:h,
    body:JSON.stringify({graph:p.graph,features:p.features,conversation_variables:p.conversation_variables||[],
      hash:${JSON.stringify(curObj.hash)}})})
    .then(function(r){return r.text().then(function(x){return r.status+' ||| '+x.slice(0,600);});});
})()`;

const resp = await evaluate(expr);
console.log('[push] ' + String(resp).slice(0, 700));

// ── 3) 回读校验
const after = await evaluate(`(function(){
  var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');
  return fetch('/console/api/apps/${APP}/workflows/draft',{credentials:'include'})
    .then(function(r){return r.json();})
    .then(function(d){return JSON.stringify({hash:d.hash,nodes:(d.graph&&d.graph.nodes||[]).length,edges:(d.graph&&d.graph.edges||[]).length,
      ids:(d.graph&&d.graph.nodes||[]).map(function(n){return n.id;})});});
})()`);
const a = JSON.parse(after);
console.log(`[verify] hash=${String(a.hash).slice(0, 16)}…  nodes=${a.nodes} edges=${a.edges}`);
console.log(`[verify] ids=${a.ids.join(',')}`);
ws.close();
process.exit(0);
