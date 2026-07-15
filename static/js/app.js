const autocompleteCache = new Map();

function initCardAutocomplete(root) {
  const input = root.querySelector('[data-autocomplete-input]');
  const menu = root.querySelector('[data-autocomplete-menu]');
  const status = root.querySelector('[data-autocomplete-status]');
  if (!input || !menu) return;

  let suggestions = [];
  let activeIndex = -1;
  let debounceTimer;
  let controller;

  const closeMenu = () => {
    suggestions = [];
    activeIndex = -1;
    menu.replaceChildren();
    menu.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  };

  const setActive = (index) => {
    const options = [...menu.querySelectorAll('[role="option"]')];
    if (!options.length) return;
    activeIndex = (index + options.length) % options.length;
    options.forEach((option, optionIndex) => {
      const active = optionIndex === activeIndex;
      option.setAttribute('aria-selected', String(active));
      option.classList.toggle('is-active', active);
    });
    input.setAttribute('aria-activedescendant', options[activeIndex].id);
    options[activeIndex].scrollIntoView({block: 'nearest'});
  };

  const selectSuggestion = (name) => {
    input.value = name;
    closeMenu();
    input.dispatchEvent(new CustomEvent('card-autocomplete:select', {
      bubbles: true, detail: {name}
    }));
  };

  const renderSuggestions = (names) => {
    suggestions = names;
    activeIndex = -1;
    menu.replaceChildren();
    names.forEach((name, index) => {
      const option = document.createElement('button');
      option.type = 'button';
      option.id = `${menu.id}-option-${index}`;
      option.className = 'autocomplete-option';
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', 'false');
      option.textContent = name;
      option.addEventListener('mousedown', event => event.preventDefault());
      option.addEventListener('click', () => selectSuggestion(name));
      menu.append(option);
    });
    menu.hidden = names.length === 0;
    input.setAttribute('aria-expanded', String(names.length > 0));
    if (status) status.textContent = names.length ? `${names.length} sugerencias disponibles.` : 'No hay sugerencias.';
  };

  const loadSuggestions = async () => {
    const query = input.value.trim();
    if (query.length < 2) {
      closeMenu();
      return;
    }
    const cacheKey = query.toLocaleLowerCase('en-US');
    if (autocompleteCache.has(cacheKey)) {
      renderSuggestions(autocompleteCache.get(cacheKey));
      return;
    }
    controller?.abort();
    controller = new AbortController();
    if (status) status.textContent = 'Buscando sugerencias…';
    try {
      const params = new URLSearchParams({q: query});
      const response = await fetch(`https://api.scryfall.com/cards/autocomplete?${params}`, {
        headers: {Accept: 'application/json'}, signal: controller.signal
      });
      if (!response.ok) throw new Error(`Scryfall ${response.status}`);
      const payload = await response.json();
      const names = Array.isArray(payload.data) ? payload.data : [];
      autocompleteCache.set(cacheKey, names);
      renderSuggestions(names);
    } catch (error) {
      if (error.name === 'AbortError') return;
      closeMenu();
      if (status) status.textContent = 'No fue posible cargar sugerencias. Puedes usar el nombre escrito.';
    }
  };

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    controller?.abort();
    if (input.value.trim().length < 2) {
      closeMenu();
      return;
    }
    debounceTimer = setTimeout(loadSuggestions, 250);
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown' && suggestions.length) {
      event.preventDefault(); setActive(activeIndex + 1);
    } else if (event.key === 'ArrowUp' && suggestions.length) {
      event.preventDefault(); setActive(activeIndex - 1);
    } else if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault(); selectSuggestion(suggestions[activeIndex]);
    } else if (event.key === 'Escape') {
      closeMenu();
    }
  });
  input.addEventListener('blur', () => setTimeout(closeMenu, 150));
}

function parseBulkCards(text) {
  const cards = [];
  const seen = new Set();
  text.split(/\r?\n/).forEach(rawLine => {
    const line = rawLine.trim();
    const lower = line.toLocaleLowerCase('en-US');
    if (!line || ['sideboard', 'sb:', '//', 'deck', 'maybeboard'].some(prefix => lower.startsWith(prefix))) return;
    const match = line.match(/^(?:(?:\d+)[xX]?\s+)?([^([\n*#]+)/);
    if (!match) return;
    const name = match[1].replace(/\s+\([A-Z0-9]+\).*$/, '').trim();
    const key = name.toLocaleLowerCase('en-US');
    if (name && !seen.has(key)) {
      seen.add(key);
      cards.push(name);
    }
  });
  return cards;
}

function initCardBuilder(builder) {
  const input = builder.querySelector('[data-autocomplete-input]');
  const hiddenInput = builder.querySelector('[data-card-list-value]');
  const list = builder.querySelector('[data-selected-cards]');
  const error = builder.querySelector('[data-card-builder-error]');
  const maxCards = Number(builder.dataset.maxCards || 100);
  let cards = [];

  const setError = message => { if (error) error.textContent = message; };
  const sync = () => { hiddenInput.value = cards.join('\n'); };
  const render = () => {
    list.replaceChildren();
    if (!cards.length) {
      const empty = document.createElement('p');
      empty.className = 'selected-cards__empty';
      empty.textContent = 'Todavía no agregas cartas.';
      list.append(empty);
    } else {
      cards.forEach((name, index) => {
        const chip = document.createElement('span');
        chip.className = 'selected-card';
        const label = document.createElement('span');
        label.textContent = name;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'selected-card__remove';
        remove.setAttribute('aria-label', `Quitar ${name}`);
        remove.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
        remove.addEventListener('click', () => {
          cards.splice(index, 1); sync(); render(); setError('');
        });
        chip.append(label, remove);
        list.append(chip);
      });
    }
    sync();
  };

  const addCard = rawName => {
    const name = String(rawName || '').replace(/\s+/g, ' ').trim();
    if (!name) {
      setError('Escribe el nombre de una carta.');
      input.focus();
      return false;
    }
    if (cards.some(card => card.toLocaleLowerCase('en-US') === name.toLocaleLowerCase('en-US'))) {
      setError(`${name} ya está en la lista.`);
      return false;
    }
    if (cards.length >= maxCards) {
      setError(`Puedes agregar como máximo ${maxCards} cartas distintas.`);
      return false;
    }
    cards.push(name);
    input.value = '';
    setError('');
    render();
    input.focus();
    return true;
  };

  try {
    const initial = JSON.parse(builder.dataset.initialCards || '[]');
    if (Array.isArray(initial)) initial.forEach(name => {
      if (cards.length < maxCards && !cards.some(card => card.toLocaleLowerCase('en-US') === String(name).toLocaleLowerCase('en-US'))) cards.push(String(name));
    });
  } catch (_) {}
  render();

  builder.querySelector('[data-add-card]')?.addEventListener('click', () => addCard(input.value));
  input.addEventListener('card-autocomplete:select', event => addCard(event.detail.name));
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.defaultPrevented) {
      event.preventDefault(); addCard(input.value);
    }
  });
  builder.querySelector('[data-import-cards]')?.addEventListener('click', () => {
    const textarea = builder.querySelector('[data-bulk-card-list]');
    const imported = parseBulkCards(textarea.value);
    let added = 0;
    imported.forEach(name => { if (addCard(name)) added += 1; });
    if (added) textarea.value = '';
    if (!imported.length) setError('No se reconocieron cartas en la lista pegada.');
  });
  builder.closest('form')?.addEventListener('submit', event => {
    sync();
    if (!cards.length) {
      event.preventDefault();
      setError('Agrega al menos una carta antes de buscar.');
      input.focus();
    }
  }, {capture: true});
}

document.querySelectorAll('[data-card-autocomplete]').forEach(initCardAutocomplete);
document.querySelectorAll('[data-card-builder]').forEach(initCardBuilder);

document.querySelectorAll('[data-submit-loading]').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (event.defaultPrevented) return;
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
