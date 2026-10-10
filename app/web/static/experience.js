/* AMP XP v1.20.3.1 — progressive visual experience, dialogs and Help Center. */
(function () {
  'use strict';

  const openDialogs = new Map();

  function dialogById(id) {
    const node = id ? document.getElementById(id) : null;
    return node instanceof HTMLDialogElement ? node : null;
  }

  function openDialog(dialog, trigger) {
    if (!dialog) return;
    openDialogs.set(dialog, trigger || document.activeElement);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    requestAnimationFrame(() => {
      const target = dialog.querySelector('[autofocus], input:not([type="hidden"]), select, textarea, button:not([data-modal-close])');
      if (target instanceof HTMLElement) target.focus({preventScroll: true});
    });
  }

  function closeDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === 'function' && dialog.open) dialog.close();
    else dialog.removeAttribute('open');
  }

  document.addEventListener('click', event => {
    const opener = event.target.closest('[data-modal-open]');
    if (opener) {
      const dialog = dialogById(opener.getAttribute('data-modal-open'));
      if (dialog) {
        event.preventDefault();
        openDialog(dialog, opener);
      }
      return;
    }
    const closer = event.target.closest('[data-modal-close]');
    if (closer) {
      const dialog = closer.closest('dialog');
      if (dialog) {
        event.preventDefault();
        closeDialog(dialog);
      }
    }
  });

  document.querySelectorAll('dialog.amp-modal').forEach(dialog => {
    dialog.addEventListener('click', event => {
      if (event.target === dialog) {
        const rect = dialog.getBoundingClientRect();
        const inside = event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
        if (!inside) closeDialog(dialog);
      }
    });
    dialog.addEventListener('close', () => {
      const trigger = openDialogs.get(dialog);
      openDialogs.delete(dialog);
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus({preventScroll: true});
    });
  });

  // Accessible reusable destructive confirmation. Replaces inline onsubmit=confirm handlers.
  const confirmDialog = dialogById('ampConfirmDialog');
  const confirmText = confirmDialog?.querySelector('[data-confirm-text]');
  const confirmSubmit = confirmDialog?.querySelector('[data-confirm-submit]');
  let pendingForm = null;

  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    const message = event.submitter?.dataset?.confirmMessage || form.dataset.confirmMessage;
    if (!message || form.dataset.confirmed === '1' || !confirmDialog) return;
    event.preventDefault();
    pendingForm = form;
    if (confirmText) confirmText.textContent = message;
    openDialog(confirmDialog, form.querySelector('button[type="submit"],button:not([type])') || document.activeElement);
  }, true);

  confirmSubmit?.addEventListener('click', () => {
    if (!pendingForm) return;
    const form = pendingForm;
    pendingForm = null;
    form.dataset.confirmed = '1';
    closeDialog(confirmDialog);
    requestAnimationFrame(() => form.requestSubmit());
  });
  confirmDialog?.addEventListener('close', () => { pendingForm = null; });

  // Help Center live search. All content stays server-rendered and readable without JS.
  const helpInput = document.querySelector('[data-help-search]');
  const helpCards = Array.from(document.querySelectorAll('[data-help-card]'));
  const helpEmpty = document.querySelector('[data-help-empty]');
  const helpRoot = helpInput?.closest('.help-center');
  if (helpInput && helpCards.length) {
    const normalize = value => String(value || '').toLocaleLowerCase('uk-UA').normalize('NFKD');
    const filter = () => {
      const query = normalize(helpInput.value).trim();
      const category = helpRoot?.dataset.helpCategory || 'all';
      let visible = 0;
      helpCards.forEach(card => {
        const haystack = normalize(`${card.dataset.helpKeywords || ''} ${card.textContent || ''}`);
        const categoryMatch = category === 'all' || card.dataset.helpCategory === category || card.dataset.helpCategory === 'all';
        const show = query ? haystack.includes(query) : categoryMatch;
        card.hidden = !show;
        if (show) visible += 1;
      });
      if (helpEmpty) helpEmpty.hidden = visible !== 0;
    };
    helpInput.addEventListener('input', filter);
    document.querySelectorAll('[data-help-query]').forEach(button => button.addEventListener('click', () => {
      helpInput.value = button.dataset.helpQuery || '';
      filter();
      helpInput.focus();
    }));
  }

  // Profile/theme preference controls use the same local preference as the app shell.
  document.querySelectorAll('[data-profile-theme]').forEach(button => button.addEventListener('click', () => {
    const theme = button.dataset.profileTheme;
    if (!['light','dark','system'].includes(theme)) return;
    const resolved = theme === 'system'
      ? (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : theme;
    document.body.dataset.theme = resolved;
    try {
      if (theme === 'system') localStorage.removeItem('amp-theme');
      else localStorage.setItem('amp-theme', theme);
    } catch (_err) {}
    document.querySelectorAll('[data-profile-theme]').forEach(item => item.classList.toggle('active', item.dataset.profileTheme === theme));
  }));

  // Small feedback enhancement: lock submit buttons during a real submit to avoid accidental doubles.
  document.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.dataset.confirmMessage && form.dataset.confirmed !== '1') return;
    const button = event.submitter;
    if (!(button instanceof HTMLButtonElement)) return;
    if (button.dataset.noLoading === '1') return;
    button.dataset.originalText = button.textContent || '';
    button.classList.add('is-loading');
    button.setAttribute('aria-busy', 'true');
    window.setTimeout(() => { button.disabled = true; }, 0);
  });

  // Progressive upgrade: existing edit <details> become accessible modal dialogs.
  // Without JS the original details remain usable; with JS forms move intact into dialogs.
  (function modalizeEditDetails(){
    const editors = Array.from(document.querySelectorAll('details')).filter(details => details.querySelector(':scope > summary.edit-action-button'));
    editors.forEach((details, index) => {
      if (details.dataset.noModal === '1') return;
      const summary = details.querySelector(':scope > summary');
      if (!summary) return;
      const rawLabel = (summary.textContent || 'Редагувати').trim();
      const label = rawLabel.replace(/^✏️\s*/,'').replace(/^＋\s*/,'').trim() || 'Редагувати';
      const trigger = document.createElement('button');
      trigger.type = 'button';
      trigger.className = summary.className || 'soft-button edit-action-button';
      trigger.classList.add('edit-launcher');
      trigger.textContent = label;
      trigger.setAttribute('aria-haspopup','dialog');

      const dialog = document.createElement('dialog');
      dialog.className = 'amp-modal amp-editor-modal';
      dialog.id = `ampEditDialog${index + 1}`;
      trigger.setAttribute('aria-controls', dialog.id);
      const shell = document.createElement('div'); shell.className = 'amp-modal-shell';
      const header = document.createElement('div'); header.className = 'amp-modal-header';
      const titleWrap = document.createElement('div');
      titleWrap.innerHTML = `<span class="eyebrow">РЕДАГУВАННЯ</span><h2>${label.replace(/[<>&]/g, ch => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[ch]))}</h2><p>Зміни застосуються після збереження форми.</p>`;
      const close = document.createElement('button'); close.type='button'; close.className='amp-modal-close'; close.dataset.modalClose='1'; close.setAttribute('aria-label','Закрити'); close.innerHTML='<span class="icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></span>';
      header.append(titleWrap, close);
      const body = document.createElement('div'); body.className='amp-modal-body';
      Array.from(details.childNodes).forEach(node => { if (node !== summary) body.appendChild(node); });
      shell.append(header, body); dialog.append(shell);
      details.replaceWith(trigger, dialog);

      trigger.addEventListener('click', () => openDialog(dialog, trigger));
      close.addEventListener('click', () => closeDialog(dialog));
      dialog.addEventListener('click', event => {
        if (event.target !== dialog) return;
        const rect=dialog.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeDialog(dialog);
      });
      dialog.addEventListener('close', () => {
        const returnTo = openDialogs.get(dialog); openDialogs.delete(dialog);
        if (returnTo instanceof HTMLElement && returnTo.isConnected) returnTo.focus({preventScroll:true});
      });
    });
  })();
})();
