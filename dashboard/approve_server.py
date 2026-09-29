#!/usr/bin/env python3
"""OPR dashboard 'Approve segmentation' endpoint.

POST /api/approve  {"code": "<dashboard code>"}   (header X-OPR-Approve: 1 required)
Locks every crop of a Draft or Recut row (Queued for redo / Redoing / Approved are refused) in BOTH manifests (entries/<book>/manifest.jsonl and entries/manifest.jsonl).

Listens on 127.0.0.1 only; published to the tailnet (never Funnel) via
  tailscale serve --http=80 --set-path=/api/approve http://127.0.0.1:8081/api/approve
Config via env (used for scratch testing): OPR_ENTRIES, OPR_DASH, OPR_STAGEA, OPR_STAGEB, OPR_RUN_STATUS (1/0), OPR_PORT.

Actions (JSON body {"code": ..., "action": ...}; action defaults to "segmentation", unchanged behaviour):
  segmentation   lock crops in both manifests (above).
  transcription  row's dashboard transcription must be Draft; every stageA/<code>/*.diplomatic.json present and none locked;
                 sets top-level "status": "locked" and "locked_by" (byte-level edit, text byte-identical).
  extraction     row's dashboard extraction must be Draft; stageB/<code>/*.json present and none locked;
                 sets "stage_b_status": "locked", "stage_b_locked_at": <ISO CT>, "stage_b_locked_by" (byte-level edit).
Both new actions: timestamped backups, atomic writes, entries/_approvals.log line (action=...), a line in
dashboard/notify_queue.jsonl for Chief, then status.py rerun. They never touch crops, manifests, or the other stage.
"""
import fcntl, glob, http.server, json, os, re, shutil, subprocess, tempfile, time, datetime, threading

ENTRIES = os.environ.get('OPR_ENTRIES', '/workspace/horn-wilmes/entries')
DASH = os.environ.get('OPR_DASH', '/workspace/horn-wilmes/dashboard')
RUN_STATUS = os.environ.get('OPR_RUN_STATUS', '1') == '1'
PORT = int(os.environ.get('OPR_PORT', '8081'))
STAGEA = os.environ.get('OPR_STAGEA', '/workspace/horn-wilmes/stageA')
STAGEB = os.environ.get('OPR_STAGEB', '/workspace/horn-wilmes/stageB')
TRANSCRIPTION_APPROVE_ENABLED = True
EXTRACTION_APPROVE_ENABLED = True          # Stephen 2026-09-29: extraction Approve locks the Stage B records
NOTIFY_QUEUE = os.path.join(DASH, 'notify_queue.jsonl')
BACKUPS = os.environ.get('OPR_BACKUPS', os.path.join(os.path.dirname(STAGEA), '_approve_backups'))
LOCKED_VALUES = {'locked', 'approved', 'final'}
LOCKFILE = os.path.join(ENTRIES, '.manifest.lock')      # shared lock convention for manifest writers
ALLOWED_ORIGINS = {'http://grokbot-box.taileabb91.ts.net', 'https://grokbot-box.taileabb91.ts.net', 'http://grokbot-box',
                   'http://127.0.0.1:8080', 'http://localhost:8080', 'null', 'file://',
                   'https://oldparishrecords.com', 'https://www.oldparishrecords.com'}   # oldparishrecords.com/dashboard/ (OPNsense nginx + HTTP basic auth, prefix stripped)   # file:// pages send Origin null (or file:// in some Chrome modes)
ALLOWED_ORIGINS |= {o.strip() for o in os.environ.get('OPR_EXTRA_ORIGINS', '').split(',') if o.strip()}   # scratch testing only
REFERER_PREFIXES = tuple(o + '/' for o in ALLOWED_ORIGINS if o not in ('null', 'file://')) + ('file://',)
PENDING = {'pending', 'draft'}
tlock = threading.Lock()

def now_ct():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')

class Reject(Exception):
    def __init__(s, msg, code=409): super().__init__(msg); s.http = code

def dashboard_rows():
    p = os.path.join(DASH, 'out', 'status.json')
    rows = json.load(open(p, encoding='utf-8'))['rows']
    recs = {r['code']: r for r in json.load(open(os.path.join(DASH, 'records.json'), encoding='utf-8'))['records']}
    return {r['code']: (r, recs.get(r['code'], {}).get('image_id')) for r in rows}

def read_lines(path):
    st = os.stat(path); data = open(path, 'rb').read()
    return data, (st.st_mtime_ns, st.st_size)

def entries_for(data, img):
    """[(line_index, dict)] of manifest lines for image_id img."""
    out = []
    for i, raw in enumerate(data.split(b'\n')):
        if not raw.strip(): continue
        try: j = json.loads(raw)
        except ValueError: continue
        if (j.get('image_id') or j.get('scan')) == img: out.append((i, j))
    return out

def crop_state(j):
    return str(j.get('crop_status', '')).lower(), str(j.get('status', '') or '').lower()

def lock_line(raw, stamp):
    """Byte-level edit: set crop_status to locked and set/insert locked_by. Everything else stays byte-identical."""
    s = raw.decode('utf-8')
    s2, n = re.subn(r'("crop_status":\s*)"(?:[^"\\]|\\.)*"', r'\1"locked"', s, count=1)
    if n != 1: raise Reject('manifest line has no crop_status field; nothing changed', 500)
    val = json.dumps(stamp)
    if re.search(r'"locked_by":\s*(?:"(?:[^"\\]|\\.)*"|null)', s2):
        s2 = re.sub(r'("locked_by":\s*)(?:"(?:[^"\\]|\\.)*"|null)', lambda m: m.group(1) + val, s2, count=1)
    else:
        k = s2.rstrip().rfind('}')
        if k < 0: raise Reject('malformed manifest line; nothing changed', 500)
        s2 = s2[:k] + ', "locked_by": ' + val + s2[k:]
    a, b = json.loads(s), json.loads(s2)
    a['crop_status'] = 'locked'; a['locked_by'] = stamp
    if a != b: raise Reject('internal check failed: edit would change other fields; nothing changed', 500)
    return s2.encode('utf-8')

def atomic_write(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.approve-', suffix='.tmp')
    with os.fdopen(fd, 'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, os.stat(path).st_mode & 0o777); os.replace(tmp, path)

def next_bak(path):
    n = 1
    for p in glob.glob(path + '.bak*'):
        m = re.fullmatch(re.escape(path) + r'\.bak(\d+)', p)
        if m: n = max(n, int(m.group(1)) + 1)
    return f'{path}.bak{n}'

HOLD = 'On hold until crops approved'
HOLD_KEYS = ('prev_transcription', 'prev_transcription_override', 'redo_prev_transcription', 'hold_set')

def is_hold(e):
    """Transcription hold set by a recut request (or the legacy 'Not started' hold used for the 2026-09-29 re-cuts)."""
    t = e.get('transcription')
    return t == HOLD or (t == 'Not started' and ('redo_prev_transcription' in e or 'prev_transcription' in e
                                                  or 'crops are approved' in str(e.get('note', ''))))

def release_hold(e):
    """After the crops are approved: drop the hold so the transcription status is file-derived again (Queued, Draft, ...)."""
    if not is_hold(e): return False
    e.pop('transcription', None)
    for k in HOLD_KEYS: e.pop(k, None)
    if 'crops are approved' in str(e.get('note', '')) or 'recut requested' in str(e.get('note', '')).lower(): e.pop('note', None)
    return True

def write_overrides(ov):
    op = os.path.join(DASH, 'overrides.json')
    fd, tmp = tempfile.mkstemp(dir=DASH, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(ov, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o644); os.replace(tmp, op)

SELFTEST_DIR = os.path.join(DASH, '_selftest')
SELFTEST_CODE = 'TEST0000'
def selftest(code, client, h):
    """Safe end-to-end test target for Site Host (action 'selftest', code 'TEST0000'). Runs the same request path
    (origin/referer + X-OPR-Approve checks, JSON body, server thread lock, a brief shared flock on the manifest lock)
    but writes ONLY dashboard/_selftest/selftest.jsonl + last.json. Never touches manifests, Stage A/B, overrides,
    _approvals.log or notify_queue.jsonl, and never runs status.py."""
    if code != SELFTEST_CODE: raise Reject(f'selftest only accepts code {SELFTEST_CODE!r}; nothing changed', 400)
    lf = open(LOCKFILE, 'a+'); t0 = time.time()
    try:
        fcntl.flock(lf, fcntl.LOCK_SH); waited = round(time.time() - t0, 3)
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN); lf.close()
    now = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    ev = {'time': now, 'action': 'selftest', 'test': True, 'code': code, 'client': client, 'origin': h.get('Origin'),
          'referer': h.get('Referer'), 'x_forwarded_for': h.get('X-Forwarded-For'), 'x_forwarded_proto': h.get('X-Forwarded-Proto'),
          'host': h.get('Host'), 'lock_wait_s': waited}
    os.makedirs(SELFTEST_DIR, exist_ok=True)
    with open(os.path.join(SELFTEST_DIR, 'selftest.jsonl'), 'a', encoding='utf-8') as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.write(json.dumps(ev, ensure_ascii=False) + '\n')
    fd, tmp = tempfile.mkstemp(dir=SELFTEST_DIR, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(ev, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o644); os.replace(tmp, os.path.join(SELFTEST_DIR, 'last.json'))
    return dict(ok=True, selftest=True, wrote='dashboard/_selftest/ only', **ev)

def notify(evt):
    """Append one event line to dashboard/notify_queue.jsonl (watched by Chief). Used by ALL three actions."""
    with open(NOTIFY_QUEUE, 'a', encoding='utf-8') as f:
        fcntl.flock(f, fcntl.LOCK_EX); f.write(json.dumps(evt, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())

def approve(code, client):
    rows = dashboard_rows()
    if code not in rows: raise Reject(f'unknown code {code!r}: not a current dashboard row', 404)
    row, img = rows[code]
    seg = str(row.get('segmentation', {}).get('status', '')); sl = seg.lower()
    if not (sl.startswith('draft') or sl.startswith('recut')):
        raise Reject(f'{code}: segmentation is {seg!r}; only Draft or Recut rows can be approved; nothing changed', 409)
    if not img: raise Reject(f'{code}: no image_id in records.json', 409)
    gpath = os.path.join(ENTRIES, 'manifest.jsonl')
    lf = open(LOCKFILE, 'a+')
    t0 = time.time()
    while True:
        try: fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB); break
        except BlockingIOError:
            if time.time() - t0 > 15: raise Reject('manifest is locked by another writer; try again', 503)
            time.sleep(0.2)
    try:
        gdata, gsig = read_lines(gpath)
        gents = entries_for(gdata, img)
        books = [p for p in glob.glob(os.path.join(ENTRIES, '*', 'manifest.jsonl'))
                 if not os.path.basename(os.path.dirname(p)).startswith('_') and entries_for(read_lines(p)[0], img)]
        if not gents: raise Reject(f'{code}: no crops in entries/manifest.jsonl; nothing changed', 409)
        if len(books) != 1: raise Reject(f'{code}: expected exactly one book manifest with these crops, found {len(books)}; nothing changed', 409)
        bpath = books[0]; bdata, bsig = read_lines(bpath); bents = entries_for(bdata, img)
        ids = lambda es: sorted(j.get('entry_id') for _, j in es)
        if ids(gents) != ids(bents): raise Reject(f'{code}: the two manifests disagree on the crop list; nothing changed', 409)
        states = [crop_state(j) for _, j in gents + bents]
        bad = [(j.get('entry_id'), j.get('crop_status')) for _, j in gents if crop_state(j)[0] not in PENDING or crop_state(j)[1] == 'locked']
        bad += [(j.get('entry_id'), j.get('crop_status')) for _, j in bents if crop_state(j)[0] not in PENDING or crop_state(j)[1] == 'locked']
        if bad:
            nl = sum(1 for s in states if s[0] == 'locked' or s[1] == 'locked')
            raise Reject(f'{code}: not every crop is pending/draft ({nl} of {len(states)} crop records already locked or other status); nothing changed', 409)
        stamp_t = now_ct(); stamp = f'Stephen dashboard Approve {stamp_t}'
        def edit(data, ents):
            lines = data.split(b'\n'); idx = {i for i, _ in ents}
            for i in idx: lines[i] = lock_line(lines[i], stamp)
            return b'\n'.join(lines)
        new_b, new_g = edit(bdata, bents), edit(gdata, gents)
        # optimistic check: nobody changed the files while we worked (Segmenter does not take the lock)
        if read_lines(bpath)[1] != bsig or read_lines(gpath)[1] != gsig:
            raise Reject('a manifest changed during the approval (another writer); nothing changed - try again', 503)
        ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        baks = []
        for p in (bpath, gpath):
            b = f'{p}.bak_approve_{code}_{ts}'; shutil.copy2(p, b); baks.append(b)
        with open(os.path.join(ENTRIES, '_approvals.log'), 'a') as f:
            f.write(f'{stamp_t}\t{code}\t{os.path.basename(os.path.dirname(bpath))}\t{len(gents)} crops\t{client}\n')
        atomic_write(bpath, new_b); atomic_write(gpath, new_g)
        # verify both manifests agree and all crops are locked with our stamp
        vb = {j['entry_id']: (j.get('crop_status'), j.get('locked_by')) for _, j in entries_for(read_lines(bpath)[0], img)}
        vg = {j['entry_id']: (j.get('crop_status'), j.get('locked_by')) for _, j in entries_for(read_lines(gpath)[0], img)}
        ok = vb == vg and all(v == ('locked', stamp) for v in vg.values())
        if not ok: raise Reject('post-write verification failed: manifests disagree; backups: ' + ', '.join(baks), 500)
        # queue line only after the lock is verified (Chief acts on it)
        notify({'time': stamp_t, 'action': 'segmentation', 'row': row.get('id'), 'code': code, 'image_id': img, 'files': len(gents),
                'locked_by': stamp, 'id': f'segmentation-{code}-{ts}'})
        # overrides: drop segmentation hold for this code
        ov_note = 'no segmentation override'
        op = os.path.join(DASH, 'overrides.json')
        try:
            ov = json.load(open(op, encoding='utf-8'))
            if isinstance(ov.get(code), dict) and (({'segmentation', 'seg_redo_note', 'seg_stage', 'seg_stage_set'} & set(ov[code])) or is_hold(ov[code])):
                ob = next_bak(op); shutil.copy2(op, ob)
                for k in ('segmentation', 'seg_redo_note', 'seg_stage', 'seg_stage_set'): ov[code].pop(k, None)   # stage override + legacy keys
                held = release_hold(ov[code])                                 # crops approved -> transcription no longer on hold
                if not ov[code]: ov.pop(code)
                fd, tmp = tempfile.mkstemp(dir=DASH, suffix='.tmp')
                with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(ov, f, ensure_ascii=False, indent=1)
                os.chmod(tmp, 0o644); os.replace(tmp, op); ov_note = f'segmentation override removed{" and transcription hold released" if held else ""} (backup {os.path.basename(ob)})'
        except Exception as ex: ov_note = f'overrides not changed: {ex}'
        st = ''
        if RUN_STATUS:
            p = subprocess.run(['python3', 'status.py'], cwd=DASH, capture_output=True, text=True, timeout=120)
            st = 'status.py ok' if p.returncode == 0 else f'status.py failed: {p.stderr[-300:]}'
        return {'ok': True, 'code': code, 'row': row.get('id'), 'book': os.path.basename(os.path.dirname(bpath)),
                'crops': len(gents), 'locked_by': stamp, 'backups': [os.path.basename(b) for b in baks],
                'overrides': ov_note, 'status': st, 'notify': f'segmentation-{code}-{ts}'}
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN); lf.close()


# ---------- transcription (Stage A) / extraction (Stage B) approval ----------
def _toplevel_spans(text):
    """{key: (value_start, value_end, key_start)} for the top-level keys of a JSON object text (string/nesting aware)."""
    n = len(text); i = text.index('{') + 1; out = {}
    def end_str(k):                                   # k at opening quote -> index after closing quote
        k += 1
        while text[k] != '"': k += 2 if text[k] == '\\' else 1
        return k + 1
    def end_val(k):                                   # k at value start -> index after the value
        if text[k] == '"': return end_str(k)
        if text[k] in '[{':
            d = 0
            while True:
                c = text[k]
                if c == '"': k = end_str(k); continue
                if c in '[{': d += 1
                elif c in ']}':
                    d -= 1
                    if d == 0: return k + 1
                k += 1
        while k < n and text[k] not in ',}] \t\r\n': k += 1
        return k
    while i < n:
        c = text[i]
        if c == '"':
            ks = i; ke = end_str(i); key = json.loads(text[ks:ke]); j = ke
            while text[j] in ' \t\r\n': j += 1
            if text[j] != ':': raise Reject('JSON scan failed; nothing changed', 500)
            j += 1
            while text[j] in ' \t\r\n': j += 1
            ve = end_val(j); out[key] = (j, ve, ks); i = ve
        elif c == '}': break
        else: i += 1
    return out

def set_toplevel(raw, updates, anchor):
    """Byte-level edit of top-level fields. Existing keys: value replaced in place. New keys: inserted right after
    `anchor`, on their own line with the same indentation. Everything else stays byte-identical (verified)."""
    text = raw.decode('utf-8'); sp = _toplevel_spans(text)
    if anchor not in sp: raise Reject(f'file has no top-level {anchor!r} field; nothing changed', 500)
    edits = []; ins = []
    for k, v in updates.items():
        if k in sp: edits.append((sp[k][0], sp[k][1], json.dumps(v, ensure_ascii=False)))
        else: ins.append((k, v))
    if ins:
        a_vs, a_ve, a_ks = sp[anchor]
        ls = text.rfind('\n', 0, a_ks) + 1; indent = text[ls:a_ks]
        sep = ('\n' + indent) if ls > 0 and indent.strip() == '' else ' '
        edits.append((a_ve, a_ve, ''.join(f',{sep}{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}' for k, v in ins)))
    edits.sort(); new = text
    for s0, e0, rp in reversed(edits): new = new[:s0] + rp + new[e0:]
    # byte check: undoing our edits on the new text must give back the original text exactly
    parts = []; cur = 0
    for s0, e0, rp in edits:                           # walk new text in order
        parts.append(text[cur:s0]); parts.append(rp); cur = e0
    parts.append(text[cur:])
    if ''.join(parts) != new: raise Reject('internal byte check failed; nothing changed', 500)
    kept = ''.join(text[x:y] for x, y in zip([0] + [e for _, e, _ in edits], [s for s, _, _ in edits] + [len(text)]))
    kept_new, cur, off = [], 0, 0
    for s0, e0, rp in edits:
        kept_new.append(new[cur + off:s0 + off]); off += len(rp) - (e0 - s0); cur = e0
    kept_new.append(new[cur + off:])
    if ''.join(kept_new) != kept: raise Reject('internal byte check failed (untouched bytes differ); nothing changed', 500)
    a, b = json.loads(text), json.loads(new); a.update(updates)
    if a != b: raise Reject('internal check failed: edit would change other fields; nothing changed', 500)
    return new.encode('utf-8')

def stage_approve(code, action, client):
    rows = dashboard_rows()
    if code not in rows: raise Reject(f'unknown code {code!r}: not a current dashboard row', 404)
    row, img = rows[code]
    cur = str(row.get(action, {}).get('status', ''))
    if not cur.lower().startswith('draft'):
        raise Reject(f'{code}: {action} is {cur!r}; only Draft rows can be approved; nothing changed', 409)
    if action == 'transcription':
        d = os.path.join(STAGEA, code); pat = '*.diplomatic.json'; skey = 'status'
    else:
        d = os.path.join(STAGEB, code); pat = '*.json'; skey = 'stage_b_status'
    lf = open(LOCKFILE, 'a+'); t0 = time.time()
    while True:
        try: fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB); break
        except BlockingIOError:
            if time.time() - t0 > 15: raise Reject('lock is held by another writer; try again', 503)
            time.sleep(0.2)
    try:
        files = sorted(p for p in glob.glob(os.path.join(d, pat)) if os.path.isfile(p) and '.bak' not in os.path.basename(p))
        if not files: raise Reject(f'{code}: no {"Stage A" if action == "transcription" else "Stage B"} files in {d}; nothing changed', 409)
        if action == 'transcription':          # every manifest entry (non-blank) must have its Stage A file
            man = {}
            for l in open(os.path.join(ENTRIES, 'manifest.jsonl'), encoding='utf-8'):
                try: j = json.loads(l)
                except ValueError: continue
                if (j.get('image_id') or j.get('scan')) == img and j.get('entry_kind') != 'blank': man[j['entry_id']] = 1
            have = {os.path.basename(p)[:-len('.diplomatic.json')] for p in files}
            miss = sorted(set(man) - have)
            if not man or miss: raise Reject(f'{code}: Stage A incomplete ({len(miss)} manifest entries have no diplomatic JSON); nothing changed', 409)
        before = {}
        for p in files:
            raw = open(p, 'rb').read(); st = os.stat(p)
            try: j = json.loads(raw)
            except ValueError: raise Reject(f'{code}: {os.path.basename(p)} is not valid JSON; nothing changed', 409)
            if not isinstance(j, dict) or skey not in j: raise Reject(f'{code}: {os.path.basename(p)} has no top-level {skey!r}; nothing changed', 409)
            if str(j[skey]).lower() in LOCKED_VALUES:
                if action == 'transcription': continue          # entries approved one by one stay as they are
                nl = sum(1 for q in files if str(json.load(open(q, encoding='utf-8')).get(skey, '')).lower() in LOCKED_VALUES)
                raise Reject(f'{code}: {nl} of {len(files)} files already locked ({skey}); nothing changed', 409)
            before[p] = (raw, (st.st_mtime_ns, st.st_size))
        if not before: raise Reject(f'{code}: every entry is already locked; nothing changed', 409)
        files = sorted(before)
        stamp_t = now_ct(); stamp = f'Stephen dashboard Approve {stamp_t}'
        if action == 'transcription': upd, anchor = {'status': 'locked', 'locked_by': stamp}, 'status'
        else: upd, anchor = {'stage_b_status': 'locked', 'stage_b_locked_at': stamp_t, 'stage_b_locked_by': stamp}, 'stage_b_locked_at'
        new = {}
        for p, (raw, _) in before.items():
            a = anchor if anchor in json.loads(raw) else skey
            new[p] = set_toplevel(raw, upd, a)
            if action == 'transcription':      # diplomatic content must stay identical
                oj, nj = json.loads(raw), json.loads(new[p])
                for k in oj:
                    if k not in upd and oj[k] != nj[k]: raise Reject(f'internal check failed on {k}; nothing changed', 500)
        for p, (_, sig) in before.items():
            st = os.stat(p)
            if (st.st_mtime_ns, st.st_size) != sig: raise Reject(f'{os.path.basename(p)} changed during the approval; nothing changed - try again', 503)
        ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S'); bdir = os.path.join(BACKUPS, action, f'{code}_{ts}')   # outside stageA/stageB so no glob ever sees the copies
        os.makedirs(bdir, exist_ok=False)
        for p in files: shutil.copy2(p, os.path.join(bdir, os.path.basename(p)))
        for p in files: atomic_write(p, new[p])
        for p in files:                        # verify
            oj, nj = json.loads(before[p][0]), json.load(open(p, encoding='utf-8')); oj.update(upd)
            if oj != nj: raise Reject(f'post-write verification failed on {os.path.basename(p)}; backups in {bdir}', 500)
        n = len(files)
        with open(os.path.join(ENTRIES, '_approvals.log'), 'a') as f:
            f.write(f'{stamp_t}\taction={action}\trow {row.get("id")}\t{code}\t{n} {"Stage A" if action == "transcription" else "Stage B"} files locked\tlocked_by={stamp}\tclient={client}\n')
        evt = {'time': stamp_t, 'action': action, 'row': row.get('id'), 'code': code, 'image_id': img, 'files': n,
               'locked_by': stamp, 'id': f'{action}-{code}-{ts}'}
        notify(evt)
        st = ''; now_status = None
        if RUN_STATUS:
            pr = subprocess.run(['python3', 'status.py'], cwd=DASH, capture_output=True, text=True, timeout=120)
            st = 'status.py ok' if pr.returncode == 0 else f'status.py failed: {pr.stderr[-300:]}'
            try: now_status = dashboard_rows()[code][0][action]['status']
            except Exception: pass
        return {'ok': True, 'action': action, 'code': code, 'row': row.get('id'), 'files': n, 'locked_by': stamp,
                'backup_dir': bdir, 'notify': evt['id'], 'status': st, 'dashboard_status': now_status}
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN); lf.close()

def recut(code, client):
    """Request a re-cut of an Approved row: overrides only (Queued for redo + transcription hold). Never touches manifests,
    crops, Stage A or Stage B - the Entry Segmenter does the unlocking and re-cutting."""
    rows = dashboard_rows()
    if code not in rows: raise Reject(f'unknown code {code!r}: not a current dashboard row', 404)
    row, img = rows[code]
    op = os.path.join(DASH, 'overrides.json')
    lf = open(LOCKFILE, 'a+'); t0 = time.time()
    while True:
        try: fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB); break
        except BlockingIOError:
            if time.time() - t0 > 15: raise Reject('lock is held by another writer; try again', 503)
            time.sleep(0.2)
    try:
        ov = json.load(open(op, encoding='utf-8')); e = ov.get(code) if isinstance(ov.get(code), dict) else {}
        seg = str(row.get('segmentation', {}).get('status', ''))
        if not seg.lower().startswith('approved') or e.get('segmentation'):
            raise Reject(f'{code}: segmentation is {e.get("segmentation") or seg!r}; a recut can only be requested for an Approved row with no redo stage; nothing changed', 409)
        tr = str(row.get('transcription', {}).get('status', ''))
        has_files = bool(glob.glob(os.path.join(STAGEA, code, '*.diplomatic.json')) or glob.glob(os.path.join(STAGEB, code, '*.json')))
        hold = has_files or tr.lower() != 'not started'
        stamp_t = now_ct(); ob = next_bak(op); shutil.copy2(op, ob)
        e['segmentation'] = 'Queued for redo'; e['seg_stage_set'] = stamp_t
        if hold and e.get('transcription') != HOLD:
            e['prev_transcription'] = tr                                   # what the dashboard showed (for the record)
            e['prev_transcription_override'] = e.get('transcription')     # None = was file-derived (restore = drop override)
            e['transcription'] = HOLD; e['hold_set'] = stamp_t
            e['note'] = f'Recut requested {stamp_t[:16].replace("T", " ")} CT; transcription on hold until the new crops are approved.'
        ov[code] = e; write_overrides(ov)
        line = {'time': stamp_t, 'action': 'recut', 'row': row.get('id'), 'code': code, 'image_id': img, 'requested_by': 'Stephen dashboard'}
        with open(os.path.join(ENTRIES, '_approvals.log'), 'a') as f: f.write(json.dumps(line, ensure_ascii=False) + '\n')
        notify(line)
        st = ''
        if RUN_STATUS:
            pr = subprocess.run(['python3', 'status.py'], cwd=DASH, capture_output=True, text=True, timeout=120)
            st = 'status.py ok' if pr.returncode == 0 else f'status.py failed: {pr.stderr[-300:]}'
        return {'ok': True, 'action': 'recut', 'code': code, 'row': row.get('id'), 'segmentation': 'Queued for redo',
                'transcription': HOLD if hold else tr, 'time': stamp_t, 'overrides_backup': os.path.basename(ob), 'status': st}
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN); lf.close()

# ---------- per-entry transcription approval + reading confirmation ----------
TOKRE = re.compile(r'([^\s\[\]|()]+)\[\?\]')          # <token>[?] - token = run of non-space chars (Unicode ok)

def _lock(lf_path=None):
    lf = open(LOCKFILE, 'a+'); t0 = time.time()
    while True:
        try: fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB); return lf
        except BlockingIOError:
            if time.time() - t0 > 15: lf.close(); raise Reject('lock is held by another writer; try again', 503)
            time.sleep(0.2)

def _unlock(lf):
    fcntl.flock(lf, fcntl.LOCK_UN); lf.close()

def _atomic_json(path, obj):
    data = (json.dumps(obj, ensure_ascii=False, indent=1) + '\n').encode('utf-8')
    if os.path.exists(path): atomic_write(path, data)
    else:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.approve-', suffix='.tmp')
        with os.fdopen(fd, 'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp, 0o644); os.replace(tmp, path)

def _backup(action, code, paths):
    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')[:-3]
    bdir = os.path.join(BACKUPS, action, f'{code}_{ts}'); os.makedirs(bdir, exist_ok=False)
    for p in paths:
        if os.path.exists(p): shutil.copy2(p, os.path.join(bdir, os.path.basename(p)))
    return bdir

def _entry_file(code, entry_id):
    if not re.fullmatch(r'[A-Za-z0-9_.\-]+', entry_id or ''): raise Reject('bad entry_id', 400)
    p = os.path.join(STAGEA, code, entry_id + '.diplomatic.json')
    if not os.path.isfile(p): raise Reject(f'{code}: no Stage A file for {entry_id}; nothing changed', 409)
    return p

def _crop_paths(img, entry_id):
    out = []
    for l in open(os.path.join(ENTRIES, 'manifest.jsonl'), encoding='utf-8'):
        try: j = json.loads(l)
        except ValueError: continue
        if j.get('entry_id') == entry_id and j.get('crop_path'): out.append(j['crop_path'])
    if not out:                                   # Stage A entry spanning faces (e.g. ..._e3 -> ..._L_e3 / ..._R_e3)
        m = re.match(r'(.*)_(e\d+)$', entry_id)
        if m:
            for l in open(os.path.join(ENTRIES, 'manifest.jsonl'), encoding='utf-8'):
                try: j = json.loads(l)
                except ValueError: continue
                if re.fullmatch(re.escape(m.group(1)) + r'_[LR]_' + m.group(2), str(j.get('entry_id'))) and j.get('crop_path'): out.append(j['crop_path'])
    return out

def _row_meta(code):
    rows = dashboard_rows()
    if code not in rows: raise Reject(f'unknown code {code!r}: not a current dashboard row', 404)
    return rows[code]

def _feedback_add(code, entry_id, token, occurrence, stamp_t):
    fp = os.path.join(STAGEA, code, '_feedback_status.json')
    try: fb = json.load(open(fp, encoding='utf-8'))
    except Exception: fb = {}
    e = fb.get(entry_id) if isinstance(fb.get(entry_id), dict) else {}
    items = e.get('items') if isinstance(e.get('items'), list) else []
    items.append({'token': token, 'occurrence': occurrence, 'state': 'pending', 'updated_at': stamp_t})
    fb[entry_id] = {'state': 'pending', 'items': items, 'updated_at': stamp_t}
    _atomic_json(fp, fb)

def approve_transcription_entry(code, entry_id, client):
    row, img = _row_meta(code)
    cur = str(row.get('transcription', {}).get('status', ''))
    if not cur.lower().startswith('draft'): raise Reject(f'{code}: transcription is {cur!r}; per-entry approval needs a Draft row; nothing changed', 409)
    p = _entry_file(code, entry_id)
    lf = _lock()
    try:
        raw = open(p, 'rb').read(); j = json.loads(raw)
        if str(j.get('status', '')).lower() in LOCKED_VALUES: raise Reject(f'{entry_id} is already locked; nothing changed', 409)
        stamp_t = now_ct(); stamp = f'Stephen dashboard Approve {stamp_t}'
        new = set_toplevel(raw, {'status': 'locked', 'locked_by': stamp, 'locked_at': stamp_t}, 'status')
        ap = os.path.join(STAGEA, code, '_entry_approvals.json')
        bdir = _backup('approve_transcription_entry', code, [p, ap])
        atomic_write(p, new)
        nj = json.load(open(p, encoding='utf-8')); j.update({'status': 'locked', 'locked_by': stamp, 'locked_at': stamp_t})
        if nj != j: raise Reject(f'post-write verification failed; backup in {bdir}', 500)
        try: al = json.load(open(ap, encoding='utf-8'))
        except Exception: al = []
        al.append({'entry_id': entry_id, 'time': stamp_t, 'by': 'Stephen dashboard'}); _atomic_json(ap, al)
        rec = next((x for x in json.load(open(os.path.join(DASH, 'records.json'), encoding='utf-8'))['records'] if x['code'] == code), {})
        files = sorted(glob.glob(os.path.join(STAGEA, code, '*.diplomatic.json')))
        nl = sum(1 for q in files if str(json.load(open(q, encoding='utf-8')).get('status', '')).lower() in LOCKED_VALUES)
        with open(os.path.join(ENTRIES, '_approvals.log'), 'a') as f:
            f.write(f'{stamp_t}\taction=approve_transcription_entry\trow {row.get("id")}\t{code}\t{entry_id}\tlocked_by={stamp}\tclient={client}\n')
        notify({'time': stamp_t, 'kind': 'transcription_entry_approved', 'action': 'approve_transcription_entry', 'row': row.get('id'),
                'code': code, 'book': rec.get('book'), 'page': rec.get('page'), 'image_id': img, 'entry_id': entry_id,
                'locked_entries': nl, 'total_entries': len(files), 'locked_by': stamp, 'source_file': p})
        flipped = False
        if nl == len(files):                      # last entry -> row is Approved exactly like the row button
            flipped = True
            with open(os.path.join(ENTRIES, '_approvals.log'), 'a') as f:
                f.write(f'{stamp_t}\taction=transcription\trow {row.get("id")}\t{code}\t{len(files)} Stage A files locked (auto-flip after per-entry approvals)\tlocked_by={stamp}\tclient={client}\n')
            notify({'time': stamp_t, 'action': 'transcription', 'row': row.get('id'), 'code': code, 'image_id': img, 'files': len(files),
                    'locked_by': stamp, 'id': f'transcription-{code}-{stamp_t[:19].replace("-", "").replace(":", "").replace("T", "-")}',
                    'auto_flip': True, 'via': 'per-entry approvals'})
        st = ''
        if RUN_STATUS:
            pr = subprocess.run(['python3', 'status.py'], cwd=DASH, capture_output=True, text=True, timeout=120)
            st = 'status.py ok' if pr.returncode == 0 else f'status.py failed: {pr.stderr[-300:]}'
        return {'ok': True, 'action': 'approve_transcription_entry', 'code': code, 'entry_id': entry_id, 'locked_by': stamp,
                'locked_entries': nl, 'total_entries': len(files), 'row_approved': flipped, 'backup_dir': bdir, 'status': st}
    finally:
        _unlock(lf)

def _json_str_positions(text, vs, ve):
    """For the JSON string literal text[vs:ve] -> (decoded string, [encoded index of each decoded char])."""
    assert text[vs] == '"' and text[ve - 1] == '"'
    out = []; pos = []; i = vs + 1
    while i < ve - 1:
        c = text[i]
        if c == '\\':
            n = text[i + 1]
            if n == 'u':
                cp = int(text[i + 2:i + 6], 16); ln = 6
                if 0xD800 <= cp < 0xDC00 and text[i + 6:i + 8] == '\\u':
                    lo = int(text[i + 8:i + 12], 16); cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00); ln = 12
                out.append(chr(cp)); pos.append(i); i += ln
            else:
                out.append({'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f'}.get(n, n)); pos.append(i); i += 2
        else: out.append(c); pos.append(i); i += 1
    return ''.join(out), pos

def confirm_reading(code, entry_id, field, token, occurrence, ctx, client):
    row, img = _row_meta(code)
    cur = str(row.get('transcription', {}).get('status', ''))
    if not cur.lower().startswith(('draft', 'approved')): raise Reject(f'{code}: transcription is {cur!r}; nothing changed', 409)
    if not token or '[?]' in token or not isinstance(occurrence, int) or occurrence < 1: raise Reject('bad token/occurrence', 400)
    md = entry_id == f'{code}_stageA.md'
    if md: p = os.path.join(STAGEA, code, f'{code}_stageA.md'); field = 'md'
    else:
        p = _entry_file(code, entry_id)
        if field not in ('diplomatic_text', 'diplomatic_margin'): raise Reject('bad field', 400)
    lf = _lock()
    try:
        raw = open(p, 'rb').read(); text = raw.decode('utf-8')
        if md: s_val, posmap, base = text, list(range(len(text))), 0
        else:
            sp = _toplevel_spans(text)
            if field not in sp: raise Reject(f'{entry_id}: no {field}; nothing changed', 409)
            vs, ve, _ = sp[field]
            if text[vs] != '"': raise Reject(f'{entry_id}: {field} is not a string; nothing changed', 409)
            s_val, posmap = _json_str_positions(text, vs, ve)
            if s_val != json.loads(raw)[field]: raise Reject('internal decode check failed; nothing changed', 500)
        hits = [m for m in TOKRE.finditer(s_val) if m.group(1) == token]
        if len(hits) < occurrence: raise Reject(f'{entry_id}: "{token}[?]" occurrence {occurrence} not found (text may have changed or it was already confirmed); nothing changed', 409)
        m = hits[occurrence - 1]; k = m.end(1)                       # index of '[' in decoded text
        if ctx is not None and not s_val[:m.start(1)].endswith(ctx):
            raise Reject(f'{entry_id}: the text around "{token}[?]" has changed since the page was built; reload and try again; nothing changed', 409)
        e0 = posmap[k]
        if text[e0:e0 + 3] != '[?]': raise Reject('internal position check failed; nothing changed', 500)
        new = text[:e0] + text[e0 + 3:]
        # verify: exactly 3 characters removed, nothing else
        if len(new) != len(text) - 3 or new[:e0] != text[:e0] or new[e0:] != text[e0 + 3:]: raise Reject('internal byte check failed', 500)
        if not md:
            a, b = json.loads(raw), json.loads(new); a[field] = s_val[:k] + s_val[k + 3:]
            if a != b: raise Reject('internal check failed: other fields would change; nothing changed', 500)
        stamp_t = now_ct()
        cr = os.path.join(STAGEA, code, '_confirmed_readings.json'); fbp = os.path.join(STAGEA, code, '_feedback_status.json')
        bdir = _backup('confirm_reading', code, [p, cr, fbp])
        atomic_write(p, new.encode('utf-8'))
        cb, ca = s_val[max(0, m.start(1) - 40):m.start(1)], s_val[m.end():m.end() + 40]
        try: crl = json.load(open(cr, encoding='utf-8'))
        except Exception: crl = []
        crl.append({'entry_id': entry_id, 'field': field, 'token': token, 'occurrence': occurrence, 'time': stamp_t, 'by': 'Stephen dashboard',
                    'context_before': cb, 'context_after': ca})
        _atomic_json(cr, crl)
        _feedback_add(code, entry_id, token, occurrence, stamp_t)
        rec = next((x for x in json.load(open(os.path.join(DASH, 'records.json'), encoding='utf-8'))['records'] if x['code'] == code), {})
        with open(os.path.join(ENTRIES, '_approvals.log'), 'a') as f:
            f.write(f'{stamp_t}\taction=confirm_reading\trow {row.get("id")}\t{code}\t{entry_id}\t{field}\t{token}[?] -> {token} (occurrence {occurrence})\tclient={client}\n')
        notify({'time': stamp_t, 'kind': 'reading_confirmed', 'action': 'confirm_reading', 'row': row.get('id'), 'code': code,
                'book': rec.get('book'), 'page': rec.get('page'), 'image_id': img, 'entry_id': entry_id, 'field': field,
                'occurrence': occurrence, 'token_before': token + '[?]', 'token_after': token, 'context_before': cb, 'context_after': ca,
                'source_file': p, 'crop_paths': [] if md else _crop_paths(img, entry_id), 'by': 'Stephen dashboard'})
        st = ''
        if RUN_STATUS:
            pr = subprocess.run(['python3', 'status.py'], cwd=DASH, capture_output=True, text=True, timeout=120)
            st = 'status.py ok' if pr.returncode == 0 else f'status.py failed: {pr.stderr[-300:]}'
        return {'ok': True, 'action': 'confirm_reading', 'code': code, 'entry_id': entry_id, 'token': token, 'occurrence': occurrence,
                'time': stamp_t, 'removed_chars': 3, 'backup_dir': bdir, 'status': st}
    finally:
        _unlock(lf)

class H(http.server.BaseHTTPRequestHandler):
    server_version = 'opr-approve/1'
    def origin_ok(s):
        o = s.headers.get('Origin'); r = s.headers.get('Referer', '')
        if o is not None: return o in ALLOWED_ORIGINS, o
        return (r.startswith(REFERER_PREFIXES), None)
    def cors(s, origin):
        if origin in ALLOWED_ORIGINS:
            s.send_header('Access-Control-Allow-Origin', origin); s.send_header('Vary', 'Origin')
            s.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
            s.send_header('Access-Control-Allow-Headers', 'Content-Type, X-OPR-Approve')
            s.send_header('Access-Control-Allow-Private-Network', 'true'); s.send_header('Access-Control-Max-Age', '600')
    def reply(s, code, obj, origin=None):
        b = json.dumps(obj, ensure_ascii=False).encode()
        s.send_response(code); s.cors(origin)
        s.send_header('Content-Type', 'application/json; charset=utf-8'); s.send_header('Cache-Control', 'no-store')
        s.send_header('Content-Length', str(len(b))); s.end_headers(); s.wfile.write(b)
    def client(s):
        ip = s.headers.get('X-Forwarded-For') or s.client_address[0]
        who = s.headers.get('Tailscale-User-Login')
        return ip + (f' ({who})' if who else '')
    def do_OPTIONS(s):
        ok, origin = s.origin_ok()
        if s.path.split('?')[0] not in ('/api/approve', '/dashboard/api/approve') or not ok: s.send_response(403); s.end_headers(); return
        s.send_response(204); s.cors(origin); s.end_headers()
    def do_GET(s):
        s.reply(405, {'ok': False, 'error': 'POST only'})
    def do_POST(s):
        ok, origin = s.origin_ok()
        if s.path.split('?')[0] not in ('/api/approve', '/dashboard/api/approve'): return s.reply(404, {'ok': False, 'error': 'not found'}, origin)
        if not ok: return s.reply(403, {'ok': False, 'error': 'origin/referer not allowed'}, None)
        if s.headers.get('X-OPR-Approve') != '1': return s.reply(403, {'ok': False, 'error': 'missing X-OPR-Approve header'}, origin)
        try:
            n = int(s.headers.get('Content-Length', 0)); body = json.loads(s.rfile.read(min(n, 10000)) or b'{}')
            code = str(body['code']).strip(); action = str(body.get('action') or 'segmentation').strip()
        except Exception: return s.reply(400, {'ok': False, 'error': 'bad request: JSON body {"code": ...} required'}, origin)
        if action not in ('segmentation', 'transcription', 'extraction', 'recut', 'approve_transcription_entry', 'confirm_reading', 'selftest'):
            return s.reply(400, {'ok': False, 'error': f'unknown action {action!r}'}, origin)
        if (action == 'transcription' and not TRANSCRIPTION_APPROVE_ENABLED) or (action == 'extraction' and not EXTRACTION_APPROVE_ENABLED):
            return s.reply(403, {'ok': False, 'error': f'{action} approval is disabled on this server'}, origin)
        try:
            with tlock:
                if action == 'selftest': res = selftest(code, s.client(), s.headers)
                elif action == 'segmentation': res = approve(code, s.client())
                elif action == 'recut': res = recut(code, s.client())
                elif action == 'approve_transcription_entry': res = approve_transcription_entry(code, str(body.get('entry_id') or ''), s.client())
                elif action == 'confirm_reading':
                    occ = body.get('occurrence'); occ = int(occ) if isinstance(occ, (int, str)) and str(occ).isdigit() else None
                    res = confirm_reading(code, str(body.get('entry_id') or ''), str(body.get('field') or 'diplomatic_text'), str(body.get('token') or ''),
                                          occ, body.get('context') if isinstance(body.get('context'), str) else None, s.client())
                else: res = stage_approve(code, action, s.client())
            s.reply(200, res, origin)
        except Reject as ex: s.reply(ex.http, {'ok': False, 'error': str(ex)}, origin)
        except Exception as ex: s.reply(500, {'ok': False, 'error': f'internal error: {ex}'}, origin)
    def log_message(s, fmt, *a):
        print(f'{now_ct()} {s.client()} {fmt % a}', flush=True)

if __name__ == '__main__':
    http.server.ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
