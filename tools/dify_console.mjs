// 通过 CDP 在浏览器侧调 Dify 控制台 API，自动 refresh-token 重试
export async function makeCtx(port = process.env.DIFY_CDP_PORT || '9243', match = 'dify') {
  const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const pages = list.filter(t => t.type === 'page' && !(t.url || '').startsWith('devtools://'));
  const t = pages.find(p => (p.url || '').includes(match)) || pages[0];
  if (!t) throw new Error('no tab');
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  let id = 0; const pend = new Map();
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
  await new Promise(r => ws.onopen = r);
  const send = (method, params) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  // timeoutMs：Runtime.evaluate 的等待上限。调长耗时工作流（blocking，可达数分钟）时务必放大。
  const evaluateWithTimeout = async (expr, timeoutMs = 300000) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true, timeout: timeoutMs });
    if (r.result && r.result.exceptionDetails) throw new Error('eval err ' + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
    return r.result && r.result.result ? r.result.result.value : undefined;
  };
  const evaluate = (expr) => evaluateWithTimeout(expr, 300000);
  const refresh = async () => String(await evaluate('(async()=>{try{const r=await fetch("/console/api/refresh-token",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});return r.status;}catch(e){return "ERR "+e.message;}})()'));
  const csrf = async () => String(await evaluate(`(async()=>{const m=document.cookie.match(/csrf_token=([^;]+)/);return m?decodeURIComponent(m[1]):'';})()`));
  const call = async (path, { method = 'GET', body = null } = {}, retry = true) => {
    const c = await csrf();
    const payload = JSON.stringify({ path, method, body, csrf: c });
    const r = await evaluate(`(async()=>{try{
      const req={method:${JSON.stringify(method)},headers:{"Content-Type":"application/json","X-CSRF-Token":${JSON.stringify(c)}}};
      ${body ? 'req.body=' + JSON.stringify(JSON.stringify(body)) + ';' : ''}
      const res=await fetch(${JSON.stringify(path)},req);
      const txt=await res.text();
      return JSON.stringify({status:res.status,body:txt});
    }catch(e){return JSON.stringify({status:-1,body:"ERR "+e.message});}})()`);
    const o = JSON.parse(r);
    if (o.status === 401 && retry) { await refresh(); return call(path, { method, body }, false); }
    let parsed = null; try { parsed = JSON.parse(o.body); } catch (e) { }
    return { status: o.status, json: parsed, text: o.body };
  };
  return { evaluate, evaluateWithTimeout, call, refresh, close: () => ws.close(), info: t.url };
}
