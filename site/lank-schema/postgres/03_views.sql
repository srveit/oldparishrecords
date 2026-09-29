-- =============================================================================
-- 03_views.sql — search-friendly flat views (+ person timeline)
-- Prefer staging for diplomatic fidelity; normalized when populated.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Flat views over staging (always available after CSV import)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW lank.baptisms_flat AS
SELECT
    b.id                    AS staging_id,
    bk.archival_id,
    bk.book_title,
    b.scan,
    b.page,
    b.entry,
    b.baptism_date,
    lank.try_iso_date(b.baptism_date) AS baptism_date_parsed,
    b.birth_date,
    lank.try_iso_date(b.birth_date)   AS birth_date_parsed,
    b.child_name,
    b.child_sex,
    b.father,
    b.mother,
    b.paternal_grandfather,
    b.paternal_grandmother,
    b.maternal_grandfather,
    b.maternal_grandmother,
    b.godfather,
    b.godmother,
    b.parents_married,
    b.parents_residence,
    b.priest,
    b.transcription_latin,
    b.translation_de,
    b.translation_en,
    b.notes,
    bk.source_url,
    format('%s&pg=%s', regexp_replace(bk.book_start_url, '\?pg=[0-9]+$', ''), b.scan)
        AS approximate_viewer_hint,
    b.created_at,
    b.deleted_at
FROM lank.stg_baptisms b
JOIN lank.books bk ON bk.id = b.book_id
WHERE b.deleted_at IS NULL AND bk.deleted_at IS NULL;

CREATE OR REPLACE VIEW lank.marriages_flat AS
SELECT
    m.id AS staging_id,
    bk.archival_id,
    bk.book_title,
    m.scan, m.page, m.entry,
    m.marriage_date,
    lank.try_iso_date(m.marriage_date) AS marriage_date_parsed,
    m.groom_name, m.groom_status, m.groom_residence,
    m.groom_father, m.groom_mother,
    m.bride_name, m.bride_status, m.bride_residence,
    m.bride_father, m.bride_mother,
    m.witness_1, m.witness_2, m.witnesses_other,
    m.banns_or_dispensation, m.priest, m.marriage_place,
    m.transcription_latin, m.translation_de, m.translation_en, m.notes,
    bk.source_url,
    m.created_at, m.deleted_at
FROM lank.stg_marriages m
JOIN lank.books bk ON bk.id = m.book_id
WHERE m.deleted_at IS NULL AND bk.deleted_at IS NULL;

CREATE OR REPLACE VIEW lank.deaths_flat AS
SELECT
    d.id AS staging_id,
    bk.archival_id,
    bk.book_title,
    d.scan, d.page, d.entry,
    d.death_date,
    lank.try_iso_date(d.death_date)  AS death_date_parsed,
    d.burial_date,
    lank.try_iso_date(d.burial_date) AS burial_date_parsed,
    d.deceased_name, d.deceased_sex, d.age, d.status,
    d.spouse_or_parents, d.residence, d.cause,
    d.priest, d.burial_place,
    d.transcription_latin, d.translation_de, d.translation_en, d.notes,
    bk.source_url,
    d.created_at, d.deleted_at
FROM lank.stg_deaths d
JOIN lank.books bk ON bk.id = d.book_id
WHERE d.deleted_at IS NULL AND bk.deleted_at IS NULL;

CREATE OR REPLACE VIEW lank.communion_flat AS
SELECT
    c.id AS staging_id,
    bk.archival_id,
    bk.book_title,
    c.scan, c.page, c.entry,
    c.communion_date,
    lank.try_iso_date(c.communion_date) AS communion_date_parsed,
    c.communicant_name, c.communicant_sex, c.age,
    c.father, c.mother, c.residence, c.priest,
    c.transcription_latin, c.translation_de, c.translation_en, c.notes,
    bk.source_url,
    c.created_at, c.deleted_at
FROM lank.stg_communion c
JOIN lank.books bk ON bk.id = c.book_id
WHERE c.deleted_at IS NULL AND bk.deleted_at IS NULL;

-- Hist-notes union for site search (list_type discriminator)
CREATE OR REPLACE VIEW lank.histnotes_flat AS
SELECT
    e.id AS staging_id,
    bk.archival_id,
    e.list_type,
    e.scan, e.page, e.entry,
    e.list_date AS event_date_text,
    lank.try_iso_date(e.list_date) AS event_date_parsed,
    e.person_name AS primary_name,
    upper(nullif(e.person_sex, '')) AS sex_normalized,
    e.residence_ex AS place_text,
    e.confraternity_name AS section_label,
    e.feast_or_occasion AS occasion,
    e.status_or_role AS status_text,
    e.priest_or_scribe AS priest,
    NULL::text AS year,
    NULL::text AS amount,
    e.transcription, e.translation_de, e.translation_en, e.notes,
    bk.source_url
FROM lank.stg_confraternity_enrollment e
JOIN lank.books bk ON bk.id = e.book_id
WHERE e.deleted_at IS NULL AND bk.deleted_at IS NULL

UNION ALL

SELECT
    y.id,
    bk.archival_id,
    y.list_type,
    y.scan, y.page, y.entry,
    COALESCE(y.list_date, y.year),
    COALESCE(lank.try_iso_date(y.list_date), NULL),
    y.person_name,
    NULL,
    y.village_or_place,
    y.section_or_heading,
    NULL,
    y.status_annotation,
    NULL,
    y.year,
    NULL,
    y.transcription, y.translation_de, y.translation_en, y.notes,
    bk.source_url
FROM lank.stg_yearly_name_roll y
JOIN lank.books bk ON bk.id = y.book_id
WHERE y.deleted_at IS NULL AND bk.deleted_at IS NULL

UNION ALL

SELECT
    l.id,
    bk.archival_id,
    l.list_type,
    l.scan, l.page, l.entry,
    l.entry_date,
    lank.try_iso_date(l.entry_date),
    l.person_name,
    NULL,
    l.residence,
    l.ledger_heading,
    l.purpose,
    NULL,
    NULL,
    NULL,
    CASE WHEN l.amount IS NOT NULL
         THEN l.amount || COALESCE(' ' || l.currency_or_unit, '')
         ELSE NULL END,
    l.transcription, l.translation_de, l.translation_en, l.notes,
    bk.source_url
FROM lank.stg_ledger_admin l
JOIN lank.books bk ON bk.id = l.book_id
WHERE l.deleted_at IS NULL AND bk.deleted_at IS NULL;

COMMENT ON VIEW lank.histnotes_flat IS
  'Union of three KB 1052_9 list types for search; list_type distinguishes rows.';

-- ---------------------------------------------------------------------------
-- Name search across staging (simple ILIKE target)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW lank.name_mentions AS
SELECT 'baptism'::text AS source, 'child'::text AS role,
       child_name AS name_as_written, baptism_date AS date_text,
       archival_id, scan, page, entry, staging_id
FROM lank.baptisms_flat WHERE child_name IS NOT NULL AND btrim(child_name) <> ''
UNION ALL
SELECT 'baptism', 'father', father, baptism_date, archival_id, scan, page, entry, staging_id
FROM lank.baptisms_flat WHERE father IS NOT NULL AND btrim(father) <> ''
UNION ALL
SELECT 'baptism', 'mother', mother, baptism_date, archival_id, scan, page, entry, staging_id
FROM lank.baptisms_flat WHERE mother IS NOT NULL AND btrim(mother) <> ''
UNION ALL
SELECT 'baptism', 'godfather', godfather, baptism_date, archival_id, scan, page, entry, staging_id
FROM lank.baptisms_flat WHERE godfather IS NOT NULL AND btrim(godfather) <> ''
UNION ALL
SELECT 'baptism', 'godmother', godmother, baptism_date, archival_id, scan, page, entry, staging_id
FROM lank.baptisms_flat WHERE godmother IS NOT NULL AND btrim(godmother) <> ''
UNION ALL
SELECT 'marriage', 'groom', groom_name, marriage_date, archival_id, scan, page, entry, staging_id
FROM lank.marriages_flat WHERE groom_name IS NOT NULL
UNION ALL
SELECT 'marriage', 'bride', bride_name, marriage_date, archival_id, scan, page, entry, staging_id
FROM lank.marriages_flat WHERE bride_name IS NOT NULL
UNION ALL
SELECT 'marriage', 'witness', witness_1, marriage_date, archival_id, scan, page, entry, staging_id
FROM lank.marriages_flat WHERE witness_1 IS NOT NULL AND btrim(witness_1) <> ''
UNION ALL
SELECT 'marriage', 'witness', witness_2, marriage_date, archival_id, scan, page, entry, staging_id
FROM lank.marriages_flat WHERE witness_2 IS NOT NULL AND btrim(witness_2) <> ''
UNION ALL
SELECT 'death', 'deceased', deceased_name, COALESCE(death_date, burial_date),
       archival_id, scan, page, entry, staging_id
FROM lank.deaths_flat WHERE deceased_name IS NOT NULL
UNION ALL
SELECT 'communion', 'communicant', communicant_name, communion_date,
       archival_id, scan, page, entry, staging_id
FROM lank.communion_flat WHERE communicant_name IS NOT NULL
UNION ALL
SELECT 'histnotes', list_type, primary_name, event_date_text,
       archival_id, scan, page, entry, staging_id
FROM lank.histnotes_flat WHERE primary_name IS NOT NULL AND btrim(primary_name) <> '';

-- ---------------------------------------------------------------------------
-- Normalized person timeline (populated after ETL)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW lank.person_timeline AS
SELECT
    p.id                    AS person_id,
    p.display_name,
    p.sex,
    ep.role,
    e.event_type,
    e.event_date,
    e.event_date_text,
    e.secondary_date,
    bk.archival_id,
    e.scan,
    e.page,
    e.entry,
    ep.name_as_written,
    ep.status_as_written,
    COALESCE(pl.name_display, ep.residence_text, e.place_text) AS place_label,
    e.staging_table,
    e.staging_id,
    e.id                    AS event_id
FROM lank.person p
JOIN lank.event_person ep ON ep.person_id = p.id AND ep.deleted_at IS NULL
JOIN lank.event e ON e.id = ep.event_id AND e.deleted_at IS NULL
JOIN lank.books bk ON bk.id = e.book_id
LEFT JOIN lank.place pl ON pl.id = COALESCE(ep.residence_place_id, e.place_id)
WHERE p.deleted_at IS NULL
ORDER BY p.id, e.event_date NULLS LAST, e.event_date_text;

-- Events with participants (normalized search)
CREATE OR REPLACE VIEW lank.events_with_people AS
SELECT
    e.id AS event_id,
    e.event_type,
    e.event_date,
    e.event_date_text,
    bk.archival_id,
    e.scan, e.page, e.entry,
    e.priest,
    e.place_text,
    pl.name_display AS place_name,
    e.staging_table,
    e.staging_id,
    jsonb_agg(
        jsonb_build_object(
            'role', ep.role,
            'name', ep.name_as_written,
            'person_id', ep.person_id,
            'status', ep.status_as_written
        ) ORDER BY ep.role, ep.role_ordinal NULLS LAST
    ) AS people
FROM lank.event e
JOIN lank.books bk ON bk.id = e.book_id
LEFT JOIN lank.place pl ON pl.id = e.place_id
LEFT JOIN lank.event_person ep ON ep.event_id = e.id AND ep.deleted_at IS NULL
WHERE e.deleted_at IS NULL
GROUP BY e.id, bk.archival_id, pl.name_display;

-- Open books only (site catalog)
CREATE OR REPLACE VIEW lank.books_open AS
SELECT *
FROM lank.books
WHERE deleted_at IS NULL
  AND access_status = 'open'
  AND load_staging = true;

CREATE OR REPLACE VIEW lank.books_gesperrt AS
SELECT archival_id, register_type, date_from, date_to,
       gesperrt_until, notes, source_url
FROM lank.books
WHERE access_status = 'gesperrt' AND deleted_at IS NULL;
