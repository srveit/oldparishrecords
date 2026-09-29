#!/usr/bin/env python3
"""Derive Wilmes-records pipeline status from files -> out/status.json + out/status.js.
Precedence per cell: overrides.json > file-derived > records.json 'baseline' > 'Not started'."""
import json, os, glob, datetime, tempfile, hashlib, re
W = os.environ.get('OPR_W', '/workspace/horn-wilmes'); D = os.environ.get('OPR_D', os.path.join(W, 'dashboard')); OUT = os.path.join(D, 'out')
NS = 'Not started'

def load_manifest():
    by = {}
    try:
        for line in open(os.path.join(W, 'entries/manifest.jsonl')):
            line = line.strip()
            if not line: continue
            try: r = json.loads(line)
            except ValueError: continue
            by.setdefault(r.get('image_id') or r.get('scan'), []).append(r)
    except FileNotFoundError: pass
    for k, v in ext_manifest().items(): by.setdefault(k, []).extend(v)     # other projects' crops (read-only), keyed by page id
    return by

def is_locked(e):
    return 'locked' in (str(e.get('crop_status', '')).lower(), str(e.get('status', '')).lower())

def seg(img, man):
    if not img: return None, ''                               # added row without book/image yet
    ents = man.get(img, [])
    if ents:
        nl = sum(map(is_locked, ents))
        if nl == len(ents): return 'Approved', f'{len(ents)} crops, all approved'
        return 'Draft', f'{len(ents)} crops' + (f', {nl} locked' if nl else '')
    tail = img.split('Horn_', 1)[-1]                      # KB007-01-T_0405
    if glob.glob(f'{W}/stage0/{img}_*') or glob.glob(f'{W}/stage0_work/*{tail}*'):
        return 'Queued (page layout done)', 'Stage 0 files present, no crops yet'
    return None, ''

# ---- Rows whose files live in ANOTHER project folder (read-only; nothing there is ever written) ----
# Keyed by (town, book) from records.json. The row's image_id is that project's page id ('KB1000_s078_p164' = Page Structure /
# manifest entry ids minus '_eN'); its manifest entries are merged into load_manifest() under that id, so the segmentation chip,
# the page (every crop of the page cut, copied + ?v=mtime) and setseg --audit treat them like Horn crops.
EXT_PROJECTS = {('lank st. stephanus', 'KB 1000'): {
    'root': '/workspace/lank-kb1000', 'label': 'Lank KB 1000',
    'prefix': 'KB1000',                                    # page id = KB1000_s<scan 3 digits>_p<page>
    'manifest': 'entries/KB1000/manifest.jsonl',          # crops (entry_id, crop_path, crop_status)
    'qc': 'entries/KB1000/_qc',                            # <page id>_redo_overlay.jpg / _redo_contact.jpg
    'structure': 'entries/KB1000/structure/*.jsonl',       # Page Structure (Stage 0): structure_id per entry
    'approve': False,                                      # crops can't be locked from the dashboard (folder is read-only for us)
    'entries': {'N0023': 'KB1000_s078_p164_e3', 'N0024': 'KB1000_s097_p202_e6'}}}   # the row's own entry on the page (target)
def ext_project(r):
    return EXT_PROJECTS.get((str(r.get('town') or '').strip().lower(), str(r.get('book') or '').strip()))
def ext_page_id(r):
    """'KB1000_s078_p164' from the row's image (scan) and page, for any row of an EXT project; '' if either is missing."""
    p = ext_project(r)
    if not p: return ''
    sc = ''.join(ch for ch in str(r.get('image') or '') if ch.isdigit()); pg = ''.join(ch for ch in str(r.get('page') or '').split('\u2013')[0] if ch.isdigit())
    return f"{p['prefix']}_s{int(sc):03d}_p{int(pg)}" if sc and pg else ''
def ext_target(r):
    """The row's own entry id on the page: explicit map, else None (the whole page is shown without a marker)."""
    p = ext_project(r)
    return p['entries'].get(r.get('code')) if p else None
def row_image_id(r):
    return r.get('image_id') or ext_page_id(r)
_EXT_CACHE = {}
def _ext_read(p):
    """(entries by page id, set of Page Structure ids) for one EXT project, read once per run."""
    if p['root'] in _EXT_CACHE: return _EXT_CACHE[p['root']]
    man, struct = {}, set()
    try:
        for l in open(os.path.join(p['root'], p['manifest']), encoding='utf-8'):
            try: j = json.loads(l)
            except ValueError: continue
            eid = str(j.get('entry_id') or ''); m = re.fullmatch(r'(.+)_e\d+[a-z]?', eid)
            if not m: continue
            j = dict(j, image_id=m.group(1), _ext_root=p['root'])
            if not j.get('crop_path') and j.get('crop_image'): j['crop_path'] = os.path.join(p['root'], j['crop_image'])
            man.setdefault(m.group(1), []).append(j)
    except OSError: pass
    for f in glob.glob(os.path.join(p['root'], p['structure'])):
        try:
            for l in open(f, encoding='utf-8'):
                try: sid = json.loads(l).get('structure_id')
                except ValueError: continue
                if sid: struct.add(sid)
        except OSError: pass
    _EXT_CACHE[p['root']] = (man, struct); return _EXT_CACHE[p['root']]
def ext_manifest():
    out = {}
    for p in EXT_PROJECTS.values(): out.update(_ext_read(p)[0])
    return out
def ext_seg(r):
    """No crops yet for an EXT page: Page Structure done -> 'Queued (page layout done)'; else None (not started)."""
    p, pid = ext_project(r), ext_page_id(r)
    if not (p and pid): return None, ''
    if any(s.startswith(pid + '_e') for s in _ext_read(p)[1]): return 'Queued (page layout done)', f'Page Structure done, no crops yet ({pid}, {p["label"]})'
    return None, ''

def _crops_newer(r, img, man, since):
    """True when a crop file for this row is newer than the 'Segmenting' stamp (no stamp -> False: the reported stage stands,
    so an old cut being redone does not hide the Segmenter's report)."""
    try: t0 = datetime.datetime.fromisoformat(str(since)).timestamp()
    except (TypeError, ValueError): return False
    return any(os.path.isfile(e.get('crop_path') or '') and os.path.getmtime(e['crop_path']) > t0 for e in man.get(img, []))

# Stage A folder per row code. Normally stageA/<code>; some rows live in a town-prefixed folder (W-S0036 -> Warstein_S0036).
# Explicit aliases first, then a unique '<Town>_<rest>' folder whose town starts with the code's prefix letter. Files are never moved.
STAGEA_ALIASES = {'W-S0036': 'Warstein_S0036'}
def _sa(code):
    base = os.path.join(W, 'stageA')
    d = os.path.join(base, code)
    if os.path.isdir(d): return d
    a = STAGEA_ALIASES.get(code)
    if a and os.path.isdir(os.path.join(base, a)): return os.path.join(base, a)
    m = re.fullmatch(r'([A-Za-z])-(\w+)', code or '')
    if m:
        c = [n for n in (os.listdir(base) if os.path.isdir(base) else []) if n.endswith('_' + m.group(2)) and n[:1].upper() == m.group(1).upper()
             and os.path.isdir(os.path.join(base, n))]
        if len(c) == 1: return os.path.join(base, c[0])
    return d
def _sa_md(code):
    """Path of the Stage A summary .md (<code>_stageA.md, or <folder>_stageA.md for an aliased folder); '' if none."""
    d = _sa(code)
    for n in (f'{code}_stageA.md', f'{os.path.basename(d)}_stageA.md'):
        if os.path.isfile(os.path.join(d, n)): return os.path.join(d, n)
    return ''

STALL_MIN = 60   # 'In progress (stalled?)' when dispatched, no diplomatic JSON yet and _work unchanged this long
def trans(code, img, man):
    d = _sa(code)
    js = glob.glob(os.path.join(d, '*.diplomatic.json')) if os.path.isdir(d) else []
    need = {e['entry_id'] for e in man.get(img, []) if e.get('entry_kind') != 'blank'}
    wk = os.path.join(d, '_work')
    wfiles = [os.path.join(r, f) for r, _, fs in os.walk(wk) for f in fs] if os.path.isdir(wk) else []
    try: sent = set(json.load(open(os.path.join(D, 'auto_transcribe_sent.json'))).get('dispatched', []))
    except Exception: sent = set()
    dispatched = img in sent or f'{img}_L' in sent or f'{img}_R' in sent
    tot = len(need) or '?'
    if not js:
        if wfiles:
            newest = max(os.path.getmtime(f) for f in wfiles)
            age = (datetime.datetime.now().timestamp() - newest) / 60
            last = datetime.datetime.fromtimestamp(newest).strftime('%H:%M')
            if dispatched and age > STALL_MIN:
                return 'In progress (stalled?)', f'no entry finished yet; _work unchanged since {last} ({int(age)} min)'
            return f'In progress (0/{tot} entries)', f'Transcriber working in _work ({len(wfiles)} files, last change {last})'
        if dispatched or seg(img, man)[0] == 'Approved':
            return 'Queued', 'segmentation approved; sent to transcriber'
        return None, ''
    have = {os.path.basename(p)[:-len('.diplomatic.json')] for p in js}
    md = _sa_md(code)
    if need and need <= have and md:
        st = set()
        for p in js:
            try: st.add(str(json.load(open(p)).get('status', '')).lower())
            except Exception: st.add('?')
        if st and st <= {'approved', 'locked', 'final'}: return 'Approved', f'{len(have)} entries approved'
        return 'Draft', f'{len(have & need)}/{len(need)} entries'
    return f'In progress ({len(have & need)}/{tot} entries)', ('' if md else 'no summary .md yet') + (f'; {len(wfiles)} files in _work' if wfiles else '')

EXPANSION_HELP = 'Transcription with abbreviations and omitted letters written out'
EXPANSION_PRODUCER = True       # the Entry Expander exists (Stephen, 29 Sep 2026); False = column always Not started
WAIT_EXP = 'Waiting on Expansion'
EXP_OVR = {'queued': 'Queued', 'inprogress': 'In progress', 'in progress': 'In progress', 'in-progress': 'In progress'}

def _exp_dir(code):
    """stageA_expanded/<folder>: same folder alias as Stage A (e.g. Warstein rows), else the code itself."""
    base = os.path.join(W, 'stageA_expanded'); a = os.path.join(base, os.path.basename(_sa(code)))
    if os.path.isdir(a): return a
    b = os.path.join(base, code)
    return b if os.path.isdir(b) else a

def _exp_files(code):
    return sorted(p for p in glob.glob(os.path.join(_exp_dir(code), '*.expanded.json')) if os.path.isfile(p) and '.bak' not in os.path.basename(p))

def _exp_md(code):
    d = _exp_dir(code)
    for n in (f'{code}_expanded.md', f'{os.path.basename(d)}_expanded.md'):
        if os.path.isfile(os.path.join(d, n)): return os.path.join(d, n)
    m = sorted(p for p in glob.glob(os.path.join(d, '*_expanded.md')) if '.bak' not in os.path.basename(p))
    return m[0] if m else None

def _exp_load(p):
    """Defensive reader for one <entry_id>.expanded.json -> dict(entry_id, status, text, margin, diplomatic, crop, notes, ok)."""
    eid = os.path.basename(p)[:-len('.expanded.json')]
    try: j = json.load(open(p, encoding='utf-8'))
    except Exception as ex: return {'entry_id': eid, 'status': '', 'text': f'(unreadable: {ex})', 'ok': False}
    if not isinstance(j, dict): j = {'expanded_text': j if isinstance(j, str) else json.dumps(j, ensure_ascii=False)}
    def first(*ks):
        for k in ks:
            v = j.get(k)
            if isinstance(v, str) and v.strip(): return v
            if isinstance(v, list) and v and all(isinstance(x, str) for x in v): return '\n'.join(v)
        return ''
    crop = j.get('crop_path') or j.get('crop_paths') or ''
    return {'entry_id': str(j.get('entry_id') or eid), 'file_id': eid, 'status': str(j.get('status', '')).lower(),
            'text': first('expanded_text', 'expanded', 'expansion', 'text', 'expanded_diplomatic'),
            'tr_de': _tr_text(j.get('translation_de')), 'tr_en': _tr_text(j.get('translation_en')),
            'margin': first('expanded_margin', 'margin_expanded'),
            'diplomatic': first('diplomatic_text', 'source_text'), 'crop': crop,
            'notes': first('notes', 'note', 'expansion_notes'), 'ok': True}

def _exp_state(code):
    """File-derived Expansion state or None (no entry files yet). N = Stage A entries (diplomatic JSON files)."""
    fs = _exp_files(code)
    if not fs: return None
    need = {os.path.basename(p)[:-len('.diplomatic.json')] for p in glob.glob(os.path.join(_sa(code), '*.diplomatic.json'))}
    have = {os.path.basename(p)[:-len('.expanded.json')] for p in fs}
    n = len(need) or len(have); d = len(have & need) if need else len(have)
    md = _exp_md(code)
    if d < n: return f'In progress ({d}/{n} entries)', 'Entry Expander output arriving'
    if not md: return f'In progress ({d}/{n} entries)', 'all entries; no summary _expanded.md yet'
    sts = [_exp_load(p)['status'] for p in fs]
    nl = sum(x in _LOCKED for x in sts)
    if nl == len(sts): return 'Approved', f'{nl} entries locked'
    return 'Draft', f'{nl}/{len(sts)} entries locked' if nl else f'{len(sts)} entries'

def expansion_output(code):
    """The Record Extraction gate: True once Expansion has output = Draft or Approved (all entries + the _expanded.md)."""
    s = _exp_state(code)
    return bool(s) and s[0] in ('Draft', 'Approved')

def expan(code, trans_status, ovr=None):
    """Expansion stage (between Transcription and Record Extraction). Rules (Stephen, 29 Sep 2026):
    - it may begin only after the row's transcription is Approved: anything else -> Not started (never Queued/In progress),
      an overrides.json 'expansion' value is ignored then;
    - transcription Approved: Queued (no output yet) -> In progress (d/N entries: some .expanded.json, or all without the .md)
      -> Draft (all entries + .md, not all locked) -> Approved (all locked);
    - overrides.json 'expansion' (setexp.py: Queued / In progress[ (d/N entries)]) applies only while no .expanded.json exists.
    Returns (status, detail, source)."""
    if not str(trans_status).lower().startswith('approved'): return NS, 'starts after the transcription is Approved', 'rule'
    if not EXPANSION_PRODUCER: return NS, 'transcription approved; no Expansion producer yet', 'rule'
    s = _exp_state(code)
    if s and s[0] in ('Draft', 'Approved'): return s[0], s[1], 'files'
    if s: return s[0], s[1], 'files'            # entry files are more precise than a reported stage
    if ovr: return str(ovr), 'reported by the Entry Expander (setexp.py)', 'override'
    return 'Queued', 'waiting for the Entry Expander', 'files'

def extr(code, img):
    hits = []                                                # img '' (added row without image) matches by code only
    for base in (f'{W}/records', f'{W}/stageB'):
        for p in glob.glob(f'{base}/**/*', recursive=True):
            n = os.path.basename(p)
            if os.path.isfile(p) and not _is_meta(p) and '.bak' not in n and (code in n or (img and (img in n or img.replace('Horn_', '') in n)) or f'_{code}_' in n):
                hits.append(p)
    if not hits: return None, ''
    st = set()
    for p in hits:
        if p.endswith('.json'):
            try:
                j = json.load(open(p))            # Stage B schema: stage_b_status ('status' in records can be a person's status)
                st.add(str(j.get('stage_b_status') if 'stage_b_status' in j else j.get('status', '')).lower())
            except Exception: pass
    nj = sum(p.endswith('.json') for p in hits); other = len(hits) - nj
    if not nj: return None, ''     # a summary .md alone (page-metadata-only folder) is not an extraction (Chief hot patch 16:02)
    nmd = sum(p.endswith('.md') for p in hits)
    det = f'{nj} record(s)' + (' + summary .md' if nmd == 1 else f' + {nmd} .md' if nmd else '') + (f' + {other - nmd} other file(s)' if other - nmd else '')          # page metadata files are never counted
    if st and st <= {'locked', 'approved', 'final'}: return 'Approved', det
    return 'Draft', det

MBASE = 'https://data.matricula-online.eu/de/deutschland/paderborn/'
def _mbase(r):
    """Matricula base for the row's diocese (records.json 'diocese'; absent = paderborn, as every original row)."""
    return MBASE.replace('/paderborn/', f"/{r['diocese']}/") if r.get('diocese') else MBASE

def mlink(r):
    """Every row gets collection + pg + url. url field wins; else collection+book+pg (pg defaults to printed page digits).
    Added rows ('added_by') never fall back to DE_EBAP_22212: no collection -> no link (other dioceses, e.g. Lank = aachen)."""
    col = r.get('collection') or ('' if r.get('added_by') else 'DE_EBAP_22212')
    pg = r.get('pg') or (''.join(ch for ch in str(r.get('page', '')).split('\u2013')[-1] if ch.isdigit()) or None)
    url = r.get('url') or ((f"{_mbase(r)}{col}/{r['book']}/" + (f"?pg={pg}" if pg else '')) if (r.get('book') and col) else '')
    out = {'collection': col, 'pg': pg if (col or r.get('url')) else None, 'url': url}
    for k in ('diocese', 'book_url'):                      # only present on rows that carry them (original rows unchanged)
        if r.get(k): out[k] = r[k]
    return out

# ---- Draft extraction pages: out/extraction/<code>.html for every row whose extraction status is Draft ----
import html as _html, re as _re
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import readings as RD   # alternative readings base[?|alt]: shared with approve_server.py
def _enum(name):
    m = _re.search(r'_e(\d+)(?:[._]|$)', name); return int(m.group(1)) if m else 10**6

def _etag(eid):
    m = _re.search(r'((?:[LR]_)?e\d+)$', str(eid)); return m.group(1) if m else str(eid)

def _stagea_text(code):
    d = _sa(code); blocks = []
    for p in sorted(glob.glob(os.path.join(d, '*.diplomatic.json')), key=lambda q: (_enum(os.path.basename(q)), q)):
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception as ex: blocks.append(f'--- {os.path.basename(p)}: unreadable ({ex}) ---'); continue
        eid = j.get('entry_id') or os.path.basename(p)[:-len('.diplomatic.json')]
        lab = ', '.join(str(x) for x in (j.get('segment_label'), j.get('entry_kind')) if x)
        t = f'--- {_etag(eid)}' + (f' ({lab})' if lab else '') + ' ---\n' + str(j.get('diplomatic_text') or '')
        if j.get('diplomatic_margin'): t += '\n[margin] ' + str(j['diplomatic_margin'])
        blocks.append(t)
    if blocks: return '\n\n'.join(blocks), 'Stage A diplomatic JSON (diplomatic_text)'
    md = _sa_md(code)
    if md: return open(md, encoding='utf-8').read(), os.path.basename(md)
    return '(no Stage A transcription found)', 'none'

NOCACHE = ('<meta name="robots" content="noindex,nofollow">'   # hidden page (also served at oldparishrecords.com/dashboard)
           '<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">'
           '<meta http-equiv="Pragma" content="no-cache"><meta http-equiv="Expires" content="0">')
# Colour-blind-safe status chips (Okabe-Ito; Stephen is red/green colour blind). The SAME CSS/JS is inlined in index.html
# (<style id="oprchipcss"> / <script id="oprchipjs">); keep both in sync. Every state has its own symbol, colour is never the only cue:
#   k-need  NEEDS STEPHEN  solid #e69f00, black bold text, 2px black border, ⚠ (gentle pulse unless prefers-reduced-motion)
#   k-proc  PROCESSING     #eeeeee, #333 text, 1px dashed #888, ⏳ ; k-wait = stale >30 min (⏳!)
#   k-done  APPROVED/DONE  quiet #e8f1fa, #0b4f8a text, 1px #0072b2, ✓
#   k-err   ERROR          #d55e00 vermillion, white bold, ✖ ;  k-none NOT STARTED white, #555, ○
# The class is derived from the chip TEXT (oprKind in JS, _kind here) and re-applied by a MutationObserver, so in-place updates recolour.
# Phone layout (iPhone SE/13 portrait + landscape): injected into every detail page by _write_page; index.html has its own block.
MOBILE_CSS = ".rtype{display:inline-block;padding:0 7px;border:1.5px solid #222;border-radius:3px;background:#fff;color:#222;font-size:13px;font-weight:600;line-height:1.5;white-space:nowrap;vertical-align:1px}.rtype .rti::before{content:\"\\25a4\\00a0\"}.rtype .de{font-weight:400;color:#444}.rtype.unk{border-style:dotted;color:#444;font-style:italic}body{padding-left:env(safe-area-inset-left);padding-right:env(safe-area-inset-right)}a.full{display:block;cursor:zoom-in}.hdr a.hl{color:#0b4f8a;text-decoration:underline;text-underline-offset:2px;text-decoration-thickness:1px}.hdr a.hl:focus,.hdr a.hl:focus-visible{outline:3px solid #0b4f8a;outline-offset:2px;border-radius:3px;background:#e8f1fa}.stktog{display:none}@media (max-width:700px),(pointer:coarse) and (max-height:500px){body{margin:10px 12px}h1{font-size:19px}p,li,summary,label,textarea,input,select,.corrpanel{font-size:16px}.stk{margin:0 -12px 12px;padding:6px 12px;--stkpt:6px}.stk .rtype .de,.stk .rtype .rti{display:none}.stk .rtype{font-size:12px;padding:0 4px;letter-spacing:-.1px}.hdr a.back{font-size:0;text-decoration:none}.hdr a.back::before{content:\"\\2190\";font-size:20px;line-height:1;padding:0 12px 0 2px}.stk .hdr{font-size:14px;line-height:1.45;padding:6px 10px}.apvbox{max-width:none;margin:0 0 4px 8px}html:not(.stkopen) .stk .stail,html:not(.stkopen) .stk .l2,html:not(.stkopen) .stk .draftban,html:not(.stkopen) .stk #tg,html:not(.stkopen) .stk .stagenote,html:not(.stkopen) .stk #oprupd{display:none}.stktog{display:inline-flex;align-items:center;justify-content:center;margin-left:6px;padding:0 10px;border:1px solid #888;border-radius:6px;background:#fff;color:#222;font-size:14px;vertical-align:middle;cursor:pointer}.stktog::after{content:\"more \\25be\"}html.stkopen .stktog::after{content:\"less \\25b4\"}pre{font-size:15px}pre.stagea-text{font-size:18px}.entact{float:none;display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:6px}}@media (pointer:coarse){.apv,.rcb,.entapv,.corrbtn,.corrpanel button,#tg,.stktog{min-height:44px;min-width:44px;box-sizing:border-box}.entapv,.fbchip,.entok{margin-left:0}.ck{min-width:44px;min-height:44px;font-size:16px;vertical-align:middle;margin:2px 4px}.corrpanel label{display:flex;align-items:center;min-height:44px;margin:0;white-space:normal}.corrpanel input[type=checkbox]{width:24px;height:24px;margin:0 10px 0 0;flex:0 0 auto}details>summary{min-height:44px;padding-top:10px;padding-bottom:10px;box-sizing:border-box}body>p>a,.hdr a{display:inline-block;padding:10px 0}.hdr a.hl{display:inline;padding:14px;margin:0 -14px}#oprlogout{padding:13px 14px!important;font-size:15px!important}body{padding-bottom:calc(56px + env(safe-area-inset-bottom))}}body{margin-top:0}.stk{position:-webkit-sticky;position:sticky;top:0;margin-top:0}.hdr a.back{white-space:nowrap}@media (pointer:coarse) and (max-height:500px){.stk{max-height:50vh;max-height:50dvh;overflow-y:auto;-webkit-overflow-scrolling:touch}html:not(.stkopen) .stk .kd{display:none}html:not(.stkopen) .stktog::after{content:\"\\25be\"}html:not(.stkopen) .stktog{padding:0 6px}}.stk{padding-top:calc(var(--stkpt,8px) + env(safe-area-inset-top,0px))}"
MOBILE_JS = "(function(){if(window.oprStk)return;window.oprStk=1;var H=document.documentElement;try{if(sessionStorage.getItem('oprStk')==='1')H.classList.add('stkopen');}catch(e){}document.addEventListener('click',function(ev){var t=ev.target&&ev.target.closest?ev.target.closest('.stktog'):null;if(!t)return;H.classList.toggle('stkopen');var o=H.classList.contains('stkopen');t.setAttribute('aria-expanded',o?'true':'false');try{sessionStorage.setItem('oprStk',o?'1':'');}catch(e){}var st=document.getElementById('stk');if(st)H.style.setProperty('--stkh',st.offsetHeight+'px');});})();"
CHIP_CSS = ".k-done,.k-need,.k-proc,.k-wait,.k-err,.k-none{white-space:nowrap}.k-done{background:#e8f1fa!important;color:#0b4f8a!important;border:1px solid #0072b2!important;font-weight:600!important}.k-need{background:#e69f00!important;color:#000!important;border:2px solid #000!important;font-weight:800!important}.k-proc,.k-wait{background:#eeeeee!important;color:#333!important;border:1px dashed #888!important;font-weight:600!important}.k-wait{border-color:#333!important}.k-err{background:#d55e00!important;color:#fff!important;border:2px solid #000!important;font-weight:800!important}.k-none{background:#fff!important;color:#555!important;border:1px solid #bbb!important;font-weight:600!important}.k-done::before{content:\"\\2713\\00a0\"}.k-need::before{content:\"\\26a0\\fe0e\\00a0\"}.k-proc::before{content:\"\\23f3\\00a0\"}.k-wait::before{content:\"\\23f3!\\00a0\"}.k-err::before{content:\"\\2716\\00a0\"}.k-none::before{content:\"\\25cb\\00a0\"}.lgc,.qbadge{display:inline-block;padding:1px 9px;border-radius:12px;font-size:12px;margin:0 4px 2px 0;vertical-align:1px}.qbadge{background:#e69f00;color:#000;border:2px solid #000;font-weight:800;margin-left:8px;cursor:help}@media (prefers-reduced-motion:no-preference){.k-need{animation:oprpulse 2.6s ease-in-out infinite}}@keyframes oprpulse{0%,100%{box-shadow:0 0 0 0 rgba(230,159,0,0)}50%{box-shadow:0 0 0 4px rgba(230,159,0,.45)}}.oprerr{color:#d55e00;font-weight:700}"
CHIP_JS = "(function(){if(window.oprKind)return; var KS=['k-done','k-need','k-proc','k-wait','k-err','k-none'],SEL='.chip,.segchip,.fbchip,.entok,.corrpend,.corrsent'; function K(t){t=String(t||'').replace(/^[\\s\\u2713\\u26a0\\ufe0e\\u23f3\\u2716\\u25cb!]+/,'').toLowerCase();if(!t)return ''; if(/^(blocked|error|failed|not sent|not done|not approved)/.test(t))return 'err'; if(/^(queued for redo|correction (pending|sent)|recut|draft)/.test(t))return 'need'; if(/^waiting on transcriber/.test(t))return 'wait'; if(/^waiting on expansion/.test(t))return 'proc'; if(/hold|^redoing|^queued|progress|running|transcrib|extracting|updating|first pass|sending|requesting|approving|researching|segmenting/.test(t))return 'proc'; if(/^(approved|locked|updated|done|complete|page found|added)/.test(t))return 'done'; if(/^not started/.test(t))return 'none';return '';} function apply(){[].forEach.call(document.querySelectorAll(SEL),function(el){var k=K(el.textContent),c=k?'k-'+k:''; KS.forEach(function(x){if(x!==c&&el.classList.contains(x))el.classList.remove(x);});if(c&&!el.classList.contains(c))el.classList.add(c);}); [].forEach.call(document.querySelectorAll('details.ent'),function(d){var a=d.querySelector('summary .entact');if(!a)return; var n=d.querySelectorAll('.tq:not(.confirmed) .qm').length,b=a.querySelector('.qbadge'); if(n){if(!b){b=document.createElement('span');b.className='qbadge';b.title='Unconfirmed readings [?] in this entry (tap \\u2713 next to each to confirm)';a.insertBefore(b,a.firstChild);} var t='[?] '+n;if(b.textContent!==t)b.textContent=t;}else if(b)b.remove();});} window.oprKind=K;window.oprKindApply=apply;var q=0; function sch(){if(q)return;q=1;setTimeout(function(){q=0;apply();},0);} function start(){apply();new MutationObserver(sch).observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class']});} if(document.body)start();else document.addEventListener('DOMContentLoaded',start);})();"
def _kind(st):
    t = re.sub(r'^[\s\u2713\u26a0\ufe0e\u23f3\u2716\u25cb!]+', '', str(st or '')).lower()
    if not t: return ''
    if re.match(r'(blocked|error|failed|not sent|not done|not approved)', t): return 'err'
    if re.match(r'(queued for redo|correction (pending|sent)|recut|draft)', t): return 'need'
    if t.startswith('waiting on transcriber'): return 'wait'
    if re.search(r'hold|^redoing|^queued|progress|running|transcrib|extracting|updating|first pass|sending|requesting|approving|researching|segmenting', t): return 'proc'
    if re.match(r'(approved|locked|updated|done|complete|page found|added)', t): return 'done'
    if t.startswith('not started'): return 'none'
    return ''
PAGE_CSS = ('body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:20px;color:#222}h1{font-size:20px;margin:0 0 6px}'
    '.hdr{background:#eef2f8;border:1px solid #d5dce8;border-radius:8px;padding:10px 14px;margin-bottom:16px;line-height:1.6}'
    'h2{font-size:17px;color:#1a3d7c;margin:18px 0 6px}pre{white-space:pre-wrap;word-wrap:break-word;'
    'font-family:Menlo,Consolas,"DejaVu Sans Mono",monospace;font-size:13px;background:#fafafa;border:1px solid #ddd;border-radius:6px;padding:10px}'
    'pre.stagea-text{font-size:calc(13px * 1.5)}.stk{position:sticky;top:0;z-index:10;background:#fff;margin:0 -20px 14px;padding:8px 20px;border-bottom:1px solid #c9d2e0;box-shadow:0 3px 6px -3px rgba(0,0,0,.2)}.stk .hdr{margin-bottom:0}.stk #tg{margin:8px 0 0}.stk .draftban{margin:8px 0 0}.apvbox{float:right;margin:0 0 6px 24px;text-align:right;max-width:45%}.apv{padding:6px 18px;font-weight:700;font-size:14px;background:#fff;color:#0072b2;border:2px solid #0072b2;border-radius:6px;cursor:pointer;box-shadow:0 1px 2px rgba(0,0,0,.15)}.apv:hover{background:#0072b2;color:#fff}.entact{float:right}.entapv{margin-left:8px;padding:2px 10px;font-size:12px;font-weight:800;background:#e69f00;color:#000;border:2px solid #000;border-radius:5px;cursor:pointer}.entapv::before{content:"\\26a0\\fe0e\\00a0"}.entapv:disabled{opacity:.6}.entok{margin-left:8px;padding:1px 9px;font-size:12px;border-radius:10px}.fbchip{margin-left:8px;padding:1px 9px;font-size:12px;font-weight:700;border-radius:10px}.ck{margin:0 2px 0 1px;padding:0 4px;font-size:11px;line-height:15px;border:1px solid #0072b2;color:#0072b2;background:#fff;border-radius:4px;cursor:pointer;vertical-align:1px}.ck:disabled{opacity:.5}.tq .qm{color:#b36b00}.tq.confirmed{background:#e8f1fa;border-radius:3px;transition:background 3s}.ckerr{color:#d55e00;font-size:12px;font-weight:700;margin-left:4px}.rcb{padding:5px 14px;font-weight:600;font-size:13px;background:#fff;color:#0b4f8a;border:2px dashed #0072b2;border-radius:6px;cursor:pointer}.rcb:hover{background:#e8f1fa}.rcb:disabled{opacity:.6;cursor:wait}.apv:disabled{opacity:.6;cursor:wait}#apvmsg{display:block;font-size:12px;margin-top:4px}.chip{display:inline-block;padding:1px 10px;border-radius:12px;font-size:13px;font-weight:700}details.ent,figure.crop,h2{scroll-margin-top:calc(var(--stkh,170px) + 10px)}.rec h3{font-size:15px;margin:14px 0 4px}.fn{font-weight:400;color:#666;font-size:12px;font-family:monospace}a{color:#1a5fb4}.src{color:#777;font-size:12px}')

def _stagea_entries(code):
    """{entry_no: [(tag, label, text), ...]} from Stage A diplomatic JSON (several parts when an entry spans L/R faces)."""
    d = _sa(code); out = {}
    for p in sorted(glob.glob(os.path.join(d, '*.diplomatic.json')), key=lambda q: (_enum(os.path.basename(q)), q)):
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception as ex: out.setdefault(_enum(os.path.basename(p)), []).append((os.path.basename(p), '', f'(unreadable: {ex})')); continue
        eid = j.get('entry_id') or os.path.basename(p)[:-len('.diplomatic.json')]
        lab = ', '.join(str(x) for x in (j.get('segment_label'), j.get('entry_kind')) if x)
        t = str(j.get('diplomatic_text') or '')
        if j.get('diplomatic_margin'): t += '\n[margin] ' + str(j['diplomatic_margin'])
        out.setdefault(_enum(eid), []).append((_etag(eid), lab, t))
    return out

def _sb_summary(j):
    """(date, name) for a Stage B record; '' where unknown."""
    iso = _re.compile(r'^\d{4}(-\d{2}(-\d{2})?)?$'); date = ''
    for k in ('baptism_date_iso', 'marriage_date_iso', 'marriage_date', 'burial_date_iso', 'burial_date', 'death_date_iso',
              'death_date', 'birth_date_iso', 'event_date_iso', 'event_date', 'date_iso', 'date'):
        v = j.get(k)
        if isinstance(v, str) and v.strip(): date = v.strip(); break
    if not date:
        for k, v in j.items():
            if k.endswith('date_iso') and isinstance(v, str) and iso.match(v.strip()): date = v.strip(); break
    nm = lambda v: v.get('name') if isinstance(v, dict) else v
    name = ''
    if j.get('groom_name') or j.get('bride_name'):
        name = ' \u00d7 '.join(str(x) for x in (nm(j.get('groom_name')), nm(j.get('bride_name'))) if x)
    else:
        for k in ('child_name', 'deceased_name', 'principal_name', 'person_name', 'name', 'principal', 'child', 'deceased', 'groom'):
            v = nm(j.get(k))
            if isinstance(v, str) and v.strip(): name = v.strip(); break
    return date, name

TR_CSS = ('details.tr{border:1px solid #c9d2e0;border-left:4px solid #56b4e9;border-radius:6px;margin:8px 0;background:#fbfcfe}'
          'details.ent details.tr>summary,details.tr>summary{cursor:pointer;padding:6px 10px;font-weight:700;font-size:14px;min-height:28px;background:#eef6fc;border:0;border-radius:6px 6px 0 0}'
          'details.tr>div{padding:2px 12px 10px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:15px;line-height:1.45}'
          '@media (pointer:coarse){details.ent details.tr>summary,details.tr>summary{min-height:44px;box-sizing:border-box;padding-top:12px}}')

def _tr_text(v):
    """translation value -> text: a string, or {'text': ...} (Stage B translation_en.text), else ''."""
    if isinstance(v, str): return v.strip()
    if isinstance(v, dict) and isinstance(v.get('text'), str): return v['text'].strip()
    return ''

def _tr_block(label, lang, text, E):
    """Read-only translation block, open by default; nothing when the text is absent."""
    return (f'<details class="tr" open><summary>{E(label)}</summary><div lang="{lang}">{E(text)}</div></details>' if text else '')

# ---- Extraction pages: Stage B records as label-and-value (Stephen, 29 Sep 2026) + Page metadata card ----
PAGE_META_SUFFIX = '_page_metadata.json'          # stageB/<code>/*_page_metadata.json: one per page (spreads: two); never a record
def _is_meta(p): return os.path.basename(p).endswith(PAGE_META_SUFFIX)
SCHEMA_DIRS = [os.environ.get('OPR_SCHEMA_DIR', '/workspace/lank-schema/book-meta/entry/extraction')]   # Schema Steward schemas (read-only)
_SCHEMAS = None
def _schema_props(schema_id):
    """{field: (title or None, description or None)} from the Stage B JSON schema whose $id names schema_id; {} if none."""
    global _SCHEMAS
    if _SCHEMAS is None:
        _SCHEMAS = {}
        for d in SCHEMA_DIRS:
            for p in glob.glob(os.path.join(d, '*.schema.json')):
                try: s = json.load(open(p, encoding='utf-8'))
                except Exception: continue
                m = re.search(r'/schemas/([^/]+)/', str(s.get('$id', '')))
                props = {k: (v.get('title'), v.get('description')) for k, v in (s.get('properties') or {}).items() if isinstance(v, dict)}
                if m: _SCHEMAS[m.group(1)] = props
    return _SCHEMAS.get(str(schema_id or ''), {})

_POSS = {'child', 'father', 'mother', 'godfather', 'godmother', 'groom', 'bride', 'deceased', 'spouse', 'priest'}
_WORDS = {'iso': '(ISO)', 'id': 'ID', 'url': 'URL', 'en': '(English)', 'de': '(German)', 'latin': 'Latin', 'md5': 'MD5', 'a': 'A', 'b': 'B', 'pg': 'pg', 'ids': 'IDs'}
_LABELS = {'place_ref': 'Place', 'soft_fields': 'Uncertain fields', 'banns_or_dispensation': 'Banns or dispensation',
           'spouse_or_parents': 'Spouse or parents', 'witnesses_other': 'Other witnesses'}
def _human(k):
    """child_given_name -> "Child's given name", date_of_baptism -> 'Date of baptism', baptism_date_iso -> 'Baptism date (ISO)'."""
    if k in _LABELS: return _LABELS[k]
    parts = [x for x in str(k).split('_') if x]
    if not parts: return str(k)
    head = ''
    if len(parts) > 1 and parts[0] in _POSS and not parts[1].isdigit(): head = parts[0].capitalize() + '\u2019s '; parts = parts[1:]
    s = ' '.join(_WORDS.get(w, w) for w in parts)
    return head + s if head else s[:1].upper() + s[1:]

def _label(k, props):
    t, d = props.get(k, (None, None))
    return (t or _human(k)), (d or '')

def _empty(v): return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)

def _summ(o):
    """One-line summary of an object in a list (e.g. a godparent): given name + surname / name, alias, then residence/role."""
    g = lambda *ks: next((str(o[k]).strip() for k in ks if isinstance(o.get(k), (str, int, float)) and str(o[k]).strip()), '')
    name = ' '.join(x for x in (g('given_name', 'first_name', 'forename', 'given'), g('surname', 'last_name', 'family_name')) if x) \
        or g('name', 'full_name', 'name_as_written', 'as_written', 'text')
    al = g('alias', 'dictus', 'vulgo', 'genannt')
    tail = ', '.join(x for x in (g('residence', 'residence_as_written', 'place', 'town', 'origin'), g('role', 'relation', 'status', 'kind')) if x)
    s = (name + (f' {al}' if al else '')).strip()
    if not s:
        vals = [str(v).strip() for v in o.values() if isinstance(v, (str, int, float)) and str(v).strip()]
        s = ', '.join(vals[:2])
    return (s + (', ' + tail if tail and tail not in s else '')) or '(no details)'

def _unc(note, E):
    return (f' <span class="unc" title="{E(note)}">\u26a0\ufe0e [?]</span> <span class="uncn">{E(note)}</span>' if note else '')

def _val(v, E, props, soft, depth=0, mono=False):
    """HTML for one value; lists -> bullets (objects: summary line + indented sub-fields); dicts -> nested label/value."""
    if _empty(v): return '<span class="none">none</span>' if isinstance(v, list) else '<span class="none">\u2014</span>'
    if isinstance(v, bool): return 'Yes' if v else 'No'
    if isinstance(v, list):
        li = []
        for x in v:
            if isinstance(x, dict):
                li.append(f'<li><span class="bsum">{E(_summ(x))}</span>' + _kv(x, E, props, {}, depth + 1) + '</li>')
            else: li.append(f'<li>{_val(x, E, props, soft, depth + 1)}</li>')
        return '<ul class="bl">' + ''.join(li) + '</ul>'
    if isinstance(v, dict): return _kv(v, E, props, {}, depth + 1)
    return f'<span class="{"kvt mono" if mono else "kvt"}">{E(v)}</span>'

def _row(k, v, E, props, soft, label=None, extra='', mono=False):
    lab, desc = (label, '') if label else _label(k, props)
    full = isinstance(v, (list, dict)) and not _empty(v)
    cls = 'kr' + (' kv-empty' if _empty(v) else '') + (' kfull' if full else '')
    return (f'<div class="{cls}"><div class="kl"{f" title={chr(34)}{E(desc)}{chr(34)}" if desc else ""}>{E(lab)}</div>'
            f'<div class="kvv">{_val(v, E, props, soft, mono=mono)}{_unc(soft.get(k), E) if isinstance(soft.get(k), str) else ""}{extra}</div></div>')

def _kv(o, E, props, soft, depth=0, keys=None):
    return '<div class="kv">' + ''.join(_row(k, o[k], E, props, soft) for k in (keys if keys is not None else o)) + '</div>'

_SECTIONS = [('Event', r'(^|_)dates?(_|$)|^age$|^cause$|burial_place|marriage_place|^banns'), ('Child', r'^child_'),
             ('Deceased', r'^deceased_|^status$|^spouse_or_parents$|^residence$'), ('Groom', r'^groom_'), ('Bride', r'^bride_'),
             ('Father', r'^father|^paternal_'), ('Mother', r'^mother|^maternal_'), ('Parents', r'^parents_'),
             ('Godparents', r'^god(father|mother|parent)'), ('Witnesses', r'^witness'), ('Priest', r'^priest'),
             ('Text', r'^(diplomatic_text|transcription_latin|expanded_latin)$'), ('Notes', r'^notes?$'),
             ('Record', r'^(schema_|stage|entry|parish_slug|archival_id|scan$|page$|incomplete|continu)'), ('Files', r'crop|path')]
_SKIP = {'translation_en', 'translation_de', 'soft_fields'}

def _record_html(j, E):
    """Label-and-value body of one Stage B record (sections, nested objects as subsections, uncertainty markers)."""
    props = _schema_props(j.get('schema_id')); soft = j.get('soft_fields') if isinstance(j.get('soft_fields'), dict) else {}
    buckets, nested, other = {t: [] for t, _ in _SECTIONS}, [], []
    for k, v in j.items():
        if k in _SKIP: continue
        if isinstance(v, dict) and v: nested.append(k); continue
        t = next((t for t, rx in _SECTIONS if re.search(rx, k)), None)
        (buckets[t] if t else other).append(k)
    order = [t for t, _ in _SECTIONS[:11]] + ['__nested__', 'Text', 'Notes', '__other__', 'Record', 'Files']
    out = []
    def sec(title, keys, mono=False, src=None):
        src = j if src is None else src
        if not keys: return
        rows = ''.join(_row(k, src[k], E, props, soft if src is j else {}, mono=mono) for k in keys)
        allempty = all(_empty(src[k]) for k in keys)
        out.append(f'<div class="ksec{" kv-empty" if allempty else ""}"><h4>{E(title)}</h4><div class="kv">{rows}</div></div>')
    for t in order:
        if t == '__nested__':
            for k in nested: sec(_label(k, props)[0], list(j[k]), src=j[k])
        elif t == '__other__': sec('Other fields', other)
        else: sec(t, buckets[t], mono=(t in ('Text', 'Files')))
    left = {k: v for k, v in soft.items() if k not in j or k in _SKIP}
    if left: sec('Uncertain fields', list(left), src=left)
    return ''.join(out)

def _record_card(fn, j, body, E, rid):
    if not isinstance(j, dict) or not j:
        return f'<div class="rec"><h3>Stage B record <span class="fn">{E(fn)}</span></h3><pre>{E(body)}</pre></div>'
    ne = sum(1 for k, v in j.items() if k not in _SKIP and _empty(v))
    return (f'<div class="rec" id="{E(rid)}"><h3>Stage B record <span class="fn">{E(fn)}</span>'
            + (f' <button type="button" class="emptog" aria-pressed="false" data-n="{ne}">Show empty fields ({ne})</button>' if ne else '') + '</h3>'
            + _record_html(j, E)
            + _tr_block('English', 'en', _tr_text(j.get('translation_en')), E) + _tr_block('Deutsch', 'de', _tr_text(j.get('translation_de')), E)
            + f'<details class="vj"><summary>View JSON</summary><pre>{E(body)}</pre></details></div>')

_META_ORDER = [('Parish', ('parish', 'parish_name', 'parish_slug')), ('Book', ('book', 'archival_id', 'book_code')),
               ('Image/Page', ('image', 'scan', 'page', 'page_number', 'printed_page')), ('Register type', ('register_type', 'register_record_type', 'register_types')),
               ('Year(s)', ('page_years', 'years', 'year', 'page_year', 'year_range')), ('Date range', ('date_range', 'date_from', 'date_to', 'first_date', 'last_date')),
               ('Register numbers', ('register_numbers', 'register_number_range', 'register_number', 'entry_numbers')), ('Entry count', ('entry_count', 'entries_count', 'n_entries')),
               ('Column headings', ('column_headings', 'columns')), ('Page-level text', ('page_text', 'page_level_text', 'page_texts', 'texts', 'other_text')),
               ('Languages', ('languages', 'language', 'script_language')), ('Scribe', ('scribe', 'scribes', 'hands_or_scribes', 'hand'))]
_META_URLS = ('book_url', 'matricula_book_url', 'page_url', 'matricula_page_url', 'matricula_url', 'url')

def _meta_text_items(v, E):
    items = v if isinstance(v, list) else [v]
    li = []
    for x in items:
        if isinstance(x, dict):
            kind = x.get('kind') or x.get('type') or x.get('position') or ''
            txt = x.get('text') or x.get('verbatim') or _summ(x)
            li.append(f'<li>{f"<span class=ktag>[{E(kind)}]</span> " if kind else ""}<span class="kvt">{E(txt)}</span></li>')
        elif not _empty(x): li.append(f'<li><span class="kvt">{E(x)}</span></li>')
    return '<ul class="bl">' + ''.join(li) + '</ul>' if li else '<span class="none">none</span>'

def _meta_card(fn, j, r, E, anchor, n_of):
    props = _schema_props(j.get('schema_id')); used = set(_META_URLS); rows = []
    def pick(keys):
        for k in keys:
            if k in j: return k, j[k]
        return None, None
    for lab, keys in _META_ORDER:
        if lab == 'Book':
            k, v = pick(keys); used.update(keys); v = v or r.get('book')
            url = j.get('book_url') or j.get('matricula_book_url') or _book_url(r)
            rows.append(f'<div class="kr{" kv-empty" if _empty(v) else ""}"><div class="kl">Book</div><div class="kvv">'
                        + (_hl(url, v, E, 'Open the book\u2019s title page on Matricula (new tab)') if not _empty(v) else '<span class="none">\u2014</span>') + '</div></div>')
        elif lab == 'Image/Page':
            used.update(keys); im = j.get('image') or j.get('scan') or r.get('image'); pg = j.get('page_number') or j.get('printed_page') or j.get('page') or r.get('page')
            if im and im == r.get('image_id'): im = r.get('image') or im          # show the row's image label (T 0091), not the image id
            t = ' / '.join(str(x) for x in (im, (f'page {pg}' if pg not in (None, '') else '')) if x not in (None, ''))
            url = j.get('page_url') or j.get('matricula_page_url') or j.get('matricula_url') or j.get('url') or r.get('url')
            rows.append(f'<div class="kr{" kv-empty" if not t else ""}"><div class="kl">Image/Page</div><div class="kvv">'
                        + (_hl(url, t, E, 'Open this page on Matricula (new tab)') if t else '<span class="none">\u2014</span>') + '</div></div>')
        elif lab == 'Date range':
            used.update(keys); v = j.get('date_range')
            if isinstance(v, dict): v = ' \u2013 '.join(str(v.get(a)) for a in ('from', 'to', 'start', 'end', 'first', 'last') if v.get(a))
            elif isinstance(v, list): v = ' \u2013 '.join(str(x) for x in v if x)
            if _empty(v): v = ' \u2013 '.join(str(j[a]) for a in ('date_from', 'first_date', 'date_to', 'last_date') if not _empty(j.get(a)))
            rows.append(_row('date_range', v or None, E, {}, {}, label='Date range'))
        elif lab == 'Register numbers':
            k, v = pick(keys); used.update(keys)
            if isinstance(v, dict): v = ' \u2013 '.join(str(v.get(a)) for a in ('from', 'to', 'start', 'end', 'first', 'last') if v.get(a) not in (None, ''))
            rows.append(_row(k or keys[0], v, E, {}, {}, label=lab))
        elif lab == 'Page-level text':
            k, v = pick(keys); used.update(keys)
            rows.append(f'<div class="kr{" kv-empty" if _empty(v) else " kfull"}"><div class="kl">Page-level text</div><div class="kvv">'
                        + (_meta_text_items(v, E) if not _empty(v) else '<span class="none">none</span>') + '</div></div>')
        else:
            k, v = pick(keys); used.update(keys)
            rows.append(_row(k or keys[0], v, E, props, {}, label=lab))
    extra = [k for k in j if k not in used]
    ex = ''.join(_row(k, j[k], E, props, {}) for k in extra)
    ne = sum(1 for x in rows if 'kv-empty' in x[:40]) + sum(1 for k in extra if _empty(j[k]))
    return (f'<section class="pmeta rec" id="{E(anchor)}"><h2>Page metadata{f" ({n_of})" if n_of else ""} <span class="fn">{E(fn)}</span>'
            + (f' <button type="button" class="emptog" aria-pressed="false" data-n="{ne}">Show empty fields ({ne})</button>' if ne else '') + '</h2>'
            + '<div class="kv">' + ''.join(rows) + '</div>' + (f'<div class="ksec"><h4>Other fields</h4><div class="kv">{ex}</div></div>' if ex else '')
            + f'<details class="vj"><summary>View JSON</summary><pre>{E(json.dumps(j, indent=2, ensure_ascii=False))}</pre></details></section>\n')

def _meta_cards(c, r, E):
    fs = sorted(p for p in glob.glob(os.path.join(W, 'stageB', c, '*' + PAGE_META_SUFFIX)) if '.bak' not in os.path.basename(p))
    if not fs:
        return ('<section class="pmeta" id="pagemeta"><h2>Page metadata</h2><span class="chip k-proc">Page metadata pending</span>'
                ' <span class="src">no stageB/' + E(c) + '/*' + PAGE_META_SUFFIX + ' yet</span></section>\n')
    out = ''
    for i, p in enumerate(fs):
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception as ex: j = {'unreadable': str(ex)}
        out += _meta_card(os.path.basename(p), j if isinstance(j, dict) else {'value': j}, r, E, 'pagemeta' if i == 0 else f'pagemeta-{i + 1}',
                          f'{i + 1} of {len(fs)}' if len(fs) > 1 else '')
    return out

KV_CSS = ('.kv{display:grid;grid-template-columns:minmax(150px,28%) minmax(0,1fr);gap:3px 14px;margin:2px 0 6px}'
          '.kr{display:contents}.kl{font-weight:600;color:#444;font-size:14px;padding:3px 0}.kvv{padding:3px 0;min-width:0;overflow-wrap:anywhere;font-size:15px}'
          '.kr.kfull>.kl{grid-column:1/-1;padding-bottom:0}.kr.kfull>.kvv{grid-column:1/-1;padding-top:0}'
          '.kvt{white-space:pre-wrap}.kvt.mono{font-family:Menlo,Consolas,"DejaVu Sans Mono",monospace;font-size:14px}.none{color:#777}'
          'ul.bl{margin:2px 0 4px;padding-left:22px;list-style:disc}ul.bl>li{margin:2px 0}ul.bl .kv{margin-left:4px;font-size:14px}.bsum{font-weight:600}'
          '.ksec h4{margin:12px 0 2px;font-size:14px;color:#1a3d7c;border-bottom:1px solid #e1e6ef;padding-bottom:2px}'
          '.rec{border:1px solid #d5dce8;border-radius:8px;padding:6px 12px 8px;margin:10px 0;background:#fff}'
          '.rec:not(.showempty) .kv-empty{display:none}'
          '.emptog{margin-left:8px;font-size:12px;padding:2px 10px;border:1px solid #0072b2;background:#fff;color:#0b4f8a;border-radius:6px;cursor:pointer;font-weight:600}'
          '.emptog[aria-pressed=true]{background:#e8f1fa}'
          '.unc{background:#e69f00;color:#000;border:1px solid #000;border-radius:4px;padding:0 4px;font-weight:800;font-size:12px;white-space:nowrap}'
          '.uncn{font-style:italic;color:#444;font-size:13px}'
          'details.vj{margin-top:8px}details.vj>summary{cursor:pointer;font-size:12px;color:#555;padding:4px 0}details.vj pre{font-size:12px;max-height:60vh;overflow:auto}'
          '.pmeta{border-left:4px solid #0072b2;background:#f8fafd}.pmeta h2{margin:6px 0}.ktag{font-family:monospace;font-size:12px;color:#0b4f8a;background:#e8f1fa;border:1px solid #0072b2;border-radius:4px;padding:0 4px}'
          'a.ttag{display:inline-block;margin-left:8px;padding:1px 9px;font-size:12px;font-weight:600;border-radius:10px;background:#eef2f8;color:#0b4f8a;border:1px dashed #0072b2;text-decoration:none}'
          'a.ttag::before{content:"\\2139\\fe0e\\00a0"}'
          '@media (max-width:699px){.kv{grid-template-columns:minmax(0,1fr);gap:0}.kl{padding:6px 0 0;font-size:13px}.kvv{padding:0 0 4px}.rec{padding:6px 10px}}'
          '@media (pointer:coarse){.emptog{min-height:44px;padding:6px 12px;font-size:14px}details.vj>summary{min-height:44px;display:flex;align-items:center}a.ttag{padding:12px 12px;font-size:14px}}')
KV_JS = ('<script>(function(){var K="oprEmpty:"+location.pathname;function st(){try{return JSON.parse(sessionStorage.getItem(K)||"{}")}catch(e){return {}}}'
         'function ap(){var s=st();[].forEach.call(document.querySelectorAll(".rec[id]"),function(r){var b=r.querySelector(".emptog");var on=!!s[r.id];'
         'r.classList.toggle("showempty",on);if(b){b.setAttribute("aria-pressed",on?"true":"false");b.textContent=(on?"Hide empty fields":"Show empty fields")+" ("+b.dataset.n+")";}});}'
         'if(!window.oprEmptyInit){window.oprEmptyInit=1;document.addEventListener("click",function(ev){var b=ev.target.closest&&ev.target.closest(".emptog");if(!b)return;'
         'var r=b.closest(".rec");if(!r||!r.id)return;var s=st();s[r.id]=!s[r.id];try{sessionStorage.setItem(K,JSON.stringify(s))}catch(e){}ap();});}ap();})();</script>\n')

def write_extraction_pages(rows, man=None):
    xd = os.path.join(OUT, 'extraction'); os.makedirs(xd, exist_ok=True); made = []; bundles = []
    man = man if man is not None else load_manifest()
    E = lambda t: _html.escape(str(t if t is not None else ''), quote=True)
    for r in rows:
        xs = str(r['extraction']['status']).lower()
        if not xs.startswith(('draft', 'approved')): continue
        nb, nbl = _json_field_counts([p for p in glob.glob(os.path.join(W, 'stageB', r['code'], '*.json')) if '.bak' not in os.path.basename(p) and not _is_meta(p)], 'stage_b_status', 'status')
        c = r['code']; r['extraction']['link'] = f'extraction/{c}.html'
        booku = _book_url(r)      # title page (BOOKPG in index.html: all books = 1); diocese-aware, '' when unknown
        sa = _stagea_entries(c); mdfull = ''
        if not sa:
            md = _sa_md(c) or os.path.join(_sa(c), f'{c}_stageA.md')
            if os.path.isfile(md): mdfull = open(md, encoding='utf-8').read()
        sb = _stageb_records(c)
        nrec = sum(len(v) for v in sb.values()); secs = []
        scr = _stagea_crops(c); pub = _PUB.get(c, {}); titles = {}          # title rows: manifest / Stage A entry_kind 'title'
        for e in man.get(r.get('image_id') or '', []) if r.get('image_id') else []:
            if str(e.get('entry_kind', '')).lower() in ('title', 'header', 'page_header'): titles.setdefault(_enum(str(e.get('entry_id', ''))), []).append(e.get('crop_path') or '')
        for n0, parts in sa.items():
            if any(re.search(r'(^|, )(title|header)$', lab or '') for _, lab, _ in parts): titles.setdefault(n0, [])
        titles = {k: [x for x in v if x] for k, v in titles.items()}
        for n in sorted(set(sa) | set(sb)):
            en = f'e{n}' if n < 10**6 else 'e?'
            recs = sb.get(n, [])
            if recs:
                dt, nm = _sb_summary(recs[0][1])
                summ = f'<b>{E(en)}</b>' + (f' \u00b7 {E(dt)}' if dt else '') + (f' \u00b7 {E(nm)}' if nm else '')
                if not (dt or nm): summ += f' \u00b7 <span class="fn">{E(recs[0][0])}</span>'
            else:
                lab = ', '.join(x[1] for x in sa.get(n, []) if x[1])
                summ = f'<b>{E(en)}</b>' + (f' \u00b7 <span class="fn">{E(lab)}</span>' if lab else '') + (
                    ' <a class="ttag" href="#pagemeta" title="Title row: no record; see the Page metadata card">Title row, no record</a>' if n in titles
                    else ' <span class="miss">no Stage B record</span>')
            if n in sa:
                a = ''.join(f'<h3>Stage A diplomatic text <span class="fn">{E(tag)}{(" \u00b7 " + E(lab)) if lab else ""}</span></h3>'
                            f'<pre class="transcription stagea-text">{E(t)}</pre>' for tag, lab, t in sa[n])
            elif mdfull:
                a = f'<p class="miss">Stage A: no diplomatic JSON for this entry; see the full {E(c)}_stageA.md at the top of the page.</p>'
            else:
                a = '<p class="miss">MISSING: no Stage A diplomatic text for this entry.</p>'
            b = ''.join(_record_card(fn, j, body, E, f'r-{en}-{i}') for i, (fn, j, body) in enumerate(recs))
            if not b and n in titles:
                b = '<p class="src">Title row: its content is described in the Page metadata card.</p>'
            elif not b: b = '<p class="miss">MISSING: no Stage B record for this entry.</p>'
            figs = ''
            if n in titles and not recs:
                for src in scr.get(n, []) or titles[n]:
                    hit = pub.get(os.path.abspath(src)) or pub.get(os.path.splitext(os.path.basename(src))[0])
                    figs += (f'<figure class="crop"><img src="../segmentation/{E(hit[0])}?v={hit[1]}" alt="{E(os.path.basename(src))}" loading="lazy"></figure>' if hit
                             else f'<p class="miss">crop not found: {E(os.path.basename(src))}</p>')
                a = figs + a
            secs.append(f'<details class="ent" id="{E(en)}"><summary>{summ}</summary><div class="body">{a}{b}</div></details>\n')
        top = (f'<h2>Stage A summary ({E(c)}_stageA.md, fallback)</h2><pre class="transcription stagea-text">{E(mdfull)}</pre>\n' if mdfull else '')
        page = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">' + NOCACHE + '<script>' + CHIP_JS + '</script>\n'
            f'<title>Row {E(r["id"])} {E(c)} \u2013 {"draft extraction" if xs.startswith("draft") else "extraction"}</title><style>{PAGE_CSS}{CHIP_CSS}{TR_CSS}'
            'details.ent{border:1px solid #d5dce8;border-radius:6px;margin:0 0 8px;background:#fff}'
            'details.ent summary{cursor:pointer;padding:8px 12px;font-size:15px;background:#f5f7fb;border-radius:6px}'
            'details.ent[open] summary{border-bottom:1px solid #d5dce8;border-radius:6px 6px 0 0}'
            'details.ent .body{padding:4px 12px 10px}.miss{color:#d55e00;font-weight:600;font-size:13px}'
            '#tg{margin:0 0 10px;padding:4px 12px;cursor:pointer}figure.crop{margin:8px 0}figure.crop img{max-width:100%;height:auto;display:block;border:1px solid #ddd}' + KV_CSS + '</style></head><body>\n'
            '<p><a href="../index.html">&larr; Dashboard</a></p>\n'
            f'<h1>Row {E(r["id"])}: {E(r["name"])} <span class="fn">({E(c)})</span> \u2013 Record extraction: {E(r["extraction"]["status"])}</h1>\n'
            + _sticky(r, 'Extraction', r["extraction"]["status"], E,
                btn=('' if not (xs.startswith('draft') and EXTRACTION_APPROVE_ENABLED and nb) else _lock_note(nbl, nb, 'Stage B records', E) if nbl else
                     ' ' + _approve_btn(r, 'extraction', f"Approve the extraction of row {r['id']} ({c})? This locks all {nb} Stage B record file(s) in stageB/{c}/.")),
                line2=(f'<b>Name</b> {E(r["name"])}{(" &times; " + E(r["spouse"])) if r.get("spouse") else ""} &nbsp; '
                       f'<b>Date</b> {E(r.get("date"))} &nbsp; <b>Image</b> {_img_link(r, E)} &nbsp; '
                       f'<a href="{E(r["url"])}" target="_blank" rel="noopener">Matricula page</a> &nbsp;|&nbsp; '
                       f'<a href="{E(booku)}" target="_blank" rel="noopener">Book title page</a>'),
                below=TOGGLE_JS) +
            _meta_cards(c, r, E) +
            f'<h2>Entries ({len(secs)}; {nrec} {"draft " if xs.startswith("draft") else ""}Stage B record(s))</h2>\n' + top +
            (''.join(secs) or '<p>(no entries found)</p>\n') +
            f'<p class="src">Generated {E(datetime.datetime.now().astimezone().isoformat(timespec="seconds"))} by status.py</p>\n'
            + KV_JS + OPEN_JS +
            '</body></html>\n')
        made.append(_write_page(xd, c, page, 'extraction', r)); bundles.append(f'{c}.bundle.js')
    for p in glob.glob(os.path.join(xd, '*.html')):          # drop pages for rows no longer Draft/Approved
        if os.path.basename(p) not in made: os.remove(p)
    _drop_stale_bundles(xd, bundles)
    fd, tmp = tempfile.mkstemp(dir=xd); os.write(fd, ''.join(m + '\n' for m in made + bundles).encode()); os.close(fd)
    os.chmod(tmp, 0o644); os.replace(tmp, os.path.join(xd, 'list.txt'))   # file list pulled by Greyhawk refresh.sh
    return made

def _stageb_records(code):
    """{entry_no: [(filename, json, pretty_body), ...]} from stageB/<code>/*.json."""
    sb = {}
    for p in sorted(glob.glob(f'{W}/stageB/{code}/*.json'), key=lambda q: (_enum(os.path.basename(q)), q)):
        fn = os.path.basename(p)
        if _is_meta(p) or '.bak' in fn: continue                 # page metadata is not a record
        try: j = json.load(open(p, encoding='utf-8')); body = json.dumps(j, indent=2, ensure_ascii=False)
        except Exception as ex: j = {}; body = f'unreadable: {ex}'
        n = _enum(fn)
        if n >= 10**6 and str(j.get('entry', '')).isdigit(): n = int(j['entry'])
        sb.setdefault(n, []).append((fn, j, body))
    return sb

TOGGLE_JS = ('<button id="tg" onclick="var d=document.querySelectorAll(\'details.ent\'),o=![].some.call(d,function(x){return x.open});'
             '[].forEach.call(d,function(x){x.open=o})">Expand / collapse all</button>\n')
OPEN_JS = ('<script id="openjs">(function(){var m=location.search.match(/[?&]open=([^&]+)/),k=m?decodeURIComponent(m[1]):location.hash.slice(1);'
           'var s=document.getElementById("stk"),f=function(){if(s)document.documentElement.style.setProperty("--stkh",s.offsetHeight+"px");};f();addEventListener("resize",f);'
           'if(k){var e=document.getElementById(k);if(e){e.open=true;requestAnimationFrame(function(){f();e.scrollIntoView({block:"start"});});}}})();</script>\n')
DETAILS_CSS = ('details.ent{border:1px solid #d5dce8;border-radius:6px;margin:0 0 8px;background:#fff}'
               'details.ent summary{cursor:pointer;padding:8px 12px;font-size:15px;background:#f5f7fb;border-radius:6px}'
               'details.ent[open] summary{border-bottom:1px solid #d5dce8;border-radius:6px 6px 0 0}'
               'details.ent .body{padding:4px 12px 10px}.miss{color:#d55e00;font-weight:600;font-size:13px}#tg{margin:0 0 10px;padding:4px 12px;cursor:pointer}')

def _sa_summary(code, n):
    """(date, name) from Stage A JSON fields for entry n, if present."""
    for p in glob.glob(os.path.join(_sa(code), f'*_e{n}.diplomatic.json')):
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception: continue
        dt = next((str(j[k]) for k in ('date_iso', 'event_date_iso', 'date', 'event_date') if j.get(k)), '')
        nm = next((str(j[k]) for k in ('name', 'principal_name', 'child_name', 'deceased_name', 'key_label') if j.get(k)), '')
        if dt or nm: return dt, nm
    return '', ''

# ---- Transcription pages: out/transcription/<code>.html for every row whose transcription status is Approved or Draft ----

# ---- Stage A parts, [?] confirmation rendering, per-entry lock + feedback state (transcription pages) ----
TOKRE = _re.compile(r'([^\s\[\]|()]+)\[\?\]')          # must match approve_server.TOKRE

def _stagea_parts(code):
    """{entry_no: [(tag, label, entry_id, locked, [(field, text), ...]), ...]} from the per-entry Stage A JSON files."""
    d = _sa(code); out = {}
    for p in sorted(glob.glob(os.path.join(d, '*.diplomatic.json')), key=lambda q: (_enum(os.path.basename(q)), q)):
        eid = os.path.basename(p)[:-len('.diplomatic.json')]
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception as ex: out.setdefault(_enum(eid), []).append((eid, '', eid, False, [('x', f'(unreadable: {ex})')])); continue
        lab = ', '.join(str(x) for x in (j.get('segment_label'), j.get('entry_kind')) if x)
        f = [('diplomatic_text', str(j.get('diplomatic_text') or ''))]
        if j.get('diplomatic_margin'): f.append(('diplomatic_margin', str(j['diplomatic_margin'])))
        out.setdefault(_enum(eid), []).append((_etag(eid), lab, eid, str(j.get('status', '')).lower() in _LOCKED, f))
    return out

def _confirmed(code):
    try: v = json.load(open(os.path.join(_sa(code), '_confirmed_readings.json'), encoding='utf-8'))
    except Exception: return []
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

def _render_tokens(text, eid, field, conf, E, regained, locked=False):
    """HTML for one Stage A text field on the transcription page.
    - <word>[?]      one-click ✓ confirm (unchanged; a confirmed token whose [?] came back is shown without it, see `regained`)
    - <word>[?|a|b]  one tap button per option (choose_reading)
    - any word       double-click / double-tap / long-press to edit it inline (edit_reading)
    - an active choice/edit (readings.py record) shows as a blue ✓ chip with Undo, never as the old token again
    Locked/approved entries are read-only: no picker, no editing (the ✓ confirm keeps its existing behaviour)."""
    # ✓ confirm records only: legacy direct-edit records ('before' field, e.g. by voice) are NOT confirms of their token
    mine = [x for x in conf if not x.get('type') and not RD.is_legacy_record(x) and x.get('entry_id') == eid and x.get('field', 'diplomatic_text') == field]
    chs = [x for x in conf if x.get('type') in ('choice', 'edit') and not x.get('undone') and x.get('entry_id') == eid and x.get('field', 'diplomatic_text') == field]
    chs += [l for l in map(RD.legacy_edit, conf) if l and l['entry_id'] == eid and (l['field'] == field or   # column-named legacy edits
            (field == 'diplomatic_text' and not l['field'].startswith('diplomatic_')))]                   # show on the main text
    toks = RD.tokens(text); places = []
    def chip(c):
        t = str(c.get('time', ''))[11:16]; verb = 'Chose' if c['type'] == 'choice' else 'Saved'
        if c.get('legacy'):      # read-only note: no Undo for direct edits recorded outside the dashboard
            how = str(c.get('by', '')).replace('Stephen', '').strip() or 'hand'
            return (f'<span class="tq chosen" title="Edited by Stephen ({E(how)}) {E(c.get("time", ""))}; was {E(c.get("token", ""))}; read-only here">{E(c["new"])}</span>'
                    f'<span class="chz legacy">\u270e Edited by {E(how)} \u201c{E(c["new"])}\u201d at {E(t)}</span>')
        und = ('' if locked else f'<button type="button" class="undo" onclick="oprUndo(this)" title="Undo: put the old reading back">Undo</button>')
        return (f'<span class="tq chosen" title="{E(verb)} by Stephen {E(c.get("time", ""))}; was {E(c.get("token", ""))}">{E(c["new"])}</span>'
                f'<span class="chz" data-id="{E(c.get("change_id", ""))}">\u2713 {verb} \u201c{E(c["new"])}\u201d at {E(t)}{und}</span>')
    for c in chs:
        old, new, cb = c.get('token', ''), c.get('new', ''), c.get('context_before', '')
        if c.get('legacy'):
            ho = RD.ctx_hits(text, old, cb)
            if len(ho) == 1: places.append((ho[0], ho[0] + len(old), chip(c))); continue   # old text back (re-apply pending)
            hn = RD.ctx_hits(text, new, cb)
            if len(hn) == 1: places.append((hn[0], hn[0] + len(new), chip(c)))
            continue
        k = RD.locate_lax(text, old, c.get('occurrence'), cb) if old else None
        if k is not None: places.append((k, k + len(old), chip(c))); continue      # source regained the old token (re-apply pending)
        t12 = RD._tail(cb); hits = [m for m in range(len(text)) if new and text.startswith(new, m) and (not t12 or RD._tail(text[:m]).endswith(t12))]
        if len(hits) == 1 or (hits and not t12): places.append((hits[0], hits[0] + len(new), chip(c)))
    items = list(places); wcnt = {}; qcnt = {}
    def attrs(tok, occ, s0): return f' data-e="{E(eid)}" data-f="{E(field)}" data-t="{E(tok)}" data-o="{occ}" data-c="{E(text[:s0][-20:])}"'
    for s0, e0, tok in toks:
        wcnt[tok] = wcnt.get(tok, 0) + 1; occ = wcnt[tok]
        m = RD.TOKRE.fullmatch(tok)
        if m: qcnt[m.group(1)] = qcnt.get(m.group(1), 0) + 1
        if any(a < e0 and s0 < b for a, b, _ in places): continue
        am = RD.ALTRE.fullmatch(tok)
        if am:
            if locked:
                items.append((s0, e0, f'{E(tok)}<span class="lockn" title="This entry is approved (locked); readings are read-only">entry approved \u2014 locked</span>')); continue
            opts = [am.group(1)] + am.group(2).split('|')[1:]
            btns = ''.join(f'<button type="button" class="opt" data-i="{i}" onclick="oprChoose(this)" title="Use \u201c{E(o)}\u201d (writes it into Stage A)">{E(o)}</button>' for i, o in enumerate(opts))
            items.append((s0, e0, f'<span class="alt"{attrs(tok, occ, s0)}><span class="tq altq w"{attrs(tok, occ, s0)}>{E(am.group(1))}<span class="qm">[?{E(am.group(2))}]</span></span>'
                                  f'<span class="altopts" role="group" aria-label="Choose the reading">{btns}</span></span>')); continue
        if m:
            base = m.group(1); qocc = qcnt[base]; before = text[:s0]
            hit = next((x for x in mine if x.get('token') == base and (before.endswith(str(x.get('context_before', ''))[-12:]) if x.get('context_before') else x.get('occurrence') == qocc)), None)
            if hit:
                regained.append({'entry_id': eid, 'field': field, 'token': base, 'occurrence': qocc})
                items.append((s0, e0, f'<span class="tq regained" title="Confirmed by Stephen {E(hit.get("time", ""))}; the source regained [?] and it is hidden here">{E(base)}</span>')); continue
            items.append((s0, e0, f'<span class="tq{"" if locked else " w"}"{"" if locked else attrs(tok, occ, s0)}>{E(base)}<span class="qm">[?]</span></span><button class="ck" onclick="oprConfirm(this)" '
                                  f'data-e="{E(eid)}" data-f="{E(field)}" data-t="{E(base)}" data-o="{qocc}" data-c="{E(before[-20:])}" title="Confirm this reading (one click)">&#10003;</button>')); continue
        items.append((s0, e0, E(tok) if locked else f'<span class="w"{attrs(tok, occ, s0)}>{E(tok)}</span>'))
    items.sort(key=lambda x: x[0]); out = []; last = 0
    for s0, e0, h in items:
        if s0 < last: continue
        out.append(E(text[last:s0])); out.append(h); last = e0
    out.append(E(text[last:]))
    return ''.join(out)

ALT_CSS = ('.altq .qm{color:#7a4a00}.altopts{display:inline-flex;flex-wrap:wrap;gap:4px;margin:0 4px;vertical-align:middle}'
           '.opt,.undo,.wcancel{font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-weight:600;cursor:pointer;box-sizing:border-box}'
           '.opt{font-size:13px;padding:2px 10px;background:#fff;color:#222;border:1.5px solid #555;border-radius:4px}'
           '.opt:hover{background:#eee}.opt:focus-visible,.undo:focus-visible,.wcancel:focus-visible{outline:3px solid #0072b2;outline-offset:1px}.opt:disabled,.undo:disabled{opacity:.6;cursor:wait}'
           '.tq.chosen{background:#e8f1fa;border-radius:3px}'
           '.chz{display:inline-flex;flex-wrap:wrap;align-items:center;gap:6px;margin:0 4px;padding:1px 4px 1px 9px;border-radius:12px;background:#e8f1fa;color:#0b4f8a;'
           'border:1px solid #0072b2;font:600 12px -apple-system,Segoe UI,Roboto,sans-serif;vertical-align:middle;white-space:normal}'
           '.undo{font-size:12px;padding:1px 8px;background:#fff;color:#0b4f8a;border:1px solid #0072b2;border-radius:10px}'
           '.lockn{font:italic 12px -apple-system,Segoe UI,Roboto,sans-serif;color:#555;margin:0 4px;white-space:nowrap}'
           '.w{border-radius:2px}.w:hover{background:#f0f0f0}.w.pressing{background:#e8f1fa;outline:2px solid #0072b2}'
           '.wedbox{display:inline-flex;flex-wrap:wrap;align-items:center;gap:4px;vertical-align:middle}'
           '.wedit{font-family:inherit;font-size:1em;padding:1px 6px;border:2px solid #0072b2;border-radius:4px;background:#fff;color:#000;box-sizing:border-box}'
           '.wcancel{font-size:12px;padding:1px 8px;background:#fff;color:#333;border:1px solid #888;border-radius:10px}'
           '@media (pointer:coarse){.opt,.undo,.wcancel{min-height:44px;min-width:44px;font-size:15px;padding:4px 12px}.altopts{gap:6px;margin:4px}'
           '.chz{min-height:44px;font-size:14px}.wedit{min-height:44px;font-size:16px}'
           '.w,.tq{-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;touch-action:manipulation}}')

def _feedback(code):
    """Tolerant reader of stageA/<code>/_feedback_status.json -> {entry_id: {state, oldest_pending, updated_at}}."""
    try: fb = json.load(open(os.path.join(_sa(code), '_feedback_status.json'), encoding='utf-8'))
    except Exception: return {}
    out = {}
    for eid, v in (fb.items() if isinstance(fb, dict) else []):
        if isinstance(v, str): v = {'state': v}
        if not isinstance(v, dict): continue
        items = [i for i in (v.get('items') or []) if isinstance(i, dict)]
        states = [str(i.get('state', 'pending')).lower() for i in items] or [str(v.get('state', 'pending')).lower()]
        st = 'processing' if 'processing' in states else 'pending' if 'pending' in states else 'done' if all(x == 'done' for x in states) else states[0]
        pend = [str(i.get('updated_at') or v.get('updated_at') or '') for i in items if str(i.get('state', 'pending')).lower() == 'pending'] or \
               ([str(v.get('updated_at') or '')] if not items and st == 'pending' else [])
        ups = [str(i.get('updated_at') or '') for i in items if i.get('updated_at')] + ([str(v['updated_at'])] if v.get('updated_at') else [])
        out[eid] = {'state': st, 'oldest_pending': min(pend) if pend else None, 'updated_at': max(ups) if ups else None}
    return out

ROW_JS = ' '.join(l.strip() for l in r"""
function oprPost(btn,payload,busy,onOk,errEl){
 if(!btn||btn.disabled||window.oprBusy)return;window.oprBusy=true;var lbl=btn.innerHTML;btn.disabled=true;if(busy)btn.textContent=busy;
 if(errEl){errEl.textContent='';}
 function fail(t){window.oprBusy=false;btn.disabled=false;btn.innerHTML=lbl;if(errEl){errEl.textContent='\u2716 '+t;errEl.style.color='#d55e00';}}
 fetch(__URL__,{method:'POST',headers:{'Content-Type':'application/json','X-OPR-Approve':'1'},body:JSON.stringify(payload)})
 .then(function(x){if(window.oprAuth&&window.oprAuth.fail(x)){var go=window.oprAuth.login();return {ok:false,_http:401,error:go?'login required, opening the login page…':'login required, please log in again'};}return x.json().then(function(j){j._http=x.status;return j;},function(){return {ok:false,error:'HTTP '+x.status,_http:x.status};});})
 .then(function(j){if(!j.ok){fail('Not done ('+(j._http||'?')+'): '+j.error);return;}window.oprBusy=false;onOk(j);})
 .catch(function(e){fail('Could not reach the approve service: '+e);});}
function oprErr(el){var e=el.parentNode.querySelector('.ckerr');if(!e){e=document.createElement('span');e.className='ckerr';el.parentNode.insertBefore(e,el.nextSibling);}return e;}
function oprConfirm(b){var d=b.dataset;oprPost(b,{code:__CODE__,action:'confirm_reading',entry_id:d.e,field:d.f,token:d.t,occurrence:+d.o,context:d.c},'\u2026',
 function(j){var t=b.previousSibling;if(t&&t.classList&&t.classList.contains('tq')){var q=t.querySelector('.qm');if(q)q.remove();t.classList.add('confirmed');}b.remove();},oprErr(b));}
function oprEsc(t){return String(t==null?'':t).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function oprFrag(h){var s=document.createElement('span');s.innerHTML=h;return [].slice.call(s.childNodes);}
function oprChip(nw,id,tm,tok,verb){return '<span class="tq chosen" title="'+verb+' by Stephen '+oprEsc(tm)+'; was '+oprEsc(tok)+'">'+oprEsc(nw)+'</span><span class="chz" data-id="'+oprEsc(id)+'">\u2713 '+verb+' \u201c'+oprEsc(nw)+'\u201d at '+oprEsc(String(tm||'').slice(11,16))+'<button type="button" class="undo" onclick="oprUndo(this)" title="Undo: put the old reading back">Undo</button></span>';}
function oprWA(j,t){return ' data-e="'+oprEsc(j.entry_id)+'" data-f="'+oprEsc(j.field)+'" data-t="'+oprEsc(t)+'" data-o="'+oprEsc(j.occurrence||1)+'" data-c="'+oprEsc(j.context||'')+'"';}
function oprTokHtml(j){var t=String(j.token||''),o=j.options,m;
 if(o&&(m=t.match(/^(.*?)\[\?(\|.*)\]$/))){var b='';o.forEach(function(x,i){b+='<button type="button" class="opt" data-i="'+i+'" onclick="oprChoose(this)" title="Use \u201c'+oprEsc(x)+'\u201d (writes it into Stage A)">'+oprEsc(x)+'</button>';});
  return '<span class="alt"'+oprWA(j,t)+'><span class="tq altq w"'+oprWA(j,t)+'>'+oprEsc(m[1])+'<span class="qm">[?'+oprEsc(m[2])+']</span></span><span class="altopts" role="group" aria-label="Choose the reading">'+b+'</span></span>';}
 if((m=t.match(/^(.*)\[\?\]$/))&&j.confirm_occurrence)return '<span class="tq w"'+oprWA(j,t)+'>'+oprEsc(m[1])+'<span class="qm">[?]</span></span><button class="ck" onclick="oprConfirm(this)" data-e="'+oprEsc(j.entry_id)+'" data-f="'+oprEsc(j.field)+'" data-t="'+oprEsc(m[1])+'" data-o="'+j.confirm_occurrence+'" data-c="'+oprEsc(j.context||'')+'" title="Confirm this reading (one click)">&#10003;</button>';
 return '<span class="w"'+oprWA(j,t)+'>'+oprEsc(t)+'</span>';}
function oprChoose(b){var w=b.closest('.alt'),d=w.dataset;oprPost(b,{code:__CODE__,action:'choose_reading',entry_id:d.e,field:d.f,token:d.t,occurrence:+d.o,context:d.c,pick:+b.dataset.i},'\u2026',
 function(j){var n=oprFrag(oprChip(j.new,j.change_id,j.time,j.token,'Chose'));var e=w.nextSibling;if(e&&e.classList&&e.classList.contains('ckerr'))e.remove();w.replaceWith.apply(w,n);},oprErr(w));}
function oprUndo(b){var z=b.closest('.chz');oprPost(b,{code:__CODE__,action:'undo_reading',change_id:z.dataset.id},'\u2026',
 function(j){var p=z.previousSibling,n=oprFrag(oprTokHtml(j));if(p&&p.classList&&p.classList.contains('chosen'))p.remove();var e=z.nextSibling;if(e&&e.classList&&e.classList.contains('ckerr'))e.remove();z.replaceWith.apply(z,n);},oprErr(z));}
(function(){if(window.oprEdInit)return;window.oprEdInit=1;var ED=null,TP=null,LT={t:0,el:null};
 function tokEl(t){var e=t&&t.closest?t.closest('.w'):null;return e&&!e.classList.contains('confirmed')&&!e.closest('.wedbox')?e:null;}
 function done(){ED=null;window.oprEditing=false;}
 function close(){if(!ED)return;var x=ED;x.cancelled=true;x.box.remove();x.host.style.display='';if(x.ck)x.ck.style.display='';done();}
 function fail(x,t){x.saving=false;x.inp.disabled=false;x.err.textContent='\u2716 '+t;x.err.style.color='#d55e00';x.inp.focus();}
 function save(){if(!ED||ED.saving)return;var x=ED,v=x.inp.value;if(v===x.old){close();return;}
  if(!v.length||/\s/.test(v)){x.err.textContent='\u2716 One word only: not empty, no spaces';x.err.style.color='#d55e00';setTimeout(function(){if(ED===x)x.inp.focus();},0);return;}
  if(window.oprBusy){x.err.textContent='\u2716 Another save is running; try again in a moment';x.err.style.color='#d55e00';return;}
  x.saving=true;x.inp.disabled=true;x.err.textContent='Saving\u2026';x.err.style.color='#333';window.oprBusy=true;var d=x.el.dataset;
  fetch(__URL__,{method:'POST',headers:{'Content-Type':'application/json','X-OPR-Approve':'1'},body:JSON.stringify({code:__CODE__,action:'edit_reading',entry_id:d.e,field:d.f,token:x.old,occurrence:+d.o,context:d.c,value:v})})
  .then(function(r){if(window.oprAuth&&window.oprAuth.fail(r)){var go=window.oprAuth.login();return {ok:false,_http:401,error:go?'login required, opening the login page\u2026':'login required, please log in again'};}return r.json().then(function(j){j._http=r.status;return j;},function(){return {ok:false,error:'HTTP '+r.status,_http:r.status};});})
  .then(function(j){window.oprBusy=false;if(!j.ok){fail(x,'Not saved ('+(j._http||'?')+'): '+j.error);return;}
   var n=oprFrag(oprChip(j.new,j.change_id,j.time,j.token,'Saved'));x.box.replaceWith.apply(x.box,n);x.host.remove();if(x.ck)x.ck.remove();if(ED===x)done();})
  .catch(function(e){window.oprBusy=false;fail(x,'Could not reach the approve service: '+e);});}
 function open(el){if(ED||window.oprBusy||!el)return;var host=el.closest('.alt')||el,ck=null;
  if(host===el&&el.nextSibling&&el.nextSibling.classList&&el.nextSibling.classList.contains('ck'))ck=el.nextSibling;
  var old=el.dataset.t,box=document.createElement('span'),inp=document.createElement('input'),cb=document.createElement('button'),err=document.createElement('span');
  box.className='wedbox';inp.type='text';inp.className='wedit';inp.value=old;inp.size=Math.max(4,old.length+2);
  ['autocapitalize','autocorrect','autocomplete'].forEach(function(a){inp.setAttribute(a,'off');});inp.setAttribute('spellcheck','false');inp.setAttribute('enterkeyhint','done');inp.setAttribute('aria-label','Edit this word (Enter saves, Esc cancels)');
  cb.type='button';cb.className='wcancel';cb.textContent='Cancel';err.className='ckerr';err.setAttribute('role','alert');
  box.appendChild(inp);box.appendChild(cb);box.appendChild(err);var after=ck||host;after.parentNode.insertBefore(box,after.nextSibling);host.style.display='none';if(ck)ck.style.display='none';
  ED={el:el,host:host,ck:ck,box:box,inp:inp,err:err,old:old,saving:false,cancelled:false};window.oprEditing=true;
  try{var sel=window.getSelection();if(sel)sel.removeAllRanges();}catch(e){}
  cb.addEventListener('mousedown',function(ev){ev.preventDefault();});cb.addEventListener('touchstart',function(){if(ED)ED.cancelling=true;},{passive:true});cb.addEventListener('click',function(){close();});
  inp.addEventListener('keydown',function(ev){if(ev.key==='Enter'){ev.preventDefault();save();}else if(ev.key==='Escape'||ev.key==='Esc'){ev.preventDefault();close();}});
  inp.addEventListener('blur',function(){var x=ED;if(!x||x.saving||x.cancelled||x.cancelling)return;setTimeout(function(){if(ED===x&&!x.saving&&!x.cancelled&&!x.cancelling&&document.activeElement!==x.inp)save();},120);});
  inp.focus();try{inp.setSelectionRange(0,inp.value.length);}catch(e){}}
 window.oprEditOpen=open;
 document.addEventListener('dblclick',function(ev){var el=tokEl(ev.target);if(!el)return;ev.preventDefault();open(el);});
 document.addEventListener('touchstart',function(ev){var el=tokEl(ev.target);if(!el||ev.touches.length!==1){TP=null;return;}var t=ev.touches[0];TP={el:el,x:t.clientX,y:t.clientY,t0:Date.now(),moved:false};TP.tm=setTimeout(function(){if(TP&&!TP.moved)TP.el.classList.add('pressing');},450);},{passive:true});
 document.addEventListener('touchmove',function(ev){if(!TP)return;var t=ev.touches[0];if(Math.abs(t.clientX-TP.x)>10||Math.abs(t.clientY-TP.y)>10){TP.moved=true;clearTimeout(TP.tm);TP.el.classList.remove('pressing');}},{passive:true});
 document.addEventListener('touchend',function(ev){if(!TP)return;var p=TP;TP=null;clearTimeout(p.tm);p.el.classList.remove('pressing');if(p.moved)return;var now=Date.now();
  if(now-p.t0>=450){ev.preventDefault();LT={t:0,el:null};open(p.el);return;}
  if(LT.el===p.el&&now-LT.t<400){ev.preventDefault();LT={t:0,el:null};open(p.el);return;}LT={t:now,el:p.el};},{passive:false});
 document.addEventListener('touchcancel',function(){if(TP){clearTimeout(TP.tm);TP.el.classList.remove('pressing');TP=null;}},{passive:true});
 document.addEventListener('contextmenu',function(ev){if(tokEl(ev.target)&&window.matchMedia&&matchMedia('(pointer:coarse)').matches)ev.preventDefault();});})();
function oprEntryApprove(ev,b){ev.preventDefault();ev.stopPropagation();oprPost(b,{code:__CODE__,action:(b.dataset.a||'approve_transcription_entry'),entry_id:b.dataset.e},'Approving\u2026',
 function(j){var c=document.createElement('span');c.className='entok';c.textContent='Approved'+(String(j.locked_by||'').match(/T(\d\d:\d\d)/)?' '+j.locked_by.match(/T(\d\d:\d\d)/)[1]:'');
  b.replaceWith(c);if(j.row_approved){var ch=document.querySelector('#stk .chip.segchip');if(ch){ch.style.cssText='';ch.textContent='Approved';}}},
 oprErr(b));}
window.oprOnRow=function(c){var fb=c.feedback||{},en=c.entries||{},now=Date.now();
 [].forEach.call(document.querySelectorAll('.fbchip'),function(el){var f=fb[el.dataset.e],t='',cl='fbchip';
  if(f){var st=f.state,op=f.oldest_pending?Date.parse(f.oldest_pending):0,up=f.updated_at?Date.parse(f.updated_at):0;
   if(st=='pending'&&op&&now-op>1800000){t='Waiting on transcriber';cl+=' fbwait';}
   else if(st=='pending'||st=='processing'){t='Transcriber updating\u2026';cl+=' fbupd';}
   else if(st=='done'&&up&&now-up<60000){t='Updated';cl+=' fbdone';}}
  el.textContent=t;el.className=cl;el.style.display=t?'':'none';});
 [].forEach.call(document.querySelectorAll('button.entapv'),function(b){if(en[b.dataset.e]=='locked'){var s=document.createElement('span');s.className='entok';s.textContent='Approved';b.replaceWith(s);}});};
""".split('\n'))

def write_transcription_pages(rows, man=None):
    td = os.path.join(OUT, 'transcription'); os.makedirs(td, exist_ok=True); made = []; bundles = []
    E = lambda t: _html.escape(str(t if t is not None else ''), quote=True)
    man = man if man is not None else load_manifest()
    imgs = {x['code']: x['image_id'] for x in json.load(open(os.path.join(D, 'records.json')))['records']}
    for r in rows:
        st = str(r['transcription']['status']); sl = st.lower()
        na, nal = _json_field_counts(glob.glob(os.path.join(_sa(r['code']), '*.diplomatic.json')), 'status')
        if not (sl.startswith('approved') or sl.startswith('draft')): continue
        c = r['code']; r['transcription']['link'] = f'transcription/{c}.html'
        sa = _stagea_parts(c); sb = _stageb_records(c); mdfull = ''; scr = _stagea_crops(c); pub = _PUB.get(c, {})
        conf = _confirmed(c); regained = []; draft = sl.startswith('draft')
        ents = {eid: ('locked' if lk else 'soft') for parts in sa.values() for _, _, eid, lk, _ in parts}
        r['transcription']['entries'] = ents; r['transcription']['feedback'] = _feedback(c)
        if draft and ents: r['transcription']['progress'] = f"{sum(v == 'locked' for v in ents.values())}/{len(ents)}"
        if not sa:
            md = _sa_md(c) or os.path.join(_sa(c), f'{c}_stageA.md')
            mdfull = open(md, encoding='utf-8').read() if os.path.isfile(md) else '(no Stage A transcription found)'
        klab = {}
        for e in man.get(imgs.get(c), []):
            k = e.get('key_label')
            if k and str(k).strip() and str(k) != 'None': klab.setdefault(_enum(str(e.get('entry_id', ''))), str(k).strip())
        secs = []
        for n in sorted(sa):
            en = f'e{n}' if n < 10**6 else 'e?'
            dt, nm = _sb_summary(sb[n][0][1]) if sb.get(n) else ('', '')
            if not (dt or nm) and n in klab: nm = klab[n]
            if not (dt or nm): dt, nm = _sa_summary(c, n)
            lab = ', '.join(x[1] for x in sa[n] if x[1])
            acts = ''
            for tag, _, eid, lk, _ in sa[n]:
                side = (' ' + tag.split('_')[0]) if len(sa[n]) > 1 else ''
                acts += f'<span class="fbchip" data-e="{E(eid)}" style="display:none"></span>'
                if lk: acts += f'<span class="entok" title="{E(eid)}">Approved{E(side)}</span>'
                elif draft and TRANSCRIPTION_APPROVE_ENABLED:
                    acts += (f'<button class="entapv" data-e="{E(eid)}" onclick="oprEntryApprove(event,this)" '
                             f'title="Approve only this entry ({E(eid)}); locks it immediately">Approve entry{E(side)}</button>')
            summ0 = (f'<b>{E(en)}</b>' + (f' \u00b7 {E(dt)}' if dt else '') + (f' \u00b7 {E(nm)}' if nm else '')
                    + (f' <span class="fn">({E(lab)})</span>' if lab and not (dt or nm) else ''))
            summ = summ0 + f'<span class="entact">{acts}</span>'
            figs = ''
            for src in sorted(scr.get(n, []), key=lambda x: (0 if '_L_' in os.path.basename(x) else 1 if '_R_' in os.path.basename(x) else 0, x)):
                hit = pub.get(os.path.abspath(src)) or pub.get(os.path.splitext(os.path.basename(src))[0])
                figs += (f'<figure class="crop"><img src="../segmentation/{E(hit[0])}?v={hit[1]}" alt="{E(os.path.basename(src))}" loading="lazy">'
                         f'<figcaption class="fn">{E(os.path.basename(hit[0]))}</figcaption></figure>' if hit else
                         f'<p class="miss">crop not found: {E(os.path.basename(src))}</p>')
            if not scr.get(n): figs = '<p class="miss">crop not found (no crop referenced by Stage A)</p>'
            body = figs + ''.join(f'<h3>Stage A diplomatic text <span class="fn">{E(tag)}{(" \u00b7 " + E(l)) if l else ""}</span></h3>'
                           + ''.join((f'<div class="src">margin</div>' if fld == 'diplomatic_margin' else '') +
                                     f'<pre class="transcription stagea-text">{_render_tokens(t, eid, fld, conf, E, regained, lk)}</pre>' for fld, t in flds)
                           for tag, l, eid, lk, flds in sa[n])
            secs.append(f'<details class="ent" id="{E(en)}"><summary>{summ}</summary><div class="body">{body}</div></details>\n')
        banner = ('<div class="draftban" style="background:#e69f00;border:2px solid #000;border-radius:8px;padding:10px 14px;margin:0 0 14px;'
                  'font-weight:800;font-size:16px;color:#000">\u26a0\ufe0e DRAFT \u2013 this transcription is not yet approved (needs your Approve).</div>\n'
                  if sl.startswith('draft') else '')
        spouse = (' &times; ' + E(r['spouse'])) if r.get('spouse') else ''
        page = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">' + NOCACHE + '<script>' + CHIP_JS + '</script>\n'
            f'<title>Row {E(r["id"])} {E(c)} \u2013 transcription</title><style>{PAGE_CSS}{CHIP_CSS}{DETAILS_CSS}{ALT_CSS}figure.crop{{margin:8px 0}}figure.crop img{{max-width:100%;height:auto;display:block;border:1px solid #ddd}}</style></head><body>\n'
            '<p><a href="../index.html">&larr; Dashboard</a></p>\n'
            f'<h1>Row {E(r["id"])}: {E(r["name"])} <span class="fn">({E(c)})</span> \u2013 Transcription</h1>\n'
            + _sticky(r, 'Transcription', st, E,
                btn=('' if not (TRANSCRIPTION_APPROVE_ENABLED and sl.startswith('draft') and na and nal < na) else
                     ' ' + _approve_btn(r, 'transcription') + (f'<div class="src">{nal} of {na} entries already approved; the row button locks the remaining {na - nal}</div>' if nal else '')),
                line2=(f'<b>Date</b> {E(r.get("date"))}{spouse and " &nbsp; <b>Spouse</b> " + E(r["spouse"])} &nbsp; '
                       f'<b>Image</b> {_img_link(r, E)} &nbsp; <a href="{E(r["url"])}" target="_blank" rel="noopener">Matricula page</a>'),
                below=banner + TOGGLE_JS) +
            f'<h2>Stage A diplomatic text ({len(secs)} entries)</h2>\n' +
            (f'<div class="src">source: {E(c)}_stageA.md (no diplomatic JSON)</div><pre class="transcription stagea-text">{_render_tokens(mdfull, f"{c}_stageA.md", "md", conf, E, regained, sl.startswith("approved"))}</pre>\n' if mdfull else '') +
            ''.join(secs) +
            f'<p class="src">Generated {E(datetime.datetime.now().astimezone().isoformat(timespec="seconds"))} by status.py</p>\n'
            + '<script>' + ROW_JS.replace('__URL__', _api_js()).replace('__CODE__', _J(c)) + '</script>\n'
            + OPEN_JS + '</body></html>\n')
        r['transcription']['regained'] = regained
        made.append(_write_page(td, c, page, 'transcription', r)); bundles.append(f'{c}.bundle.js')
    for p in glob.glob(os.path.join(td, '*.html')):          # drop pages for rows no longer Approved/Draft
        if os.path.basename(p) not in made: os.remove(p)
    _drop_stale_bundles(td, bundles)
    fd, tmp = tempfile.mkstemp(dir=td); os.write(fd, ''.join(m + '\n' for m in made + bundles).encode()); os.close(fd)
    os.chmod(tmp, 0o644); os.replace(tmp, os.path.join(td, 'list.txt'))   # file list pulled by Greyhawk refresh.sh
    return made

# ---- Expansion pages: out/expansion/<code>.html (Draft/Approved rows): crop, Stage A diplomatic text | expanded text ----
EXPANSION_APPROVE_ENABLED = True
_SUPRE = _re.compile(r'\[([^\[\]\n]+)\]')
EXP_CSS = ('.xgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}'
           '.xgrid>div{min-width:0}.xgrid h3{margin:6px 0 4px}'
           '@media (max-width:699px){.xgrid{grid-template-columns:1fr}}'
           'span.sup{background:#e8f1fa;color:#0b4f8a;border-bottom:2px solid #0b4f8a;border-radius:3px;padding:0 1px}'
           '.xkey{display:inline-block;margin:4px 0 10px;font-size:14px}')

def _exp_hl(text, E):
    """Escape the expanded text; supplied [letters/words] get the Okabe-Ito blue 'supplied' style (background + underline,
    so not colour-only). Whole-line section labels ([margin_date]) and [?...] uncertainty markers are left plain."""
    out, cur = [], 0
    for m in _SUPRE.finditer(text):
        inner = m.group(1); ls = text.rfind('\n', 0, m.start()) + 1; le = text.find('\n', m.end()); le = len(text) if le < 0 else le
        if inner.startswith('?') or text[ls:le].strip() == m.group(0) or ('_' in inner and _re.fullmatch(r'[a-z_]+', inner)): continue
        out.append(E(text[cur:m.start()])); out.append(f'<span class="sup" title="supplied by the Expander">[{E(inner)}]</span>'); cur = m.end()
    out.append(E(text[cur:])); return ''.join(out)

def write_expansion_pages(rows):
    td = os.path.join(OUT, 'expansion'); os.makedirs(td, exist_ok=True); made = []; bundles = []
    E = lambda t: _html.escape(str(t if t is not None else ''), quote=True)
    for r in rows:
        st = str(r['expansion']['status']); sl = st.lower()
        if not (sl.startswith('approved') or sl.startswith('draft')): continue
        c = r['code']; r['expansion']['link'] = f'expansion/{c}.html'; draft = sl.startswith('draft')
        xs = {}
        for p in _exp_files(c):
            x = _exp_load(p); xs[x['file_id']] = x
        ents = {k: ('locked' if x['status'] in _LOCKED else 'soft') for k, x in xs.items()}
        r['expansion']['entries'] = ents; nl = sum(v == 'locked' for v in ents.values())
        if draft and ents: r['expansion']['progress'] = f'{nl}/{len(ents)}'
        sa = _stagea_parts(c); scr = _stagea_crops(c); pub = _PUB.get(c, {}); used = set(); secs = []
        for n in sorted(set(sa) | {_enum(k) for k in xs}):
            en = f'e{n}' if n < 10**6 else 'e?'
            parts = sa.get(n) or []
            eids = [eid for _, _, eid, _, _ in parts] or sorted(k for k in xs if _enum(k) == n)
            acts = ''
            for eid in eids:
                x = xs.get(eid)
                if not x: acts += f'<span class="miss" title="{E(eid)}">no expansion yet</span>'; continue
                side = (' ' + _etag(eid).split('_')[0]) if len(eids) > 1 else ''
                if x['status'] in _LOCKED: acts += f'<span class="entok" title="{E(eid)}">Approved{E(side)}</span>'
                elif draft and EXPANSION_APPROVE_ENABLED:
                    acts += (f'<button class="entapv" data-e="{E(eid)}" data-a="approve_expansion_entry" onclick="oprEntryApprove(event,this)" '
                             f'title="Approve only this entry\u2019s expansion ({E(eid)}); locks it immediately">Approve entry{E(side)}</button>')
            lab = ', '.join(x[1] for x in parts if x[1])
            summ = f'<b>{E(en)}</b>' + (f' <span class="fn">({E(lab)})</span>' if lab else '') + f'<span class="entact">{acts}</span>'
            figs = ''
            for src in sorted(scr.get(n, []), key=lambda q: (0 if '_L_' in os.path.basename(q) else 1 if '_R_' in os.path.basename(q) else 0, q)):
                hit = pub.get(os.path.abspath(src)) or pub.get(os.path.splitext(os.path.basename(src))[0])
                figs += (f'<figure class="crop"><img src="../segmentation/{E(hit[0])}?v={hit[1]}" alt="{E(os.path.basename(src))}" loading="lazy">'
                         f'<figcaption class="fn">{E(os.path.basename(hit[0]))}</figcaption></figure>' if hit else
                         f'<p class="miss">crop not found: {E(os.path.basename(src))}</p>')
            if not scr.get(n): figs = '<p class="miss">crop not found (no crop referenced by Stage A)</p>'
            body = figs
            for eid in eids:
                x = xs.get(eid) or {}; used.add(eid)
                p0 = next((q for q in parts if q[2] == eid), None)
                dip = '\n\n'.join(t for _, t in p0[4]) if p0 else (x.get('diplomatic') or '(no Stage A text)')
                exp = x.get('text') or ('(no expanded text in the file)' if x else '(no expansion for this entry yet)')
                if x.get('margin'): exp += '\n\n' + x['margin']
                tag = f' <span class="fn">{E(_etag(eid))}</span>' if len(eids) > 1 else ''
                body += (f'<div class="xgrid"><div><h3>Diplomatic (Stage A){tag}</h3><pre class="transcription stagea-text">{E(dip)}</pre></div>'
                         f'<div><h3>Expanded{tag}</h3><pre class="transcription">{_exp_hl(exp, E)}</pre>'
                         + _tr_block('Deutsch', 'de', x.get('tr_de', ''), E) + _tr_block('English', 'en', x.get('tr_en', ''), E)
                         + (f'<div class="src">{E(x["notes"])}</div>' if x.get('notes') else '') + '</div></div>')
            secs.append(f'<details class="ent" id="{E(en)}"><summary>{summ}</summary><div class="body">{body}</div></details>\n')
        banner = ('<div class="draftban" style="background:#e69f00;border:2px solid #000;border-radius:8px;padding:10px 14px;margin:0 0 14px;'
                  'font-weight:800;font-size:16px;color:#000">\u26a0\ufe0e DRAFT \u2013 this expansion is not yet approved (needs your Approve).</div>\n' if draft else '')
        spouse = (' &times; ' + E(r['spouse'])) if r.get('spouse') else ''
        md = _exp_md(c)
        page = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">' + NOCACHE + '<script>' + CHIP_JS + '</script>\n'
            f'<title>Row {E(r["id"])} {E(c)} \u2013 expansion</title><style>{PAGE_CSS}{CHIP_CSS}{DETAILS_CSS}{EXP_CSS}{TR_CSS}figure.crop{{margin:8px 0}}figure.crop img{{max-width:100%;height:auto;display:block;border:1px solid #ddd}}</style></head><body>\n'
            '<p><a href="../index.html">&larr; Dashboard</a></p>\n'
            f'<h1>Row {E(r["id"])}: {E(r["name"])} <span class="fn">({E(c)})</span> \u2013 Expansion</h1>\n'
            + _sticky(r, 'Expansion', st, E,
                btn=('' if not (EXPANSION_APPROVE_ENABLED and draft and ents and nl < len(ents)) else
                     ' ' + _approve_btn(r, 'approve_expansion') + (f'<div class="src">{nl} of {len(ents)} entries already approved; the row button locks the remaining {len(ents) - nl}</div>' if nl else '')),
                line2=(f'<b>Date</b> {E(r.get("date"))}{spouse and " &nbsp; <b>Spouse</b> " + E(r["spouse"])} &nbsp; '
                       f'<b>Image</b> {_img_link(r, E)} &nbsp; <a href="{E(r["url"])}" target="_blank" rel="noopener">Matricula page</a>'),
                below=banner + TOGGLE_JS) +
            f'<h2>Diplomatic and expanded text ({len(secs)} entries)</h2>\n'
            '<div class="xkey">Key: <span class="sup">[supplied]</span> = letters or words written out by the Expander (not on the page).</div>\n'
            + ''.join(secs) +
            f'<p class="src">Source: stageA_expanded/{E(os.path.basename(_exp_dir(c)))}/ ({len(xs)} entry files{", " + E(os.path.basename(md)) if md else ""}).</p>\n'
            f'<p class="src">Generated {E(datetime.datetime.now().astimezone().isoformat(timespec="seconds"))} by status.py</p>\n'
            + '<script>' + ROW_JS.replace('__URL__', _api_js()).replace('__CODE__', _J(c)) + '</script>\n'
            + OPEN_JS + '</body></html>\n')
        made.append(_write_page(td, c, page, 'expansion', r)); bundles.append(f'{c}.bundle.js')
    for p in glob.glob(os.path.join(td, '*.html')):          # drop pages for rows no longer Approved/Draft
        if os.path.basename(p) not in made: os.remove(p)
    _drop_stale_bundles(td, bundles)
    fd, tmp = tempfile.mkstemp(dir=td); os.write(fd, ''.join(m + '\n' for m in made + bundles).encode()); os.close(fd)
    os.chmod(tmp, 0o644); os.replace(tmp, os.path.join(td, 'list.txt'))
    return made

_PUB = {}   # code -> {abs source path | source stem: ('<code>/<file>.jpg', source mtime)}, filled by write_segmentation_pages

def _stagea_crops(code):
    """{entry_no: [crop source paths in L-then-R order]} referenced by Stage A diplomatic JSON."""
    out = {}
    for p in sorted(glob.glob(os.path.join(_sa(code), '*.diplomatic.json')), key=lambda q: (_enum(os.path.basename(q)), q)):
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception: continue
        srcs = []
        for k in ('crop_path', 'crop_paths', 'crops'):
            v = j.get(k); srcs += [v] if isinstance(v, str) else [x for x in (v or []) if isinstance(x, str)]
        lst = out.setdefault(_enum(j.get('entry_id') or os.path.basename(p)), [])
        lst += [x for x in srcs if x not in lst]
    return out

# ---- Segmentation pages: out/segmentation/<code>.html + downscaled JPG crops in out/segmentation/<code>/ (Approved/Draft rows) ----
SEG_MAX = 1600; SEG_Q = 85
def _seg_key(e):
    face = str(e.get('face') or '').upper(); fo = {'L': 0, 'R': 1}.get(face[:1], 2) if face else 0
    try: n = int(str(e.get('entry', '')).strip())
    except ValueError: n = _enum(str(e.get('entry_id', '')))
    return (fo, n, str(e.get('entry_id', '')))

_SRCMAP = {}   # published jpg (relative to out/segmentation) -> [abs source path, mtime_ns, size]; persisted in .srcmap.json
def _crop_jpg(src, dst):
    """Copy/convert one source crop to a JPEG (long side <= SEG_MAX). Source is only read.
    Re-converts whenever the source file the manifest points to changes (path, mtime or size), e.g. a new _fix file."""
    st = os.stat(src); key = os.path.relpath(dst, os.path.join(OUT, 'segmentation'))
    ident = [os.path.abspath(src), st.st_mtime_ns, st.st_size]
    if os.path.isfile(dst) and _SRCMAP.get(key) == ident: return
    _SRCMAP[key] = ident
    from PIL import Image
    with Image.open(src) as im:
        im.load()
        if im.mode not in ('RGB', 'L'):
            if im.mode in ('RGBA', 'LA', 'P'):
                im = im.convert('RGBA'); bg = Image.new('RGB', im.size, (255, 255, 255)); bg.paste(im, mask=im.split()[-1]); im = bg
            else: im = im.convert('RGB')
        if max(im.size) > SEG_MAX: im.thumbnail((SEG_MAX, SEG_MAX), Image.LANCZOS)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dst), suffix='.jpg'); os.close(fd)
        im.save(tmp, 'JPEG', quality=SEG_Q, optimize=True); os.chmod(tmp, 0o644); os.replace(tmp, dst)

# Segmentation stages (overrides.json "segmentation"); chip style via _kind/CHIP_CSS (Queued for redo + Recut = needs Stephen, Redoing = processing)
SEG_STAGE_COL = {'queued for redo': None, 'redoing': None, 'recut': None}   # stage names only; colours come from CHIP_CSS (k-need / k-proc)
def _stage(sl):
    return next((k for k in SEG_STAGE_COL if sl.startswith(k)), None)

APPROVE_URL = os.environ.get('OPR_APPROVE_URL', 'http://grokbot-box.taileabb91.ts.net/api/approve')   # used ONLY on file:// pages (Greyhawk mirror); tailnet-only (tailscale serve, not Funnel) -> approve_server.py
def _api_js():
    """JS expression for the approve endpoint, resolved at runtime: on http(s) it is relative to the dashboard root
    (detail pages live one level down, so '../api/approve' -> /api/approve on the tailnet, /dashboard/api/approve on
    oldparishrecords.com); on file:// the absolute tailnet URL is used."""
    return '(location.protocol==="file:"?' + _J(APPROVE_URL) + ':new URL("../api/approve",location.href).href)'

def _J(v):
    """JSON literal safe inside an inline <script> (no HTML escaping there - entities are not decoded in scripts)."""
    return json.dumps(v).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')

TRANSCRIPTION_APPROVE_ENABLED = True
RECUT_ENABLED = True                       # 'Recut with latest algorithm' on Approved segmentation pages
EXTRACTION_APPROVE_ENABLED = True          # Stephen 2026-09-29: extraction Approve locks the Stage B records

def _approve_btn(r, action, msg=None):
    """Approve button + script for the sticky header; one click POSTs {code, action} to approve_server.py (tailnet only).
    No confirm/alert. Disabled on first click (double-click guard; server 409 is the backstop). Success: the button becomes a
    blue \u2713 'Approved - N <unit> locked at HH:MM CT' chip and the header chip turns Approved, in place (no reload; the live
    poller then swaps in the regenerated page). Errors are shown inline and the button is re-enabled."""
    unit = {'segmentation': 'crops', 'transcription': 'entries', 'approve_expansion': 'entries', 'extraction': 'records', 'recut': ''}[action]
    if action == 'recut':
        label, busy, cls, title = '&#9986; Recut with latest algorithm', 'Requesting recut\u2026', 'rcb', 'Queues this row for a re-cut immediately (no confirmation)'
    else:
        label, busy, cls, title = '&#128274; Approve', 'Approving\u2026', 'apv', 'Locks immediately (no confirmation)'
    js = (_APPROVE_JS.replace('__CODE__', _J(r['code'])).replace('__ACTION__', _J(action))
          .replace('__URL__', _api_js()).replace('__UNIT__', _J(unit)).replace('__LABEL__', _J(label)).replace('__BUSY__', _J(busy)))
    return (f'<button id="apv" class="{cls}" onclick="oprApprove()" title="{title}">{label}</button>'
            '<span id="apvmsg"></span><script>' + js + '</script>')

_APPROVE_JS = ' '.join(l.strip() for l in r'''function oprApprove(){
 var C=__CODE__,A=__ACTION__,U=__URL__,UNIT=__UNIT__,LBL=__LABEL__,BUSY=__BUSY__;
 var b=document.getElementById("apv"),m=document.getElementById("apvmsg");
 if(!b||b.disabled||window.oprBusy)return;
 window.oprBusy=true;b.disabled=true;b.textContent=BUSY;
 function say(t,col){m.textContent=t;m.style.color=col||"#555";m.style.fontWeight="700";}
 say("");
 function fail(t){window.oprBusy=false;b.disabled=false;b.innerHTML=LBL;say("\u2716 "+t,"#d55e00");}
 fetch(U,{method:"POST",headers:{"Content-Type":"application/json","X-OPR-Approve":"1"},body:JSON.stringify({code:C,action:A})})
 .then(function(x){if(window.oprAuth&&window.oprAuth.fail(x)){var go=window.oprAuth.login();return {ok:false,_http:401,error:go?"login required, opening the login page\u2026":"login required, please log in again"};}return x.json().then(function(j){j._http=x.status;return j;},function(){return {ok:false,error:"HTTP "+x.status,_http:x.status};});})
 .then(function(j){
  if(!j.ok){fail((A=="recut"?"Recut not requested":"Not approved")+" ("+(j._http||"?")+"): "+j.error);return;}
  if(A=="recut"){var q="",tq=(String(j.time||"").match(/T(\d\d:\d\d)/)||[])[1]||"";
   var d=document.createElement("span");d.className="chip apvdone";d.style.cssText=q+";font-size:13px;padding:4px 12px";
   d.textContent="Queued for redo"+(tq?" \u2013 requested at "+tq+" CT":"");b.replaceWith(d);say("");
   var c2=document.querySelector("#stk .chip.segchip");if(c2){c2.style.cssText=q;c2.textContent="Queued for redo";}window.oprBusy=false;return;}
  var n=(j.crops!=null?j.crops:j.files),tm=(String(j.locked_by||"").match(/T(\d\d:\d\d)/)||[])[1]||"";
  var g="";
  var ok=document.createElement("span");ok.className="chip apvdone";ok.style.cssText=g+";font-size:13px;padding:4px 12px";
  ok.textContent="Approved \u2013 "+n+" "+UNIT+" locked"+(tm?" at "+tm+" CT":"");b.replaceWith(ok);say("");
  var ch=document.querySelector("#stk .chip.segchip");if(ch){ch.style.cssText=g;ch.textContent="Approved";}
  [].forEach.call(document.querySelectorAll("#stk .draftban,#stk .stagenote"),function(e){e.style.display="none";});
  window.oprBusy=false;
 })
 .catch(function(e){fail("Could not reach the approve service: "+e);});
}'''.split('\n'))

# ---- live update: every detail page polls status (15 s) and soft-swaps its body from <code>.bundle.js when its rev changes ----
AUTH_JS = "(function(R){if(window.oprAuth)return; var file=location.protocol=='file:',tried=false,pub=/^(www\\.)?oldparishrecords\\.com$/i.test(location.hostname); function u(p){return new URL(R+p,location.href).href;} function fail(r){if(file||!r)return false;if(r.status===401)return true; try{if(r.redirected&&/\\/login$/.test(new URL(r.url).pathname))return true;}catch(e){} return (r.headers.get('content-type')||'').toLowerCase().indexOf('text/html')>=0;} function login(){if(file)return false;if(tried)return true;tried=true; var k='oprLoginTry',now=Date.now(),last=0;try{last=+sessionStorage.getItem(k)||0;}catch(e){} if(now-last<20000)return false; try{sessionStorage.setItem(k,String(now));}catch(e){} location.assign(u('login')+'?next='+encodeURIComponent(location.pathname+location.search+location.hash));return true;} function link(){if(!pub||!document.body||document.getElementById('oprlogout'))return; var a=document.createElement('a');a.id='oprlogout';a.href=u('logout');a.textContent='Log out'; a.style.cssText='position:fixed;right:calc(10px + env(safe-area-inset-right));bottom:calc(6px + env(safe-area-inset-bottom));z-index:50;font:12px system-ui,sans-serif;color:#666;background:rgba(255,255,255,.85);padding:1px 6px;border-radius:6px;text-decoration:none'; document.body.appendChild(a);} window.oprAuth={fail:fail,login:login,link:link,url:u}; if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',link);else link(); })(__ROOT__);"   # login gate helper (oldparishrecords.com): 401 -> login?next=..., Log out link; inert on file://
def _auth_js(root): return AUTH_JS.replace('__ROOT__', json.dumps(root))

LIVE_JS = ' '.join(l.strip() for l in r'''(function(){
 var M=document.querySelector('meta[name="opr-rev"]');if(!M)return;
 var REV=M.content,K=M.getAttribute('data-kind'),C=M.getAttribute('data-code'),file=location.protocol=="file:";
 window.oprBusy=false;
 function inj(src,id){var o=document.getElementById(id);if(o)o.remove();var s=document.createElement('script');s.id=id;s.src=src+'?t='+Date.now();document.head.appendChild(s);}
 function onStatus(d){try{var r=(d.rows||[]).filter(function(x){return x.code==C;})[0];if(!r||!r[K])return;var c=r[K];
   if(window.oprOnRow)try{window.oprOnRow(c,r);}catch(e){}
   if(c.rev){if(c.rev!==REV)inj(encodeURIComponent(C)+'.bundle.js','oprb');}
   else{var ch=document.querySelector('#stk .chip.segchip');if(ch&&ch.textContent!==c.status)ch.textContent=c.status;}}catch(e){}}
 window.wilmesStatus=onStatus;
 window.oprPage=function(p){if(window.oprBusy||window.oprEditing||!p||p.code!==C||p.kind!==K||p.rev===REV)return;
   var op=[].map.call(document.querySelectorAll('details.ent[open]'),function(e){return e.id;}),y=window.scrollY,keep=window.oprKeep?window.oprKeep():null;
   document.body.innerHTML=p.body;
   [].forEach.call(document.body.querySelectorAll('script'),function(s){if(s.id=='openjs')return;var n=document.createElement('script');n.text=s.text;s.parentNode.replaceChild(n,s);});
   op.forEach(function(id){var e=document.getElementById(id);if(e)e.open=true;});
   if(keep&&window.oprRestore)try{window.oprRestore(keep);}catch(e){}
   var st=document.getElementById('stk');if(st)document.documentElement.style.setProperty('--stkh',st.offsetHeight+'px');
   window.scrollTo(0,y);REV=p.rev;M.content=REV;
   var h=document.querySelector('#stk .hdr');if(h){var u=document.createElement('span');u.id='oprupd';u.className='src';
     u.textContent=' · updated live '+new Date().toLocaleTimeString();h.appendChild(u);}if(window.oprAuth)window.oprAuth.link();};
 function poll(){if(window.oprBusy)return;
   if(file){inj('../status.js','oprs');return;}
   fetch('../status.json?t='+Date.now(),{cache:'no-store'}).then(function(r){if(window.oprAuth&&window.oprAuth.fail(r)){window.oprAuth.login();throw 'auth';}if(!r.ok)throw r.status;return r.json();}).then(onStatus)
     .catch(function(e){if(e==='auth')return;inj('../status.js','oprs');});}
 setInterval(poll,15000);setTimeout(poll,2000);
})();'''.split('\n'))

def _page_rev(page):
    return hashlib.sha1(_re.sub(r'<p class="src">Generated [^<]*', '', page).encode('utf-8')).hexdigest()[:12]

def _write_page(dirpath, c, page, kind, r):
    """Write <c>.html (with rev meta + live script) and <c>.bundle.js (same body, for soft swaps incl. file://)."""
    page = page.replace('content="width=device-width,initial-scale=1"', 'content="width=device-width,initial-scale=1,viewport-fit=cover"')
    page = page.replace('</head>', f'<style>{MOBILE_CSS}</style><script>{MOBILE_JS}</script></head>', 1)
    # Pinned header: the sticky block is moved to the top of <body> (it used to sit below the back link + <h1>, so it scrolled
    # 86-124 px with the page before it locked, and on short pages it never locked at all). The back link goes inside it.
    page = re.sub(r'<p><a href="\.\./index\.html">&larr; Dashboard</a></p>\n(<h1>.*?</h1>\n)(<div class="stk" id="stk">.*?<!--/stk-->\n)',
                  lambda m: m.group(2).replace('<b>Row</b>', '<a class="back" href="../index.html">&larr; Dashboard</a> &nbsp; <b>Row</b>', 1) + m.group(1),
                  page, count=1, flags=re.S)
    page = re.sub(r'(?<!title="Open full size">)(<img src="([^"]+)"[^>]*>)', r'<a class="full" href="\2" target="_blank" rel="noopener" title="Open full size">\1</a>', page)   # crops tappable
    rev = _page_rev(page); r[kind]['rev'] = rev
    head = (f'<meta name="opr-rev" content="{rev}" data-kind="{kind}" data-code="{_html.escape(c, quote=True)}">'
            f'<script>{_auth_js("../")}</script><script>{LIVE_JS}</script>')
    page = page.replace('<head>', '<head>' + head, 1)
    body = page[page.index('<body>') + 6: page.rindex('</body>')]
    bundle = 'window.oprPage&&window.oprPage(' + json.dumps({'code': c, 'kind': kind, 'rev': rev, 'body': body}) + ');\n'
    for name, data in ((f'{c}.html', page), (f'{c}.bundle.js', bundle)):
        fd, tmp = tempfile.mkstemp(dir=dirpath); os.write(fd, data.encode('utf-8')); os.close(fd)
        os.chmod(tmp, 0o644); os.replace(tmp, os.path.join(dirpath, name))
    return f'{c}.html'

def _drop_stale_bundles(dirpath, keep):
    for p in glob.glob(os.path.join(dirpath, '*.bundle.js')):
        if os.path.basename(p) not in keep: os.remove(p)

_LOCKED = {'locked', 'approved', 'final'}
def _lock_note(nl, n, what, E):
    """Shown instead of the Approve button when the server would refuse (some items already locked)."""
    return (f' <span class="lknote" style="margin-left:8px;padding:2px 8px;border-radius:10px;background:#f1f3f5;color:#555;'
            f'border:1px solid #ccc;font-size:12px;font-weight:600">{nl} of {n} {E(what)} locked; approve is not available</span>')

def _json_field_counts(paths, key, fallback=None):
    """(n_files, n_locked) for JSON files by top-level status key."""
    nl = 0
    for p in paths:
        try:
            j = json.load(open(p, encoding='utf-8'))
            v = j.get(key) if (key in j or not fallback) else j.get(fallback)
            nl += str(v).lower() in _LOCKED
        except Exception: pass
    return len(paths), nl

def _chip(st, E):
    """Status chip used in every detail-page header: colour-blind-safe class from _kind (CHIP_CSS), no inline colours."""
    k = _kind(st)
    return k, f'<span class="chip segchip{" k-" + k if k else ""}">{E(st)}</span>'

MATRICULA_BASE = 'https://data.matricula-online.eu/de/deutschland/paderborn/'   # same as MBASE in index.html
def _hl(url, txt, E, title):
    """Header link (Book/Image/Page): new tab, underlined; plain text when there is no URL."""
    return (f'<a class="hl" href="{E(url)}" target="_blank" rel="noopener noreferrer" title="{E(title)}">{E(txt)}</a>' if url else E(txt))
def _book_url(r):
    """Book title page on Matricula: same logic as booklink() in index.html (book_url, else collection/book/?pg=BOOKPG, BOOKPG is 1 for every book)."""
    if r.get('book_url'): return r['book_url']
    col = r.get('collection') or ('' if r.get('added') or r.get('added_by') else 'DE_EBAP_22212')
    base = MATRICULA_BASE.replace('/paderborn/', f"/{r['diocese']}/") if r.get('diocese') else MATRICULA_BASE
    return f'{base}{col}/{r["book"]}/?pg=1' if (r.get('book') and col) else ''
def _img_link(r, E):
    return _hl(r.get('url'), r.get('image'), E, 'Open this image on Matricula (new tab)')

# ---------------- Record type (register) shown in every detail-page header and in the Pipeline table: ONE mapping for both ----------------
# Order (never guess): 1) records.json row 'type'  2) register_type in the crop manifests for that image  3) register_type anywhere in
# the same book's manifest entries  4) the book-code suffix  -> otherwise 'Type unknown'. If 1) and 2) disagree -> 'Type unknown'.
# German terms are Matricula's own register titles. Suffix convention checked 29 Sep 2026 against the Matricula titles of every book in use:
#   DE_EBAP_22212 (Horn): KB004-02-T Taufen 1760-1799, KB004-06-T Taufen 1800-1807, KB005-02-H Trauungen 1760-1807,
#   KB006-01-S Sterbefälle 1760-1807, KB007-01-T Taufen 1808-1837, KB010-01-S Sterbefälle 1808-1851;  DE_EBAP_23815 (Warstein): KB013-01-S Sterbefälle 1843-1882.
RECORD_TYPES = {'births': ('Births', 'Geburten'), 'confcomm': ('Confirmation/Communion', 'Firmung/Erstkommunion'), 'baptisms': ('Baptisms', 'Taufen'), 'marriages': ('Marriages', 'Trauungen'), 'burials': ('Burials', 'Sterbefälle'), 'deaths': ('Deaths', 'Sterbefälle'),
                'communion': ('First Communion', 'Erstkommunion'), 'confirmation': ('Confirmations', 'Firmungen'), 'notes': ('Notes', None)}
_TYPE_WORDS = [('confcomm', r'^confirmation/communion$'), ('births', r'^(birth|geburt)'), ('baptisms', r'bapti|taufe|geburt|birth'), ('marriages', r'marri|trauung|heirat|ehe|wedding'),
               ('deaths', r'^death$'), ('burials', r'buri|death|sterbe|begr(ä|ae|a)bni|tote|verstorb'), ('communion', r'communion|kommunion'),
               ('confirmation', r'confirm|firm'), ('notes', r'note|notiz|vermerk')]
BOOK_SUFFIX_TYPES = {'T': 'baptisms', 'H': 'marriages', 'S': 'burials'}   # verified per book above; a new suffix/book -> 'Type unknown'
def _type_key(word):
    w = str(word or '').strip().lower()
    if not w: return None
    for k, rx in _TYPE_WORDS:
        if re.search(rx, w): return k
    return None
_REG_CACHE = {}
def _register_types():
    """{'img': {image_id: set(keys)}, 'book': {book: set(keys)}} from register_type in entries/manifest.jsonl (cached per run)."""
    if _REG_CACHE: return _REG_CACHE
    img, book = {}, {}
    try:
        for line in open(os.path.join(W, 'entries/manifest.jsonl'), encoding='utf-8'):
            line = line.strip()
            if not line: continue
            try: e = json.loads(line)
            except ValueError: continue
            k = _type_key(e.get('register_type'))
            iid = e.get('image_id') or e.get('scan') or ''
            m = re.search(r'_(KB[\w-]+?)_\d{3,4}$', iid)
            if k:
                img.setdefault(iid, set()).add(k)
                if m: book.setdefault(m.group(1), set()).add(k)
    except FileNotFoundError: pass
    _REG_CACHE.update({'img': img, 'book': book}); return _REG_CACHE
_TSLOT = {'Birth': 'Birth', 'Baptism': 'Baptism', 'Marriage': 'Marriage', 'Burial': 'Burial', 'Death': 'Death',
          'First Communion': 'First Communion', 'Confirmation/Communion': 'First Communion'}
def _tslot(t):
    """records.json type -> the ＋ menu slot (same table as rowedit.type_slot); 'Other: …' and anything else -> ''."""
    return _TSLOT.get(str(t or '').strip(), '')
def record_type(r):
    """-> {'key','en','de','label','source'} for a records.json row (see the order above)."""
    reg = _register_types()
    if str(r.get('type') or '').startswith('Other:'):          # added row, record type 'Other' with Stephen's own words
        t = str(r['type'])[6:].strip() or 'Other'
        return {'key': 'other', 'en': t, 'de': '', 'label': f'Other: {t}', 'source': 'records.json type (added row)'}
    k1 = _type_key(r.get('type'))
    ki = reg['img'].get(r.get('image_id') or '', set())
    k2 = next(iter(ki)) if len(ki) == 1 else None
    kb = reg['book'].get(r.get('book') or '', set())
    k3 = next(iter(kb)) if len(kb) == 1 else None
    suf = str(r.get('book') or '').rsplit('-', 1)[-1] if '-' in str(r.get('book') or '') else ''
    k4 = BOOK_SUFFIX_TYPES.get(suf)
    if k1 and k2 and k1 != k2: key, src = None, 'conflict: records.json says %s, manifest says %s' % (k1, k2)
    elif k1: key, src = k1, 'records.json type' + (' (manifest agrees)' if k2 == k1 else '')
    elif k2: key, src = k2, 'manifest register_type'
    elif k3: key, src = k3, 'manifest register_type (same book)'
    elif k4: key, src = k4, 'book suffix -' + suf
    else: key, src = None, 'no data'
    if not key: return {'key': '', 'en': 'Type unknown', 'de': '', 'label': 'Type unknown', 'source': src}
    en, de = RECORD_TYPES[key]
    return {'key': key, 'en': en, 'de': de or '', 'label': en + (f' ({de})' if de else ''), 'source': src}
def _type_pill(r, E):
    t = r.get('record_type') or record_type(r)
    de = f' <span class="de">({E(t["de"])})</span>' if t['de'] else ''
    return (f'<span class="rtype{" unk" if not t["key"] else ""}" title="Record type: {E(t["label"])} (from {E(t["source"])})">'
            f'<span class="rti" aria-hidden="true"></span>{E(t["en"])}{de}</span>')

def _sticky(r, kind, st, E, btn='', tail='', line2='', below=''):
    """Shared sticky header for extraction, transcription and segmentation pages: row, book, page, status chip (+ extras)."""
    return (f'<div class="stk" id="stk"><div class="hdr">'
            + (f'<span class="apvbox">{btn.strip()}</span>' if btn.strip() else '') +
            f'<b>Row</b> {E(r["id"])} &nbsp; <b>Book</b> {_hl(_book_url(r), r["book"], E, "Open this book\u2019s title page on Matricula (new tab)")} &nbsp; <b>Page</b> {_hl(r.get("url"), r.get("page"), E, "Open this page on Matricula (new tab)")} &nbsp; {_type_pill(r, E)} <span class="kd">&nbsp; <b>{E(kind)}</b></span> {_chip(st, E)[1]}' + (f'<span class="stail">{tail}</span>' if tail else '')
            + '<button class="stktog" type="button" aria-expanded="false" aria-label="Show or hide the header details"></button>'
            + (f'<span class="l2"><br>\n{line2}</span>' if line2 else '') + f'</div>{below}</div><!--/stk-->\n')

def _seg_header(r, st, n, E, ents=(), xp=None):
    """Status header for segmentation pages; Draft rows get an Approve button (POST to approve_server.py)."""
    sl = st.lower(); stg = _stage(sl)
    k = _kind(st)
    chip = f'<span class="segchip{" k-" + k if k else ""}">{E(st)}</span>'
    btn = ''
    note = {'queued for redo': 'A re-cut is queued. The crops below are the OLD cut; no approval until the re-cut is ready (Recut).',
            'redoing': 'The Entry Segmenter is re-cutting this page now. Crops below are the old cut or in progress; no approval yet.'}.get(stg, '')
    nbad = sum(1 for e in ents if str(e.get('crop_status', '')).lower() not in ('pending', 'draft') or str(e.get('status', '') or '').lower() == 'locked')
    if (sl.startswith('draft') or stg == 'recut') and nbad:
        btn = _lock_note(nbad, n, 'crops', E).replace(' locked;', ' locked or not pending;')
    elif sl.startswith('approved') and not stg and RECUT_ENABLED:
        btn = _approve_btn(r, 'recut')
    elif (sl.startswith('draft') or stg == 'recut') and xp and not xp.get('approve'):
        btn = ('<span class="stagenote lank" role="note" style="display:inline-block;padding:4px 10px;border-radius:6px;white-space:normal">\u24d8 Approve is not available yet for '
               + E(xp['label']) + ' crops: they live in ' + E(xp['root']) + ', which the dashboard only reads. Lock them in the Lank project; this page updates by itself.</span>')
    elif sl.startswith('draft') or stg == 'recut':
        btn = _approve_btn(r, 'segmentation', f"Approve all {n} crops of row {r['id']} ({r['code']})? This locks them in the Entry Segmenter manifests.")
    line2 = (f'<b>Image</b> {_img_link(r, E)} &nbsp; <span class="src">{E(r["segmentation"].get("detail", ""))}</span> &nbsp; '
             f'<a href="{E(r["url"])}" target="_blank" rel="noopener">Matricula page</a>')
    below = (f'<div class="stagenote" class="k-{k}" style="margin-top:6px;padding:6px 10px;border-radius:6px;white-space:normal">{E(note)}</div>' if note else '')
    return _sticky(r, 'Segmentation', st, E, btn=(' ' + btn if btn and not btn.startswith(' ') else btn), tail=f' &nbsp; <b>Crops</b> {n}', line2=line2, below=below)

CORR_JS = '(function(){if(window.oprCorr)return;window.oprCorr=1; function C(){var m=document.querySelector(\'meta[name="opr-rev"]\');return m?m.getAttribute(\'data-code\'):\'\';} function box(el){return el&&el.closest?el.closest(\'.corr\'):null;} function reset(b){var p=b.querySelector(\'.corrpanel\');if(!p)return;p.hidden=true;b.removeAttribute(\'data-open\'); [].forEach.call(p.querySelectorAll(\'input[type=checkbox]\'),function(c){c.checked=false;});p.querySelector(\'textarea\').value=\'\'; var er=b.querySelector(\'.correrr\');if(er)er.textContent=\'\';var cb=b.querySelector(\'.corrbtn\');if(cb)cb.hidden=false;} function send(b,btn){var p=b.querySelector(\'.corrpanel\'),err=b.querySelector(\'.correrr\'); var iss=[].filter.call(p.querySelectorAll(\'input[type=checkbox]\'),function(c){return c.checked;}).map(function(c){return c.value;}); var note=p.querySelector(\'textarea\').value.trim(); if(!iss.length&&!note){err.textContent=\'\\u2716 Tick at least one box or write a note.\';err.style.color=\'#d55e00\';return;} if(btn.disabled||window.oprBusy)return;window.oprBusy=true;btn.disabled=true;var lbl=btn.textContent;btn.textContent=\'Sending\\u2026\';err.textContent=\'\'; function fail(t){window.oprBusy=false;btn.disabled=false;btn.textContent=lbl;err.textContent=\'\\u2716 \'+t;err.style.color=\'#d55e00\';} fetch(__URL__,{method:\'POST\',headers:{\'Content-Type\':\'application/json\',\'X-OPR-Approve\':\'1\'},body:JSON.stringify({code:C(),action:\'segmentation_correction\',entry_id:b.getAttribute(\'data-e\'),issues:iss,note:note})}) .then(function(x){if(window.oprAuth&&window.oprAuth.fail(x)){var go=window.oprAuth.login();return {ok:false,_http:401,error:go?\'login required, opening the login page\\u2026\':\'login required, please log in again\'};} return x.json().then(function(j){j._http=x.status;return j;},function(){return {ok:false,error:\'HTTP \'+x.status,_http:x.status};});}) .then(function(j){if(!j.ok){fail(\'Not sent (\'+(j._http||\'?\')+\'): \'+j.error);return;} window.oprBusy=false;b.removeAttribute(\'data-open\');p.hidden=true;reset(b);var cb=b.querySelector(\'.corrbtn\');if(cb)cb.hidden=true; var d=document.createElement(\'span\');d.className=\'chip corrsent\';d.textContent=\'Correction sent \\u00b7 queued\'+(j.recut_request?\' (recut request)\':\'\');b.insertBefore(d,b.firstChild); var pe=b.querySelector(\'.corrpend\');if(pe){pe.textContent=\'Correction pending: \'+(j.issues||[]).concat(j.note?[]:[]).join(\', \');pe.hidden=false;} var ch=document.querySelector(\'#stk .chip.segchip\');if(ch&&j.segmentation){ch.style.cssText=\'\';ch.textContent=j.segmentation;}}) .catch(function(e){fail(\'Could not reach the approve service: \'+e);});} document.addEventListener(\'click\',function(ev){var t=ev.target;if(!t||!t.classList)return; if(t.classList.contains(\'corrbtn\')){var b=box(t);b.querySelector(\'.corrpanel\').hidden=false;b.setAttribute(\'data-open\',\'1\');t.hidden=true;var er=b.querySelector(\'.correrr\');if(er)er.textContent=\'\';return;} if(t.classList.contains(\'corrcancel\')){reset(box(t));return;} if(t.classList.contains(\'corrsend\')){send(box(t),t);}}); window.oprKeep=function(){return [].map.call(document.querySelectorAll(\'.corr[data-open]\'),function(b){var p=b.querySelector(\'.corrpanel\'),ta=p.querySelector(\'textarea\'); return {e:b.getAttribute(\'data-e\'),checks:[].filter.call(p.querySelectorAll(\'input[type=checkbox]\'),function(c){return c.checked;}).map(function(c){return c.value;}), note:ta.value,focus:document.activeElement===ta,s0:ta.selectionStart,s1:ta.selectionEnd,err:(b.querySelector(\'.correrr\')||{}).textContent||\'\'};});}; window.oprRestore=function(k){(k||[]).forEach(function(o){var b=[].filter.call(document.querySelectorAll(\'.corr\'),function(x){return x.getAttribute(\'data-e\')===o.e;})[0];if(!b)return; var p=b.querySelector(\'.corrpanel\');p.hidden=false;b.setAttribute(\'data-open\',\'1\');var cb=b.querySelector(\'.corrbtn\');if(cb)cb.hidden=true; [].forEach.call(p.querySelectorAll(\'input[type=checkbox]\'),function(c){c.checked=o.checks.indexOf(c.value)>=0;});var ta=p.querySelector(\'textarea\');ta.value=o.note; if(o.err){var er=b.querySelector(\'.correrr\');if(er)er.textContent=o.err;} if(o.focus){ta.focus();try{ta.setSelectionRange(o.s0,o.s1);}catch(e){}}});}; window.oprOnRow=function(c){var cr=c.corrections||{};[].forEach.call(document.querySelectorAll(\'.corr\'),function(b){var pe=b.querySelector(\'.corrpend\');if(!pe)return; var t=cr[b.getAttribute(\'data-e\')];if(t){pe.textContent=\'Correction pending: \'+t;pe.hidden=false;}else if(!b.querySelector(\'.corrsent\')){pe.textContent=\'\';pe.hidden=true;}});}; })();'
CORR_ISSUES = [('top_cut', 'Top cut off'), ('bottom_cut', 'Bottom cut off'), ('left_cut', 'Left edge cut'), ('right_cut', 'Right edge cut'),
               ('neighbour', 'Includes part of neighbour entry'), ('merge_above', 'Merge with entry above'), ('merge_below', 'Merge with entry below'),
               ('split', 'Split this entry'), ('wrong_label', 'Wrong entry number or label'), ('other', 'Other')]
CORR_CSS = ('.corr{margin-top:6px}.corrbtn{font-size:12px;padding:2px 10px;border:1px solid #b36b00;color:#7a4a00;background:#fff;border-radius:12px;cursor:pointer}'
            '.corrpanel{border:1px solid #e0a800;background:#fffaf0;border-radius:6px;padding:8px 10px;margin-top:6px;font-size:13px}'
            '.corrpanel label{display:inline-block;margin:2px 14px 2px 0;white-space:nowrap}.corrpanel textarea{width:100%;box-sizing:border-box;min-height:44px;margin:6px 0;font:inherit}'
            '.corrpanel button{font-size:13px;padding:3px 12px;margin-right:8px;border-radius:12px;cursor:pointer}.corrsend{border:1px solid #b36b00;background:#b36b00;color:#fff}.corrcancel{border:1px solid #999;background:#fff}'
            '.corrpend{display:inline-block;background:#e69f00;color:#000;border:2px solid #000;border-radius:12px;padding:1px 10px;font-size:12px;font-weight:700;margin-left:6px}'
            '.corrsent{display:inline-block;background:#e69f00;color:#000;border:2px solid #000;border-radius:12px;padding:1px 10px;font-size:12px;font-weight:700;margin-right:6px}.correrr{margin-left:6px;font-weight:700}.corr [hidden]{display:none!important}')

def _corrections(code):
    """{entry_id: 'top cut off, split this entry; note: “…”'} from entries/_corrections/<code>.json (pending only)."""
    try: cj = json.load(open(os.path.join(W, 'entries', '_corrections', f'{code}.json'), encoding='utf-8'))
    except Exception: return {}
    out = {}
    for eid, items in (cj.get('pending') or {}).items():
        if not isinstance(items, list) or not items: continue
        labs = []
        for it in items:
            for l in it.get('issues') or []:
                if l not in labs: labs.append(l)
        notes = [str(it.get('note') or '').strip() for it in items if str(it.get('note') or '').strip()]
        t = ', '.join(labs)
        if notes: n = notes[-1]; t += ('; ' if t else '') + 'note: “' + (n[:80] + ('…' if len(n) > 80 else '')) + '”'
        if len(items) > 1: t += f' ({len(items)} flags)'
        out[eid] = t
    return out

def _corr_block(eid, pend, E):
    boxes = ''.join(f'<label><input type="checkbox" value="{k}"> {E(l)}</label>' for k, l in CORR_ISSUES)
    return (f'<div class="corr" data-e="{E(eid)}"><button type="button" class="corrbtn" title="Report a problem with this crop to the Entry Segmenter">Correct</button>'
            f'<span class="corrpend"{"" if pend else " hidden"}>{("Correction pending: " + E(pend)) if pend else ""}</span>'
            f'<div class="corrpanel" hidden>{boxes}<textarea placeholder="Note for the Entry Segmenter (optional if a box is ticked)" maxlength="2000"></textarea>'
            '<button type="button" class="corrsend">Submit</button><button type="button" class="corrcancel">Cancel</button><span class="correrr"></span></div></div>')

def write_segmentation_pages(rows, man):
    import shutil
    sd = os.path.join(OUT, 'segmentation'); os.makedirs(sd, exist_ok=True); made = []; bundles = []; files = []; pubcodes = set(); _PUB.clear()
    smp = os.path.join(sd, '.srcmap.json'); _SRCMAP.clear()
    try: _SRCMAP.update(json.load(open(smp)))
    except Exception: pass
    imgs = {x['code']: x['image_id'] for x in json.load(open(os.path.join(D, 'records.json')))['records']}
    E = lambda t: _html.escape(str(t if t is not None else ''), quote=True)
    for r in rows:
        st = str(r['segmentation']['status']); sl = st.lower()
        tq = str(r['transcription']['status']).lower().startswith(('approved', 'draft'))  # transcription page needs the crops
        img = imgs.get(r['code']) or r.get('image_id') or ''; ents = sorted(man.get(img, []), key=_seg_key); stg = _stage(sl)
        xp = EXT_PROJECTS.get((str(r.get('town') or '').strip().lower(), str(r.get('book') or '').strip())) if ents and ents[0].get('_ext_root') else None
        tgt = (xp['entries'].get(r['code']) if xp else None)
        corr = _corrections(r['code']); r['segmentation']['corrections'] = corr
        # page + link: Approved/Draft/Recut always; Queued for redo/Redoing only when crops exist (old cut / in progress)
        sq = sl.startswith(('approved', 'draft')) or stg == 'recut' or (stg in ('queued for redo', 'redoing') and bool(ents))
        if not (sq or tq): continue
        c = r['code']; pubcodes.add(c); pub = _PUB.setdefault(c, {})
        cd = os.path.join(sd, c); os.makedirs(cd, exist_ok=True); keep = set(); blocks = []
        for e in ents:
            eid = str(e.get('entry_id', '')); lab = eid[len(img):].lstrip('_') if img and eid.startswith(img) else eid
            cs = 'locked' if is_locked(e) else 'draft'
            src = e.get('crop_path') or ''; fn = (lab or 'crop').replace('/', '_') + '.jpg'; tag = ''
            try:
                if not os.path.isfile(src): raise FileNotFoundError(src)
                _crop_jpg(src, os.path.join(cd, fn)); keep.add(fn); files.append(f'{c}/{fn}')
                pub[os.path.abspath(src)] = pub[os.path.splitext(os.path.basename(src))[0]] = (f'{c}/{fn}', int(os.path.getmtime(src)))
                tag = f'<img src="{E(c)}/{E(fn)}?v={int(os.path.getmtime(src))}" alt="{E(lab)}" loading="lazy">'
            except Exception as ex: tag = f'<p class="src">crop unavailable: {E(ex)}</p>'
            col = '#0b4f8a' if cs == 'locked' else '#7a4a00'
            mlab = next((str(e[k]).strip() for k in ('label', 'crop_label', 'segment_label', 'description', 'key_label') if e.get(k) and str(e[k]).strip()), '')
            mine = bool(tgt) and eid == tgt
            blocks.append(f'<figure class="crop{" mine" if mine else ""}"' + (' id="target"' if mine else '') + f'><figcaption><b>Entry {E(lab)}</b> <span class="st" style="color:{col};border-color:{col}">{cs}</span> '
                          + ('<span class="tgt">\u25c6 This row\u2019s entry</span> ' if mine else '') +
                          f'<span class="fn">{E(e.get("entry_kind", ""))}</span>'
                          + (f' <span class="lbl">{E(mlab)}</span>' if mlab else '')
                          + (f'<div class="desc">{E(e.get("notes"))}</div>' if e.get('notes') else '')
                          + f'</figcaption>{tag}' + _corr_block(eid, corr.get(eid), E) + '</figure>\n')
        if tq:                                                        # crops referenced by Stage A but not in the manifest
            for srcs in _stagea_crops(c).values():
                for src in srcs:
                    stem = os.path.splitext(os.path.basename(src))[0]
                    if os.path.abspath(src) in pub or stem in pub or not os.path.isfile(src): continue
                    lab = stem[len(img):].lstrip('_') if img and stem.startswith(img) else stem; fn = lab + '.jpg'
                    try:
                        _crop_jpg(src, os.path.join(cd, fn)); keep.add(fn); files.append(f'{c}/{fn}')
                        pub[os.path.abspath(src)] = pub[stem] = (f'{c}/{fn}', int(os.path.getmtime(src)))
                    except Exception: pass
        qc = []                                                       # Segmenter QC images (entries/_qc/<image>_redo_*.jpg), linked only
        for kind in ('overlay', 'contact'):
            q = os.path.join(xp['root'], xp['qc'], f'{img}_redo_{kind}.jpg') if xp else os.path.join(W, 'entries', '_qc', f'{img}_redo_{kind}.jpg'); fn = f'qc_{kind}.jpg'
            if not (sq and img and os.path.isfile(q)): continue
            dst = os.path.join(cd, fn)
            if not os.path.isfile(dst) or os.path.getmtime(dst) != os.path.getmtime(q) or os.path.getsize(dst) != os.path.getsize(q):
                shutil.copy2(q, dst + '.tmp'); os.chmod(dst + '.tmp', 0o644); os.replace(dst + '.tmp', dst)
            keep.add(fn); files.append(f'{c}/{fn}')
            qc.append(f'<a href="{E(c)}/{fn}?v={int(os.path.getmtime(q))}" target="_blank" rel="noopener">re-cut {kind}</a>')
        qc_html = (f'<p class="src">Segmenter QC images: {" &nbsp;|&nbsp; ".join(qc)}</p>\n' if qc else '')
        for p in glob.glob(os.path.join(cd, '*')):                    # clear stale crops for this row
            if os.path.basename(p) not in keep: os.remove(p)
        if not sq: continue                                           # crops published for the transcription page only
        r['segmentation']['link'] = f'segmentation/{c}.html'
        page = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">' + NOCACHE + '<script>' + CHIP_JS + '</script>\n'
            f'<script>{CORR_JS.replace("__URL__", _api_js())}</script>'
            f'<title>Row {E(r["id"])} {E(c)} \u2013 segmentation</title><style>{PAGE_CSS}{CHIP_CSS}{CORR_CSS}'
            'figure.crop{margin:0 0 18px;border:1px solid #ddd;border-radius:6px;padding:8px;background:#fafafa}'
            'figure.crop img{max-width:100%;height:auto;display:block;margin-top:6px}'
            '.segchip{display:inline-block;padding:2px 10px;border-radius:12px;font-size:13px;font-weight:700}'
            'figure.crop.mine{border:3px solid #0072b2;background:#f1f7fc}.tgt{display:inline-block;margin-left:6px;padding:0 8px;border:2px solid #0072b2;border-radius:10px;color:#0b4f8a;font-weight:700;font-size:12px}'
            '.stagenote.lank{background:#f1f7fc;border:1px dashed #0072b2;color:#1a3d7c}'
            '.st{border:1px solid;border-radius:10px;padding:0 8px;font-size:12px;font-weight:700;margin-left:6px}.lbl{font-weight:600;color:#1a3d7c;margin-left:6px}.desc{color:#555;font-size:12px;margin-top:2px}</style></head><body>\n'
            '<p><a href="../index.html">&larr; Dashboard</a></p>\n'
            f'<h1>Row {E(r["id"])}: {E(r["name"])} <span class="fn">({E(c)})</span> \u2013 Segmentation</h1>\n'
            + _seg_header(r, st, len(ents), E, ents, xp)
            + (f'<p class="src">Crops read from {E(xp["label"])} ({E(os.path.join(xp["root"], xp["manifest"]))}, read-only): the whole page cut, {len(ents)} crops'
               + (f'; this row\u2019s entry is <a href="#target">{E(tgt[len(img):].lstrip("_"))}</a> (\u25c6).' if tgt and any(e.get("entry_id") == tgt for e in ents) else '; this row\u2019s entry on the page is not mapped yet, so all crops are shown unmarked.') + '</p>\n' if xp else '')
            + qc_html
            + (''.join(blocks) or '<p>(no crops in the segmentation manifest)</p>\n') + OPEN_JS +
            f'<p class="src">Generated {E(datetime.datetime.now().astimezone().isoformat(timespec="seconds"))} by status.py; '
            f'crops converted to JPEG, long side \u2264 {SEG_MAX}px, q{SEG_Q}.</p>\n</body></html>\n')
        made.append(_write_page(sd, c, page, 'segmentation', r)); bundles.append(f'{c}.bundle.js')
    for p in glob.glob(os.path.join(sd, '*')):                        # drop pages/crop dirs for rows no longer linked
        b = os.path.basename(p)
        if os.path.isdir(p) and b not in pubcodes: shutil.rmtree(p)
        elif b.endswith('.html') and b not in made: os.remove(p)
    _drop_stale_bundles(sd, bundles)
    # bundles LAST: Greyhawk's refresh.sh fetches in list order, so crops are local before a page bundle announces them
    fd, tmp = tempfile.mkstemp(dir=sd); os.write(fd, ''.join(m + '\n' for m in made + files + bundles).encode()); os.close(fd)
    os.chmod(tmp, 0o644); os.replace(tmp, os.path.join(sd, 'list.txt'))   # pages + <code>/<crop>.jpg, pulled by refresh.sh
    live = {k: v for k, v in _SRCMAP.items() if os.path.isfile(os.path.join(sd, k))}
    fd, tmp = tempfile.mkstemp(dir=sd); os.write(fd, json.dumps(live).encode()); os.close(fd)
    os.chmod(tmp, 0o644); os.replace(tmp, smp)
    return made

def _added_info(r, ov):
    """Extra fields for rows added with '＋ Add row': research chip, edit values, deletable (same rule as approve_server delete_row)."""
    try:
        import rowedit as RE
        why = RE.work(RE.Ctx(W, D), r); dup = RE.same_page(RE.Ctx(W, D), r)
    except Exception as ex: why, dup = [f'check failed: {ex}'], []
    rs = str(r.get('research') or '')
    return {'added': {'by': r.get('added_by'), 'at': r.get('added_at'), 'notes': r.get('notes', ''), 'book_url': r.get('book_url', ''),
                      'page_url': r.get('url', ''), 'type_raw': r.get('type', ''), 'seg_requested': r.get('seg_requested', ''),
                      'deletable': not why, 'work': why, 'same_page': dup},
            'research': ({'status': rs, 'detail': {'Researching': 'Chief is looking for the book and page',
                                                  'Page found': 'book, image and page are known'}.get(rs, ''), 'source': 'records.json'} if rs else None)}

def main():
    try:                                   # Stephen's recorded reading choices survive a Transcriber/Extractor rewrite
        _codes = [x['code'] for x in json.load(open(os.path.join(D, 'records.json')))['records']]
        for fx in RD.reapply_all(W, D, _codes, log=lambda m: print(m, file=_sys.stderr)):
            print(f"re-applied reading {fx['type']} {fx['token']} -> {fx['new']} in {fx['code']} ({fx['entry_id']})", file=_sys.stderr)
    except Exception as ex: print(f'readings re-apply failed: {ex}', file=_sys.stderr)
    recs = json.load(open(os.path.join(D, 'records.json')))
    try: ov = json.load(open(os.path.join(D, 'overrides.json')))
    except Exception as ex: ov = {}; print('overrides.json unreadable:', ex)
    man = load_manifest(); rows = []
    towns = {}                                            # book (archival_id) -> church town, from Stage 0 parish field
    for p in glob.glob(f'{W}/stage0/*.page.json'):
        try:
            j = json.load(open(p)); b, par = j.get('archival_id'), j.get('parish') or ''
            if b and par and b not in towns: towns[b] = par.split(',')[0].strip()
        except Exception: pass
    for r in recs['records']:
        c, img = r['code'], row_image_id(r); o = ov.get(c, {}) if isinstance(ov.get(c), dict) else {}
        cells = {}; added = bool(r.get('added_by')); located = bool(str(r.get('book') or '').strip() and str(r.get('page') or '').strip())
        for k, fn in (('segmentation', lambda: seg(img, man) if (man.get(img) or not ext_project(r)) else ext_seg(r)), ('transcription', lambda: trans(c, img, man)),
                      ('expansion', lambda: expan(c, cells['transcription']['status'], o.get('expansion'))), ('extraction', lambda: extr(c, img))):
            v, why, *sx = fn(); src = sx[0] if sx else 'files'
            if v is None: v, why, src = r.get('baseline', {}).get(k, NS), '', 'baseline'
            seg_first_cut = (k == 'segmentation' and str(o.get(k) or '').startswith('Segmenting') and src == 'files' and v in ('Draft', 'Approved')
                             and _crops_newer(r, img, man, o.get('seg_stage_set')))   # crops made after 'Segmenting' was set -> files win
            if k in o and k != 'expansion' and not seg_first_cut: v, why, src = o[k], o.get('note', '') or ('Segmenter is making the first cut' if o[k] == 'Segmenting' else ''), 'override'   # expansion override handled (gated) in expan()
            if added and k == 'segmentation' and src == 'baseline' and r.get('seg_requested'):
                v, why, src = 'Queued', f"segmentation requested {str(r['seg_requested'])[11:16]} CT (book, image and page filled in)", 'rule'
            if added and not located and k != 'extraction' and src != 'override':
                v, why, src = NS, 'added row: waits for book and page', 'rule'
            if k == 'extraction' and src != 'files' and not expansion_output(c):
                v, why, src = WAIT_EXP, 'Record Extraction starts once this row\u2019s Expansion has output', 'rule'   # existing Stage B drafts are 'files' and stay as they are
            cells[k] = {'status': v, 'detail': why, 'source': src}
        rows.append({**{k: r[k] for k in ('id', 'group', 'name', 'spouse', 'date', 'type', 'book', 'image', 'page', 'code')},
                     'person_id': r.get('person_id') or '', 'person_kind': r.get('person_kind') or 'person', 'tslot': _tslot(r.get('type')),
                     'town': r.get('town') or towns.get(r['book'], ''), 'record_type': record_type(r), 'image_id': img,
                     **mlink(r), **cells, **(_added_info(r, ov) if added else {})})
    os.makedirs(OUT, exist_ok=True); write_segmentation_pages(rows, man); write_extraction_pages(rows, man); write_transcription_pages(rows, man); write_expansion_pages(rows)   # segmentation first: fills _PUB (crops for extraction title rows); also sets .link on linked chips
    now = datetime.datetime.now().astimezone()
    data = {'generated_at': now.isoformat(timespec='seconds'), 'generated_epoch': int(now.timestamp()),
            'groups': recs['groups'], 'rows': rows}
    try: data['meta_html'] = build_meta(rows, now)
    except Exception as ex: data['meta_html'] = '<p>Meta could not be built: ' + _html.escape(str(ex)) + '</p>'
    os.makedirs(OUT, exist_ok=True)
    s = json.dumps(data, ensure_ascii=False, indent=1)
    write_selftest_page()
    for name, body in (('status.json', s), ('status.js', 'window.wilmesStatus(' + s + ');\n')):
        fd, tmp = tempfile.mkstemp(dir=OUT); os.write(fd, body.encode()); os.close(fd)
        os.chmod(tmp, 0o644); os.replace(tmp, os.path.join(OUT, name))
    return data

# ---------------- Meta tab (index.html #metatab), rebuilt every run so live facts stay current ----------------
def _count_lines(p):
    try:
        with open(p, encoding='utf-8') as f: return sum(1 for l in f if l.strip())
    except Exception: return None

def build_meta(rows, now):
    """HTML for the Meta tab. Facts come from this code, approve_server.py, updater.sh/push.sh/ensure_dashboard.sh,
    `tailscale serve status` and Greyhawk's refresh.sh + LaunchAgent (read 2026-09-29). No credentials or secret paths."""
    import collections, html as H
    e = H.escape
    def sec(t, body): return f'<h2>{e(t)}</h2>{body}'
    def ul(items): return '<ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>'
    def chip(t, bg, fg, bd=None): return (f'<span class="chip" style="background:{bg};color:{fg};border:1px solid {bd or bg}">{e(t)}</span>')
    # live values
    man = collections.Counter(); algo = collections.Counter(); segv = collections.Counter(); nman = 0
    try:
        for l in open(os.path.join(W, 'entries/manifest.jsonl'), encoding='utf-8'):
            if not l.strip(): continue
            j = json.loads(l); nman += 1
            man[str(j.get('crop_status') or j.get('status') or 'pending')] += 1
            if j.get('algorithm_version'): algo[j['algorithm_version']] += 1
            if j.get('segmenter_version'): segv[j['segmenter_version']] += 1
    except Exception: pass
    heads = []
    try: heads = [l[3:].strip() for l in open(os.path.join(W, 'entries/_tools/ALGORITHM_VERSION.md'), encoding='utf-8') if l.startswith('## ')]
    except Exception: pass
    sb = collections.Counter(); nb = 0
    for p in glob.glob(os.path.join(W, 'stageB', '*', '*.json')):
        if '.bak' in os.path.basename(p) or p.endswith('_page_metadata.json'): continue
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception: continue
        if isinstance(j, dict) and j.get('schema_version'): sb[f"{j.get('schema_id') or '?'} {j['schema_version']}"] += 1; nb += 1
    sa = collections.Counter(); na = 0
    for p in glob.glob(os.path.join(W, 'stageA', '*', '*.diplomatic.json')):
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception: continue
        na += 1; sa[str(j.get('schema_version') or j.get('schema_id') or '(no schema field)')] += 1
    st = {k: collections.Counter() for k in ('segmentation', 'transcription', 'expansion', 'extraction')}
    for r in rows:
        for k in st: st[k][(r.get(k) or {}).get('status', '?')] += 1
    q = _count_lines(os.path.join(D, 'notify_queue.jsonl')); lg = _count_lines(os.path.join(W, 'entries', '_approvals.log'))
    cnt = lambda c: ', '.join(f'{e(str(k))}: {v}' for k, v in sorted(c.items(), key=lambda x: -x[1])) or '–'

    h = ['<p class="mnote">Operational notes for this dashboard, rebuilt by <code>status.py</code> on every refresh '
         f'(this copy: {e(now.strftime("%Y-%m-%d %H:%M:%S"))} CT). Anything not confirmed from the code or config is marked <i>unverified</i>.</p>']
    h.append(sec('1. How it is hosted', ul([
        '<b>https://oldparishrecords.com/dashboard/</b> (hidden: not linked from the public site; every page carries <code>noindex,nofollow</code>). '
        'OPNsense nginx terminates TLS and gates the whole <code>/dashboard</code> tree, including the API, behind a <b>login page with a session cookie</b> '
        '(auth service on the box at 127.0.0.1:8082, reached via tailscale serve paths <code>/login</code>, <code>/logout</code>, <code>/auth/check</code>; '
        'unauthenticated pages are sent to the login page, API/JSON requests get 401). It then reverse-proxies '
        'over Tailscale to the grokbot box\u2019s <code>tailscale serve</code> on port 80 with the <code>/dashboard</code> prefix stripped. '
        'OPNsense also sends <code>X-Robots-Tag: noindex, nofollow</code>. <i>(nginx side as reported by Site Host; not visible from this box)</i>',
        '<code>tailscale serve</code> (tailnet only, not Funnel): <code>/</code> \u2192 <code>127.0.0.1:8080</code> (<code>server.py</code>, static files from <code>dashboard/out/</code>); '
        '<code>/api/approve</code> \u2192 <code>127.0.0.1:8081/api/approve</code> (<code>approve_server.py</code>); both servers listen on localhost only.',
        'Tailnet URL <code>http://grokbot-box.taileabb91.ts.net/</code> works unchanged. All page links, images and polling URLs are relative; '
        'the approve URL is resolved in the browser (<code>../api/approve</code> from detail pages), so the same files work under <code>/</code> and <code>/dashboard/</code>.',
        'Approve API accepts only allowed origins (the tailnet host, <code>https://oldparishrecords.com</code>, <code>https://www.oldparishrecords.com</code>, local file pages) '
        'and requires the <code>X-OPR-Approve: 1</code> header. Hidden is not access control: the API is reachable only via the tailnet or behind the login gate. Pages show a small <b>Log out</b> link on oldparishrecords.com; if a poll or an action gets 401 (session expired), the page goes to <code>login?next=&lt;this page&gt;</code> once per page load.',
        'Greyhawk mirror: <code>~/OPR-Dashboard/</code> on Stephen\u2019s Mac, opened as <code>file://</code>; approve buttons there post to the tailnet URL.',
        'Self-test for the approve path: <code>_selftest.html</code> (not linked) posts action <code>selftest</code> / code <code>TEST0000</code>, '
        'which writes only <code>dashboard/_selftest/</code>.'])))
    h.append(sec('2. Where the data comes from', ul([
        'Scans: Matricula Online (links on each row point to <code>data.matricula-online.eu</code>).',
        '<code>dashboard/records.json</code>: the row list (code, book, page, image_id, groups).',
        '<code>entries/manifest.jsonl</code> (combined crop manifest; segmentation status, crop paths, lock state) and per-book <code>entries/&lt;book&gt;/manifest.jsonl</code> '
        '(written by approve; status.py reads the combined file).',
        '<code>stage0/*.page.json</code> (page structure; parish/town names) and <code>stage0_work/</code> (presence check only).',
        '<code>stageA/&lt;code&gt;/*.diplomatic.json</code> and <code>&lt;code&gt;_stageA.md</code> (transcriptions; <code>status</code> soft/locked per entry), '
        '<code>stageA/&lt;code&gt;/_confirmed_readings.json</code>, <code>_feedback_status.json</code>.',
        '<code>stageB/&lt;code&gt;/*.json</code> (extracted records; <code>stage_b_status</code>) and <code>&lt;code&gt;_stageB.md</code>.',
        '<code>dashboard/overrides.json</code> (manual status overrides, redo stages, holds), <code>dashboard/auto_transcribe_sent.json</code> (dispatch marker), '
        '<code>entries/_qc/*_redo_*.jpg</code> (QC images), crop images at each manifest line\u2019s <code>crop_path</code>.'])))
    h.append(sec('3. How it updates', ul([
        '<code>updater.sh</code> loops every 30 s: runs <code>status.py</code> (writes <code>out/status.json</code>, <code>out/status.js</code>, all detail pages + bundles), '
        'copies <code>index.html</code> into <code>out/</code>, then runs <code>push.sh</code> (copies <code>goals.html</code>).',
        '<code>approve_server.py</code> runs <code>status.py</code> inline after every successful action, so the pages change within seconds.',
        'Open pages poll every 15 s (<code>status.json</code> over http(s), <code>status.js</code> on file://) and swap changed content in place: '
        'no reload, open sections and scroll position kept, the selected tab (URL hash) kept.',
        'Cache busting: images carry <code>?v=&lt;mtime&gt;</code>, polling requests carry <code>?t=&lt;now&gt;</code>, pages carry no-cache meta tags.',
        'Greyhawk: LaunchAgent <code>com.veithome.opr-dashboard</code> runs <code>refresh.sh</code> every 60 s (and at login); it fetches '
        '<code>index.html</code>, <code>status.js</code>, <code>goals.html</code>, then each folder\u2019s <code>list.txt</code> items (crops before bundles), mirroring deletions.',
        '<code>ensure_dashboard.sh</code> restarts tailscaled, <code>tailscale serve</code>, the updater, <code>server.py</code> and <code>approve_server.py</code> if missing.'])))
    act = [
        ('Segmentation Approve', 'Locks the row\u2019s pending crops in <code>entries/manifest.jsonl</code> and the per-book manifest (under <code>entries/.manifest.lock</code>); '
         'backups <code>manifest.jsonl.bak_approve_&lt;code&gt;_&lt;ts&gt;</code>; clears any redo stage and transcription hold in <code>overrides.json</code> (backup <code>.bakN</code>). '
         'Log: <code>_approvals.log</code>; queue line <code>action: segmentation</code>. Next: transcription shows <b>Queued</b> and the row goes to the Entry Transcriber.'),
        ('Transcription Approve (row)', 'Sets <code>status: locked</code> + <code>locked_by</code> on the remaining Stage A entry files; backup in <code>_approve_backups/transcription/</code>. '
         'Log line + queue line <code>action: transcription</code>. Next: extraction by the Record Extractor <i>(unverified in code)</i>.'),
        ('Transcription Approve (per entry)', 'Locks one entry file; backup in <code>_approve_backups/approve_transcription_entry/</code>, mirror in <code>stageA/&lt;code&gt;/_entry_approvals.json</code>. '
         'Queue <code>kind: transcription_entry_approved</code>. When the last entry is locked the row flips to Approved automatically (extra row line with <code>auto_flip: true</code>).'),
        ('Expansion Approve (row)', 'Sets <code>status: locked</code> + <code>locked_by</code> on the remaining <code>stageA_expanded/&lt;folder&gt;/*.expanded.json</code> files (row must be Draft: every Stage A entry has its file, plus the <code>_expanded.md</code>); '
         'backup in <code>_approve_backups/approve_expansion/</code>; log line <code>action=approve_expansion</code>; queue line <code>kind: expansion_approved</code>. Expanded text is never changed.'),
        ('Expansion Approve (per entry)', 'Locks one <code>.expanded.json</code> (<code>status/locked_by/locked_at</code>); backup in <code>_approve_backups/approve_expansion_entry/</code>; queue <code>kind: expansion_entry_approved</code>; '
         'the last entry flips the row to Approved (extra <code>expansion_approved</code> line with <code>auto_flip: true</code>).'),
        ('\uff0b Add row / Edit details / Delete', 'Button below the table (end of the card list on phones). Inline form: Name and Record type required. '
         '<code>add_row</code> writes a records.json row (group <b>Added rows</b>, code <code>N</code>+4-digit id, ids never reused: <code>records_meta.json</code> high-water + <code>_deleted_rows.jsonl</code>), '
         'backup <code>records.json.bakN</code>, log line, queue <code>kind: row_added</code>. Research chip \U0001F50D Researching until the page is found (<code>setresearch.py</code>). '
         'When book, image and page are all filled in (Edit details / <code>update_row</code> or Chief\u2019s <code>updaterow.py</code>): Research \u2713 Page found, Segmentation Queued, one queue line '
         '<code>kind: segmentation_requested</code> (never repeated for the same book|image|page). <code>delete_row</code> only for added rows with no pipeline work (409 otherwise), queue <code>kind: row_deleted</code>.'),
        ('Extraction Approve', 'Locks the row\u2019s Stage B records (<code>stage_b_status</code>); backup in <code>_approve_backups/extraction/</code>; log + queue line <code>action: extraction</code>.'),
        ('Recut with latest algorithm', 'Only for Approved rows with no redo stage. Sets <code>segmentation: Queued for redo</code> in <code>overrides.json</code> (backup <code>.bakN</code>) and, if a transcription exists, '
         'puts it <b>On hold until crops approved</b>. Log + queue line <code>action: recut</code>. Never touches manifests or Stage A/B. Next: the Entry Segmenter re-cuts '
         '(Queued for redo \u2192 Redoing \u2192 Recut), then the row is approved again.'),
        ('Correct (per crop, segmentation pages)', 'Opens an inline panel (top/bottom/left/right cut, neighbour ink, merge above/below, split, wrong label, other + note). '
         'Stores the flag in <code>entries/_corrections/&lt;code&gt;.json</code> (pending, several per row/entry; backup in <code>_approve_backups/segmentation_correction/</code>) '
         'and sets the row to <b>Queued for redo</b> (left alone if already Queued/Redoing) with the recut-style transcription hold (<code>overrides.json</code> backup <code>.bakN</code>). '
         'Refused (409) for a locked crop unless the whole row is Approved; on an Approved row it becomes a recut request (<code>recut_request: true</code>). '
         'Queue <code>kind: segmentation_correction</code>. Each flagged crop shows a \u26a0 <b>Correction pending</b> chip (needs-Stephen style). Next: the Entry Segmenter re-cuts; '
         '<code>setseg.py &lt;code&gt; recut</code> archives the row\u2019s corrections (<code>entries/_corrections/archive/</code>), <code>setseg.py &lt;code&gt; clear</code> cancels them. Never touches manifests, crops or Stage A/B.'),
        ('\u2713 Confirm reading', 'Removes exactly one <code>[?]</code> from the token in the Stage A text; backup in <code>_approve_backups/confirm_reading/</code>; record in '
         '<code>_confirmed_readings.json</code>, pending item in <code>_feedback_status.json</code>. Queue <code>kind: reading_confirmed</code>. Next: the Entry Transcriber '
         'updates the item (processing \u2192 done) and must not re-add the <code>[?]</code>.'),
        ('Choose reading', 'For <code>word[?|alt]</code> (or <code>[?|a|b]</code>) one tap button per option. The page sends entry, field, token, occurrence and the '
         '20 characters before it; if the Stage A text no longer has that exact token there the server answers 409 and writes nothing. Writes the picked spelling into '
         'the Stage A diplomatic JSON (the shown field, plus every other field where the marked token occurs once) and the summary <code>&lt;code&gt;_stageA.md</code> '
         'under <code>entries/.manifest.lock</code>, backup in <code>_approve_backups/choose_reading/</code>, record <code>type: choice</code> in '
         '<code>_confirmed_readings.json</code>, log line, queue <code>kind: choose_reading</code>. Stage B is NOT refreshed from Stage A any more (Stephen, 29 Sep): '
         'the event lists the Stage B drafts that contain the token (<code>stage_b_review</code>); later Stage B will be refreshed from the Expansion output.'),
        ('Edit reading', 'Double-click a word (desktop), or double-tap / long-press it (iPhone), to edit that one word inline; Enter or leaving the box saves, Esc or '
         'Cancel cancels; empty or multi-word values are refused inline. Same path, checks and storage as Choose reading (action <code>edit_reading</code>, '
         'record <code>type: edit</code> with old \u2192 new, backup <code>_approve_backups/edit_reading/</code>, queue <code>kind: reading_edited</code> so the '
         'Entry Transcriber can add a curated line to <code>stageA/_learned_readings.jsonl</code>). An edit that removes a <code>[?]</code> counts as confirmed.'),
        ('Durability', 'Every status.py run re-applies active choices and edits if a rewrite brought the old token back (Stage A JSON unless locked, and the .md; '
         'never Stage B), backup <code>_approve_backups/reading_reapply/</code>, log <code>action=reading_reapply</code>, queue <code>reading_change_reapplied</code>.'),
        ('Locked entries', 'Approved/locked Stage A entries are read-only for choices and edits: no buttons or edit affordance (alternatives show \u201centry approved '
         '\u2014 locked\u201d) and the server answers 409. The \u2713 confirm keeps its existing behaviour.'),
        ('Undo (choice or edit)', 'Restores the old token in the Stage A JSON and .md, reverts only the Stage B draft values the change wrote, marks the record '
         '<code>undone</code> and appends a <code>type: undo</code> record (history kept); backup <code>_approve_backups/undo_reading/</code>, queue '
         '<code>kind: choose_reading_undone</code> or <code>reading_edit_undone</code>.'),
    ]
    h.append(sec('4. What each action does', ul([f'<b>{e(a)}</b>: {b}' for a, b in act]) +
                 '<p class="mnote">All actions: one click, no confirmation dialog, timestamped backups, atomic writes. Queue lines go to <code>dashboard/notify_queue.jsonl</code> '
                 '(read by Chief\u2019s watcher; Chief QC). Page Structure (stage0) is upstream of segmentation and has no dashboard action.</p>'))
    def lg(k, t): return f'<span class="lgc k-{k}">{e(t)}</span>'
    h.append(sec('5. Status words and chips (colour-blind safe)', '<p class="mnote">Okabe-Ito colours; every state also has its own symbol and border, so colour is never the only cue '
        '(checked in greyscale and a deuteranopia simulation). The chip class follows the chip <i>text</i>, so it changes in place when a poll or a click changes the state. '
        'Legend at the top of the Pipeline tab. Pipeline status columns: Segmentation \u2192 Transcription \u2192 <b>Expansion</b> (' + EXPANSION_HELP.lower() +
        '; producer: the Entry Expander, output in <code>stageA_expanded/&lt;folder&gt;/</code> (<code>&lt;entry_id&gt;.expanded.json</code> + <code>&lt;code&gt;_expanded.md</code>). '
        'It may start only after the row\u2019s transcription is Approved: before that ' + lg('none', 'Not started') + ' (never Queued/In progress, and an <code>overrides.json</code> <code>expansion</code> value is ignored). Then '
        + lg('proc', 'Queued') + ' (no output yet) \u2192 ' + lg('proc', 'In progress (d/N entries)') + ' (some entry files, or all without the .md) \u2192 ' + lg('need', 'Draft') +
        ' (all entries + .md, not all locked; links to <code>expansion/&lt;code&gt;.html</code> with Approve) \u2192 ' + lg('done', 'Approved') + ' (every entry <code>status: locked</code>). '
        'Stages reported by the Expander are applied with <code>setexp.py CODE queued|inprogress[:D/N]|clear</code> (used only while no entry file exists; files decide after that)) '
        '\u2192 Record Extraction (shows ' + lg('proc', 'Waiting on Expansion') + ' until that row\u2019s Expansion is Draft or Approved; rows that already have Stage B drafts or '
        'approved records keep their Draft/Approved chip, link and Approve button).</p>' + ul([
        lg('need', 'Needs you') + '<b>NEEDS STEPHEN</b> (most prominent): solid amber #e69f00, black bold text, 2px black border, \u26a0; gentle pulse unless the device asks for reduced motion. '
        'States: ' + lg('need', 'Queued for redo') + lg('need', 'Recut') + lg('need', 'Draft 2/5') + lg('need', 'Correction pending: \u2026') +
        ' (Queued for redo is on this list at Stephen\u2019s request, although the Entry Segmenter acts next). Also: the per-entry <b>Approve entry</b> buttons on unapproved entries, '
        'the DRAFT banner, and the <span class="qbadge">[?] 3</span> badge = unconfirmed readings in that entry.',
        lg('proc', 'Processing') + '<b>PROCESSING</b> (an agent or automated step is next): grey #eeeeee, #333 text, 1px dashed #888 border, \u23f3. States: ' +
        lg('proc', 'Redoing') + lg('proc', 'Queued') + lg('proc', 'First pass in progress') + lg('proc', 'In progress') + lg('proc', 'Transcriber updating\u2026') +
        lg('proc', 'On hold until crops approved') + ' (and extracting / transcribing / Approving\u2026 / Requesting\u2026). ' +
        lg('wait', 'Waiting on transcriber') + ' = still processing but pending over 30 min (symbol \u23f3!, darker dashed border).',
        lg('done', 'Approved') + '<b>DONE</b> (quiet): pale blue #e8f1fa, #0b4f8a text, 1px #0072b2 border, \u2713. States: Approved, locked, the in-place '
        '\u201cApproved \u2013 N crops locked at HH:MM CT\u201d chip, per-entry \u201cApproved HH:MM\u201d, and ' + lg('done', 'Updated') + ' (60 s after the transcriber finishes).',
        lg('none', 'Not started') + '<b>NOT STARTED</b>: white, #555 text, grey border, \u25cb (the previous stage is not finished yet).',
        lg('err', 'Blocked') + '<b>ERROR</b>: vermillion #d55e00, white bold text, \u2716 (Blocked / error / failed). Inline error messages after a click are vermillion and start with \u2716.',
        'Crop captions on segmentation pages: <span style="color:#0b4f8a;font-weight:700">locked</span> (blue) or <span style="color:#7a4a00;font-weight:700">pending</span> (brown). '
        'Buttons: \U0001F512 Approve (blue outline), \u2702 Recut with latest algorithm (blue dashed), \u2713 confirm reading (small blue outline).'])))
    h.append(sec('6. Versions and live counts', ul([
        'Segmentation algorithm versions in <code>ALGORITHM_VERSION.md</code>: ' + (', '.join(f'<code>{e(x)}</code>' for x in heads) or '–'),
        f'Combined manifest: {nman} crop lines (crop_status – {cnt(man)}); algorithm_version: {cnt(algo)}; lines without it: {nman - sum(algo.values())}.',
        f'segmenter_version: {cnt(segv)}.',
        f'Stage A entry files: {na} ({cnt(sa)}).',
        f'Stage B records with a schema: {nb} ({cnt(sb)}).',
        f'Rows: {len(rows)}. Segmentation \u2013 {cnt(st["segmentation"])}.',
        f'Transcription \u2013 {cnt(st["transcription"])}.', f'Expansion \u2013 {cnt(st["expansion"])}.', f'Extraction \u2013 {cnt(st["extraction"])}. Extraction pages show each Stage B record as labels and values (humanised field names; schema descriptions as tooltips), uncertainty as \u26a0 [?] + note, English/Deutsch translation blocks, a closed View JSON, and a Page metadata card at the top from <code>stageB/&lt;code&gt;/*_page_metadata.json</code> (never counted as a record or locked by Approve).',
        f'notify_queue.jsonl: {q if q is not None else "–"} lines; _approvals.log: {lg if lg is not None else "–"} lines.',
        f'Last refresh: {e(now.isoformat(timespec="seconds"))}.'])))
    h.append(sec('7. Backups and undo', ul([
        'Segmentation approve: restore <code>entries/&lt;book&gt;/manifest.jsonl.bak_approve_&lt;code&gt;_&lt;ts&gt;</code> and <code>entries/manifest.jsonl.bak_approve_&lt;code&gt;_&lt;ts&gt;</code>, '
        'plus <code>overrides.json</code> from the <code>.bakN</code> named in the response.',
        'Transcription, extraction, per-entry, confirm-reading: copy the files back from <code>_approve_backups/&lt;action&gt;/&lt;code&gt;_&lt;ts&gt;/</code> into '
        '<code>stageA/&lt;code&gt;/</code> or <code>stageB/&lt;code&gt;/</code> (confirm-reading also restores <code>_confirmed_readings.json</code> and <code>_feedback_status.json</code>; '
        'per-entry: remove the entry from <code>_entry_approvals.json</code>).',
        'Recut: <code>setseg.py &lt;code&gt; clear</code> or restore <code>overrides.json.bakN</code>.',
        'Correction: <code>setseg.py &lt;code&gt; clear</code> (archives the pending corrections as cancelled and removes the stage/hold), or restore '
        '<code>entries/_corrections/&lt;code&gt;.json</code> and <code>overrides.json</code> from <code>_approve_backups/segmentation_correction/&lt;code&gt;_&lt;ts&gt;/</code>.',
        'Hold <code>entries/.manifest.lock</code> while restoring, then run <code>status.py</code>. Queue lines are append-only: tell Chief to disregard the line.'])))
    return ''.join(h)

SELFTEST_JS = r"""
document.getElementById('go').onclick=function(){var b=this,o=document.getElementById('out');b.disabled=true;o.textContent='Sending…';
 var u=new URL('api/approve',location.href).href;
 fetch(u,{method:'POST',headers:{'Content-Type':'application/json','X-OPR-Approve':'1'},body:JSON.stringify({code:'TEST0000',action:'selftest'})})
 .then(function(x){if(window.oprAuth&&window.oprAuth.fail(x)){o.textContent=window.oprAuth.login()?'Login required, opening the login page…':'Login required, please log in again';b.disabled=false;return;}return x.text().then(function(t){o.textContent='POST '+u+'\nHTTP '+x.status+'\n'+t;b.disabled=false;});})
 .catch(function(e){o.textContent='POST '+u+'\nfailed: '+e;b.disabled=false;});};
"""
def write_selftest_page():
    """out/_selftest.html: hidden (noindex, not linked anywhere) one-button page for Site Host's end-to-end test of the
    approve path through the login. Hits action 'selftest' / code 'TEST0000', which writes only dashboard/_selftest/."""
    page = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            + NOCACHE + '<script>' + _auth_js('') + '</script><title>OPR dashboard – approve self-test</title>'
            '<style>body{font:15px/1.5 system-ui,sans-serif;margin:24px;max-width:760px}button{font:inherit;padding:6px 16px}'
            'pre{background:#f4f4f4;padding:10px;white-space:pre-wrap;word-break:break-all}</style></head><body>'
            '<h1>Approve self-test</h1><p>Sends <code>{"code":"TEST0000","action":"selftest"}</code> to <code>api/approve</code> '
            '(relative to this page) with the <code>X-OPR-Approve</code> header. The server writes only to its self-test folder: '
            'no manifests, Stage A/B, overrides, approvals log or notify queue are touched.</p>'
            '<button id="go" type="button">Run self-test</button><pre id="out"></pre>'
            '<script>' + SELFTEST_JS + '</script></body></html>\n')
    fd, tmp = tempfile.mkstemp(dir=OUT); os.write(fd, page.encode()); os.close(fd)
    os.chmod(tmp, 0o644); os.replace(tmp, os.path.join(OUT, '_selftest.html'))

if __name__ == '__main__':
    d = main()
    for r in d['rows']: print(f"{r['code']:6} {r['segmentation']['status']:30} {r['transcription']['status']:14} {r['extraction']['status']}")
