# Stage B — shared fields (opr-shared-defs v1.0.0)

**Status:** DRAFT 2026-09-29 (Schema Steward). **Pending Stephen approval.** Nothing here is locked.
**Definitions:** [`opr_shared_defs.schema.json`](./opr_shared_defs.schema.json) is the single source of truth. Each record schema carries an **identical copy** under its own `$defs`, so every schema still validates standalone (`jsonschema -i rec.json baptism_record.schema.json`).
After editing the shared file, run `python3 /workspace/lank-schema/tools/sync_shared_defs.py`, then copy to `extraction/`. `--check` reports any drift in the schemas or the mirror.
**Validate:** `/workspace/.venv-js/bin/python /workspace/lank-schema/tools/validate_stage_b.py <records…>` picks the schema from `entry_kind`.

Every new field is **optional and nullable**, so records written before the bump stay valid.

| Schema | Before | After | Lock state |
|--------|--------|-------|-----------|
| `opr-baptism-record` | 1.0.3 (locked) | **1.1.0** additive | bump **pending Stephen approval** |
| `opr-death-record` | 1.0.1 (draft) | **1.1.0** additive | draft |
| `opr-communion-record` | 1.0.2 (locked) | **1.1.0** additive | bump **pending Stephen approval** |
| `opr-marriage-record` | — | **1.0.0** | draft ([STAGE_B_MARRIAGE.md](./STAGE_B_MARRIAGE.md)) |

`schema_version` now accepts `1.0.x` and `1.1.x` in baptism, death and communion. The top-level `version` key was behind `$id` in all three schemas (it said 1.0.2 / 1.0.0 / 1.0.1). It is now aligned to 1.1.0.

## The definitions

| `$defs` name | Shape | Used for |
|------|-------|----------|
| `source_citation` | `{matricula_url, citation, archive, matricula_collection, parish, book_signature, image_number, image_label, page, accessed, notes}`, all nullable | (a) where the entry can be seen |
| `place_identification` | `{place_as_written*, identified_name, place_id, match_confidence, as_of_date, basis, notes}` | (b) and (e): place as written vs identified place |
| `period_jurisdiction` | `{source* gazetteer\|editorial, place_id, as_of_date, editorial_levels[], basis, notes}` | (c) territory / Amt / diocese at the event date |
| `alias`, `person_aliases` | `{form*, marker*, marker_as_written, form_as_written, notes}`; map person-field → [alias] | (d) dictus / genannt / vulgo / condictus |
| `vital_status` | `{status* deceased\|living\|uncertain, as_written, notes}` | (h) defunctus / Ffti / obitorum / selig / quondam |
| `previous_spouse` | `{name*, name_as_written, vital_status, residence_identified, aliases, notes}` | (g) widowed bride/groom, deceased's earlier spouse |
| `person_with_residence` | `{name*, residence_identified, aliases, notes}` | (e) extra named witnesses beyond the two slots |

`*` = required inside the object.

### (a) Source citation: `source_citation`, highest priority
- `matricula_url` is the **canonical viewer permalink to the image page** (`https://data.matricula-online.eu/…/<book>/?pg=N`), never the hosted-images JPEG. The schema checks the host prefix (`^https://data\.matricula-online\.eu/`).
- Copy it from the entry manifest's `matricula_url` (Lank KB999_3, KB1000 and KB999_4 manifests and the Horn manifest already have it). Put `N` in `image_number`.
- `citation` is a human-readable string: *Parish, register + book signature, scan/image, page, entry. Matricula Online: URL*.
- Structured parts (`archive`, `matricula_collection`, `parish`, `book_signature`, `image_label`, `page`) are optional helpers. `parish_slug`, `archival_id`, `scan`, `page` and `entry` stay the machine keys.
- `null` (or leaving the field out) is valid. Existing files have none and still validate.

### (b) Place identification: `*_identified`
- The existing **string** fields (`groom_residence`, `parents_residence`, `residence`, `marriage_place`, …) keep the **diplomatic** value, as the locked CSVs require. Each gets a sibling `<field>_identified` object.
- `place_as_written` is the place words as written, without `ex`/`in`/`de`, with abbreviations and `[?]` kept (e.g. `Schall.`). `identified_name` is the editorial name (e.g. Schallern). `place_id` is the gazetteer id from `/workspace/lank-schema/places/` (e.g. `place:lank`); leave it null until the place exists there. `match_confidence` is `certain|probable|possible|unmatched` (same vocabulary as `opr-place-ref`). `as_of_date` is the event date.
- This is a superset of `places/place_ref.schema.json` (opr-place-ref v1.0.0). Only one field is renamed: `residence_as_written` becomes `place_as_written`, because the same object also serves `marriage_place` and `burial_place`. ETL maps the rest 1:1.
- The old free-form `place_ref` stays in every schema for envelope parity, marked legacy.

### (c) Period jurisdiction: `period_jurisdiction`
- The temporal gazetteer **already models this**. `place_admin` has time-bounded `admin_level` + `admin_name` rows (herrschaft, amt, kreis, departement, state, country, deanery, …), resolved by `place_id` + `as_of_date` (see `places/README.md`, "Resolving a register residence").
- So the record **references** the gazetteer: `{source: "gazetteer", place_id, as_of_date}`, and nothing is copied. The schema enforces `place_id` when `source=gazetteer`.
- `source: "editorial"` + `editorial_levels[]` is a stop-gap for places not yet in the gazetteer (e.g. Horn 1799: Duchy of Westphalia / Kurköln). Promote those into `place_admin` rows later.
- Gap for Stephen: `place_admin.admin_level` has no `territory` or ecclesiastical `diocese` (only `diocese_civil` and `deanery`). The Horn examples use `territory` under the editorial snapshot. I propose adding `territory` and `diocese` in opr-place-admin v1.1.0.

### (d) Aliases: `person_aliases`
- The value is a map from a person field name to an array of `{form, marker}`. Each schema limits the keys to its own person fields (e.g. marriage: `groom_name`, `groom_mother`, …).
- `marker` is the normalized lemma: `dictus` (dictus/dicta/dtā/dtʸ/dæ̱), `genannt`, `vulgo`, `condictus` (cond./conducta/condicta), `alias` or `other`. `marker_as_written` keeps the ink form.
- The person field keeps the **primary name only** (`groom_name: "Conradus Halberschmidt"`, alias Schäper). This matches the locked marriage pilot decision 1 and death decision 2 (primary name in the name field). The legacy `notes` token (`condictus: Brauns`) may stay for CSV export.

### (e) Sponsor and witness residence
- Baptism: `godfather_residence_identified`, `godmother_residence_identified`. There is no string column, so `place_as_written` carries the diplomatic form.
- Marriage: `witness_1_residence_identified`, `witness_2_residence_identified`, plus `witnesses_other_details[]` (`person_with_residence`) for further **named** witnesses, in the same order as `witnesses_other`. Unnamed classes (`N vicino`, `patribus`) stay only in `witnesses_other`.

### (f) Child surname (baptism)
- `child_surname` is the surname as written for the child. If the entry gives none, it is the surname Stage B assigns (normally the father's).
- `child_surname_inferred` is `true` when the surname is not written for the child in this entry, `false` when it is written, and `null` when not assessed. `child_name` is unchanged (given names as today).

### (g) Previous spouse
- Marriage: `groom_previous_spouses[]` and `bride_previous_spouses[]`. Death: `previous_spouses[]`; the current or last spouse stays in `spouse_or_parents`.
- Each item holds `name` (nominative), `name_as_written` (e.g. genitive `Marie Margarethae Schüer[?]`), `vital_status`, `residence_identified`, `aliases` and `notes`.

### (h) Deceased-parent status: `*_vital_status`
- Marriage: `groom_father_vital_status`, `groom_mother_vital_status`, `bride_father_vital_status`, `bride_mother_vital_status`. Baptism and communion: `father_vital_status`, `mother_vital_status`. Death: `spouse_or_parents_vital_status`.
- `status` is `deceased|living|uncertain`. `as_written` holds the diplomatic word (`Ffti`, `obtōrum`, `defunctus`, `selig`, `quondam`). A couple-level word (`obtōrum Cjgūm`) is repeated on both parents.
- Name choice: `*_status` already means marital status (`groom_status: viduus`), so the new fields are called `*_vital_status`.

## Applicability matrix

| Field | baptism 1.1.0 | death 1.1.0 | communion 1.1.0 | marriage 1.0.0 |
|-------|:---:|:---:|:---:|:---:|
| `source_citation` | ✓ | ✓ | ✓ | ✓ |
| `period_jurisdiction` | ✓ | ✓ | ✓ | ✓ |
| `person_aliases` | ✓ | ✓ | ✓ | ✓ |
| place `*_identified` | `parents_residence_identified` | `residence_identified`, `burial_place_identified` | `residence_identified` | `groom_/bride_residence_identified`, `marriage_place_identified` |
| sponsor/witness residence | `godfather_/godmother_residence_identified` | — | — | `witness_1_/witness_2_residence_identified`, `witnesses_other_details` |
| `child_surname` (+`_inferred`) | ✓ | — | — | — |
| previous spouse | — | `previous_spouses` | — | `groom_/bride_previous_spouses` |
| `*_vital_status` | `father_`, `mother_` | `spouse_or_parents_` | `father_`, `mother_` | groom/bride × father/mother |

## Examples
- `examples/KB1000_s003_p15_e1.baptism.v1_1.json`: citation, `child_surname` inferred, gazetteer jurisdiction
- `examples/KB999_4_s010_p16_e3.death.v1_1.json`: `person_aliases` (cond. Brauns), `residence_identified`
- `examples/*.marriage.json`: all marriage fields (see STAGE_B_MARRIAGE.md)

## Not in this bump (open)
Several register owners already write lock and provenance keys that no schema allows: `stage_b_locked_by`, `expanded_latin_status`, `expanded_latin_locked_at/_by`, `soft_spots`, `crop_md5`, `lock_note`, `csv_appended`. Because of these, the 4 live KB999_4 death records fail `additionalProperties:false` (this was true **before** this change). Proposal for Stephen: a shared `provenance` $def in the next bump.
