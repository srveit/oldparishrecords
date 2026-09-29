# Lank St. Stephanus — Postgres schema for Site Host

Prepared for **Site Host** (Stephen’s searchable genealogy site) from Schema Steward’s locked CSV / book-meta schemas (2026-09-10).

**Path:** `/workspace/lank-schema/postgres/`

## Layers

| Layer | File | Purpose |
|-------|------|---------|
| Book meta | `00_book_meta.sql` | `books`, optional `scans`; Matricula URLs; gesperrt flags |
| Staging | `01_staging.sql` | 1:1 CSV mirrors for import (`stg_*`) |
| Normalized | `02_normalized.sql` | Searchable `person`, `place`, `event`, `event_person` (pragmatic) |
| Views | `03_views.sql` | Flat search views + `person_timeline` |
| Expanded Latin | `04_expanded_latin.sql` | `expanded_latin` columns, `fold_search_text()`, FTS indexes, search view |
| Fixes | `05_expanded_latin_fixes.sql` | Œ fold, view comment, REINDEX of the FTS indexes (idempotent; apply to live) |
| Optional | `06_stage_b_citation_columns.sql` | UNTESTED on live: `matricula_url` / `source_citation` / `stage_b_shared`, marriage `entry_id` |
| Decisions | `NOTES.md` | Dates, sex, identity, hist-notes joins, open questions |

Diplomatic transcription stays in staging (`transcription_latin` / `transcription`, DE/EN, notes). Normalization extracts people/places/dates for search **without** rewriting the diplomatic text.

## Import order

1. Apply SQL in numeric order: `00` → `01` → `02` → `03` → `04` → `05` (→ `06` optional, after approval).
2. Load **`books`** (seed in `00_book_meta.sql`, or upsert from `*_meta.json`).
3. `COPY` / import CSVs into matching `stg_*` tables with `book_id` (or `archival_id` then resolve).
4. Optionally run ETL into normalized tables (mapping notes in `02_normalized.sql` / `NOTES.md`).
5. Query via views in `03_views.sql`.

Suggested CSV → staging map:

| CSV / schema | Staging table | Book(s) |
|--------------|---------------|---------|
| KB1000 baptisms | `stg_baptisms` | KB 1000 |
| KB999_3 marriages | `stg_marriages` | KB 999_3 |
| deaths schema | `stg_deaths` | KB 999_4, KB 1009 (**not** 1010) |
| communion schema | `stg_communion` | KB 1052_5 (**not** 1011) |
| confraternity_enrollment | `stg_confraternity_enrollment` | KB 1052_9 |
| yearly_name_roll | `stg_yearly_name_roll` | KB 1052_9 |
| ledger_admin | `stg_ledger_admin` | KB 1052_9 |

## Conventions (summary)

- **PostgreSQL 16**-ish; **UTF-8**; **snake_case**.
- **PKs:** `bigserial`. Staging also has **UNIQUE (`book_id`, `scan`, `page`, `entry`)**.
- **Names / transcriptions:** `TEXT`. Soft readings: in-cell **`[?]`** (documented in `NOTES.md`).
- **Dates:** CSV columns stay `TEXT`. Parsed search dates use nullable `DATE` + `*_original` / `event_date_text`.
- **Soft delete:** `deleted_at TIMESTAMPTZ NULL` on staging (+ optional `is_deleted` generated).
- **Gesperrt (not loaded):** KB **1010** (deaths → 2107-12-31), KB **1011** (communion → 2044-12-31). Rows exist in `books` with `access_status = 'gesperrt'` only — no staging data.

## Source schema locations (locked / sample)

- Baptisms: `/workspace/lank-kb1000/transcript/SCHEMA.md`
- Marriages: `/workspace/lank-kb999_3/transcript/marriage_schema.md`
- Deaths: `/workspace/lank-deaths/transcript/death_schema.md`
- Communion: `/workspace/lank-communion/transcript/communion_schema.md`
- Hist notes: `/workspace/lank-histnotes/transcript/list_types.md` (+ three list-type schemas)
- Book meta shape: `/workspace/lank-kb999_3/transcript/book_meta_schema.json`

## Apply example

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f /workspace/lank-schema/postgres/00_book_meta.sql \
  -f /workspace/lank-schema/postgres/01_staging.sql \
  -f /workspace/lank-schema/postgres/02_normalized.sql \
  -f /workspace/lank-schema/postgres/03_views.sql
```

> **Book meta v1.1 draft:** see `/workspace/lank-schema/book-meta/` (`opr-matricula-book-meta`). Apply `book-meta/postgres_deltas_v1_1.sql` when ready.

> **Parish entity:** `/workspace/lank-schema/book-meta/postgres_parishes_v1.sql` + `matricula_parish_meta.schema.json` (books FK via `parish_ref_id`).
