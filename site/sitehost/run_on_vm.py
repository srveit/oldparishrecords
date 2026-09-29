#!/usr/bin/env python3
"""Steps 1-4 against VM 107 via the qemu guest agent (prepared 2026-09-25, NOT yet run:
pve.veithome.com TLS handshake was failing from the box). Usage: python3 run_on_vm.py [precheck|dryrun|apply|app]"""
import sys, hashlib, pve
SQL_LOCAL = '/workspace/lank-schema/postgres/04_expanded_latin.sql'
PSQL = 'sudo -u postgres psql -d lank -v ON_ERROR_STOP=1'
def sh(cmd):
    c, o, e = pve.run(cmd); print(o, end=''); print(e, end='', file=sys.stderr); print(f'[exit {c}]'); return c, o
PRECHECK = r"""SELECT c.relname, count(a.attname) FILTER (WHERE a.attname IN ('id','deleted_at','book_id','scan','page','entry')) AS core6,
  bool_or(a.attname='transcription_latin') AS has_tl, bool_or(a.attname='transcription') AS has_t, bool_or(a.attname='expanded_latin') AS has_el
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace AND n.nspname='lank'
JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
WHERE c.relname IN ('stg_baptisms','stg_marriages','stg_deaths','stg_communion','stg_confraternity_enrollment','stg_yearly_name_roll','stg_ledger_admin')
GROUP BY 1 ORDER BY 1;"""
COUNTS = " UNION ALL ".join(f"SELECT '{t}', count(*), count(*) FILTER (WHERE deleted_at IS NULL) FROM lank.{t}" for t in
  ['stg_baptisms','stg_marriages','stg_deaths','stg_communion','stg_confraternity_enrollment','stg_yearly_name_roll','stg_ledger_admin']) + ';'
VERIFY = COUNTS + r"""
SELECT lank.fold_search_text('Prænob[ilis] et Gen[?]erosus ſ');
SELECT indexname FROM pg_indexes WHERE schemaname='lank' AND indexname LIKE '%fts_idx' ORDER BY 1;
SELECT table_name FROM information_schema.columns WHERE table_schema='lank' AND column_name='expanded_latin' ORDER BY 1;
SELECT (SELECT count(*) FROM lank.record_text_search) AS view_n,
  (SELECT count(*) FROM lank.stg_baptisms WHERE deleted_at IS NULL)+(SELECT count(*) FROM lank.stg_marriages WHERE deleted_at IS NULL)
  +(SELECT count(*) FROM lank.stg_deaths WHERE deleted_at IS NULL)+(SELECT count(*) FROM lank.stg_communion WHERE deleted_at IS NULL) AS reg_n;
SELECT to_regclass('lank.histnotes') AS histnotes, to_regclass('lank.histnotes_flat') AS histnotes_flat;
SET enable_seqscan=off;
EXPLAIN SELECT id FROM lank.stg_deaths WHERE to_tsvector('simple', lank.fold_search_text(coalesce(expanded_latin, transcription_latin, ''))) @@ plainto_tsquery('simple', lank.fold_search_text('sepultus'));
"""
def q(sql): return sh(f"{PSQL} <<'EOSQL'\n{sql}\nEOSQL")
step = sys.argv[1]
if step == 'precheck':
    q(PRECHECK); q(COUNTS)
elif step == 'dryrun':
    pve.put(SQL_LOCAL, '/tmp/04_expanded_latin.sql')
    sh(f"chmod a+r /tmp/04_expanded_latin.sql; printf 'BEGIN;\\n\\\\i /tmp/04_expanded_latin.sql\\nROLLBACK;\\n' | {PSQL} 2>&1")
elif step == 'apply':
    q(COUNTS)
    sh(f"{PSQL} -f /tmp/04_expanded_latin.sql 2>&1 && {PSQL} -f /tmp/04_expanded_latin.sql 2>&1")
    q(VERIFY)
elif step == 'app':
    D = '/opt/lank-search'
    c, o = sh(f"sha256sum {D}/app.py")
    vm_sha = o.split()[0]
    base = hashlib.sha256(open('/workspace/sitehost/app/app.py.box-orig','rb').read()).hexdigest()
    if vm_sha != base:
        sys.exit(f'VM app.py ({vm_sha}) differs from box copy ({base}); fetch it and re-patch UNION_SQL before deploying.')
    sh(f"cp -p {D}/app.py {D}/app.py.bak-2026-09-25")
    pve.put('/workspace/sitehost/app/app.py', '/tmp/app.py.new')
    sh(f"cat /tmp/app.py.new > {D}/app.py && systemctl restart lank-search && sleep 3 && systemctl is-active lank-search")
    c, o = sh("curl -sf 127.0.0.1:8000/health && for t in sepultus Pr%C3%A6nobilis Jacobs; do echo; curl -sf \"127.0.0.1:8000/search?q=$t&limit=5\" | head -c 600 || exit 7; done")
    if c != 0:
        sh(f"cp -p {D}/app.py.bak-2026-09-25 {D}/app.py && systemctl restart lank-search && sleep 3 && systemctl is-active lank-search && curl -s 127.0.0.1:8000/health")
        sys.exit('smoke test failed; backup restored')
    import shutil; shutil.copy('/workspace/sitehost/app/app.py', '/workspace/pve/search/app.py')
