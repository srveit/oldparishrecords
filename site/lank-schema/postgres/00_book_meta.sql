-- =============================================================================
-- 00_book_meta.sql — books / register metadata (+ optional scans)
-- Source shape: book_meta_schema.json (lank-st-stephanus-book-meta v1.0.0)
-- PK convention: bigserial (documented in NOTES.md)
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS lank;

-- ---------------------------------------------------------------------------
-- books
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.books (
    id                      bigserial PRIMARY KEY,
    archival_id             text NOT NULL,           -- e.g. 'KB 1000', 'KB 999_3'
    parish_name             text NOT NULL,
    parish_place            text NOT NULL,
    diocese_archive         text NOT NULL,
    country                 text NOT NULL,
    book_title              text NOT NULL,           -- English display
    book_title_de           text NOT NULL,
    register_type           text NOT NULL,           -- Taufen | Trauungen | Sterbefälle | …
    date_from               date,                    -- coverage start (nullable if unknown)
    date_to                 date,
    comment                 text,                    -- e.g. Mischbuch
    -- source.* flattened for SQL convenience
    source_platform         text NOT NULL DEFAULT 'Matricula Online',
    source_url              text NOT NULL,
    book_start_url          text NOT NULL,
    first_page_url          text NOT NULL,
    first_page_note         text,
    scan_count              integer,
    scan_label_range        text,
    image_url_pattern       text,                    -- {NNN} placeholder
    image_referer           text DEFAULT 'https://data.matricula-online.eu/',
    csv_schema_ref          text,
    notes                   text,
    -- access / load control
    access_status           text NOT NULL DEFAULT 'open'
        CHECK (access_status IN ('open', 'gesperrt', 'stub')),
    gesperrt_until          date,                    -- NULL when open
    load_staging            boolean NOT NULL DEFAULT true,  -- false for gesperrt
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,             -- soft-delete
    CONSTRAINT books_archival_id_unique UNIQUE (archival_id)
);

COMMENT ON TABLE lank.books IS
  'Matricula register / book metadata (book_meta_schema). One row per archival_id.';
COMMENT ON COLUMN lank.books.access_status IS
  'open = transcribe/load; gesperrt = legal lock — meta only; stub = placeholder.';
COMMENT ON COLUMN lank.books.load_staging IS
  'When false, Site Host must not import CSV rows for this volume.';

CREATE INDEX IF NOT EXISTS books_register_type_idx ON lank.books (register_type);
CREATE INDEX IF NOT EXISTS books_access_status_idx ON lank.books (access_status);

-- ---------------------------------------------------------------------------
-- scans — optional source pointers (archival scan faces)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lank.scans (
    id                      bigserial PRIMARY KEY,
    book_id                 bigint NOT NULL REFERENCES lank.books (id) ON DELETE CASCADE,
    scan                    text NOT NULL,           -- digits only, e.g. '002', '118'
    scan_label              text,                    -- e.g. KB_1000-002
    page_left               text,                    -- optional face page numbers
    page_right              text,
    matricula_pg            integer,                 -- ?pg=N if known
    viewer_url              text,
    image_url               text,
    notes                   text,
    created_at              timestamptz NOT NULL DEFAULT now(),
    deleted_at              timestamptz,
    CONSTRAINT scans_book_scan_unique UNIQUE (book_id, scan)
);

COMMENT ON TABLE lank.scans IS
  'Optional Matricula scan inventory / URL cache. Staging rows also store scan+page+entry.';

CREATE INDEX IF NOT EXISTS scans_book_id_idx ON lank.scans (book_id);

-- ---------------------------------------------------------------------------
-- Seed: open volumes from locked *_meta.json (2026-09-10)
-- ---------------------------------------------------------------------------
INSERT INTO lank.books (
    archival_id, parish_name, parish_place, diocese_archive, country,
    book_title, book_title_de, register_type, date_from, date_to, comment,
    source_platform, source_url, book_start_url, first_page_url, first_page_note,
    scan_count, scan_label_range, image_url_pattern, image_referer,
    csv_schema_ref, notes, access_status, gesperrt_until, load_staging
) VALUES
(
    'KB 1000', 'St. Stephanus', 'Lank (Lank-Latum)', 'Aachen, rk. Bistum', 'Deutschland',
    'St. Stephan, Lank, Baptismal Records, Jan 1, 1779–Dec 31, 1837',
    'St. Stephanus, Lank, Taufbuch, 1. Jan. 1779–31. Dez. 1837',
    'Taufen', '1779-01-01', '1837-12-31', NULL,
    'Matricula Online',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1000/?pg=1',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1000/?pg=1',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1000/?pg=3',
    'Matricula scan 002 / ?pg=3 — first written register face (book page 13). ?pg=1 is the cover.',
    323, 'KB_1000-000 … KB_1000-322',
    'https://hosted-images.matricula-online.eu/images/matricula/DE-BDAA/images/17%20Matricula/DE_2187_KB_1000/JPEG-1MB/DE_2187_KB_1000-{NNN}.jpg',
    'https://data.matricula-online.eu/',
    'SCHEMA.md',
    'Catholic parish register. Early entries Latin (priest Wilh. Jacobs et al.).',
    'open', NULL, true
),
(
    'KB 999_3', 'St. Stephanus', 'Lank (Lank-Latum)', 'Aachen, rk. Bistum', 'Deutschland',
    'St. Stephan, Lank, Marriage Records, Jan 1, 1754–Dec 31, 1798',
    'St. Stephanus, Lank, Trauungen, 1. Jan. 1754–31. Dez. 1798',
    'Trauungen', '1754-01-01', '1798-12-31', 'Mischbuch',
    'Matricula Online',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+999_3/?pg=1',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+999_3/?pg=1',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+999_3/?pg=1',
    'Scan KB_999-117 = pp.250 blank / 251 title Heirathen; first marriages scan 118 (pp.252–253).',
    42, 'KB_999-117 … KB_999-158',
    'https://hosted-images.matricula-online.eu/images/matricula/DE-BDAA/images/17%20Matricula/DE_2187_KB_999_M/H/DE_2187_KB_999-{NNN}.jpg',
    'https://data.matricula-online.eu/',
    'marriage_schema.json',
    'Marriage slice of Mischbuch KB 999. Overlap later with KB 1002 Trauungen.',
    'open', NULL, true
),
(
    'KB 999_4', 'St. Stephanus', 'Lank (Lank-Latum)', 'Aachen, rk. Bistum', 'Deutschland',
    'St. Stephan, Lank, Death Records, Jan 1, 1710–Dec 31, 1798',
    'St. Stephanus, Lank, Sterbefälle, 1. Jan. 1710–31. Dez. 1798',
    'Sterbefälle', '1710-01-01', '1798-12-31', 'Mischbuch',
    'Matricula Online',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+999_4/?pg=1',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+999_4/?pg=1',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+999_4/?pg=5',
    'Scan 004 / ?pg=5 — SERIES MORTUORUM title. Body /S/ 000–093; Alph. Reg S 094–116.',
    117, 'KB_999-000 … KB_999-116',
    'https://hosted-images.matricula-online.eu/images/matricula/DE-BDAA/images/17%20Matricula/DE_2187_KB_999_M/S/DE_2187_KB_999-{NNN}.jpg',
    'https://data.matricula-online.eu/',
    'death_schema.json',
    'Death slice of Mischbuch KB 999. Alpha register scans 094–116 are indexes — transcribe only if project expands.',
    'open', NULL, true
),
(
    'KB 1009', 'St. Stephanus', 'Lank (Lank-Latum)', 'Aachen, rk. Bistum', 'Deutschland',
    'St. Stephan, Lank, Death Records, Jan 1, 1779–Dec 31, 1878',
    'St. Stephanus, Lank, Sterbefälle, 1. Jan. 1779–31. Dez. 1878',
    'Sterbefälle', '1779-01-01', '1878-12-31', NULL,
    'Matricula Online',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1009/?pg=1',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1009/?pg=1',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1009/?pg=1',
    'Scan 000 cover; 002 title flyleaf. Same death_schema as KB 999_4.',
    333, 'KB_1009-000 … KB_1009-332',
    'https://hosted-images.matricula-online.eu/images/matricula/DE-BDAA/images/17%20Matricula/DE_2187_KB_1009/JPEG-1MB/DE_2187_KB_1009-{NNN}.jpg',
    'https://data.matricula-online.eu/',
    'death_schema.json',
    'Standalone Sterbebuch overlapping late KB 999_4.',
    'open', NULL, true
),
(
    'KB 1052_5', 'St. Stephanus', 'Lank (Lank-Latum)', 'Aachen, rk. Bistum', 'Deutschland',
    'St. Stephan, Lank, First Communion Records, 1755–1756',
    'St. Stephanus, Lank, Erstkommunion, 1755–1756',
    'Erstkommunion', '1755-01-01', '1756-03-22', 'Mischbuch',
    'Matricula Online',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1052_5/?pg=1',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1052_5/?pg=1',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1052_5/?pg=1',
    'Only scan KB_1052-073 (pp.134–135). Pilot 135 rows; ink includes 1756-03-22.',
    1, 'KB_1052-073',
    'https://hosted-images.matricula-online.eu/images/matricula/DE-BDAA/images/17%20Matricula/DE_2187_KB_1052_M/EK/DE_2187_KB_1052-073.jpg',
    'https://data.matricula-online.eu/',
    'communion_schema.json',
    'Pilot accepted 2026-09-10. KB 1011 gesperrt — do not load.',
    'open', NULL, true
),
(
    'KB 1052_9', 'St. Stephanus', 'Lank (Lank-Latum)', 'Aachen, rk. Bistum', 'Deutschland',
    'St. Stephan, Lank, Historical Notes (Confraternities & Lists), Jan 1, 1687–Dec 31, 1918',
    'St. Stephanus, Lank, historische Notizen (Bruderschaften & Verzeichnisse), 1. Jan. 1687–31. Dez. 1918',
    'historische Notizen', '1687-01-01', '1918-12-31',
    'Mischbuch; Liber Confraternitatum Scapularis et S. Sebastiani in Lanck. Carmel typo 1958→1858.',
    'Matricula Online',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1052_9/',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1052_9/?pg=1',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1052_9/?pg=4',
    'Viewer ?pg=1 = scan KB_1052-000. Three list-type CSVs share this book.',
    100, 'KB_1052-000 … KB_1052-101 (skips 084, 085)',
    'https://hosted-images.matricula-online.eu/images/matricula/DE-BDAA/images/17%20Matricula/DE_2187_KB_1052_M/hist.%20N/DE_2187_KB_1052-{NNN}.jpg',
    'https://data.matricula-online.eu/',
    'list_types.md',
    'Distinct list types: confraternity_enrollment, yearly_name_roll, ledger_admin (sample-before-lock).',
    'open', NULL, true
)
ON CONFLICT (archival_id) DO UPDATE SET
    book_title      = EXCLUDED.book_title,
    book_title_de   = EXCLUDED.book_title_de,
    notes           = EXCLUDED.notes,
    updated_at      = now();

-- ---------------------------------------------------------------------------
-- Gesperrt volumes — meta only, never load staging
-- ---------------------------------------------------------------------------
INSERT INTO lank.books (
    archival_id, parish_name, parish_place, diocese_archive, country,
    book_title, book_title_de, register_type, date_from, date_to, comment,
    source_platform, source_url, book_start_url, first_page_url, first_page_note,
    scan_count, scan_label_range, image_url_pattern, image_referer,
    csv_schema_ref, notes, access_status, gesperrt_until, load_staging
) VALUES
(
    'KB 1010', 'St. Stephanus', 'Lank (Lank-Latum)', 'Aachen, rk. Bistum', 'Deutschland',
    'St. Stephan, Lank, Death Records, 1879–2007 (GESPERRT)',
    'St. Stephanus, Lank, Sterbefälle, 1879–2007 (gesperrt)',
    'Sterbefälle', '1879-01-01', '2007-12-31', NULL,
    'Matricula Online',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1010/',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1010/',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1010/',
    'Gesperrt — viewer blocked for legal reasons. See KB1010_gesperrt.md.',
    282, 'KB_1010-000 … KB_1010-281',
    NULL, 'https://data.matricula-online.eu/',
    'death_schema.json',
    'GESPERRT bis 31.12.2107. Do not sample, download images for transcription, or load CSV. When unlocked, reuse death_schema.',
    'gesperrt', '2107-12-31', false
),
(
    'KB 1011', 'St. Stephanus', 'Lank (Lank-Latum)', 'Aachen, rk. Bistum', 'Deutschland',
    'St. Stephan, Lank, First Communion Records, 1880–1934 (GESPERRT)',
    'St. Stephanus, Lank, Erstkommunion, 1880–1934 (gesperrt)',
    'Erstkommunion', '1880-01-01', '1934-12-31', NULL,
    'Matricula Online',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1011/',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1011/',
    'https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+1011/',
    'Gesperrt — pilot only KB 1052_5. See KB1011_gesperrt.md.',
    76, 'KB_1011-000 … KB_1011-075',
    NULL, 'https://data.matricula-online.eu/',
    'communion_schema.json',
    'GESPERRT bis 31.12.2044. Do not transcribe. When unlocked, reuse communion_schema (age/parents reserved).',
    'gesperrt', '2044-12-31', false
)
ON CONFLICT (archival_id) DO UPDATE SET
    access_status   = EXCLUDED.access_status,
    gesperrt_until  = EXCLUDED.gesperrt_until,
    load_staging    = false,
    notes           = EXCLUDED.notes,
    updated_at      = now();
