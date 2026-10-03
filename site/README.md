# site/ — oldparishrecords.com source (as found on the Grok box)

Public site https://oldparishrecords.com/ runs on the sites host. One Python process,
systemd `lank-search.service`, serves search and the dashboard (files and cookie login)
on port 8000. PostgreSQL and nginx are the other processes. `deploy/deploy-sites.sh`
copies `lank-search/app.py` and `lank-search/dashboard_routes.py` to `/opt/lank-search/`.
Search static files stay in `/opt/lank-search/static/`. Postgres database `lank`.
Public TLS is OPNsense; path routing for the sites vhost is `deploy/nginx/`.
To run this app on a workstation, use `../dev/run.sh` (local Postgres, empty `lank` database).

| Path | What |
|------|------|
| `lank-search/` | Live app (search, owner edits, and `/dashboard/` routes). This is what sites runs. |
| `dashboard/` | Dashboard files, login helpers (`server.py`), and generated `out/`. Imported by lank-search; the 8080 listener is not started on sites. See `dashboard/README.md`. |
| `dashboard-auth/` | Old separate login launcher. Sites does not start it. See `dashboard-auth/README.md`. |
| `sitehost/app/app.py` | Older search app. Do not copy this over `/opt/lank-search/app.py`. |
| `sitehost/app/app.py.box-orig` | Backend as deployed before that patch (sha baseline `run_on_vm.py` checks against). |
| `sitehost/run_on_vm.py`, `sitehost/pve.py` | Deploy helpers: run SQL/app steps on the VM via Proxmox qemu guest agent (VM 107). |
| `pve/search/app.py`, `pve/search/static/index.html` | Earlier copy of the backend (== box-orig) and the original v0 UI. |
| `pve/import/load.sql` | CSV → staging tables loader (code only; the CSVs are record data and are excluded). |
| `opr-ui-v1/static/` | Current UI incl. "Cite this record" (`cite-fields.js`). Deploy: `DEPLOY.md`, `CITE-DEPLOY.md`. |
| `opr-ui-v1/baseline-live-2026-09-29/` | Live production UI snapshot before the Cite deploy (rollback). |
| `opr-ui-v1/preview_server.py` | Local preview proxying /health,/search to production. |
| `lank-schema/` | Schema Steward DDL (`postgres/00..06_*.sql`), JSON schemas, validation tools. Examples (real record data) excluded. |

## Configuration / secrets (env vars, never committed)
- `DATABASE_URL` — Postgres DSN used by `app.py` (e.g. `postgresql://lank:${LANK_PG_PASSWORD}@127.0.0.1:5432/lank`). Password is box secret `LANK_PG_PASSWORD`.
- `LANK_STATIC_DIR` — optional, default `/opt/lank-search/static`.
- `PROXMOX_API_TOKEN_SECRET` (+ optional `PROXMOX_API_TOKEN_ID`, default `sitehost@pve@pam!api`) — for `sitehost/pve.py`.
  The box original read this from `/home/box/agent-data/box-secrets.json`; replaced with env var for the repo.

## Not in this repo (not found on the box)
The deployed VM copy was not pulled (guest agent down). No systemd unit file, nginx config, or `.env` for the
site exists on the box; they live only on the VM / OPNsense. Add them later from the VM, secrets redacted.
