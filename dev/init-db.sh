#!/usr/bin/env bash
# Create a local lank database and load the repo schema (00 through 05).
# Uses Postgres on this machine. Does not connect to sites and does not copy records.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -d /Applications/Postgres.app/Contents/Versions/latest/bin ]]; then
  export PATH="/Applications/Postgres.app/Contents/Versions/latest/bin:$PATH"
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
    sys.exit("refusing DATABASE_URL host %s; this script only loads a database on this machine" % host)
PY

name="$(python3 - "$DATABASE_URL" "$DB" <<'PY'
import re, sys
from urllib.parse import urlparse
path = urlparse(sys.argv[1]).path.lstrip("/") or sys.argv[2]
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", path):
    sys.exit("database name must be a plain identifier")
print(path)
PY
)"

if ! psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$name'" | grep -q 1; then
  createdb "$name"
  echo "created database $name"
else
  echo "database $name already exists"
fi

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
for f in 00_book_meta.sql 01_staging.sql 02_normalized.sql 03_views.sql 04_expanded_latin.sql 05_expanded_latin_fixes.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$ROOT/site/lank-schema/postgres/$f"
done
echo "loaded schema lank into $name"
