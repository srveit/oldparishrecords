# OPR pipeline status dashboard

The Old Parish Records (OPR) status dashboard tracks the church-book records being worked. Each row is one record
(a person's baptism, marriage, burial and so on) at a known book and page on Matricula Online, grouped into family
groups. For every row it shows where that record stands in the pipeline (Segmentation → Transcription → Expansion →
Record Extraction, with Page Structure (Stage 0) upstream), links to the scan on Matricula, and generated review/detail
pages where the stage output can be checked and approved with one click. `status.py` derives every status from the
pipeline's files every 30 s; the page (`index.html`) polls `status.json` every 15 s.

> **Repo copy.** This folder is a clean source snapshot. The live copy runs from
> `/workspace/horn-wilmes/dashboard` on the Grok box (http :8080 via `server.py`, approve endpoint
> 127.0.0.1:8081 via `approve_server.py`, `updater.sh` loop, started by `ensure_dashboard.sh`).
> Paths in the scripts are absolute to that live location. Runtime/data files (records.json,
> overrides.json, matricula_pg.json, notify_queue*.jsonl, auto_transcribe_sent.json, out/, logs, pids)
> are intentionally not in git.

# Wilmes records status dashboard

Files: records.json (19 rows, static fields + baseline), overrides.json (coordinator-edited), status.py (derivation),
index.html (UI), updater.sh (loop), out/ (generated status.json, status.js, index.html).

Status notes: edit status_notes.json (list of {date YYYY-MM-DD, time HH:MM CT or "", title, body, kind info|resolved}; plain text, no credentials) to add or remove a note; status.py shows it on the Pipeline page and the Meta tab within 30 s.

## Updater
Running: PID 4183527 (also in updater.pid), started 2026-09-27 07:26 CDT. Regenerates out/ every 30 s; errors -> updater.log.
Restart:  kill $(cat updater.pid); cd /workspace/horn-wilmes/dashboard && nohup ./updater.sh >/dev/null 2>&1 & echo $! > updater.pid
Optional: an executable push.sh here is run after each regen (hook for a future LAN/tailnet/gist push).

## Delivery (current: option d, file copy)
Greyhawk (macOS, /Users/sveit): /Users/sveit/OPR-Dashboard/index.html (open with "Open OPR Dashboard.command"). Kept current by ~/OPR-Dashboard/refresh.sh via launchd com.veithome.opr-dashboard, which pulls from the box tailnet URL. The old Desktop/Downloads Wilmes-dashboard copies were trashed 2026-09-29.
Do not copy status.js to the Desktop; Greyhawk syncs itself via refresh.sh.
If ever served over http, the page fetches status.json instead; ?src=<url> points it at a remote JSON URL.

## Derivation rules (per image code, e.g. T0407)
Precedence: overrides.json > file-derived > records.json baseline > "Not started".
Segmentation: manifest.jsonl rows with image_id: all rows crop_status=='locked' or status=='locked' -> Locked; any rows -> Draft (n crops, k locked);
  none but stage0/<image_id>_* or stage0_work/*<KBxxx-xx-X_nnnn>* present -> Queued (page layout running).
Transcription: stageA/<code>/ missing -> Not started; every non-blank manifest entry has <entry_id>.diplomatic.json AND <code>_stageA.md exists
  -> Done (review) (-> Approved if all diplomatic JSON status in approved/locked/final); otherwise (e.g. only _work/) -> In progress.
Record extraction: files under horn-wilmes/records/ or horn-wilmes/stageB/ whose name contains the code or image id -> Draft
  (Locked if all such JSON have status locked/approved/final); none -> Not started.

## Overrides
Edit overrides.json, e.g.  "T0405": {"segmentation": "Locked", "note": "Stephen approved"}  (fields: segmentation/transcription/extraction).
Delete the key to return to derived status. Picked up within 30 s. Chips with an override show a small pencil mark.

## Non-Horn rows (added 2026-09-29)
records.json rows may carry optional "collection" (e.g. DE_EBAP_23815) and "url" (full Matricula viewer URL); status.py passes them through.
index.html imgcell(): uses r.url if present; else MPG key "<collection>|<book>|<image>" for non-Horn collections, or "<book>|<image>" for Horn (DE_EBAP_22212, default).
Non-Horn codes are prefixed to avoid collisions, e.g. W-S0036 = Warstein KB013-01-S S_0036.
## Links (2026-09-29)
Every records.json row carries collection, pg (viewer page) and url; status.py (mlink) guarantees url/collection/pg in status.json.
index.html: Image and Page cells -> mlink(r) (url > MPG > collection+book+pg/page; never plain text).
Book cell -> booklink(r): title page, BOOKPG["<collection>|<book>"] (default 1; all current books checked, pg=1 is the title page).
Headless click/link test: /workspace/tmp/cdptest.js (node --experimental-websocket cdptest.js <chrome> <url>).

## Main page: family groups, collapse/expand
Rows are grouped by `group` (the `groups` list in records.json, copied to status.json). Each group header is a toggle
button (`button.grptog`, `aria-expanded`). Collapse/expand state is remembered per browser in `localStorage`, key
`opr.grp.<group name>` (`'0'` = collapsed; key absent = expanded), so it survives page refreshes and the 15 s poll
(`render()` re-reads it every time). **▾ Expand all** (`#gexp`) and **▸ Collapse all** (`#gcolall`) sit above the table.
Sorting by date or town (column headers) shows one flat list; "back to grouped view" restores the groups. A newly added row
opens its group if that group was collapsed.

## Login and session gate (/dashboard)
Source: `status.py` Meta tab, section "1. How it is hosted" (around lines 1679–1690), and `dashboard-auth/` in this repo.
* https://oldparishrecords.com/dashboard/ (not linked from the public site; pages carry `noindex,nofollow`). nginx
  terminates TLS and gates the whole `/dashboard` tree, API included, behind a login page with a session cookie.
* Auth service `dashboard-auth/auth_server.py` on **127.0.0.1:8082** (localhost only): `GET /login` form,
  `POST /login` (303 + `opr_dash_session` cookie, HttpOnly/Secure/SameSite=Strict; 401 on bad credentials; 429 rate limit),
  `/logout` (clears the cookie, 303 to `/dashboard/login?loggedout=1`), `/auth/check` (204 if the cookie is valid, else 401).
  nginx uses `/auth/check` as its `auth_request` for everything else under `/dashboard/`.
* Not signed in: HTML pages are redirected to the login page (`/dashboard/login?next=…`); API/JSON requests get **401**.
  In the page, a 401 on a poll or action sends the browser to the login page (`oprAuth`); a small **Log out** link shows on oldparishrecords.com.
* Hosting is being moved: `deploy/nginx/oldparishrecords.com.conf` (commit 74ed9e6) proxies `/dashboard/login`,
  `/dashboard/logout` to 127.0.0.1:8082 and `/dashboard/` to 127.0.0.1:8080 on the web VM, and keeps the box copy at `/dashboard-old/`.

## Approvals and the notify queue
* **Approve** buttons are on the detail pages (sticky header: row Approve for segmentation, transcription, expansion,
  extraction; per-entry **Approve entry** on transcription/expansion pages). One click, no confirmation; the button is disabled
  while saving and turns into a blue ✓ **Approved – N crops/entries/records locked at HH:MM CT** chip in place
  (per entry: "Approved HH:MM"). Errors show inline (✖) and re-enable the button.
* Endpoint: `POST /api/approve` → `approve_server.py` (127.0.0.1:8081). Requires header `X-OPR-Approve: 1` (403 without it)
  and an allowed Origin. Row edits (`add_row`, `update_row`, `delete_row`, `start_research`, `person_plus`) go to the same
  endpoint and are handled by `rowedit.py`.
* Every action writes `_approvals.log` and appends one line to `notify_queue.jsonl` (read by Chief's watcher).
  Queue `kind`/`action` values in the code: `action: segmentation`, `action: transcription`, `action: extraction`,
  `action: recut`, `kind: segmentation_correction`, `transcription_entry_approved`, `expansion_entry_approved`,
  `expansion_approved`, `reading_confirmed`, `choose_reading`, `reading_edited`, `choose_reading_undone`,
  `reading_edit_undone` (approve_server.py); `row_added`, `segmentation_requested`, `row_deleted`, `research_requested`
  (rowedit.py / addrow.py / updaterow.py). `notify_queue_handled.json` sits next to the queue on the box but no dashboard
  code reads or writes it (it belongs to the queue consumer).
* **🔍 Start research**: shown in the Name cell while book and page are both empty and research is not already running.
  One click → `start_research` → research = Researching, one `research_requested` queue line; refused (409) if book/page is set
  or research is already running.
* **Correct** (per crop, segmentation pages): inline panel (cut edges, neighbour ink, merge/split, wrong label, other + note);
  stores the flag in `entries/_corrections/<code>.json`, sets the row to Queued for redo, queues `segmentation_correction`,
  and shows a ⚠ Correction pending chip on the crop.

## Pipeline stages and status values (status.py)
Order: Page Structure (Stage 0) → Segmentation → Transcription (Stage A) → Expansion → Record Extraction (Stage B).
Page Structure has no column or action of its own; it shows up as Segmentation "Queued (page layout done)".
Precedence per cell: `overrides.json` > file-derived > records.json `baseline` > **Not started**. Override chips get a ✎ mark.
"Approved" from files means every crop/entry/record status is `locked`, `approved` or `final`.
* **Segmentation** (`seg()`, crops in `entries/manifest.jsonl`): Draft (n crops, m locked) → Approved (all crops locked).
  No crops but Stage 0 files → Queued (page layout done). Added rows with book/image/page filled → Queued.
  Stages set in overrides.json by the Segmenter or by actions: Segmenting (first cut; crops newer than the stamp win),
  Queued for redo (Recut / Correct) → Redoing → Recut, then approved again.
* **Transcription** (`trans()`, `stageA/<code>/`): Queued (segmentation Approved / dispatched) → In progress (n/N entries)
  → Draft (all entries + `<code>_stageA.md`) → Approved. In progress (stalled?) when dispatched, nothing finished and `_work/`
  unchanged for 60 min. Transcription detail pages show feedback chips: Transcriber updating… and Waiting on transcriber
  (pending over 30 min).
* **Expansion** (`expan()`, `stageA_expanded/<folder>/`): Not started until the transcription is Approved (an override is ignored
  before that) → Queued → In progress (d/N entries) → Draft (all entries + `_expanded.md`) → Approved (all locked).
* **Record Extraction** (`extr()`, `records/` or `stageB/`, field `stage_b_status`): Waiting on Expansion until Expansion is Draft
  or Approved (rows that already have Stage B files keep them) → Draft → Approved. Not started when there is nothing else.
* Not started also shows for added rows still waiting for book and page.

## Chips (colour-blind safe)
Chip class follows the chip text (`_kind()` in status.py / `oprKind` in the page), Okabe-Ito colours plus a symbol and border
so colour is never the only cue:
* Needs Stephen (`k-need`): amber #e69f00, black bold text, ⚠ – Draft, Recut, Queued for redo, Correction pending.
* Processing (`k-proc`): grey, dashed border, ⏳ – Queued, In progress, Redoing, Segmenting, Researching, Transcriber updating…, Approving….
* Waiting (`k-wait`): Waiting on transcriber, ⏳!, darker dashed border.
* Done (`k-done`): pale blue #e8f1fa, #0072b2 border, ✓ – Approved, locked, Page found, Added.
* Not started (`k-none`): white, grey border, ○ – the previous stage is not finished yet.
* Error (`k-err`): vermillion #d55e00, white bold text, ✖ – Blocked, error, failed, Not sent.

## Detail pages and links
* `status.py` regenerates `out/segmentation/`, `out/transcription/`, `out/expansion/` and `out/extraction/` (one page per row
  code) on every refresh; linked chips on the main page open them (↗).
* **Book** cell → the book's Matricula title page (`booklink()`, `BOOKPG`, default pg=1). **Image** and **Page** cells → the exact
  page (`mlink()`: row url > MPG map > collection+book+pg).
