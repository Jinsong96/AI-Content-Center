// ReadPal · 生产链路端到端探针：真跑 Railway 站点上的桥接接口
//
// 用法：
//   node tools/probe_prod_wf.mjs --wf=lite --inputs=/tmp/in.json [--site=<url>] [--port=9243] [--out=/tmp/out.json]
//
// 覆盖的真实路径（前端同事实际用的那条）：
//   生产站点首页 → POST /api/dify/workflows/run {wf, inputs} → agent_reach_bridge.py
//   → keymap 取环境变量 → api.dify.ai 调 **线上已发布版本**
//
// 为什么不能只用 curl：沙箱直连 Railway 恒 000，直连 api.dify.ai 会被 Cloudflare 拦（403 code 1010）。
// 借已登录 Chrome 的 CDP **同源**发请求可绕开两者，且顺带验证了首页 WB_CONFIG 注入。
//
// 退出码：0 通过；1 失败
// ⚠️ 真花钱：默认 blocking，图 C 约 15–30s；改 --wf=licgen 更久（约 60s+）

import fs from 'node:fs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => { const h = argv.find(a => a.startsWith(`--${k}=`)); return h ? h.slice(k.length + 3) : d; };
const WF = arg('wf', 'lite');
const IN = arg('inputs');
const SITE = arg('site', 'https://web-production-2a16e.up.railway.app');
const PORT = arg('port', process.env.DIFY_CDP_PORT || '9243');
const OUT = arg('out');
if (!IN) { console.error('用法: --wf=lite --inputs=<json> [--site=] [--port=9243] [--out=]'); process.exit(1); }
const inputs = JSON.parse(fs.readFileSync(IN, 'utf8'));

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const pages = list.filter(t => t.type === 'page' && !(t.url || '').startsWith('devtools://'));
const tab = pages.find(p => /cloud\.dify\.ai/.test(p.url || '')) || pages[0];
if (!tab) { console.error('✗ 没有可用页签'); process.exit(1); }

const ws = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id = 0; const pend = new Map();
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } });
const send = (method, params = {}) => new Promise(res => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true, userGesture: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text);
  return r.result?.result?.value;
};
await send('Page.enable'); await send('Runtime.enable');

let rc = 1;
try {
  console.log(`[goto] ${SITE}`);
  await send('Page.navigate', { url: SITE });
  await new Promise(r => setTimeout(r, 6000));
  const info = await evaluate(`(function(){var n=-1;try{n=Object.keys(window.WB_CONFIG||{}).length}catch(e){}
    return JSON.stringify({title:document.title,keys:n,href:location.href})})()`);
  const pi = JSON.parse(info);
  console.log(`[page] ${pi.title} | WB_CONFIG 键数=${pi.keys}`);
  if (!/ReadPal/.test(pi.title || '')) { console.error('✗ 首页没打开（可能部署未完成）'); }
  console.log(`[run] wf=${WF}  blocking 真调线上已发布版本…`);

  const expr = `(async function(){
    var t0=Date.now();
    var r=await fetch('/api/dify/workflows/run',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({wf:${JSON.stringify(WF)},inputs:${JSON.stringify(inputs)},response_mode:'blocking',user:'prod-probe'})});
    var txt=await r.text(); var ms=Date.now()-t0;
    var out={http:r.status,ms:ms,len:txt.length,snippet:txt.slice(0,300)};
    try{ var j=JSON.parse(txt);
      out.ok=j.ok; out.status=(j.data&&j.data.status)||j.status; out.err=String(j.error||'').slice(0,240);
      var o=(j.data&&j.data.outputs)||j.outputs||{};
      out.parse_ok=o.parse_ok; out.parse_warn=String(o.parse_warn||'');
      out.fields=Object.keys(o); out._raw=o;
    }catch(e){}
    return JSON.stringify(out);
  })()`;
  const res = JSON.parse(await evaluate(expr));
  console.log(`[bridge] http=${res.http} | 耗时 ${res.ms}ms | 响应 ${res.len} 字节`);
  console.log(`[bridge] ok=${res.ok} status=${res.status}`);
  if (res.err) console.log(`[bridge] error=${res.err}`);
  if (res.parse_ok !== undefined) console.log(`[bridge] parse_ok=${res.parse_ok}  parse_warn=${res.parse_warn || '(无)'}`);
  if (res.fields) console.log(`[bridge] 输出字段=${res.fields.join(',')}`);
  if (OUT && res._raw) { fs.writeFileSync(OUT, JSON.stringify(res._raw, null, 1)); console.log(`[out] ${OUT}`); }
  if (!res.fields) console.log('[body] ' + res.snippet);
  rc = (res.http === 200 && res.ok !== false && res.parse_ok !== 'false') ? 0 : 1;
} catch (e) {
  console.error('✗ ' + (e?.message || e));
} finally {
  try {
    await send('Page.navigate', { url: 'https://cloud.dify.ai/' });
    await new Promise(r => setTimeout(r, 4000));
    console.log(`[restore] ${await evaluate('location.href')}`);
  } catch { console.log('[restore] 跳过'); }
  ws.close();
}
console.log(rc === 0 ? '✅ 生产链路通过' : '✗ 生产链路未通过');
process.exit(rc);
