# Stage B — marriage record (structured)

**Schema:** [`marriage_record.schema.json`](./marriage_record.schema.json) (`opr-marriage-record` **v1.0.0 DRAFT**, 2026-09-29, Schema Steward). **Not locked.** It awaits Stephen's QC.
**Shared fields:** [STAGE_B_SHARED_FIELDS.md](./STAGE_B_SHARED_FIELDS.md) (`opr_shared_defs.schema.json`)
**Aligns with:** `lank-st-stephanus-marriage-csv` **v1.1.0** (`/workspace/lank-kb999_3/transcript/marriage_schema.md`, 25 columns, `expanded_latin` = col 25) → `lank.stg_marriages`
**Pipeline brief:** `/workspace/opr-pipeline/MARRIAGE_PIPELINE_BRIEF.md`
**Rulebook:** [EXPANDED_LATIN_RULES.md](./EXPANDED_LATIN_RULES.md)
Also mirrored under `extraction/`.

**Examples** (all validate, and all pass `check_expanded_latin.py`):
- [`examples/KB999_3_s118_p252_e4.marriage.json`](./examples/KB999_3_s118_p252_e4.marriage.json): Lank. Converted from the locked 2026-09-26 record (`lank-st-stephanus-marriage-csv` 1.1.0 JSON). Sparse early entry, unnamed witness class `N vicino`, jurisdiction referenced from the gazetteer (`place:lank`).
- [`examples/Horn_KB005-02-H_0135_e2.marriage.json`](./examples/Horn_KB005-02-H_0135_e2.marriage.json): Horn. Widower + `groom_previous_spouses`, `vulgo` / `dtā` aliases, `quondam` → vital status `uncertain`, `q;` in the Latin.
- [`examples/Horn_KB005-02-H_0135_e3.marriage.json`](./examples/Horn_KB005-02-H_0135_e3.marriage.json): Horn (key Wilmes entry). `obtōrum` → both groom's parents `uncertain` (Stephen reads obitorum, reference reads dictorum), mother alias from the interlinear, `[struck: …]` / `[interlinear: …]` markers, witness residences.
- [`examples/Horn_KB005-02-H_0135_e4.marriage.json`](./examples/Horn_KB005-02-H_0135_e4.marriage.json): Horn. `Ffti` → groom's father `deceased`, `dtʸ` alias, `witnesses_other_details`, unmatched place `Bökum`.

The Horn examples are converted from the Record Extractor's DRAFT output (`/workspace/horn-wilmes/stageB/H0135/`, generator `tmp/stageB_H0135/gen.py`). Every value comes from that output, its locked Stage A files or `horn-wilmes/entries/manifest.jsonl`. Nothing was invented.

---

## Field list (in schema order)

**Envelope (identical to baptism/death):** `schema_id` (const `opr-marriage-record`), `schema_version` (`1.0.x`), `stage` (`structured`), `stage_a_status`, `stage_b_status` (`draft|locked|null`), `stage_b_locked_at`, `entry_id`, `parish_slug`, `archival_id`, `scan`, `page`, `entry`, `entry_kind` (const `marriage`), `crop_image`, `crops[]`, `crop_image_continued`, `diplomatic_path`, `diplomatic_paths[]`, `diplomatic_text`, **`source_citation`**.
Required: the same 13 envelope keys as baptism/death (`schema_id … crop_image, transcription_latin, stage_a_status`).

**Marriage (CSV v1.1.0 columns plus shared objects):**

| Field | CSV col | Notes |
|-------|---------|-------|
| `marriage_date` | 4 | CSV rule: ISO when clear; partial `YYYY-MM-??` or as written + `[?]`; *eadem* resolved (word in notes) |
| `groom_name` | 5 | primary name only (nominative, person-field form); alias → `person_aliases.groom_name` |
| `groom_status` | 6 | as written (`viduus`, `caelebs`); never invent |
| `groom_previous_spouses[]` | — | (g) for a widowed groom |
| `groom_residence` | 7 | **diplomatic** as written, without `ex` (`Lathum`, `Schall.`) |
| `groom_residence_identified` | — | (b) as written vs identified place |
| `groom_father`, `groom_mother` | 8, 9 | never invent |
| `groom_father_vital_status`, `groom_mother_vital_status` | — | (h) |
| `bride_name`, `bride_status`, `bride_previous_spouses[]`, `bride_residence`, `bride_residence_identified`, `bride_father`, `bride_father_vital_status`, `bride_mother`, `bride_mother_vital_status` | 10–14 | as for the groom |
| `witness_1`, `witness_1_residence_identified` | 15 | (e) |
| `witness_2`, `witness_2_residence_identified` | 16 | (e) |
| `witnesses_other` | 17 | named extras `; `-separated, or unnamed classes (`N vicino`, `patribus`, `et aliis`) |
| `witnesses_other_details[]` | — | (e) named extras with residence, same order |
| `banns_or_dispensation` | 18 | short summary |
| `priest` | 19 | as written; `à me parocho` phrase if no name; never inherited from a prologue |
| `marriage_place`, `marriage_place_identified` | 20 | only when stated; `in facie Ecclesiae` → null |
| `period_jurisdiction` | — | (c) reference to the gazetteer |
| `person_aliases` | — | (d) keys: groom/bride name, father, mother; witness_1/2; priest |
| `transcription_latin` | 21 | diplomatic, Stage A markers kept; multi-column layout `margin \| place \| main text \| Testes` |
| `expanded_latin` | 25 | right after `transcription_latin`, per the rulebook; null = not produced yet |
| `translation_de`, `translation_en` | 22, 23 | the CSV requires them for complete rows; nullable in JSON for fragments |
| `notes` | 24 | |
| `soft_fields`, `incomplete`, `continuation_note`, `continues_entry_id`, `continued_from_entry_id`, `place_ref` (legacy) | — | envelope parity |

**CSV export:** columns 1–25 map 1:1 by name. `scan`, `page` and `entry` come from the envelope. JSON `null` becomes an empty cell. The shared objects are not CSV columns: for now keep them in JSON or load them into the optional `06_*` Postgres columns.

## Locked CSV pilot decisions (carried over unchanged)
1. Bynames (`conducta` / `condicta` / `dictus` / `vulgo`) are not a status. The primary name stays in the name field. **New in 1.0.0:** the alias is also structured in `person_aliases`; the notes token is optional.
2. Unnamed witness classes go in `witnesses_other`, as diplomatic Latin.
3. Out-of-order dates: keep the calendar date and flag it in notes. Keep page order.
4. `à me parocho` stays in `priest`. Never inherit a name.
5. Residence spelling is diplomatic per entry. Normalization lives **only** in `*_identified`.
6. `in facie Ecclesiae`: leave `marriage_place` null.

## Stage A → Stage B
| | Stage A | Stage B |
|--|---------|---------|
| Output | `*.diplomatic.json` | `<entry_id>.marriage.json` |
| Latin | per leaf; columns (`[margin_date]`, `[place]`, `[main_text]`, `[testes]`) where the book has them | `transcription_latin` = columns joined with ` \| `, lines with ` / `, markers (`[struck: …]`, `[interlinear: …]`) kept |
| People | running text | nominative person fields, aliases split out |
| Places | `ex Schall.` | `groom_residence: "Schall."` plus `groom_residence_identified.identified_name: "Schallern"` |
| Soft | `soft_spots`, `[?]`, `X[?\|Y]` | `[?]` in fields, `soft_fields`, notes |

## Multi-leaf
As for baptism v1.0.2: one Stage B record, `incomplete: true` until the continuation is locked, then append to `crops[]` / `diplomatic_paths[]`.

## Converting existing marriage JSON
- **Lank KB999_3 p252 e4** (locked): set `schema_id` / `schema_version`, `locked_at` → `stage_b_locked_at`, `""` → `null`. `soft_spots`, `expanded_latin_status`, `locked_by` and `lock_note` have no v1.0.0 field (see the provenance open question). In the example, `lock_note` was appended to `notes` and `soft_spots` was dropped (its content overlaps `soft_fields`).
- **Horn H0135 (Record Extractor)**: see "Changes for the Record Extractor" below.

## Changes for the Record Extractor (H0135 output → v1.0.0)
To validate at all, you only need to set `schema_id: "opr-marriage-record"` and `schema_version: "1.0.0"`. Your current files then pass, because the legacy `place_ref` is free-form. To conform to the conventions:
1. **Residences diplomatic.** `groom_residence` / `bride_residence` must hold the form as written (`Schall.`, `Berenbrok`, `Clive`, `Bökum.`), not the normalized name (CSV pilot lock 5). Move `Schallern` / `Berenbrock` / `Klieve` into `*_residence_identified.identified_name`.
2. **Place objects.** Replace `place_ref.{groom,bride}` with `groom_residence_identified` / `bride_residence_identified`. Rename `residence_as_written` → `place_as_written` and drop the preposition (`ex Schall.` → `Schall.`). Put the reason in `basis`, not in `notes`. Keep `match_confidence`, `as_of_date` and `place_id` (null until the gazetteer has Horn places).
3. **Aliases out of name fields.** `Conradus Halberschmidt vulgo Schäper` → `groom_name: "Conradus Halberschmidt"` + `person_aliases.groom_name: [{form: "Schäper", marker: "vulgo", marker_as_written: "Vulgo"}]`. The same applies to `dicta Schröer`, `dictus Herweg`, the groom's mother `Brinkhoff dicta Herweg` and `dictus Schulte`.
4. **Previous spouse.** e2's first wife (currently only in `soft_fields.groom_status`) → `groom_previous_spouses`.
5. **Deceased parents.** e3 `obtōrum` → both `groom_*_vital_status: uncertain` until Stephen confirms obitorum vs dictorum; e4 `Ffti` → `groom_father_vital_status: deceased`; e2 `quondam` → `uncertain` on both bride parents.
6. **Witness residences.** Fill `witness_1/2_residence_identified`. Fill `witnesses_other_details` for named extras (e4: Petrus Koch, Franz Anton Kruse).
7. **Source and jurisdiction.** Move the SOURCE sentence and the Matricula URL from `notes` into `source_citation`, and the Duchy of Westphalia / Kurköln sentence into `period_jurisdiction` (editorial, until Horn is in the gazetteer).
8. **Blanks.** Use `null` instead of `""` (still tolerated).
9. **`stage_a_status` vs `stage_b_status`.** `stage_a_status` reports the status of the upstream Stage A diplomatic file (the Horn H0135 Stage A files are `status: locked`, Stephen 2026-09-27). The extractor's own output status is `stage_b_status`, which stays `draft` until Stephen locks it. `soft` is still accepted in `stage_a_status` if the upstream file is soft. (Pending confirmation from Chief/Stephen.)
10. **IDs (resolved 2026-09-29, Record Extractor).** `archival_id` is the Matricula book code `KB005-02-H` (URL path `.../DE_EBAP_22212/KB005-02-H/`); `scan` is the image name `H_0135`; `entry_id` is `Horn_KB005-02-H_0135_eN`. `KB005-02` is only the crop folder name under `entries/`. Same pattern for KB004-02-T, KB004-06-T, KB006-01-S, KB007-01-T.
11. **File name.** Use `<entry_id>.marriage.json`, the house convention (`*.baptism.json`, `*.death.json`), e.g. `Horn_KB005-02-H_0135_e3.marriage.json`.
12. **Validation.** Use the canonical schema (`validate_stage_b.py`) instead of `marriage_record.derived.schema.json`. The good parts of the derived schema (the envelope, column descriptions, `soft_fields`, `place_ref`) were reused.
`check_expanded_latin.py` v2 now passes all three H0135 records **unchanged**.

## Open questions for Stephen
1. Require `translation_de` / `translation_en` at Stage B for complete rows? (The CSV requires them; baptism defers them.)
2. `marriage_date`: keep ISO-in-field (CSV), or add `marriage_date_diplomatic` like baptism's `*_date` + `*_iso`? This is the same question as for death.
3. Approve moving aliases out of the name fields (structured `person_aliases`) for marriages. The pilot lock put them in `notes` only.
5. A provenance $def for owners' lock keys (`soft_spots`, `stage_b_locked_by`, `expanded_latin_status`, …)?
