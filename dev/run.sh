#!/usr/bin/env bash
# Run search and the dashboard on this machine: http://127.0.0.1:8000/
# Local Postgres only. A .env file is loaded when present, and a remote
# DATABASE_URL is refused so this cannot point at sites by accident.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -d /Applications/Postgres.app/Contents/Versions/latest/bin ]]; then
  export PATH="/Applications/Postgres.app/Contents/Versions/latest/bin:$PATH"
fi
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

DB="${LANK_DB:-lank}"
if [[ -z ${DATABASE_URL:-} ]]; then
  export DATABASE_URL="postgresql:///${DB}"
fi
python3 - "$DATABASE_URL" <<'PY'
import sys
from urllib.parse import urlparse
host = urlparse(sys.argv[1]).hostname
if host not in (None, "", "localhost", "127.0.0.1", "::1"):
    sys.exit("refusing DATABASE_URL host %s; local dev does not connect to another machine" % host)
PY

export LANK_STATIC_DIR="${LANK_STATIC_DIR:-$ROOT/site/opr-ui-v1/static}"
export OPR_DASHBOARD_DIR="${OPR_DASHBOARD_DIR:-$ROOT/site/dashboard}"
HOST="${OPR_DEV_HOST:-127.0.0.1}"
PORT="${OPR_DEV_PORT:-8000}"

SECRETS="${OPR_DEV_SECRETS:-$HOME/.config/oldparishrecords}"
mkdir -p "$SECRETS"
chmod 700 "$SECRETS"
if [[ -z ${OPR_CRED_FILE:-} ]]; then
  export OPR_CRED_FILE="$SECRETS/basicauth.txt"
fi
if [[ -z ${OPR_SESSION_KEY_FILE:-} ]]; then
  export OPR_SESSION_KEY_FILE="$SECRETS/session-key"
fi
if [[ ! -f $OPR_CRED_FILE ]]; then
  umask 077
  printf 'user=dev\npass=dev\n' > "$OPR_CRED_FILE"
  echo "Created a local dashboard login: user dev, password dev"
  echo "Credentials file: $OPR_CRED_FILE"
fi

mkdir -p "$OPR_DASHBOARD_DIR/out"
# Copy the source pages when out/ has no real file. A symlink would point
# outside out/, and the file server rejects that.
if [[ -L $OPR_DASHBOARD_DIR/out/index.html || ! -e $OPR_DASHBOARD_DIR/out/index.html ]]; then
  rm -f "$OPR_DASHBOARD_DIR/out/index.html"
  cp "$OPR_DASHBOARD_DIR/index.html" "$OPR_DASHBOARD_DIR/out/index.html"
fi
if [[ -f $OPR_DASHBOARD_DIR/goals.html ]] && [[ -L $OPR_DASHBOARD_DIR/out/goals.html || ! -e $OPR_DASHBOARD_DIR/out/goals.html ]]; then
  rm -f "$OPR_DASHBOARD_DIR/out/goals.html"
  cp "$OPR_DASHBOARD_DIR/goals.html" "$OPR_DASHBOARD_DIR/out/goals.html"
fi

if ! psql "$DATABASE_URL" -tAc "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'lank'" 2>/dev/null | grep -q 1; then
  "$ROOT/dev/init-db.sh"
fi

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, psycopg' >/dev/null 2>&1; then
  .venv/bin/pip install -r site/lank-search/requirements.txt
fi

echo "Old Parish Records at http://${HOST}:${PORT}/  (dashboard http://${HOST}:${PORT}/dashboard/)"
exec .venv/bin/uvicorn app:app \
  --app-dir "$ROOT/site/lank-search" \
  --host "$HOST" \
  --port "$PORT" \
  --reload \
  --reload-dir "$ROOT/site/lank-search" \
  --reload-dir "$ROOT/site/dashboard"
