// 图 C 解析节点（nodeParse）单测：正常 / 围栏 / 缺字段 / 越界 / 坏 JSON / 无 JSON
// 用法：node tools/probe_graphC_parse.mjs
import fs from 'node:fs';
import path from 'node:path';

const REPO = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const g = JSON.parse(fs.readFileSync(path.join(REPO, 'dify_graphs/graphC.new.json'), 'utf-8'));
const node = g.graph.nodes.find(n => n.id === 'nodeParse');
if (!node) { console.error('✗ 找不到 nodeParse'); process.exit(1); }
const main = eval(node.data.code + '; main');

let pass = 0, fail = 0;
const ok = (name, cond, extra = '') => {
  if (cond) { pass++; console.log(`  ✓ ${name}`); }
  else { fail++; console.log(`  ✗ ${name} ${extra}`); }
};

const GOOD = {
  articles_json: { A1: 'Pam keeps her room a mess.\n\nShe never puts things away.', A2: 'Pam is a clutterer.\n\nShe keeps a messy room and never tidies up.' },
  paras_json: { A1: ['Pam keeps her room a mess.', 'She never puts things away.'], A2: ['Pam is a clutterer.', 'She keeps a messy room and never tidies up.'] },
  quiz_json: { levels: {
    A1: [
      { type: 'language', q: 'What does "clutterer" mean?', options: ['a messy person', 'a cleaner', 'a teacher', 'a driver'], answer: 0, explain: 'clutterer 指把东西堆得乱糟糟的人。' },
      { type: 'language', q: 'Pam never ____ things away.', options: ['puts', 'eats', 'reads', 'buys'], answer: 0, explain: '原文 put things away。' },
      { type: 'text', q: 'Where does Pam keep her things?', options: ['In her room', 'In the car', 'At school', 'In the garden'], answer: 0, explain: '原文直接说 her room。' },
    ],
    A2: [
      { type: 'language', q: '"Tidy up" is closest in meaning to ____.', options: ['make clean', 'make dirty', 'give away', 'look at'], answer: 0, explain: 'tidy up = 收拾干净。' },
      { type: 'text', q: 'What is Sam Gosling?', options: ['A psychologist', 'A driver', 'A chef', 'A singer'], answer: 0, explain: '原文直说他是心理学家。' },
      { type: 'logic', q: 'Why does Pam lose her keys?', options: ['Her room is messy', 'She has no keys', 'The door is broken', 'She is late'], answer: 0, explain: '房间乱 → 找不到钥匙，需连读两句。' },
    ],
    B1: [
      { type: 'text', q: 'What did the study find about messy desks?', options: ['They can spark ideas', 'They slow people down', 'They cause illness', 'They save money'], answer: 0, explain: '原文说乱桌子可能激发想法。' },
      { type: 'logic', q: 'Why do cheap mooncakes sell well but earn less?', options: ['Low price with thin margin', 'People buy fewer', 'They expire fast', 'Shops hide them'], answer: 0, explain: '便宜→销量高但单件利润薄。' },
      { type: 'cognitive', q: 'What does the clutter study suggest about order?', options: ['Order is not always best', 'Order is always best', 'Mess is always bad', 'Nobody likes order'], answer: 0, explain: '考查对「整洁并非永远最优」的思辨。' },
    ],
  } },
};

console.log('\n[1] 正常输出（带 ```json 围栏）');
{
  const r = main({ text: '```json\n' + JSON.stringify(GOOD) + '\n```', title_in: 'The Clutterer' });
  ok('parse_ok=true', r.parse_ok === 'true');
  ok('title 透传', r.title === 'The Clutterer');
  const A = JSON.parse(r.articles_json), P = JSON.parse(r.paras_json), Q = JSON.parse(r.quiz_json);
  ok('articles 只有 A1/A2', Object.keys(A).sort().join(',') === 'A1,A2', JSON.stringify(Object.keys(A)));
  ok('paras 段数=A1:2 A2:2', P.A1.length === 2 && P.A2.length === 2);
  ok('quiz 三档齐', Object.keys(Q.levels).sort().join(',') === 'A1,A2,B1');
  ok('每档 3 题', Q.levels.A1.length === 3 && Q.levels.A2.length === 3 && Q.levels.B1.length === 3);
  ok('题型保留 language/text/logic/cognitive', Q.levels.B1[2].type === 'cognitive');
  ok('answer 为数字下标', Q.levels.A2[2].answer === 0);
  ok('无告警', r.parse_warn === '', r.parse_warn);
}

console.log('\n[2] 键写成 A1_1 / A2.1（Dify 老写法）');
{
  const t = JSON.parse(JSON.stringify(GOOD));
  t.articles_json = { A1_1: GOOD.articles_json.A1, A2_1: GOOD.articles_json.A2 };
  t.paras_json = { 'A1-1': GOOD.paras_json.A1, 'A2.1': GOOD.paras_json.A2 };
  const r = main({ text: JSON.stringify(t), title_in: 'T' });
  const A = JSON.parse(r.articles_json);
  ok('A1_1 → A1 归一化', !!A.A1 && !!A.A2, JSON.stringify(Object.keys(A)));
  ok('parse_ok=true', r.parse_ok === 'true');
}

console.log('\n[3] 缺 paras_json → 按换行拆 + 报警');
{
  const t = JSON.parse(JSON.stringify(GOOD)); delete t.paras_json;
  const r = main({ text: JSON.stringify(t), title_in: 'T' });
  const P = JSON.parse(r.paras_json);
  ok('按换行拆出段落', P.A1.length === 2, JSON.stringify(P.A1));
  ok('有告警提到 paras_json', /paras_json/.test(r.parse_warn), r.parse_warn);
}

console.log('\n[4] 缺 B1 题目 / answer 越界 / 未知题型 / 多余档');
{
  const t = JSON.parse(JSON.stringify(GOOD));
  delete t.quiz_json.levels.B1;
  t.quiz_json.levels.A1[0].answer = 9;
  t.quiz_json.levels.A1[1].type = 'vocab';
  t.articles_json.B1 = 'should not be used';
  const r = main({ text: JSON.stringify(t), title_in: 'T' });
  const Q = JSON.parse(r.quiz_json), A = JSON.parse(r.articles_json);
  ok('缺 B1 → 报警', /缺 B1 题目/.test(r.parse_warn), r.parse_warn);
  ok('answer 越界 → 置 0', Q.levels.A1[0].answer === 0);
  ok('未知题型 → 降为 text', Q.levels.A1[1].type === 'text');
  ok('多余 B1 文章不入库', !A.B1, JSON.stringify(Object.keys(A)));
  ok('多余档有告警', /额外产出/.test(r.parse_warn));
  ok('parse_ok 仍为 true', r.parse_ok === 'true');
}

console.log('\n[5] 坏 JSON → 显式报错，不静默');
{
  const r = main({ text: '{"articles_json": {"A1": "x",,}', title_in: 'T' });
  ok('parse_ok=false', r.parse_ok === 'false');
  ok('parse_warn 说明失败原因', /JSON 解析失败/.test(r.parse_warn), r.parse_warn);
  ok('articles_json 落回空对象', r.articles_json === '{}');
}

console.log('\n[6] 完全没有 JSON');
{
  const r = main({ text: 'Sure! Here are the articles you asked for.', title_in: 'T' });
  ok('parse_ok=false', r.parse_ok === 'false');
  ok('parse_warn 明确说找不到 JSON', /找不到 JSON/.test(r.parse_warn), r.parse_warn);
}

console.log(`\n${fail === 0 ? '✅' : '✗'} ${pass}/${pass + fail} 通过`);
process.exit(fail === 0 ? 0 : 1);
