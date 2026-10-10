/* AMP XP v1.20.1 app-shell source contract; dependency-free Node smoke. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const src = fs.readFileSync('app/web/static/app_shell.js', 'utf8');
const base = fs.readFileSync('app/web/templates/base.html', 'utf8');
for (const token of [
  'amp-sidebar-collapsed', 'localStorage', 'setCollapsed', 'openSidebar', 'closeSidebar',
  'focusableInSidebar', 'trapSidebarFocus', "event.key === 'Escape'", 'mobileReturnFocus',
  "setAttribute('aria-expanded'", 'prefers-color-scheme: dark', 'data-live-region'
]) assert.ok(src.includes(token), `missing app-shell contract: ${token}`);
for (const token of ['data-sidebar-collapse','data-mobile-menu','data-sidebar-backdrop','skip-link','id="main-content"'])
  assert.ok(base.includes(token), `missing shell markup: ${token}`);
assert.equal(base.includes('onclick='), false, 'CSP-safe shell must not use inline event handlers');
console.log('AMP v1.20.1 app shell: collapse persistence, mobile focus/ESC and CSP-safe bindings PASS');
