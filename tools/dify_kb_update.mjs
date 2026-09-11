// ReadPal · 更新 Dify 知识库文档内容（走控制台 API，不点 UI）
//
// 用法：
//   node tools/dify_kb_update.mjs --dataset=<dataset_id> --doc=<document_id> --file=<新语料.md> [--name=<文档名>]
//        [--port=9224] [--dry]
//
// 原理：POST /console/api/datasets/{dataset}/documents/{doc}/update-by-text
//   body = { name, text, process_rule: { mode: "automatic" } }
// 更新后 Dify 会重新切分与向量化，索引状态需轮询到 completed 才可被检索。
//
// 退出码：0 成功；1 失败

import fs from 'node:fs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => {
  const hit = argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const has = k => argv.includes(`--${k}`);

const DS = arg('dataset'), DOC = arg('doc'), FILE = arg('file');
const PORT = Number(arg('port', process.env.DIFY_CDP_PORT || 9224));
if (!DS || !DOC || !FILE) { console.error('用法: --dataset=<id> --doc=<id> --file=<md> [--name=]'); process.exit(1); }
const text = fs.readFileSync(FILE, 'utf-8');
const name = arg('name') || FILE.split('/').pop();
console.log(`[load] ${FILE}  ${text.length} 字符  → 文档名 "${name}"`);

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

const body = { name, text, process_rule: { mode: 'automatic' } };
const expr = `(function(){
  var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');
  var h={'X-CSRF-Token':t,'Content-Type':'application/json'};
  var B=${JSON.stringify(JSON.stringify(body))};
  return fetch('/console/api/datasets/${DS}/documents/${DOC}/update-by-text',{method:'POST',credentials:'include',headers:h,body:B})
    .then(function(r){return r.text().then(function(x){return r.status+' ||| '+x.slice(0,400);});});
})()`;

if (has('dry')) { console.log('[dry] 不提交，负载 %d 字符' % expr.length); ws.close(); process.exit(0); }

console.log('[update] 提交…');
console.log('  ' + String(await evaluate(expr)).slice(0, 420));

// 轮询索引状态
for (let i = 0; i < 40; i++) {
  await new Promise(r => setTimeout(r, 3000));
  const st = await evaluate(`(function(){
    var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');
    return fetch('/console/api/datasets/${DS}/documents/${DOC}',{credentials:'include',headers:{'X-CSRF-Token':t}})
      .then(function(r){return r.json();})
      .then(function(d){return JSON.stringify({status:d.indexing_status,words:d.word_count,segs:d.segment_count,err:d.error||null});});
  })()`);
  const s = JSON.parse(st);
  console.log(`  [${i}] status=${s.status} words=${s.words} segments=${s.segs} ${s.err || ''}`);
  if (s.status === 'completed' || s.status === 'error') break;
}
ws.close();
process.exit(0);
