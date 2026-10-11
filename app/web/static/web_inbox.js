/* Optional enhancement. The inbox itself works without JavaScript. */
(() => {
  'use strict';
  const badge = document.querySelector('[data-web-unread]');
  if (!badge) return;
  let inFlight = false;
  let lastFetched = 0;
  const refresh = async () => {
    if (inFlight || document.hidden || !navigator.onLine || Date.now() - lastFetched < 30000) return;
    inFlight = true;
    lastFetched = Date.now();
    try {
      const response = await fetch('/admin/web-inbox/count', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) return;
      const result = await response.json();
      const count = Math.max(0, Number(result.unread) || 0);
      badge.hidden = count === 0;
      badge.textContent = count > 99 ? '99+' : String(count);
      badge.parentElement?.setAttribute('aria-label', `Мої сповіщення, непрочитаних: ${count}`);
    } catch (_) { /* offline: accessible inbox link remains usable */ } finally { inFlight = false; }
  };
  refresh();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  window.addEventListener('focus', refresh);
})();
