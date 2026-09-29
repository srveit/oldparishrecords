"""Add a dashboard row from the command line (same code path as the dashboard's '＋ Add row' / add_row).

Usage:
  addrow.py --name NAME --type Birth|Baptism|Marriage|Burial|Confirmation/Communion|Other [--type-other TEXT]
            [--group G] [--town T] [--book B] [--image I] [--page P] [--date D] [--spouse S] [--notes N]
            [--book-url URL] [--page-url URL]
Group defaults to 'Added rows'; a new group name becomes a new table heading. Writes records.json (backup .bakN, shared lock),
records_meta.json (id high-water), _approvals.log and ONE notify_queue line {kind: row_added, ...}; runs status.py and prints the row.
Env (testing): OPR_W, OPR_D.
"""
import argparse, json, os, subprocess, sys
W = os.environ.get('OPR_W', '/workspace/horn-wilmes'); D = os.environ.get('OPR_D', os.path.join(W, 'dashboard'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rowedit as RE

def main(argv):
    ap = argparse.ArgumentParser(prog='addrow.py', description='Add a dashboard row (see module doc).')
    for a, k in (('--name', 'name'), ('--type', 'record_type'), ('--type-other', 'type_other'), ('--group', 'group'), ('--town', 'town'),
                 ('--book', 'book'), ('--image', 'image'), ('--page', 'page'), ('--date', 'date'), ('--spouse', 'spouse'), ('--notes', 'notes'),
                 ('--book-url', 'book_url'), ('--page-url', 'url')):
        ap.add_argument(a, dest=k, required=k in ('name', 'record_type'))
    f = {k: v for k, v in vars(ap.parse_args(argv)).items() if v is not None}
    try: r = RE.add_row(RE.Ctx(W, D), f, 'addrow.py')
    except RE.RowError as ex: print('ERROR:', ex); return 2
    print(f"added row {r['row']} ({r['code']}) in group {r['record']['group']!r}; backup: {r['records_backup']}" + (f"; note: {r['warning']}" if r.get('warning') else ''))
    for e in r['events']: print('notify:', json.dumps(e, ensure_ascii=False))
    p = subprocess.run([sys.executable, 'status.py'], cwd=D, capture_output=True, text=True)
    if p.returncode: print('ERROR: status.py failed:\n' + p.stderr[-800:]); return 1
    x = {q['code']: q for q in json.load(open(os.path.join(D, 'out', 'status.json'), encoding='utf-8'))['rows']}.get(r['code'], {})
    print(f"{r['code']}: research = {(x.get('research') or {}).get('status')} | segmentation = {x.get('segmentation', {}).get('status')} | page link {x.get('url') or '(none)'}")
    return 0

if __name__ == '__main__': sys.exit(main(sys.argv[1:]))
