"""Stephen's inline reading changes on the transcription pages, shared by approve_server.py and status.py.

  choose_reading  word[?|alt] / word[?|a|b]  -> one tap button per option; the picked spelling replaces the token
  edit_reading    double-click / double-tap / long-press a single word -> edit it inline (value: one word, no whitespace)
  undo_reading    undo either kind (history kept)

Both kinds are stored in the per-row stageA/<folder>/_confirmed_readings.json (the list the ✓ confirm_reading uses) as records
with "type": "choice" | "edit" (plain ✓ records have no "type"). status.py calls reapply_all() every run, so a change survives
page regeneration AND a later rewrite of Stage A / Stage B drafts / the summary .md that brings the old token back.
Every write: under entries/.manifest.lock, backup first, byte-preserving JSON edit (only the changed string literals are
replaced; the result is re-parsed and compared), a line in entries/_approvals.log, an event in dashboard/notify_queue.jsonl.
Locked/approved Stage A entries and locked Stage B records are never written (the server refuses with 409)."""
import datetime, fcntl, glob, json, os, re, shutil, tempfile, time

TOKRE = re.compile(r'([^\s\[\]|()]+)\[\?\]')                          # plain word[?] (the ✓ confirm), same as status/approve_server
ALTRE = re.compile(r'([^\s\[\]|()]+)\[\?((?:\|[^\[\]|\n]+)+)\]')     # word[?|alt] or word[?|a|b]
WORDRE = re.compile(r'[^\s\[\]|()]+(?:\[\?(?:\|[^\[\]|\n]+)*\])?')  # one editable word: run of non-space chars + optional [?] / [?|..]
LOCKED_VALUES = {'locked', 'approved', 'final'}
DISPLAY_FIELDS = ('diplomatic_text', 'diplomatic_margin')
STAGEA_ALIASES = {'W-S0036': 'Warstein_S0036'}                        # same mapping as status.py / approve_server.py _sa()

class Refuse(Exception):
    def __init__(self, msg, http=409): super().__init__(msg); self.http = http

def now_ct(): return datetime.datetime.now().astimezone().isoformat(timespec='seconds')

def sa_dir(stagea, code):
    d = os.path.join(stagea, str(code))
    if os.path.isdir(d): return d
    a = STAGEA_ALIASES.get(code)
    if a and os.path.isdir(os.path.join(stagea, a)): return os.path.join(stagea, a)
    m = re.fullmatch(r'([A-Za-z])-(\w+)', code or '')
    if m and os.path.isdir(stagea):
        c = [n for n in os.listdir(stagea) if n.endswith('_' + m.group(2)) and n[:1].upper() == m.group(1).upper() and os.path.isdir(os.path.join(stagea, n))]
        if len(c) == 1: return os.path.join(stagea, c[0])
    return d

def md_path(stagea, code):
    d = sa_dir(stagea, code)
    for n in (f'{code}_stageA.md', f'{os.path.basename(d)}_stageA.md'):
        if os.path.isfile(os.path.join(d, n)): return os.path.join(d, n)
    return ''

def parse_alt(tok):
    m = ALTRE.fullmatch(tok or '')
    return ([m.group(1)] + m.group(2).split('|')[1:]) if m else None

def has_marker(tok): return '[?' in (tok or '')

def valid_value(v):
    return isinstance(v, str) and 0 < len(v) <= 120 and not re.search(r'\s', v)

# ---------------- tokens ----------------
def tokens(text): return [(m.start(), m.end(), m.group(0)) for m in WORDRE.finditer(text or '')]

def nth(text, tok, occ):
    hits = [t for t in tokens(text) if t[2] == tok]
    return hits[occ - 1][0] if isinstance(occ, int) and 1 <= occ <= len(hits) else None

def locate_strict(text, tok, occ, ctx):
    """User actions: the occ-th token equal to tok AND (if ctx given) the text right before it must end with ctx -> else 409."""
    i = nth(text, tok, occ)
    if i is None: raise Refuse(f'"{tok}" (occurrence {occ}) is not in the text any more (it changed or was already done); reload; nothing changed')
    if ctx is not None and not text[:i].endswith(ctx):
        raise Refuse(f'the text around "{tok}" has changed since the page was built; reload and try again; nothing changed')
    return i

def _tail(s, n=12): return re.sub(r'\s+', ' ', s or '')[-n:]

def locate_lax(text, tok, occ, ctx):
    """Re-apply: a token equal to tok whose preceding text matches the recorded context (last 12 chars, whitespace-normalised);
    else, only for a marked token ([?]/[?|..]) that occurs exactly once, that one. Never a guess for plain words."""
    hits = [t[0] for t in tokens(text) if t[2] == tok]
    if not hits: return None
    t12 = _tail(ctx)
    if t12:
        m = [i for i in hits if _tail(text[:i]).endswith(t12)]
        if len(m) == 1: return m[0]
        if len(m) > 1: return m[occ - 1] if isinstance(occ, int) and 1 <= occ <= len(m) else None
    return hits[0] if len(hits) == 1 and has_marker(tok) else None

# ---------------- JSON helpers (byte-preserving) ----------------
def walk(v, path=()):
    if isinstance(v, str): yield path, v
    elif isinstance(v, dict):
        for k, x in v.items(): yield from walk(x, path + (k,))
    elif isinstance(v, list):
        for i, x in enumerate(v): yield from walk(x, path + (i,))

def get_path(o, p):
    for k in p: o = o[k]
    return o

def set_path(o, p, v):
    for k in p[:-1]: o = o[k]
    o[p[-1]] = v

def copy(o): return json.loads(json.dumps(o))

def rewrite_bytes(raw, expected, changes):
    text = raw.decode('utf-8'); new = text
    for _, before, after in changes:
        for asc in (False, True):
            lit = json.dumps(before, ensure_ascii=asc)
            if lit in new: new = new.replace(lit, json.dumps(after, ensure_ascii=asc)); break
        else: new = None; break
    if new is not None:
        try:
            if json.loads(new) == expected: return new.encode('utf-8')
        except ValueError: pass
    m = re.search(r'\n( +)"', text); ind = len(m.group(1)) if m else 1
    out = (json.dumps(expected, ensure_ascii=False, indent=ind) + ('\n' if text.endswith('\n') else '')).encode('utf-8')
    if json.loads(out) != expected: raise Refuse('rewrite verification failed; nothing changed', 500)
    return out

def atomic_write(path, data):
    st = os.stat(path) if os.path.exists(path) else None
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.readings-', suffix='.tmp')
    with os.fdopen(fd, 'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, (st.st_mode & 0o777) if st else 0o644); os.replace(tmp, path)

def atomic_json(path, obj): atomic_write(path, (json.dumps(obj, ensure_ascii=False, indent=1) + '\n').encode('utf-8'))

def lock(lockfile, timeout=15):
    lf = open(lockfile, 'a+'); t0 = time.time()
    while True:
        try: fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB); return lf
        except BlockingIOError:
            if time.time() - t0 > timeout: lf.close(); raise Refuse('lock is held by another writer; try again', 503)
            time.sleep(0.2)

def unlock(lf): fcntl.flock(lf, fcntl.LOCK_UN); lf.close()

def backup(backups, action, code, paths):
    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:-3]
    bdir = os.path.join(backups, action, f'{code}_{ts}'); os.makedirs(bdir, exist_ok=False)
    for p in paths:
        if p and os.path.exists(p):
            dst = os.path.join(bdir, os.path.basename(p))
            if os.path.exists(dst): dst = os.path.join(bdir, os.path.basename(os.path.dirname(p)) + '__' + os.path.basename(p))
            shutil.copy2(p, dst)
    return bdir

def notify(queue, evt):
    with open(queue, 'a', encoding='utf-8') as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.write(json.dumps(evt, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())

def log_line(entries, line):
    with open(os.path.join(entries, '_approvals.log'), 'a', encoding='utf-8') as f: f.write(line.rstrip('\n') + '\n')

# ---------------- plans ----------------
def plan_entry(obj, field, tok, new, start):
    """Replace tok at `start` in obj[field]. Other string fields of the entry (columns, uncertain, notes, ...): for a marked
    token that occurs once in the field, every occurrence of the exact token is replaced; plain words are left and listed."""
    s = obj[field]; ns = s[:start] + new + s[start + len(tok):]
    out = copy(obj); set_path(out, (field,), ns); changes = [((field,), s, ns)]; skipped = []
    single = sum(1 for t in tokens(s) if t[2] == tok) == 1
    for p, v in walk(obj):
        if p == (field,) or tok not in v: continue
        if has_marker(tok) and single:
            nv = v.replace(tok, new); set_path(out, p, nv); changes.append((p, v, nv))
        else: skipped.append('.'.join(map(str, p)))
    return out, changes, skipped

WORDC = re.compile(r'[^\s\[\]|()/.,;:!?\'"]')   # a character that would continue a word
def _mdnorm(s): return re.sub(r'[\s/]+', '', s or '')

def md_hits(md, tok, ctx):
    """Positions of tok in the summary .md whose preceding text matches the entry context (last 10 characters, ignoring whitespace
    and the ' / ' line-break marks the summary uses). The .md repeats an entry (entry block, raw dump), so every matching copy counts;
    notes such as '- Uncertain: <token>' have a different context and are left alone. No context -> no match (never a guess)."""
    c = _mdnorm(ctx)[-10:]
    if not c: return []
    out, k = [], md.find(tok)
    while k >= 0:
        e = k + len(tok); pre = md[k - 1] if k else ' '; post = md[e] if e < len(md) else ' '
        if (not WORDC.match(pre)) and (not WORDC.match(post)) and post != '[' and _mdnorm(md[max(0, k - 80):k]).endswith(c): out.append(k)
        k = md.find(tok, k + 1)
    return out

def plan_md(md, tok, new, ctx):
    """-> (new_md, {'context','before','after','count'}) or (None, reason)."""
    hs = md_hits(md, tok, ctx)
    if not hs: return None, 'token not found with the same context in the summary .md (left unchanged)'
    out = md
    for i in reversed(hs): out = out[:i] + new + out[i + len(tok):]
    return out, {'context': ctx, 'before': tok, 'after': new, 'count': len(hs)}

def stageb_files(stageb, code, entry_id, stagea_path):
    out = []; base = re.sub(r'_[LR](_e\d+)$', r'\1', entry_id)
    for p in sorted(glob.glob(os.path.join(stageb, code, '*.json'))):
        try: j = json.load(open(p, encoding='utf-8'))
        except Exception: continue
        if not isinstance(j, dict): continue
        dps = [j.get('diplomatic_path')] + list(j.get('diplomatic_paths') or [])
        if j.get('entry_id') in (entry_id, base) or any(d and os.path.basename(str(d)) == os.path.basename(stagea_path) for d in dps): out.append((p, j))
    return out

def locked_b(j): return str(j.get('stage_b_status', j.get('status', ''))).lower() in LOCKED_VALUES

def plan_b(j, tok, new, ctx):
    """Draft Stage B record: marked token -> every exact occurrence; plain word -> only where the recorded context precedes it."""
    out = copy(j); ch = []
    for p, v in walk(j):
        if tok not in v: continue
        if has_marker(tok): nv = v.replace(tok, new)
        else:
            i = locate_lax(v, tok, None, ctx)
            if i is None or not _tail(ctx): continue
            nv = v[:i] + new + v[i + len(tok):]
        if nv != v: set_path(out, p, nv); ch.append((p, v, nv))
    return out, ch

def word_hits(obj, word):
    rx = re.compile(r'(?<![\w\[|])' + re.escape(word) + r'(?![\w\]|])')
    return ['.'.join(map(str, p)) for p, v in walk(obj) if rx.search(v)]

def load_confirmed(sadir):
    try: v = json.load(open(os.path.join(sadir, '_confirmed_readings.json'), encoding='utf-8'))
    except Exception: return []
    return v if isinstance(v, list) else []

def legacy_edit(x):
    """Older direct-edit records (e.g. 'by': 'Stephen voice'/'Stephen chat'): no 'type'/'change_id', 'token' = the NEW text and
    'before' = the old text. -> an edit-shaped dict (token = old, new = new, legacy = True), or None when it is not such a record or
    is not unambiguous (needs entry_id, field, before != token, and a context_before anchor). These are never undone or reverted."""
    if not isinstance(x, dict) or x.get('type') or 'before' not in x: return None
    e, f, old, new, cb = x.get('entry_id'), x.get('field'), x.get('before'), x.get('token'), x.get('context_before')
    if not all(isinstance(v, str) and v for v in (e, f, old, new, cb)) or old == new or f == 'md': return None
    return {'type': 'edit', 'legacy': True, 'change_id': f'legacy:{e}:{f}:{x.get("time", "")}', 'entry_id': e, 'field': f,
            'token': old, 'new': new, 'occurrence': x.get('occurrence'), 'context_before': cb, 'context_after': x.get('context_after', ''),
            'time': x.get('time', ''), 'by': x.get('by', ''), 'author': 'Stephen', 'confirms_reading': has_marker(old) and not has_marker(new)}

def is_legacy_record(x): return isinstance(x, dict) and not x.get('type') and 'before' in x

def active_changes(sadir):
    out = [x for x in load_confirmed(sadir) if isinstance(x, dict) and x.get('type') in ('choice', 'edit') and not x.get('undone')]
    return out + [l for l in map(legacy_edit, load_confirmed(sadir)) if l]

def ctx_hits(v, tok, ctx):
    """Positions of tok in v (whole word: not inside a longer word, not followed by '[') whose preceding text ends with the
    recorded context (last 12 chars, whitespace-normalised). Context is required: never a guess."""
    t12 = _tail(ctx); out = []
    if not t12 or not tok: return out
    k = v.find(tok)
    while k >= 0:
        e = k + len(tok); pre = v[k - 1] if k else ' '; post = v[e] if e < len(v) else ' '
        if not WORDC.match(pre) and not WORDC.match(post) and post != '[' and _tail(v[:k]).endswith(t12): out.append(k)
        k = v.find(tok, k + 1)
    return out

def plan_legacy(obj, field, tok, new, ctx):
    """Forward re-apply of a legacy edit: the named top-level field and its transcription copies (diplomatic_*, columns.*), each only
    where the old text sits after the same context and exactly once. Notes, uncertain lists etc. are never touched."""
    out = copy(obj); ch = []
    for p, v in walk(obj):
        if not (p[0] == field or str(p[0]).startswith('diplomatic_') or p[0] == 'columns'): continue
        hs = ctx_hits(v, tok, ctx)
        if len(hs) != 1: continue
        nv = v[:hs[0]] + new + v[hs[0] + len(tok):]; set_path(out, p, nv); ch.append((p, v, nv))
    return out, ch

# ---------------- the three user actions ----------------
class Ctx:
    """Paths + callbacks from the caller (approve_server): stagea, stageb, entries (lock + approvals log), backups, queue."""
    def __init__(self, stagea, stageb, entries, backups, queue):
        self.stagea, self.stageb, self.entries, self.backups, self.queue = stagea, stageb, entries, backups, queue

def _entry_path(C, code, entry_id, field):
    d = sa_dir(C.stagea, code)
    if field == 'md' or entry_id.endswith('_stageA.md'):
        p = md_path(C.stagea, code)
        if not p: raise Refuse(f'{code}: no summary .md; nothing changed')
        return d, p, 'md'
    if field not in DISPLAY_FIELDS: raise Refuse('bad field', 400)
    if not re.fullmatch(r'[A-Za-z0-9_.\-]+', entry_id or ''): raise Refuse('bad entry_id', 400)
    p = os.path.join(d, entry_id + '.diplomatic.json')
    if not os.path.isfile(p): raise Refuse(f'{code}: no Stage A file for {entry_id}; nothing changed')
    return d, p, field

def change(C, code, row_status, kind, entry_id, field, token, occurrence, ctx, value, pick=None):
    """kind 'choice' (value = options[pick]) or 'edit'. Returns (record, info) after writing; raises Refuse."""
    if not str(row_status).lower().startswith(('draft', 'approved')): raise Refuse(f'{code}: transcription is {row_status!r}; nothing changed')
    if not isinstance(occurrence, int) or occurrence < 1: raise Refuse('bad occurrence', 400)
    if not isinstance(ctx, str): raise Refuse('context required', 400)
    opts = None
    if kind == 'choice':
        opts = parse_alt(token)
        if not opts: raise Refuse('bad token: expected word[?|alternative]', 400)
        if not isinstance(pick, int) or not 0 <= pick < len(opts): raise Refuse('bad option index', 400)
        value = opts[pick]
    else:
        if not valid_value(value): raise Refuse('the new reading must be one word: not empty, no spaces', 400)
        if not token or re.search(r'\s', token): raise Refuse('bad token', 400)
        if value == token: raise Refuse('unchanged; nothing to save', 400)
    sadir, p, field = _entry_path(C, code, entry_id, field)
    lf = lock(os.path.join(C.entries, '.manifest.lock'))
    try:
        raw = open(p, 'rb').read()
        if field == 'md':
            if str(row_status).lower().startswith('approved'): raise Refuse(f'{code}: transcription is approved (read-only); nothing changed')
            text = raw.decode('utf-8'); obj = None
        else:
            obj = json.loads(raw); text = obj.get(field)
            if not isinstance(text, str): raise Refuse(f'{entry_id}: no {field}; nothing changed')
            if str(obj.get('status', '')).lower() in LOCKED_VALUES: raise Refuse(f'{entry_id} is approved (locked): read-only; nothing changed')
        i = locate_strict(text, token, occurrence, ctx)
        cb, ca = text[max(0, i - 40):i], text[i + len(token):i + len(token) + 40]
        if field == 'md': newtext = text[:i] + value + text[i + len(token):]; a_changes = [((), text, newtext)]; skipped = []; newobj = None
        else: newobj, a_changes, skipped = plan_entry(obj, field, token, value, i)
        mdp = md_path(C.stagea, code) if field != 'md' else ''
        md_new = md_info = None; md_note = ''
        if mdp:
            md_new, md_info = plan_md(open(mdp, encoding='utf-8').read(), token, value, cb)
            if md_new is None: md_note, md_info = md_info, None
        b_upd, b_locked, b_review = [], [], []
        if field != 'md':
            for bp, bj in stageb_files(C.stageb, code, entry_id, p):
                if token not in json.dumps(bj, ensure_ascii=False): continue
                if locked_b(bj): b_locked.append(bp); continue
                nb, bch = plan_b(bj, token, value, cb)
                if bch: b_upd.append((bp, nb, bch))
                rest = word_hits(nb, token) if not has_marker(token) else [k for k, v in walk(nb) if token in v]
                if rest: b_review.append({'file': bp, 'token': token, 'fields': rest})
                for o in (opts or []):
                    if o != value and word_hits(nb, o): b_review.append({'file': bp, 'unchosen_option': o, 'fields': word_hits(nb, o)})
        stamp = now_ct(); crp = os.path.join(sadir, '_confirmed_readings.json'); fbp = os.path.join(sadir, '_feedback_status.json')
        action = 'choose_reading' if kind == 'choice' else 'edit_reading'
        bdir = backup(C.backups, action, code, [p, crp, fbp, mdp if md_new else ''] + [bp for bp, _, _ in b_upd])
        if field == 'md': atomic_write(p, newtext.encode('utf-8'))
        else:
            atomic_write(p, rewrite_bytes(raw, newobj, a_changes))
            if json.load(open(p, encoding='utf-8')) != newobj: raise Refuse(f'post-write verification failed; backup in {bdir}', 500)
        if md_new is not None: atomic_write(mdp, md_new.encode('utf-8'))
        b_changes = []
        for bp, nb, bch in b_upd:
            atomic_write(bp, rewrite_bytes(open(bp, 'rb').read(), nb, bch))
            b_changes += [{'file': bp, 'path': list(q), 'before': x, 'after': y} for q, x, y in bch]
        rec = {'type': kind, 'change_id': f'{code}:{entry_id}:{stamp}:{kind}:{occurrence}', 'entry_id': entry_id, 'field': field,
               'token': token, 'new': value}
        if kind == 'choice': rec.update({'options': opts, 'picked': value, 'index': pick})
        rec.update({'occurrence': occurrence, 'context_before': cb, 'context_after': ca, 'time': stamp, 'author': 'Stephen', 'by': 'Stephen dashboard',
                    'confirms_reading': has_marker(token) and not has_marker(value), 'stage_a_file': p,
                    'stage_a_changes': [{'path': list(q), 'before': x, 'after': y} for q, x, y in a_changes] if field != 'md' else [{'path': [], 'context': cb, 'before': token, 'after': value}],
                    'other_fields_skipped': skipped, 'md_change': dict(md_info, file=mdp) if md_info else None, 'md_note': md_note,
                    'stage_b_changes': b_changes, 'stage_b_locked_with_token': b_locked, 'stage_b_review': b_review, 'undone': False})
        crl = load_confirmed(sadir); crl.append(rec); atomic_json(crp, crl)
        return rec, {'backup_dir': bdir, 'stage_b_updated': [bp for bp, _, _ in b_upd]}
    finally: unlock(lf)

def undo(C, code, change_id):
    sadir = sa_dir(C.stagea, code)
    lf = lock(os.path.join(C.entries, '.manifest.lock'))
    try:
        crl = load_confirmed(sadir)
        rec = next((x for x in crl if isinstance(x, dict) and x.get('type') in ('choice', 'edit') and x.get('change_id') == change_id), None)
        if not rec: raise Refuse(f'{code}: no such change; nothing changed', 404)
        if rec.get('undone'): raise Refuse(f'{code}: that change was already undone; nothing changed')
        _, p, field = _entry_path(C, code, rec['entry_id'], rec['field'])
        raw = open(p, 'rb').read(); old, new = rec['token'], rec['new']; ctx12 = _tail(rec.get('context_before', ''))
        def back(v):
            j = [m for m in (k for k in range(len(v)) if v.startswith(new, k)) if _tail(v[:m]).endswith(ctx12)] if ctx12 else []
            if len(j) != 1: return None
            return v[:j[0]] + old + v[j[0] + len(new):]
        if field == 'md':
            v = raw.decode('utf-8'); nv = back(v)
            if nv is None: raise Refuse(f'{code}: the text changed since and the place cannot be found safely; nothing changed')
            newobj = None; a_changes = [((), v, nv)]
        else:
            obj = json.loads(raw)
            if str(obj.get('status', '')).lower() in LOCKED_VALUES: raise Refuse(f'{rec["entry_id"]} is approved (locked): read-only; nothing changed')
            newobj = copy(obj); a_changes = []
            for ch in rec.get('stage_a_changes', []):
                q = tuple(ch['path'])
                try: cur = get_path(obj, q)
                except (KeyError, IndexError, TypeError): continue
                nv = ch['before'] if cur == ch['after'] else (back(cur) if q == (field,) else None)
                if nv is None:
                    if q == (field,): raise Refuse(f'{code}: the Stage A text changed since and the place cannot be found safely; nothing changed')
                    continue
                set_path(newobj, q, nv); a_changes.append((q, cur, nv))
        md = rec.get('md_change') or None; md_new = None; md_skip = ''
        if md and os.path.isfile(md.get('file', '')):
            mt = open(md['file'], encoding='utf-8').read(); md_new, _ = plan_md(mt, md['after'], md['before'], md['context'])
            if md_new is None: md_skip = 'summary .md changed since; not reverted'
        bplan = {}; b_skip = []
        for ch in rec.get('stage_b_changes', []):
            bp = ch['file']
            try: bj = json.load(open(bp, encoding='utf-8'))
            except Exception: b_skip.append(bp); continue
            if locked_b(bj): b_skip.append(bp); continue
            ent = bplan.setdefault(bp, [bj, copy(bj), []])
            try: cur = get_path(ent[1], tuple(ch['path']))
            except (KeyError, IndexError, TypeError): b_skip.append(bp); continue
            if cur != ch['after']: b_skip.append(bp); continue
            set_path(ent[1], tuple(ch['path']), ch['before']); ent[2].append((tuple(ch['path']), ch['after'], ch['before']))
        stamp = now_ct(); crp = os.path.join(sadir, '_confirmed_readings.json')
        bdir = backup(C.backups, 'undo_reading', code, [p, crp, os.path.join(sadir, '_feedback_status.json'), md['file'] if md_new else ''] + list(bplan))
        if field == 'md': atomic_write(p, a_changes[0][2].encode('utf-8'))
        else: atomic_write(p, rewrite_bytes(raw, newobj, a_changes))
        if md_new is not None: atomic_write(md['file'], md_new.encode('utf-8'))
        for bp, (bj, nb, chs) in bplan.items():
            if chs: atomic_write(bp, rewrite_bytes(open(bp, 'rb').read(), nb, chs))
        rec.update({'undone': True, 'undone_at': stamp, 'undone_by': 'Stephen dashboard'})
        crl.append({'type': 'undo', 'change_id': change_id, 'undoes': rec['type'], 'entry_id': rec['entry_id'], 'field': rec['field'],
                    'token': old, 'new': new, 'time': stamp, 'author': 'Stephen', 'by': 'Stephen dashboard',
                    'md_reverted': md_new is not None, 'md_note': md_skip, 'stage_b_reverted': list(bplan), 'stage_b_skipped': b_skip})
        atomic_json(crp, crl)
        # data for rebuilding the token in place on the page
        cur_text = (a_changes[0][2] if field == 'md' else newobj[field])
        i = next((m for m in (t[0] for t in tokens(cur_text) if t[2] == old) if _tail(cur_text[:m]).endswith(ctx12)), None)
        occ = sum(1 for t in tokens(cur_text[:i]) if t[2] == old) + 1 if i is not None else rec.get('occurrence')
        cocc = None
        if i is not None and old.endswith('[?]') and not parse_alt(old):
            base = old[:-3]; cocc = sum(1 for m in TOKRE.finditer(cur_text[:i]) if m.group(1) == base) + 1
        return rec, {'backup_dir': bdir, 'md_reverted': md_new is not None, 'stage_b_reverted': list(bplan), 'stage_b_skipped': b_skip,
                     'occurrence': occ, 'confirm_occurrence': cocc, 'context': cur_text[:i][-20:] if i is not None else ''}
    finally: unlock(lf)

# ---------------- durability: status.py re-applies active changes every run ----------------
def reapply_all(W, dash, codes, log=print):
    stagea, stageb, entries = os.path.join(W, 'stageA'), os.path.join(W, 'stageB'), os.path.join(W, 'entries')
    backups = os.path.join(W, '_approve_backups'); queue = os.path.join(dash, 'notify_queue.jsonl'); fixed = []
    todo = []
    for code in codes:
        sadir = sa_dir(stagea, code)
        for c in active_changes(sadir):
            fp = md_path(stagea, code) if c.get('field') == 'md' else os.path.join(sadir, c['entry_id'] + '.diplomatic.json')
            if not fp or not os.path.isfile(fp): continue
            tok = c['token']; txt = open(fp, encoding='utf-8').read()
            cb = c.get('context_before', '')
            if c.get('field') == 'md': hit = locate_lax(txt, tok, c.get('occurrence'), cb) is not None
            else:
                try: o = json.loads(txt)
                except Exception: continue
                v = o.get(c['field'])
                if c.get('legacy') and not isinstance(v, str): continue       # field not a top-level text field: ambiguous, leave alone
                unl = str(o.get('status', '')).lower() not in LOCKED_VALUES
                if c.get('legacy'): hit = unl and bool(plan_legacy(o, c['field'], tok, c['new'], cb)[1])
                else: hit = unl and isinstance(v, str) and locate_lax(v, tok, c.get('occurrence'), cb) is not None
            mdp = md_path(stagea, code) if c.get('field') != 'md' else ''
            mhit = bool(mdp) and os.path.isfile(mdp) and bool(md_hits(open(mdp, encoding='utf-8').read(), tok, c.get('context_before', '')))
            bh = [bp for bp, bj in stageb_files(stageb, code, c['entry_id'], fp) if not locked_b(bj) and tok in json.dumps(bj, ensure_ascii=False) and plan_b(bj, tok, c['new'], cb)[1]] if c.get('field') != 'md' else []
            if hit or mhit or bh: todo.append((code, sadir, c, fp, mdp))
    if not todo: return fixed
    try: lf = lock(os.path.join(entries, '.manifest.lock'), timeout=3)
    except Refuse: log('readings: lock busy; re-apply deferred to the next run'); return fixed
    try:
        for code, sadir, c, fp, mdp in todo:
            tok, new, cb = c['token'], c['new'], c.get('context_before', '')
            raw = open(fp, 'rb').read(); plan_a = None
            if c.get('field') == 'md':
                s = raw.decode('utf-8'); i = locate_lax(s, tok, c.get('occurrence'), cb)
                if i is not None: plan_a = ('md', s[:i] + new + s[i + len(tok):])
            else:
                obj = json.loads(raw)
                if c.get('legacy'):
                    if str(obj.get('status', '')).lower() not in LOCKED_VALUES:
                        no, ch = plan_legacy(obj, c['field'], tok, new, cb)
                        if ch: plan_a = ('json', no, ch)
                elif str(obj.get('status', '')).lower() not in LOCKED_VALUES and isinstance(obj.get(c['field']), str):
                    i = locate_lax(obj[c['field']], tok, c.get('occurrence'), cb)
                    if i is not None:
                        no, ch, _ = plan_entry(obj, c['field'], tok, new, i); plan_a = ('json', no, ch)
            md_new = None
            if mdp and os.path.isfile(mdp):
                md_new, _ = plan_md(open(mdp, encoding='utf-8').read(), tok, new, cb)
            bplans = []
            if c.get('field') != 'md':
                for bp, bj in stageb_files(stageb, code, c['entry_id'], fp):
                    if locked_b(bj) or tok not in json.dumps(bj, ensure_ascii=False): continue
                    nb, bch = plan_b(bj, tok, new, cb)
                    if bch: bplans.append((bp, nb, bch))
            if not plan_a and md_new is None and not bplans: continue
            stamp = now_ct()
            bdir = backup(backups, 'reading_reapply', code, [fp if plan_a else '', mdp if md_new is not None else ''] + [bp for bp, _, _ in bplans])
            if plan_a:
                if plan_a[0] == 'md': atomic_write(fp, plan_a[1].encode('utf-8'))
                else: atomic_write(fp, rewrite_bytes(raw, plan_a[1], plan_a[2]))
            if md_new is not None: atomic_write(mdp, md_new.encode('utf-8'))
            for bp, nb, bch in bplans: atomic_write(bp, rewrite_bytes(open(bp, 'rb').read(), nb, bch))
            res = {'code': code, 'entry_id': c['entry_id'], 'token': tok, 'new': new, 'type': c['type'], 'stage_a': bool(plan_a),
                   'md': md_new is not None, 'stage_b': [bp for bp, _, _ in bplans], 'backup_dir': bdir}
            log_line(entries, f'{stamp}\taction=reading_reapply\t{code}\t{c["entry_id"]}\t{tok} -> {new} ({c["type"]} {c.get("change_id")} re-applied after a rewrite)'
                     f'\tstage_a={res["stage_a"]}\tmd={res["md"]}\tstage_b={len(res["stage_b"])}\tby=status.py')
            notify(queue, {'time': stamp, 'kind': 'reading_change_reapplied', 'action': 'reading_reapply', 'code': code, 'entry_id': c['entry_id'],
                           'change_type': c['type'], 'change_id': c.get('change_id'), 'token_before': tok, 'token_after': new,
                           'stage_a_file': fp if plan_a else None, 'md_file': mdp if md_new is not None else None, 'stage_b_files': res['stage_b'],
                           'backup_dir': bdir, 'for': ['Chief', 'Entry Transcriber', 'Record Extractor'],
                           'note': "Stephen's recorded reading was re-applied because a rewrite brought the old token back"})
            fixed.append(res)
    finally: unlock(lf)
    return fixed
