# Images: entry crops + full pages (Stephen 2026-09-13)

## Requirements

1. **Every entry** must include or strongly link to its **segment crop** (all ink for that record).
2. **Books/pages** must expose the **entire page image** (Matricula scan face or spread) for “view full page”.

Storage backend (VM fs vs S3/MinIO) is **TBD** — schema stores both `*_path` (object key / absolute-or-repo-relative path) and optional `*_url`.

## Proposed columns

### `lank.scans` (full page under a book)

| Column | Purpose |
|--------|---------|
| `image_path` | Durable path/key for full face or spread |
| `image_url` | Optional HTTP(S) URL to same bytes |
| `face` | `left` \| `right` \| `single` \| `spread` |
| `image_path_left` / `_right` (+ urls) | When spread is stored as two faces |
| `image_width` / `image_height` / `image_sha256` | Optional QC |
| `storage_backend` | `fs` \| `s3` \| `matricula` \| `other` |
| `viewer_url` | Matricula `?pg=` deep link (already present) |

UI: book → scan/page → show `image_path`/`image_url`.

### `lank.entry_images` (crop per entry)

| Column | Purpose |
|--------|---------|
| `entry_id` | Stable PK from Segmenter |
| `crop_image_path` **NOT NULL** | Segmenter `crop_image` |
| `crop_image_url` | Optional served URL |
| `source_image_path` | Face used to cut crop |
| `scan_id` | FK → `lank.scans` for full-page jump |
| `bbox` / `polygon` / `mask_fill` | Geometry |
| `book_id`, `scan`, `page`, `face`, `entry`, `entry_kind` | Join helpers |

UI: entry detail → crop; button “view full page” → parent `scan_id`.

### Staging convenience (`stg_baptisms` pattern)

| Column | Purpose |
|--------|---------|
| `entry_id` | Link to manifest / entry_images |
| `crop_image_path` / `crop_image_url` | Denorm for simple queries |
| `scan_id` | Optional FK to full page |

Other `stg_*` tables get the same three columns when Site Host wires them.

## Manifest (Entry Segmenter)

Required: `crop_image` (path).  
Recommended: `source_image`, optional `crop_image_url` / `source_image_url` / `scan_image_ref`.  
Schema: `entry_manifest.schema.json` v1.2.0.

## SQL

`/workspace/lank-schema/book-meta/postgres_images_v1.sql`
