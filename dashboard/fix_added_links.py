"""One-off (29 Sep 2026): clear the guessed DE_EBAP_22212 collection on added rows whose town has no known Matricula home
and no pasted URL (N0023, N0024 - Lank St. Stephanus is in the aachen diocese). Only 'collection' (and a derived pg) change."""
import json, os, sys
W = os.environ.get('OPR_W', '/workspace/horn-wilmes'); D = os.environ.get('OPR_D', os.path.join(W, 'dashboard'))
sys.path.insert(0, D); import rowedit as RE
ctx = RE.Ctx(W, D); codes = sys.argv[1:]
lf = RE.lock(ctx)
try:
    recs = RE.load(ctx); ch = []
    for r in recs['records']:
        if r.get('code') in codes and RE.is_added(r) and not r.get('url') and not r.get('book_url') and r.get('collection') == 'DE_EBAP_22212' \
                and str(r.get('town') or '').strip().lower() not in RE.TOWN_COLL:
            r['collection'] = ''; r['pg'] = None; ch.append(r['code'])
    if ch:
        bak = RE.save(ctx, recs); stamp = RE.now_ct()
        for c in ch: RE.log(ctx, stamp, 'fix_row_links', next(x['id'] for x in recs['records'] if x['code'] == c), c, 'collection DE_EBAP_22212 (guessed) -> "" (no Matricula links until a URL is given)', 'fix_added_links.py')
        print('cleared collection on', ch, 'backup', bak)
    else: print('nothing to change')
finally: RE.unlock(lf)
