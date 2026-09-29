# Deploy — "Cite this record" (Site Host)

Front-end only. No new routes are required. `/health` and `/search` JSON
contracts and the search form field names (`q`, `name`, `place`, `date`, `kind`)
are unchanged.

## 1. Files to copy → `/opt/lank-search/static/`

From `/workspace/opr-ui-v1/static/` on the shared box:

| File | Change |
|------|--------|
| `index.html` | one added line: `<script src="/static/cite-fields.js" defer></script>` before `app.js` |
| `app.js` | cards get a collapsed "Cite this record" section (with a collapsed "More Ancestry fields" section), copy buttons, single-record view |
| `styles.css` | appended "Cite this record" styles (existing rules untouched) |
| `cite-fields.js` | **new** — the one file holding all Ancestry.com / FamilySearch field definitions |

```bash
sudo cp index.html app.js styles.css cite-fields.js /opt/lank-search/static/
# static files only; a restart is not needed unless you cache responses
```

Rollback: the live-synced baseline (identical to production on 2026-09-29) is in
`/workspace/opr-ui-v1/baseline-live-2026-09-29/` (`index.html`, `styles.css`, `app.js`);
copy those three back and delete `cite-fields.js`.

## Ancestry.com side (verified against Ancestry's live forms on 29 Sep 2026)
Source of truth: the `anc()` template in the dashboard; `cite-fields.js` mirrors it
(labels, order, REQUIRED flags, hints). FamilySearch is unchanged.

Visible first: **Quick add-source dialog** with Source title (optional), Citation details
(REQUIRED) and Citation web address. Below it, one collapsed section, "More Ancestry
fields: full citation, source and repository", holds:
- **Citation (full form):** Details (REQUIRED), Web address, Transcription of text, Other information, Date, Source title. Media is a citation tab ("Add media to source"), not a field; a note says so.
- **Source:** Source title (REQUIRED), Author, Publisher, Publisher location, Call number, Publication date, REFN, Note, Repository name.
- **Repository:** Name (REQUIRED), Address, Phone number, Email, Call number, REFN, Note.

REFN (both), Repository Address / Phone / Email / Call number, and Publication date have
no data source and always show "Not available".

## 2. Single-record URL (no backend change)

```
/?record=<kind>:<archival_id>:<scan>:<entry>[:<date_text>][&site=ancestry|familysearch]
```
Example (works on the public host once deployed):
```
https://oldparishrecords.com/?record=death%3AKB%20999_4%3A017%3A2%3A1736-01-05&site=familysearch
```
The page is still `/` (existing FileResponse). app.js finds the record by
calling the existing `/search?kind=<kind>&date=<date_text>&limit=200` and
matching kind + archival_id + scan + entry exactly (falls back to year-only
date, then `kind` alone). Each result card has a "Link to this record" link that
builds this URL. Switching Ancestry.com / FamilySearch in this view updates
`&site=` in the URL.

Limitation without a backend change: a record without `date_text` whose kind has
more than 200 rows may not be found. The optional endpoint in 3b removes that.

## 3. Backend additions requested (additive only)

### 3a. Extra optional fields on each `/search` hit
Add these keys to every hit (null when unknown). **Do not rename or change any
existing key.** The front end already renders them; they fill "Not available"
fields automatically.

| JSON key | Source (Schema Steward DDL) | Fills |
|----------|-----------------------------|-------|
| `parish_name` | `lank.books.parish_name` (join on staging `book_id`) | Ancestry Source title (quick, full citation, Source), Author; FS Source Title, Citation |
| `parish_place` | `lank.books.parish_place` | same (shown as "<place> <parish>") |
| `diocese_archive` | `lank.books.diocese_archive` | Ancestry Source › Note and Repository name, Repository › Name; FS Citation "<archive>" |
| `register_type` | `lank.books.register_type` (Taufen, Trauungen, Sterbefälle, Erstkommunion, …) | "Kirchenbuch <register>" in the Ancestry Source title fields and FS Citation (today falls back to a per-kind default; communion/histnotes have none) |
| `book_date_from`, `book_date_to` | `lank.books.date_from`, `date_to` (ISO `YYYY-MM-DD`) | years in the Ancestry Source title fields |
| `book_url` | `lank.books.source_url` | fallback for FS Web Page only (flagged "book, not exact page"); Ancestry Citation web address / Web address use `matricula_url` only |
| `matricula_url` | `lank.scans.viewer_url`, or `books.book_start_url` with `?pg=` set to `scans.matricula_pg`, joined on `(book_id, scan)`. **Null when no confirmed mapping — do not derive pg from the scan number.** | Ancestry Citation web address and full-citation Web address; FS Web Page |
| `primary_name` | principal person: `child_name` (baptisms), `deceased_name` (deaths), `communicant_name` (communion), `groom_name + ' & ' + bride_name` (marriages), `primary_name` (histnotes_flat) | FS Source Title and the name in Ancestry Citation details (today uses `names`, which lists everyone in the entry) |
| `transcription` | `transcription_latin` (baptisms/marriages/deaths/communion) or `transcription` (hist-notes tables) — diplomatic text | Ancestry Transcription of text; FS Notes |
| `translation_en` | `translation_en` | Ancestry Other information; English text in FS Notes (today both fall back to `snippet`, flagged as the search summary) |

Also rendered if present, but **no DB column exists today** (leave out unless a
source is added): `archive_address`, `archive_phone`, `archive_email`,
`archive_code` (Ancestry Repository › Address / Phone / Email / Note).

Not used by the front end: `notes`, `crop_image_url` (Ancestry Media is a tab, not a
field). Harmless if sent.

### 3b. Optional exact lookup endpoint (recommended, not required)
```
GET /record?kind=<kind>&archival_id=<id>&scan=<scan>&entry=<entry>
200 → {"hit": { ...same shape as a /search hit, incl. 3a fields... }}
404 → {"detail": "Not Found"}
```
app.js already tries `/record` first and quietly falls back to `/search` on a
404, so this lights up on its own. Sketch:

```python
@app.get("/record")
def record(kind: str, archival_id: str, scan: str, entry: int):
    hit = lookup_one(kind, archival_id, scan, entry)   # same SELECT as /search, WHERE exact match, LIMIT 1
    if not hit:
        raise HTTPException(status_code=404)
    return {"hit": hit}
```
Until it exists, each single-record view makes one extra request that gets a 404; this is harmless.

## 4. Smoke checklist (after copy)
1. `curl -sS https://oldparishrecords.com/health` → JSON `ok: true` (unchanged).
2. `curl -sS 'https://oldparishrecords.com/search?name=Mueller'` → JSON with same keys as before.
3. `curl -sSI https://oldparishrecords.com/static/cite-fields.js` → 200, JS content type.
4. Open `/`, search Name = `Radmächer`, Kind = Death → 6 cards; each has a collapsed "Cite this record" and a "Link to this record" link.
5. Open one card's Cite section → Ancestry.com is selected; the Quick add-source dialog shows Source title, Citation details (REQUIRED), Citation web address. For Mathias Radmächer, Citation details = `KB 999_4, image 017, p. 31, no. 2; 1736-01-05; Mathias Radmächer`. Below it, "More Ancestry fields: full citation, source and repository" is collapsed; opening it shows Citation (full form) with Details = `KB 999_4, image 017, p. 31, no. 2`, Other information = the snippet, and Date = `1736-01-05`, then Source (Call number `KB 999_4`) and Repository. The words "not yet verified" appear nowhere.
6. Click FamilySearch → table switches; arrow keys move between the two tabs.
7. Click Copy on a row → button shows "Copied", and pasting gives the value.
8. Open the example URL from §2 → one card, Cite open on FamilySearch, back link to search, tab title "Mathias Radmächer · Death · Old Parish Records". The same URL with `&site=ancestry` opens on the Ancestry side.
9. `/?record=baptism%3AKB%201000%3A002%3A99` → "Record not found" message, with no JS errors.
10. Page source/branding: "Old Parish Records" only.
11. After adding the 3a fields: Ancestry Source title, Citation web address (with `matricula_url`), Source title / Author / Repository name / Repository Name and FS Citation fill in; `transcription` fills Transcription of text, and the "Not available yet: parish" notes disappear.

## Editing fields later
All field names, order, REQUIRED flags, hints and which record property fills
each field: `/static/cite-fields.js` (one file; see the comment at its top).
