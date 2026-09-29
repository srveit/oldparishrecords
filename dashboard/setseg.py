#!/usr/bin/env python3
"""Set / clear a row's segmentation re-cut stage, publish immediately, verify crops.

Usage:
  setseg.py CODE STAGE [CODE STAGE ...] [--wait-mac [SECONDS]]
  setseg.py --audit                      # check every published segmentation page against the manifest
STAGE: queued (= 'Queued for redo') | redoing | recut | clear
  recut archives the row's pending corrections (entries/_corrections/archive/, reason recut);
  clear removes the stage (and legacy 'seg_redo_note') and archives pending corrections (reason cancelled); a recut hold ('On hold until crops approved') is undone
  (previous transcription override restored, or file-derived); the entry is dropped if nothing else is left.
Backs up overrides.json (next free .bakN), runs status.py at once (pages + crops regenerated before the 30 s updater),
then verifies every crop on the row's segmentation page: ?v= must equal the mtime of the file the manifest points to.
--wait-mac polls the dashboard server log (http.log) for Greyhawk's refresh.sh pull of the new list.txt, page and changed crops.
Env (testing): OPR_W (default /workspace/horn-wilmes), OPR_D (default $OPR_W/dashboard).
"""
import fcntl, glob, json, os, re, shutil, subprocess, sys, tempfile, time, datetime

W = os.environ.get('OPR_W', '/workspace/horn-wilmes'); D = os.environ.get('OPR_D', os.path.join(W, 'dashboard'))
OUT = os.path.join(D, 'out'); SD = os.path.join(OUT, 'segmentation')
STAGES = {'queued': 'Queued for redo', 'queued for redo': 'Queued for redo', 'queued-for-redo': 'Queued for redo',
          'redoing': 'Redoing', 'recut': 'Recut', 'clear': None}

def archive_corrections(code, reason, stamp):
    """Move entries/_corrections/<code>.json pending items to entries/_corrections/archive/<code>_<ts>_<reason>.json
    (reason 'recut' = the Segmenter re-cut the row; 'cancelled' = setseg clear). Never deletes the record."""
    cp = os.path.join(W, 'entries', '_corrections', f'{code}.json')
    try: cj = json.load(open(cp, encoding='utf-8'))
    except Exception: return 0
    pend = cj.get('pending') if isinstance(cj.get('pending'), dict) else {}
    n = sum(len(v) for v in pend.values() if isinstance(v, list))
    ad = os.path.join(W, 'entries', '_corrections', 'archive'); os.makedirs(ad, exist_ok=True)
    ap = os.path.join(ad, f'{code}_{stamp[:19].replace(":", "").replace("-", "")}_{reason}.json')
    rec = dict(cj, archived_at=stamp, archive_reason=reason)
    fd, tmp = tempfile.mkstemp(dir=ad, suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(rec, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o644); os.replace(tmp, ap); os.remove(cp)
    print(f'{code}: {n} pending correction(s) archived ({reason}) -> {os.path.relpath(ap, W)}')
    return n

def die(msg): print('ERROR:', msg); sys.exit(2)

def next_bak(p):
    n = 1
    for q in glob.glob(p + '.bak*'):
        m = re.fullmatch(re.escape(p) + r'\.bak(\d+)', q)
        if m: n = max(n, int(m.group(1)) + 1)
    return f'{p}.bak{n}'

def manifest():
    by = {}
    for l in open(os.path.join(W, 'entries', 'manifest.jsonl'), encoding='utf-8'):
        if not l.strip(): continue
        try: j = json.loads(l)
        except ValueError: continue
        by.setdefault(j.get('image_id') or j.get('scan'), []).append(j)
    return by

def verify(code, img, man):
    """Return (ok, lines). Compares page <img ?v=> and published jpg to manifest crop_path."""
    page = os.path.join(SD, f'{code}.html'); ents = man.get(img, []); out = []
    if not os.path.isfile(page): return (not ents, [f'  no segmentation page (manifest crops: {len(ents)})'])
    h = open(page, encoding='utf-8').read()
    srcs = dict(re.findall(r'<img src="' + re.escape(code) + r'/([^"?]+)\?v=(\d+)"', h))
    try: smap = json.load(open(os.path.join(SD, '.srcmap.json')))
    except Exception: smap = {}
    ok = True
    for e in ents:
        eid = str(e.get('entry_id', '')); lab = eid[len(img):].lstrip('_') if eid.startswith(img) else eid; fn = lab + '.jpg'
        cp = e.get('crop_path') or ''
        if not os.path.isfile(cp): ok = False; out.append(f'  FAIL {fn}: manifest file missing: {cp}'); continue
        want = int(os.path.getmtime(cp)); got = srcs.get(fn)
        ident = smap.get(f'{code}/{fn}'); same_src = bool(ident) and ident[0] == os.path.abspath(cp) and ident[1] == os.stat(cp).st_mtime_ns
        pub = os.path.isfile(os.path.join(SD, code, fn))
        if got is None or int(got) != want or not pub or not same_src:
            ok = False; out.append(f'  FAIL {fn}: page v={got} manifest mtime={want} published={pub} source-match={same_src} ({os.path.basename(cp)})')
    extra = set(srcs) - {(str(e.get("entry_id", ""))[len(img):].lstrip("_") + ".jpg") for e in ents}
    if extra: ok = False; out.append(f'  FAIL page shows crops not in manifest: {sorted(extra)}')
    out.insert(0, f'  {"PASS" if ok else "FAIL"}: {len(ents)} manifest crops, {len(srcs)} on page, v= matches manifest file mtime: {ok}')
    return ok, out

def newer_siblings(cp):
    """Files next to the manifest's crop that look like newer versions (e.g. _fix copies) - informational."""
    d, b = os.path.split(cp); stem = os.path.splitext(b)[0]
    m = re.match(r'(.*_e\d+)', stem); base = m.group(1) if m else stem
    t = os.path.getmtime(cp)
    return [os.path.basename(q) for q in glob.glob(os.path.join(d, base + '*'))
            if q != cp and os.path.getmtime(q) > t and re.fullmatch(re.escape(base) + r'_fix\w*\.(png|jpg|jpeg|tif)', os.path.basename(q))]

def wait_mac(codes, t0, secs):
    """Poll http.log for Greyhawk's pull (refresh.sh) of list.txt, pages and crops after t0."""
    log = os.path.join(D, 'http.log'); need_list = True
    want = {f'/segmentation/{c}.html' for c in codes if os.path.isfile(os.path.join(SD, f'{c}.html'))}
    deadline = time.time() + secs; seen = set(); crops = {}
    while time.time() < deadline:
        for line in open(log, errors='replace'):
            m = re.search(r'\[(\d+/\w+/\d+ \d+:\d+:\d+)\] "GET (\S+) HTTP/[\d.]+" (\d+)', line)
            if not m: continue
            t = datetime.datetime.strptime(m.group(1), '%d/%b/%Y %H:%M:%S').timestamp()
            if t < t0: continue
            path = m.group(2).split('?')[0]
            if path == '/segmentation/list.txt' and m.group(3) == '200': need_list = False
            if path in want and m.group(3) == '200': seen.add(path)
            for c in codes:
                if path.startswith(f'/segmentation/{c}/'): crops[path] = m.group(3)
        if not need_list and seen == want:
            print(f'MAC PULL: PASS - Greyhawk fetched segmentation/list.txt and {len(seen)} page(s) after the change; '
                  f'crop requests: {sum(v == "200" for v in crops.values())} downloaded, {sum(v == "304" for v in crops.values())} unchanged (304)')
            return True
        time.sleep(5)
    print(f'MAC PULL: FAIL/TIMEOUT after {secs}s - list.txt fetched={not need_list}, pages fetched={sorted(seen)} of {sorted(want)}')
    return False

def main(argv):
    wait = None; audit = False; args = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--wait-mac':
            wait = 120
            if i + 1 < len(argv) and argv[i + 1].isdigit(): wait = int(argv[i + 1]); i += 1
        elif a == '--audit': audit = True
        elif a in ('-h', '--help'): print(__doc__); return 0
        else: args.append(a)
        i += 1
    recs = {r['code']: r for r in json.load(open(os.path.join(D, 'records.json'), encoding='utf-8'))['records']}
    if audit:
        man = manifest(); bad = 0
        for p in sorted(glob.glob(os.path.join(SD, '*.html'))):
            c = os.path.basename(p)[:-5]; img = recs.get(c, {}).get('image_id')
            ok, lines = verify(c, img, man); bad += not ok
            sib = [f'{e.get("entry_id")}: {newer_siblings(e["crop_path"])}' for e in man.get(img, []) if e.get('crop_path') and os.path.isfile(e['crop_path']) and newer_siblings(e['crop_path'])]
            print(f'{c}:'); print('\n'.join(lines))
            for s_ in sib: print(f'  NOTE newer file next to manifest crop (manifest not updated?): {s_}')
        print(f'AUDIT: {"PASS" if not bad else "FAIL"} ({bad} page(s) with mismatches)'); return 1 if bad else 0
    if not args or len(args) % 2: print(__doc__); return 2
    pairs = []
    for c, st in zip(args[::2], args[1::2]):
        if c not in recs: die(f'unknown code {c!r} (not in records.json)')
        k = st.strip().lower()
        if k not in STAGES: die(f'unknown stage {st!r}; use queued | redoing | recut | clear')
        pairs.append((c, STAGES[k]))
    op = os.path.join(D, 'overrides.json')
    lf = open(os.path.join(W, 'entries', '.manifest.lock'), 'a+'); fcntl.flock(lf, fcntl.LOCK_EX)   # same lock as approve_server.py
    try:
        ov = json.load(open(op, encoding='utf-8')); bak = next_bak(op); shutil.copy2(op, bak)
        for c, stage in pairs:
            e = ov.get(c) if isinstance(ov.get(c), dict) else {}
            if stage is None:
                for k in ('segmentation', 'seg_redo_note', 'seg_stage'): e.pop(k, None)
                if e.get('transcription') == 'On hold until crops approved':      # cancel a recut request: restore the hold's previous state
                    prev = e.get('prev_transcription_override')
                    if prev is None: e.pop('transcription', None)
                    else: e['transcription'] = prev
                    for k in ('prev_transcription', 'prev_transcription_override', 'hold_set'): e.pop(k, None)
                    if str(e.get('note', '')).startswith('Recut requested'): e.pop('note', None)
                    print(f'{c}: transcription hold removed -> ' + (repr(prev) if prev is not None else 'file-derived'))
            else:
                e['segmentation'] = stage; e.pop('seg_redo_note', None)
                e['seg_stage_set'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
            if stage is None: e.pop('seg_stage_set', None)
            if stage in (None, 'Recut'):                                            # recut done / request cancelled: archive pending corrections
                archive_corrections(c, 'recut' if stage else 'cancelled', datetime.datetime.now().astimezone().isoformat(timespec='seconds'))
            if e: ov[c] = e
            else: ov.pop(c, None)
            print(f'{c}: segmentation stage -> {stage or "(cleared: file-derived)"}')
        fd, tmp = tempfile.mkstemp(dir=D, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(ov, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o644); os.replace(tmp, op); print(f'backup: {os.path.basename(bak)}')
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN); lf.close()
    t0 = time.time() - 1
    p = subprocess.run([sys.executable, 'status.py'], cwd=D, capture_output=True, text=True)
    if p.returncode: die('status.py failed:\n' + p.stderr[-800:])
    rows = {r['code']: r for r in json.load(open(os.path.join(OUT, 'status.json'), encoding='utf-8'))['rows']}
    man = manifest(); allok = True
    for c, _ in pairs:
        r = rows[c]; s = r['segmentation']
        print(f'{c} (row {r["id"]}): dashboard segmentation = {s["status"]} ({s.get("detail", "")}); page link: {s.get("link") or "none"}')
        ok, lines = verify(c, recs[c]['image_id'], man); allok &= ok; print('\n'.join(lines))
    print('VERIFY:', 'PASS' if allok else 'FAIL')
    if wait: wait_mac([c for c, _ in pairs], t0, wait)
    return 0 if allok else 1

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
