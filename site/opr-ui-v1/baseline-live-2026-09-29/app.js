(function () {
  const form = document.getElementById('search');
  const status = document.getElementById('status');
  const results = document.getElementById('results');
  const countsEl = document.getElementById('counts');

  const KIND_LABEL = {
    baptism: 'Baptism',
    marriage: 'Marriage',
    death: 'Death',
    deaths: 'Death',
    communion: 'Communion',
    histnotes: 'Historical notes'
  };

  function setStatus(text, tone) {
    status.textContent = text;
    if (tone) status.dataset.tone = tone;
    else delete status.dataset.tone;
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatCounts(c) {
    if (!c) return '';
    const parts = [];
    if (c.baptisms != null) parts.push(c.baptisms + ' baptisms');
    if (c.marriages != null) parts.push(c.marriages + ' marriages');
    if (c.deaths != null) parts.push(c.deaths + ' deaths');
    if (c.communion != null) parts.push(c.communion + ' communion');
    if (c.histnotes != null) parts.push(c.histnotes + ' historical notes');
    return parts.join(' · ');
  }

  function cite(hit) {
    const bits = [];
    if (hit.archival_id) bits.push(hit.archival_id);
    if (hit.scan != null && hit.scan !== '') bits.push('scan ' + hit.scan);
    if (hit.page != null && hit.page !== '') bits.push('page ' + hit.page);
    if (hit.entry != null && hit.entry !== '') bits.push('entry ' + hit.entry);
    return bits.join(' · ');
  }

  function renderHits(data) {
    const hits = (data && data.hits) || [];
    const n = data && typeof data.count === 'number' ? data.count : hits.length;
    if (!hits.length) {
      results.innerHTML = '<p class="empty">No matching entries.</p>';
      setStatus(n === 0 ? '0 results' : 'No hits returned', 'warn');
      return;
    }
    setStatus(n + (n === 1 ? ' result' : ' results'), 'ok');
    results.innerHTML = hits.map(function (hit) {
      const kind = hit.kind || '';
      const label = KIND_LABEL[kind] || kind || 'Record';
      const when = hit.date_text ? esc(hit.date_text) : 'Date unknown';
      const where = hit.place_text ? ' · ' + esc(hit.place_text) : '';
      const names = hit.names ? esc(hit.names) : '—';
      const snip = hit.snippet ? esc(hit.snippet) : '';
      const citation = esc(cite(hit));
      return (
        '<article class="card">' +
          '<div class="card-top">' +
            '<span class="kind" data-kind="' + esc(kind) + '">' + esc(label) + '</span>' +
            '<span class="meta">' + when + where + '</span>' +
          '</div>' +
          '<h2 class="names">' + names + '</h2>' +
          (snip ? '<p class="snippet">' + snip + '</p>' : '') +
          (citation ? '<p class="cite">' + citation + '</p>' : '') +
        '</article>'
      );
    }).join('');
  }

  async function loadHealth() {
    try {
      const r = await fetch('/health');
      const j = await r.json();
      const line = formatCounts(j.counts);
      countsEl.textContent = line
        ? ('Staging · ' + line + ' · read-only')
        : 'Staging collection · read-only';
      setStatus(j.ok ? 'Ready to search' : 'Service reported a problem', j.ok ? 'ok' : 'warn');
    } catch (e) {
      countsEl.textContent = 'Staging collection · read-only';
      setStatus('Could not reach /health', 'warn');
    }
  }

  async function runSearch(fd) {
    const params = new URLSearchParams();
    for (const [k, v] of fd.entries()) {
      if (String(v).trim() !== '') params.set(k, String(v).trim());
    }
    setStatus('Searching…');
    results.innerHTML = '';
    try {
      const r = await fetch('/search?' + params.toString());
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      renderHits(j);
    } catch (e) {
      setStatus('Search failed', 'warn');
      results.innerHTML = '<pre class="raw">Search request failed. Try again, or open /search directly.</pre>';
    }
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    runSearch(new FormData(form));
  });

  form.addEventListener('reset', function () {
    setTimeout(function () {
      results.innerHTML = '';
      setStatus('Ready to search', 'ok');
    }, 0);
  });

  // Hydrate from URL if someone shared /?# or landed with query params on /
  (function hydrateFromLocation() {
    const sp = new URLSearchParams(location.search);
    let any = false;
    ['q', 'name', 'place', 'date', 'kind'].forEach(function (k) {
      if (sp.has(k) && form.elements[k]) {
        form.elements[k].value = sp.get(k);
        any = true;
      }
    });
    loadHealth().then(function () {
      if (any) runSearch(new FormData(form));
    });
  })();
})();
