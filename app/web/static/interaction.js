/* AMP XP v1.20.3.1 — tabs, account menu, combobox, avatar preview and motion feedback. */
(function () {
  'use strict';

  const reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function focusables(root) {
    return Array.from(root.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'))
      .filter(node => !node.hidden && node.getClientRects().length);
  }

  // Real application tabs: no anchor scrolling. URL query state is preserved.
  document.querySelectorAll('[data-tabs]').forEach(root => {
    const key = root.dataset.tabsKey || 'tab';
    const tabs = Array.from(root.querySelectorAll('[role="tab"][data-tab]'));
    const owner = root.closest('.account-cabinet,.help-center') || document;
    const panels = Array.from(owner.querySelectorAll('[role="tabpanel"][data-tab-panel]'));
    if (!tabs.length || !panels.length) return;

    const allowed = new Set(tabs.map(tab => tab.dataset.tab));
    const params = new URLSearchParams(location.search);
    const initial = allowed.has(params.get(key)) ? params.get(key) : (allowed.has(root.dataset.tabsDefault) ? root.dataset.tabsDefault : tabs[0].dataset.tab);

    function positionIndicator(tab) {
      const indicator = root.querySelector('.amp-tab-indicator');
      const list = root.querySelector('[role="tablist"]');
      if (!indicator || !list || !tab) return;
      const a = tab.getBoundingClientRect();
      const b = list.getBoundingClientRect();
      indicator.style.width = `${a.width}px`;
      indicator.style.transform = `translateX(${a.left - b.left + list.scrollLeft}px)`;
    }

    function activate(name, options = {}) {
      if (!allowed.has(name)) return;
      tabs.forEach(tab => {
        const active = tab.dataset.tab === name;
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
        tab.tabIndex = active ? 0 : -1;
        tab.classList.toggle('active', active);
        if (active) positionIndicator(tab);
      });
      panels.forEach(panel => {
        const active = panel.dataset.tabPanel === name;
        panel.hidden = !active;
        panel.classList.toggle('is-active', active);
        if (active && !reducedMotion) {
          panel.classList.remove('panel-enter');
          requestAnimationFrame(() => panel.classList.add('panel-enter'));
        }
      });
      if (options.url !== false) {
        const url = new URL(location.href);
        url.searchParams.set(key, name);
        history.replaceState({[key]: name}, '', url);
      }
      if (options.focus) tabs.find(tab => tab.dataset.tab === name)?.focus({preventScroll:true});
    }

    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => activate(tab.dataset.tab));
      tab.addEventListener('keydown', event => {
        let next = null;
        if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
        if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = tabs.length - 1;
        if (next === null) return;
        event.preventDefault();
        activate(tabs[next].dataset.tab, {focus:true});
      });
    });
    activate(initial, {url: params.has(key)});
    window.addEventListener('resize', () => positionIndicator(tabs.find(tab => tab.getAttribute('aria-selected') === 'true')));
  });

  // Compact top-right account menu.
  const accountButton = document.querySelector('[data-account-menu-button]');
  const accountMenu = document.querySelector('[data-account-menu]');
  if (accountButton && accountMenu) {
    const close = (restore = false) => {
      accountMenu.hidden = true;
      accountButton.setAttribute('aria-expanded','false');
      if (restore) accountButton.focus({preventScroll:true});
    };
    const open = () => {
      accountMenu.hidden = false;
      accountButton.setAttribute('aria-expanded','true');
      focusables(accountMenu)[0]?.focus({preventScroll:true});
    };
    accountButton.addEventListener('click', event => {
      event.stopPropagation();
      accountMenu.hidden ? open() : close();
    });
    document.addEventListener('click', event => {
      if (!accountMenu.hidden && !accountMenu.contains(event.target) && event.target !== accountButton) close();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !accountMenu.hidden) { event.preventDefault(); close(true); }
    });
  }

  // Accessible participant combobox used by superadmin profile linking.
  document.querySelectorAll('[data-participant-combobox]').forEach(box => {
    const input = box.querySelector('[data-combobox-input]');
    const hidden = box.querySelector('input[name="linked_user_id"]');
    const list = box.querySelector('[data-combobox-list]');
    const selected = box.querySelector('[data-combobox-selected]');
    if (!input || !hidden || !list) return;
    let timer = null;
    let current = -1;
    let items = [];

    const render = rows => {
      items = rows;
      current = -1;
      list.innerHTML = '';
      rows.forEach((row, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'combobox-option';
        button.setAttribute('role','option');
        button.dataset.index = String(index);
        button.innerHTML = `<strong>${escapeHtml(row.name)}</strong><span>${escapeHtml(row.amp_id)}${row.username ? ` · @${escapeHtml(row.username)}` : ''}</span>`;
        button.addEventListener('click', () => choose(row));
        list.append(button);
      });
      list.hidden = rows.length === 0;
      input.setAttribute('aria-expanded', rows.length ? 'true':'false');
    };
    const choose = row => {
      hidden.value = String(row.id);
      input.value = `${row.amp_id} · ${row.name}`;
      if (selected) selected.innerHTML = `<strong>${escapeHtml(row.name)}</strong><span>${escapeHtml(row.amp_id)}${row.username ? ` · @${escapeHtml(row.username)}` : ''}</span>`;
      list.hidden = true;
      input.setAttribute('aria-expanded','false');
    };
    const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const search = async () => {
      const q = input.value.trim();
      if (q.length < 2) { render([]); return; }
      try {
        const response = await fetch(`/admin/security/participant-search?q=${encodeURIComponent(q)}`, {headers:{'Accept':'application/json'}});
        if (!response.ok) throw new Error('search failed');
        const data = await response.json();
        render(Array.isArray(data.items) ? data.items : []);
      } catch (_err) { render([]); }
    };
    input.addEventListener('input', () => { hidden.value = ''; clearTimeout(timer); timer=setTimeout(search,180); });
    input.addEventListener('keydown', event => {
      const options = Array.from(list.querySelectorAll('[role="option"]'));
      if (!options.length) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); current=(current+1)%options.length; options[current].focus(); }
      else if (event.key === 'Escape') { list.hidden=true; input.setAttribute('aria-expanded','false'); }
    });
    box.addEventListener('focusout', () => setTimeout(() => { if (!box.contains(document.activeElement)) { list.hidden=true; input.setAttribute('aria-expanded','false'); } }, 80));
  });

  // Help Center category tabs. Search remains cross-category and temporarily overrides the category filter.
  const helpRoot = document.querySelector('.help-center');
  const helpInput = helpRoot?.querySelector('[data-help-search]');
  const helpCategoryButtons = Array.from(helpRoot?.querySelectorAll('[data-help-category-filter]') || []);
  if (helpRoot && helpCategoryButtons.length) {
    const setCategory = (name, focus = false) => {
      helpRoot.dataset.helpCategory = name;
      helpCategoryButtons.forEach(button => {
        const active = button.dataset.helpCategoryFilter === name;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', active ? 'true' : 'false');
        button.tabIndex = active ? 0 : -1;
        if (active && focus) button.focus({preventScroll:true});
      });
      if (helpInput && !helpInput.value.trim()) helpInput.dispatchEvent(new Event('input', {bubbles:true}));
    };
    helpCategoryButtons.forEach((button, index) => {
      button.addEventListener('click', () => { if (helpInput) helpInput.value=''; setCategory(button.dataset.helpCategoryFilter || 'all'); });
      button.addEventListener('keydown', event => {
        let next=null;
        if (event.key==='ArrowRight') next=(index+1)%helpCategoryButtons.length;
        if (event.key==='ArrowLeft') next=(index-1+helpCategoryButtons.length)%helpCategoryButtons.length;
        if (event.key==='Home') next=0;
        if (event.key==='End') next=helpCategoryButtons.length-1;
        if (next===null) return;
        event.preventDefault();
        if (helpInput) helpInput.value='';
        setCategory(helpCategoryButtons[next].dataset.helpCategoryFilter || 'all', true);
      });
    });
    setCategory('all');
  }

  // Avatar preview before upload.
  document.querySelectorAll('[data-avatar-input]').forEach(input => {
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      const preview = input.closest('dialog')?.querySelector('[data-avatar-preview]');
      if (!file || !preview || !file.type.startsWith('image/')) return;
      const url = URL.createObjectURL(file);
      preview.innerHTML = '';
      const img = document.createElement('img'); img.src=url; img.alt='Попередній перегляд нового аватара';
      img.addEventListener('load', () => URL.revokeObjectURL(url), {once:true});
      preview.append(img);
    });
  });

  // v1.20.3.1.1: transient server messages are handled centrally by polish.js.

})();
