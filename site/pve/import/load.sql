\set ON_ERROR_STOP on
-- 2026-09-25 Site Host: accepts an optional trailing `expanded_latin` CSV column (04_expanded_latin.sql).
-- Requires 04_expanded_latin.sql applied and a superuser / pg_read_server_files role (same as server-side COPY).
BEGIN;

-- baptisms.csv -> lank.stg_baptisms (KB 1000)
SELECT lank.assert_book_loadable(lank.book_id_for($$KB 1000$$));
DROP TABLE IF EXISTS tmp_load_0;
CREATE TEMP TABLE tmp_load_0 (
  scan text, page text, entry integer, baptism_date text, birth_date text, child_name text, child_sex text, father text, paternal_grandfather text, paternal_grandmother text, mother text, maternal_grandfather text, maternal_grandmother text, godfather text, godmother text, parents_married text, parents_residence text, priest text, transcription_latin text, translation_de text, translation_en text, notes text, expanded_latin text
);
-- Optional trailing CSV column expanded_latin: detected from the header row.
-- Present -> COPY it and upsert it (CSV is authoritative, blank clears).
-- Absent  -> COPY without it; existing expanded_latin is left untouched (new rows NULL).
DO $el$
DECLARE
  head bytea := pg_read_binary_file('/tmp/lank-import/baptisms.csv', 0, 65536);
  hdr  text;
  has_el boolean;
BEGIN
  IF position('\x0a'::bytea IN head) > 0 THEN
    head := substring(head FROM 1 FOR position('\x0a'::bytea IN head) - 1);
  END IF;
  hdr := replace(replace(convert_from(head, 'UTF8'), E'\r', ''), U&'\FEFF', '');
  has_el := lower(btrim(regexp_replace(hdr, '^.*,', ''), ' "')) = 'expanded_latin';
  CREATE TEMP TABLE IF NOT EXISTS tmp_load_flags (k int PRIMARY KEY, has_el boolean NOT NULL);
  INSERT INTO tmp_load_flags VALUES (0, has_el) ON CONFLICT (k) DO UPDATE SET has_el = EXCLUDED.has_el;
  EXECUTE format('COPY tmp_load_0 (scan, page, entry, baptism_date, birth_date, child_name, child_sex, father, paternal_grandfather, paternal_grandmother, mother, maternal_grandfather, maternal_grandmother, godfather, godmother, parents_married, parents_residence, priest, transcription_latin, translation_de, translation_en, notes%s) FROM %L WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')',
                 CASE WHEN has_el THEN ', expanded_latin' ELSE '' END, '/tmp/lank-import/baptisms.csv');
  RAISE NOTICE 'tmp_load_0: expanded_latin column %', CASE WHEN has_el THEN 'present' ELSE 'absent' END;
END
$el$;
INSERT INTO lank.stg_baptisms (book_id, scan, page, entry, baptism_date, birth_date, child_name, child_sex, father, paternal_grandfather, paternal_grandmother, mother, maternal_grandfather, maternal_grandmother, godfather, godmother, parents_married, parents_residence, priest, transcription_latin, translation_de, translation_en, notes, expanded_latin)
SELECT lank.book_id_for($$KB 1000$$), scan, COALESCE(page, ''), entry, baptism_date, birth_date, child_name, child_sex, father, paternal_grandfather, paternal_grandmother, mother, maternal_grandfather, maternal_grandmother, godfather, godmother, parents_married, parents_residence, priest, transcription_latin, translation_de, translation_en, notes, expanded_latin
FROM tmp_load_0
WHERE entry IS NOT NULL AND scan IS NOT NULL
ON CONFLICT (book_id, scan, page, entry) DO UPDATE SET
    baptism_date = EXCLUDED.baptism_date,
    birth_date = EXCLUDED.birth_date,
    child_name = EXCLUDED.child_name,
    child_sex = EXCLUDED.child_sex,
    father = EXCLUDED.father,
    paternal_grandfather = EXCLUDED.paternal_grandfather,
    paternal_grandmother = EXCLUDED.paternal_grandmother,
    mother = EXCLUDED.mother,
    maternal_grandfather = EXCLUDED.maternal_grandfather,
    maternal_grandmother = EXCLUDED.maternal_grandmother,
    godfather = EXCLUDED.godfather,
    godmother = EXCLUDED.godmother,
    parents_married = EXCLUDED.parents_married,
    parents_residence = EXCLUDED.parents_residence,
    priest = EXCLUDED.priest,
    transcription_latin = EXCLUDED.transcription_latin,
    translation_de = EXCLUDED.translation_de,
    translation_en = EXCLUDED.translation_en,
    notes = EXCLUDED.notes,
    expanded_latin = CASE WHEN (SELECT has_el FROM tmp_load_flags WHERE k = 0)
                          THEN EXCLUDED.expanded_latin ELSE stg_baptisms.expanded_latin END,
    updated_at = now();


-- marriages.csv -> lank.stg_marriages (KB 999_3)
SELECT lank.assert_book_loadable(lank.book_id_for($$KB 999_3$$));
DROP TABLE IF EXISTS tmp_load_1;
CREATE TEMP TABLE tmp_load_1 (
  scan text, page text, entry integer, marriage_date text, groom_name text, groom_status text, groom_residence text, groom_father text, groom_mother text, bride_name text, bride_status text, bride_residence text, bride_father text, bride_mother text, witness_1 text, witness_2 text, witnesses_other text, banns_or_dispensation text, priest text, marriage_place text, transcription_latin text, translation_de text, translation_en text, notes text, expanded_latin text
);
-- Optional trailing CSV column expanded_latin: detected from the header row.
-- Present -> COPY it and upsert it (CSV is authoritative, blank clears).
-- Absent  -> COPY without it; existing expanded_latin is left untouched (new rows NULL).
DO $el$
DECLARE
  head bytea := pg_read_binary_file('/tmp/lank-import/marriages.csv', 0, 65536);
  hdr  text;
  has_el boolean;
BEGIN
  IF position('\x0a'::bytea IN head) > 0 THEN
    head := substring(head FROM 1 FOR position('\x0a'::bytea IN head) - 1);
  END IF;
  hdr := replace(replace(convert_from(head, 'UTF8'), E'\r', ''), U&'\FEFF', '');
  has_el := lower(btrim(regexp_replace(hdr, '^.*,', ''), ' "')) = 'expanded_latin';
  CREATE TEMP TABLE IF NOT EXISTS tmp_load_flags (k int PRIMARY KEY, has_el boolean NOT NULL);
  INSERT INTO tmp_load_flags VALUES (1, has_el) ON CONFLICT (k) DO UPDATE SET has_el = EXCLUDED.has_el;
  EXECUTE format('COPY tmp_load_1 (scan, page, entry, marriage_date, groom_name, groom_status, groom_residence, groom_father, groom_mother, bride_name, bride_status, bride_residence, bride_father, bride_mother, witness_1, witness_2, witnesses_other, banns_or_dispensation, priest, marriage_place, transcription_latin, translation_de, translation_en, notes%s) FROM %L WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')',
                 CASE WHEN has_el THEN ', expanded_latin' ELSE '' END, '/tmp/lank-import/marriages.csv');
  RAISE NOTICE 'tmp_load_1: expanded_latin column %', CASE WHEN has_el THEN 'present' ELSE 'absent' END;
END
$el$;
INSERT INTO lank.stg_marriages (book_id, scan, page, entry, marriage_date, groom_name, groom_status, groom_residence, groom_father, groom_mother, bride_name, bride_status, bride_residence, bride_father, bride_mother, witness_1, witness_2, witnesses_other, banns_or_dispensation, priest, marriage_place, transcription_latin, translation_de, translation_en, notes, expanded_latin)
SELECT lank.book_id_for($$KB 999_3$$), scan, COALESCE(page, ''), entry, marriage_date, groom_name, groom_status, groom_residence, groom_father, groom_mother, bride_name, bride_status, bride_residence, bride_father, bride_mother, witness_1, witness_2, witnesses_other, banns_or_dispensation, priest, marriage_place, transcription_latin, translation_de, translation_en, notes, expanded_latin
FROM tmp_load_1
WHERE entry IS NOT NULL AND scan IS NOT NULL
ON CONFLICT (book_id, scan, page, entry) DO UPDATE SET
    marriage_date = EXCLUDED.marriage_date,
    groom_name = EXCLUDED.groom_name,
    groom_status = EXCLUDED.groom_status,
    groom_residence = EXCLUDED.groom_residence,
    groom_father = EXCLUDED.groom_father,
    groom_mother = EXCLUDED.groom_mother,
    bride_name = EXCLUDED.bride_name,
    bride_status = EXCLUDED.bride_status,
    bride_residence = EXCLUDED.bride_residence,
    bride_father = EXCLUDED.bride_father,
    bride_mother = EXCLUDED.bride_mother,
    witness_1 = EXCLUDED.witness_1,
    witness_2 = EXCLUDED.witness_2,
    witnesses_other = EXCLUDED.witnesses_other,
    banns_or_dispensation = EXCLUDED.banns_or_dispensation,
    priest = EXCLUDED.priest,
    marriage_place = EXCLUDED.marriage_place,
    transcription_latin = EXCLUDED.transcription_latin,
    translation_de = EXCLUDED.translation_de,
    translation_en = EXCLUDED.translation_en,
    notes = EXCLUDED.notes,
    expanded_latin = CASE WHEN (SELECT has_el FROM tmp_load_flags WHERE k = 1)
                          THEN EXCLUDED.expanded_latin ELSE stg_marriages.expanded_latin END,
    updated_at = now();


-- deaths.csv -> lank.stg_deaths (KB 999_4)
SELECT lank.assert_book_loadable(lank.book_id_for($$KB 999_4$$));
DROP TABLE IF EXISTS tmp_load_2;
CREATE TEMP TABLE tmp_load_2 (
  scan text, page text, entry integer, death_date text, burial_date text, deceased_name text, deceased_sex text, age text, status text, spouse_or_parents text, residence text, cause text, priest text, burial_place text, transcription_latin text, translation_de text, translation_en text, notes text, expanded_latin text
);
-- Optional trailing CSV column expanded_latin: detected from the header row.
-- Present -> COPY it and upsert it (CSV is authoritative, blank clears).
-- Absent  -> COPY without it; existing expanded_latin is left untouched (new rows NULL).
DO $el$
DECLARE
  head bytea := pg_read_binary_file('/tmp/lank-import/deaths.csv', 0, 65536);
  hdr  text;
  has_el boolean;
BEGIN
  IF position('\x0a'::bytea IN head) > 0 THEN
    head := substring(head FROM 1 FOR position('\x0a'::bytea IN head) - 1);
  END IF;
  hdr := replace(replace(convert_from(head, 'UTF8'), E'\r', ''), U&'\FEFF', '');
  has_el := lower(btrim(regexp_replace(hdr, '^.*,', ''), ' "')) = 'expanded_latin';
  CREATE TEMP TABLE IF NOT EXISTS tmp_load_flags (k int PRIMARY KEY, has_el boolean NOT NULL);
  INSERT INTO tmp_load_flags VALUES (2, has_el) ON CONFLICT (k) DO UPDATE SET has_el = EXCLUDED.has_el;
  EXECUTE format('COPY tmp_load_2 (scan, page, entry, death_date, burial_date, deceased_name, deceased_sex, age, status, spouse_or_parents, residence, cause, priest, burial_place, transcription_latin, translation_de, translation_en, notes%s) FROM %L WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')',
                 CASE WHEN has_el THEN ', expanded_latin' ELSE '' END, '/tmp/lank-import/deaths.csv');
  RAISE NOTICE 'tmp_load_2: expanded_latin column %', CASE WHEN has_el THEN 'present' ELSE 'absent' END;
END
$el$;
INSERT INTO lank.stg_deaths (book_id, scan, page, entry, death_date, burial_date, deceased_name, deceased_sex, age, status, spouse_or_parents, residence, cause, priest, burial_place, transcription_latin, translation_de, translation_en, notes, expanded_latin)
SELECT lank.book_id_for($$KB 999_4$$), scan, COALESCE(page, ''), entry, death_date, burial_date, deceased_name, deceased_sex, age, status, spouse_or_parents, residence, cause, priest, burial_place, transcription_latin, translation_de, translation_en, notes, expanded_latin
FROM tmp_load_2
WHERE entry IS NOT NULL AND scan IS NOT NULL
ON CONFLICT (book_id, scan, page, entry) DO UPDATE SET
    death_date = EXCLUDED.death_date,
    burial_date = EXCLUDED.burial_date,
    deceased_name = EXCLUDED.deceased_name,
    deceased_sex = EXCLUDED.deceased_sex,
    age = EXCLUDED.age,
    status = EXCLUDED.status,
    spouse_or_parents = EXCLUDED.spouse_or_parents,
    residence = EXCLUDED.residence,
    cause = EXCLUDED.cause,
    priest = EXCLUDED.priest,
    burial_place = EXCLUDED.burial_place,
    transcription_latin = EXCLUDED.transcription_latin,
    translation_de = EXCLUDED.translation_de,
    translation_en = EXCLUDED.translation_en,
    notes = EXCLUDED.notes,
    expanded_latin = CASE WHEN (SELECT has_el FROM tmp_load_flags WHERE k = 2)
                          THEN EXCLUDED.expanded_latin ELSE stg_deaths.expanded_latin END,
    updated_at = now();


-- communion.csv -> lank.stg_communion (KB 1052_5)
SELECT lank.assert_book_loadable(lank.book_id_for($$KB 1052_5$$));
DROP TABLE IF EXISTS tmp_load_3;
CREATE TEMP TABLE tmp_load_3 (
  scan text, page text, entry integer, communion_date text, communicant_name text, communicant_sex text, age text, father text, mother text, residence text, priest text, transcription_latin text, translation_de text, translation_en text, notes text, expanded_latin text
);
-- Optional trailing CSV column expanded_latin: detected from the header row.
-- Present -> COPY it and upsert it (CSV is authoritative, blank clears).
-- Absent  -> COPY without it; existing expanded_latin is left untouched (new rows NULL).
DO $el$
DECLARE
  head bytea := pg_read_binary_file('/tmp/lank-import/communion.csv', 0, 65536);
  hdr  text;
  has_el boolean;
BEGIN
  IF position('\x0a'::bytea IN head) > 0 THEN
    head := substring(head FROM 1 FOR position('\x0a'::bytea IN head) - 1);
  END IF;
  hdr := replace(replace(convert_from(head, 'UTF8'), E'\r', ''), U&'\FEFF', '');
  has_el := lower(btrim(regexp_replace(hdr, '^.*,', ''), ' "')) = 'expanded_latin';
  CREATE TEMP TABLE IF NOT EXISTS tmp_load_flags (k int PRIMARY KEY, has_el boolean NOT NULL);
  INSERT INTO tmp_load_flags VALUES (3, has_el) ON CONFLICT (k) DO UPDATE SET has_el = EXCLUDED.has_el;
  EXECUTE format('COPY tmp_load_3 (scan, page, entry, communion_date, communicant_name, communicant_sex, age, father, mother, residence, priest, transcription_latin, translation_de, translation_en, notes%s) FROM %L WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')',
                 CASE WHEN has_el THEN ', expanded_latin' ELSE '' END, '/tmp/lank-import/communion.csv');
  RAISE NOTICE 'tmp_load_3: expanded_latin column %', CASE WHEN has_el THEN 'present' ELSE 'absent' END;
END
$el$;
INSERT INTO lank.stg_communion (book_id, scan, page, entry, communion_date, communicant_name, communicant_sex, age, father, mother, residence, priest, transcription_latin, translation_de, translation_en, notes, expanded_latin)
SELECT lank.book_id_for($$KB 1052_5$$), scan, COALESCE(page, ''), entry, communion_date, communicant_name, communicant_sex, age, father, mother, residence, priest, transcription_latin, translation_de, translation_en, notes, expanded_latin
FROM tmp_load_3
WHERE entry IS NOT NULL AND scan IS NOT NULL
ON CONFLICT (book_id, scan, page, entry) DO UPDATE SET
    communion_date = EXCLUDED.communion_date,
    communicant_name = EXCLUDED.communicant_name,
    communicant_sex = EXCLUDED.communicant_sex,
    age = EXCLUDED.age,
    father = EXCLUDED.father,
    mother = EXCLUDED.mother,
    residence = EXCLUDED.residence,
    priest = EXCLUDED.priest,
    transcription_latin = EXCLUDED.transcription_latin,
    translation_de = EXCLUDED.translation_de,
    translation_en = EXCLUDED.translation_en,
    notes = EXCLUDED.notes,
    expanded_latin = CASE WHEN (SELECT has_el FROM tmp_load_flags WHERE k = 3)
                          THEN EXCLUDED.expanded_latin ELSE stg_communion.expanded_latin END,
    updated_at = now();


-- confraternity.csv -> lank.stg_confraternity_enrollment (KB 1052_9)
SELECT lank.assert_book_loadable(lank.book_id_for($$KB 1052_9$$));
DROP TABLE IF EXISTS tmp_load_4;
CREATE TEMP TABLE tmp_load_4 (
  scan text, page text, entry integer, list_date text, feast_or_occasion text, confraternity_name text, person_name text, person_sex text, residence_ex text, status_or_role text, priest_or_scribe text, transcription text, translation_de text, translation_en text, notes text, expanded_latin text
);
-- Optional trailing CSV column expanded_latin: detected from the header row.
-- Present -> COPY it and upsert it (CSV is authoritative, blank clears).
-- Absent  -> COPY without it; existing expanded_latin is left untouched (new rows NULL).
DO $el$
DECLARE
  head bytea := pg_read_binary_file('/tmp/lank-import/confraternity.csv', 0, 65536);
  hdr  text;
  has_el boolean;
BEGIN
  IF position('\x0a'::bytea IN head) > 0 THEN
    head := substring(head FROM 1 FOR position('\x0a'::bytea IN head) - 1);
  END IF;
  hdr := replace(replace(convert_from(head, 'UTF8'), E'\r', ''), U&'\FEFF', '');
  has_el := lower(btrim(regexp_replace(hdr, '^.*,', ''), ' "')) = 'expanded_latin';
  CREATE TEMP TABLE IF NOT EXISTS tmp_load_flags (k int PRIMARY KEY, has_el boolean NOT NULL);
  INSERT INTO tmp_load_flags VALUES (4, has_el) ON CONFLICT (k) DO UPDATE SET has_el = EXCLUDED.has_el;
  EXECUTE format('COPY tmp_load_4 (scan, page, entry, list_date, feast_or_occasion, confraternity_name, person_name, person_sex, residence_ex, status_or_role, priest_or_scribe, transcription, translation_de, translation_en, notes%s) FROM %L WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')',
                 CASE WHEN has_el THEN ', expanded_latin' ELSE '' END, '/tmp/lank-import/confraternity.csv');
  RAISE NOTICE 'tmp_load_4: expanded_latin column %', CASE WHEN has_el THEN 'present' ELSE 'absent' END;
END
$el$;
INSERT INTO lank.stg_confraternity_enrollment (book_id, scan, page, entry, list_date, feast_or_occasion, confraternity_name, person_name, person_sex, residence_ex, status_or_role, priest_or_scribe, transcription, translation_de, translation_en, notes, expanded_latin)
SELECT lank.book_id_for($$KB 1052_9$$), scan, COALESCE(page, ''), entry, list_date, feast_or_occasion, confraternity_name, person_name, person_sex, residence_ex, status_or_role, priest_or_scribe, transcription, translation_de, translation_en, notes, expanded_latin
FROM tmp_load_4
WHERE entry IS NOT NULL AND scan IS NOT NULL
ON CONFLICT (book_id, scan, page, entry) DO UPDATE SET
    list_date = EXCLUDED.list_date,
    feast_or_occasion = EXCLUDED.feast_or_occasion,
    confraternity_name = EXCLUDED.confraternity_name,
    person_name = EXCLUDED.person_name,
    person_sex = EXCLUDED.person_sex,
    residence_ex = EXCLUDED.residence_ex,
    status_or_role = EXCLUDED.status_or_role,
    priest_or_scribe = EXCLUDED.priest_or_scribe,
    transcription = EXCLUDED.transcription,
    translation_de = EXCLUDED.translation_de,
    translation_en = EXCLUDED.translation_en,
    notes = EXCLUDED.notes,
    expanded_latin = CASE WHEN (SELECT has_el FROM tmp_load_flags WHERE k = 4)
                          THEN EXCLUDED.expanded_latin ELSE stg_confraternity_enrollment.expanded_latin END,
    updated_at = now();


-- confraternity_pilot.csv -> lank.stg_confraternity_enrollment (KB 1052_9)
SELECT lank.assert_book_loadable(lank.book_id_for($$KB 1052_9$$));
DROP TABLE IF EXISTS tmp_load_5;
CREATE TEMP TABLE tmp_load_5 (
  scan text, page text, entry integer, list_date text, feast_or_occasion text, confraternity_name text, person_name text, person_sex text, residence_ex text, status_or_role text, priest_or_scribe text, transcription text, translation_de text, translation_en text, notes text, expanded_latin text
);
-- Optional trailing CSV column expanded_latin: detected from the header row.
-- Present -> COPY it and upsert it (CSV is authoritative, blank clears).
-- Absent  -> COPY without it; existing expanded_latin is left untouched (new rows NULL).
DO $el$
DECLARE
  head bytea := pg_read_binary_file('/tmp/lank-import/confraternity_pilot.csv', 0, 65536);
  hdr  text;
  has_el boolean;
BEGIN
  IF position('\x0a'::bytea IN head) > 0 THEN
    head := substring(head FROM 1 FOR position('\x0a'::bytea IN head) - 1);
  END IF;
  hdr := replace(replace(convert_from(head, 'UTF8'), E'\r', ''), U&'\FEFF', '');
  has_el := lower(btrim(regexp_replace(hdr, '^.*,', ''), ' "')) = 'expanded_latin';
  CREATE TEMP TABLE IF NOT EXISTS tmp_load_flags (k int PRIMARY KEY, has_el boolean NOT NULL);
  INSERT INTO tmp_load_flags VALUES (5, has_el) ON CONFLICT (k) DO UPDATE SET has_el = EXCLUDED.has_el;
  EXECUTE format('COPY tmp_load_5 (scan, page, entry, list_date, feast_or_occasion, confraternity_name, person_name, person_sex, residence_ex, status_or_role, priest_or_scribe, transcription, translation_de, translation_en, notes%s) FROM %L WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')',
                 CASE WHEN has_el THEN ', expanded_latin' ELSE '' END, '/tmp/lank-import/confraternity_pilot.csv');
  RAISE NOTICE 'tmp_load_5: expanded_latin column %', CASE WHEN has_el THEN 'present' ELSE 'absent' END;
END
$el$;
INSERT INTO lank.stg_confraternity_enrollment (book_id, scan, page, entry, list_date, feast_or_occasion, confraternity_name, person_name, person_sex, residence_ex, status_or_role, priest_or_scribe, transcription, translation_de, translation_en, notes, expanded_latin)
SELECT lank.book_id_for($$KB 1052_9$$), scan, COALESCE(page, ''), entry, list_date, feast_or_occasion, confraternity_name, person_name, person_sex, residence_ex, status_or_role, priest_or_scribe, transcription, translation_de, translation_en, notes, expanded_latin
FROM tmp_load_5
WHERE entry IS NOT NULL AND scan IS NOT NULL
ON CONFLICT (book_id, scan, page, entry) DO UPDATE SET
    list_date = EXCLUDED.list_date,
    feast_or_occasion = EXCLUDED.feast_or_occasion,
    confraternity_name = EXCLUDED.confraternity_name,
    person_name = EXCLUDED.person_name,
    person_sex = EXCLUDED.person_sex,
    residence_ex = EXCLUDED.residence_ex,
    status_or_role = EXCLUDED.status_or_role,
    priest_or_scribe = EXCLUDED.priest_or_scribe,
    transcription = EXCLUDED.transcription,
    translation_de = EXCLUDED.translation_de,
    translation_en = EXCLUDED.translation_en,
    notes = EXCLUDED.notes,
    expanded_latin = CASE WHEN (SELECT has_el FROM tmp_load_flags WHERE k = 5)
                          THEN EXCLUDED.expanded_latin ELSE stg_confraternity_enrollment.expanded_latin END,
    updated_at = now();


-- yearly_roll.csv -> lank.stg_yearly_name_roll (KB 1052_9)
SELECT lank.assert_book_loadable(lank.book_id_for($$KB 1052_9$$));
DROP TABLE IF EXISTS tmp_load_6;
CREATE TEMP TABLE tmp_load_6 (
  scan text, page text, entry integer, year text, list_date text, row_number text, person_name text, village_or_place text, ditto_note text, status_annotation text, section_or_heading text, transcription text, translation_de text, translation_en text, notes text, expanded_latin text
);
-- Optional trailing CSV column expanded_latin: detected from the header row.
-- Present -> COPY it and upsert it (CSV is authoritative, blank clears).
-- Absent  -> COPY without it; existing expanded_latin is left untouched (new rows NULL).
DO $el$
DECLARE
  head bytea := pg_read_binary_file('/tmp/lank-import/yearly_roll.csv', 0, 65536);
  hdr  text;
  has_el boolean;
BEGIN
  IF position('\x0a'::bytea IN head) > 0 THEN
    head := substring(head FROM 1 FOR position('\x0a'::bytea IN head) - 1);
  END IF;
  hdr := replace(replace(convert_from(head, 'UTF8'), E'\r', ''), U&'\FEFF', '');
  has_el := lower(btrim(regexp_replace(hdr, '^.*,', ''), ' "')) = 'expanded_latin';
  CREATE TEMP TABLE IF NOT EXISTS tmp_load_flags (k int PRIMARY KEY, has_el boolean NOT NULL);
  INSERT INTO tmp_load_flags VALUES (6, has_el) ON CONFLICT (k) DO UPDATE SET has_el = EXCLUDED.has_el;
  EXECUTE format('COPY tmp_load_6 (scan, page, entry, year, list_date, row_number, person_name, village_or_place, ditto_note, status_annotation, section_or_heading, transcription, translation_de, translation_en, notes%s) FROM %L WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')',
                 CASE WHEN has_el THEN ', expanded_latin' ELSE '' END, '/tmp/lank-import/yearly_roll.csv');
  RAISE NOTICE 'tmp_load_6: expanded_latin column %', CASE WHEN has_el THEN 'present' ELSE 'absent' END;
END
$el$;
INSERT INTO lank.stg_yearly_name_roll (book_id, scan, page, entry, year, list_date, row_number, person_name, village_or_place, ditto_note, status_annotation, section_or_heading, transcription, translation_de, translation_en, notes, expanded_latin)
SELECT lank.book_id_for($$KB 1052_9$$), scan, COALESCE(page, ''), entry, year, list_date, row_number, person_name, village_or_place, ditto_note, status_annotation, section_or_heading, transcription, translation_de, translation_en, notes, expanded_latin
FROM tmp_load_6
WHERE entry IS NOT NULL AND scan IS NOT NULL
ON CONFLICT (book_id, scan, page, entry) DO UPDATE SET
    year = EXCLUDED.year,
    list_date = EXCLUDED.list_date,
    row_number = EXCLUDED.row_number,
    person_name = EXCLUDED.person_name,
    village_or_place = EXCLUDED.village_or_place,
    ditto_note = EXCLUDED.ditto_note,
    status_annotation = EXCLUDED.status_annotation,
    section_or_heading = EXCLUDED.section_or_heading,
    transcription = EXCLUDED.transcription,
    translation_de = EXCLUDED.translation_de,
    translation_en = EXCLUDED.translation_en,
    notes = EXCLUDED.notes,
    expanded_latin = CASE WHEN (SELECT has_el FROM tmp_load_flags WHERE k = 6)
                          THEN EXCLUDED.expanded_latin ELSE stg_yearly_name_roll.expanded_latin END,
    updated_at = now();


-- yearly_roll_pilot.csv -> lank.stg_yearly_name_roll (KB 1052_9)
SELECT lank.assert_book_loadable(lank.book_id_for($$KB 1052_9$$));
DROP TABLE IF EXISTS tmp_load_7;
CREATE TEMP TABLE tmp_load_7 (
  scan text, page text, entry integer, year text, list_date text, row_number text, person_name text, village_or_place text, ditto_note text, status_annotation text, section_or_heading text, transcription text, translation_de text, translation_en text, notes text, expanded_latin text
);
-- Optional trailing CSV column expanded_latin: detected from the header row.
-- Present -> COPY it and upsert it (CSV is authoritative, blank clears).
-- Absent  -> COPY without it; existing expanded_latin is left untouched (new rows NULL).
DO $el$
DECLARE
  head bytea := pg_read_binary_file('/tmp/lank-import/yearly_roll_pilot.csv', 0, 65536);
  hdr  text;
  has_el boolean;
BEGIN
  IF position('\x0a'::bytea IN head) > 0 THEN
    head := substring(head FROM 1 FOR position('\x0a'::bytea IN head) - 1);
  END IF;
  hdr := replace(replace(convert_from(head, 'UTF8'), E'\r', ''), U&'\FEFF', '');
  has_el := lower(btrim(regexp_replace(hdr, '^.*,', ''), ' "')) = 'expanded_latin';
  CREATE TEMP TABLE IF NOT EXISTS tmp_load_flags (k int PRIMARY KEY, has_el boolean NOT NULL);
  INSERT INTO tmp_load_flags VALUES (7, has_el) ON CONFLICT (k) DO UPDATE SET has_el = EXCLUDED.has_el;
  EXECUTE format('COPY tmp_load_7 (scan, page, entry, year, list_date, row_number, person_name, village_or_place, ditto_note, status_annotation, section_or_heading, transcription, translation_de, translation_en, notes%s) FROM %L WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')',
                 CASE WHEN has_el THEN ', expanded_latin' ELSE '' END, '/tmp/lank-import/yearly_roll_pilot.csv');
  RAISE NOTICE 'tmp_load_7: expanded_latin column %', CASE WHEN has_el THEN 'present' ELSE 'absent' END;
END
$el$;
INSERT INTO lank.stg_yearly_name_roll (book_id, scan, page, entry, year, list_date, row_number, person_name, village_or_place, ditto_note, status_annotation, section_or_heading, transcription, translation_de, translation_en, notes, expanded_latin)
SELECT lank.book_id_for($$KB 1052_9$$), scan, COALESCE(page, ''), entry, year, list_date, row_number, person_name, village_or_place, ditto_note, status_annotation, section_or_heading, transcription, translation_de, translation_en, notes, expanded_latin
FROM tmp_load_7
WHERE entry IS NOT NULL AND scan IS NOT NULL
ON CONFLICT (book_id, scan, page, entry) DO UPDATE SET
    year = EXCLUDED.year,
    list_date = EXCLUDED.list_date,
    row_number = EXCLUDED.row_number,
    person_name = EXCLUDED.person_name,
    village_or_place = EXCLUDED.village_or_place,
    ditto_note = EXCLUDED.ditto_note,
    status_annotation = EXCLUDED.status_annotation,
    section_or_heading = EXCLUDED.section_or_heading,
    transcription = EXCLUDED.transcription,
    translation_de = EXCLUDED.translation_de,
    translation_en = EXCLUDED.translation_en,
    notes = EXCLUDED.notes,
    expanded_latin = CASE WHEN (SELECT has_el FROM tmp_load_flags WHERE k = 7)
                          THEN EXCLUDED.expanded_latin ELSE stg_yearly_name_roll.expanded_latin END,
    updated_at = now();


-- ledger_pilot.csv -> lank.stg_ledger_admin (KB 1052_9)
SELECT lank.assert_book_loadable(lank.book_id_for($$KB 1052_9$$));
DROP TABLE IF EXISTS tmp_load_8;
CREATE TEMP TABLE tmp_load_8 (
  scan text, page text, entry integer, entry_date text, ledger_heading text, person_name text, residence text, amount text, currency_or_unit text, purpose text, related_person text, transcription text, translation_de text, translation_en text, notes text, expanded_latin text
);
-- Optional trailing CSV column expanded_latin: detected from the header row.
-- Present -> COPY it and upsert it (CSV is authoritative, blank clears).
-- Absent  -> COPY without it; existing expanded_latin is left untouched (new rows NULL).
DO $el$
DECLARE
  head bytea := pg_read_binary_file('/tmp/lank-import/ledger_pilot.csv', 0, 65536);
  hdr  text;
  has_el boolean;
BEGIN
  IF position('\x0a'::bytea IN head) > 0 THEN
    head := substring(head FROM 1 FOR position('\x0a'::bytea IN head) - 1);
  END IF;
  hdr := replace(replace(convert_from(head, 'UTF8'), E'\r', ''), U&'\FEFF', '');
  has_el := lower(btrim(regexp_replace(hdr, '^.*,', ''), ' "')) = 'expanded_latin';
  CREATE TEMP TABLE IF NOT EXISTS tmp_load_flags (k int PRIMARY KEY, has_el boolean NOT NULL);
  INSERT INTO tmp_load_flags VALUES (8, has_el) ON CONFLICT (k) DO UPDATE SET has_el = EXCLUDED.has_el;
  EXECUTE format('COPY tmp_load_8 (scan, page, entry, entry_date, ledger_heading, person_name, residence, amount, currency_or_unit, purpose, related_person, transcription, translation_de, translation_en, notes%s) FROM %L WITH (FORMAT csv, HEADER true, ENCODING ''UTF8'')',
                 CASE WHEN has_el THEN ', expanded_latin' ELSE '' END, '/tmp/lank-import/ledger_pilot.csv');
  RAISE NOTICE 'tmp_load_8: expanded_latin column %', CASE WHEN has_el THEN 'present' ELSE 'absent' END;
END
$el$;
INSERT INTO lank.stg_ledger_admin (book_id, scan, page, entry, entry_date, ledger_heading, person_name, residence, amount, currency_or_unit, purpose, related_person, transcription, translation_de, translation_en, notes, expanded_latin)
SELECT lank.book_id_for($$KB 1052_9$$), scan, COALESCE(page, ''), entry, entry_date, ledger_heading, person_name, residence, amount, currency_or_unit, purpose, related_person, transcription, translation_de, translation_en, notes, expanded_latin
FROM tmp_load_8
WHERE entry IS NOT NULL AND scan IS NOT NULL
ON CONFLICT (book_id, scan, page, entry) DO UPDATE SET
    entry_date = EXCLUDED.entry_date,
    ledger_heading = EXCLUDED.ledger_heading,
    person_name = EXCLUDED.person_name,
    residence = EXCLUDED.residence,
    amount = EXCLUDED.amount,
    currency_or_unit = EXCLUDED.currency_or_unit,
    purpose = EXCLUDED.purpose,
    related_person = EXCLUDED.related_person,
    transcription = EXCLUDED.transcription,
    translation_de = EXCLUDED.translation_de,
    translation_en = EXCLUDED.translation_en,
    notes = EXCLUDED.notes,
    expanded_latin = CASE WHEN (SELECT has_el FROM tmp_load_flags WHERE k = 8)
                          THEN EXCLUDED.expanded_latin ELSE stg_ledger_admin.expanded_latin END,
    updated_at = now();


SELECT 'stg_baptisms' AS t, b.archival_id, count(*)::int AS n
FROM lank.stg_baptisms s JOIN lank.books b ON b.id=s.book_id WHERE s.deleted_at IS NULL GROUP BY 1,2
UNION ALL
SELECT 'stg_marriages', b.archival_id, count(*)::int FROM lank.stg_marriages s JOIN lank.books b ON b.id=s.book_id WHERE s.deleted_at IS NULL GROUP BY 1,2
UNION ALL
SELECT 'stg_deaths', b.archival_id, count(*)::int FROM lank.stg_deaths s JOIN lank.books b ON b.id=s.book_id WHERE s.deleted_at IS NULL GROUP BY 1,2
UNION ALL
SELECT 'stg_communion', b.archival_id, count(*)::int FROM lank.stg_communion s JOIN lank.books b ON b.id=s.book_id WHERE s.deleted_at IS NULL GROUP BY 1,2
UNION ALL
SELECT 'stg_confraternity_enrollment', b.archival_id, count(*)::int FROM lank.stg_confraternity_enrollment s JOIN lank.books b ON b.id=s.book_id WHERE s.deleted_at IS NULL GROUP BY 1,2
UNION ALL
SELECT 'stg_yearly_name_roll', b.archival_id, count(*)::int FROM lank.stg_yearly_name_roll s JOIN lank.books b ON b.id=s.book_id WHERE s.deleted_at IS NULL GROUP BY 1,2
UNION ALL
SELECT 'stg_ledger_admin', b.archival_id, count(*)::int FROM lank.stg_ledger_admin s JOIN lank.books b ON b.id=s.book_id WHERE s.deleted_at IS NULL GROUP BY 1,2
ORDER BY 1,2;
COMMIT;
