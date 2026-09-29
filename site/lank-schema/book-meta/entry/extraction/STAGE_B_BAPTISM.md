# Stage B — baptism record (structured)

**Schema:** [`baptism_record.schema.json`](./baptism_record.schema.json) (`opr-baptism-record` **v1.0.3** locked; **v1.1.0** additive draft, pending Stephen approval)  
**Examples:**
- [`examples/KB1000_s003_p15_e1.baptism.json`](./examples/KB1000_s003_p15_e1.baptism.json) — complete single-leaf
- [`examples/KB1000_s003_p15_e5.baptism.json`](./examples/KB1000_s003_p15_e5.baptism.json) — incomplete two-page span stub

**Aligns with:** `lank.stg_baptisms` in `/workspace/lank-schema/postgres/01_staging.sql`  
Also mirrored under `extraction/`.

---


## v1.1.0 shared fields (DRAFT 2026-09-29, **pending Stephen approval**)

The locked **v1.0.3** stays in force. v1.1.0 is **additive only**: every new field is optional and nullable, `schema_version` accepts `1.0.x` and `1.1.x`, and all existing 1.0.3 records validate unchanged. Until Stephen approves, owners may keep writing `1.0.3`.

New fields: `source_citation`; `child_surname` + `child_surname_inferred`; `father_vital_status`, `mother_vital_status`; `godfather_residence_identified`, `godmother_residence_identified`; `parents_residence_identified`; `period_jurisdiction`; `person_aliases`. Definitions and rules: **[STAGE_B_SHARED_FIELDS.md](./STAGE_B_SHARED_FIELDS.md)** (`opr_shared_defs.schema.json`, identical copies in this schema's `$defs`).

Example: [`examples/KB1000_s003_p15_e1.baptism.v1_1.json`](./examples/KB1000_s003_p15_e1.baptism.v1_1.json).


## `expanded_latin` (v1.0.3, 2026-09-25)

- New nullable field placed right after `transcription_latin`. It is the reading and search form: abbreviations expanded with supplied letters in `[ ]`, uncertain expansions marked `[?]`, wrap hyphens joined, ` / ` removed, and the margin prefixed as `margin | `.
- Follow the shared rulebook **[EXPANDED_LATIN_RULES.md](./EXPANDED_LATIN_RULES.md)**. `diplomatic_text` and `transcription_latin` stay unchanged.
- `null` means not yet produced. Backfill locked records on the next QC pass.
- Same bump also formalizes `stage_b_status` (`draft`/`locked`), `stage_b_locked_at`, `stage_a_status: locked`, and lets enum fields be null (they were already used in practice).

## Locked decisions

| Decision | Rule |
|----------|------|
| Person / priest case | **Nominative** when unambiguous. |
| Translations | **Defer** DE/EN — leave **null** at Stage B. |
| Residence | `parents_town` + `parents_place`; compose `parents_residence` for staging. |
| Godparent parents | First-class: `godfather_father` / `godfather_mother` / `godmother_father` / `godmother_mother`. |
| Two-page spans | **One** Stage B record; attach ordered `crops[]` + `diplomatic_paths[]` when continuation locked. |

### Version history
- **v1.0.1** — godparent parents; split residence
- **v1.0.2** — multi-leaf `crops[]` / `diplomatic_paths[]`; optional `crop_image_continued`; `continues_entry_id` / `continued_from_entry_id`

---

## Two-page / multi-leaf spans (v1.0.2)

Stephen-approved plan:

1. **One Stage B record** per baptism (not one JSON per leaf after merge).
2. While only the first leaf is locked: emit an **incomplete** fragment (`incomplete: true` + `continuation_note`). Fill only safe fields from that leaf. `crops` = `[leaf1]`; `crop_image_continued` null; `continues_entry_id` optional if a distinct continuation entry_id exists before merge.
3. When the continuation leaf is locked: **merge into the same record** — append the second crop and diplomatic path, fill remaining person/fields, concatenate `transcription_latin`, set `incomplete: false`. Prefer keeping the **first leaf’s** `entry_id` as the canonical id; if the continuation had its own id, set `continued_from_entry_id` / retire the fragment id in notes.

| Field | Role |
|-------|------|
| `crop_image` | Primary leaf (required) = `crops[0]` |
| `crops[]` | Ordered crop paths (all leaves) |
| `crop_image_continued` | Optional shorthand for `crops[1]` (exactly two leaves) |
| `diplomatic_path` | Primary Stage A file = `diplomatic_paths[0]` |
| `diplomatic_paths[]` | Ordered; parallel to `crops[]` |
| `incomplete` | true until continuation locked and fields filled |
| `continuation_note` | Where it continues / prior leaf |
| `continues_entry_id` | Optional: other entry_id this fragment continues into |
| `continued_from_entry_id` | Optional: prior fragment entry_id |

Example e5 stub ends at `mar` on scan 003; continuation expected on scan 004 (p16). Do not invent mother/etc. until that leaf is locked.

---

## Stage A → Stage B

| | Stage A | Stage B |
|--|---------|---------|
| Output | `*.diplomatic.json` | `*.baptism.json` |
| `stage` | `diplomatic` | `structured` |
| Latin | Per leaf | Copied / concatenated into `transcription_latin` |
| People | Running text | Nominative fields + godparent parents |
| Residence | `in Langst ven …` | `parents_town` + `parents_place` |
| Soft | `soft_spots[]` | `[?]` and/or `soft_fields` |

### Staging load
Core fields → `stg_baptisms`. Compose `parents_residence` from town+place.  
Primary `crop_image` for image columns; store full `crops[]` in JSON until staging has multi-image support.

---

## Pilot
p15 e1 + e3; e5 as incomplete span stub (this schema).

### Joannis preference (Stephen 2026-09-16)

- When Stephen specifies **Joannis** for a spelled Joannes/Joannis form (e.g. godmother_father Nehr), prefer **Joannis** over Joannes.
- **Nierst ven confinis:** after Nierst, prefer **confinis** over Cuiford when that letter-form appears (Stephen QC 2026-09-16 on p13 e1). Do not auto-change Lanck ven Cuiford[?] until Stephen confirms.

- **Mid-matre fragment:** conjugibus pair after opening `filia` on a continuation crop → `maternal_grandfather` / `maternal_grandmother`; leave `father`/`mother` null until prior leaf.
- **Lütgeri → Lütgerus** nominative (e1 godfather_father).
- **Nierst in confinio** (e1); **Lanck ven confinis** (e6) — use Stephen’s locked diplomatic form per entry.
- **Lathum ven Müssen:** after Lathum this farm/local phrase is **ven Müssen** (not ex Müssen) — p13 e5 Stephen QC 2026-09-16.

### Residence split — Strümp ven Bantagns (Stephen 2026-09-17, p164 e4)
- Diplomatic: `in Strümp ven Bantagns[*]` (not `Strümpen`).
- Stage B: `parents_town` = **Strümp**; `parents_place` = **ven Bantagns[*]**; compose `parents_residence`.
- Letter lessons from same QC: **Bolten** (t tick, not Bollen); **Bens** (final s, not Bend).

### Final s — Brens (Stephen 2026-09-17, p15 e1)
- Paternal grandmother **Catharina Brens** (not Brend[?]); same final-s lesson as **Bens**.
- Stage B lock for p15 e1 held until Segmenter delivers crop with top raised to page top.

### Visible ü — Büsch (Stephen 2026-09-17, p15 e3)
- **Büsch** (not Busch) when umlaut over u is visible — both Gertrudis and Petrus.
- Pairs with no-invented-umlaut: write ü/ö/ÿ only when ink shows the mark.

### P vs R / Joēs / Rafen / Haus (Stephen 2026-09-17, Gotzen p15 e5 ↔ p16 e1)
- **Peiffers** not Reiffers — capital **P** (compare Parochus/Parochialis/Proto); contrast **R** in Reinartz.
- Maternal GF diplomatic **Andreae Peiffers** → Stage B nominative **Andreas Peiffers** (present; not struck).
- **Joēs** with macron between o and e → Stage B **Joannes** (child / godfather / godmother father).
- **Rafen** not Hafen — **R** like Reinartz.
- **Anna Haus** not Staus — initial **H**.

### Joīs vs Joēs (Stephen 2026-09-18, p16 e2)
- Diplomatic **Joīs** (macron over oi form) → Stage B nominative expansion **Johannis** (genitive Joannis as written).
- Diplomatic **Joēs** → Stage B **Joannes** (per Gotzen p16 e1 lesson).
- Do not swap these forms in Stage A.

### N. unknown surname (Stephen 2026-09-18, p16 e2)
- Diplomatic **N.** stays **N.** in Stage B person fields (e.g. Catharina N., Gertrudis N.) — not null and not `[?]`.
- `[?]` is for uncertain readings; **N.** is intentionally blank surname as written.

## QC lesson (2026-09-18) — ven after town
After the parents' town, the farm/local phrase is usually **ven …** (not **an …**), e.g. `in Gellep ven Cormoers[?]` (p16 e2). Prefer **ven** when the ink is ambiguous between an/ven. Stage B: `parents_town` = town; `parents_place` = `ven …`.

### p16 e4 expansions (Stephen 2026-09-18)
- Diplomatic **Xtinæ** → Stage B **Christina** (Chi/X = Christ-).
- **Ostertz**, **Hülters** (t-tick), **Rinkes** (R ≠ K in Kyfers).
- Birth formula **curre.** as locked in Stage A.
- **p16 e4 residence:** town Ilverich; place **ven slonns** (Stephen 2026-09-18).
- **p16 e5:** diplomatic **Weÿers** (ÿ) → Stage B **Weÿers** (keep ÿ); **Wellen** definite.
- **ÿ per occurrence (Stephen 2026-09-18/19, p16 e5):** write ÿ only where ink shows it. e.g. father **Hermanno Weÿers** keeps ÿ; paternal GF **Joīs Petri Weyers** has no ÿ — do not copy ÿ across the surname within one entry.
### Weÿers two-leaf merge (Stephen 2026-09-22)
- Canonical Stage B `KB1000_s004_p16_e5`; leaf2 `KB1000_s004_p17_e1`.
- No invented conjugibus → `parents_married` null if not on page; residence null if not written.
- Godfather **Henricus** (Adm. R. Dñus, sacellanus, receptor redituum … Barones de Backum in Castro de Lathum); parents Bernardus Schmitz × Maria Catharina Peil.
- Godmother Agnes Weÿers; father Johannis Petrus Weÿers (ÿ on leaf2).
- Maternal GM Gertrudis Busch; child Maria Agnes.
### Weÿers QC addendum (Stephen 2026-09-22)
- Baptism date diplomatic **16ta Nov̄s** → Stage B date string as written; ISO still 1779-11-16.
- Maternal GM **Gertrudis Büsch**; godmother **Agnes Weyers**; GM father **Johannis Petrus Weyers** (no ÿ on leaf2).
- Title in transcription: **Dñæ L. Baronesse de Backum** (keep in Latin transcription; godfather person field remains Henricus).

### Lanck ven Lüten / no invented maternal GF (Stephen 2026-09-23, p17 e2)
- Diplomatic: `in Lanck ven Lüten` → Stage B `parents_town` = **Lanck**; `parents_place` = **ven Lüten**; compose `parents_residence`.
- Mother line without `filia …`: default `maternal_grandfather` = null; `maternal_grandmother` from `et Margarethæ Pitsch conjugibus` (Herken p17 e2 Stage A).
- **Exception — Stage B kinship inference (Stephen 2026-09-23, Herken/Mols):** if godfather shares mother's surname **and** godfather's mother = maternal grandmother, set `maternal_grandfather` from godfather's father (Johannis Mols). Do **not** invent `filia Joīs mols` back into locked Stage A.
- **Klapdors** (final s) in paternal GM / godmother mother fields.
- Diplomatic lowercase **mols** → Stage B person-field **Mols** (same capitalize-as-surname pattern as müllers → Müllers).

### Χtina / Xtina → Christina (Stephen 2026-09-23, p17 e4)
- Diplomatic **Χtina** (Greek chi) or **Xtina** → Stage B nominative **Christina**.
- Do not Stage-A-read as Annâ/Anna when the form is Χtina/Xtina.
