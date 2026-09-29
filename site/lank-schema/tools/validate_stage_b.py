#!/usr/bin/env python3
"""Validate Stage B JSON records against the matching opr-*-record schema (picked by entry_kind).
Run with the venv that has jsonschema:  /workspace/.venv-js/bin/python validate_stage_b.py FILE.json [...]
Also checks every schema against the 2020-12 meta-schema.  --schemas DIR to use another schema dir (e.g. extraction/)."""
import json, sys
from jsonschema import Draft202012Validator
args = sys.argv[1:]
D = '/workspace/lank-schema/book-meta/entry'
if args[:1] == ['--schemas']: D, args = args[1], args[2:]
V = {}
for k in ('baptism', 'death', 'communion', 'marriage'):
    s = json.load(open(f'{D}/{k}_record.schema.json')); Draft202012Validator.check_schema(s)
    V[k] = Draft202012Validator(s)
bad = 0
for f in args:
    d = json.load(open(f)); k = d.get('entry_kind')
    errs = sorted(V[k].iter_errors(d), key=lambda e: list(e.path)) if k in V else ['unknown entry_kind']
    if errs:
        bad += 1; print('FAIL', f)
        for e in errs[:8]: print('    ', getattr(e, 'json_path', ''), getattr(e, 'message', e)[:200])
    else: print('OK  ', f)
print(f'{len(args) - bad}/{len(args)} valid'); sys.exit(bool(bad))
