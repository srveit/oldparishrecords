"""Added rows ('＋ Add row' on the dashboard): shared by approve_server.py (add_row / update_row / delete_row) and the CLIs
setresearch.py / updaterow.py, so every path writes records.json the same way.

records.json fields of an added row (same as existing rows, plus the added_* / research / seg_* bookkeeping):
  id, group (default 'Added rows'; any group name, created on first use), name, type, book, image, page, code, image_id, date, spouse, collection, pg, url,
  [town], [diocese] (only when not paderborn, from a pasted Matricula URL), [book_url], [notes], added_by 'Stephen dashboard', added_at (CT ISO), research ('Researching' | 'Page found' | ''),
  [seg_requested (time), seg_requested_for 'book|image|page'], [updated_at, updated_by]
Row ids are never reused: next id = max(records ids, records_meta.json high_water_id, ids in _deleted_rows.jsonl) + 1.
Codes: 'N' + 4-digit id (N0023), never a book-suffix letter (T/H/S), checked against every existing/deleted code and Stage A folder.
Every write: entries/.manifest.lock (same lock as approve_server/setseg), records.json backup to the next free .bakN,
atomic replace, _approvals.log line, notify_queue.jsonl event(s)."""
import datetime, fcntl, glob, json, os, re, shutil, tempfile, time

BY = 'Stephen dashboard'
GROUP = 'Added rows'
TYPES = ['Birth', 'Baptism', 'Marriage', 'Burial', 'Confirmation/Communion', 'Other']
ORIGINAL_GROUPS = ('Family of Caspar Anton Wilmes gen. Herweg', 'Other Wilmes records', 'Other Horn pages')   # never removed
MROOT = 'https://data.matricula-online.eu/de/deutschland/'
def mbase(diocese): return f'{MROOT}{diocese or "paderborn"}/'
MBASE = mbase('paderborn')
TOWN_COLL = {'horn': ('paderborn', 'DE_EBAP_22212'), 'warstein': ('paderborn', 'DE_EBAP_23815')}   # only towns whose Matricula home is known
COLL_TOWN = {v[1]: k.capitalize() for k, v in TOWN_COLL.items()}
DEFAULT_COLL = ''     # other towns without a URL: NO collection and NO links (never guess DE_EBAP_22212)
LIMITS = {'group': 120, 'name': 200, 'type_other': 80, 'town': 80, 'book': 40, 'image': 20, 'page': 20, 'date': 60, 'spouse': 200,
          'notes': 2000, 'book_url': 400, 'url': 400}
FIELDS = ('name', 'record_type', 'type_other', 'town', 'book', 'image', 'page', 'date', 'spouse', 'notes', 'book_url', 'url')

class RowError(Exception):
    def __init__(self, msg, http=409): super().__init__(msg); self.http = http

class Ctx:
    def __init__(self, W, D):
        self.W, self.D = W, D
        self.records = os.path.join(D, 'records.json'); self.meta = os.path.join(D, 'records_meta.json')
        self.deleted = os.path.join(D, '_deleted_rows.jsonl'); self.notifyq = os.path.join(D, 'notify_queue.jsonl')
        self.overrides = os.path.join(D, 'overrides.json')
        self.log = os.path.join(W, 'entries', '_approvals.log'); self.lockf = os.path.join(W, 'entries', '.manifest.lock')

def now_ct(): return datetime.datetime.now().astimezone().isoformat(timespec='seconds')

def next_bak(p):
    n = 1
    for q in glob.glob(p + '.bak*'):
        m = re.fullmatch(re.escape(p) + r'\.bak(\d+)', q)
        if m: n = max(n, int(m.group(1)) + 1)
    return f'{p}.bak{n}'

def lock(ctx, timeout=15):
    lf = open(ctx.lockf, 'a+'); t0 = time.time()
    while True:
        try: fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB); return lf
        except BlockingIOError:
            if time.time() - t0 > timeout: lf.close(); raise RowError('lock is held by another writer; try again', 503)
            time.sleep(0.2)

def unlock(lf): fcntl.flock(lf, fcntl.LOCK_UN); lf.close()

def _atomic(path, text):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.rowedit-', suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f: f.write(text); f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, 0o644); os.replace(tmp, path)

def load(ctx): return json.load(open(ctx.records, encoding='utf-8'))

def save(ctx, recs):
    bak = next_bak(ctx.records); shutil.copy2(ctx.records, bak)
    _atomic(ctx.records, json.dumps(recs, ensure_ascii=False, indent=1) + '\n')
    return os.path.basename(bak)

def notify(ctx, evt):
    with open(ctx.notifyq, 'a', encoding='utf-8') as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.write(json.dumps(evt, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())

def log(ctx, stamp, action, row, code, text, client):
    with open(ctx.log, 'a', encoding='utf-8') as f:
        f.write(f'{stamp}\taction={action}\trow {row}\t{code}\t{text}\tby={BY}\tclient={client}\n')

def _deleted(ctx):
    out = []
    try:
        for l in open(ctx.deleted, encoding='utf-8'):
            try: out.append(json.loads(l))
            except ValueError: pass
    except FileNotFoundError: pass
    return out

def clean(v, k):
    s = '' if v is None else str(v)
    s = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', s).strip() if k == 'notes' else re.sub(r'[\x00-\x1f\x7f]+', ' ', s).strip()
    if len(s) > LIMITS.get(k, 200): raise RowError(f'{k} is too long (max {LIMITS.get(k, 200)} characters); nothing saved', 400)
    return s

_URLRE = re.compile(r'https?://data\.matricula-online\.eu/[a-z]{2}/[^/?#]+/([^/?#]+)/([^/?#]+)/([^/?#]+)/?(?:\?(?:[^#]*&)?pg=(\d+))?')
def parse_url4(u):
    """Matricula URL .../<lang>/<country>/<diocese>/<collection>/<book>/?pg=N -> (diocese, collection, book, pg); Nones if not one."""
    m = _URLRE.match(u or '')
    return (m.group(1), m.group(2), m.group(3), int(m.group(4)) if m.group(4) else None) if m else (None, None, None, None)
def parse_url(u):
    """(collection, book, pg) - kept for callers of the old signature."""
    return parse_url4(u)[1:]

def page_digits(p): return ''.join(ch for ch in str(p or '').split('\u2013')[-1].split('-')[-1] if ch.isdigit())

def coll_for(rec, recs):
    """(diocese, collection): given page/book URL > town Horn/Warstein (paderborn) > another row with the same book (only when
    the town is empty or matches) > ('', '') = unknown: no links are built."""
    for u in (rec.get('url'), rec.get('book_url')):
        d, c, _, _ = parse_url4(u)
        if c: return d, c
    t = str(rec.get('town') or '').strip().lower()
    if t in TOWN_COLL: return TOWN_COLL[t]
    if not t:
        for r in recs:
            if rec.get('book') and r.get('book') == rec.get('book') and r.get('collection') and r is not rec:
                return r.get('diocese') or 'paderborn', r['collection']
    return '', ''


def derive(rec, recs, auto_url=True, auto_book_url=True):
    """Fill collection, pg, url, book_url and image_id the way the table builds them (editable: given URLs win)."""
    dio, col = coll_for(rec, recs); rec['collection'] = col
    if dio and dio != 'paderborn': rec['diocese'] = dio
    else: rec.pop('diocese', None)                            # absent = paderborn (as every original row)
    d2, c2, b2, pg2 = parse_url4(rec.get('url'))
    if pg2: rec['pg'] = pg2
    elif rec.get('book') and col and page_digits(rec.get('page')): rec['pg'] = int(page_digits(rec['page']))
    else: rec['pg'] = None
    if col and rec.get('book') and not rec.get('url') and auto_url:
        rec['url'] = f"{mbase(dio)}{col}/{rec['book']}/" + (f"?pg={rec['pg']}" if rec.get('pg') else '')
    if col and rec.get('book') and not rec.get('book_url') and auto_book_url:
        rec['book_url'] = f"{mbase(dio)}{col}/{rec['book']}/?pg=1"       # title page (BOOKPG is 1 for every book in use)
    town = COLL_TOWN.get(col, '') if col in COLL_TOWN else ''   # image_id prefix only where it is known (Horn/Warstein)
    dig = page_digits(rec.get('image'))
    rec['image_id'] = f"{town}_{rec['book']}_{int(dig):04d}" if (town and rec.get('book') and dig) else ''
    return rec

def is_added(rec): return bool(rec.get('added_by'))
def has_bip(rec): return all(str(rec.get(k) or '').strip() for k in ('book', 'image', 'page'))

def _sa(W, code):
    d = os.path.join(W, 'stageA', code)
    return d

def work(ctx, rec):
    """Reasons this row already has pipeline work (then it cannot be deleted); [] = none."""
    W, code, img = ctx.W, rec['code'], rec.get('image_id') or ''
    why = []
    others = [r for r in _records_quiet(ctx) if r.get('code') != code and r.get('image_id') == img] if img else []
    if img and not others:                                     # crops of a page another row also uses are that row's work, not this one's
        try:
            n = sum(1 for l in open(os.path.join(W, 'entries', 'manifest.jsonl'), encoding='utf-8')
                    if l.strip() and (lambda j: (j.get('image_id') or j.get('scan')) == img)(json.loads(l)))
            if n: why.append(f'{n} crop(s) in the manifest')
        except (FileNotFoundError, ValueError): pass
        if glob.glob(os.path.join(W, 'stage0', f'{img}_*')): why.append('Stage 0 files')
    for sub, lab in (('stageA', 'Stage A'), ('stageA_expanded', 'expansion')):
        d = os.path.join(W, sub, code)
        if os.path.isdir(d) and any(os.scandir(d)): why.append(f'{lab} files')
    for base in ('records', 'stageB'):
        for p in glob.glob(os.path.join(W, base, '**', '*'), recursive=True):
            n = os.path.basename(p)
            if os.path.isfile(p) and (code in n or (img and (img in n or img.split('_', 1)[-1] in n))): why.append('Stage B files'); break
    try: ov = json.load(open(ctx.overrides, encoding='utf-8')).get(code) or {}
    except Exception: ov = {}
    for k in ('segmentation', 'transcription', 'expansion', 'extraction'):
        if isinstance(ov, dict) and k in ov: why.append(f'{k} override')
    return why

def _records_quiet(ctx):
    try: return load(ctx).get('records', [])
    except Exception: return []

def same_page(ctx, rec):
    """Other rows that point at the same image (a duplicate of an existing page)."""
    img = rec.get('image_id')
    return [f"row {r['id']} ({r['code']})" for r in _records_quiet(ctx) if img and r.get('code') != rec.get('code') and r.get('image_id') == img]

def _drop_group_if_empty(recs, g):
    """Remove a group heading that an added row created once no row uses it; the original three are never removed."""
    if g and g not in ORIGINAL_GROUPS and g in recs['groups'] and not any(x.get('group') == g for x in recs['records']): recs['groups'].remove(g)

def _find(recs, code):
    r = next((x for x in recs['records'] if x.get('code') == code), None)
    if not r: raise RowError(f'unknown code {code!r}', 404)
    return r

def _type(record_type, other):
    t = str(record_type or '').strip()
    if t not in TYPES: raise RowError('Record type is required (' + ', '.join(TYPES[:-1]) + ' or Other)', 400)
    if t == 'Other':
        if not other: raise RowError('Record type Other needs a short description', 400)
        return f'Other: {other}'
    return t

def _apply_fields(rec, f, recs):
    """Copy the optional fields from form/CLI dict f into rec (only keys present in f). Returns changed keys."""
    before = dict(rec); ch = []
    for k in ('town', 'book', 'image', 'page', 'date', 'spouse', 'notes', 'book_url', 'url'):
        if k in f:
            v = clean(f[k], k)
            if k in ('book_url', 'url') and v and not re.match(r'https?://', v): raise RowError(f'{k} must start with https://', 400)
            if k == 'book' and v and not re.fullmatch(r'[A-Za-z0-9._\- +]+', v): raise RowError('book code may use letters, digits, spaces, . _ - + only', 400)
            if k == 'town' and not v: rec.pop('town', None)
            elif k in ('notes', 'book_url') and not v: rec.pop(k, None)
            else: rec[k] = v
    for k in ('book', 'image', 'page', 'town'):                  # location changed and URL not re-given -> rebuild the derived URLs
        if k in f and before.get(k, '') != rec.get(k, ''):
            if 'url' not in f or f.get('url') == before.get('url'): rec['url'] = ''
            if k in ('book', 'town') and ('book_url' not in f or f.get('book_url') == before.get('book_url')): rec.pop('book_url', None)
    derive(rec, recs['records'])
    for k in set(before) | set(rec):
        if before.get(k) != rec.get(k): ch.append(k)
    return ch

def _seg_trigger(ctx, rec, stamp, events):
    """book+image+page all present and not yet requested for exactly this book|image|page -> Research 'Page found',
    Segmentation 'Queued' (status.py: seg_requested and no crops yet) and one segmentation_requested event."""
    if not has_bip(rec): return False
    key = f"{rec['book']}|{rec['image']}|{rec['page']}"
    if rec.get('seg_requested_for') == key: return False
    rec['seg_requested'] = stamp; rec['seg_requested_for'] = key; rec['research'] = 'Page found'
    events.append({'kind': 'segmentation_requested', 'row': rec['id'], 'code': rec['code'], 'book': rec['book'],
                   'image': rec['image'], 'page': rec['page'], 'time': stamp})
    return True

def _new_id_code(ctx, recs):
    try: hw = int(json.load(open(ctx.meta, encoding='utf-8')).get('high_water_id', 0))
    except Exception: hw = 0
    dels = _deleted(ctx)
    nid = max([int(r.get('id', 0)) for r in recs['records']] + [hw] + [int(d.get('row', 0)) for d in dels]) + 1
    taken = {str(r.get('code')) for r in recs['records']} | {str(d.get('code')) for d in dels}
    taken |= set(os.listdir(os.path.join(ctx.W, 'stageA'))) if os.path.isdir(os.path.join(ctx.W, 'stageA')) else set()
    code = f'N{nid:04d}'; sfx = 0
    while code in taken: sfx += 1; code = f'N{nid:04d}{chr(96 + sfx)}'
    return nid, code

def add_row(ctx, f, client='cli'):
    name = clean(f.get('name'), 'name')
    if not name: raise RowError('Name is required', 400)
    typ = _type(f.get('record_type'), clean(f.get('type_other'), 'type_other'))
    lf = lock(ctx)
    try:
        recs = load(ctx); stamp = now_ct()
        nid, code = _new_id_code(ctx, recs)
        grp = clean(f.get('group'), 'group') or GROUP
        rec = {'id': nid, 'group': grp, 'name': name, 'type': typ, 'book': '', 'image': '', 'page': '', 'code': code, 'image_id': '',
               'date': '', 'spouse': '', 'collection': DEFAULT_COLL, 'pg': None, 'url': ''}
        _apply_fields(rec, f, recs)
        rec.update({'added_by': BY, 'added_at': stamp, 'research': 'Researching'})
        events = [{k: v for k, v in (('kind', 'row_added'), ('row', nid), ('code', code), ('name', name), ('record_type', typ),
                   ('parish', rec.get('town', '')), ('book', rec['book']), ('page', rec['page']), ('time', stamp), ('by', BY))
                   if k not in ('parish', 'book', 'page') or v}]
        _seg_trigger(ctx, rec, stamp, events)
        if grp not in recs['groups']: recs['groups'].append(grp)
        recs['records'].append(rec)
        bak = save(ctx, recs)
        _atomic(ctx.meta, json.dumps({'high_water_id': nid, 'updated_at': stamp,
                                      'note': 'highest row id ever issued; ids are never reused (rowedit.py)'}, indent=1) + '\n')
        log(ctx, stamp, 'add_row', nid, code, f'{typ}: {name}', client)
        for e in events: notify(ctx, e)
        dup = [f"row {r['id']} ({r['code']})" for r in recs['records'] if rec.get('image_id') and r is not rec and r.get('image_id') == rec['image_id']]
        return {'ok': True, 'action': 'add_row', 'row': nid, 'code': code, 'record': rec, 'records_backup': bak, 'events': events, 'time': stamp,
                'warning': f"same page as {', '.join(dup)}" if dup else ''}
    finally: unlock(lf)

def update_row(ctx, code, f, client='cli', who=BY, allow_research=True):
    lf = lock(ctx)
    try:
        recs = load(ctx); rec = _find(recs, code)
        if not is_added(rec): raise RowError(f'{code} is not an added row; only rows added with \u201c\uff0b Add row\u201d can be edited here', 409)
        stamp = now_ct(); events = []; before = json.dumps(rec, sort_keys=True); b_nt = (rec.get('name'), rec.get('type'))
        if 'name' in f:
            n = clean(f['name'], 'name')
            if not n: raise RowError('Name is required', 400)
            rec['name'] = n
        if 'record_type' in f: rec['type'] = _type(f['record_type'], clean(f.get('type_other'), 'type_other'))
        old_group = rec.get('group')
        if 'group' in f:
            g = clean(f['group'], 'group') or GROUP
            rec['group'] = g
            if g not in recs['groups']: recs['groups'].append(g)
        ch = _apply_fields(rec, f, recs) + [k for k, a in (('name', b_nt[0]), ('type', b_nt[1]), ('group', old_group)) if rec.get(k) != a]
        if rec.get('group') != old_group: _drop_group_if_empty(recs, old_group)
        fired = _seg_trigger(ctx, rec, stamp, events)
        changed = before != json.dumps(rec, sort_keys=True)
        if not changed and not fired: return {'ok': True, 'action': 'update_row', 'row': rec['id'], 'code': code, 'changed': [], 'record': rec, 'events': [], 'time': stamp, 'records_backup': None}
        rec['updated_at'] = stamp; rec['updated_by'] = who
        bak = save(ctx, recs)
        log(ctx, stamp, 'update_row', rec['id'], code, 'changed ' + ','.join(sorted(set(ch))) + (' ; segmentation_requested' if fired else ''), client)
        for e in events: notify(ctx, e)
        return {'ok': True, 'action': 'update_row', 'row': rec['id'], 'code': code, 'changed': sorted(set(ch)), 'record': rec,
                'events': events, 'segmentation_requested': fired, 'records_backup': bak, 'time': stamp,
                'warning': (lambda d: f"same page as {', '.join(d)}" if d else '')([f"row {r['id']} ({r['code']})" for r in recs['records'] if rec.get('image_id') and r is not rec and r.get('image_id') == rec['image_id']])}
    finally: unlock(lf)

def delete_row(ctx, code, client='cli'):
    lf = lock(ctx)
    try:
        recs = load(ctx); rec = _find(recs, code)
        if not is_added(rec): raise RowError(f'{code} is not an added row; it cannot be deleted from the dashboard', 409)
        why = work(ctx, rec)
        if why: raise RowError(f'{code} already has pipeline work ({"; ".join(why)}); not deleted', 409)
        stamp = now_ct()
        recs['records'] = [x for x in recs['records'] if x is not rec]
        _drop_group_if_empty(recs, rec.get('group'))
        bak = save(ctx, recs)
        with open(ctx.deleted, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps({'row': rec['id'], 'code': code, 'time': stamp, 'by': BY, 'record': rec}, ensure_ascii=False) + '\n')
        log(ctx, stamp, 'delete_row', rec['id'], code, f'deleted (records backup {bak})', client)
        evt = {'kind': 'row_deleted', 'row': rec['id'], 'code': code, 'name': rec.get('name'), 'time': stamp, 'by': BY}
        notify(ctx, evt)
        return {'ok': True, 'action': 'delete_row', 'row': rec['id'], 'code': code, 'records_backup': bak, 'events': [evt], 'time': stamp}
    finally: unlock(lf)

def set_research(ctx, code, value, client='cli'):
    v = {'researching': 'Researching', 'found': 'Page found', 'page found': 'Page found', 'clear': ''}.get(str(value).strip().lower())
    if v is None: raise RowError(f'unknown research state {value!r}; use researching | found | clear', 400)
    lf = lock(ctx)
    try:
        recs = load(ctx); rec = _find(recs, code); stamp = now_ct()
        if v: rec['research'] = v
        else: rec.pop('research', None)
        bak = save(ctx, recs)
        log(ctx, stamp, 'set_research', rec['id'], code, f'research -> {v or "(cleared)"}', client)
        return {'ok': True, 'row': rec['id'], 'code': code, 'research': v, 'records_backup': bak}
    finally: unlock(lf)
