// 通过已运行的调试 Chrome（CDP 9222）渲染页面并输出 DOM。
// 用途：桥接层所在的受限沙箱内 subprocess Chrome 会 Abort trap 6 崩溃，
// 此时改用用户已开启的调试浏览器实例来渲染（仅供本地 demo 环境使用）。
// 用法: node cdp_render.js <url> [wait_ms]
const WebSocket = require("ws");
const url = process.argv[2];
const WAIT = parseInt(process.argv[3] || "25000", 10);
const CDP = "http://127.0.0.1:9222";

(async () => {
  let created = null;
  let ws = null;
  // 复用标签页：优先拿一个现成的空白页，避免每次 json/new 都激活窗口抢焦点。
  // 用完导航回 about:blank 留着下次用，而不是关掉（关闭/新建都会让 Chrome 抢前台）。
  const takeTab = async () => {
    try {
      const r = await fetch(CDP + "/json/list");
      const tabs = await r.json();
      const blank = (tabs || []).find(t => t.type === "page" && (t.url === "about:blank" || t.url === ""));
      if (blank && blank.webSocketDebuggerUrl) return blank;
    } catch (e) { /* 退回新建 */ }
    for (let i = 0; i < 3; i++) {
      try {
        const r = await fetch(CDP + "/json/new?about:blank", { method: "PUT" });
        const t = await r.json();
        if (t && t.webSocketDebuggerUrl) return t;
      } catch (e) { /* 重试 */ }
      await new Promise(r => setTimeout(r, 900));
    }
    return null;
  };
  const cleanup = async () => {
    try { if (ws) ws.close(); } catch (e) { }
    // 导航回空白页留待复用；彻底关闭会在下次渲染时重建窗口并抢焦点
    try {
      if (ws && created) {
        const w2 = new WebSocket(created.webSocketDebuggerUrl, { perMessageDeflate: false, maxPayload: 256 * 1024 * 1024 });
        await new Promise(r => { w2.on("open", r); w2.on("error", r); });
        w2.send(JSON.stringify({ id: 9999, method: "Page.navigate", params: { url: "about:blank" } }));
        await new Promise(r => setTimeout(r, 300));
        try { w2.close(); } catch (e) { }
      }
    } catch (e) { }
  };
  try {
    created = await takeTab();
    if (!created) throw new Error("无法获取标签页（Chrome 未响应）");
    ws = new WebSocket(created.webSocketDebuggerUrl, { perMessageDeflate: false, maxPayload: 256 * 1024 * 1024 });
    let id = 0; const p = new Map();
    ws.on("message", raw => {
      try { const m = JSON.parse(raw.toString()); if (m.id && p.has(m.id)) { p.get(m.id)(m); p.delete(m.id); } } catch (e) { }
    });
    await new Promise(r => ws.on("open", r));
    const send = (m, q) => new Promise((res, rej) => {
      const mid = ++id; p.set(mid, x => x.error ? rej(new Error(JSON.stringify(x.error))) : res(x.result));
      ws.send(JSON.stringify({ id: mid, method: m, params: q || {} }));
    });
    const ev = async (e) => {
      const r = await send("Runtime.evaluate", { expression: e, awaitPromise: true, returnByValue: true });
      return r.result ? r.result.value : null;
    };

    await send("Page.enable", {});
    await send("Page.navigate", { url });

    // 等待渲染出实质内容（最多 WAIT 毫秒）
    const deadline = Date.now() + WAIT;
    let textLen = 0;
    while (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 700));
      const t = await ev("(document.body.innerText||'')");
      textLen = (typeof t === "string") ? t.length : 0;
      if (textLen > 200) break;
    }
    const dom = await ev("document.documentElement.outerHTML");
    const domLen = (dom || "").length;
    if (domLen < 500) {
      // 页面没渲染出来：把可诊断的信息写 stderr，让桥接层记进日志
      process.stderr.write("页面未渲染 url=" + url + " textLen=" + textLen + " domLen=" + domLen);
      await cleanup();
      process.exit(2);          // 退出码 2 = 渲染未完成（区别于其它异常）
    }
    process.stdout.write(dom);
    await cleanup();
    process.exit(0);
  } catch (e) {
    await cleanup();
    process.stderr.write("cdp_render failed: " + String(e && e.message || e));
    process.exit(1);
  }
})();
