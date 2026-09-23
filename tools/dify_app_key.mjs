// ReadPal · 读取 / 创建 Dify 应用的 API Key（service API，形如 app-xxxx）
//
// 用法：
//   node tools/dify_app_key.mjs --app=<app_id> --list
//   node tools/dify_app_key.mjs --app=<app_id> --create
//
// 原理（走已登录 Chrome 的 CDP，浏览器侧 fetch 带 cookie）：
//   GET  /console/api/apps/{app}/api-keys         列出
//   POST /console/api/apps/{app}/api-keys         创建，body={}，返回 token 明文（仅此一次）
//
// ⚠️ Dify 现在**连 GET 也校验 X-CSRF-Token**（2026-09-22 起），三处 fetch 必须都带头。
//
// 退出码：0 成功；1 失败

const argv = process.argv.slice(2);
const arg = (k, d = null) => {
  const hit = argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const has = k => argv.includes(`--${k}`);

const APP = arg('app');
const PORT = Number(arg('port', process.env.DIFY_CDP_PORT || 9224));
if (!APP) { console.error('用法: --app=<app_id> --list | --create'); process.exit(1); }

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
await send('Runtime.enable');

const H = `var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');var h={'X-CSRF-Token':t,'Content-Type':'application/json'};`;

const call = async (method, path, body) => {
  const res = await evaluate(`(async function(){${H}
    return fetch('${path}',{method:'${method}',credentials:'include',headers:h${body ? `,body:${JSON.stringify(JSON.stringify(body))}` : ''}})
      .then(function(r){return r.text().then(function(x){return r.status+' ||| '+x.slice(0,4000);});});
  })()`);
  const [st, txt] = String(res).split(' ||| ');
  return { status: Number(st), text: txt || '' };
};

if (has('list')) {
  const r = await call('GET', `/console/api/apps/${APP}/api-keys`);
  console.log('HTTP', r.status);
  try {
    const d = JSON.parse(r.text);
    (d.data || []).forEach(k => console.log('  ' + k.id + '  ' + (k.token || '(隐藏)') + '  created=' + k.created_at));
    console.log('共 %d 个', (d.data || []).length);
  } catch (e) { console.log(r.text.slice(0, 800)); }
  ws.close(); process.exit(0);
}

if (has('create')) {
  const r = await call('POST', `/console/api/apps/${APP}/api-keys`, {});
  console.log('HTTP', r.status);
  let parsed = null; try { parsed = JSON.parse(r.text); } catch (e) {}
  if (r.status === 201 || r.status === 200) {
    console.log('✓ 创建成功');
    console.log('API_KEY=' + (parsed?.token || '(未返回)'));
  } else {
    console.error('✗ 创建失败：', r.text.slice(0, 500));
    ws.close(); process.exit(1);
  }
  ws.close(); process.exit(0);
}

console.error('✗ 需要 --list 或 --create');
ws.close(); process.exit(1);
