// ReadPal · 在 Dify 上运行 draft 工作流并解析 SSE 事件流
//
// 用途：改完工作流后，在【不发布】的前提下真实跑一遍，逐节点看耗时/状态/输出。
//   published 版本完全不受影响，线上依旧跑旧版。
//
// 用法：
//   node tools/dify_run_draft.mjs --app=<app_id> --inputs=<inputs.json> [--port=9224]
//        [--keys=title,article_a2,validation_score]   # 只打印这些输出字段（默认打印全部键名）
//        [--raw=/tmp/run.json]                        # 把完整事件流落盘
//
// 退出码：0 workflow succeeded；2 failed；1 连接/参数错误

import fs from 'node:fs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => {
  const hit = argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const APP = arg('app');
const INPUTS = arg('inputs');
const PORT = Number(arg('port', process.env.DIFY_CDP_PORT || 9224));
if (!APP || !INPUTS) { console.error('用法: --app=<app_id> --inputs=<file.json>'); process.exit(1); }
const inputs = JSON.parse(fs.readFileSync(INPUTS, 'utf-8'));
console.log(`[inputs] ${JSON.stringify(inputs).slice(0, 200)}`);

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

const expr = `(function(){
  var t=decodeURIComponent((document.cookie.match(/__Host-csrf_token=([^;]+)/)||[])[1]||'');
  var h={'X-CSRF-Token':t,'Content-Type':'application/json'};
  var T0=Date.now();
  var IN=${JSON.stringify(inputs)};
  return fetch('/console/api/apps/${APP}/workflows/draft/run',{method:'POST',credentials:'include',headers:h,
    body:JSON.stringify({inputs:IN,files:[]})})
   .then(function(r){
     if(!r.ok){ return r.text().then(function(x){return JSON.stringify({http:r.status,body:x.slice(0,500)});}); }
     var rd=r.body.getReader(), dec=new TextDecoder(), buf='';
     var evs=[];
     function pump(){
       return rd.read().then(function(o){
         if(o.done){ evs.push({_end:true}); return JSON.stringify({elapsed:Date.now()-T0,events:evs}); }
         buf+=dec.decode(o.value,{stream:true});
         var parts=buf.split('\\n\\n'); buf=parts.pop();
         for(var i=0;i<parts.length;i++){
           var L=parts[i].split('\\n').filter(function(x){return x.indexOf('data: ')===0;});
           for(var j=0;j<L.length;j++){
             try{ evs.push(JSON.parse(L[j].slice(6))); }catch(e){}
           }
         }
         return pump();
       });
     }
     return pump();
   });
})()`;

console.log('[run] 提交 draft 并等待…');
const t0 = Date.now();
const res = await evaluate(expr);
const parsed = JSON.parse(res);

if (parsed.http) { console.error(`✗ HTTP ${parsed.http}: ${parsed.body}`); process.exit(1); }
if (arg('raw')) { fs.writeFileSync(arg('raw'), JSON.stringify(parsed, null, 1)); console.log(`[raw] ${arg('raw')}`); }

const evs = parsed.events || [];
const started = new Map();
let wf = null;
console.log(`\n[节点] 共 ${evs.length} 个事件`);
for (const e of evs) {
  if (e.event === 'node_started') started.set(e.data.node_id, Date.now());
  if (e.event === 'node_finished') {
    const d = e.data;
    const el = d.elapsed_time != null ? Number(d.elapsed_time).toFixed(1) + 's' : '';
    console.log(`  ${d.status === 'succeeded' ? '✓' : '✗'} ${String(d.title).padEnd(26)} ${String(el).padStart(8)}  ${d.error || ''}`);
    if (d.status !== 'succeeded') console.log(`      inputs=${JSON.stringify(d.inputs).slice(0, 200)}`);
  }
  if (e.event === 'workflow_finished') wf = e.data;
}

if (!wf) { console.error('\n✗ 没有 workflow_finished 事件'); process.exit(1); }
console.log(`\n[workflow] status=${wf.status} 总耗时=${(wf.elapsed_time / 1000).toFixed(1)}s  ${wf.error || ''}`);

if (wf.outputs) {
  const keys = arg('keys');
  console.log('\n[输出]');
  if (keys) {
    keys.split(',').forEach(k => {
      let v = wf.outputs[k];
      if (typeof v === 'string' && v.length > 400) v = v.slice(0, 400) + `…(共 ${v.length} 字符)`;
      console.log(`  ${k} = ${typeof v === 'string' ? v : JSON.stringify(v)}`);
    });
  } else {
    Object.keys(wf.outputs).forEach(k => {
      const v = wf.outputs[k];
      const s = typeof v === 'string' ? v : JSON.stringify(v);
      console.log(`  ${k} (${s ? s.length : 0}) = ${String(s).slice(0, 110)}`);
    });
  }
}
ws.close();
process.exit(wf.status === 'succeeded' ? 0 : 2);
