"""Chief's post-research update of an added row (the same code path as the dashboard's 'Edit details' / update_row).

Usage:
  updaterow.py CODE [--name N] [--type Birth|Baptism|Marriage|Burial|Confirmation/Communion|Other] [--group G] [--type-other TEXT]
                    [--date D] [--spouse S] [--town T] [--book B] [--image I] [--page P]
                    [--book-url URL] [--page-url URL] [--notes TEXT]
Writes the existing records.json fields (book, image, page, date, spouse, town, notes, collection, pg, url, book_url, image_id).
URLs not given are derived like the table does: diocese + collection from a given Matricula URL (any diocese, e.g.
.../deutschland/aachen/<collection>/<book>/?pg=N) / town Horn (paderborn DE_EBAP_22212) or Warstein (paderborn DE_EBAP_23815) /
another row with the same book when no town is set; any other town without a URL gets NO links (never a guessed collection).
Book link = <base>/<collection>/<book>/?pg=1 (title page);
Image/Page link = <collection>/<book>/?pg=<page digits>  (give --page-url when the Matricula pg differs from the printed page).
When book, image and page are all filled in (first time, or changed): Research -> 'Page found', Segmentation -> 'Queued' and ONE
notify_queue line {kind: segmentation_requested, row, code, book, image, page, time}; repeating the same values never re-sends.
Backs up records.json (next free .bakN) under entries/.manifest.lock, logs to entries/_approvals.log, runs status.py, prints the chips.
Only rows added with '＋ Add row' can be updated. Env (testing): OPR_W, OPR_D.
"""
import argparse, json, os, subprocess, sys
W = os.environ.get('OPR_W', '/workspace/horn-wilmes'); D = os.environ.get('OPR_D', os.path.join(W, 'dashboard'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rowedit as RE

def main(argv):
    ap = argparse.ArgumentParser(prog='updaterow.py', description='Update an added dashboard row (see module doc).')
    ap.add_argument('code')
    for a, k in (('--group', 'group'), ('--name', 'name'), ('--type', 'record_type'), ('--type-other', 'type_other'), ('--date', 'date'), ('--spouse', 'spouse'),
                 ('--town', 'town'), ('--book', 'book'), ('--image', 'image'), ('--page', 'page'), ('--book-url', 'book_url'),
                 ('--page-url', 'url'), ('--notes', 'notes')):
        ap.add_argument(a, dest=k)
    a = vars(ap.parse_args(argv)); code = a.pop('code')
    f = {k: v for k, v in a.items() if v is not None}
    if not f: print('nothing to change; give at least one option'); return 2
    try: r = RE.update_row(RE.Ctx(W, D), code, f, 'updaterow.py', who='Chief (updaterow.py)')
    except RE.RowError as ex: print('ERROR:', ex); return 2
    print(f"{code} (row {r['row']}): changed {', '.join(r['changed']) or 'nothing'}; backup: {r['records_backup'] or '(none, no change)'}")
    for e in r['events']: print('notify:', json.dumps(e, ensure_ascii=False))
    p = subprocess.run([sys.executable, 'status.py'], cwd=D, capture_output=True, text=True)
    if p.returncode: print('ERROR: status.py failed:\n' + p.stderr[-800:]); return 1
    x = {q['code']: q for q in json.load(open(os.path.join(D, 'out', 'status.json'), encoding='utf-8'))['rows']}.get(code, {})
    print(f"{code}: research = {(x.get('research') or {}).get('status') or '(none)'} | segmentation = {x.get('segmentation', {}).get('status')} | "
          f"book {x.get('book')!r} image {x.get('image')!r} page {x.get('page')!r} | page link {x.get('url')}")
    return 0

if __name__ == '__main__': sys.exit(main(sys.argv[1:]))
