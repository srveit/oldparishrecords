# Matricula parish + book metadata (OPR)

| Entity | Schema id | Version | File |
|--------|-----------|---------|------|
| **Parish** | `opr-matricula-parish-meta` | **1.0.0** | [`matricula_parish_meta.schema.json`](./matricula_parish_meta.schema.json) |
| **Book** | `opr-matricula-book-meta` | **1.2.0** | [`matricula_book_meta.schema.json`](./matricula_book_meta.schema.json) |

**Site:** oldparishrecords.com (multi-parish).  
**Rule:** Parish fields live on the **parish** entity. Books reference **`parish_slug`** (Matricula slug natural key). Entry manifests reference `archival_id` (+ optional `parish_slug`) — do not copy diocese/country onto every entry.

Supersedes: embedded `parish{…}` on book v1.1 and flat v1.0 `parish_name` / `parish_place`.

---

## Entity relationship

```
parishes (parish_slug)
    └── books (parish_slug → parishes.parish_slug)
            └── entry manifests / staging rows (archival_id → books)
                    └── crops (entry_id)
```

Postgres: `lank.parishes` ← `lank.books.parish_ref_id` FK · see [`postgres_parishes_v1.sql`](./postgres_parishes_v1.sql).

---

## Parish field table

| Field | Matricula / source | Notes |
|-------|--------------------|-------|
| `parish_slug` | *(OPR)* | Stable public id; **prefer Matricula parish URL slug** (`lank-st-stephanus`) |
| `display_name` | Landing title | e.g. Lank St. Stephanus |
| `name` | Dedication / short name | e.g. St. Stephanus |
| `place` | Locality | e.g. Lank (Lank-Latum) |
| `diocese_archive` | Landing diocese/archive | e.g. Aachen, rk. Bistum |
| `country` | Landing country | Deutschland |
| `history` | Landing history blurb | long text; optional |
| `matricula.parish_url` | Landing URL | required when Matricula-sourced |
| `matricula.parish_slug` | URL slug | usually equals `parish_slug` |
| `matricula.platform` | | default Matricula Online |
| `links[]` | *(OPR)* | optional `{rel, label, url}` (wikipedia, diocese, opr, …) |
| `notes` | *(OPR)* | |

Example: [`examples/parish_lank-st-stephanus.v1.json`](./examples/parish_lank-st-stephanus.v1.json)

---

## Book field table (v1.2)

| Field | Matricula / source | Notes |
|-------|--------------------|-------|
| `parish_slug` | FK → parish | **replaces** embedded parish object |
| `archival_id` | Register list / viewer ID | e.g. KB 1000; unique **per parish** |
| `register_type` | Type | Taufen, Trauungen, Sterbefälle, Erstkommunion, historische Notizen, … |
| `date_from` / `date_to` | Date from / to | ISO; nullable |
| `date_from_raw` / `date_to_raw` | Display strings | optional |
| `book_title` / `book_title_de` | *(OPR UI)* | bilingual |
| `comment` | Comment | e.g. Mischbuch |
| `description` | Description / Inhalt | raw; may include gesperrt phrase |
| `source.*` | Viewer + images | URLs, scan_count, label range/skips, image patterns + Referer |
| `access.*` | Derived + Description | status, gesperrt_until(+raw), load_staging |
| `csv_schema_ref` | *(OPR)* | locked entry CSV schema |
| `list_types` | *(OPR)* | multi-structure books |
| `notes` | *(OPR)* | |
| `parish_snapshot` | — | **deprecated**; offline bag cache only |

Examples: `examples/KB1000_meta.v1_2.json`, `examples/KB1011_meta_gesperrt.v1_2.json`

### Gesperrt parsing

Same as v1.1: raw phrase → `description` + `access.gesperrt_until_raw`; parse ISO → `access.gesperrt_until`; `status=gesperrt`, `load_staging=false`.

---

## Link to entry crops / manifests

| Layer | Keys | Parish data |
|-------|------|-------------|
| Parish JSON / `lank.parishes` | `parish_slug` | Full parish record |
| Book JSON / `lank.books` | `parish_slug` + `archival_id` | No diocese/country copy |
| Entry Segmenter manifest | `entry_id`, `archival_id`, optional `parish_slug` | Join only |
| Staging CSV | `book_id` | Join `books` → `parishes` |

Lean manifest:

```
entry_id, parish_slug?, archival_id, scan, page, face, entry,
matricula_url, source_image, crop_image, bbox, polygon?,
continuation_from_prior_leaf, notes
```

---

## Postgres

1. Existing: [`../postgres/00_book_meta.sql`](../postgres/00_book_meta.sql)  
2. Column adds: [`postgres_deltas_v1_1.sql`](./postgres_deltas_v1_1.sql)  
3. **Parish table + FK:** [`postgres_parishes_v1.sql`](./postgres_parishes_v1.sql)

`postgres_parishes_v1.sql` creates `lank.parishes`, seeds Lank, adds `books.parish_ref_id`, backfills, and unique `(parish_ref_id, archival_id)`.

Legacy parish_* columns on `books` may remain during transition; new reads should **JOIN parishes**.

---

## Open questions for Stephen

1. Is **Matricula slug = `parish_slug`** the permanent public id, or do you want opaque UUIDs with slug as alternate key?
2. Normalize diocese/country to lookup tables later, or keep text on parish?
3. When should Entry Segmenter **drop** required parish_name/place from manifests (now vs after first second parish)?
4. Store Matricula history HTML vs plain text?
5. Rename Postgres schema `lank` → `opr` when multi-parish goes live?
6. Should `books.archival_id` stay globally unique in UI paths (`/kb/1000`) or always be parish-scoped (`/lank-st-stephanus/kb/1000`)?

Draft status: **ready for Stephen review**.

---

## Related: temporal places gazetteer

Residences (Ilverich, Lanck/Lank, …) → `/workspace/lank-schema/places/`  
Parish ≠ hamlet; places link to parishes with time ranges.

## Images

Full-page scans + entry crops: [`entry/IMAGES.md`](./entry/IMAGES.md), [`postgres_images_v1.sql`](./postgres_images_v1.sql).
