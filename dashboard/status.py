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
    return by

def is_locked(e):
    return 'locked' in (str(e.get('crop_status', '')).lower(), str(e.get('status', '')).lower())

def seg(img, man):
    ents = man.get(img, [])
    if ents:
        nl = sum(map(is_locked, ents))
        if nl == len(ents): return 'Approved', f'{len(ents)} crops, all approved'
        return 'Draft', f'{len(ents)} crops' + (f', {nl} locked' if nl else '')
    tail = img.split('Horn_', 1)[-1]                      # KB007-01-T_0405
    if glob.glob(f'{W}/stage0/{img}_*') or glob.glob(f'{W}/stage0_work/*{tail}*'):
        return 'Queued (page layout running)', 'Stage 0 files present, no crops yet'
    return None, ''

def trans(code, img, man):
    d = os.path.join(W, 'stageA', code)
    if not os.path.isdir(d) or not glob.glob(os.path.join(d, '*.diplomatic.json')):
        try: sent = set(json.load(open(os.path.join(D, 'auto_transcribe_sent.json'))).get('dispatched', []))
        except Exception: sent = set()
        if img in sent or f'{img}_L' in sent or f'{img}_R' in sent or seg(img, man)[0] == 'Approved':
            return 'Queued', 'segmentation approved; sent to transcriber'
        return None, ''
    js = glob.glob(os.path.join(d, '*.diplomatic.json'))
    need = {e['entry_id'] for e in man.get(img, []) if e.get('entry_kind') != 'blank'}
    have = {os.path.basename(p)[:-len('.diplomatic.json')] for p in js}
    md = glob.glob(os.path.join(d, f'{code}_stageA.md'))
    if need and need <= have and md:
        st = set()
        for p in js:
            try: st.add(str(json.load(open(p)).get('status', '')).lower())
            except Exception: st.add('?')
        if st and st <= {'approved', 'locked', 'final'}: return 'Approved', f'{len(have)} entries approved'
        return 'Draft', f'{len(have & need)}/{len(need)} entries'
    return 'In progress', f'{len(have & need)}/{len(need) or "?"} entries' + ('' if md else ', no summary .md yet')

def extr(code, img):
    hits = []
    for base in (f'{W}/records', f'{W}/stageB'):
        for p in glob.glob(f'{base}/**/*', recursive=True):
            n = os.path.basename(p)
            if os.path.isfile(p) and (code in n or img in n or img.replace('Horn_', '') in n or f'_{code}_' in n):
                hits.append(p)
    if not hits: return None, ''
    st = set()
    for p in hits:
        if p.endswith('.json'):
            try:
                j = json.load(open(p))            # Stage B schema: stage_b_status ('status' in records can be a person's status)
                st.add(str(j.get('stage_b_status') if 'stage_b_status' in j else j.get('status', '')).lower())
            except Exception: pass
    if st and st <= {'locked', 'approved', 'final'}: return 'Approved', f'{len(hits)} file(s)'
    return 'Draft', f'{len(hits)} file(s)'

MBASE = 'https://data.matricula-online.eu/de/deutschland/paderborn/'
def mlink(r):
    """Every row gets collection + pg + url. url field wins; else collection+book+pg (pg defaults to printed page digits)."""
    col = r.get('collection') or 'DE_EBAP_22212'
    pg = r.get('pg') or (''.join(ch for ch in str(r.get('page', '')).split('\u2013')[-1] if ch.isdigit()) or None)
    url = r.get('url') or (f"{MBASE}{col}/{r['book']}/" + (f"?pg={pg}" if pg else ''))
    return {'collection': col, 'pg': pg, 'url': url}

# ---- Draft extraction pages: out/extraction/<code>.html for every row whose extraction status is Draft ----
import html as _html, re as _re
def _enum(name):
    m = _re.search(r'_e(\d+)(?:[._]|$)', name); return int(m.group(1)) if m else 10**6

def _etag(eid):
    m = _re.search(r'((?:[LR]_)?e\d+)$', str(eid)); return m.group(1) if m else str(eid)

def _stagea_text(code):
    d = os.path.join(W, 'stageA', code); blocks = []
    for p in sorted(glob.glob(os.path.join(d, '*.diplomatic.json')), key=lambda q: (_enum(os.path.basename(q)), q)):
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception as ex: blocks.append(f'--- {os.path.basename(p)}: unreadable ({ex}) ---'); continue
        eid = j.get('entry_id') or os.path.basename(p)[:-len('.diplomatic.json')]
        lab = ', '.join(str(x) for x in (j.get('segment_label'), j.get('entry_kind')) if x)
        t = f'--- {_etag(eid)}' + (f' ({lab})' if lab else '') + ' ---\n' + str(j.get('diplomatic_text') or '')
        if j.get('diplomatic_margin'): t += '\n[margin] ' + str(j['diplomatic_margin'])
        blocks.append(t)
    if blocks: return '\n\n'.join(blocks), 'Stage A diplomatic JSON (diplomatic_text)'
    md = os.path.join(d, f'{code}_stageA.md')
    if os.path.isfile(md): return open(md, encoding='utf-8').read(), f'{code}_stageA.md'
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
CHIP_JS = "(function(){if(window.oprKind)return; var KS=['k-done','k-need','k-proc','k-wait','k-err','k-none'],SEL='.chip,.segchip,.fbchip,.entok,.corrpend,.corrsent'; function K(t){t=String(t||'').replace(/^[\\s\\u2713\\u26a0\\ufe0e\\u23f3\\u2716\\u25cb!]+/,'').toLowerCase();if(!t)return ''; if(/^(blocked|error|failed|not sent|not done|not approved)/.test(t))return 'err'; if(/^(queued for redo|correction (pending|sent)|recut|draft)/.test(t))return 'need'; if(/^waiting on transcriber/.test(t))return 'wait'; if(/hold|^redoing|^queued|progress|running|transcrib|extracting|updating|first pass|sending|requesting|approving/.test(t))return 'proc'; if(/^(approved|locked|updated|done|complete)/.test(t))return 'done'; if(/^not started/.test(t))return 'none';return '';} function apply(){[].forEach.call(document.querySelectorAll(SEL),function(el){var k=K(el.textContent),c=k?'k-'+k:''; KS.forEach(function(x){if(x!==c&&el.classList.contains(x))el.classList.remove(x);});if(c&&!el.classList.contains(c))el.classList.add(c);}); [].forEach.call(document.querySelectorAll('details.ent'),function(d){var a=d.querySelector('summary .entact');if(!a)return; var n=d.querySelectorAll('.tq:not(.confirmed) .qm').length,b=a.querySelector('.qbadge'); if(n){if(!b){b=document.createElement('span');b.className='qbadge';b.title='Unconfirmed readings [?] in this entry (tap \\u2713 next to each to confirm)';a.insertBefore(b,a.firstChild);} var t='[?] '+n;if(b.textContent!==t)b.textContent=t;}else if(b)b.remove();});} window.oprKind=K;window.oprKindApply=apply;var q=0; function sch(){if(q)return;q=1;setTimeout(function(){q=0;apply();},0);} function start(){apply();new MutationObserver(sch).observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['class']});} if(document.body)start();else document.addEventListener('DOMContentLoaded',start);})();"
def _kind(st):
    t = re.sub(r'^[\s\u2713\u26a0\ufe0e\u23f3\u2716\u25cb!]+', '', str(st or '')).lower()
    if not t: return ''
    if re.match(r'(blocked|error|failed|not sent|not done|not approved)', t): return 'err'
    if re.match(r'(queued for redo|correction (pending|sent)|recut|draft)', t): return 'need'
    if t.startswith('waiting on transcriber'): return 'wait'
    if re.search(r'hold|^redoing|^queued|progress|running|transcrib|extracting|updating|first pass|sending|requesting|approving', t): return 'proc'
    if re.match(r'(approved|locked|updated|done|complete)', t): return 'done'
    if t.startswith('not started'): return 'none'
    return ''
PAGE_CSS = ('body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:20px;color:#222}h1{font-size:20px;margin:0 0 6px}'
    '.hdr{background:#eef2f8;border:1px solid #d5dce8;border-radius:8px;padding:10px 14px;margin-bottom:16px;line-height:1.6}'
    'h2{font-size:17px;color:#1a3d7c;margin:18px 0 6px}pre{white-space:pre-wrap;word-wrap:break-word;'
    'font-family:Menlo,Consolas,"DejaVu Sans Mono",monospace;font-size:13px;background:#fafafa;border:1px solid #ddd;border-radius:6px;padding:10px}'
    'pre.stagea-text{font-size:calc(13px * 1.5)}.stk{position:sticky;top:0;z-index:10;background:#fff;margin:0 -20px 14px;padding:8px 20px;border-bottom:1px solid #c9d2e0;box-shadow:0 3px 6px -3px rgba(0,0,0,.2)}.stk .hdr{margin-bottom:0}.stk #tg{margin:8px 0 0}.stk .draftban{margin:8px 0 0}.apvbox{float:right;margin:0 0 6px 24px;text-align:right;max-width:45%}.apv{padding:6px 18px;font-weight:700;font-size:14px;background:#fff;color:#0072b2;border:2px solid #0072b2;border-radius:6px;cursor:pointer;box-shadow:0 1px 2px rgba(0,0,0,.15)}.apv:hover{background:#0072b2;color:#fff}.entact{float:right}.entapv{margin-left:8px;padding:2px 10px;font-size:12px;font-weight:800;background:#e69f00;color:#000;border:2px solid #000;border-radius:5px;cursor:pointer}.entapv::before{content:"\\26a0\\fe0e\\00a0"}.entapv:disabled{opacity:.6}.entok{margin-left:8px;padding:1px 9px;font-size:12px;border-radius:10px}.fbchip{margin-left:8px;padding:1px 9px;font-size:12px;font-weight:700;border-radius:10px}.ck{margin:0 2px 0 1px;padding:0 4px;font-size:11px;line-height:15px;border:1px solid #0072b2;color:#0072b2;background:#fff;border-radius:4px;cursor:pointer;vertical-align:1px}.ck:disabled{opacity:.5}.tq .qm{color:#b36b00}.tq.confirmed{background:#e8f1fa;border-radius:3px;transition:background 3s}.ckerr{color:#d55e00;font-size:12px;font-weight:700;margin-left:4px}.rcb{padding:5px 14px;font-weight:600;font-size:13px;background:#fff;color:#0b4f8a;border:2px dashed #0072b2;border-radius:6px;cursor:pointer}.rcb:hover{background:#e8f1fa}.rcb:disabled{opacity:.6;cursor:wait}.apv:disabled{opacity:.6;cursor:wait}#apvmsg{display:block;font-size:12px;margin-top:4px}.chip{display:inline-block;padding:1px 10px;border-radius:12px;font-size:13px;font-weight:700}details.ent,figure.crop,h2{scroll-margin-top:calc(var(--stkh,170px) + 10px)}.rec h3{font-size:15px;margin:14px 0 4px}.fn{font-weight:400;color:#666;font-size:12px;font-family:monospace}a{color:#1a5fb4}.src{color:#777;font-size:12px}')

def _stagea_entries(code):
    """{entry_no: [(tag, label, text), ...]} from Stage A diplomatic JSON (several parts when an entry spans L/R faces)."""
    d = os.path.join(W, 'stageA', code); out = {}
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

def write_extraction_pages(rows):
    xd = os.path.join(OUT, 'extraction'); os.makedirs(xd, exist_ok=True); made = []; bundles = []
    E = lambda t: _html.escape(str(t if t is not None else ''), quote=True)
    for r in rows:
        xs = str(r['extraction']['status']).lower()
        if not xs.startswith(('draft', 'approved')): continue
        nb, nbl = _json_field_counts([p for p in glob.glob(os.path.join(W, 'stageB', r['code'], '*.json')) if '.bak' not in os.path.basename(p)], 'stage_b_status', 'status')
        c = r['code']; r['extraction']['link'] = f'extraction/{c}.html'
        booku = f"{MBASE}{r['collection']}/{r['book']}/?pg=1"      # title page (BOOKPG in index.html: all books = 1)
        sa = _stagea_entries(c); mdfull = ''
        if not sa:
            md = os.path.join(W, 'stageA', c, f'{c}_stageA.md')
            if os.path.isfile(md): mdfull = open(md, encoding='utf-8').read()
        sb = _stageb_records(c)
        nrec = sum(len(v) for v in sb.values()); secs = []
        for n in sorted(set(sa) | set(sb)):
            en = f'e{n}' if n < 10**6 else 'e?'
            recs = sb.get(n, [])
            if recs:
                dt, nm = _sb_summary(recs[0][1])
                summ = f'<b>{E(en)}</b>' + (f' \u00b7 {E(dt)}' if dt else '') + (f' \u00b7 {E(nm)}' if nm else '')
                if not (dt or nm): summ += f' \u00b7 <span class="fn">{E(recs[0][0])}</span>'
            else:
                lab = ', '.join(x[1] for x in sa.get(n, []) if x[1])
                summ = f'<b>{E(en)}</b>' + (f' \u00b7 <span class="fn">{E(lab)}</span>' if lab else '') + ' <span class="miss">no Stage B record</span>'
            if n in sa:
                a = ''.join(f'<h3>Stage A diplomatic text <span class="fn">{E(tag)}{(" \u00b7 " + E(lab)) if lab else ""}</span></h3>'
                            f'<pre class="transcription stagea-text">{E(t)}</pre>' for tag, lab, t in sa[n])
            elif mdfull:
                a = f'<p class="miss">Stage A: no diplomatic JSON for this entry; see the full {E(c)}_stageA.md at the top of the page.</p>'
            else:
                a = '<p class="miss">MISSING: no Stage A diplomatic text for this entry.</p>'
            b = ''.join(f'<h3>Stage B record <span class="fn">{E(fn)}</span></h3><pre>{E(body)}</pre>' for fn, j, body in recs) \
                or '<p class="miss">MISSING: no Stage B record for this entry.</p>'
            secs.append(f'<details class="ent" id="{E(en)}"><summary>{summ}</summary><div class="body">{a}{b}</div></details>\n')
        top = (f'<h2>Stage A summary ({E(c)}_stageA.md, fallback)</h2><pre class="transcription stagea-text">{E(mdfull)}</pre>\n' if mdfull else '')
        page = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">' + NOCACHE + '<script>' + CHIP_JS + '</script>\n'
            f'<title>Row {E(r["id"])} {E(c)} \u2013 {"draft extraction" if xs.startswith("draft") else "extraction"}</title><style>{PAGE_CSS}{CHIP_CSS}'
            'details.ent{border:1px solid #d5dce8;border-radius:6px;margin:0 0 8px;background:#fff}'
            'details.ent summary{cursor:pointer;padding:8px 12px;font-size:15px;background:#f5f7fb;border-radius:6px}'
            'details.ent[open] summary{border-bottom:1px solid #d5dce8;border-radius:6px 6px 0 0}'
            'details.ent .body{padding:4px 12px 10px}.miss{color:#d55e00;font-weight:600;font-size:13px}'
            '#tg{margin:0 0 10px;padding:4px 12px;cursor:pointer}</style></head><body>\n'
            '<p><a href="../index.html">&larr; Dashboard</a></p>\n'
            f'<h1>Row {E(r["id"])}: {E(r["name"])} <span class="fn">({E(c)})</span> \u2013 Record extraction: {E(r["extraction"]["status"])}</h1>\n'
            + _sticky(r, 'Extraction', r["extraction"]["status"], E,
                btn=('' if not (xs.startswith('draft') and EXTRACTION_APPROVE_ENABLED and nb) else _lock_note(nbl, nb, 'Stage B records', E) if nbl else
                     ' ' + _approve_btn(r, 'extraction', f"Approve the extraction of row {r['id']} ({c})? This locks all {nb} Stage B record file(s) in stageB/{c}/.")),
                line2=(f'<b>Name</b> {E(r["name"])}{(" &times; " + E(r["spouse"])) if r.get("spouse") else ""} &nbsp; '
                       f'<b>Date</b> {E(r.get("date"))} &nbsp; <b>Type</b> {E(r.get("type"))} &nbsp; <b>Image</b> {_img_link(r, E)} &nbsp; '
                       f'<a href="{E(r["url"])}" target="_blank" rel="noopener">Matricula page</a> &nbsp;|&nbsp; '
                       f'<a href="{E(booku)}" target="_blank" rel="noopener">Book title page</a>'),
                below=TOGGLE_JS) +
            f'<h2>Entries ({len(secs)}; {nrec} {"draft " if xs.startswith("draft") else ""}Stage B record(s))</h2>\n' + top +
            (''.join(secs) or '<p>(no entries found)</p>\n') +
            f'<p class="src">Generated {E(datetime.datetime.now().astimezone().isoformat(timespec="seconds"))} by status.py</p>\n'
            + OPEN_JS +
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
    for p in glob.glob(os.path.join(W, 'stageA', code, f'*_e{n}.diplomatic.json')):
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
    d = os.path.join(W, 'stageA', code); out = {}
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
    try: v = json.load(open(os.path.join(W, 'stageA', code, '_confirmed_readings.json'), encoding='utf-8'))
    except Exception: return []
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []

def _render_tokens(text, eid, field, conf, E, regained):
    """HTML for a Stage A text: every <token>[?] gets a one-click confirm control. A token already confirmed by Stephen
    (listed in _confirmed_readings.json) whose [?] came back in a re-run is shown WITHOUT [?] and reported in `regained`."""
    out = []; last = 0; cnt = {}
    mine = [x for x in conf if x.get('entry_id') == eid and x.get('field', 'diplomatic_text') == field]
    for m in TOKRE.finditer(text):
        tok = m.group(1); cnt[tok] = cnt.get(tok, 0) + 1; occ = cnt[tok]
        out.append(E(text[last:m.start()])); last = m.end()
        before = text[:m.start()]
        hit = next((x for x in mine if x.get('token') == tok and (before.endswith(str(x.get('context_before', ''))[-12:]) if x.get('context_before') else x.get('occurrence') == occ)), None)
        if hit:
            regained.append({'entry_id': eid, 'field': field, 'token': tok, 'occurrence': occ})
            out.append(f'<span class="tq regained" title="Confirmed by Stephen {E(hit.get("time", ""))}; the source regained [?] and it is hidden here">{E(tok)}</span>')
            continue
        ctx = before[-20:]
        out.append(f'<span class="tq">{E(tok)}<span class="qm">[?]</span></span><button class="ck" onclick="oprConfirm(this)" '
                   f'data-e="{E(eid)}" data-f="{E(field)}" data-t="{E(tok)}" data-o="{occ}" data-c="{E(ctx)}" title="Confirm this reading (one click)">&#10003;</button>')
    out.append(E(text[last:]))
    return ''.join(out)

def _feedback(code):
    """Tolerant reader of stageA/<code>/_feedback_status.json -> {entry_id: {state, oldest_pending, updated_at}}."""
    try: fb = json.load(open(os.path.join(W, 'stageA', code, '_feedback_status.json'), encoding='utf-8'))
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
function oprEntryApprove(ev,b){ev.preventDefault();ev.stopPropagation();oprPost(b,{code:__CODE__,action:'approve_transcription_entry',entry_id:b.dataset.e},'Approving\u2026',
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
        na, nal = _json_field_counts(glob.glob(os.path.join(W, 'stageA', r['code'], '*.diplomatic.json')), 'status')
        if not (sl.startswith('approved') or sl.startswith('draft')): continue
        c = r['code']; r['transcription']['link'] = f'transcription/{c}.html'
        sa = _stagea_parts(c); sb = _stageb_records(c); mdfull = ''; scr = _stagea_crops(c); pub = _PUB.get(c, {})
        conf = _confirmed(c); regained = []; draft = sl.startswith('draft')
        ents = {eid: ('locked' if lk else 'soft') for parts in sa.values() for _, _, eid, lk, _ in parts}
        r['transcription']['entries'] = ents; r['transcription']['feedback'] = _feedback(c)
        if draft and ents: r['transcription']['progress'] = f"{sum(v == 'locked' for v in ents.values())}/{len(ents)}"
        if not sa:
            md = os.path.join(W, 'stageA', c, f'{c}_stageA.md')
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
                                     f'<pre class="transcription stagea-text">{_render_tokens(t, eid, fld, conf, E, regained)}</pre>' for fld, t in flds)
                           for tag, l, eid, lk, flds in sa[n])
            secs.append(f'<details class="ent" id="{E(en)}"><summary>{summ}</summary><div class="body">{body}</div></details>\n')
        banner = ('<div class="draftban" style="background:#e69f00;border:2px solid #000;border-radius:8px;padding:10px 14px;margin:0 0 14px;'
                  'font-weight:800;font-size:16px;color:#000">\u26a0\ufe0e DRAFT \u2013 this transcription is not yet approved (needs your Approve).</div>\n'
                  if sl.startswith('draft') else '')
        spouse = (' &times; ' + E(r['spouse'])) if r.get('spouse') else ''
        page = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">' + NOCACHE + '<script>' + CHIP_JS + '</script>\n'
            f'<title>Row {E(r["id"])} {E(c)} \u2013 transcription</title><style>{PAGE_CSS}{CHIP_CSS}{DETAILS_CSS}figure.crop{{margin:8px 0}}figure.crop img{{max-width:100%;height:auto;display:block;border:1px solid #ddd}}</style></head><body>\n'
            '<p><a href="../index.html">&larr; Dashboard</a></p>\n'
            f'<h1>Row {E(r["id"])}: {E(r["name"])} <span class="fn">({E(c)})</span> \u2013 Transcription</h1>\n'
            + _sticky(r, 'Transcription', st, E,
                btn=('' if not (TRANSCRIPTION_APPROVE_ENABLED and sl.startswith('draft') and na and nal < na) else
                     ' ' + _approve_btn(r, 'transcription') + (f'<div class="src">{nal} of {na} entries already approved; the row button locks the remaining {na - nal}</div>' if nal else '')),
                line2=(f'<b>Date</b> {E(r.get("date"))} &nbsp; <b>Type</b> {E(r.get("type"))}{spouse and " &nbsp; <b>Spouse</b> " + E(r["spouse"])} &nbsp; '
                       f'<b>Image</b> {_img_link(r, E)} &nbsp; <a href="{E(r["url"])}" target="_blank" rel="noopener">Matricula page</a>'),
                below=banner + TOGGLE_JS) +
            f'<h2>Stage A diplomatic text ({len(secs)} entries)</h2>\n' +
            (f'<div class="src">source: {E(c)}_stageA.md (no diplomatic JSON)</div><pre class="transcription stagea-text">{_render_tokens(mdfull, f"{c}_stageA.md", "md", conf, E, regained)}</pre>\n' if mdfull else '') +
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

_PUB = {}   # code -> {abs source path | source stem: ('<code>/<file>.jpg', source mtime)}, filled by write_segmentation_pages

def _stagea_crops(code):
    """{entry_no: [crop source paths in L-then-R order]} referenced by Stage A diplomatic JSON."""
    out = {}
    for p in sorted(glob.glob(os.path.join(W, 'stageA', code, '*.diplomatic.json')), key=lambda q: (_enum(os.path.basename(q)), q)):
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
    unit = {'segmentation': 'crops', 'transcription': 'entries', 'extraction': 'records', 'recut': ''}[action]
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
 window.oprPage=function(p){if(window.oprBusy||!p||p.code!==C||p.kind!==K||p.rev===REV)return;
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
    return f'{MATRICULA_BASE}{r.get("collection") or "DE_EBAP_22212"}/{r["book"]}/?pg=1' if r.get('book') else ''
def _img_link(r, E):
    return _hl(r.get('url'), r.get('image'), E, 'Open this image on Matricula (new tab)')

# ---------------- Record type (register) shown in every detail-page header and in the Pipeline table: ONE mapping for both ----------------
# Order (never guess): 1) records.json row 'type'  2) register_type in the crop manifests for that image  3) register_type anywhere in
# the same book's manifest entries  4) the book-code suffix  -> otherwise 'Type unknown'. If 1) and 2) disagree -> 'Type unknown'.
# German terms are Matricula's own register titles. Suffix convention checked 29 Sep 2026 against the Matricula titles of every book in use:
#   DE_EBAP_22212 (Horn): KB004-02-T Taufen 1760-1799, KB004-06-T Taufen 1800-1807, KB005-02-H Trauungen 1760-1807,
#   KB006-01-S Sterbefälle 1760-1807, KB007-01-T Taufen 1808-1837, KB010-01-S Sterbefälle 1808-1851;  DE_EBAP_23815 (Warstein): KB013-01-S Sterbefälle 1843-1882.
RECORD_TYPES = {'baptisms': ('Baptisms', 'Taufen'), 'marriages': ('Marriages', 'Trauungen'), 'burials': ('Burials/Deaths', 'Sterbefälle'),
                'communion': ('First Communion', 'Erstkommunion'), 'confirmation': ('Confirmations', 'Firmungen'), 'notes': ('Notes', None)}
_TYPE_WORDS = [('baptisms', r'bapti|taufe|geburt|birth'), ('marriages', r'marri|trauung|heirat|ehe|wedding'),
               ('burials', r'buri|death|sterbe|begr(ä|ae|a)bni|tote|verstorb'), ('communion', r'communion|kommunion'),
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
def record_type(r):
    """-> {'key','en','de','label','source'} for a records.json row (see the order above)."""
    reg = _register_types()
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

def _seg_header(r, st, n, E, ents=()):
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
        img = imgs.get(r['code']); ents = sorted(man.get(img, []), key=_seg_key); stg = _stage(sl)
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
            blocks.append(f'<figure class="crop"><figcaption><b>Entry {E(lab)}</b> <span class="st" style="color:{col};border-color:{col}">{cs}</span> '
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
            q = os.path.join(W, 'entries', '_qc', f'{img}_redo_{kind}.jpg'); fn = f'qc_{kind}.jpg'
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
            '.st{border:1px solid;border-radius:10px;padding:0 8px;font-size:12px;font-weight:700;margin-left:6px}.lbl{font-weight:600;color:#1a3d7c;margin-left:6px}.desc{color:#555;font-size:12px;margin-top:2px}</style></head><body>\n'
            '<p><a href="../index.html">&larr; Dashboard</a></p>\n'
            f'<h1>Row {E(r["id"])}: {E(r["name"])} <span class="fn">({E(c)})</span> \u2013 Segmentation</h1>\n'
            + _seg_header(r, st, len(ents), E, ents)
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

def main():
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
        c, img = r['code'], r['image_id']; o = ov.get(c, {}) if isinstance(ov.get(c), dict) else {}
        cells = {}
        for k, fn in (('segmentation', lambda: seg(img, man)), ('transcription', lambda: trans(c, img, man)),
                      ('extraction', lambda: extr(c, img))):
            v, why = fn(); src = 'files'
            if v is None: v, why, src = r.get('baseline', {}).get(k, NS), '', 'baseline'
            if k in o: v, why, src = o[k], o.get('note', ''), 'override'
            cells[k] = {'status': v, 'detail': why, 'source': src}
        rows.append({**{k: r[k] for k in ('id', 'group', 'name', 'spouse', 'date', 'type', 'book', 'image', 'page', 'code')},
                     'town': r.get('town') or towns.get(r['book'], ''), 'record_type': record_type(r),
                     **mlink(r), **cells})
    os.makedirs(OUT, exist_ok=True); write_extraction_pages(rows); write_segmentation_pages(rows, man); write_transcription_pages(rows, man)   # also set .link on linked chips
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
        if '.bak' in os.path.basename(p): continue
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception: continue
        if isinstance(j, dict) and j.get('schema_version'): sb[f"{j.get('schema_id') or '?'} {j['schema_version']}"] += 1; nb += 1
    sa = collections.Counter(); na = 0
    for p in glob.glob(os.path.join(W, 'stageA', '*', '*.diplomatic.json')):
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception: continue
        na += 1; sa[str(j.get('schema_version') or j.get('schema_id') or '(no schema field)')] += 1
    st = {k: collections.Counter() for k in ('segmentation', 'transcription', 'extraction')}
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
    ]
    h.append(sec('4. What each action does', ul([f'<b>{e(a)}</b>: {b}' for a, b in act]) +
                 '<p class="mnote">All actions: one click, no confirmation dialog, timestamped backups, atomic writes. Queue lines go to <code>dashboard/notify_queue.jsonl</code> '
                 '(read by Chief\u2019s watcher; Chief QC). Page Structure (stage0) is upstream of segmentation and has no dashboard action.</p>'))
    def lg(k, t): return f'<span class="lgc k-{k}">{e(t)}</span>'
    h.append(sec('5. Status words and chips (colour-blind safe)', '<p class="mnote">Okabe-Ito colours; every state also has its own symbol and border, so colour is never the only cue '
        '(checked in greyscale and a deuteranopia simulation). The chip class follows the chip <i>text</i>, so it changes in place when a poll or a click changes the state. '
        'Legend at the top of the Pipeline tab.</p>' + ul([
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
        f'Transcription \u2013 {cnt(st["transcription"])}.', f'Extraction \u2013 {cnt(st["extraction"])}.',
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
