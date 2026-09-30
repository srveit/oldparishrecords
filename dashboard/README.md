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
Greyhawk (macOS, /Users/sveit): /Users/sveit/OPR-Dashboard/index.html (open with "Open OPR Dashboard.command"). Kept current by ~/OPR-Dashboard/refresh.sh via launchd com.veithome.opr-dashboard, which pulls from http://grokbot-box.taileabb91.ts.net. The old Desktop/Downloads Wilmes-dashboard copies were trashed 2026-09-29.
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
