"""One-off (29 Sep 2026): give every records.json row a person_id (P####), through rowedit's lock + save (backup .bakN).
Same person: rows 1,2,5,21 (Caspar Anton Wilmes, father); rows 7,20 (his son Caspar Anton, b. 1808, bur. 1814);
rows 18,19 (Franz Theodor, son of Maria Christina Wilmes gt. Herweg: baptism 6 Dec 1832 + burial 1833, same name and mother).
Row 22 is a page of several burials -> person_kind 'page'. Everyone else is their own person. Rows that already have a
person_id are left alone (idempotent). records_meta.json gets person_high_water."""
import os, sys
W = os.environ.get('OPR_W', '/workspace/horn-wilmes'); D = os.environ.get('OPR_D', os.path.join(W, 'dashboard'))
sys.path.insert(0, D); import rowedit as RE
SAME = [(1, 2, 5, 21), (7, 20), (18, 19)]; PAGE = {22}
ctx = RE.Ctx(W, D); lf = RE.lock(ctx)
try:
    recs = RE.load(ctx); m = RE.meta_load(ctx); stamp = RE.now_ct(); by_id = {r['id']: r for r in recs['records']}; done = []
    for r in recs['records']:
        if r.get('person_id'): continue
        grp = next((g for g in SAME if r['id'] in g), (r['id'],))
        pid = next((by_id[i]['person_id'] for i in grp if i in by_id and by_id[i].get('person_id')), None) or RE.new_person_id(ctx, recs, m)
        for i in grp:
            if i in by_id and not by_id[i].get('person_id'):
                by_id[i]['person_id'] = pid; done.append((i, pid))
                if i in PAGE: by_id[i]['person_kind'] = 'page'
    if done:
        bak = RE.save(ctx, recs); RE.meta_save(ctx, m, stamp)
        RE.log(ctx, stamp, 'person_ids', 0, '-', 'assigned ' + ', '.join(f'row {i}={p}' for i, p in sorted(done)), 'migrate_person_ids.py')
        print('backup', bak, '| person_high_water', m['person_high_water'])
    for r in recs['records']: print(r['id'], r['code'], r['person_id'], r.get('person_kind', 'person'), r['name'][:50])
finally: RE.unlock(lf)
