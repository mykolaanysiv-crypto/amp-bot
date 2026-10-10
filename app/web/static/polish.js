/* AMP XP v1.20.3.1.1 — compact toast and dialog safety layer. */
(() => {
  'use strict';

  const region = document.querySelector('[data-toast-region]');
  const iconPath = {
    success: '<path d="m5 12 4 4 10-10"/>',
    error: '<path d="M6 6l12 12M18 6 6 18"/>',
    warning: '<path d="m12 3 9 17H3z"/><path d="M12 9v5M12 17h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>'
  };

  function buildIcon(type) {
    const wrap = document.createElement('span');
    wrap.className = 'amp-toast-icon';
    wrap.setAttribute('aria-hidden', 'true');
    wrap.innerHTML = `<svg viewBox="0 0 24 24">${iconPath[type] || iconPath.info}</svg>`;
    return wrap;
  }

  function removeToast(toast) {
    if (!toast || toast.dataset.closing === 'true') return;
    toast.dataset.closing = 'true';
    toast.classList.remove('show');
    window.setTimeout(() => toast.remove(), 190);
  }

  function showToast(message, type = 'info', timeout = 4200) {
    if (!region || !message) return null;
    const toast = document.createElement('div');
    toast.className = `amp-toast ${type}`;
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');

    const copy = document.createElement('div');
    copy.className = 'amp-toast-copy';
    copy.textContent = String(message).trim();

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'amp-toast-close';
    close.setAttribute('aria-label', 'Закрити повідомлення');
    close.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
    close.addEventListener('click', () => removeToast(toast));

    toast.append(buildIcon(type), copy, close);
    region.append(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    if (timeout > 0) window.setTimeout(() => removeToast(toast), timeout);
    return toast;
  }

  window.AMPToast = { show: showToast };

  // Only explicitly transient server messages become toasts; persistent warnings stay in-page.
  document.querySelectorAll('.alert[data-toast-source]').forEach(alert => {
    const type = alert.classList.contains('danger') ? 'error' :
      alert.classList.contains('warning') ? 'warning' :
      alert.classList.contains('success') ? 'success' : 'info';
    const text = (alert.textContent || '').replace(/\s+/g, ' ').trim();
    if (!text) return;
    showToast(text, type);
    alert.dataset.toastConsumed = 'true';
  });

  // Do not allow generated editor dialogs with no usable content to appear as blank modals.
  document.addEventListener('click', event => {
    const trigger = event.target.closest('[data-modal-open]');
    if (!trigger) return;
    const id = trigger.getAttribute('data-modal-open');
    const dialog = id ? document.getElementById(id) : null;
    if (!(dialog instanceof HTMLDialogElement) || !dialog.classList.contains('amp-editor-modal')) return;
    const body = dialog.querySelector('.amp-modal-body');
    const usable = body && (body.querySelector('form,input,select,textarea,button,a') || (body.textContent || '').trim());
    if (!usable) {
      event.preventDefault();
      event.stopImmediatePropagation();
      showToast('Для цього блоку немає даних для редагування.', 'info');
    }
  }, true);
})();
