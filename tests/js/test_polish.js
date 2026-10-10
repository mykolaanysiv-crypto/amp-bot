/* AMP XP v1.20.3.1 polish source contract; dependency-free Node smoke. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const js = fs.readFileSync('app/web/static/polish.js', 'utf8');
const css = fs.readFileSync('app/web/static/polish.css', 'utf8');
const base = fs.readFileSync('app/web/templates/base.html', 'utf8');
for (const token of ['window.AMPToast','amp-toast-close','data-toast-source','amp-editor-modal'])
  assert.ok(js.includes(token), `missing polish JS contract: ${token}`);
for (const token of ['white-space:nowrap','hyphens:none','.amp-toast-region','dialog.amp-modal','.ops-card.severity-high','.kpi-icon'])
  assert.ok(css.includes(token), `missing polish CSS contract: ${token}`);
assert.ok(base.includes('/static/polish.js?v=1.20.3.1'), 'polish.js cache token not wired');
assert.equal(base.includes('desktop-sidebar-toggle'), false, 'duplicate topbar sidebar button returned');
assert.equal(js.includes('eval('), false, 'unsafe eval detected');
assert.equal(js.includes('new Function'), false, 'unsafe dynamic function detected');
console.log('AMP v1.20.3.1 polish: wrapping, toasts, modals, overview icons and action layout PASS');
