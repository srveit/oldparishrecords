-- =============================================================================
-- Book meta v1.1 deltas for lank.books (non-breaking)
-- Source: /workspace/lank-schema/book-meta/matricula_book_meta.schema.json
-- Apply after 00_book_meta.sql. Safe to re-run (IF NOT EXISTS / ADD COLUMN guards).
-- =============================================================================

ALTER TABLE lank.books
    ADD COLUMN IF NOT EXISTS schema_version text DEFAULT '1.1.0',
    ADD COLUMN IF NOT EXISTS parish_display_name text,
    ADD COLUMN IF NOT EXISTS parish_history text,
    ADD COLUMN IF NOT EXISTS matricula_parish_url text,
    ADD COLUMN IF NOT EXISTS matricula_parish_slug text,
    ADD COLUMN IF NOT EXISTS description text,
    ADD COLUMN IF NOT EXISTS gesperrt_until_raw text,
    ADD COLUMN IF NOT EXISTS date_from_raw text,
    ADD COLUMN IF NOT EXISTS date_to_raw text,
    ADD COLUMN IF NOT EXISTS list_types text[],
    ADD COLUMN IF NOT EXISTS image_url_patterns jsonb;

COMMENT ON COLUMN lank.books.parish_display_name IS 'Matricula parish landing title';
COMMENT ON COLUMN lank.books.description IS 'Matricula Description/Inhalt raw text';
COMMENT ON COLUMN lank.books.gesperrt_until_raw IS 'Raw gesperrt phrase from Matricula';
COMMENT ON COLUMN lank.books.list_types IS 'Optional multi list_type ids (historische Notizen)';
COMMENT ON COLUMN lank.books.image_url_patterns IS 'Optional alt image patterns JSON array';

-- Backfill Lank parish display from existing rows (best-effort)
UPDATE lank.books
SET parish_display_name = COALESCE(parish_display_name, 'Lank St. Stephanus'),
    matricula_parish_slug = COALESCE(matricula_parish_slug, 'lank-st-stephanus'),
    matricula_parish_url = COALESCE(
        matricula_parish_url,
        'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/'
    ),
    schema_version = COALESCE(schema_version, '1.1.0')
WHERE parish_place ILIKE '%Lank%';

-- Optional multi-parish uniqueness (commented until Site Host confirms)
-- CREATE UNIQUE INDEX IF NOT EXISTS books_parish_archival_uidx
--   ON lank.books (matricula_parish_slug, archival_id)
--   WHERE deleted_at IS NULL;
