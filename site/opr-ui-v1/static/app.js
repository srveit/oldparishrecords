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
    results.innerHTML = hits.map(function (hit, i) { return renderCard(hit, i, {}); }).join('');
  }


  // ---- Record cards + "Cite this record" (fields defined in cite-fields.js) ----
  const CF = window.CITE_FIELDS || null;
  const SITE_KEYS = CF ? CF.order.filter(function (k) { return CF.sites[k]; }) : [];
  const SITE_ALIASES = { ancestry: 'ancestry', 'ancestry.com': 'ancestry', familysearch: 'familysearch', fs: 'familysearch' };
  const hitStore = [];   // index -> hit, so the cite panel can re-render on switch

  function recordKey(hit) {
    const parts = [hit.kind || '', hit.archival_id || '', hit.scan == null ? '' : hit.scan, hit.entry == null ? '' : hit.entry];
    if (hit.date_text) parts.push(hit.date_text);  // lookup hint for /search?date=
    return parts.join(':');
  }
  function recordHref(hit, site) {
    return '/?record=' + encodeURIComponent(recordKey(hit)) + (site ? '&site=' + encodeURIComponent(site) : '');
  }

  function fieldRows(hit, siteKey, uid) {
    const site = CF.sites[siteKey];
    const k = CF.kinds[hit.kind] || CF.kinds._default;
    let out = '<p class="cite-intro">' + esc(site.intro) + '</p>';
    let adv = '';
    site.groups.forEach(function (g, gi) {
      let h = '';
      h += '<section class="cite-group"><h3>' + esc(g.title) + '</h3><div class="cite-fields">';
      g.fields.forEach(function (f, fi) {
        let res = null;
        try { res = f.fill ? f.fill(hit, k) : null; } catch (e) { res = null; }
        let value = null, note = '';
        if (res && typeof res === 'object') { value = res.value; note = res.note || ''; }
        else value = res;
        if (value != null && String(value).trim() === '') value = null;
        const vid = uid + '-' + siteKey + '-' + gi + '-' + fi;
        const label = esc(f.label);
        h += '<div class="cite-row' + (value == null ? ' is-na' : '') + '">' +
          '<div class="cite-label">' + label + (f.required ? ' <span class="req">Required</span>' : '') + '</div>' +
          '<div class="cite-value">' +
            (value == null
              ? '<span class="na">Not available' + (f.why ? ' — ' + esc(f.why) : '') + '</span>'
              : '<span class="val" id="' + vid + '">' + esc(value) + '</span>') +
            (note ? '<span class="cite-note">' + esc(note) + '</span>' : '') +
            (f.hint ? '<span class="cite-hint">' + esc(site.label) + ' expects: ' + esc(f.hint) + '</span>' : '') +
          '</div>' +
          '<div class="cite-copy">' +
            (value == null ? '' :
              '<button type="button" class="copy" data-copy="' + vid + '" aria-label="Copy ' + label + ' (' + esc(g.title) + ', ' + esc(site.label) + ')">Copy</button>') +
          '</div>' +
        '</div>';
      });
      h += '</div>' + (g.after ? '<p class="cite-after">' + esc(g.after) + '</p>' : '') + '</section>';
      if (g.advanced) adv += h; else out += h;
    });
    if (adv) {
      out += '<details class="cite-adv"><summary>' + esc(site.advancedLabel || 'Advanced details') + '</summary>' +
        (site.advancedIntro ? '<p class="cite-intro">' + esc(site.advancedIntro) + '</p>' : '') + adv + '</details>';
    }
    return out;
  }

  function citeSection(hit, idx, site, open) {
    if (!CF || !SITE_KEYS.length) return '';
    const uid = 'rec' + idx;
    const tabs = SITE_KEYS.map(function (key) {
      const on = key === site;
      return '<button type="button" role="tab" class="cite-tab" id="' + uid + '-tab-' + key + '"' +
        ' aria-selected="' + on + '" aria-controls="' + uid + '-panel" tabindex="' + (on ? '0' : '-1') + '"' +
        ' data-site="' + key + '" data-idx="' + idx + '">' + esc(CF.sites[key].label) + '</button>';
    }).join('');
    return '<details class="cite-box"' + (open ? ' open' : '') + '>' +
      '<summary>Cite this record</summary>' +
      '<div class="cite-body">' +
        '<div class="cite-switch" role="tablist" aria-label="Citation fields for">' + tabs + '</div>' +
        '<div class="cite-panel" role="tabpanel" id="' + uid + '-panel" aria-labelledby="' + uid + '-tab-' + site + '" data-idx="' + idx + '">' +
          fieldRows(hit, site, uid) +
        '</div>' +
      '</div>' +
    '</details>';
  }

  function renderCard(hit, idx, opts) {
    hitStore[idx] = hit;
    const kind = hit.kind || '';
    const label = KIND_LABEL[kind] || kind || 'Record';
    const when = hit.date_text ? esc(hit.date_text) : 'Date unknown';
    const where = hit.place_text ? ' · ' + esc(hit.place_text) : '';
    const names = hit.names ? esc(hit.names) : '—';
    const snip = hit.snippet ? esc(hit.snippet) : '';
    const citation = esc(cite(hit));
    const site = opts.site || SITE_KEYS[0];
    return (
      '<article class="card' + (opts.single ? ' card-single' : '') + '">' +
        '<div class="card-top">' +
          '<span class="kind" data-kind="' + esc(kind) + '">' + esc(label) + '</span>' +
          '<span class="meta">' + when + where + '</span>' +
        '</div>' +
        '<h2 class="names">' + names + '</h2>' +
        (snip ? '<p class="snippet">' + snip + '</p>' : '') +
        (citation ? '<p class="cite">' + citation +
          (opts.single ? '' : ' · <a class="permalink" href="' + esc(recordHref(hit)) + '">Link to this record</a>') +
        '</p>' : '') +
        citeSection(hit, idx, site, !!opts.open) +
      '</article>'
    );
  }

  function selectSite(idx, site, focus) {
    const hit = hitStore[idx];
    if (!hit || !CF.sites[site]) return;
    const uid = 'rec' + idx;
    SITE_KEYS.forEach(function (key) {
      const b = document.getElementById(uid + '-tab-' + key);
      if (!b) return;
      const on = key === site;
      b.setAttribute('aria-selected', String(on));
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    const panel = document.getElementById(uid + '-panel');
    panel.setAttribute('aria-labelledby', uid + '-tab-' + site);
    panel.innerHTML = fieldRows(hit, site, uid);
    if (singleMode) {
      const sp = new URLSearchParams(location.search);
      sp.set('site', site);
      history.replaceState(null, '', '/?' + sp.toString().replace(/\+/g, '%20'));
    }
  }

  const liveMsg = document.createElement('p');
  liveMsg.className = 'visually-hidden';
  liveMsg.setAttribute('aria-live', 'polite');
  document.body.appendChild(liveMsg);

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).catch(function () { return legacyCopy(text); });
    }
    return legacyCopy(text);
  }
  function legacyCopy(text) {
    return new Promise(function (resolve, reject) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed'; ta.style.top = '-1000px'; ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      document.body.removeChild(ta);
      ok ? resolve() : reject(new Error('copy failed'));
    });
  }

  document.addEventListener('click', function (e) {
    const tab = e.target.closest('.cite-tab');
    if (tab) { selectSite(Number(tab.dataset.idx), tab.dataset.site, false); return; }
    const btn = e.target.closest('button.copy');
    if (btn) {
      const el = document.getElementById(btn.dataset.copy);
      if (!el) return;
      const name = btn.getAttribute('aria-label').replace(/^Copy /, '');
      copyText(el.textContent).then(function () {
        btn.textContent = 'Copied'; btn.classList.add('done');
        liveMsg.textContent = 'Copied ' + name;
      }, function () {
        btn.textContent = 'Select & copy'; 
        liveMsg.textContent = 'Could not copy automatically. Select the text and copy it.';
        const range = document.createRange(); range.selectNodeContents(el);
        const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
      });
      clearTimeout(btn._t);
      btn._t = setTimeout(function () { btn.textContent = 'Copy'; btn.classList.remove('done'); }, 1600);
    }
  });

  document.addEventListener('keydown', function (e) {
    const tab = e.target.closest && e.target.closest('.cite-tab');
    if (!tab) return;
    const i = SITE_KEYS.indexOf(tab.dataset.site);
    let n = -1;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') n = (i + 1) % SITE_KEYS.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') n = (i - 1 + SITE_KEYS.length) % SITE_KEYS.length;
    else if (e.key === 'Home') n = 0;
    else if (e.key === 'End') n = SITE_KEYS.length - 1;
    if (n < 0) return;
    e.preventDefault();
    selectSite(Number(tab.dataset.idx), SITE_KEYS[n], true);
  });

  // ---- Single-record view: /?record=<kind>:<archival_id>:<scan>:<entry>[:<date_text>][&site=familysearch]
  let singleMode = false;

  function parseRecordKey(v) {
    const p = String(v || '').split(':');
    if (p.length < 4 || !p[0] || !p[1]) return null;
    return { kind: p[0], archival_id: p[1], scan: p[2], entry: p[3], date: p.slice(4).join(':') };
  }
  function sameRecord(h, k) {
    return String(h.kind) === k.kind && String(h.archival_id) === k.archival_id &&
      String(h.scan == null ? '' : h.scan) === k.scan && String(h.entry == null ? '' : h.entry) === k.entry;
  }
  async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }
  async function findRecord(k) {
    // 1) Optional exact endpoint, if Site Host adds it (see CITE-DEPLOY.md).
    try {
      const j = await fetchJSON('/record?' + new URLSearchParams({ kind: k.kind, archival_id: k.archival_id, scan: k.scan, entry: k.entry }).toString());
      const h = j && (j.hit || (j.hits && j.hits[0]));
      if (h && sameRecord(h, k)) return h;
    } catch (e) { /* endpoint not present yet */ }
    // 2) Existing /search: narrow by kind + date prefix, then match exactly.
    const tries = [];
    if (k.date) tries.push({ kind: k.kind, date: k.date, limit: '200' });
    if (k.date && k.date.length > 4) tries.push({ kind: k.kind, date: k.date.slice(0, 4), limit: '200' });
    tries.push({ kind: k.kind, limit: '200' });
    for (const q of tries) {
      try {
        const j = await fetchJSON('/search?' + new URLSearchParams(q).toString());
        const h = ((j && j.hits) || []).find(function (x) { return sameRecord(x, k); });
        if (h) return h;
      } catch (e) { /* try next */ }
    }
    return null;
  }

  async function showSingle(rawKey, siteParam) {
    singleMode = true;
    document.body.classList.add('single-record');
    const k = parseRecordKey(rawKey);
    const site = SITE_ALIASES[String(siteParam || '').toLowerCase()] || SITE_KEYS[0];
    const back = '<p class="backlink"><a href="/">← Back to search</a></p>';
    if (!k) {
      setStatus('That record link is not valid', 'warn');
      results.innerHTML = back + '<p class="empty">The record link could not be read.</p>';
      return;
    }
    setStatus('Loading record…');
    const hit = await findRecord(k);
    if (!hit) {
      setStatus('Record not found', 'warn');
      results.innerHTML = back + '<p class="empty">No entry matched ' + esc(k.archival_id) + ', scan ' + esc(k.scan) + ', entry ' + esc(k.entry) + '.</p>';
      return;
    }
    setStatus('Single record', 'ok');
    document.title = (hit.names ? hit.names + ' · ' : '') + (KIND_LABEL[hit.kind] || 'Record') + ' · Old Parish Records';
    results.innerHTML = back + renderCard(hit, 0, { single: true, open: true, site: site });
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
    if (singleMode) {
      singleMode = false;
      document.body.classList.remove('single-record');
      document.title = 'Old Parish Records';
      history.replaceState(null, '', '/');
    }
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
    const rec = sp.get('record');
    loadHealth().then(function () {
      if (rec) showSingle(rec, sp.get('site'));
      else if (any) runSearch(new FormData(form));
    });
  })();
})();
