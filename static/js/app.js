document.querySelectorAll('[data-submit-loading]').forEach((form) => {
  form.addEventListener('submit', () => {
    const button = form.querySelector('[type="submit"]');
    const panel = document.querySelector(form.dataset.loadingTarget || '#search-loading');
    if (button) {
      button.disabled = true;
      button.setAttribute('aria-disabled', 'true');
      const label = button.querySelector('[data-button-label]');
      if (label) label.textContent = button.dataset.loadingLabel || 'Procesando…';
    }
    if (panel) {
      panel.classList.add('is-visible');
      panel.removeAttribute('hidden');
      panel.setAttribute('aria-busy', 'true');
    }
  });
});

document.querySelectorAll('[data-local-date]').forEach((element) => {
  const value = element.getAttribute('datetime') || element.dataset.localDate;
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return;
  element.textContent = new Intl.DateTimeFormat('es-CL', {
    dateStyle: 'medium', timeStyle: 'short'
  }).format(date);
});
