# Stage B extraction schemas

- Baptisms: `../STAGE_B_BAPTISM.md`
- Deaths: `../STAGE_B_DEATH.md`
- Communion: `STAGE_B_COMMUNION.md` / `communion_record.schema.json` (v1.0.2 locked; v1.1.0 additive draft)
- Marriages: `STAGE_B_MARRIAGE.md` / `marriage_record.schema.json` (v1.0.0 DRAFT 2026-09-29)
- Shared fields: `STAGE_B_SHARED_FIELDS.md` / `opr_shared_defs.schema.json` (DRAFT 2026-09-29)

This folder mirrors the schemas, docs and examples one level up (`../`); keep it in sync with `tools/sync_shared_defs.py --check`.

## Stage B text fields — `expanded_latin` (2026-09-25)

All Stage B record schemas (baptism v1.0.3 / v1.1.0 draft, death v1.1.0 draft, communion v1.0.2 / v1.1.0 draft, **marriage v1.0.0 draft**; hist-notes when drafted) carry nullable `expanded_latin` right after `transcription_latin`. Rules: [EXPANDED_LATIN_RULES.md](../EXPANDED_LATIN_RULES.md).

## Stage B record schemas (2026-09-29)

| Register | Schema | Version | Doc |
|----------|--------|---------|-----|
| Baptism | `baptism_record.schema.json` | 1.0.3 locked → **1.1.0** additive DRAFT (pending Stephen approval) | STAGE_B_BAPTISM.md |
| Death | `death_record.schema.json` | **1.1.0** DRAFT (1.0.1 records valid) | STAGE_B_DEATH.md |
| Communion | `communion_record.schema.json` | 1.0.2 locked → **1.1.0** additive DRAFT (pending Stephen approval) | STAGE_B_COMMUNION.md |
| Marriage | `marriage_record.schema.json` | **1.0.0 DRAFT** (new) | STAGE_B_MARRIAGE.md |
| Shared defs | `opr_shared_defs.schema.json` | 1.0.0 DRAFT | STAGE_B_SHARED_FIELDS.md |

Shared fields (source citation, place identification, period jurisdiction, aliases, sponsor/witness residence, child surname, previous spouse, vital status) are defined once in `opr_shared_defs.schema.json` and copied into each schema's `$defs` by `/workspace/lank-schema/tools/sync_shared_defs.py` (`--check` detects drift). Validate records with `/workspace/.venv-js/bin/python /workspace/lank-schema/tools/validate_stage_b.py <files>`, and check `expanded_latin` with `/workspace/lank-schema/tools/check_expanded_latin.py` (v2).
