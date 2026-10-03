# oldparishrecords (private monorepo)

Source for Old Parish Records lives under `site/`:

- **`site/lank-search/`** — the one app process on sites. systemd `lank-search.service` runs
  `app:app` on port 8000 and serves search plus `/dashboard/` (files and cookie login).
  `deploy/deploy-sites.sh` copies `app.py` and `dashboard_routes.py` to `/opt/lank-search/`.
- **`site/dashboard/`** — dashboard files, login helpers (`server.py`), and generated `out/`.
  Sites imports `server.py`; it does not listen on 8080 there. See `site/dashboard/README.md`.
- **`site/dashboard-auth/`** — the old separate login launcher. Sites does not start it.
  See `site/dashboard-auth/README.md`.
- The rest of **`site/`** — schema SQL, the static search UI, and older search copies that are
  not what sites runs. See `site/README.md`.

## Run locally

`./dev/run.sh` starts the same process on this machine at http://127.0.0.1:8000/ (dashboard at http://127.0.0.1:8000/dashboard/). It uses the Postgres server on the default local port (PostgreSQL 18 on port 5432), creates a database named `lank` if needed, and loads `site/lank-schema/postgres/` `00` through `05`. The database starts empty. Records are not copied from sites. Postgres.app 16, on port 5433, is left alone.

The first run also creates a Python virtualenv and a local dashboard login, user `dev` and password `dev`, in `~/.config/oldparishrecords/`. A `DATABASE_URL` that points at another machine is refused. `./dev/init-db.sh` reloads the schema.

## Secrets
Nothing secret is committed. Required secrets are supplied at runtime:
| Variable | Used by |
|----------|---------|
| `DATABASE_URL` (contains `LANK_PG_PASSWORD`) | `site/lank-search/app.py` |
| `PROXMOX_API_TOKEN_SECRET`, `PROXMOX_API_TOKEN_ID` | `site/sitehost/pve.py`, `run_on_vm.py` |
| Dashboard login credentials and session signing key | `site/dashboard/server.py` (on sites, `/home/sveit/opr-secrets/`; never in git) |
| Tailscale node state | `site/dashboard/ensure_dashboard.sh` copies it from `/home/box/tailscale/` at runtime; not in git |

## Excluded by design
Backups (`*.bak*`), `__pycache__`, logs, pid files, generated `out/`, runtime state (notify queues, overrides,
auto_transcribe_sent.json, _approve_backups, _selftest), and all data (records.json, manifests, crops,
Stage 0/A/B outputs, parish images, import CSVs, DB dumps, screenshots).
