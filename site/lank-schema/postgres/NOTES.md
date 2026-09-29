# Schema Steward → Site Host — design notes

Postgres target: **16-ish**. Schema namespace: **`lank`**. PK choice: **`bigserial`** everywhere (simpler ops than UUID for import/ETL); staging rows also enforce **UNIQUE (`book_id`, `scan`, `page`, `entry`)**.

Prepared 2026-09-10 from locked register schemas under `/workspace/lank-*/transcript/`.

---

## 1. Two layers (do not collapse)

| Layer | What | Why |
|-------|------|-----|
| **Staging (`stg_*`)** | CSV columns 1:1 as `TEXT` (+ `book_id`, timestamps, `deleted_at`) | Faithful import; diplomatic Latin/German; re-export equals CSV |
| **Normalized (`person`, `place`, `event`, `event_person`)** | Optional analytical model | person × place × date search without destroying transcription |

Views (`*_flat`, `name_mentions`) work **from staging alone**. Normalized tables fill when Site Host runs ETL.

---

## 2. Date handling

**CSV / staging:** all date fields remain **`TEXT`**.

Conventions from locked schemas:

- Clear calendar day → ISO `YYYY-MM-DD`
- Partial → `YYYY-MM-??`, `YYYY-??-??`, or literal + ` [?]`
- Soft / unclear → keep as written with **`[?]`**
- `eadem` / `eodem` / `ejusdem` → resolve to prior dated entry’s calendar date; record the Latin word in **`notes`**

**Parsed dates:** `lank.try_iso_date(text)` returns `DATE` only for clean `YYYY-MM-DD` **without** `?` or `[`. Otherwise `NULL`. Always keep original in `*_date` / `event_date_text`.

Normalized `event`:

- `event_date` + `event_date_text` + `event_date_precision`
- `secondary_date` / `secondary_date_text` for birth↔baptism, burial↔death

Do **not** invent dates from other books.

---

## 3. Soft readings: `[?]`

Documented house rule across all register types:

- Unclear word/name/date fragment marked **`[?]`** in-cell
- Longer ambiguity → **`notes`**
- Never invent grandparents, parents, status, age, residence, or cause

Site Host search: strip or weight `[?]` as needed; do not treat `[?]` as a person name token.

---

## 4. Sex enums

| Source | Values | Staging | Normalized |
|--------|--------|---------|------------|
| Baptisms, deaths, communion | `M` / `F` / `?` | store as-is | `person.sex`, `event_person.sex` |
| Confraternity enrollment | `m` / `f` (lowercase in sample schema) | store as-is | **upper-case to `M`/`F`** in ETL |
| Blank | not stated | `NULL` / empty | `NULL` — never invent |

Open question: whether Site Host normalizes communion/baptism `?` vs blank the same way in UI.

---

## 5. Status / parents_married fields

- **Marriage / death `status`:** diplomatic Latin (or German) as written — `viduus`, `vidua`, `caelebs`, `filia`, … Preferred vocabularies in schema docs are **not** CHECK constraints (open + blank allowed).
- **`parents_married` (baptisms):** `yes` / `no` / `?` (`conjugibus` → `yes`).
- Blank = not stated — **do not invent “single”**.

---

## 6. Books, scans, Matricula URLs

- **`lank.books`:** one row per `archival_id`; seeded from `*_meta.json` + gesperrt stubs.
- **`lank.scans`:** optional inventory; staging already stores `scan`+`page`+`entry` so Site Host can build viewer links without filling `scans`.
- Image downloads need HTTP header **`Referer: https://data.matricula-online.eu/`** (stored as `books.image_referer`).
- Default ceremony/burial place is parish church / churchyard — **leave blank** in CSV/staging when unstated; Site Host may display default from book meta in UI only.

### Gesperrt (not loaded)

| Archival ID | Type | Locked until | Action |
|-------------|------|--------------|--------|
| **KB 1010** | Sterbefälle 1879–2007 | **2107-12-31** | `access_status=gesperrt`, `load_staging=false` — no CSV |
| **KB 1011** | Erstkommunion 1880–1934 | **2044-12-31** | same — pilot only **KB 1052_5** |

When eventually unlocked: reuse `death_schema` / `communion_schema` columns.

---

## 7. Hist-notes list types (KB 1052_9)

Three **distinct** staging tables share **`book_id` → KB 1052_9**:

| `list_type` | Table | Join key |
|-------------|-------|----------|
| `confraternity_enrollment` | `stg_confraternity_enrollment` | `book_id` + scan/page/entry |
| `yearly_name_roll` | `stg_yearly_name_roll` | same |
| `ledger_admin` | `stg_ledger_admin` | same |

- Discriminator is **table name** (and redundant `list_type` column).
- Search union: view **`lank.histnotes_flat`**.
- Classify faces **by structure** (feast *inscripti* vs year columns vs fee ledger) — see `list_types.md`. Carmel band may mix types on one scan.
- Schemas status: **LOCKED** (2026-09-10) for staging import / site schema. Lank Notes is piloting; column set will not change without an explicit Schema Steward revision + ping to Site Host.
- **Normalized ETL on hist-notes:** OK to hold aggressive person/event ETL until pilots look clean; staging load for all three list types is approved now.
- Front matter (covers/flyleaves): no CSV / no staging rows.
- Communion (KB 1052_5) is a **separate** track — do not merge with `yearly_name_roll`.

---

## 8. Person identity (no forced merging)

**Decision:** ETL creates `event_person` rows with `name_as_written` always; `person_id` may be:

1. **Deferred (recommended start):** `person_id` NULL until a human/matcher links; or
2. **Per-mention person:** one `person` row per name cell (easy timeline later via `person_link`).

**Do not** auto-collapse “Wilh. Jacobs” across baptisms/marriages/deaths into one person without review.

Use **`lank.person_link`** (`same_as`, `possibly_same`, `parent_of`, `spouse_of`) for later identity / kinship. Confidence: `certain` | `probable` | `possible` | `rejected`.

`spouse_or_parents` on deaths stays one TEXT cell in staging; normalized ETL may leave it as a single `event_person` with role `other` / notes until parsed.

---

## 9. Soft-delete

All mutable tables: **`deleted_at TIMESTAMPTZ NULL`**. Views filter `deleted_at IS NULL`. Prefer soft-delete over hard DELETE for transcribed rows.

---

## 10. Import / FK expectations

1. Insert/upsert **`books`** first (`00_book_meta.sql` seed).
2. Set `book_id = lank.book_id_for('KB 1000')` (etc.) on each staging row.
3. Enforce natural unique; re-import = upsert on `(book_id, scan, page, entry)`.
4. Call `lank.assert_book_loadable(book_id)` in load scripts to block gesperrt volumes.
5. Optional: populate `scans` for URL caching.
6. Optional: ETL → `event` / `event_person` / `person` / `place`.

Encoding: **UTF-8**. Prefer Python `csv` module for export/import (quoted commas).

---

## 11. Site Host v1 decisions (recorded 2026-09-10)

1. **Viewer deep links:** defer “open image” until per-book `scans.matricula_pg` mapping is confirmed; staging scan/page/entry is enough for v1.
2. **Full-text search:** add `pg_trgm` + `tsvector` on `name_mentions` / translations **after first CSV load**.
3. **Death `spouse_or_parents`:** keep opaque TEXT in staging/ETL v1; structured roles later.
4. **Hist-notes:** schemas **LOCKED**; load staging for all three list types now; hold aggressive normalized ETL on hist-notes until Steward says pilots are clean enough (or “locked for prod ETL”).
5. **KB 999_4 alpha register (094–116):** **skip** site until Schema Steward expands scope.
6. **IDs:** keep `bigserial`; optional `public_id uuid` later for public URLs.
7. **Multi-book deaths:** UI filters by `archival_id` / book.
8. **Default place:** UI-only “Lank St. Stephanus” when place blank — **never invent in DB**.

Gesperrt KB 1010/1011 stay meta-only (`assert_book_loadable`). Ping Schema Steward if any `.sql` / NOTES change is needed before provision.

---

## 12. Pointers back to locked docs

| Topic | Path |
|-------|------|
| Baptisms | `/workspace/lank-kb1000/transcript/SCHEMA.md` |
| Marriages | `/workspace/lank-kb999_3/transcript/marriage_schema.md` |
| Deaths | `/workspace/lank-deaths/transcript/death_schema.md` |
| Communion | `/workspace/lank-communion/transcript/communion_schema.md` |
| Hist list types | `/workspace/lank-histnotes/transcript/list_types.md` |
| Book meta JSON Schema | `/workspace/lank-kb999_3/transcript/book_meta_schema.json` |
| This Postgres pack | `/workspace/lank-schema/postgres/` |

## 2026-09-21 — communion multi-parish
`stg_communion` also targets Osterath KB 1106_5 (`parish_slug=osterath-st-nikolaus`). Update table COMMENT when applying; CSV header unchanged.

## 2026-09-21 — communion Stage B lock
Stephen locked: shared CSV header; defer DE/EN at Stage B; `stg_communion` includes KB 1106_5 / Osterath (`parish_slug=osterath-st-nikolaus`).

## 2026-09-25 — `expanded_latin` + folded full-text search (`04_expanded_latin.sql`)
- Nullable `expanded_latin text` on all seven `stg_*` tables (Stage B reading/search form; rules in `book-meta/entry/EXPANDED_LATIN_RULES.md`).
- `lank.fold_search_text()` (IMMUTABLE): lowercase, æ/œ/ſ folded, `[?]` and brackets stripped, so `Prænob[ilis]` matches `praenobilis`.
- GIN `to_tsvector('simple', fold(coalesce(expanded_latin, transcription_latin)))` per table, so rows are searchable before backfill.
- `lank.record_text_search` union view for register search. CSV loaders accept an optional trailing `expanded_latin` column; the locked CSV headers are otherwise unchanged.
- Not yet executed against a live DB. Site Host applies it and checks it.

## 2026-09-29 — `05_expanded_latin_fixes.sql` (Site Host report) + optional `06_stage_b_citation_columns.sql`

> ⚠️ **The FTS indexes depend on `lank.fold_search_text()`.** All seven `stg_*_fts_idx` GIN indexes (and any future index built on the fold) are **expression indexes over this function**. Postgres does **not** rebuild them when the function body is replaced with `CREATE OR REPLACE`, and it does not warn. Rows indexed under the old body keep stale entries, so matches are silently missed (in the scratch test, `oeconomus` was not found until REINDEX). **After any change to `fold_search_text()`, REINDEX every index that uses it.** 05 does this for the seven known indexes; add new ones to its list. For zero downtime, run `REINDEX INDEX CONCURRENTLY …` outside a transaction instead of 05's DO block. Never change the function's output for existing input without a REINDEX, and keep it `IMMUTABLE`.

- **05 (apply to live; idempotent):**
  (a) the `lank.record_text_search` view comment now names **`lank.histnotes_flat`** (it wrongly said `lank.histnotes`);
  (b) `fold_search_text()` also folds capital **`Œ` → `Oe`** (`Æ` → `Ae` was already there). It stays IMMUTABLE PARALLEL SAFE with the same signature;
  (c) REINDEX of the seven FTS indexes (skips any that are missing).
  04 is corrected the same way, for fresh installs (00→05 gives the same end state). Smoke-tested on a scratch PG 17 cluster only.
- **06 (optional, UNTESTED on live; apply only after Stephen approves the v1.1 shared fields):** adds `matricula_url` (CHECK: Matricula host), `source_citation` text and `stage_b_shared` jsonb to `stg_baptisms`, `stg_marriages`, `stg_deaths` and `stg_communion`. It also adds `entry_id` / `entry_kind` / `crop_image_path` + a unique `entry_id` index on `stg_marriages` (same pattern as baptisms in `book-meta/postgres_images_v1.sql`). The CSV headers are unchanged.
- **Marriage Stage B (`opr-marriage-record` v1.0.0 DRAFT):** no required DDL. `stg_marriages` already has all 24 CSV columns (01), plus `expanded_latin` and the FTS index (04). 06 only adds the optional link and citation columns.
