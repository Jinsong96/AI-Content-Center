// ReadPal · 列出一个 Dify 应用的所有工作流版本（含 draft），并检查某个改动是否真的在线上
//
// 用法：
//   node tools/dify_versions.mjs --app=<app_id> [--port=9243] [--markers=looseFix,剥标题] [--json]
//
//   --markers=a,b,c   在每个版本的节点代码/提示词里找这些标记，输出 ✓/✗
//                     （用来回答「这个改动到底发布到线上了吗」）
//   --json            输出原始 JSON
//
// 为什么需要它：`dify_publish.mjs --check` 只比 hash 字符串，
// **看不出线上那份图里到底有没有你要的改动**；而前端走的是 published 版本，
// 所以「草稿改了」≠「线上生效」。本工具直接读 published 版本的 graph。
//
// 原理：GET /console/api/apps/{app}/workflows → items[]（含 draft 与各发布版本，每条都带完整 graph）
// 退出码：0 正常；1 出错

const argv = process.argv.slice(2);
const arg = (k, d = null) => {
  const hit = argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const APP = arg('app');
const PORT = arg('port', process.env.DIFY_CDP_PORT || '9243');
const MARKERS = (arg('markers', '') || '').split(',').map(s => s.trim()).filter(Boolean);
const AS_JSON = argv.includes('--json');
if (!APP) { console.error('用法: --app=<app_id> [--port=9243] [--markers=a,b] [--json]'); process.exit(1); }

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const pages = list.filter(t => t.type === 'page' && !(t.url || '').startsWith('devtools://'));
const tab = pages.find(p => /cloud\.dify\.ai/.test(p.url || '')) || pages[0];
if (!tab) { console.error('✗ 没有可用页签（需已登录 Dify 的 Chrome）'); process.exit(1); }

const ws = new WebSocket(tab.webSocketDebuggerUrl);
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
await send('Runtime.enable');

const expr = `(async function(){
  var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');
  var H={'X-CSRF-Token':t};
  var r=await fetch('/console/api/apps/${APP}/workflows',{credentials:'include',headers:H});
  if(r.status!==200) return JSON.stringify({__err:'http '+r.status});
  var j=await r.json();
  var markers=${JSON.stringify(MARKERS)};
  var out=(j.items||[]).map(function(it){
    var nodes=(it.graph&&it.graph.nodes)||[];
    var llm=nodes.filter(function(n){return n.data&&n.data.type==='llm'})[0];
    // 把每个节点的代码 + 提示词拼成一份大文本，供标记检索（覆盖 code 节点与 LLM 节点提示词）
    var blob=nodes.map(function(n){
      var d=n.data||{};
      return String(d.code||'')+'\\n'+String(d.prompt_template||d.instructions||d.prompt||'');
    }).join('\\n');
    var hit={};
    markers.forEach(function(m){ hit[m]= blob.indexOf(m)>=0; });
    return {version:it.version, version_number:it.version_number, hash:String(it.hash||''),
      created_at:it.created_at, comment:it.marked_comment||'',
      nodes:nodes.length, llmNodes:nodes.filter(function(n){return n.data&&n.data.type==='llm'}).length,
      model:llm&&llm.data.model?(llm.data.model.provider+' / '+llm.data.model.name):'?',
      markers:hit};
  });
  return JSON.stringify(out);
})()`;

const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
ws.close();
const raw = r.result?.result?.value;
if (!raw) { console.error('✗ 读取失败：' + JSON.stringify(r).slice(0, 300)); process.exit(1); }
const data = JSON.parse(raw);
if (data.__err) { console.error('✗ ' + data.__err + '（登录态可能过期：刷新一下 Dify 页签即可，无需重新登录）'); process.exit(1); }

const items = [...data].sort((a, b) => (a.version_number || 9999) - (b.version_number || 9999));
if (AS_JSON) { console.log(JSON.stringify(items, null, 2)); process.exit(0); }

const fmt = ts => ts ? new Date(ts * 1000).toISOString().replace('T', ' ').slice(0, 19) : '-';
const tag = it => (it.version_number == null ? 'draft' : `v${it.version_number}`);
console.log(`共 ${items.length} 个版本（draft + ${items.length - 1} 个已发布）`);
console.log('');
const head = ['版本', 'hash', '节点', 'LLM', '创建时间', '模型'].concat(MARKERS);
const rows = items.map(it => [
  tag(it), it.hash.slice(0, 12), String(it.nodes), String(it.llmNodes), fmt(it.created_at), it.model,
].concat(MARKERS.map(m => (it.markers[m] ? '✓' : '✗'))));
const w = head.map((h, i) => Math.max(String(h).length * 2, ...rows.map(r => String(r[i]).length)));
const pad = (s, n) => s + ' '.repeat(Math.max(0, n - String(s).length));
console.log(head.map((h, i) => pad(h, w[i])).join('  '));
console.log(w.map(n => '-'.repeat(n)).join('  '));
rows.forEach(r => console.log(r.map((c, i) => pad(c, w[i])).join('  ')));
if (MARKERS.length) {
  console.log('');
  console.log(`标记：${MARKERS.join(' / ')}   ← ✓ 表示该版本的节点代码或提示词里含此字符串`);
}
console.log('');
const pub = items.filter(i => i.version_number != null).pop();
const dr = items.find(i => i.version_number == null);
if (dr && pub) {
  console.log(`线上生效的是 ${tag(pub)}（${fmt(pub.version ? pub.created_at : pub.created_at)}），前端走的是这一版；draft 未发布则不影响线上。`);
}
process.exit(0);
