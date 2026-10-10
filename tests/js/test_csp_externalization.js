/* AMP XP v1.20.2 CSP source contract; dependency-free Node smoke. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const templateDir = 'app/web/templates';
const files = fs.readdirSync(templateDir).filter(name => name.endsWith('.html')).sort();
const handlerPattern = /\s(?:onclick|onchange|oninput|onsubmit|onload|onkeydown|onkeyup)=/i;
const scriptPattern = /<script([^>]*)>([\s\S]*?)<\/script>/gi;
const offenders = [];
for (const name of files) {
  const source = fs.readFileSync(path.join(templateDir, name), 'utf8');
  if (handlerPattern.test(source)) offenders.push(`${name}:inline-handler`);
  scriptPattern.lastIndex = 0;
  let match;
  while ((match = scriptPattern.exec(source)) !== null) {
    if (!/\bsrc\s*=/.test(match[1])) offenders.push(`${name}:inline-script`);
  }
}
assert.deepEqual(offenders, [], `CSP inline-JS offenders: ${offenders.join(', ')}`);

const base = fs.readFileSync('app/web/templates/base.html', 'utf8');
for (const token of [
  '/static/page_behaviors.js?v=1.20.2',
  '/static/app_shell.js?v=1.20.2',
  '/static/experience.js?v=1.20.2',
  '/static/interaction.js?v=1.20.2',
]) assert.ok(base.includes(token), `missing external runtime bundle: ${token}`);

for (const file of [
  'app/web/static/page_behaviors.js',
  'app/web/static/event_detail.js',
  'app/web/static/telegram_event_scanner.js',
  'app/web/static/analytics.js',
  'app/web/static/analytics_detail.js',
]) assert.ok(fs.existsSync(file), `missing external page script: ${file}`);

console.log('AMP v1.20.2 CSP externalization: no inline executable JS or HTML event handlers PASS');
