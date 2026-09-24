// ReadPal · 把页面上「与生成侧探针共享」的函数**逐字**同步到 tools/probe_card_gen.mjs
//
// 为什么要这个工具：这些函数是页面与生成侧诊断的**同一条逻辑**（回炉指令、按档择优、增量合并、
// 回炉范围提示），两边必须逐字一致；靠手改已经漏同步过三次（漏 scopeHint / 把 buildFixList
// 整段删掉 / 注释差 103 字符）。同步完**必须**跑 tools/probe_card_check.mjs 的同源守卫复核。
//
// 用法：
//   node tools/sync_card_shared.mjs           # 只预演，打印每个函数的新旧长度
//   node tools/sync_card_shared.mjs --write   # 真的写回
//
// 退出码：0 成功；1 抽取失败（说明页面里函数名改了或结构变了）
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PAGE = path.join(REPO, 'frontend/card.html');
const PROBE = path.join(REPO, 'tools/probe_card_gen.mjs');
const WRITE = process.argv.includes('--write');

/* 大括号配对抽取（跳过字符串 / 模板串 / 行注释 / 块注释）——
   用正则找「下一个 function」会跑过头，见 probe_card_check.mjs 的同源守卫。 */
function grabFn(src, name) {
  const i = src.indexOf('function ' + name + '(');
  if (i < 0) return null;
  let d = 0, q = null, esc = false, line = false, blk = false;
  for (let k = src.indexOf('{', i); k < src.length; k++) {
    const c = src.charAt(k), n = src.charAt(k + 1);
    if (line) { if (c === '\n') line = false; continue; }
    if (blk) { if (c === '*' && n === '/') { blk = false; k++; } continue; }
    if (q) {
      if (esc) { esc = false; continue; }
      if (c === '\\') { esc = true; continue; }
      if (c === q) q = null;
      continue;
    }
    if (c === '/' && n === '/') { line = true; k++; continue; }
    if (c === '/' && n === '*') { blk = true; k++; continue; }
    if (c === '"' || c === "'" || c === '`') { q = c; continue; }
    if (c === '{') d++;
    else if (c === '}') { d--; if (d === 0) return src.slice(i, k + 1); }
  }
  return null;
}

const NAMES = ['keepBest', 'assembleBest', 'mergeCard', 'failingLevels', 'scopeHint', 'buildFixList'];
let page = fs.readFileSync(PAGE, 'utf-8');
const probe = fs.readFileSync(PROBE, 'utf-8');
let out = probe, bad = 0;

NAMES.forEach(n => {
  const a = grabFn(page, n), b = grabFn(out, n);
  if (!a) { console.error('✗ 页面里抽不到 ' + n); bad++; return; }
  if (!b) { console.error('✗ 探针里抽不到 ' + n + '（结构变了，需人工处理）'); bad++; return; }
  if (a === b) { console.log('  = ' + n + ' 已一致（' + a.length + ' 字符）'); return; }
  console.log('  → ' + n + ' 同步：探针 ' + b.length + ' → ' + a.length + ' 字符');
  out = out.replace(b, a);
});
if (bad) { console.error('\n抽取失败 ' + bad + ' 个，未写盘。'); process.exit(1); }
if (out === probe) { console.log('\n无需改动。'); process.exit(0); }
if (!WRITE) { console.log('\n（预演，未写盘；加 --write 生效）'); process.exit(0); }
fs.writeFileSync(PROBE, out, 'utf-8');
console.log('\n✓ 已写回 ' + path.relative(REPO, PROBE) + ' —— 请跑 node tools/probe_card_check.mjs 复核同源守卫');
