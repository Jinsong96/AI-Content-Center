// ReadPal · 通过 CDP 调用 Dify console API（创建 / 列出应用）
//
// 为什么走 CDP：本机到 cloud.dify.ai 的直连与代理都不通（见技能），
// 但已登录的 Chrome 里 fetch 带 cookie 可以正常调 console API。
//
// 🔴 关键：console API 需要 **x-csrf-token** request header（不是 Bearer）。
//    该 token 不在 localStorage、也读不到（httpOnly 侧），
//    唯一可靠来源是 —— 让页面自己发一次请求，用 CDP Network 抓它带的 header。
//
// 用法：
//   node tools/dify_create_app.mjs --list
//   node tools/dify_create_app.mjs --name="ReadPal · 母稿预处理" --mode=workflow [--desc="..."]
//
// 退出码：0 成功；1 失败

const PORT = Number(process.env.DIFY_CDP_PORT || 9237);
const CDP = `http://127.0.0.1:${PORT}`;

const arg = (k, d = '') => {
  const p = process.argv.find(a => a.startsWith('--' + k + '='));
  return p ? p.slice(k.length + 3) : d;
};
const LIST = process.argv.includes('--list');
const NAME = arg('name');
const MODE = arg('mode', 'workflow');
const DESC = arg('desc', '');

const list = await (await fetch(`${CDP}/json/list`)).json();
const pages = list.filter(t => t.type === 'page' && !(t.url || '').startsWith('devtools://'));
const target = pages.find(p => (p.url || '').includes('dify')) || pages[0];
if (!target) { console.error('✗ 没有可用页签（Chrome 起了吗？）'); process.exit(1); }

const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id = 0; const pending = new Map(); let events = [];
ws.addEventListener('message', e => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  else if (m.method) events.push(m);
});
const send = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });

await send('Runtime.enable');
await send('Network.enable');
await send('Page.enable');

const ev = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result && r.result.exceptionDetails) {
    return { __err: (r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text || '').slice(0, 300) };
  }
  return r.result?.result?.value;
};

/* 让页面自己发一次请求，从 CDP 抓 x-csrf-token */
async function ensureCsrf() {
  events = [];
  await send('Page.navigate', { url: 'https://cloud.dify.ai/apps' });
  for (let i = 0; i < 20; i++) {
    await new Promise(r => setTimeout(r, 1000));
    const hit = events.find(e => e.method === 'Network.requestWillBeSent'
      && e.params.request.url.includes('/console/api/')
      && e.params.request.headers && e.params.request.headers['x-csrf-token']);
    if (hit) return hit.params.request.headers['x-csrf-token'];
  }
  return null;
}

const csrf = await ensureCsrf();
if (!csrf) { console.error('✗ 抓不到 x-csrf-token（Dify 会话可能已失效，请在 Chrome 里重新登录）'); process.exit(1); }
console.log('✓ 已取得 x-csrf-token（%d 字符）', csrf.length);

const H = { 'Content-Type': 'application/json', 'x-csrf-token': csrf };

if (LIST) {
  const out = await ev(`fetch('/console/api/apps?page=1&limit=100&name=&sort_by=last_modified',{credentials:'include',headers:${JSON.stringify(H)}}).then(async r=>({status:r.status, text: await r.text()}))`);
  if (out && out.__err) { console.error('✗ 失败：', out.__err); process.exit(1); }
  console.log('HTTP', out.status);
  try {
    const d = JSON.parse(out.text);
    (d.data || []).forEach(a => console.log('  %s  %-34s %s', a.id, (a.name || '').slice(0, 34), a.mode));
    console.log('共 %d 个', (d.data || []).length);
  } catch (e) { console.log(out.text.slice(0, 600)); }
  ws.close(); process.exit(0);
}

if (!NAME) { console.error('✗ 需要 --name'); process.exit(1); }

const body = JSON.stringify({ name: NAME, mode: MODE, icon: '📘', icon_background: '#FFEAD5', description: DESC });
const out = await ev(`fetch('/console/api/apps',{method:'POST',credentials:'include',headers:${JSON.stringify(H)},body:${JSON.stringify(body)}}).then(async r=>({status:r.status, text: await r.text()}))`);
if (!out) { console.error('✗ 无响应'); process.exit(1); }
console.log('HTTP', out.status);
let parsed = null; try { parsed = JSON.parse(out.text); } catch (e) {}
if (out.status === 201 || out.status === 200) {
  console.log('✓ 创建成功');
  console.log('  APP_ID =', parsed?.id);
  console.log('  name   =', parsed?.name, '| mode =', parsed?.mode);
} else {
  console.error('✗ 创建失败：', out.text.slice(0, 400));
  process.exit(1);
}
ws.close(); process.exit(0);
