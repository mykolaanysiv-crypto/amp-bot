/* AMP XP v1.20.3 — CSP-safe page behaviours for server-rendered admin pages. */
(function () {
  'use strict';

  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function temporaryButtonState(button, text, timeout = 1800) {
    if (!(button instanceof HTMLElement)) return;
    const original = button.innerHTML;
    button.textContent = text;
    button.classList.add('is-success');
    window.setTimeout(() => {
      button.innerHTML = original;
      button.classList.remove('is-success');
    }, timeout);
  }

  async function copyText(value, button) {
    if (!value) return false;
    try {
      await navigator.clipboard.writeText(value);
      temporaryButtonState(button, 'Скопійовано');
      return true;
    } catch (_err) {
      return false;
    }
  }

  // Event and opportunity share controls.
  qsa('[data-copy-source]').forEach(button => button.addEventListener('click', () => {
    const source = document.getElementById(button.dataset.copySource || '');
    copyText(source?.value || button.dataset.copyUrl || '', button);
  }));
  qsa('[data-share-source]').forEach(button => button.addEventListener('click', async () => {
    const source = document.getElementById(button.dataset.shareSource || '');
    const url = button.dataset.shareUrl || source?.value || '';
    if (!url) return;
    if (navigator.share) {
      try { await navigator.share({title: button.dataset.shareTitle || undefined, url}); return; } catch (_err) { return; }
    }
    await copyText(url, button);
  }));

  // Goals: personal target picker.
  const goalScope = qs('#goalScope');
  const goalUserField = qs('#goalUserField');
  if (goalScope && goalUserField) {
    const sync = () => { goalUserField.style.display = goalScope.value === 'personal' ? 'flex' : 'none'; };
    goalScope.addEventListener('change', sync);
    sync();
  }

  // Survey audience controls, shared by create/edit forms.
  function surveyChecks(suffix) {
    return qsa(`#surveyUserPicker${suffix} input[name="audience_user_ids"]`);
  }
  function surveyCount(suffix) {
    const counter = qs(`#surveyAudienceCount${suffix}`);
    if (counter) counter.textContent = String(surveyChecks(suffix).filter(item => item.checked).length);
  }
  function surveyFilter(suffix) {
    const value = (qs(`#surveyAudienceSearch${suffix}`)?.value || '').trim().toLowerCase();
    qsa(`#surveyUserPicker${suffix} .survey-user-option`).forEach(row => {
      row.hidden = Boolean(value && !(row.dataset.search || '').includes(value));
    });
  }
  function surveySetVisible(suffix, checked) {
    qsa(`#surveyUserPicker${suffix} .survey-user-option`).forEach(row => {
      const input = qs('input[name="audience_user_ids"]', row);
      if (!row.hidden && input) input.checked = checked;
    });
    surveyCount(suffix);
  }
  function surveyToggle(suffix) {
    const select = qs(`#surveyAudience${suffix}`);
    if (!select) return;
    const eventBox = qs(`#surveyAudienceEvent${suffix}`);
    const usersBox = qs(`#surveyAudienceUsers${suffix}`);
    if (eventBox) eventBox.style.display = select.value === 'event' ? 'grid' : 'none';
    if (usersBox) usersBox.style.display = select.value === 'users' ? 'grid' : 'none';
    surveyCount(suffix);
  }
  ['Create', 'Edit'].forEach(suffix => {
    const select = qs(`#surveyAudience${suffix}`);
    if (!select) return;
    select.addEventListener('change', () => surveyToggle(suffix));
    qs(`#surveyAudienceSearch${suffix}`)?.addEventListener('input', () => surveyFilter(suffix));
    qs(`#surveyUserPicker${suffix}`)?.addEventListener('change', event => {
      if (event.target.matches('input[name="audience_user_ids"]')) surveyCount(suffix);
    });
    qsa(`[data-survey-select-visible="${suffix}"]`).forEach(button => button.addEventListener('click', () => surveySetVisible(suffix, true)));
    qsa(`[data-survey-clear="${suffix}"]`).forEach(button => button.addEventListener('click', () => {
      surveyChecks(suffix).forEach(item => { item.checked = false; });
      surveyCount(suffix);
    }));
    surveyToggle(suffix);
  });

  // Survey question option builder.
  const optionRowsRoot = qs('#surveyOptionRows');
  const surveyQuestionType = qs('#surveyQuestionType');
  const surveyOptionsBuilder = qs('#surveyOptionsBuilder');
  const surveyQuestionForm = qs('.survey-question-form');
  const optionRows = () => optionRowsRoot ? qsa('.survey-option-input-row', optionRowsRoot) : [];
  const renumberOptions = () => optionRows().forEach((row, index) => {
    const number = qs('span', row); const input = qs('input', row);
    if (number) number.textContent = String(index + 1);
    if (input) input.placeholder = `Варіант ${index + 1}`;
  });
  function addSurveyOption(value = '') {
    if (!optionRowsRoot) return;
    const row = document.createElement('div');
    row.className = 'survey-option-input-row';
    const number = document.createElement('span');
    const input = document.createElement('input'); input.type = 'text'; input.value = value;
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'survey-option-remove'; remove.dataset.removeSurveyOption = '1'; remove.setAttribute('aria-label','Видалити варіант'); remove.textContent = '×';
    row.append(number, input, remove); optionRowsRoot.append(row); renumberOptions(); input.focus();
  }
  function removeSurveyOption(button) {
    const row = button.closest('.survey-option-input-row'); if (!row) return;
    const rows = optionRows();
    if (rows.length <= 2) { const input = qs('input', row); if (input) input.value = ''; return; }
    row.remove(); renumberOptions();
  }
  const toggleSurveyOptions = () => {
    if (surveyQuestionType && surveyOptionsBuilder) surveyOptionsBuilder.style.display = surveyQuestionType.value === 'text' ? 'none' : 'grid';
  };
  qs('[data-survey-add-option]')?.addEventListener('click', () => addSurveyOption());
  optionRowsRoot?.addEventListener('click', event => {
    const button = event.target.closest('[data-remove-survey-option],.survey-option-remove');
    if (button) removeSurveyOption(button);
  });
  surveyQuestionType?.addEventListener('change', toggleSurveyOptions);
  if (surveyQuestionForm) {
    surveyQuestionForm.addEventListener('submit', event => {
      const type = surveyQuestionType?.value || 'text';
      const values = optionRows().map(row => (qs('input', row)?.value || '').trim()).filter(Boolean);
      const target = qs('#surveyOptionsValue'); if (target) target.value = values.join('\n');
      if (type !== 'text' && values.length < 2) {
        event.preventDefault();
        const first = qs('input', optionRowsRoot);
        first?.setCustomValidity('Додайте щонайменше два варіанти відповіді.');
        first?.reportValidity();
        window.setTimeout(() => first?.setCustomValidity(''), 0);
      }
    });
    toggleSurveyOptions();
  }

  // Participant 360 internal panels.
  const participantTabs = qs('[data-p360-tabs]');
  if (participantTabs) {
    qsa('[data-tab]', participantTabs).forEach(button => button.addEventListener('click', () => {
      qsa('[data-tab]', participantTabs).forEach(item => item.classList.toggle('active', item === button));
      qsa('.p360-panel').forEach(panel => panel.classList.toggle('active', panel.dataset.panel === button.dataset.tab));
    }));
  }

  // Reports period controls.
  const periodType = qs('#periodType');
  if (periodType) {
    const sync = () => qsa('.period-field').forEach(field => { field.style.display = field.dataset.period === periodType.value ? 'flex' : 'none'; });
    periodType.addEventListener('change', sync); sync();
  }

  // Giveaway detail and creation conditional fields.
  const giveawayEdit = qs('.giveaway-edit-form');
  if (giveawayEdit) {
    const mode = qs('#detailParticipationMode', giveawayEdit), audience = qs('#detailAudienceType', giveawayEdit);
    const sync = () => {
      const task = qs('.detail-task-block', giveawayEdit); if (task && mode) task.style.display = mode.value === 'task' ? 'block' : 'none';
      ['event','roles','users'].forEach(type => { const el=qs(`.detail-audience-${type}`,giveawayEdit); if(el&&audience)el.style.display=audience.value===type?'block':'none'; });
    };
    mode?.addEventListener('change', sync); audience?.addEventListener('change', sync); sync();
  }
  const giveawayCreate = qs('#giveawayCreateForm');
  if (giveawayCreate) {
    const mode=qs('#createParticipationMode',giveawayCreate), audience=qs('#createAudienceType',giveawayCreate);
    const sync=()=>{
      const task=qs('.giveaway-task-block',giveawayCreate); if(task&&mode)task.style.display=mode.value==='task'?'block':'none';
      qsa('[class*="giveaway-audience-"]',giveawayCreate).forEach(el=>{if(!el.classList.contains('giveaway-task-block'))el.style.display='none';});
      if(audience){const target=qs(`.giveaway-audience-${audience.value}`,giveawayCreate);if(target)target.style.display='block';}
    };
    mode?.addEventListener('change',sync); audience?.addEventListener('change',sync); sync();
    const search=qs('.giveaway-user-search',giveawayCreate);
    search?.addEventListener('input',()=>{const value=search.value.toLowerCase().trim();qsa('.giveaway-user-picker .survey-user-option',giveawayCreate).forEach(el=>{el.style.display=!value||(el.dataset.search||'').includes(value)?'flex':'none';});});
  }

  // Quest type/completion mode controls.
  function syncQuestForm(form) {
    const type=qs('[name="quest_type"]',form), mode=qs('[name="completion_mode"]',form); if(!type||!mode)return;
    const team=type.value==='team'; if(team)mode.value='manual';
    qsa('.quest-team-target',form).forEach(el=>{el.hidden=!team;});
    qsa('.quest-automatic-mode',form).forEach(el=>{el.hidden=team;});
    qsa('.quest-auto-field',form).forEach(el=>{el.hidden=team||mode.value!=='qr_on_time';});
    const event=qs('[name="event_id"]',form); if(event)event.required=!team&&mode.value==='qr_on_time';
  }
  qsa('form[action$="/create"],form[action$="/update"]').forEach(form=>{
    if(!qs('[name="quest_type"]',form))return;
    form.addEventListener('change',()=>syncQuestForm(form)); syncQuestForm(form);
  });

  // Quick XP forms and quiz draft rows.
  function setPanelControls(panel, enabled){qsa('input,textarea,select',panel).forEach(el=>{if(el.name!=='_csrf')el.disabled=!enabled;});}
  function syncQuickXpKind(form){const kind=qs('.quick-xp-kind-select',form)?.value;qsa('[data-kind-panel]',form).forEach(panel=>{const active=panel.dataset.kindPanel===kind;panel.hidden=!active;setPanelControls(panel,active);});}
  qsa('[data-kind-form]').forEach(form=>{const select=qs('.quick-xp-kind-select',form);syncQuickXpKind(form);select?.addEventListener('change',()=>syncQuickXpKind(form));});
  const renumberQuickXpDrafts=list=>qsa('[data-quiz-question]',list).forEach((row,index)=>{const n=qs('[data-question-number]',row);if(n)n.textContent=String(index+1);});
  qsa('[data-quiz-question-list]').forEach(list=>list.addEventListener('click',event=>{const button=event.target.closest('[data-remove-quiz-question]');if(!button)return;const rows=qsa('[data-quiz-question]',list);if(rows.length<=1){const input=qs('input,textarea',rows[0]);input?.setCustomValidity('Мініквіз має містити хоча б одне питання.');input?.reportValidity();window.setTimeout(()=>input?.setCustomValidity(''),0);return;}button.closest('[data-quiz-question]')?.remove();renumberQuickXpDrafts(list);}));
  qsa('[data-add-quiz-question]').forEach(button=>button.addEventListener('click',()=>{const panel=button.closest('[data-kind-panel="quiz"]');const list=panel&&qs('[data-quiz-question-list]',panel);const tpl=qs('#quickXpQuestionTemplate');if(!list||!tpl)return;list.appendChild(tpl.content.cloneNode(true));renumberQuickXpDrafts(list);}));

  // Broadcast audience, presets, character count and template selection.
  const broadcastAudience=qs('#audienceType');
  if(broadcastAudience){
    const extras=qsa('.broadcast-extra');
    const sync=()=>{extras.forEach(el=>{const active=el.dataset.audience===broadcastAudience.value;el.hidden=!active;qsa('select,input',el).forEach(input=>{if(['settlement_value','event_value'].includes(input.name))input.disabled=!active;});});};
    broadcastAudience.addEventListener('change',sync);sync();
    qsa('[data-age]').forEach(button=>button.addEventListener('click',()=>{const [min,max]=(button.dataset.age||',').split(',');const minInput=qs('input[name="age_min"]'),maxInput=qs('input[name="age_max"]');if(minInput)minInput.value=min||'';if(maxInput)maxInput.value=max||'';}));
    const textarea=qs('#broadcastText'),counter=qs('#broadcastCharCount'),templateCode=qs('#templateCode');
    const count=()=>{if(counter&&textarea)counter.textContent=`${textarea.value.length} / 3800`;};
    textarea?.addEventListener('input',count);count();
    qsa('.broadcast-template-button').forEach(button=>button.addEventListener('click',()=>{if(!textarea)return;let value=button.dataset.templateText||'""';try{value=JSON.parse(value);}catch(_err){}textarea.value=value;if(templateCode)templateCode.value=button.dataset.templateCode||'';qsa('.broadcast-template-button').forEach(item=>item.classList.remove('is-selected'));button.classList.add('is-selected');count();textarea.focus();}));
    const preview=qs('#broadcastPreview');if(preview)window.setTimeout(()=>preview.scrollIntoView({behavior:'smooth',block:'start'}),100);
  }

  // Badge type field and batch selection.
  const badgeTypeCreate=qs('#badgeTypeCreate'),badgePngCreate=qs('#badgePngCreate');
  if(badgeTypeCreate&&badgePngCreate){const sync=()=>{badgePngCreate.style.display=badgeTypeCreate.value==='ambassador'?'flex':'none';};badgeTypeCreate.addEventListener('change',sync);sync();}
  qsa('[data-badge-users]').forEach(button=>button.addEventListener('click',()=>{const checked=button.dataset.badgeUsers==='all';qsa('input[name="user_ids"]').forEach(input=>{input.checked=checked;});}));
})();
