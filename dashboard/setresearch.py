"""Apply Chief's research report to an added row's Research chip (records.json 'research'), publish immediately.

Usage:
  setresearch.py CODE STATE [CODE STATE ...]
STATE: researching (grey 🔍 Researching) | found (blue ✓ Page found) | clear (no Research chip)
Backs up records.json (next free .bakN) under entries/.manifest.lock, logs to entries/_approvals.log, runs status.py, prints the chip.
To record the book/image/page found, use updaterow.py (it also flips Research to Page found and requests segmentation).
Env (testing): OPR_W (default /workspace/horn-wilmes), OPR_D (default $OPR_W/dashboard).
"""
import json, os, subprocess, sys
W = os.environ.get('OPR_W', '/workspace/horn-wilmes'); D = os.environ.get('OPR_D', os.path.join(W, 'dashboard'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rowedit as RE

def main(argv):
    if not argv or argv[0] in ('-h', '--help') or len(argv) % 2: print(__doc__); return 0 if argv[:1] in (['-h'], ['--help']) else 2
    ctx = RE.Ctx(W, D)
    for c, st in zip(argv[::2], argv[1::2]):
        try: r = RE.set_research(ctx, c, st, 'setresearch.py')
        except RE.RowError as ex: print('ERROR:', ex); return 2
        print(f"{c} (row {r['row']}): research -> {r['research'] or '(cleared)'}; backup: {r['records_backup']}")
    p = subprocess.run([sys.executable, 'status.py'], cwd=D, capture_output=True, text=True)
    if p.returncode: print('ERROR: status.py failed:\n' + p.stderr[-800:]); return 1
    rows = {r['code']: r for r in json.load(open(os.path.join(D, 'out', 'status.json'), encoding='utf-8'))['rows']}
    for c in argv[::2]:
        x = rows.get(c, {}).get('research') or {}
        print(f"{c}: dashboard research = {x.get('status') or '(none)'} | segmentation = {rows.get(c, {}).get('segmentation', {}).get('status')}")
    return 0

if __name__ == '__main__': sys.exit(main(sys.argv[1:]))
