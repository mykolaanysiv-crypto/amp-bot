/* AMP XP v1.20.3.1 interaction source contract; dependency-free Node smoke. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const src = fs.readFileSync('app/web/static/interaction.js', 'utf8');
const account = fs.readFileSync('app/web/templates/account_security.html', 'utf8');
const base = fs.readFileSync('app/web/templates/base.html', 'utf8');
for (const token of [
  'URLSearchParams', 'history.replaceState', 'ArrowRight', 'ArrowLeft',
  'data-account-menu-button', 'participant-search', 'data-avatar-input',
  'data-help-category-filter', 'data-toast-region'
]) assert.ok(src.includes(token) || base.includes(token), `missing interaction contract: ${token}`);
for (const token of ['role="tablist"','role="tabpanel"','data-tabs-key="tab"'])
  assert.ok(account.includes(token), `missing account tabs markup: ${token}`);
for (const forbidden of ['href="#profile"','href="#achievements"','href="#security"','href="#sessions"'])
  assert.equal(account.includes(forbidden), false, `anchor-as-tab regression: ${forbidden}`);
assert.equal(src.includes('eval('), false, 'unsafe eval detected');
assert.equal(src.includes('new Function'), false, 'unsafe dynamic function detected');
console.log('AMP v1.20.3.1 interaction: real tabs, account menu, combobox, avatar preview and toast contracts PASS');
