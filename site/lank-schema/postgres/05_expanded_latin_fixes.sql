-- =============================================================================
-- 05_expanded_latin_fixes.sql — fixes for 04_expanded_latin.sql (Site Host report)
-- 2026-09-29 (Schema Steward). Smoke-tested on a scratch PG 17 cluster (04-as-live + data → 05
-- twice; 'oeconomus' found via the GIN index only after the REINDEX; fresh 00→05 OK).
-- Not yet run on the live DB. Idempotent: safe to run more than once on the live DB
-- where 04 is already applied. 04 has been corrected too, so fresh installs that run
-- 00→05 end up in the same state.
--
--   (a) record_text_search view comment named lank.histnotes; the real view is
--       lank.histnotes_flat (03_views.sql).
--   (b) fold_search_text() did not fold capital Œ (Æ was already folded). With
--       lower() applied last, and in a C / non-ICU collation, 'Œ' stayed 'Œ' and
--       'Œconomus' did not match 'oeconomus'. Adds replace('Œ','Oe'); the function
--       stays IMMUTABLE PARALLEL SAFE with the same signature.
--   (c) The GIN FTS indexes from 04 are expression indexes over fold_search_text().
--       Postgres does NOT rebuild them when the function body changes, so rows
--       that contain Œ keep stale index entries until REINDEX. Step 3 reindexes all
--       seven (only those that exist).
-- =============================================================================

-- 1) Function (same signature; CREATE OR REPLACE keeps dependent indexes attached).
CREATE OR REPLACE FUNCTION lank.fold_search_text(t text)
RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT lower(
           replace(replace(replace(replace(replace(replace(replace(
             replace(t, '[?]', ''),
           '[', ''), ']', ''),
           'æ', 'ae'), 'Æ', 'Ae'),
           'œ', 'oe'), 'Œ', 'Oe'), 'ſ', 's')
         )
$$;

COMMENT ON FUNCTION lank.fold_search_text(text) IS
  'Search fold (IMMUTABLE): [?] and brackets stripped, æ/Æ→ae, œ/Œ→oe, ſ→s, lowercased. Used by the stg_*_fts_idx expression indexes: REINDEX them after any change to this function.';

-- 2) View comment: lank.histnotes → lank.histnotes_flat.
COMMENT ON VIEW lank.record_text_search IS
  'Register text for site search; search_text = folded coalesce(expanded_latin, transcription_latin). Hist-notes use the lank.histnotes_flat view + their own FTS indexes.';

-- 3) Rebuild the expression indexes that depend on fold_search_text().
--    Plain REINDEX takes a lock that blocks writes to the table (reads still work)
--    while it runs. The tables are small. For zero-downtime, run the equivalent
--    statements outside a transaction instead:
--      REINDEX INDEX CONCURRENTLY lank.stg_baptisms_fts_idx;   -- etc.
--    and skip this block.
DO $$
DECLARE
  ix text;
BEGIN
  FOREACH ix IN ARRAY ARRAY[
    'lank.stg_baptisms_fts_idx',
    'lank.stg_marriages_fts_idx',
    'lank.stg_deaths_fts_idx',
    'lank.stg_communion_fts_idx',
    'lank.stg_confraternity_fts_idx',
    'lank.stg_yearly_roll_fts_idx',
    'lank.stg_ledger_admin_fts_idx'
  ] LOOP
    IF to_regclass(ix) IS NOT NULL THEN
      EXECUTE format('REINDEX INDEX %s', ix);
      RAISE NOTICE 'reindexed %', ix;
    ELSE
      RAISE NOTICE 'skipped % (not present)', ix;
    END IF;
  END LOOP;
END
$$;

-- Equivalent explicit statements (for reference / manual runs):
-- REINDEX INDEX lank.stg_baptisms_fts_idx;
-- REINDEX INDEX lank.stg_marriages_fts_idx;
-- REINDEX INDEX lank.stg_deaths_fts_idx;
-- REINDEX INDEX lank.stg_communion_fts_idx;
-- REINDEX INDEX lank.stg_confraternity_fts_idx;
-- REINDEX INDEX lank.stg_yearly_roll_fts_idx;
-- REINDEX INDEX lank.stg_ledger_admin_fts_idx;

-- 4) Smoke checks (expect: oeconomus | praenobilis baro).
-- SELECT lank.fold_search_text('Œconomus'), lank.fold_search_text('Prænob[ilis] B[aro][?]');
