/* АМПасадори: єдина перевірка форм без переходу на сторінку HTTP-помилки. */
(function () {
  'use strict';
  const isAdminForm = form => form instanceof HTMLFormElement && form.method.toLowerCase() === 'post' && new URL(form.action, location.href).pathname.startsWith('/admin/');
  const eventForm = form => /\/admin\/events\/(create|\d+\/update)$/.test(new URL(form.action, location.href).pathname);
  function messageArea(form) {
    let box = form.querySelector(':scope > .amp-form-errors');
    if (!box) {
      box = document.createElement('div');
      box.className = 'amp-form-errors';
      box.setAttribute('role', 'alert');
      box.setAttribute('aria-live', 'polite');
      form.prepend(box);
    }
    return box;
  }
  function showError(form, message, field) {
    const box = messageArea(form);
    box.textContent = message;
    box.hidden = false;
    if (field) {
      field.classList.add('amp-invalid-field');
      field.setAttribute('aria-invalid', 'true');
      field.focus({ preventScroll: true });
    }
    box.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  }
  function clearError(form) {
    const box = form.querySelector(':scope > .amp-form-errors');
    if (box) {box.textContent = '';box.hidden = true;}
    form.querySelectorAll('.amp-invalid-field').forEach(field => {
      field.classList.remove('amp-invalid-field');field.removeAttribute('aria-invalid');
    });
  }
  function readableField(field) {
    const label = field.closest('label');
    return label ? (label.textContent || '').trim().split('\n')[0].slice(0, 70) : 'Обов’язкове поле';
  }
  function readDate(form, prefix) {
    const names = prefix ? ['end_day', 'end_month', 'end_year', 'end_time'] : ['day', 'month', 'year', 'event_time'];
    const fields = names.map(name => form.elements.namedItem(name));
    if (fields.some(field => !field || !field.value)) return { fields, date: null, missing: true };
    const [day, month, year] = fields.map(field => Number(field.value));
    const match = /^([0-2]\d):([0-5]\d)$/.exec(fields[3].value);
    if (!match) return { fields, date: null };
    const hour = Number(match[1]), minute = Number(match[2]);
    if (hour > 23) return { fields, date: null };
    const date = new Date(year, month-1, day, hour, minute);
    if (date.getFullYear() !== year || date.getMonth() !== month-1 || date.getDate() !== day || date.getHours() !== hour || date.getMinutes() !== minute) return { fields, date: null };
    return { fields, date };
  }
  function checkEventDate(form, live) {
    if (!eventForm(form)) return true;
    const start = readDate(form, ''), end = readDate(form, 'end_');
    const target = form.elements.namedItem('end_time');
    if (target) target.setCustomValidity('');
    if ((start.missing || end.missing) && live) return true;
    if (!start.missing && !start.date) {if (!live) showError(form, 'Перевірте дату та час початку події.', start.fields[0]);return false;}
    if (!end.missing && !end.date) {if (!live) showError(form, 'Перевірте дату та час завершення події.', end.fields[0]);return false;}
    if (start.date && end.date && end.date <= start.date) {
      if (target) target.setCustomValidity('Час завершення має бути пізнішим за час початку.');
      if (!live) showError(form, 'Час завершення події має бути пізнішим за час початку.', target);
      return false;
    }
    return !!(start.date && end.date) || !!live;
  }
  function localCheck(form, live = false) {
    if (eventForm(form) && !checkEventDate(form, live)) return false;
    if (live) return true;
    const invalid = Array.from(form.elements).find(field => field.willValidate && !field.validity.valid);
    if (invalid) {
      showError(form, `Перевірте поле «${readableField(invalid)}»: ${invalid.validationMessage || 'некоректне значення'}.`, invalid);
      return false;
    }
    const oversized = Array.from(form.querySelectorAll('input[type="file"]')).find(el => Array.from(el.files || []).some(f => f.size > 20 * 1024 * 1024));
    if (oversized) {showError(form, 'Файл завеликий. Максимальний розмір — 20 МБ.', oversized);return false;}
    return true;
  }
  document.addEventListener('input', function (e) {
    const form = e.target.closest && e.target.closest('form');
    if (!form || !isAdminForm(form)) return;
    clearError(form);
    if (eventForm(form)) checkEventDate(form, true);
  }, true);
  document.addEventListener('change', function (e) {
    const form = e.target.closest && e.target.closest('form');
    if (!form || !isAdminForm(form)) return;
    clearError(form);
    if (eventForm(form)) checkEventDate(form, true);
  }, true);
  document.addEventListener('focusout', function(e) {
    const field = e.target;
    const form = field.form;
    if (!isAdminForm(form)) return;
    if (eventForm(form)) checkEventDate(form, true);
    if (field.willValidate && !field.validity.valid) {
      const detail = field.validity.customError ? field.validationMessage : `Перевірте поле «${readableField(field)}».`;
      showError(form, detail);
      field.classList.add('amp-invalid-field');
      field.setAttribute('aria-invalid', 'true');
    }
  }, true);
  document.addEventListener('invalid', function(e) {
    const form = e.target.form;
    if (isAdminForm(form)) {
      const custom = e.target.validity.customError ? e.target.validationMessage : '';
      showError(form, custom || `Перевірте поле «${readableField(e.target)}».`, e.target);
    }
  }, true);
  document.addEventListener('submit', async function(e) {
    const form = e.target;
    if (!isAdminForm(form) || e.defaultPrevented || form.dataset.ampSubmitting === '1') return;
    e.preventDefault();
    clearError(form);
    if (!localCheck(form)) return;
    const submitter = e.submitter || null;
    const data = new FormData(form);
    if (submitter && submitter.name) data.append(submitter.name, submitter.value);
    const buttons = Array.from(form.querySelectorAll('[type="submit"], button:not([type])'));
    form.dataset.ampSubmitting = '1';
    const enabledButtons = buttons.filter(button => !button.disabled);
    form.dataset.liveDirty = '1';
    enabledButtons.forEach(button => button.disabled = true);
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: data, credentials: 'same-origin',
        headers: {'X-AMP-Form': '1', 'Accept': 'application/json, text/html;q=0.9'},
        redirect: 'follow',
      });
      if (response.redirected) {
        const url = new URL(response.url);
        if (url.origin !== location.origin) throw new Error('Неочікувана адреса відповіді сервера.');
        location.assign(url.href);
        return;
      }
      if (response.ok) {
        const disposition = response.headers.get('content-disposition') || '';
        if (/attachment/i.test(disposition)) {
          const rawName = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(disposition);
          const fallbackName = /filename\s*=\s*"?([^";]+)"?/i.exec(disposition);
          const name = rawName ? decodeURIComponent(rawName[1]) : (fallbackName ? fallbackName[1] : 'звіт');
          const objectUrl = URL.createObjectURL(await response.blob());
          const link = document.createElement('a');
          link.href = objectUrl; link.download = name;
          document.body.appendChild(link); link.click(); link.remove();
          setTimeout(() => URL.revokeObjectURL(objectUrl), 5000);
          return;
        }
        location.reload();return;
      }
      let detail = '';
      let errorField = null;
      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        const body = await response.json();
        if (typeof body.detail === 'string') detail = body.detail;
        else if (Array.isArray(body.detail)) {
          detail = body.detail.map(item => item.msg || 'Некоректне значення').join('; ');
          const location = body.detail[0] && body.detail[0].loc;
          if (Array.isArray(location)) errorField = form.elements.namedItem(location[location.length - 1]);
        }
      }
      if (!detail && response.status === 403) detail = 'Доступ заборонено або термін дії форми минув. Оновіть сторінку.';
      if (!detail && response.status === 409) detail = 'Конфлікт даних. Перевірте інформацію та повторіть дію.';
      if (!detail && response.status >= 500) detail = 'Помилка сервера. Перевірте, чи зміни вже збереглися, перш ніж повторити дію.';
      showError(form, detail || 'Не вдалося зберегти дані. Перевірте введену інформацію.', errorField);
    } catch (err) {
      showError(form, 'Немає відповіді сервера. Перевірте з’єднання та чи не збереглися зміни, перш ніж повторити дію.');
    } finally {
      delete form.dataset.ampSubmitting;
      enabledButtons.forEach(button => button.disabled = false);
    }
  });
})();
