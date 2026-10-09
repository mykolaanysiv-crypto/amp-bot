/* AMP XP v1.20.0 — accessible app shell and progressive UI helpers. */
(function () {
  'use strict';

  const body = document.body;
  const sidebar = document.getElementById('adminSidebar');
  const mobileMenu = document.querySelector('[data-mobile-menu]');
  const backdrop = document.querySelector('[data-sidebar-backdrop]');
  const collapseButtons = Array.from(document.querySelectorAll('[data-sidebar-collapse]'));
  const themeButtons = Array.from(document.querySelectorAll('[data-theme-toggle]'));
  const SIDEBAR_KEY = 'amp-sidebar-collapsed';
  const THEME_KEY = 'amp-theme';
  let mobileReturnFocus = null;

  function safeGet(key) { try { return localStorage.getItem(key); } catch (_err) { return null; } }
  function safeSet(key, value) { try { localStorage.setItem(key, value); } catch (_err) {} }

  function setTheme(theme) {
    const resolved = theme === 'dark' ? 'dark' : 'light';
    body.dataset.theme = resolved;
    safeSet(THEME_KEY, resolved);
    themeButtons.forEach(button => {
      button.setAttribute('aria-label', resolved === 'dark' ? 'Увімкнути світлу тему' : 'Увімкнути темну тему');
      button.setAttribute('title', resolved === 'dark' ? 'Світла тема' : 'Темна тема');
    });
  }
  function toggleTheme() { setTheme(body.dataset.theme === 'dark' ? 'light' : 'dark'); }
  window.toggleTheme = toggleTheme; // compatibility for old extensions; UI uses event listeners.

  function setCollapsed(collapsed, persist = true) {
    body.classList.toggle('sidebar-collapsed', collapsed);
    collapseButtons.forEach(button => {
      button.setAttribute('aria-expanded', String(!collapsed));
      button.setAttribute('aria-label', collapsed ? 'Розгорнути бокове меню' : 'Згорнути бокове меню');
      button.setAttribute('title', collapsed ? 'Розгорнути меню' : 'Згорнути меню');
    });
    if (persist) safeSet(SIDEBAR_KEY, collapsed ? '1' : '0');
  }

  function focusableInSidebar() {
    if (!sidebar) return [];
    return Array.from(sidebar.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'))
      .filter(element => !element.hidden && element.offsetParent !== null);
  }

  function openSidebar(trigger) {
    if (!sidebar) return;
    mobileReturnFocus = trigger || document.activeElement;
    sidebar.classList.add('is-open');
    body.classList.add('nav-open');
    mobileMenu?.setAttribute('aria-expanded', 'true');
    sidebar.setAttribute('aria-modal', 'true');
    const items = focusableInSidebar();
    if (items[0]) items[0].focus({preventScroll: true});
  }

  function closeSidebar({restoreFocus = true} = {}) {
    if (!sidebar) return;
    const wasOpen = sidebar.classList.contains('is-open');
    sidebar.classList.remove('is-open');
    body.classList.remove('nav-open');
    mobileMenu?.setAttribute('aria-expanded', 'false');
    sidebar.removeAttribute('aria-modal');
    if (restoreFocus && wasOpen && mobileReturnFocus instanceof HTMLElement) mobileReturnFocus.focus({preventScroll: true});
  }

  function trapSidebarFocus(event) {
    if (event.key !== 'Tab' || !sidebar?.classList.contains('is-open') || window.innerWidth > 1023) return;
    const items = focusableInSidebar();
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  const storedTheme = safeGet(THEME_KEY);
  if (storedTheme) setTheme(storedTheme);
  else setTheme(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  setCollapsed(safeGet(SIDEBAR_KEY) === '1', false);

  themeButtons.forEach(button => button.addEventListener('click', toggleTheme));
  collapseButtons.forEach(button => button.addEventListener('click', () => setCollapsed(!body.classList.contains('sidebar-collapsed'))));
  mobileMenu?.addEventListener('click', () => sidebar?.classList.contains('is-open') ? closeSidebar() : openSidebar(mobileMenu));
  backdrop?.addEventListener('click', () => closeSidebar());

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && sidebar?.classList.contains('is-open')) { event.preventDefault(); closeSidebar(); return; }
    trapSidebarFocus(event);
  });
  document.querySelectorAll('#adminSidebar nav a').forEach(link => link.addEventListener('click', () => { if (window.innerWidth <= 1023) closeSidebar({restoreFocus:false}); }));
  window.addEventListener('resize', () => { if (window.innerWidth > 1023) closeSidebar({restoreFocus:false}); });

  (function enhanceFileInputs(){
    document.querySelectorAll('input[type="file"]:not([data-file-enhanced])').forEach(function(input){
      input.dataset.fileEnhanced='1';
      const shell=document.createElement('div'); shell.className='file-upload-shell';
      const button=document.createElement('span'); button.className='file-upload-button'; button.textContent='Обрати файл';
      const name=document.createElement('span'); name.className='file-upload-name'; name.textContent='Файл не вибрано';
      input.parentNode.insertBefore(shell,input); shell.append(button,name,input); input.classList.add('file-upload-native');
      input.addEventListener('change',function(){name.textContent=input.files && input.files.length ? input.files[0].name : 'Файл не вибрано';name.title=name.textContent;});
    });
  })();

  (function smartFilters(){
    document.querySelectorAll('form.smart-filters, form.filters').forEach(function(form){
      if((form.method||'get').toLowerCase()!=='get') return;
      const key='amp-filter:'+location.pathname; const params=new URLSearchParams(location.search);
      if(!params.toString()){
        try{const saved=JSON.parse(sessionStorage.getItem(key)||'{}');let changed=false;Object.entries(saved).forEach(([name,value])=>{const field=form.elements.namedItem(name);if(field && value!=='' && value!=null){field.value=value;changed=true;}});if(changed && form.dataset.autorestore!=='0') form.requestSubmit();}catch(_err){}
      }
      form.addEventListener('submit',function(){const data={};new FormData(form).forEach((value,keyName)=>{if(keyName!=='_csrf') data[keyName]=String(value);});try{sessionStorage.setItem(key,JSON.stringify(data));}catch(_err){}});
      let reset=form.querySelector('[data-filter-reset]');
      if(!reset){reset=document.createElement('a');reset.href=location.pathname;reset.className='soft-button filter-reset';reset.dataset.filterReset='1';reset.textContent='Скинути';form.appendChild(reset);}
      reset.addEventListener('click',function(){try{sessionStorage.removeItem(key);}catch(_err){}});
    });
  })();

  document.addEventListener('keydown', function(event){
    if(event.key==='/' && !event.metaKey && !event.ctrlKey && !/input|textarea|select/i.test(document.activeElement.tagName)){
      const field=document.querySelector('.global-search-top input'); if(field){event.preventDefault();field.focus();}
    }
  });

  (function installCsrfProtection(){
    const token=(window.AMP_UI && window.AMP_UI.csrfToken) || '';
    function ensure(form){if(!form || String(form.method||'get').toLowerCase()!=='post') return;let input=form.querySelector('input[name="_csrf"]');if(!input){input=document.createElement('input');input.type='hidden';input.name='_csrf';form.appendChild(input);}input.value=token;}
    document.querySelectorAll('form').forEach(ensure); document.addEventListener('submit',event=>ensure(event.target),true);
  })();

  (function responsiveTables(){
    document.querySelectorAll('table').forEach(table => {
      if (table.closest('.table-wrap,.amp-table-scroll')) return;
      const wrapper=document.createElement('div'); wrapper.className='amp-table-scroll'; wrapper.setAttribute('role','region'); wrapper.setAttribute('aria-label','Таблиця з горизонтальним прокручуванням'); wrapper.tabIndex=0;
      table.parentNode.insertBefore(wrapper,table); wrapper.appendChild(table);
    });
  })();

  (function ampLiveRegions(){
    const POLL_MS=5000; let inFlight=false;
    document.addEventListener('input',event=>{const form=event.target?.closest?.('form');if(form) form.dataset.liveDirty='1';},true);
    document.addEventListener('change',event=>{const form=event.target?.closest?.('form');if(form) form.dataset.liveDirty='1';},true);
    document.addEventListener('submit',event=>{const form=event.target;if(form?.dataset) delete form.dataset.liveDirty;},true);
    async function sync(){
      if(inFlight || document.hidden) return; const regions=[...document.querySelectorAll('[data-live-region][id]')]; if(!regions.length) return; inFlight=true;
      try{const response=await fetch(location.href,{credentials:'same-origin',headers:{'X-AMP-Live':'1','Cache-Control':'no-cache'}});if(!response.ok) return;const html=await response.text();const next=new DOMParser().parseFromString(html,'text/html');let changed=0;for(const current of regions){const active=document.activeElement;if(active&&current.contains(active)) continue;if(current.querySelector('form[data-live-dirty="1"]')) continue;const fresh=next.getElementById(current.id);if(!fresh||!fresh.hasAttribute('data-live-region')) continue;if(current.innerHTML!==fresh.innerHTML){current.innerHTML=fresh.innerHTML;changed++;}}if(changed) document.dispatchEvent(new CustomEvent('amp:live-updated',{detail:{count:changed}}));}
      catch(_err){} finally{inFlight=false;}
    }
    window.setInterval(sync,POLL_MS);
  })();
})();
