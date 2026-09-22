// 拉取 Dify 应用当前 draft 的 graph，存成 JSON —— 只读，不提交
import fs from 'node:fs';

const APP = process.argv[2];
const OUT = process.argv[3];
const PORT = Number(process.env.DIFY_CDP_PORT || 9224);

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const pages = list.filter(t => t.type === 'page' && !(t.url || '').startsWith('devtools://'));
const t = pages.find(p => (p.url || '').includes('dify')) || pages[0];
if (!t) { console.error('✗ 没有可用页签'); process.exit(1); }

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

// ⚠️ 2026-09-22：Dify 现在连 GET 也校验 X-CSRF-Token，不带就 401 —— 必须带上
const raw = await evaluate(`(function(){
  var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');
  return fetch('/console/api/apps/${APP}/workflows/draft',{credentials:'include',headers:{'X-CSRF-Token':t}})
    .then(function(r){return r.json();})
    .then(function(d){return JSON.stringify({hash:d.hash, graph:d.graph, err:(d.message||'')});});
})()`);
if (!raw) { console.error('✗ 拉取为空（可能 CSRF 失效，刷新页面重试）'); process.exit(1); }
const o = JSON.parse(raw);
if (!o.graph) { console.error('✗ 拉取失败：' + (o.err || '会话可能已失效，请重新登录 Dify')); process.exit(1); }
fs.writeFileSync(OUT, JSON.stringify(o.graph, null, 1), 'utf-8');
console.log(`[draft] hash=${o.hash}  nodes=${(o.graph?.nodes || []).length}  edges=${(o.graph?.edges || []).length}  -> ${OUT}`);
process.exit(0);
