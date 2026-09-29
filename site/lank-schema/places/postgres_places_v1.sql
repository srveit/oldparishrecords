-- =============================================================================
-- Temporal place gazetteer (OPR) — sketch for Site Host
-- Schema docs: /workspace/lank-schema/places/
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS lank;

CREATE TABLE IF NOT EXISTS lank.places (
    id                  bigserial PRIMARY KEY,
    place_id            text NOT NULL UNIQUE,      -- e.g. place:lank
    place_kind          text NOT NULL,
    preferred_label     text,
    lat                 double precision,
    lon                 double precision,
    external_ids        jsonb,
    notes               text,
    sources             jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    deleted_at          timestamptz
);

CREATE TABLE IF NOT EXISTS lank.place_names (
    id                  bigserial PRIMARY KEY,
    place_id            text NOT NULL REFERENCES lank.places (place_id),
    name                text NOT NULL,
    name_type           text NOT NULL,
    lang                text,
    date_from           date,
    date_to             date,
    date_from_precision text,
    date_to_precision   text,
    uncertain_end       boolean NOT NULL DEFAULT false,
    notes               text,
    sources             jsonb,
    deleted_at          timestamptz
);

CREATE INDEX IF NOT EXISTS place_names_place_idx ON lank.place_names (place_id);
CREATE INDEX IF NOT EXISTS place_names_name_idx ON lank.place_names (lower(name));
-- as-of lookup helper: names valid on D
-- WHERE (date_from IS NULL OR date_from <= D) AND (date_to IS NULL OR date_to >= D)

CREATE TABLE IF NOT EXISTS lank.place_admin (
    id                  bigserial PRIMARY KEY,
    place_id            text NOT NULL REFERENCES lank.places (place_id),
    admin_level         text NOT NULL,
    admin_name          text NOT NULL,
    admin_name_lang     text,
    date_from           date,
    date_to             date,
    uncertain_end       boolean NOT NULL DEFAULT false,
    notes               text,
    sources             jsonb,
    deleted_at          timestamptz
);

CREATE INDEX IF NOT EXISTS place_admin_place_idx ON lank.place_admin (place_id);

CREATE TABLE IF NOT EXISTS lank.place_parish_links (
    id                  bigserial PRIMARY KEY,
    place_id            text NOT NULL REFERENCES lank.places (place_id),
    parish_slug         text NOT NULL,             -- FK logically to parishes.parish_id/slug
    role                text NOT NULL,
    date_from           date,
    date_to             date,
    uncertain_end       boolean NOT NULL DEFAULT false,
    notes               text,
    sources             jsonb,
    deleted_at          timestamptz
);

CREATE INDEX IF NOT EXISTS place_parish_place_idx ON lank.place_parish_links (place_id);
CREATE INDEX IF NOT EXISTS place_parish_slug_idx ON lank.place_parish_links (parish_slug);

-- Optional structured residence on staging (keep diplomatic text columns too)
-- ALTER TABLE lank.stg_baptisms ADD COLUMN IF NOT EXISTS parents_residence_place_id text;
-- ALTER TABLE lank.stg_baptisms ADD COLUMN IF NOT EXISTS parents_residence_as_of date;

COMMENT ON TABLE lank.places IS 'Stable place identity; names/admin are time-bounded children';
