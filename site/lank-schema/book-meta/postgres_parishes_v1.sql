-- NOTE: JSON field parish_slug maps to column parishes.parish_id (same string).
-- =============================================================================
-- Parishes entity + books.parish_id FK (OPR book-meta v1.2)
-- Apply after 00_book_meta.sql (and optionally postgres_deltas_v1_1.sql).
-- =============================================================================

CREATE TABLE IF NOT EXISTS lank.parishes (
    id                      bigserial PRIMARY KEY,
    parish_id               text NOT NULL,           -- = parish_slug natural key (JSON parish_slug)
    display_name            text NOT NULL,           -- Matricula landing title
    name                    text NOT NULL,           -- dedication / short name
    place                   text NOT NULL,
    diocese_archive         text NOT NULL,
    country                 text NOT NULL,
    history                 text,                    -- landing blurb
    matricula_platform      text NOT NULL DEFAULT 'Matricula Online',
    matricula_parish_url    text NOT NULL,
    matricula_parish_slug   text,                    -- usually equals parish_id
    links                   jsonb,                   -- [{rel, label, url}, ...]
    notes                   text,
    schema_version          text NOT NULL DEFAULT '1.0.0',
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT parishes_parish_id_unique UNIQUE (parish_id)
);

COMMENT ON TABLE lank.parishes IS
  'Parish-level metadata (opr-matricula-parish-meta). Books FK here — do not duplicate on books.';
COMMENT ON COLUMN lank.parishes.parish_id IS
  'Stable public id; prefer Matricula parish URL slug.';

CREATE INDEX IF NOT EXISTS parishes_country_idx ON lank.parishes (country);
CREATE INDEX IF NOT EXISTS parishes_diocese_idx ON lank.parishes (diocese_archive);

-- Seed Lank St. Stephanus
INSERT INTO lank.parishes (
    parish_id, display_name, name, place, diocese_archive, country,
    history, matricula_parish_url, matricula_parish_slug, links, notes
) VALUES (
    'lank-st-stephanus',
    'Lank St. Stephanus',
    'St. Stephanus',
    'Lank (Lank-Latum)',
    'Aachen, rk. Bistum',
    'Deutschland',
    NULL,
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/',
    'lank-st-stephanus',
    '[]'::jsonb,
    'OPR pilot parish'
)
ON CONFLICT (parish_id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    name = EXCLUDED.name,
    place = EXCLUDED.place,
    diocese_archive = EXCLUDED.diocese_archive,
    country = EXCLUDED.country,
    matricula_parish_url = EXCLUDED.matricula_parish_url,
    matricula_parish_slug = EXCLUDED.matricula_parish_slug,
    updated_at = now();

-- Link books → parishes
ALTER TABLE lank.books
    ADD COLUMN IF NOT EXISTS parish_ref_id bigint REFERENCES lank.parishes (id);

-- Backfill Lank books
UPDATE lank.books b
SET parish_ref_id = p.id
FROM lank.parishes p
WHERE p.parish_id = 'lank-st-stephanus'
  AND b.parish_ref_id IS NULL
  AND (
    b.matricula_parish_slug = 'lank-st-stephanus'
    OR b.parish_place ILIKE '%Lank%'
    OR b.source_url ILIKE '%lank-st-stephanus%'
  );

CREATE INDEX IF NOT EXISTS books_parish_ref_id_idx ON lank.books (parish_ref_id);

-- Prefer unique archival_id per parish (multi-parish safe)
CREATE UNIQUE INDEX IF NOT EXISTS books_parish_archival_uidx
  ON lank.books (parish_ref_id, archival_id)
  WHERE deleted_at IS NULL AND parish_ref_id IS NOT NULL;

-- NOTE: legacy parish_* columns on books may remain during transition for views;
-- new code should JOIN lank.parishes. Soft-deprecate copying diocese/country onto books.
