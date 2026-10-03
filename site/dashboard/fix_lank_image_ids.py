"""One-off (29 Sep 2026): store the Lank KB 1000 page id as image_id on added Lank rows that have book/image/page but a blank
image_id (rowedit used to blank it for towns other than Horn/Warstein). Uses rowedit's lock + save (backup .bakN) + log."""
import os, sys
W = os.environ.get('OPR_W', '/workspace/horn-wilmes'); D = os.environ.get('OPR_D', os.path.join(W, 'dashboard'))
sys.path.insert(0, D); import rowedit as RE
ctx = RE.Ctx(W, D); lf = RE.lock(ctx)
try:
    recs = RE.load(ctx); ch = []
    for r in recs['records']:
        xp = RE.EXT_PAGE_IDS.get((str(r.get('town') or '').strip().lower(), str(r.get('book') or '').strip()))
        dig, pdig = RE.page_digits(r.get('image')), RE.page_digits(str(r.get('page') or '').split('\u2013')[0])
        if xp and dig and pdig and not r.get('image_id'):
            r['image_id'] = f"{xp}_s{int(dig):03d}_p{int(pdig)}"; ch.append((r['id'], r['code'], r['image_id']))
    if ch:
        bak = RE.save(ctx, recs); st = RE.now_ct()
        for i, c, v in ch: RE.log(ctx, st, 'fix_row_image_id', i, c, f'image_id "" -> {v} (Lank KB 1000 page id)', 'fix_lank_image_ids.py')
        print('set', ch, 'backup', bak)
    else: print('nothing to change')
finally: RE.unlock(lf)
