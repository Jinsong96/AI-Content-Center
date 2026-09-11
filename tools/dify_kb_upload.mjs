// ReadPal · 通过 CDP 向 Dify 知识库上传本地文件（走 UI，不猜 API）
//
// 用法：
//   node tools/dify_kb_upload.mjs --file=<绝对路径> [--port=9224]
//
// 前置：浏览器已停在 知识库 → Add file → Step 1「Upload file」页面
//       （用 dify_cdp.mjs --goto=<.../datasets/<ds>/documents/create> 打开）
//
// 原理：DOM.setFileInputFiles 给页面里的 <input type=file> 塞文件，
//       触发 React onChange，由前端自己完成上传。
//
// 退出码：0 成功；1 失败

import fs from 'node:fs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => {
  const hit = argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const FILE = arg('file');
const PORT = Number(arg('port', process.env.DIFY_CDP_PORT || 9224));
if (!FILE) { console.error('用法: --file=<绝对路径>'); process.exit(1); }
if (!fs.existsSync(FILE)) { console.error(`✗ 文件不存在: ${FILE}`); process.exit(1); }
console.log(`[file] ${FILE}  ${fs.statSync(FILE).size}B`);

const sleep = ms => new Promise(r => setTimeout(r, ms));

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const pages = list.filter(t => t.type === 'page' && !(t.url || '').startsWith('devtools://'));
const t = pages.find(p => (p.url || '').includes('dify')) || pages[0];
if (!t) { console.error('✗ 没有可用页签'); process.exit(1); }
console.log(`[attach] ${t.title} | ${t.url}`);

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
await send('DOM.enable');

// 1) 找 file input
const doc = await send('DOM.getDocument', { depth: -1, pierce: true });
const rootId = doc.result?.root?.nodeId;
const q = await send('DOM.querySelector', { nodeId: rootId, selector: 'input[type=file]' });
const nodeId = q.result?.nodeId;
if (!nodeId) {
  console.error('✗ 页面上没有 input[type=file]。确认已停在 Step 1 上传页。');
  ws.close(); process.exit(1);
}
console.log(`[input] input[type=file] nodeId=${nodeId}`);

// 2) 塞文件
const r = await send('DOM.setFileInputFiles', { files: [FILE], nodeId });
if (r.error) { console.error('✗ setFileInputFiles 失败: ' + JSON.stringify(r.error)); ws.close(); process.exit(1); }
console.log('[set] 文件已注入，等待前端上传…');

// 3) 观察页面变化
for (let i = 0; i < 20; i++) {
  await sleep(1500);
  const txt = await evaluate('document.body.innerText');
  const tail = String(txt).split('\n').map(s => s.trim()).filter(Boolean).slice(-14).join(' | ');
  console.log(`  [${i}] ${tail.slice(0, 300)}`);
  if (/DOCUMENT PROCESSING|EXECUTE & FINISH|Uploaded|Next/i.test(txt) && !/^Upload file$/m.test(tail)) {
    if (i >= 1) break;
  }
}
await send('Page.captureScreenshot', { captureBeyondViewport: false }).then(s => {
  if (s.result?.data) fs.writeFileSync('/tmp/kb_uploaded.png', Buffer.from(s.result.data, 'base64'));
});
console.log('[shot] /tmp/kb_uploaded.png');
ws.close();
process.exit(0);
