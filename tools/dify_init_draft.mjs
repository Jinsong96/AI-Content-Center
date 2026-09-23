// ReadPal · 初始化 Dify 应用的 draft workflow
//
// 背景：`POST /console/api/apps` 建出来的 workflow 应用，draft 记录**不会**同步生成，
//   直接 GET /workflows/draft 会 404 `draft_workflow_not_exist`，导致推图脚本卡在「读不到 draft」。
//   人工做法是「在控制台里点开一次这个应用」——Dify 前端打开工作流编辑器时会自动建 draft。
//   本脚本用 CDP 复现这一步。
//
// 用法：
//   node tools/dify_init_draft.mjs --app=<app_id> [--port=9224] [--wait=25]
//
// 退出码：0 draft 已就绪；1 超时

const argv = process.argv.slice(2);
const arg = (k, d = null) => {
  const hit = argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const APP = arg('app');
const PORT = Number(arg('port', process.env.DIFY_CDP_PORT || 9224));
const WAIT = Number(arg('wait', 25));
if (!APP) { console.error('用法: --app=<app_id> [--wait=25]'); process.exit(1); }

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const pages = list.filter(t => t.type === 'page' && !(t.url || '').startsWith('devtools://'));
const t = pages.find(p => (p.url || '').includes('dify')) || pages[0];
if (!t) { console.error('✗ 没有可用页签（Chrome 起了吗？）'); process.exit(1); }
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
// 防呆复检：attach 到的必须是普通 Chrome，不能是 headless（无登录态、无窗口）
const ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
if (/HeadlessChrome/i.test(ver['User-Agent'] || '')) {
  console.error(`✗ 端口 ${PORT} 上是 headless Chrome（无登录态）。换个端口的可见窗口。`);
  ws.close(); process.exit(1);
}

await send('Runtime.enable');
const H = `var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');var h={'X-CSRF-Token':t,'Content-Type':'application/json'};`;

const probe = async () => {
  const r = await evaluate(`(async function(){${H}
    var x=await fetch('/console/api/apps/${APP}/workflows/draft',{credentials:'include',headers:h});
    var b=await x.text();
    return x.status+' ||| '+b;
  })()`);
  const idx = String(r).indexOf(' ||| ');
  return { status: Number(String(r).slice(0, idx)), text: String(r).slice(idx + 5) };
};
/* 从 draft body 里安全取节点数（body 未必是合法 JSON ⇒ 不抛异常） */
const nodeCount = body => {
  try { return (JSON.parse(body).graph?.nodes || []).length; } catch (e) { return '?'; }
};

// 先在当前页签直接探一次（可能已经是好的）
let p = await probe();
if (p.status === 200) {
  console.log(`✓ draft 已存在（无需初始化）  nodes=${nodeCount(p.text)}`);
  ws.close(); process.exit(0);
}
console.log(`[probe] ${p.status} ${p.text.slice(0, 90)}`);

// 导航到该应用的工作流编辑器 —— 前端会自己把 draft 建出来
const url = `https://cloud.dify.ai/app/${APP}/workflow`;
console.log(`[nav] ${url}`);
await send('Page.enable');
await send('Page.navigate', { url });

for (let i = 1; i <= WAIT; i++) {
  await new Promise(r => setTimeout(r, 1000));
  p = await probe();
  if (p.status === 200) {
    let hash = '?';
    try { hash = String(JSON.parse(p.text).hash).slice(0, 12); } catch (e) {}
    console.log(`✓ draft 已初始化（${i}s）  nodes=${nodeCount(p.text)}  hash=${hash}…`);
    ws.close(); process.exit(0);
  }
  if (i % 5 === 0) console.log(`  …等待中 ${i}s  最后状态=${p.status}`);
}
console.error(`✗ ${WAIT}s 内 draft 仍不可用：${p.status} ${p.text.slice(0, 120)}`);
ws.close(); process.exit(1);
