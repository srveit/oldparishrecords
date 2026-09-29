# Stage B — death / burial record (structured)

**Schema:** [`death_record.schema.json`](./death_record.schema.json) (`opr-death-record` **v1.1.0** DRAFT; v1.0.1 records remain valid)  
**Examples:**
- [`examples/KB999_4_s010_p16_e3.death.json`](./examples/KB999_4_s010_p16_e3.death.json) — Petrus Heijes + `condictus: Brauns`
- [`examples/KB999_4_s010_p16_e2.death.json`](./examples/KB999_4_s010_p16_e2.death.json) — unnamed `infantulus`

**Aligns with:** `/workspace/lank-deaths/transcript/death_schema.md` → `lank.stg_deaths`  
**Pipeline brief:** `/workspace/opr-pipeline/DEATH_PIPELINE_BRIEF.md`  
**Book (pilot):** KB 999_4 Sterbefälle — https://data.matricula-online.eu/en/deutschland/aachen/lank-st-stephanus/KB+999_4/  
**Stage A/B owner:** **Lank Deaths** (not Entry Transcriber)

Also mirrored under `extraction/`.

---


## v1.1.0 shared fields (DRAFT 2026-09-29)

Additive bump from v1.0.1 (still draft). Every new field is optional and nullable, and existing records validate unchanged.

New fields: `source_citation`; `spouse_or_parents_vital_status`; `previous_spouses[]`; `residence_identified`; `burial_place_identified`; `period_jurisdiction`; `person_aliases` (the `condictus: X` / `vulg: Y` notes token may stay for CSV). Definitions and rules: **[STAGE_B_SHARED_FIELDS.md](./STAGE_B_SHARED_FIELDS.md)** (`opr_shared_defs.schema.json`, identical copies in this schema's `$defs`).

Example: [`examples/KB999_4_s010_p16_e3.death.v1_1.json`](./examples/KB999_4_s010_p16_e3.death.v1_1.json).

**Pre-existing validation gap:** the 4 live records in `/workspace/lank-deaths/entries/KB999_4/transcripts/` carry keys no schema version allows (`crop_md5`, `crop_xmax`, `expanded_latin_status`, `expanded_latin_locked_at/_by`, `expanded_latin_added_at`, `amended_at`, `stage_b_locked_by`, `csv_appended`), so they fail `additionalProperties:false` under both 1.0.1 and 1.1.0. See the provenance question in STAGE_B_SHARED_FIELDS.md.


## `expanded_latin` (v1.0.1, 2026-09-25)

- New nullable field placed right after `transcription_latin`. It is the reading and search form: abbreviations expanded with supplied letters in `[ ]`, uncertain expansions marked `[?]`, wrap hyphens joined, ` / ` removed, and the margin prefixed as `margin | `.
- Follow the shared rulebook **[EXPANDED_LATIN_RULES.md](./EXPANDED_LATIN_RULES.md)**. `diplomatic_text` and `transcription_latin` stay unchanged.
- `null` means not yet produced. Backfill locked records on the next QC pass.
- Same bump also formalizes `stage_b_status` (`draft`/`locked`), `stage_b_locked_at`, `stage_a_status: locked`, and lets enum fields be null (they were already used in practice).

## Status

**DRAFT for Stephen QC** (2026-09-21). Hybrid pipeline kickoff: Page Structure → Segmenter → Lank Deaths Stage A/B.

Not yet locked. Do not treat as final until Stephen / Chief sign off.

---

## Stage A → Stage B

| | Stage A (diplomatic) | Stage B (structured) |
|--|----------------------|----------------------|
| Output | `*.diplomatic.json` | `*.death.json` (this schema) |
| `stage` | `diplomatic` | `structured` |
| Latin | Full diplomatic line | Copied to `transcription_latin` **unchanged** |
| People / facts | Running text | `deceased_*`, `age`, `status`, `spouse_or_parents`, `residence`, … |
| Dates | Margin + in-text | Prefer **ISO** in `death_date` / `burial_date` when clear (locked CSV); else partial / as-written + `[?]` |
| Soft | `soft_spots[]` | Trailing `[?]` and/or `soft_fields` + `notes` tokens |
| Image | `crop_image` | Same (+ `crops[]` for multi-leaf) |

### What expands / maps
- Month abbrevs (`7bris`…`Xbris`) → calendar month when writing ISO dates
- *eadem* / *ejusdem* → resolve date; keep Latin word in `notes`
- *sepultus/a* → prefer `burial_date` when that is the only date
- Sex from *filius/filia*, *sepultus/sepulta*, *viduus/vidua*, given name
- `gh.` before a surname → **spouse** in `spouse_or_parents`, not `status` (`notes`: `gh. → spouse`)

### What stays diplomatic / notes-only
- `transcription_latin` abbreviations
- Aliases: primary name in `deceased_name`; `condictus: X` / `vulg: Y` in **`notes`** (no alias column)
- Soft tokens with `[?]`
- Margin book numbers (`N. 29`) → `notes`

### What not to invent
- Parents, spouse, residence, age, cause, priest, burial_place
- Default burial place (Lank churchyard) on every row
- Certainty when Stage A marked soft
- Any rows for **KB 1010** (gesperrt)

### Locked pilot decisions (carry into Stage B)
From `death_schema.md` (KB 999_4 scan 010):

1. **Unnamed infants** — own row; descriptive Latin in `deceased_name`; `status` = noun used (`infantulus` / `infans`)
2. **Aliases** (`cond.` / `vulg.`) — primary identity in `deceased_name`; token in `notes`
3. **`gh.`** — spouse pointer → `spouse_or_parents`; not `status`

### Multi-leaf spans
Same pattern as baptism v1.0.2: **one** Stage B record; `incomplete: true` until continuation locked; then append `crops[]` / `diplomatic_paths[]` and fill fields. Optional `continues_entry_id` / `continued_from_entry_id`.

### Translations
Locked CSV marks `translation_de` / `translation_en` **required** for complete rows.  
JSON allows null for incomplete fragments. **Open for Stephen:** require DE/EN at Stage B for every complete pilot row (recommended — Lank Deaths already produces them), or defer like baptism Stage B?

### Residence
Keep **single** `residence` string as written (matches `stg_deaths`).  
**Open for Stephen:** split `residence_town` / `residence_place` like baptism `parents_town` / `parents_place`?

### Dates vs baptism
Baptism Stage B keeps diplomatic text in `*_date` + optional `*_date_iso`.  
Death locked CSV puts ISO (when clear) **in** `death_date` / `burial_date`. This draft **follows the death CSV** for staging 1:1.  
**Open for Stephen:** add optional `death_date_diplomatic` / `burial_date_diplomatic`, or keep as-is?

---

## Staging load mapping

JSON field → `stg_deaths` column (same names for core fields).  
Also set pipeline: `entry_id`, crop path(s).  
`scan` / `page` / `entry` must match the manifest natural key.  
`archival_id` / `book_id` → KB 999_4 or KB 1009 only.

**Volume caveat:** KB 999_4 scan order ≠ timeline (retrospective blocks after gap note scan 016). Sort/search by entry dates, not `scan`.

---

## Hybrid roles (from DEATH_PIPELINE_BRIEF)

1. Page Structure — spans; `entry_kind=death` on body  
2. Entry Segmenter — crops + pads  
3. Lank Deaths — Stage A + Stage B  
4. Schema Steward — this schema / docs  
5. Chief — QC lock loop  

Pilot faces: scan **004** title; scan **005** left first body.

---

## Open questions for Stephen

1. DE/EN required at Stage B for complete rows? (recommend **yes**)  
2. Keep ISO-in-`death_date` (CSV), or diplomatic+`_iso` like baptisms?  
3. Split residence town/place, or keep one `residence` string?  
4. Priest field: nominative expansion (`Wilhelmus Jacobs`) like baptisms, or leave as written (`Wilh. Jacobs`)?
