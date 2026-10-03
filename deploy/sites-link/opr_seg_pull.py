#!/usr/bin/env python3
"""Box -> sites segmentation sync. Pulls the Entry Segmenter output from the Grok box's read-only seg-sync
endpoint (tailnet only, bearer token) into the sites dashboard's entries/ tree and overrides.json. Stdlib only.

What it syncs (exactly what the box endpoint serves):
  plain copy (sha256-verified, atomic): entries/<book>/<file> (crops, per-book manifest.jsonl), entries/_qc/<file>,
      entries/_overrides/<file>, entries/_corrections/archive/*.json
  merged:
    entries/manifest.jsonl     box lines are authoritative (new crops, recuts, removed crops), EXCEPT: when sites has
                               locked a crop (Approve on sites) and the box line for the same entry_id has the same
                               crop_path + bbox but is not locked, the sites lock fields are kept.
    entries/_corrections/<code>.json   pending items = union(sites, box) by item id, minus ids found in any
                               _corrections/archive/*.json (resolved by the segmenter). Empty -> file removed (backed up).
    dashboard/overrides.json   only segmentation / seg_* fields; a box change is applied when it is new since the last
                               pull and its seg_stage_set is not older than the sites one (a sites Correct click stays).
                               Box-cleared fields arrive as tombstones and are applied once.
  deletion: a plain file the puller wrote earlier and the box no longer lists is removed if it is unchanged locally.
Writers take the same flock as approve_server.py (entries/.manifest.lock). Backups: entries/_sync_backups/.

Env (/etc/opr-sites-link.env):
  OPR_SEGSYNC_URL   (default http://100.120.170.46/seg-sync)    box tailnet IP + tailscale-serve path
  OPR_SEGSYNC_HOST  (default grokbot-box.taileabb91.ts.net)     Host header tailscale serve answers to
  OPR_SEGSYNC_TOKEN (required; box: /home/box/agent-data/secrets/opr-segsync.env)
  OPR_ENTRIES (default /workspace/horn-wilmes/entries)  OPR_DASH (default /workspace/horn-wilmes/dashboard)
      -> use the SAME values approve_server.py / status.py use on sites (crop_path in the manifest is absolute
         /workspace/horn-wilmes/entries/...; status.py opens it, so that path must resolve on sites).
  OPR_SYNC_STATE (default /var/lib/opr-sites-link/pull_state.json)  OPR_SYNC_INTERVAL (60)
Usage: opr_seg_pull.py [--once] [--dry-run] [-v]
"""
import argparse, datetime, fcntl, glob, hashlib, json, os, shutil, sys, tempfile, time, urllib.parse, urllib.request

E = os.environ.get
URL = E('OPR_SEGSYNC_URL', 'http://100.120.170.46/seg-sync').rstrip('/')
HOSTH = E('OPR_SEGSYNC_HOST', 'grokbot-box.taileabb91.ts.net')
TOKEN = E('OPR_SEGSYNC_TOKEN', '')
ENTRIES = E('OPR_ENTRIES', '/workspace/horn-wilmes/entries')
DASH = E('OPR_DASH', '/workspace/horn-wilmes/dashboard')
STATE = E('OPR_SYNC_STATE', '/var/lib/opr-sites-link/pull_state.json')
INTERVAL = float(E('OPR_SYNC_INTERVAL', '60'))
LOCKFILE = os.path.join(ENTRIES, '.manifest.lock')
BACKUPS = os.path.join(ENTRIES, '_sync_backups')
LOCK_FIELDS = ('crop_status', 'status', 'locked_by', 'locked_at', 'approved_by', 'approved_at')
A = None

def log(m): print(time.strftime('%Y-%m-%dT%H:%M:%S%z'), m, flush=True)
def vlog(m):
    if A.verbose: log(m)

def get(path, timeout=120):
    req = urllib.request.Request(URL + path, headers={'Authorization': f'Bearer {TOKEN}', 'Host': HOSTH, 'User-Agent': 'opr-seg-pull/1'})
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()

def sha(b): return hashlib.sha256(b).hexdigest()
def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

def atomic_write(p, data, mtime=None, mode=0o644):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), suffix='.synctmp')
    with os.fdopen(fd, 'wb') as f: f.write(data)
    os.chmod(tmp, mode)
    if mtime: os.utime(tmp, (mtime, mtime))
    os.replace(tmp, p)

def backup(p, tag):
    if not os.path.exists(p): return
    os.makedirs(BACKUPS, exist_ok=True)
    shutil.copy2(p, os.path.join(BACKUPS, f'{tag}.{time.strftime("%Y%m%d-%H%M%S")}'))
    old = sorted(glob.glob(os.path.join(BACKUPS, f'{tag}.*')))
    for q in old[:-20]: os.remove(q)

class Lock:
    def __enter__(self):
        os.makedirs(ENTRIES, exist_ok=True)
        self.f = open(LOCKFILE, 'a+'); t0 = time.time()
        while True:
            try: fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB); return self
            except BlockingIOError:
                if time.time() - t0 > 30: raise RuntimeError('manifest lock busy for 30 s')
                time.sleep(0.2)
    def __exit__(self, *a): fcntl.flock(self.f, fcntl.LOCK_UN); self.f.close()

def is_special(p):
    return p == 'manifest.jsonl' or (p.startswith('_corrections/') and p.count('/') == 1)

def locked(j): return 'locked' in (str(j.get('crop_status', '')).lower(), str(j.get('status', '') or '').lower())

def merge_manifest(box_raw):
    lp = os.path.join(ENTRIES, 'manifest.jsonl')
    try: local_raw = open(lp, 'rb').read()
    except FileNotFoundError: local_raw = b''
    sites = {}
    for l in local_raw.decode('utf-8').splitlines():
        try: j = json.loads(l)
        except ValueError: continue
        if isinstance(j, dict) and j.get('entry_id'): sites[j['entry_id']] = j
    out, kept, seen = [], 0, set()
    for l in box_raw.decode('utf-8').splitlines():
        if not l.strip(): continue
        try: j = json.loads(l)
        except ValueError: out.append(l); continue
        eid = j.get('entry_id') if isinstance(j, dict) else None
        s = sites.get(eid) if eid else None
        if eid: seen.add(eid)
        if s and locked(s) and not locked(j) and s.get('crop_path') == j.get('crop_path') and s.get('bbox') == j.get('bbox'):
            for k in LOCK_FIELDS:
                if k in s: j[k] = s[k]
            l = json.dumps(j, ensure_ascii=False); kept += 1
        out.append(l)
    dropped = sorted(set(sites) - seen)
    new = ('\n'.join(out) + '\n').encode('utf-8') if out else b''
    if new == local_raw: return False
    log(f'manifest.jsonl: {len(out)} lines from box, {kept} sites lock(s) kept, {len(dropped)} sites-only line(s) dropped'
        + (f' (e.g. {dropped[:3]})' if dropped else ''))
    if not A.dry_run:
        backup(lp, 'manifest.jsonl'); atomic_write(lp, new)
    return True

def resolved_ids():
    ids = set()
    for p in glob.glob(os.path.join(ENTRIES, '_corrections', 'archive', '*.json')):
        try: cj = json.load(open(p, encoding='utf-8'))
        except Exception: continue
        for items in (cj.get('pending') or {}).values():
            for it in items or []:
                if isinstance(it, dict) and it.get('id'): ids.add(it['id'])
    return ids

def merge_corrections(box_files):
    """box_files: {name: parsed json} for top-level _corrections/<code>.json on the box."""
    cdir = os.path.join(ENTRIES, '_corrections'); res = resolved_ids(); changed = False
    local = {os.path.basename(p): p for p in glob.glob(os.path.join(cdir, '*.json'))}
    for name in sorted(set(local) | set(box_files)):
        lp = os.path.join(cdir, name)
        try: sj = json.load(open(lp, encoding='utf-8')) if name in local else None
        except Exception: sj = None
        bj = box_files.get(name)
        pend = {}
        for src in (sj, bj):
            for eid, items in ((src or {}).get('pending') or {}).items():
                for it in items or []:
                    if not isinstance(it, dict) or it.get('id') in res: continue
                    lst = pend.setdefault(eid, [])
                    if not any(x.get('id') == it.get('id') for x in lst): lst.append(it)
        for eid in pend: pend[eid].sort(key=lambda x: str(x.get('time', '')))
        if not pend:
            if sj is not None:
                log(f'_corrections/{name}: all items resolved on the box -> removed')
                if not A.dry_run: backup(lp, f'corrections_{name}'); os.remove(lp)
                changed = True
            continue
        base = dict(bj or sj); base['pending'] = pend
        base['updated_at'] = max(str((sj or {}).get('updated_at', '')), str((bj or {}).get('updated_at', '')))
        if sj is not None and sj.get('pending') == pend: continue
        log(f'_corrections/{name}: {sum(len(v) for v in pend.values())} pending item(s) after merge')
        if not A.dry_run:
            backup(lp, f'corrections_{name}')
            atomic_write(lp, json.dumps(base, ensure_ascii=False, indent=1).encode('utf-8'))
        changed = True
    return changed

def _t(s):
    try: return datetime.datetime.fromisoformat(str(s)).timestamp()
    except Exception: return 0.0

def merge_overrides(codes, st):
    op = os.path.join(DASH, 'overrides.json')
    try: ov = json.load(open(op, encoding='utf-8'))
    except FileNotFoundError: log(f'overrides.json not found at {op}; skipping'); return False
    last = st.setdefault('box_seg', {}); changed = []
    for code, f in sorted(codes.items()):
        if last.get(code) == f: continue                         # box value not new since the last pull
        e = ov.get(code) if isinstance(ov.get(code), dict) else {}
        cur = {k: v for k, v in e.items() if k == 'segmentation' or k.startswith('seg_')}
        box_t = _t(f.get('_tomb') or f.get('seg_stage_set'))
        if cur.get('seg_stage_set') and _t(cur['seg_stage_set']) > box_t:
            vlog(f'overrides {code}: sites seg fields newer than box; kept'); last[code] = f; continue
        if '_tomb' in f: new = {k: v for k, v in e.items() if not (k == 'segmentation' or k.startswith('seg_'))}
        else: new = {**{k: v for k, v in e.items() if not (k == 'segmentation' or k.startswith('seg_'))}, **f}
        if new != e:
            changed.append(f'{code}: {cur.get("segmentation")!r} -> {new.get("segmentation")!r}')
            if new: ov[code] = new
            else: ov.pop(code, None)
        last[code] = f
    if not changed: return False
    log('overrides.json seg fields: ' + '; '.join(changed))
    if not A.dry_run:
        backup(op, 'overrides.json')
        fd, tmp = tempfile.mkstemp(dir=DASH, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh: json.dump(ov, fh, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o644); os.replace(tmp, op)
    return True

def load_state():
    try: return json.load(open(STATE))
    except Exception: return {'files': {}, 'box_seg': {}}

def save_state(st):
    if A.dry_run: return
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'; json.dump(st, open(tmp, 'w')); os.replace(tmp, STATE)

def sync_once():
    idx = json.loads(get('/index.json'))
    st = load_state(); files = st.setdefault('files', {})
    listed = {f['p']: f for f in idx['files']}
    n_dl = n_del = 0; box_corr = {}; box_manifest = None
    for p, f in listed.items():
        if '..' in p.split('/') or p.startswith('/'): log(f'refusing path {p!r}'); continue
        lp = os.path.join(ENTRIES, p)
        if is_special(p):
            data = get('/f/' + urllib.parse.quote(p))
            if sha(data) != f['sha256']: raise RuntimeError(f'sha mismatch on {p}')
            if p == 'manifest.jsonl': box_manifest = data
            else: box_corr[os.path.basename(p)] = json.loads(data)
            continue
        if files.get(p) == f['sha256'] and os.path.isfile(lp) and os.path.getsize(lp) == f['size']: continue
        if os.path.isfile(lp) and os.path.getsize(lp) == f['size'] and sha_file(lp) == f['sha256']:
            files[p] = f['sha256']; continue
        data = get('/f/' + urllib.parse.quote(p))
        if sha(data) != f['sha256']: raise RuntimeError(f'sha mismatch on {p} (box changed mid-pull?); retry next round')
        vlog(f'download {p} ({len(data)} B)'); n_dl += 1
        if not A.dry_run: atomic_write(lp, data, f.get('mtime')); files[p] = f['sha256']
    for p in [q for q in files if q not in listed]:
        lp = os.path.join(ENTRIES, p)
        if os.path.isfile(lp) and sha_file(lp) == files[p]:
            vlog(f'delete {p} (removed on box)'); n_del += 1
            if not A.dry_run: os.remove(lp)
        if not A.dry_run: files.pop(p)
    with Lock():
        m = merge_manifest(box_manifest) if box_manifest is not None else False
        c = merge_corrections(box_corr)
        o = merge_overrides((idx.get('overrides_seg') or {}).get('codes') or {}, st)
    save_state(st)
    if n_dl or n_del or m or c or o or A.verbose:
        log(f'sync: {len(listed)} listed, {n_dl} downloaded, {n_del} deleted, manifest {"updated" if m else "same"}, '
            f'corrections {"updated" if c else "same"}, overrides {"updated" if o else "same"}' + (' [dry-run]' if A.dry_run else ''))

def main():
    global A
    ap = argparse.ArgumentParser(); ap.add_argument('--once', action='store_true'); ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('-v', '--verbose', action='store_true'); A = ap.parse_args()
    if not TOKEN: sys.exit('OPR_SEGSYNC_TOKEN not set')
    log(f'pulling {URL} (Host {HOSTH}) -> entries {ENTRIES}, dash {DASH}' + (' [dry-run]' if A.dry_run else ''))
    while True:
        try: sync_once()
        except Exception as e:
            log(f'sync failed: {e!r}')
            if A.once: sys.exit(1)
        if A.once: break
        time.sleep(INTERVAL)

if __name__ == '__main__': main()
