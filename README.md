# oldparishrecords (private monorepo)

Two related projects for Old Parish Records:

- **`dashboard/`** — the OPR status dashboard (pipeline status for segmentation / transcription / extraction,
  Approve and confirm-reading endpoints). Live copy runs from `/workspace/horn-wilmes/dashboard` on the Grok box
  (http :8080, approve 127.0.0.1:8081, published on the tailnet; also at oldparishrecords.com/dashboard/ behind
  a dedicated login page at `/dashboard/login` with a signed session cookie, enforced by OPNsense nginx
  `auth_request`; the auth service is in `dashboard-auth/`). See `dashboard/README.md`.
- **`dashboard-auth/`** — the login/session service for the public dashboard (`auth_server.py` on 127.0.0.1:8082,
  `/login`, `/logout`, `/auth/check`), its run/ensure scripts and the nginx spec. See `dashboard-auth/README.md`.
- **`site/`** — the public search site https://oldparishrecords.com/ (FastAPI + Postgres + static UI with
  "Cite this record"), its schema SQL and deploy helpers. See `site/README.md`.

## Secrets
Nothing secret is committed. Required secrets are supplied at runtime:
| Variable | Used by |
|----------|---------|
| `DATABASE_URL` (contains `LANK_PG_PASSWORD`) | `site/sitehost/app/app.py` |
| `PROXMOX_API_TOKEN_SECRET`, `PROXMOX_API_TOKEN_ID` | `site/sitehost/pve.py`, `run_on_vm.py` |
| Dashboard login credentials and session signing key | `dashboard-auth/auth_server.py` (kept in `/home/box/agent-data/secrets/`, never in git) |
| Tailscale node state | `ensure_dashboard.sh` copies it from `/home/box/tailscale/` at runtime; not in git |

## Excluded by design
Backups (`*.bak*`), `__pycache__`, logs, pid files, generated `out/`, runtime state (notify queues, overrides,
auto_transcribe_sent.json, _approve_backups, _selftest), and all data (records.json, manifests, crops,
Stage 0/A/B outputs, parish images, import CSVs, DB dumps, screenshots).
