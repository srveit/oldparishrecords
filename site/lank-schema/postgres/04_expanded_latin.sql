-- =============================================================================
-- 04_expanded_latin.sql — nullable expanded_latin + folded full-text search
-- 2026-09-25 (Schema Steward). Idempotent; safe to run on a live DB.
-- Rules: /workspace/lank-schema/book-meta/entry/EXPANDED_LATIN_RULES.md
-- Stage B schemas: baptism v1.0.3, death v1.0.1 (draft), communion v1.0.2.
-- =============================================================================

-- 1) Column on every staging table (null until the register owner backfills).
ALTER TABLE lank.stg_baptisms                 ADD COLUMN IF NOT EXISTS expanded_latin text;
ALTER TABLE lank.stg_marriages                ADD COLUMN IF NOT EXISTS expanded_latin text;
ALTER TABLE lank.stg_deaths                   ADD COLUMN IF NOT EXISTS expanded_latin text;
ALTER TABLE lank.stg_communion                ADD COLUMN IF NOT EXISTS expanded_latin text;
ALTER TABLE lank.stg_confraternity_enrollment ADD COLUMN IF NOT EXISTS expanded_latin text;
ALTER TABLE lank.stg_yearly_name_roll         ADD COLUMN IF NOT EXISTS expanded_latin text;
ALTER TABLE lank.stg_ledger_admin             ADD COLUMN IF NOT EXISTS expanded_latin text;

COMMENT ON COLUMN lank.stg_baptisms.expanded_latin IS
  'Reading/search form: abbreviations expanded ([supplied], [?] uncertain), wraps joined, / removed, margin | prefix. See EXPANDED_LATIN_RULES.md.';

-- 2) Immutable fold for search: lowercase, æ/Æ→ae, œ/Œ→oe, ſ→s, strip [?] and
--    brackets so "Prænob[ilis]" matches "praenobilis". Umlauts are kept
--    (unaccent() is not IMMUTABLE; add an unaccent-based fold later if wanted).
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

--    2026-09-29: capital Œ added here for fresh installs; a live DB gets it from
--    05_expanded_latin_fixes.sql (which also REINDEXes the FTS indexes below).

-- 3) GIN full-text index per register ('simple' config: no Latin stemming).
--    Falls back to transcription_latin / transcription while expanded_latin is null.
CREATE INDEX IF NOT EXISTS stg_baptisms_fts_idx ON lank.stg_baptisms
  USING gin (to_tsvector('simple', lank.fold_search_text(coalesce(expanded_latin, transcription_latin, ''))));
CREATE INDEX IF NOT EXISTS stg_marriages_fts_idx ON lank.stg_marriages
  USING gin (to_tsvector('simple', lank.fold_search_text(coalesce(expanded_latin, transcription_latin, ''))));
CREATE INDEX IF NOT EXISTS stg_deaths_fts_idx ON lank.stg_deaths
  USING gin (to_tsvector('simple', lank.fold_search_text(coalesce(expanded_latin, transcription_latin, ''))));
CREATE INDEX IF NOT EXISTS stg_communion_fts_idx ON lank.stg_communion
  USING gin (to_tsvector('simple', lank.fold_search_text(coalesce(expanded_latin, transcription_latin, ''))));
CREATE INDEX IF NOT EXISTS stg_confraternity_fts_idx ON lank.stg_confraternity_enrollment
  USING gin (to_tsvector('simple', lank.fold_search_text(coalesce(expanded_latin, transcription, ''))));
CREATE INDEX IF NOT EXISTS stg_yearly_roll_fts_idx ON lank.stg_yearly_name_roll
  USING gin (to_tsvector('simple', lank.fold_search_text(coalesce(expanded_latin, transcription, ''))));
CREATE INDEX IF NOT EXISTS stg_ledger_admin_fts_idx ON lank.stg_ledger_admin
  USING gin (to_tsvector('simple', lank.fold_search_text(coalesce(expanded_latin, transcription, ''))));

-- 4) One union view for site full-text search. Queries must use the same
--    expression so the indexes are hit, e.g.
--    WHERE to_tsvector('simple', lank.fold_search_text(coalesce(expanded_latin, transcription_latin, '')))
--          @@ plainto_tsquery('simple', lank.fold_search_text('Prænobilis Baukum'))
CREATE OR REPLACE VIEW lank.record_text_search AS
  SELECT 'baptism'::text AS record_type, id AS staging_id, book_id, scan, page, entry,
         transcription_latin AS source_text, expanded_latin,
         lank.fold_search_text(coalesce(expanded_latin, transcription_latin, '')) AS search_text
    FROM lank.stg_baptisms WHERE deleted_at IS NULL
  UNION ALL
  SELECT 'marriage', id, book_id, scan, page, entry, transcription_latin, expanded_latin,
         lank.fold_search_text(coalesce(expanded_latin, transcription_latin, ''))
    FROM lank.stg_marriages WHERE deleted_at IS NULL
  UNION ALL
  SELECT 'death', id, book_id, scan, page, entry, transcription_latin, expanded_latin,
         lank.fold_search_text(coalesce(expanded_latin, transcription_latin, ''))
    FROM lank.stg_deaths WHERE deleted_at IS NULL
  UNION ALL
  SELECT 'communion', id, book_id, scan, page, entry, transcription_latin, expanded_latin,
         lank.fold_search_text(coalesce(expanded_latin, transcription_latin, ''))
    FROM lank.stg_communion WHERE deleted_at IS NULL;

COMMENT ON VIEW lank.record_text_search IS
  'Register text for site search; search_text = folded coalesce(expanded_latin, transcription_latin). Hist-notes use the lank.histnotes_flat view + their own FTS indexes.';
