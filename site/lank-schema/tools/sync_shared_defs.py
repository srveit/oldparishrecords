#!/usr/bin/env python3
"""Copy $defs from book-meta/entry/opr_shared_defs.schema.json into every Stage B record schema
(identical copies, so each schema validates standalone). --check also verifies the entry/ -> entry/extraction/
mirror (schemas, STAGE_B docs, rulebook, examples); copy files with cp after editing.
Usage: sync_shared_defs.py          write
       sync_shared_defs.py --check  exit 1 if any schema's shared $defs or the mirror has drifted
"""
import json, sys, os, filecmp
ENTRY = '/workspace/lank-schema/book-meta/entry'
SCHEMAS = ['baptism_record.schema.json', 'death_record.schema.json',
           'communion_record.schema.json', 'marriage_record.schema.json']
MIRROR = SCHEMAS + ['opr_shared_defs.schema.json', 'EXPANDED_LATIN_RULES.md', 'STAGE_B_BAPTISM.md',
                    'STAGE_B_DEATH.md', 'STAGE_B_COMMUNION.md', 'STAGE_B_MARRIAGE.md', 'STAGE_B_SHARED_FIELDS.md']
MIRROR += ['examples/' + f for f in sorted(os.listdir(f'{ENTRY}/examples'))]
shared = json.load(open(f'{ENTRY}/opr_shared_defs.schema.json'))['$defs']
check = '--check' in sys.argv
bad = 0
for n in SCHEMAS:
    p = f'{ENTRY}/{n}'
    s = json.load(open(p))
    cur = s.get('$defs', {})
    want = dict(cur); want.update(shared)
    if check:
        drift = [k for k in shared if cur.get(k) != shared[k]]
        if drift: bad += 1; print('DRIFT', n, drift)
        else: print('ok   ', n)
    elif cur != want:
        s['$defs'] = want
        with open(p, 'w') as f: json.dump(s, f, ensure_ascii=False, indent=2); f.write('\n')
        print('synced', n)
for n in MIRROR:
    a, b = f'{ENTRY}/{n}', f'{ENTRY}/extraction/{n}'
    same = os.path.exists(b) and filecmp.cmp(a, b, shallow=False)
    if check and not same: bad += 1; print('MIRROR DRIFT', n)
if check and not bad: print('mirror ok (%d files)' % len(MIRROR))
sys.exit(bad)
