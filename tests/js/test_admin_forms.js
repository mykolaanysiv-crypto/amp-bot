/* Standalone browser-logic smoke tests; no dependencies beyond Node. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Form {}
const listeners = {};
let fetches = 0;
const sandbox = {
  HTMLFormElement: Form,
  URL,
  Date,
  location: {href: 'https://amp.example/admin/events', origin: 'https://amp.example', assign() {throw new Error('Unexpected navigation');}, reload() {throw new Error('Unexpected reload');}},
  document: {
    addEventListener(name, callback) {listeners[name] = callback;},
    createElement() {return {setAttribute() {},scrollIntoView() {}, textContent: ''};}
  },
  FormData: class { constructor() {this.fields = {}} append(key, value) {this.fields[key] = value;} },
  fetch: async (_url, options) => {
    fetches++;
    assert.equal(options.body.fields.action, 'approve', 'the actual clicked button must be sent');
    return {ok:false,redirected:false,status:400,headers:{get(key){return key === 'content-type' ? 'application/json' : '';}},async json(){return {detail:'Некоректне значення'};}};
  },
};
let src = fs.readFileSync('app/web/static/admin_forms.js', 'utf8');
src = src.replace(/\}\)\(\);\s*$/, 'Object.assign(globalThis, {__checkEventDate: checkEventDate});})();');
vm.runInNewContext(src, sandbox);
function field(value) {return {value:String(value),willValidate:true,validity:{valid:true},setCustomValidity(message){this.validationMessage = message; this.validity.valid = !message;},closest(){return {textContent:'Поле'};},setAttribute(){},removeAttribute(){},focus(){},classList:{add(){},remove(){}}};}
const form = new Form();
form.method = 'post';form.action = 'https://amp.example/admin/events/create';form.dataset = {};
const fields = {day:field(25),month:field(9),year:field(2026),event_time:field('17:00'),end_day:field(25),end_month:field(9),end_year:field(2026),end_time:field('16:00')};
form.elements = Object.assign(Object.values(fields), {namedItem(key) {return fields[key] || null;}});
form.querySelector = () => form.error || null;
form.prepend = el => form.error = el;
form.querySelectorAll = () => [];
assert.equal(sandbox.__checkEventDate(form, true), false, 'end-before-start is rejected');
fields.end_time.value = '18:00';
assert.equal(sandbox.__checkEventDate(form, true), true, 'valid same-day event is accepted');
fields.day.value = '31';fields.month.value = '2';
assert.equal(sandbox.__checkEventDate(form, true), false, 'invalid calendar date is rejected');
fields.day.value = '25';fields.month.value = '9';
async function run() {
  fields.end_time.value = '16:00';
  await listeners.submit({target:form,defaultPrevented:false,submitter:{name:'action',value:'approve'},preventDefault(){}});
  assert.equal(fetches, 0, 'invalid event must not reach server');
  fields.end_time.value = '18:00';
  await listeners.submit({target:form,defaultPrevented:false,submitter:{name:'action',value:'approve'},preventDefault(){}});
  assert.equal(fetches, 1);
  assert.equal(form.error.textContent, 'Некоректне значення', 'server errors remain in the form');
  assert.equal(fields.end_time.value, '18:00', 'input survives a failed request');
  console.log('Admin form JS: invalid dates, submit action, inline error, preserved input PASS');
}
run().catch(err => {console.error(err);process.exitCode=1;});
