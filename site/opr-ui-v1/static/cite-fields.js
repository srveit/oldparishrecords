/*
 * Old Parish Records — "Cite this record" field definitions.
 * THIS IS THE ONLY FILE TO EDIT for which fields Ancestry.com and FamilySearch
 * show, their labels, order, REQUIRED flags, and which record property fills
 * each one. app.js only renders what is defined here.
 *
 * How to edit
 *  - CITE_FIELDS.sites.<ancestry|familysearch>.groups is an ordered list of
 *    groups; each group has an ordered list of fields.
 *  - Field keys:
 *      label     text shown (and used in the copy button's accessible label)
 *      required  true shows the REQUIRED flag
 *      hint      what the site expects in this box (from the field templates)
 *      fill(r,k) returns the value built from record r (a /search hit), or
 *                null when we do not have the data. Return
 *                { value: "...", note: "..." } to add a short note shown
 *                under the value (never copied). A null result is shown as
 *                "Not available" automatically. NEVER make values up here.
 *      why       optional text shown after "Not available" (e.g. "your choice")
 *  - Group keys: title, fields, optional after (note shown below the group),
 *    optional advanced: true (shown in a collapsed section labelled by the
 *    site's advancedLabel / advancedIntro, collapsed by default).
 *  - k = the per-kind wording in CITE_FIELDS.kinds (ev = record type phrase,
 *    evShort = short event word, de = German register name default).
 *  - Record properties the API returns today: kind, archival_id, scan, page,
 *    entry, date_text, place_text, names, snippet.
 *    Optional properties that light up automatically once /search returns them
 *    (see CITE-DEPLOY.md): parish_name, parish_place, diocese_archive,
 *    register_type, book_date_from, book_date_to, book_url, matricula_url,
 *    primary_name, transcription, translation_en.
 *  - Keep this valid JavaScript:  node --check cite-fields.js
 */
var CITE_FIELDS = (function () {
  function has(v) { return v != null && String(v).trim() !== ''; }
  function s(v) { return String(v).trim(); }

  // "<Place> <Parish>" e.g. "Lank (Lank-Latum) St. Stephanus"; null if unknown.
  function parish(r) {
    var bits = [r.parish_place, r.parish_name].filter(has).map(s);
    return bits.length ? bits.join(' ') : null;
  }
  function years(r) {
    var a = has(r.book_date_from) ? s(r.book_date_from).slice(0, 4) : '';
    var b = has(r.book_date_to) ? s(r.book_date_to).slice(0, 4) : '';
    return a && b ? (a === b ? a : a + '–' + b) : (a || b || null);
  }
  function register(r, k) { return has(r.register_type) ? s(r.register_type) : (k.de || null); }
  function imagePageEntry(r) {
    var bits = [];
    if (has(r.scan)) bits.push('image ' + s(r.scan));
    if (has(r.page)) bits.push('p. ' + s(r.page));
    if (has(r.entry)) bits.push('no. ' + s(r.entry));
    return bits.length ? bits.join(', ') : null;
  }
  function missing(list) {
    return list.length ? 'Not available yet: ' + list.join(', ') + '.' : '';
  }
  // Diplomatic transcription + English text.
  function transcriptionText(r) {
    var out = [], miss = [], note = '';
    if (has(r.transcription)) out.push('Transcription (diplomatic): ' + s(r.transcription));
    else miss.push('diplomatic transcription');
    if (has(r.translation_en)) out.push('English: ' + s(r.translation_en));
    else if (has(r.snippet)) { out.push('English: ' + s(r.snippet)); note = 'English text is the search summary. '; }
    else miss.push('English translation');
    if (!out.length) return null;
    return { value: out.join('\n'), note: (note + missing(miss)).trim() };
  }
  function pageLink(r) {
    if (has(r.matricula_url)) return s(r.matricula_url);
    if (has(r.book_url)) return { value: s(r.book_url), note: 'Link to the register book; exact-page link not available yet.' };
    return null;
  }
  // "<Parish>, Kirchenbuch <register>, <years>"; null without the parish.
  function sourceTitle(r, k) {
    var p = parish(r), reg = register(r, k), y = years(r);
    if (!p) return null;   // a title without the parish would mislead
    var v = p + (reg ? ', Kirchenbuch ' + reg : '') + (y ? ', ' + y : '');
    var m = []; if (!reg) m.push('register name'); if (!y) m.push('book years');
    return { value: v, note: missing(m) };
  }
  function personName(r) {
    if (has(r.primary_name)) return { name: s(r.primary_name), note: '' };
    if (has(r.names)) return { name: s(r.names), note: 'Names lists everyone in the entry; shorten it to the person you are citing.' };
    return null;
  }

  return {
    // Per-kind wording (from the field templates). de = default German
    // register name when the record has no register_type yet.
    kinds: {
      baptism:   { ev: 'baptism', evShort: 'baptism', de: 'Taufen' },
      marriage:  { ev: 'marriage', evShort: 'marriage', de: 'Trauungen' },
      death:     { ev: 'death and burial', evShort: 'death and burial', de: 'Sterbefälle / Beerdigungen' },
      deaths:    { ev: 'death and burial', evShort: 'death and burial', de: 'Sterbefälle / Beerdigungen' },
      communion: { ev: 'first communion', evShort: 'first communion', de: null },
      histnotes: { ev: 'record', evShort: 'record', de: null },
      _default:  { ev: 'record', evShort: 'record', de: null }
    },

    order: ['ancestry', 'familysearch'],   // switch order; first = default side

    sites: {
      ancestry: {
        label: 'Ancestry.com',
        intro: 'Ancestry.com, checked against the live forms on 29 Sep 2026. Adding a source to a fact opens a quick dialog with two tabs, “Create a new source” and “Select existing source”. “Save and add advanced details” (or editing later) opens the full citation, source and repository forms.',
        // Groups with advanced: true are shown together in one collapsed section.
        advancedLabel: 'More Ancestry fields: full citation, source and repository',
        advancedIntro: 'Shown after “Save and add advanced details”, or when you edit the citation later.',
        groups: [
          { title: 'Quick add-source dialog', fields: [
            { label: 'Source title',
              hint: '<Parish>, Kirchenbuch <register>, <years>. Optional on this form.',
              fill: function (r, k) { return sourceTitle(r, k); } },
            { label: 'Citation details', required: true,
              hint: 'Book signature, image, page and entry number (e.g. KB013-01-S, image S_0036, p. 36, no. 59). The Save buttons stay disabled until this is filled.',
              fill: function (r) {
                // Quick dialog has no Date field, so date and name are appended here.
                var bits = [], m = [], head = [];
                if (has(r.archival_id)) head.push(s(r.archival_id)); else m.push('call number');
                var ipe = imagePageEntry(r); if (ipe) head.push(ipe);
                if (head.length) bits.push(head.join(', '));
                if (has(r.date_text)) bits.push(s(r.date_text));
                var n = personName(r); if (n) bits.push(n.name);
                if (!bits.length) return null;
                return { value: bits.join('; '), note: ((n ? n.note : '') + ' ' + missing(m)).trim() };
              } },
            { label: 'Citation web address',
              hint: 'Matricula link to the exact page',
              fill: function (r) { return has(r.matricula_url) ? s(r.matricula_url) : null; } }
          ]},
          { title: 'Citation (full form)', advanced: true,
            after: 'Media is a separate tab on the citation (“Add media to source”), not a field. Use it for a crop of the entry.',
            fields: [
            { label: 'Details', required: true,
              hint: 'Book signature, image, page and entry number',
              fill: function (r) {
                var head = [];
                if (has(r.archival_id)) head.push(s(r.archival_id));
                var ipe = imagePageEntry(r); if (ipe) head.push(ipe);
                if (!head.length) return null;
                return has(r.archival_id) ? head.join(', ') : { value: head.join(', '), note: missing(['call number']) };
              } },
            { label: 'Web address',
              hint: 'Matricula link to the exact page',
              fill: function (r) { return has(r.matricula_url) ? s(r.matricula_url) : null; } },
            { label: 'Transcription of text',
              hint: 'Our diplomatic transcription of the entry',
              fill: function (r) { return has(r.transcription) ? s(r.transcription) : null; } },
            { label: 'Other information',
              hint: 'English translation; why this entry is this person; uncertain readings',
              fill: function (r) {
                if (has(r.translation_en)) return s(r.translation_en);
                if (has(r.snippet)) return { value: s(r.snippet), note: 'This is the search summary, not the full English translation.' };
                return null;
              } },
            { label: 'Date',
              hint: 'Date of the <event> as written in the record',
              fill: function (r) { return has(r.date_text) ? s(r.date_text) : null; } },
            { label: 'Source title',
              hint: 'Links the citation to its source (choose the source below)',
              fill: function (r, k) { return sourceTitle(r, k); } }
          ]},
          { title: 'Source', advanced: true, fields: [
            { label: 'Source title', required: true,
              hint: '<Parish>, Kirchenbuch <register>, <years> (e.g. Warstein St. Pankratius, Kirchenbuch Sterbefälle)',
              fill: function (r, k) { return sourceTitle(r, k); } },
            { label: 'Author',
              hint: 'Katholische Kirche <Parish> (Catholic Church)',
              fill: function (r) { var p = parish(r); return p ? 'Katholische Kirche ' + p : null; } },
            { label: 'Publisher',
              hint: 'Matricula Online (ICARUS)',
              fill: function () { return 'Matricula Online (ICARUS)'; } },
            { label: 'Publisher location',
              hint: 'Vienna, Austria (Matricula) or the archive city',
              fill: function () { return 'Vienna, Austria'; } },
            { label: 'Call number',
              hint: 'Archive book signature (e.g. KB013-01-S)',
              fill: function (r) { return has(r.archival_id) ? s(r.archival_id) : null; } },
            { label: 'Publication date',
              hint: 'Leave blank, or the date the scans were put online',
              fill: function () { return null; }, why: 'leave blank' },
            { label: 'REFN',
              hint: 'Optional reference number, e.g. our book code',
              fill: function () { return null; } },
            { label: 'Note',
              hint: 'Record type: <event>. Diocese and archive holding the book.',
              fill: function (r, k) {
                var v = 'Record type: ' + k.ev + '.';
                if (has(r.diocese_archive)) return v + ' Archive: ' + s(r.diocese_archive) + '.';
                return { value: v, note: missing(['diocese / archive']) };
              } },
            { label: 'Repository name',
              hint: 'Choose or type the archive (see below)',
              fill: function (r) { return has(r.diocese_archive) ? s(r.diocese_archive) : null; } }
          ]},
          { title: 'Repository', advanced: true, fields: [
            { label: 'Name', required: true,
              hint: 'Archive holding the book (e.g. Erzbistumsarchiv Paderborn)',
              fill: function (r) { return has(r.diocese_archive) ? s(r.diocese_archive) : null; } },
            { label: 'Address', hint: 'Archive street address',
              fill: function (r) { return has(r.archive_address) ? s(r.archive_address) : null; } },
            { label: 'Phone number', hint: 'Archive phone',
              fill: function (r) { return has(r.archive_phone) ? s(r.archive_phone) : null; } },
            { label: 'Email', hint: 'Archive email',
              fill: function (r) { return has(r.archive_email) ? s(r.archive_email) : null; } },
            { label: 'Call number', hint: 'Optional; the archive’s own shelf mark',
              fill: function () { return null; } },
            { label: 'REFN', hint: 'Optional reference number',
              fill: function () { return null; } },
            { label: 'Note', hint: 'Matricula archive code (e.g. DE_EBAP)',
              fill: function (r) { return has(r.archive_code) ? s(r.archive_code) : null; } }
          ]}
        ]
      },

      familysearch: {
        label: 'FamilySearch',
        intro: 'Fields on FamilySearch when you create a source (Add Source / Source Box) and attach it to a person.',
        groups: [
          { title: 'Source', fields: [
            { label: 'Web Page',
              hint: 'Matricula link to the exact page',
              fill: function (r) { return pageLink(r); } },
            { label: 'Date',
              hint: 'Date of the <event> as written in the record',
              fill: function (r) { return has(r.date_text) ? s(r.date_text) : null; } },
            { label: 'Source Title', required: true,
              hint: '<Name>, <event> <date>, <Parish>',
              fill: function (r, k) {
                var n = personName(r);
                if (!n) return null;
                var p = parish(r);
                var v = n.name + ', ' + k.evShort + (has(r.date_text) ? ' ' + s(r.date_text) : '') + (p ? ', ' + p : '');
                var m = []; if (!has(r.date_text)) m.push('date'); if (!p) m.push('parish');
                return { value: v, note: (n.note + ' ' + missing(m)).trim() };
              } },
            { label: 'Citation',
              hint: 'Katholische Kirche <Parish>, Kirchenbuch <register>, <call number>, image <n>, p. <page>, no. <entry>; Matricula Online, <archive>',
              fill: function (r, k) {
                var p = parish(r), reg = register(r, k), ipe = imagePageEntry(r), parts = [], m = [];
                if (p) parts.push('Katholische Kirche ' + p); else m.push('parish');
                if (reg) parts.push('Kirchenbuch ' + reg); else m.push('register name');
                if (has(r.archival_id)) parts.push(s(r.archival_id)); else m.push('call number');
                if (ipe) parts.push(ipe);
                if (!parts.length) return null;
                var v = parts.join(', ') + '; Matricula Online' + (has(r.diocese_archive) ? ', ' + s(r.diocese_archive) : '');
                if (!has(r.diocese_archive)) m.push('archive');
                return { value: v, note: missing(m) };
              } },
            { label: 'Notes',
              hint: 'Our transcription of the entry (diplomatic and English)',
              fill: function (r) { return transcriptionText(r); } }
          ]},
          { title: 'Attaching to a person', fields: [
            { label: 'Reason This Source Is Attached',
              hint: 'Why this entry is this person (names, place, dates that match)',
              fill: function (r) {
                var bits = [];
                if (has(r.names)) bits.push('Names in entry: ' + s(r.names));
                if (has(r.place_text)) bits.push('Place: ' + s(r.place_text));
                if (has(r.date_text)) bits.push('Date: ' + s(r.date_text));
                return bits.length ? { value: bits.join('; ') + '.', note: 'Facts from the record. Add why they match your person.' } : null;
              } },
            { label: 'Tag (which facts it supports)',
              hint: 'Name, sex, and the <event> event (plus relationships for related persons)',
              fill: function (r, k) { return 'Name, sex, and the ' + k.evShort + ' event'; } },
            { label: 'Folder',
              hint: 'Optional Source Box folder',
              fill: function () { return null; }, why: 'your own Source Box folder (optional)' }
          ]}
        ]
      }
    }
  };
})();
if (typeof module !== 'undefined') module.exports = CITE_FIELDS;
