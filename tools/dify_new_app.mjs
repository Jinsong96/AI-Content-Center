// ReadPal · 新建一个 Dify App（workflow），返回 app_id
//
// 用法：
//   node tools/dify_new_app.mjs --name="ReadPal · 事实检查" [--desc="..."] [--port=9243]
//
// 原理：POST /console/api/apps
//   body = { name, mode:"workflow", icon, icon_background, description }
//   ⚠️ 控制台接口鉴权是 cookie + X-CSRF-Token（不是 Bearer）。
import { makeCtx } from './dify_console.mjs';

const argv = process.argv.slice(2);
const arg = (k, d = null) => {
  const hit = argv.find(a => a.startsWith(`--${k}=`));
  return hit ? hit.slice(k.length + 3) : d;
};

const NAME = arg('name');
const DESC = arg('desc', '');
const ICON = arg('icon', '🔎');
const BG = arg('icon_background', '#E4FBCC');
const PORT = arg('port', process.env.DIFY_CDP_PORT || '9243');

if (!NAME) { console.error('用法: --name="应用名" [--desc=说明] [--port=9243]'); process.exit(1); }

const ctx = await makeCtx(PORT);
console.log(`[attach] ${ctx.info}`);
console.log(`[refresh] ${await ctx.refresh()}`);

const r = await ctx.call('/console/api/apps', {
  method: 'POST',
  body: {
    name: NAME,
    mode: 'workflow',
    icon: ICON,
    icon_background: BG,
    description: DESC,
    use_icon_as_answer_icon: false,
  },
});
console.log('status', r.status);
if (r.status !== 200 && r.status !== 201) {
  console.error('✗ 建 App 失败：', r.text.slice(0, 500));
  ctx.close();
  process.exit(1);
}
const app = r.json || {};
console.log('✓ app_id =', app.id);
console.log('  name   =', app.name, '| mode =', app.mode);
ctx.close();
