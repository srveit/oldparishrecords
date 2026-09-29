-- =============================================================================
-- Image fields for full-page scans + entry crops (Stephen 2026-09-13)
-- Binaries may live on VM filesystem or object store later — store path AND/OR URL.
-- Apply after 00_book_meta.sql (+ parishes optional).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- lank.scans — full Matricula page / face images (book-level "view full page")
-- ---------------------------------------------------------------------------
ALTER TABLE lank.scans
    ADD COLUMN IF NOT EXISTS face text
        CHECK (face IS NULL OR face IN ('left', 'right', 'single', 'spread')),
    ADD COLUMN IF NOT EXISTS image_path text,          -- VM/object key for full face or spread
    ADD COLUMN IF NOT EXISTS image_url text,           -- public or signed URL (may duplicate legacy col)
    ADD COLUMN IF NOT EXISTS image_path_left text,     -- when spread stored as two faces
    ADD COLUMN IF NOT EXISTS image_url_left text,
    ADD COLUMN IF NOT EXISTS image_path_right text,
    ADD COLUMN IF NOT EXISTS image_url_right text,
    ADD COLUMN IF NOT EXISTS image_width integer,
    ADD COLUMN IF NOT EXISTS image_height integer,
    ADD COLUMN IF NOT EXISTS image_sha256 text,
    ADD COLUMN IF NOT EXISTS storage_backend text
        CHECK (storage_backend IS NULL OR storage_backend IN ('fs', 's3', 'matricula', 'other'));

COMMENT ON COLUMN lank.scans.image_path IS
  'Full-page (or face) image object path on VM/object store — Site Host "view full page"';
COMMENT ON COLUMN lank.scans.image_url IS
  'Resolvable URL for the same image (Matricula hosted or CDN). Prefer path for durable serve.';
COMMENT ON COLUMN lank.scans.face IS
  'left|right|single|spread — which geometry image_path refers to';

-- If image_url already existed from 00_book_meta, ADD IF NOT EXISTS is a no-op for that name.
-- Ensure viewer_url remains Matricula deep link (?pg=).

-- ---------------------------------------------------------------------------
-- lank.entry_images — crop (and optional parent scan link) for every entry
-- One row per entry_id; staging tables may also denorm crop paths for convenience.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.entry_images (
    id                      bigserial PRIMARY KEY,
    entry_id                text NOT NULL,           -- KB1000_s002_p13_e2
    book_id                 bigint NOT NULL REFERENCES lank.books (id),
    scan_id                 bigint REFERENCES lank.scans (id),  -- parent full page
    scan                    text NOT NULL,
    page                    text,
    face                    text,
    entry                   integer,
    entry_kind              text,
    -- crop (human-facing "all ink" for this entry)
    crop_image_path         text NOT NULL,           -- Segmenter crop_image path/key
    crop_image_url          text,                    -- optional served URL
    source_image_path       text,                    -- face/spread used to cut the crop
    bbox                    jsonb,                   -- [x,y,w,h] in source_image
    polygon                 jsonb,                   -- [[x,y],…] slanted cut
    mask_fill               text,
    storage_backend         text
        CHECK (storage_backend IS NULL OR storage_backend IN ('fs', 's3', 'other')),
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT entry_images_entry_id_unique UNIQUE (entry_id)
);

CREATE INDEX IF NOT EXISTS entry_images_book_scan_idx
    ON lank.entry_images (book_id, scan) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS entry_images_scan_id_idx
    ON lank.entry_images (scan_id) WHERE deleted_at IS NULL;

COMMENT ON TABLE lank.entry_images IS
  'Segment crop per entry (required for UI entry detail). Links optional scan_id for full-page view.';

-- ---------------------------------------------------------------------------
-- Convenience columns on staging baptisms (pattern for other stg_* tables)
-- ---------------------------------------------------------------------------
ALTER TABLE lank.stg_baptisms
    ADD COLUMN IF NOT EXISTS entry_id text,
    ADD COLUMN IF NOT EXISTS entry_kind text DEFAULT 'baptism',
    ADD COLUMN IF NOT EXISTS crop_image_path text,
    ADD COLUMN IF NOT EXISTS crop_image_url text,
    ADD COLUMN IF NOT EXISTS scan_id bigint REFERENCES lank.scans (id);

CREATE UNIQUE INDEX IF NOT EXISTS stg_baptisms_entry_id_uidx
    ON lank.stg_baptisms (entry_id) WHERE entry_id IS NOT NULL AND deleted_at IS NULL;

COMMENT ON COLUMN lank.stg_baptisms.crop_image_path IS
  'Strong link to segment crop; prefer also lank.entry_images for geometry metadata';
