# Entry manifest metadata

See also `/workspace/opr-pipeline/ENTRY_SEGMENTER_SPEC.md`.

## `entry_kind` (required)

| Kind | Use |
|------|-----|
| `baptism` | Taufe formula entry |
| `marriage` | Trauung entry (when segmenting marriage books) |
| `death` | Sterbe entry |
| `communion` | Erstkommunion name/line |
| `note` | Misc clerical note as its own block |
| `index` | Alphabetical / tabular index |
| `title` | Title / section / year header without a person entry |
| `blank` | Intentionally empty (rare to crop) |
| `other` | Clear non-sacrament content |
| `uncertain` | Needs QC |

**Steward note:** Stephen’s baptism-volume list is the core. Added `marriage` / `death` / `communion` so one manifest schema works across register types; for KB 1000 body pages the common values are still baptism|note|index|title|blank|other|uncertain.

Extractors are **kind-specific**: baptism extractor only on `entry_kind=baptism`, etc.

Manifest also requires `parish_slug` + `archival_id` (book FK). Strip legacy `parish_name` / `parish_place` after transition.

See also [IMAGES.md](./IMAGES.md) for full-page + crop columns.

## Stage B text fields — `expanded_latin` (2026-09-25)

All Stage B record schemas (baptism v1.0.3 / v1.1.0 draft, death v1.1.0 draft, communion v1.0.2 / v1.1.0 draft, **marriage v1.0.0 draft**; hist-notes when drafted) carry nullable `expanded_latin` right after `transcription_latin`. Rules: [EXPANDED_LATIN_RULES.md](./EXPANDED_LATIN_RULES.md).

## Stage B record schemas (2026-09-29)

| Register | Schema | Version | Doc |
|----------|--------|---------|-----|
| Baptism | `baptism_record.schema.json` | 1.0.3 locked → **1.1.0** additive DRAFT (pending Stephen approval) | STAGE_B_BAPTISM.md |
| Death | `death_record.schema.json` | **1.1.0** DRAFT (1.0.1 records valid) | STAGE_B_DEATH.md |
| Communion | `communion_record.schema.json` | 1.0.2 locked → **1.1.0** additive DRAFT (pending Stephen approval) | STAGE_B_COMMUNION.md |
| Marriage | `marriage_record.schema.json` | **1.0.0 DRAFT** (new) | STAGE_B_MARRIAGE.md |
| Shared defs | `opr_shared_defs.schema.json` | 1.0.0 DRAFT | STAGE_B_SHARED_FIELDS.md |

Shared fields (source citation, place identification, period jurisdiction, aliases, sponsor/witness residence, child surname, previous spouse, vital status) are defined once in `opr_shared_defs.schema.json` and copied into each schema's `$defs` by `/workspace/lank-schema/tools/sync_shared_defs.py` (`--check` detects drift). Validate records with `/workspace/.venv-js/bin/python /workspace/lank-schema/tools/validate_stage_b.py <files>`, and check `expanded_latin` with `/workspace/lank-schema/tools/check_expanded_latin.py` (v2).
