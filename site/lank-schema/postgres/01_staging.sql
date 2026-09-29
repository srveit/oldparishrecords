-- =============================================================================
-- 01_staging.sql — CSV-mirror staging tables (1:1 columns + book FK + soft-delete)
-- Import UTF-8 CSVs; keep diplomatic text untouched.
-- Natural unique: (book_id, scan, page, entry)
-- =============================================================================

-- Shared helper: only allow staging load for open books
CREATE OR REPLACE FUNCTION lank.assert_book_loadable(p_book_id bigint)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_status text;
    v_load   boolean;
    v_aid    text;
BEGIN
    SELECT access_status, load_staging, archival_id
      INTO v_status, v_load, v_aid
      FROM lank.books WHERE id = p_book_id AND deleted_at IS NULL;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'book_id % not found', p_book_id;
    END IF;
    IF NOT v_load OR v_status = 'gesperrt' THEN
        RAISE EXCEPTION 'book % (%) is not loadable (access_status=%)',
            v_aid, p_book_id, v_status;
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------
-- stg_baptisms  ← KB 1000 SCHEMA.md
-- scan,page,entry,baptism_date,birth_date,child_name,child_sex,father,
-- paternal_grandfather,paternal_grandmother,mother,maternal_grandfather,
-- maternal_grandmother,godfather,godmother,parents_married,parents_residence,
-- priest,transcription_latin,translation_de,translation_en,notes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.stg_baptisms (
    id                      bigserial PRIMARY KEY,
    book_id                 bigint NOT NULL REFERENCES lank.books (id),
    -- CSV columns (TEXT for diplomatic / uncertain dates)
    scan                    text NOT NULL,
    page                    text NOT NULL,
    entry                   integer NOT NULL,
    baptism_date            text,
    birth_date              text,
    child_name              text,
    child_sex               text,                    -- M | F | ?
    father                  text,
    paternal_grandfather    text,
    paternal_grandmother    text,
    mother                  text,
    maternal_grandfather    text,
    maternal_grandmother    text,
    godfather               text,
    godmother               text,
    parents_married         text,                    -- yes | no | ?
    parents_residence       text,
    priest                  text,
    transcription_latin     text,
    translation_de          text,
    translation_en          text,
    notes                   text,
    -- ops
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT stg_baptisms_natural_unique UNIQUE (book_id, scan, page, entry)
);

CREATE INDEX IF NOT EXISTS stg_baptisms_child_name_idx
    ON lank.stg_baptisms (child_name) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS stg_baptisms_baptism_date_idx
    ON lank.stg_baptisms (baptism_date) WHERE deleted_at IS NULL;

COMMENT ON TABLE lank.stg_baptisms IS
  'Staging 1:1 with KB1000_Taufen CSV. book_id → typically KB 1000.';

-- ---------------------------------------------------------------------------
-- stg_marriages  ← marriage_schema.md / .json
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.stg_marriages (
    id                      bigserial PRIMARY KEY,
    book_id                 bigint NOT NULL REFERENCES lank.books (id),
    scan                    text NOT NULL,
    page                    text NOT NULL,
    entry                   integer NOT NULL,
    marriage_date           text,
    groom_name              text,
    groom_status            text,
    groom_residence         text,
    groom_father            text,
    groom_mother            text,
    bride_name              text,
    bride_status            text,
    bride_residence         text,
    bride_father            text,
    bride_mother            text,
    witness_1               text,
    witness_2               text,
    witnesses_other         text,
    banns_or_dispensation   text,
    priest                  text,
    marriage_place          text,
    transcription_latin     text,
    translation_de          text,
    translation_en          text,
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT stg_marriages_natural_unique UNIQUE (book_id, scan, page, entry)
);

CREATE INDEX IF NOT EXISTS stg_marriages_groom_idx
    ON lank.stg_marriages (groom_name) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS stg_marriages_bride_idx
    ON lank.stg_marriages (bride_name) WHERE deleted_at IS NULL;

COMMENT ON TABLE lank.stg_marriages IS
  'Staging 1:1 with KB999_3 Trauungen CSV. book_id → KB 999_3.';

-- ---------------------------------------------------------------------------
-- stg_deaths  ← death_schema.md (KB 999_4, KB 1009; NOT 1010)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.stg_deaths (
    id                      bigserial PRIMARY KEY,
    book_id                 bigint NOT NULL REFERENCES lank.books (id),
    scan                    text NOT NULL,
    page                    text NOT NULL,
    entry                   integer NOT NULL,
    death_date              text,
    burial_date             text,
    deceased_name           text,
    deceased_sex            text,                    -- M | F | ?
    age                     text,
    status                  text,
    spouse_or_parents       text,
    residence               text,
    cause                   text,
    priest                  text,
    burial_place            text,
    transcription_latin     text,
    translation_de          text,
    translation_en          text,
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT stg_deaths_natural_unique UNIQUE (book_id, scan, page, entry)
);

CREATE INDEX IF NOT EXISTS stg_deaths_name_idx
    ON lank.stg_deaths (deceased_name) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS stg_deaths_death_date_idx
    ON lank.stg_deaths (death_date) WHERE deleted_at IS NULL;

COMMENT ON TABLE lank.stg_deaths IS
  'Staging 1:1 with death CSV. book_id → KB 999_4 or KB 1009. Never KB 1010 (gesperrt).';

-- ---------------------------------------------------------------------------
-- stg_communion  ← communion_schema.md (KB 1052_5 Lank; KB 1106_5 Osterath; NOT 1011)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.stg_communion (
    id                      bigserial PRIMARY KEY,
    book_id                 bigint NOT NULL REFERENCES lank.books (id),
    scan                    text NOT NULL,
    page                    text NOT NULL,
    entry                   integer NOT NULL,
    communion_date          text,
    communicant_name        text,
    communicant_sex         text,                    -- M | F | ?
    age                     text,
    father                  text,
    mother                  text,
    residence               text,
    priest                  text,
    transcription_latin     text,
    translation_de          text,
    translation_en          text,
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT stg_communion_natural_unique UNIQUE (book_id, scan, page, entry)
);

CREATE INDEX IF NOT EXISTS stg_communion_name_idx
    ON lank.stg_communion (communicant_name) WHERE deleted_at IS NULL;

COMMENT ON TABLE lank.stg_communion IS
  'Staging 1:1 with Erstkommunion CSV. book_id → KB 1052_5 (Lank) or KB 1106_5 (Osterath St. Nikolaus). Never KB 1011 (gesperrt).';

-- ---------------------------------------------------------------------------
-- Hist notes list types (KB 1052_9) — three tables, shared book
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.stg_confraternity_enrollment (
    id                      bigserial PRIMARY KEY,
    book_id                 bigint NOT NULL REFERENCES lank.books (id),
    list_type               text NOT NULL DEFAULT 'confraternity_enrollment'
        CHECK (list_type = 'confraternity_enrollment'),
    scan                    text NOT NULL,
    page                    text NOT NULL,
    entry                   integer NOT NULL,
    list_date               text,
    feast_or_occasion       text,
    confraternity_name      text,
    person_name             text,
    person_sex              text,                    -- m | f (schema); normalize in ETL
    residence_ex            text,
    status_or_role          text,
    priest_or_scribe        text,
    transcription           text,                    -- note: not transcription_latin
    translation_de          text,
    translation_en          text,
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT stg_conf_enroll_natural_unique UNIQUE (book_id, scan, page, entry)
);

CREATE INDEX IF NOT EXISTS stg_conf_enroll_name_idx
    ON lank.stg_confraternity_enrollment (person_name) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS stg_conf_enroll_conf_idx
    ON lank.stg_confraternity_enrollment (confraternity_name) WHERE deleted_at IS NULL;

COMMENT ON TABLE lank.stg_confraternity_enrollment IS
  'KB 1052_9 list_type=confraternity_enrollment. Status: sample-before-lock.';

CREATE TABLE IF NOT EXISTS lank.stg_yearly_name_roll (
    id                      bigserial PRIMARY KEY,
    book_id                 bigint NOT NULL REFERENCES lank.books (id),
    list_type               text NOT NULL DEFAULT 'yearly_name_roll'
        CHECK (list_type = 'yearly_name_roll'),
    scan                    text NOT NULL,
    page                    text NOT NULL,
    entry                   integer NOT NULL,
    year                    text,
    list_date               text,
    row_number              text,                    -- scribe number; never invent
    person_name             text,
    village_or_place        text,
    ditto_note              text,
    status_annotation       text,
    section_or_heading      text,
    transcription           text,
    translation_de          text,
    translation_en          text,
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT stg_yearly_roll_natural_unique UNIQUE (book_id, scan, page, entry)
);

CREATE INDEX IF NOT EXISTS stg_yearly_roll_name_idx
    ON lank.stg_yearly_name_roll (person_name) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS stg_yearly_roll_year_idx
    ON lank.stg_yearly_name_roll (year) WHERE deleted_at IS NULL;

COMMENT ON TABLE lank.stg_yearly_name_roll IS
  'KB 1052_9 list_type=yearly_name_roll. Status: sample-before-lock.';

CREATE TABLE IF NOT EXISTS lank.stg_ledger_admin (
    id                      bigserial PRIMARY KEY,
    book_id                 bigint NOT NULL REFERENCES lank.books (id),
    list_type               text NOT NULL DEFAULT 'ledger_admin'
        CHECK (list_type = 'ledger_admin'),
    scan                    text NOT NULL,
    page                    text NOT NULL,
    entry                   integer NOT NULL,
    entry_date              text,
    ledger_heading          text,
    person_name             text,
    residence               text,
    amount                  text,
    currency_or_unit        text,
    purpose                 text,
    related_person          text,
    transcription           text,
    translation_de          text,
    translation_en          text,
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT stg_ledger_admin_natural_unique UNIQUE (book_id, scan, page, entry)
);

CREATE INDEX IF NOT EXISTS stg_ledger_admin_name_idx
    ON lank.stg_ledger_admin (person_name) WHERE deleted_at IS NULL;

COMMENT ON TABLE lank.stg_ledger_admin IS
  'KB 1052_9 list_type=ledger_admin (e.g. Toten / Begräbnis-Gelder). Status: sample-before-lock.';

-- ---------------------------------------------------------------------------
-- Convenience: resolve archival_id → book_id
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION lank.book_id_for(p_archival_id text)
RETURNS bigint
LANGUAGE sql
STABLE
AS $$
    SELECT id FROM lank.books
     WHERE archival_id = p_archival_id AND deleted_at IS NULL;
$$;
