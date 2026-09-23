#!/usr/bin/env node
/* 读线上 ReadPal 首页注入的 window.WB_CONFIG（密钥默认打码），用来核实
   「Railway 环境变量有没有真的进到容器」。

   为什么需要它：沙箱**无法直连** Railway 域名（curl / fetch 一律 000），
   但本机可见 Chrome 走系统网络可以。本脚本借它的 CDP 页签读真实 DOM。

   用法：
     node tools/read_live_config.mjs                    # 自动找/开线上页签
     CDP_PORT=9243 node tools/read_live_config.mjs      # 指定 Chrome 调试端口
     SHOW=1 node tools/read_live_config.mjs             # 打印明文（默认只打前 11 位）

   典型排错：某 key 显示 "(空)" ⇒ 容器里取不到。检查顺序
     ① Railway 变量编辑是**暂存**的：改完必须点左上角 "Apply N changes" 才生效（踩过）
     ② 变量名逐字符比对（大小写 / 首尾空格）
     ③ 加在了别的 service 或别的 environment
     ④ 三条来源优先级：os.environ > frontend/config.local.js > backend/keys.fallback.json
        （后两者线上都没有 ⇒ 云端只认环境变量，除非 key 写进了 keys.fallback.json）
*/
const PORT = process.env.CDP_PORT || 9243;
const LIVE = process.env.URL_LIVE || 'https://web-production-2a16e.up.railway.app/';
const SHOW = process.env.SHOW === '1';

const j = async (p) => (await fetch(`http://127.0.0.1:${PORT}${p}`)).json();

// ① 找已打开的线上页签；没有就新开一个
let list = await j('/json/list');
let target = list.find(t => t.type === 'page' && t.url.startsWith(LIVE.replace(/\/$/, '')));
if (!target) {
  await fetch(`http://127.0.0.1:${PORT}/json/new?${LIVE}`, { method: 'PUT' }).catch(() => {});
  await new Promise(r => setTimeout(r, 5000));
  list = await j('/json/list');
  target = list.find(t => t.type === 'page' && t.url.startsWith(LIVE.replace(/\/$/, '')));
}
if (!target) { console.error(`✗ 端口 ${PORT} 上没有 ${LIVE} 的页签，也没能新建`); process.exit(1); }

const ws = new WebSocket(target.webSocketDebuggerUrl);
let id = 0; const pending = new Map();
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
});
await new Promise(r => ws.addEventListener('open', r));
const evaluate = async (expr) => {
  const i = ++id;
  const r = await new Promise(res => { pending.set(i, res); ws.send(JSON.stringify({ id: i, method: 'Runtime.evaluate', params: { expression: expr, returnByValue: true } })); });
  const res = (r.result || {}).result;
  return res ? res.value : null;
};

const raw = await evaluate(`(function(){
  var c = window.WB_CONFIG;
  return c ? JSON.stringify(c) : null;
})()`);

if (!raw) { console.error('✗ 页面上没有 window.WB_CONFIG（后端没注入？或页面还没加载完）'); process.exit(1); }
const cfg = JSON.parse(raw);

const mask = (v) => { const s = String(v || ''); return s ? (SHOW ? s : s.slice(0, 11) + '…') + ` (len=${s.length})` : '(空)'; };
const head = (k) => k.startsWith('DIFY_WF_', 0) || k === 'SF_API_KEY';

console.log(`源：${target.url}`);
console.log(`--- Dify / 大模型密钥（env 变量面板控制的就是这些）---`);
Object.keys(cfg).filter(head).sort().forEach(k => {
  const flag = String(cfg[k] || '') ? '  ' : '⚠️ ';
  console.log(`${flag}${k.padEnd(16)} ${mask(cfg[k])}`);
});
const miss = Object.keys(cfg).filter(k => head(k) && !String(cfg[k] || ''));
console.log(miss.length ? `\n✗ ${miss.length} 项为空：${miss.join(', ')}` : '\n✓ 全部有值');
ws.close();
