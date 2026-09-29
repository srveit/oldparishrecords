# Stage B — communion / Erstkommunion record (structured)

**Schema:** [`communion_record.schema.json`](./communion_record.schema.json) (`opr-communion-record` **v1.0.2** locked; **v1.1.0** additive draft, pending Stephen approval)  
**Stub example:** [`examples/KB1106_5_s020_stub.communion.json`](./examples/KB1106_5_s020_stub.communion.json)  
**CSV / staging:** shared `communion_schema` → `lank.stg_communion`  
**Parishes:** `lank-st-stephanus` (KB 1052_5) · **`osterath-st-nikolaus`** (KB 1106_5)

Also under `extraction/`.

---


## v1.1.0 shared fields (DRAFT 2026-09-29, **pending Stephen approval**)

The locked **v1.0.2** stays in force. v1.1.0 is **additive only**: every new field is optional and nullable, `schema_version` accepts `1.0.x` and `1.1.x`, and all existing 1.0.2 records validate unchanged. Until Stephen approves, owners may keep writing `1.0.2`.

New fields: `source_citation`; `father_vital_status`, `mother_vital_status`; `residence_identified`; `period_jurisdiction`; `person_aliases`. The shared CSV header is **unchanged** (JSON-only fields). Definitions and rules: **[STAGE_B_SHARED_FIELDS.md](./STAGE_B_SHARED_FIELDS.md)** (`opr_shared_defs.schema.json`, identical copies in this schema's `$defs`).


## `expanded_latin` (v1.0.2, 2026-09-25)

- New nullable field placed right after `transcription_latin`. It is the reading and search form: abbreviations expanded with supplied letters in `[ ]`, uncertain expansions marked `[?]`, wrap hyphens joined, ` / ` removed, and the margin prefixed as `margin | `.
- Follow the shared rulebook **[EXPANDED_LATIN_RULES.md](./EXPANDED_LATIN_RULES.md)**. `diplomatic_text` and `transcription_latin` stay unchanged.
- `null` means not yet produced. Backfill locked records on the next QC pass.
- Same bump also formalizes `stage_b_status` (`draft`/`locked`), `stage_b_locked_at`, `stage_a_status: locked`, and lets enum fields be null (they were already used in practice).

## Status

**Locked 2026-09-21** (Stephen via Chief recommendations). Meta pack for KB 1106_5 accepted (48 scans, image pattern, `parish_slug`, first leaf 020 / printed 34–35).

### Locked decisions

| Decision | Rule |
|----------|------|
| CSV header | **Keep shared** header with Lank until first Osterath face shows need for new columns. |
| Translations | **Defer** `translation_de` / `translation_en` at Stage B — leave **null**. Not required for Stage B complete/QC. (CSV/staging columns remain for a later pass.) |
| Staging | `stg_communion` comments include KB 1106_5 / Osterath books. |

---

## Stage A → Stage B

| | Stage A | Stage B |
|--|---------|---------|
| Output | `*.diplomatic.json` | `*.communion.json` |
| `stage` | `diplomatic` | `structured` |
| Source text | Diplomatic Latin/German | → `transcription_latin` unchanged |
| Date | Section header | → `communion_date` (ISO when clear) |
| Soft | `soft_spots` | `[?]` / `soft_fields` / `notes` |
| DE/EN | — | **null** at Stage B |

### Owners
- **Lank Communion** — Lank KB 1052_5 (+ related open Lank)
- **Osterath Communion** — Osterath KB 1106_5

### Multi-leaf
Same as baptism/death: one Stage B record; `crops[]` / `diplomatic_paths[]`; `incomplete` until continuation locked.

### What not to invent
- Parents, age, priest, residence, certainty
- New CSV columns without Stephen/Chief lock after a real Osterath sample face

## Book meta (Osterath)

`/workspace/osterath-kb1106_5/transcript/KB1106_5_meta.json` — 48 scans (`020`–`068`, gap `032`), image pattern + Referer, first leaf = `020` / printed **34–35**.
