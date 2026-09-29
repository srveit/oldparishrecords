# Temporal places / towns gazetteer (OPR)

**Priority deliverable** for residences that change name and jurisdiction over time.

| File | Purpose |
|------|---------|
| `place.schema.json` | Stable place identity |
| `place_name.schema.json` | Time-bounded names |
| `place_admin.schema.json` | Time-bounded admin divisions |
| `place_parish_link.schema.json` | Time-bounded place ↔ parish |
| `place_ref.schema.json` | How CSV residence fields point here |
| `postgres_places_v1.sql` | Postgres sketch |
| `examples/place_lank.json` | Lank / Lanck (EXAMPLE eras) |
| `examples/place_ilverich.json` | Ilverich (EXAMPLE eras) |

## Field tables (short)

### Place identity (`opr-place`)
| Field | Notes |
|-------|--------|
| `place_id` | Stable id (`place:lank`) — **never** renamed when the town is |
| `place_kind` | hamlet / village / town / … |
| `preferred_label` | Modern UI default when no as-of date |
| `centroid`, `external_ids` | Optional OSM/Wikidata/etc. |

### Names (`opr-place-name`)
| Field | Notes |
|-------|--------|
| `name` | Lanck, Lank, Lank-Latum, … |
| `name_type` | official / common / latin / register_form / … |
| `date_from` / `date_to` | Inclusive validity; null = open/unknown |
| `uncertain_end` | Soft end of period |

### Admin (`opr-place-admin`)
| Field | Notes |
|-------|--------|
| `admin_level` | herrschaft, kreis, gemeinde, stadt, departement, country, plz, … |
| `admin_name` | Jurisdiction label for that period |
| `date_from` / `date_to` | Validity range |

### Parish link (`opr-place-parish-link`)
| Field | Notes |
|-------|--------|
| `parish_slug` | FK to parish entity |
| `role` | in_parish / filial / registers_in / … |
| dates | When this hamlet “belonged” to that parish for register purposes |

**Parish ≠ place:** `lank-st-stephanus` is the **parish**; Ilverich/Nierst/Strümp are **places** that may link to it for some periods.

## Resolving a register residence

1. CSV keeps diplomatic text: `parents_residence = "Ilverich"` / `"Lanck"`.
2. Optional ETL adds `place_ref`: `{ residence_as_written, place_id, as_of_date }` where `as_of_date` = event date (`baptism_date`, etc.).
3. Display query: pick `place_names` and `place_admin` rows where `as_of_date` ∈ [date_from, date_to].
4. Until matched, show diplomatic text only (`match_confidence=unmatched`).

## Relationship to parish / book meta

```
parishes (parish_slug)
places (place_id) ──place_parish_links──► parishes
books (parish_slug) ──► parishes
entry residence text ──optional place_id+as_of──► places
```

## Open questions for Stephen

1. `place_id` style: `place:ilverich` slugs vs opaque UUIDs?
2. How hard to normalize early Herrschaft/Amt lines for the Lank area first — research depth for v1?
3. Should unmatched register spellings auto-create `place_names` stubs, or only human-curated places?
4. Multiple places sharing a spelling (homonyms) — require parish_slug disambiguation on match?
5. Civil vs church geography: keep both in `place_admin` + `place_parish_links`, or separate graphs?
6. Example admin eras in `place_lank.json` are **provisional** — who confirms French/Prussian/Meerbusch cutovers?

**Status:** draft for review; examples marked EXAMPLE.
