-- =============================================================================
-- 02_normalized.sql — pragmatic analytical layer for person × place × date
-- Does NOT force person merges across events; link later via person_link.
-- Mapping notes: see NOTES.md and comments below.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- place — residence / hamlet / ceremony place (normalize spelling later)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.place (
    id                      bigserial PRIMARY KEY,
    name_display            text NOT NULL,           -- preferred display (e.g. Lank)
    name_normalized         text NOT NULL,           -- lower(unaccent) key for search
    name_variants           text[],                  -- Latum, Lathum, …
    place_kind              text DEFAULT 'locality'
        CHECK (place_kind IN ('locality', 'parish', 'hamlet', 'other')),
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT place_name_normalized_unique UNIQUE (name_normalized)
);

CREATE INDEX IF NOT EXISTS place_name_display_idx ON lank.place (name_display);

COMMENT ON TABLE lank.place IS
  'Places from parents_residence, ex/zu phrases, marriage_place, burial_place, villages.';

-- Seed common Lank-area localities (extend as transcription finds more)
INSERT INTO lank.place (name_display, name_normalized, name_variants, place_kind) VALUES
    ('Lank', 'lank', ARRAY['Lanck', 'Lank-Latum'], 'locality'),
    ('Latum', 'latum', ARRAY['Lathum'], 'hamlet'),
    ('Stratum', 'stratum', NULL, 'hamlet'),
    ('Ilverich', 'ilverich', NULL, 'hamlet'),
    ('Gellep', 'gellep', NULL, 'hamlet'),
    ('Nierst', 'nierst', NULL, 'hamlet'),
    ('Hamm', 'hamm', NULL, 'hamlet'),
    ('Osterath', 'osterath', NULL, 'locality'),
    ('Bockum', 'bockum', NULL, 'hamlet'),
    ('Kierst', 'kierst', NULL, 'hamlet'),
    ('Gladbach', 'gladbach', NULL, 'locality')
ON CONFLICT (name_normalized) DO NOTHING;

-- ---------------------------------------------------------------------------
-- person — one row per *mention cluster* you choose to create in ETL
-- Default ETL: one person row per named role occurrence (no cross-event merge).
-- Later: merge via person_link / same person_id reassignment.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.person (
    id                      bigserial PRIMARY KEY,
    display_name            text NOT NULL,           -- diplomatic or lightly cleaned
    sex                     text
        CHECK (sex IS NULL OR sex IN ('M', 'F', '?')),
    name_normalized         text,                    -- search key (lower, collapsed space)
    birth_year_approx       smallint,                -- optional hint only
    death_year_approx       smallint,
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz
);

CREATE INDEX IF NOT EXISTS person_name_normalized_idx
    ON lank.person (name_normalized) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS person_display_name_trgm_ready_idx
    ON lank.person (display_name);  -- enable pg_trgm GIN later if desired

COMMENT ON TABLE lank.person IS
  'Pragmatic person rows. Do NOT auto-merge same names across events; use person_link.';

-- Optional: explicit same-person / related links (manual or later matching)
CREATE TABLE IF NOT EXISTS lank.person_link (
    id                      bigserial PRIMARY KEY,
    person_id_a             bigint NOT NULL REFERENCES lank.person (id),
    person_id_b             bigint NOT NULL REFERENCES lank.person (id),
    link_type               text NOT NULL
        CHECK (link_type IN ('same_as', 'possibly_same', 'parent_of', 'spouse_of', 'other')),
    confidence              text DEFAULT 'possible'
        CHECK (confidence IN ('certain', 'probable', 'possible', 'rejected')),
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT person_link_ordered CHECK (person_id_a < person_id_b),
    CONSTRAINT person_link_unique UNIQUE (person_id_a, person_id_b, link_type)
);

COMMENT ON TABLE lank.person_link IS
  'Deferred identity / relationship edges. Empty until Site Host / researchers link.';

-- ---------------------------------------------------------------------------
-- event — one sacramental / list event (baptism, marriage, death, …)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.event (
    id                      bigserial PRIMARY KEY,
    event_type              text NOT NULL
        CHECK (event_type IN (
            'baptism', 'marriage', 'death', 'burial', 'communion',
            'confraternity_enrollment', 'yearly_name_roll', 'ledger_admin',
            'other'
        )),
    event_date              date,                    -- parsed when ISO-complete
    event_date_text         text,                    -- original CSV date cell(s)
    event_date_precision    text
        CHECK (event_date_precision IS NULL OR event_date_precision IN (
            'day', 'month', 'year', 'partial', 'unknown', 'literal'
        )),
    secondary_date          date,                    -- e.g. burial vs death, birth vs baptism
    secondary_date_text     text,
    place_id                bigint REFERENCES lank.place (id),
    place_text              text,                    -- as written if no place_id yet
    book_id                 bigint NOT NULL REFERENCES lank.books (id),
    scan                    text,
    page                    text,
    entry                   integer,
    -- provenance to staging
    staging_table           text NOT NULL,           -- e.g. stg_baptisms
    staging_id              bigint NOT NULL,
    priest                  text,
    transcription_excerpt   text,                    -- optional short; full text stays in staging
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT event_staging_unique UNIQUE (staging_table, staging_id)
);

CREATE INDEX IF NOT EXISTS event_type_date_idx
    ON lank.event (event_type, event_date) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS event_book_scan_page_idx
    ON lank.event (book_id, scan, page, entry);
CREATE INDEX IF NOT EXISTS event_place_id_idx ON lank.event (place_id);

COMMENT ON TABLE lank.event IS
  'One row per staging entry (or death+burial as one event with secondary_date).';

-- ---------------------------------------------------------------------------
-- event_person — roles on an event (child, father, witness, deceased, …)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.event_person (
    id                      bigserial PRIMARY KEY,
    event_id                bigint NOT NULL REFERENCES lank.event (id) ON DELETE CASCADE,
    person_id               bigint REFERENCES lank.person (id),  -- NULL until linked
    role                    text NOT NULL
        CHECK (role IN (
            'child', 'father', 'mother',
            'paternal_grandfather', 'paternal_grandmother',
            'maternal_grandfather', 'maternal_grandmother',
            'godfather', 'godmother',
            'groom', 'bride', 'groom_father', 'groom_mother',
            'bride_father', 'bride_mother',
            'witness', 'witness_other',
            'deceased', 'spouse', 'parent',  -- parent when spouse_or_parents unresolved
            'communicant',
            'enrollee', 'scribe', 'priest',
            'payer', 'related',
            'other'
        )),
    role_ordinal            smallint,                -- witness 1, 2, …
    name_as_written         text NOT NULL,           -- diplomatic from CSV cell
    sex                     text
        CHECK (sex IS NULL OR sex IN ('M', 'F', '?')),
    status_as_written       text,                    -- viduus, filia, …
    residence_place_id      bigint REFERENCES lank.place (id),
    residence_text          text,
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz
);

CREATE INDEX IF NOT EXISTS event_person_event_id_idx ON lank.event_person (event_id);
CREATE INDEX IF NOT EXISTS event_person_person_id_idx
    ON lank.event_person (person_id) WHERE person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS event_person_name_idx ON lank.event_person (name_as_written);
CREATE INDEX IF NOT EXISTS event_person_role_idx ON lank.event_person (role);

COMMENT ON TABLE lank.event_person IS
  'Named participants. person_id optional — fill when identity resolved; name_as_written always kept.';

-- ---------------------------------------------------------------------------
-- Date parse helper (strict ISO day only → DATE; else NULL)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION lank.try_iso_date(p_text text)
RETURNS date
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    IF p_text IS NULL OR btrim(p_text) = '' THEN
        RETURN NULL;
    END IF;
    -- Reject obvious uncertain / partial forms
    IF p_text ~ '[\?\[]' OR p_text ~ '\?\?' THEN
        RETURN NULL;
    END IF;
    IF p_text ~ '^\d{4}-\d{2}-\d{2}$' THEN
        RETURN p_text::date;
    END IF;
    RETURN NULL;
EXCEPTION WHEN others THEN
    RETURN NULL;
END;
$$;

COMMENT ON FUNCTION lank.try_iso_date(text) IS
  'Returns DATE only for clean YYYY-MM-DD without [?]/??. Otherwise NULL; keep original TEXT.';

-- ---------------------------------------------------------------------------
-- MAPPING CHEATSHEET (ETL — implement in app or later SQL scripts)
-- ---------------------------------------------------------------------------
-- stg_baptisms → event_type='baptism'
--   event_date ← try_iso_date(baptism_date); event_date_text ← baptism_date
--   secondary_date ← try_iso_date(birth_date)
--   event_person: child, father, mother, grandparents, godfather, godmother
--   place_text ← parents_residence
--
-- stg_marriages → event_type='marriage'
--   roles: groom, bride, groom_father/mother, bride_father/mother,
--          witness (ordinal 1,2), witness_other (split witnesses_other on ';')
--   place_text ← marriage_place (blank = default parish church; do not invent)
--
-- stg_deaths → event_type='death' (burial date → secondary_*)
--   role deceased; spouse_or_parents → spouse OR parent (or leave as notes /
--   role 'other' with name_as_written = full cell if unparsed)
--
-- stg_communion → event_type='communion'; roles communicant, father, mother
--
-- stg_confraternity_enrollment → event_type='confraternity_enrollment'
--   role enrollee; person_sex m/f → upper M/F
--
-- stg_yearly_name_roll → event_type='yearly_name_roll'
--   event_date_text ← list_date or year; place ← village_or_place
--
-- stg_ledger_admin → event_type='ledger_admin'
--   roles payer (person_name), related (related_person)
--
-- ALWAYS: staging_table + staging_id; book_id + scan + page + entry
-- NEVER: invent blank parents/status; never load gesperrt books
-- =============================================================================
