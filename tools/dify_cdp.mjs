// ReadPal · Dify 控制台 CDP 驱动（零第三方依赖）
//
// 用途：操作「已经人工登录好」的 Dify 控制台。
//   与 cdp_shot.mjs 的关键区别：
//     1) 它复用【已存在的页签】，不新开标签，因此保留登录态；
//     2) 它【不启动也不关闭】Chrome —— Chrome 由 /tmp/launch_dify_chrome.py 以
//        双 fork + setsid 方式常驻；本脚本只做 attach。
//
// 用法：
//   node tools/dify_cdp.mjs [--port=9224] [--match=cloud.dify.ai]
//        [--goto=<url>] [--wait=5000]
//        [--eval="<js>"]          在页面里执行 JS，打印返回值
//        [--text] [--limit=6000]  打印 document.body.innerText
//        [--shot=/tmp/x.png] [--full]
//
// 典型用法：
//   node tools/dify_cdp.mjs --text                       # 看看现在页面上有什么
//   node tools/dify_cdp.mjs --eval="location.href"       # 当前地址
//
// 退出码：0 成功；1 失败

import fs from 'node:fs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => {
  const hit = argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};
const has = k => argv.includes(`--${k}`);

const PORT = Number(arg('port', process.env.DIFY_CDP_PORT || 9224));
const CDP = `http://127.0.0.1:${PORT}`;
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function pickTarget() {
  const list = await (await fetch(`${CDP}/json/list`)).json();
  const pages = list.filter(t => t.type === 'page' && !(t.url || '').startsWith('devtools://'));
  const want = arg('match', 'dify');
  const hit = pages.find(p => (p.url || '').includes(want));
  return hit || pages[0];
}

async function main() {
  let t;
  try {
    t = await pickTarget();
  } catch (e) {
    console.error(`✗ 连不上 CDP ${CDP}。Chrome 起了吗？先跑 /tmp/launch_dify_chrome.py`);
    process.exit(1);
  }
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
    const r = await send('Runtime.evaluate', {
      expression: expr, returnByValue: true, awaitPromise: true, userGesture: true,
    });
    if (r.result?.exceptionDetails) {
      return `[JS ERROR] ${r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text}`;
    }
    const v = r.result?.result?.value;
    return v === undefined ? '(undefined)' : v;
  };

  await send('Runtime.enable');
  await send('Page.enable');

  const goto = arg('goto');
  if (goto) {
    await send('Page.navigate', { url: goto });
    await sleep(Number(arg('wait', 5000)));
    console.log(`[goto] ${goto}`);
  }

  const ev = arg('eval');
  if (ev) {
    const r = await evaluate(ev);
    const outFile = arg('out');
    if (outFile) {
      fs.writeFileSync(outFile, typeof r === 'string' ? r : JSON.stringify(r, null, 1));
      console.log(`[eval→file] ${outFile} (${fs.statSync(outFile).size}B)`);
    } else {
      console.log('--- eval ---');
      console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 1));
    }
  }

  if (has('text')) {
    const txt = await evaluate('document.body.innerText');
    console.log('--- innerText ---');
    console.log(String(txt).slice(0, Number(arg('limit', 6000))));
  }

  const shot = arg('shot');
  if (shot) {
    const s = await send('Page.captureScreenshot', { captureBeyondViewport: has('full') });
    if (!s.result?.data) { console.error('✗ 截图失败'); process.exit(1); }
    fs.writeFileSync(shot, Buffer.from(s.result.data, 'base64'));
    console.log(`[shot] ${shot} (${fs.statSync(shot).size}B)`);
  }

  ws.close();
  process.exit(0);
}
main().catch(e => { console.error('FAIL', e); process.exit(1); });
