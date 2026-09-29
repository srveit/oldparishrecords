-- =============================================================================
-- 06_stage_b_citation_columns.sql — OPTIONAL. DRAFT 2026-09-29 (Schema Steward).
-- *** UNTESTED against the live DB. Only smoke-tested on a throwaway PG 17 scratch cluster
--     (00→06 fresh, and 06 applied twice: idempotent; CHECK rejects non-Matricula URLs).
--     Site Host: dry-run in a transaction and ROLLBACK first. Do not apply until Stephen
--     approves the v1.1 shared fields. ***
-- Idempotent (IF NOT EXISTS + guarded constraint).
--
-- Purpose: give staging somewhere to put the Stage B shared fields that the locked
-- CSV headers do not have. The CSV headers stay UNCHANGED; loaders fill these from
-- the Stage B JSON (NULL when absent).
--   matricula_url    ← source_citation.matricula_url   (canonical ?pg= image-page permalink)
--   source_citation  ← source_citation.citation        (human-readable)
--   stage_b_shared   ← jsonb of the structured shared objects, verbatim from JSON:
--                      source_citation, *_identified, period_jurisdiction, person_aliases,
--                      *_vital_status, *_previous_spouses, witnesses_other_details,
--                      child_surname / child_surname_inferred
-- Marriage: stg_marriages already exists (01_staging.sql) and has expanded_latin (04).
-- It has no pipeline link, so it also gets entry_id / entry_kind / crop_image_path,
-- following the stg_baptisms pattern in book-meta/postgres_images_v1.sql.
-- =============================================================================

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['stg_baptisms', 'stg_marriages', 'stg_deaths', 'stg_communion'] LOOP
    EXECUTE format('ALTER TABLE lank.%I ADD COLUMN IF NOT EXISTS matricula_url text', t);
    EXECUTE format('ALTER TABLE lank.%I ADD COLUMN IF NOT EXISTS source_citation text', t);
    EXECUTE format('ALTER TABLE lank.%I ADD COLUMN IF NOT EXISTS stage_b_shared jsonb', t);
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = t || '_matricula_url_chk'
                      AND conrelid = format('lank.%I', t)::regclass) THEN
      EXECUTE format(
        'ALTER TABLE lank.%I ADD CONSTRAINT %I CHECK (matricula_url IS NULL OR matricula_url LIKE %L)',
        t, t || '_matricula_url_chk', 'https://data.matricula-online.eu/%');
    END IF;
    EXECUTE format($c$COMMENT ON COLUMN lank.%I.matricula_url IS
      'Stage B source_citation.matricula_url: canonical Matricula viewer permalink to the image page (?pg=N). NULL until recorded.'$c$, t);
    EXECUTE format($c$COMMENT ON COLUMN lank.%I.stage_b_shared IS
      'Stage B shared fields (opr-shared-defs v1.0.0) as jsonb: *_identified places, period_jurisdiction, person_aliases, vital status, previous spouses, witness details. Not part of the CSV.'$c$, t);
  END LOOP;
END
$$;

-- Marriage pipeline link (same pattern as stg_baptisms in postgres_images_v1.sql).
ALTER TABLE lank.stg_marriages
    ADD COLUMN IF NOT EXISTS entry_id        text,
    ADD COLUMN IF NOT EXISTS entry_kind      text DEFAULT 'marriage',
    ADD COLUMN IF NOT EXISTS crop_image_path text;

CREATE UNIQUE INDEX IF NOT EXISTS stg_marriages_entry_id_uidx
    ON lank.stg_marriages (entry_id) WHERE entry_id IS NOT NULL AND deleted_at IS NULL;

-- Optional lookups on the jsonb (uncomment when the site queries them):
-- CREATE INDEX IF NOT EXISTS stg_marriages_shared_gin ON lank.stg_marriages USING gin (stage_b_shared jsonb_path_ops);
-- e.g. identified groom place:  stage_b_shared #>> '{groom_residence_identified,place_id}'

COMMENT ON TABLE lank.stg_marriages IS
  'Staging 1:1 with the marriage CSV (lank-st-stephanus-marriage-csv v1.1.0, incl. expanded_latin). book_id → KB 999_3 (other parishes'' marriage books as loaded). Stage B JSON: opr-marriage-record v1.0.0 (entry_id, crop, matricula_url, stage_b_shared).';
