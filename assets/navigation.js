(() => {
  'use strict';
  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  const url = new URL(window.location.href);
  // Filtering is an enhancement: every row and download remains in the static HTML.
  document.querySelectorAll('[data-filter-table]').forEach(table => {
    const kind = table.dataset.filterTable;
    const rows = Array.from(table.querySelectorAll('tr')).filter(row => row.querySelector('td'));
    if (!rows.length) return;
    const original = rows.slice();
    let page = 0;
    const pageSize = kind === 'counties' ? 25 : Infinity;
    const tools = document.createElement('div');
    tools.className = 'filter-tools';
    const id = `filter-${kind}`;
    tools.innerHTML = `<div class="filter-controls"><div class="field"><label for="${id}">Search ${kind}</label><input type="search" id="${id}" autocomplete="off" placeholder="${kind === 'counties' ? 'County or county equivalent' : kind === 'states' ? 'State name or abbreviation' : 'File name'}"></div><button type="button" class="filter-clear">Clear</button></div><p class="filter-count" aria-live="polite" aria-atomic="true"></p>`;
    table.before(tools);
    const input = tools.querySelector('input');
    const count = tools.querySelector('.filter-count');
    const empty = document.createElement('p');
    empty.className = 'filter-empty';
    empty.textContent = `No matching ${kind}. Try a different name or clear your search.`;
    empty.hidden = true;
    table.after(empty);
    let pager;
    if (Number.isFinite(pageSize)) {
      pager = document.createElement('div');
      pager.className = 'filter-pager';
      pager.innerHTML = '<button type="button">Previous</button><span aria-live="polite"></span><button type="button">Next</button><button type="button" class="show-all">Show all</button>';
      empty.after(pager);
    }
    let showAll = false;
    function render() {
      const query = normalize(input.value);
      const abbreviation = kind === 'states' && /^[a-z]{2}$/.test(query) && original.some(row => normalize(row.dataset.abbreviation || '') === query);
      const matches = original.filter(row => abbreviation ? normalize(row.dataset.abbreviation || '') === query : normalize(row.dataset.search || row.cells[0].textContent).includes(query));
      const size = showAll ? Infinity : pageSize;
      const pages = Number.isFinite(size) ? Math.max(1, Math.ceil(matches.length / size)) : 1;
      page = Math.min(page, pages - 1);
      const visible = new Set(matches.slice(page * (Number.isFinite(size) ? size : 0), Number.isFinite(size) ? (page + 1) * size : undefined));
      original.forEach(row => { row.hidden = !visible.has(row); });
      const start = matches.length ? page * (Number.isFinite(size) ? size : 0) + 1 : 0;
      count.textContent = `${matches.length ? `${start}–${start + visible.size - 1} of ` : ''}${matches.length} ${kind}${query ? ` matching “${input.value.trim()}”` : ''}`;
      empty.hidden = matches.length > 0;
      if (pager) {
        const buttons = pager.querySelectorAll('button');
        buttons[0].disabled = page === 0;
        buttons[1].disabled = page >= pages - 1;
        buttons[2].textContent = showAll ? 'Show 25 at a time' : `Show all ${matches.length}`;
        pager.querySelector('span').textContent = `Page ${page + 1} of ${pages}`;
        pager.hidden = matches.length <= pageSize;
      }
    }
    input.addEventListener('input', () => { page = 0; render(); });
    tools.querySelector('.filter-clear').addEventListener('click', () => { input.value = ''; page = 0; render(); input.focus(); });
    if (pager) {
      const buttons = pager.querySelectorAll('button');
      buttons[0].addEventListener('click', () => { page--; render(); tools.scrollIntoView({block:'start'}); });
      buttons[1].addEventListener('click', () => { page++; render(); tools.scrollIntoView({block:'start'}); });
      buttons[2].addEventListener('click', () => { showAll = !showAll; page = 0; render(); });
    }
    if (kind === 'states') input.value = url.searchParams.get('q') || '';
    render();
  });
  // Keep wide records inside their own accessible horizontal scrolling region.
  document.querySelectorAll('main table').forEach(table => {
    const region = document.createElement('div');
    region.className = 'table-scroll';
    region.tabIndex = 0;
    region.setAttribute('role', 'region');
    region.setAttribute('aria-label', 'Data table. Scroll horizontally for more columns.');
    table.before(region);
    region.append(table);
  });
  const radios = Array.from(document.querySelectorAll('.yr-in'));
  function applyYear(year, updateURL) {
    const radio = radios.find(item => item.id === `yr${year}` || item.id === `fyr${year}`);
    if (!radio) return;
    if (!radio.checked) {
      radio.checked = true;
      radio.dispatchEvent(new Event('change', {bubbles:true}));
    }
    if (updateURL) {
      const next = new URL(window.location.href);
      next.searchParams.set('year', year);
      history.replaceState(null, '', next);
    }
    // Only carry the selected year to places that have a matching year control.
    document.querySelectorAll('a[href]').forEach(link => {
      const target = new URL(link.getAttribute('href'), window.location.href);
      if (target.origin !== location.origin || !/\/(?:states\/[^/]+|counties\/[^/]+\/[^/]+)\/index\.html$/.test(target.pathname)) return;
      target.searchParams.set('year', year);
      link.href = target.pathname + target.search + target.hash;
    });
  }
  radios.forEach(radio => radio.addEventListener('change', () => {
    if (radio.checked) applyYear(radio.id.replace(/^f?yr/, ''), true);
  }));
  applyYear(url.searchParams.get('year') || '2026', false);
  window.addEventListener('popstate', () => applyYear(new URL(location.href).searchParams.get('year') || '2026', false));
})();
