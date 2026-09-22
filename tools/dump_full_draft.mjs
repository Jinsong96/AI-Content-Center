// ReadPal · 拉取 Dify 应用 draft 的【完整对象】并直接落盘（含 features / conversation_variables）
//
// 与 dump_draft.mjs 的区别（很重要）：
//   dump_draft.mjs   只存 graph；且把结果经 stdout 打印，会撞上 64KB 输出上限被截断
//   dump_full_draft  存整个 draft 响应，直接写文件、不经 stdout —— 不会截断
//
// 为什么需要它：
//   dify_push_graph.mjs 的请求体是 { graph, features, conversation_variables, hash }。
//   若拿「只有 graph」的载荷去推，features / conversation_variables 会以 undefined 送出去，
//   应用的 features（文件上传、语音、retriever 等）会被清空。
//   → **推送前一律先用本脚本拉完整草稿，在它的 graph 上定点改，再整体推回。**
//
// 用法：
//   DIFY_CDP_PORT=9237 node tools/dump_full_draft.mjs <app_id> /tmp/full_gen.json
//
// 前置：Chrome 已人工登录 Dify 控制台，且带 --remote-debugging-port（见 tools/launch_dify_chrome.py）
// 退出码：0 成功；1 失败

import fs from 'node:fs';

const APP = process.argv[2];
const OUT = process.argv[3];
const PORT = Number(process.env.DIFY_CDP_PORT || 9224);

if (!APP || !OUT) { console.error('用法: node tools/dump_full_draft.mjs <app_id> <out.json>'); process.exit(1); }

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const pages = list.filter(t => t.type === 'page' && !(t.url || '').startsWith('devtools://'));
const t = pages.find(p => (p.url || '').includes('dify')) || pages[0];
if (!t) { console.error('✗ 没有可用页签（Chrome 起了吗？）'); process.exit(1); }

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

// 注意：evaluate 返回的是结构化值，不经过 stdout，所以不受输出长度限制
// ⚠️ 2026-09-22：Dify 现在连 GET 也校验 X-CSRF-Token，不带就 401 —— 必须带上
const raw = await evaluate(`(function(){
  var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');
  return fetch('/console/api/apps/${APP}/workflows/draft',{credentials:'include',headers:{'X-CSRF-Token':t}})
    .then(function(r){return r.text().then(function(x){try{return JSON.parse(x);}catch(e){return {__err:r.status+' '+x.slice(0,200)};}});});
})()`);
if (!raw || !raw.graph) {
  console.error('✗ 拉取失败：' + (raw && raw.__err ? raw.__err : '会话可能已失效（重新登录 Dify 后重试）'));
  process.exit(1);
}

fs.writeFileSync(OUT, JSON.stringify(raw, null, 1), 'utf-8');
console.log(`[full] hash=${String(raw.hash).slice(0, 16)}… nodes=${raw.graph.nodes.length} edges=${raw.graph.edges.length} → ${OUT} (${fs.statSync(OUT).size} B)`);
console.log(`[full] keys=${Object.keys(raw).join(',')}`);
process.exit(0);
