/* AMP XP v1.20.3.1 visual-experience source contract; dependency-free Node smoke. */
const fs = require('fs');
const src = fs.readFileSync('app/web/static/experience.js', 'utf8');
const required = [
  'data-modal-open', 'data-modal-close', 'confirmMessage', 'showModal',
  'data-help-search', 'edit-action-button', 'amp-theme', "dialog.addEventListener('close'"
];
for (const token of required) {
  if (!src.includes(token)) throw new Error(`Missing experience token: ${token}`);
}
if (src.includes('eval(') || src.includes('new Function')) throw new Error('Unsafe dynamic JavaScript detected');
console.log('AMP v1.20.3.1 experience: dialogs, confirmations, help search, edit enhancement and theme PASS');
