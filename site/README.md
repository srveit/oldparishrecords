# site/ — oldparishrecords.com source (as found on the Grok box)

Public search site https://oldparishrecords.com/ : FastAPI app `lank-search` (uvicorn :8000, systemd
`lank-search.service`) + static UI in `/opt/lank-search/static/`, Postgres 16 database `lank` (schema `lank`),
on the Proxmox VM "oldparishrecords". Public TLS/reverse proxy is OPNsense nginx (config lives on OPNsense, not here).

| Path | What |
|------|------|
| `sitehost/app/app.py` | Newest backend (Site Host, 2026-09-25): adds `expanded_latin` full-text search. **Prepared, not confirmed deployed.** |
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
