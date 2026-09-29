"""Apply an Entry Expander stage report to a row's Expansion chip (overrides.json key 'expansion'), publish immediately.

Usage:
  setexp.py CODE STAGE [CODE STAGE ...]
STAGE: queued | inprogress[:D/N] | clear          e.g.  setexp.py H0167 inprogress:3/7
  queued      -> 'Queued'                 (grey, processing)
  inprogress  -> 'In progress' or 'In progress (D/N entries)'
  clear       -> remove the override (chip derived from stageA_expanded/<folder>/ files again)
Rules (status.py expan()): the override is ignored while the row's transcription is not Approved (chip stays Not started),
and once any <entry_id>.expanded.json exists the files decide (In progress d/N, Draft, Approved).
Backs up overrides.json (next free .bakN) under entries/.manifest.lock, then runs status.py and prints the resulting chip.
Env (testing): OPR_W (default /workspace/horn-wilmes), OPR_D (default $OPR_W/dashboard).
"""
import fcntl, glob, json, os, re, shutil, subprocess, sys, tempfile, datetime

W = os.environ.get('OPR_W', '/workspace/horn-wilmes'); D = os.environ.get('OPR_D', os.path.join(W, 'dashboard'))

def die(msg): print('ERROR:', msg); sys.exit(2)

def next_bak(p):
    n = 1
    for q in glob.glob(p + '.bak*'):
        m = re.fullmatch(re.escape(p) + r'\.bak(\d+)', q)
        if m: n = max(n, int(m.group(1)) + 1)
    return f'{p}.bak{n}'

def parse(st):
    k = st.strip().lower().replace(' ', '').replace('-', '').replace('_', '')
    if k == 'clear': return None
    if k == 'queued': return 'Queued'
    m = re.fullmatch(r'inprogress(?::?(\d+)/(\d+))?', k)
    if m: return 'In progress' + (f' ({int(m.group(1))}/{int(m.group(2))} entries)' if m.group(1) else '')
    die(f'unknown stage {st!r}; use queued | inprogress[:D/N] | clear')

def main(argv):
    if not argv or argv[0] in ('-h', '--help') or len(argv) % 2: print(__doc__); return 0 if argv[:1] in (['-h'], ['--help']) else 2
    recs = {r['code']: r for r in json.load(open(os.path.join(D, 'records.json'), encoding='utf-8'))['records']}
    pairs = []
    for c, st in zip(argv[::2], argv[1::2]):
        if c not in recs: die(f'unknown code {c!r} (not in records.json)')
        pairs.append((c, parse(st)))
    op = os.path.join(D, 'overrides.json')
    lf = open(os.path.join(W, 'entries', '.manifest.lock'), 'a+'); fcntl.flock(lf, fcntl.LOCK_EX)   # same lock as approve_server.py
    try:
        ov = json.load(open(op, encoding='utf-8')); bak = next_bak(op); shutil.copy2(op, bak)
        for c, v in pairs:
            e = ov.get(c) if isinstance(ov.get(c), dict) else {}
            if v is None: e.pop('expansion', None); e.pop('expansion_set', None)
            else: e['expansion'] = v; e['expansion_set'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
            if e: ov[c] = e
            else: ov.pop(c, None)
            print(f'{c}: expansion override -> {v or "(cleared: file-derived)"}')
        fd, tmp = tempfile.mkstemp(dir=D, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(ov, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o644); os.replace(tmp, op); print(f'backup: {os.path.basename(bak)}')
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN); lf.close()
    p = subprocess.run([sys.executable, 'status.py'], cwd=D, capture_output=True, text=True)
    if p.returncode: die('status.py failed:\n' + p.stderr[-800:])
    rows = {r['code']: r for r in json.load(open(os.path.join(D, 'out', 'status.json'), encoding='utf-8'))['rows']}
    for c, v in pairs:
        x = rows[c].get('expansion', {})
        note = '' if (v is None or x.get('source') == 'override') else '  (override not shown: ' + str(x.get('detail', '')) + ')'
        print(f'{c} (row {rows[c]["id"]}): dashboard expansion = {x.get("status")} [{x.get("source")}]{note}')
    return 0

if __name__ == '__main__': sys.exit(main(sys.argv[1:]))
