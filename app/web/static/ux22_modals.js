/* AMP XP 1.22 unified editors: moves live DOM forms, never clones server-bound inputs. */
(() => {
 'use strict';
 const pathname = window.location.pathname.replace(/\/$/, '') || '/';
 const pages = {
  '/admin/quests': ['.entity-create-card', 'Створити квест'],
  '/admin/tasks': ['.entity-create-card', 'Створити задачу'],
  '/admin/opportunities': ['.opportunity-create-card', 'Додати можливість'],
  '/admin/surveys': ['.survey-create-card', 'Створити опитування'],
  '/admin/quick-xp': ['.quick-xp-create-card', 'Створити швидке XP'],
  '/admin/rewards': ['.reward-create-form', 'Додати винагороду'],
  '/admin/badges': ['.badge-create-form', 'Створити бейдж'],
  '/admin/activities': ['.create-activity-form', 'Створити активність'],
  '/admin/ambassadors': ['.team-task-create', 'Створити завдання для команди'],
  '/admin/goals': ['.goal-builder-card', 'Створити ціль'],
  '/admin/giveaways': ['#giveawayCreateForm', 'Створити розіграш'],
  '/admin/seasons': ['form[action="/admin/seasons/create"]', 'Почати сезон'],
  '/admin/broadcasts': ['.custom-template-form', 'Створити шаблон повідомлення'],
  '/admin/donations': ['form[action="/admin/donations/reports/create"]', 'Створити звіт']
 };
 const config = pages[pathname] || (/^\/admin\/surveys\/\d+$/.test(pathname) ? ['.survey-question-create-card', 'Додати питання'] : null);
 if (!config) return;
 const head = document.querySelector('.page-head');
 if (!head) return;
 const dialog = document.createElement('dialog');
 dialog.className = 'ux22-dialog';
 dialog.setAttribute('aria-labelledby','ux22-dialog-title');
 dialog.innerHTML = '<section class="ux22-shell"><header class="ux22-header"><div><small>AMP XP · Редактор</small><h2 id="ux22-dialog-title"></h2></div><button type="button" class="ux22-close" aria-label="Закрити">×</button></header><div class="ux22-body"></div><footer class="ux22-footer"><button type="button" class="soft-button ux22-cancel">Скасувати</button></footer></section>';
 document.body.appendChild(dialog);
 const body = dialog.querySelector('.ux22-body');
 const title = dialog.querySelector('#ux22-dialog-title');
 let active = null;
 let changed = false;
 let opener = null;
 let pendingSubmit = false;
 const records = new Map();
 const attach = (node) => {
   if(records.has(node)) return;
   const marker = document.createComment('ux22 restore marker');
   node.parentNode.insertBefore(marker,node);
   records.set(node,marker);
   node.addEventListener('input',()=>{if(active===node)changed=true;});
   node.addEventListener('change',()=>{if(active===node)changed=true;});
   // Do not disable controls before the browser validates the form: only act
   // after successful native validation, preserving existing server handlers.
   (node.matches('form') ? [node] : [...node.querySelectorAll('form')]).forEach(form => {
     form.addEventListener('submit', e => {
       if (e.defaultPrevented || !form.checkValidity()) return;
       if (pendingSubmit) { e.preventDefault(); return; }
       pendingSubmit = true;
       changed = false;
       const submitter = e.submitter;
       if (submitter) {
         submitter.setAttribute('aria-disabled', 'true');
         submitter.classList.add('ux22-submitting');
         // Do not set .disabled: that removes name/value from FormData.
       }
     });
   });
 };
 const restore = () => {
   if(!active)return;
   const node=active;
   const marker=records.get(node);
   if(marker && marker.parentNode) marker.parentNode.insertBefore(node,marker.nextSibling);
   else if (node.isConnected) document.body.appendChild(node);
   if(node.matches('details')) node.open=false;
   node.hidden = node.dataset.ux22HiddenInitially === 'true';
   if (node.dataset.ux22CollapsedInitially === 'true') node.dataset.ux22Collapsed = 'true';
   else delete node.dataset.ux22Collapsed;
   delete node.dataset.ux22HiddenInitially;
   delete node.dataset.ux22CollapsedInitially;
   active=null;
   pendingSubmit=false;
   node.querySelectorAll('.ux22-submitting').forEach(button=>{button.removeAttribute('aria-disabled');button.classList.remove('ux22-submitting');});
   body.replaceChildren();
   if(opener && opener.isConnected && typeof opener.focus === 'function') opener.focus({preventScroll:true});
   opener=null;
 };
 const open = (node, heading, trigger) => {
   if(dialog.open || active) return;
   attach(node);
   changed=false;pendingSubmit=false;opener=trigger||document.activeElement;
   node.dataset.ux22HiddenInitially=String(node.hidden);
   node.dataset.ux22CollapsedInitially=String(node.dataset.ux22Collapsed === 'true');
   delete node.dataset.ux22Collapsed;
   node.hidden=false;
   if(node.matches('details'))node.open=true;
   title.textContent=heading;
   body.appendChild(node);
   active=node;
   if (typeof dialog.showModal !== 'function') { restore(); return; }
   try { dialog.showModal(); } catch (error) { restore(); throw error; }
   const first=node.querySelector('input:not([type="hidden"]):not([disabled]),select:not([disabled]),textarea:not([disabled])');
   if(first)first.focus({preventScroll:true});
   // Keep the dialog accessible when editing forms that are dynamically mounted.
   dialog.setAttribute('aria-modal','true');
 };
 const dismiss=()=>{
   if(changed && !window.confirm('У формі є незбережені зміни. Закрити без збереження?'))return;
   changed=false;
   dialog.close();
 };
 dialog.addEventListener('close',restore);
 dialog.addEventListener('cancel', e=>{e.preventDefault();dismiss();});
 dialog.addEventListener('click',e=>{if(e.target===dialog)dismiss();});
 dialog.querySelectorAll('.ux22-close,.ux22-cancel').forEach(x=>x.addEventListener('click',dismiss));
 const [selector,caption]=config;
 const source=document.querySelector(selector);
 if(source && (source.matches('form') || source.querySelector('form'))){
  attach(source);
  source.hidden=true;
  source.dataset.ux22Collapsed = 'true';
  const action=document.createElement('button');action.type='button';action.className='primary ux22-open';
  action.textContent='+ '+caption;
  head.appendChild(action);
  action.addEventListener('click',()=>open(source,caption,action));
 }
 // Use the existing server-backed edit form in its original DOM; restore after any close.
 const editSelector = [
   'details.event-edit-details',
   'details.quick-xp-edit-details',
   '.reward-card > details',
   '.badge-card > details',
   'details.survey-question-edit-details'
 ].join(',');
 document.querySelectorAll(editSelector).forEach(details=>{
   if(details===source || (source && source.contains(details)))return;
   const summary=details.querySelector(':scope > summary');
   const form=details.querySelector('form');
   if(!summary || !form)return;
   attach(details);
   summary.addEventListener('click',e=>{
     if(dialog.open)return;
     e.preventDefault();
     open(details,'Редагувати · '+(details.closest('article')?.querySelector('h3,h4')?.textContent?.trim()||'запис'),summary);
   });
 });
})();
