/* AMP XP v1.20.3 — layout, motion and Help Center refinement. */
(function () {
  'use strict';
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Progressive reveal: subtle and disabled for reduced motion.
  if (!reduced && 'IntersectionObserver' in window) {
    const nodes = Array.from(document.querySelectorAll('.content > .page-head,.content > .page-header,.content > .hero,.content > .card,.content > .kpis,.content > .cards,.content > .work-cards-grid,.content > .event-cards-grid'));
    nodes.forEach((node, index) => {
      node.dataset.uiReveal = '1';
      node.style.transitionDelay = `${Math.min(index, 5) * 30}ms`;
    });
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, {threshold: 0.05, rootMargin: '0px 0px -3% 0px'});
    nodes.forEach(node => observer.observe(node));
  }

  // Help quick-start cards switch the real category instead of stuffing text into search.
  const helpRoot = document.querySelector('.help-center');
  if (helpRoot) {
    const search = helpRoot.querySelector('[data-help-search]');
    const categoryButtons = Array.from(helpRoot.querySelectorAll('[data-help-category-filter]'));
    const cards = Array.from(helpRoot.querySelectorAll('[data-help-card]'));
    const activateCategory = category => {
      const button = categoryButtons.find(item => item.dataset.helpCategoryFilter === category) || categoryButtons[0];
      if (!button) return;
      if (search) search.value = '';
      button.click();
      requestAnimationFrame(() => {
        const first = cards.find(card => !card.hidden && (category === 'all' || card.dataset.helpCategory === category || card.dataset.helpCategory === 'all'));
        if (first) first.scrollIntoView({behavior: reduced ? 'auto' : 'smooth', block: 'start'});
      });
    };
    helpRoot.querySelectorAll('[data-help-category-target]').forEach(button => {
      button.addEventListener('click', () => activateCategory(button.dataset.helpCategoryTarget || 'all'));
    });
  }

  // Size modal editors by their content instead of allowing oversized fly-outs.
  document.addEventListener('click', event => {
    const trigger = event.target.closest('.edit-launcher,[data-modal-open]');
    if (!trigger) return;
    const id = trigger.getAttribute('aria-controls') || trigger.dataset.modalOpen;
    const dialog = id ? document.getElementById(id) : null;
    if (!(dialog instanceof HTMLDialogElement)) return;
    const fields = dialog.querySelectorAll('input:not([type="hidden"]),select,textarea').length;
    dialog.classList.toggle('amp-modal-wide', fields >= 9);
  });

  // Prevent accidental word-by-word labels in dynamic buttons by exposing a useful tooltip.
  document.querySelectorAll('.amp-tab,.nav-item,.primary,.soft-button,.danger-btn').forEach(node => {
    if (!node.title && node.textContent) node.title = node.textContent.trim().replace(/\s+/g, ' ');
  });
})();
