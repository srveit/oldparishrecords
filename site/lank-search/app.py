from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import psycopg
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

DATABASE_URL = os.environ["DATABASE_URL"]
STATIC_DIR = Path(os.environ.get("LANK_STATIC_DIR", "/opt/lank-search/static"))

app = FastAPI(title="Old Parish Records search", version="0.1.0")
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

UNION_SQL = """
SELECT * FROM (
  SELECT 'baptism'::text AS kind,
         f.archival_id, f.scan, f.page, f.entry,
         f.baptism_date AS date_text,
         f.parents_residence AS place_text,
         concat_ws(' ', f.child_name, f.father, f.mother, f.godfather, f.godmother) AS names,
         COALESCE(f.translation_en, f.translation_de, f.transcription_latin) AS snippet,
         st.expanded_latin,
         (%(q)s::text IS NOT NULL AND to_tsvector('simple', lank.fold_search_text(coalesce(st.expanded_latin, st.transcription_latin, ''))) @@ plainto_tsquery('simple', lank.fold_search_text(%(q)s::text))) AS fts_hit,
         f.child_name AS name_value, NULL::text AS spouse_value, NULL::text AS list_type
  FROM lank.baptisms_flat f
  JOIN lank.stg_baptisms st ON st.id = f.staging_id
  UNION ALL
  SELECT 'marriage', f.archival_id, f.scan, f.page, f.entry,
         f.marriage_date, COALESCE(f.marriage_place, f.groom_residence, f.bride_residence),
         concat_ws(' ', f.groom_name, f.bride_name, f.groom_father, f.bride_father, f.witness_1, f.witness_2),
         COALESCE(f.translation_en, f.translation_de, f.transcription_latin),
         st.expanded_latin,
         (%(q)s::text IS NOT NULL AND to_tsvector('simple', lank.fold_search_text(coalesce(st.expanded_latin, st.transcription_latin, ''))) @@ plainto_tsquery('simple', lank.fold_search_text(%(q)s::text)))
         , f.groom_name, f.bride_name, NULL::text
  FROM lank.marriages_flat f
  JOIN lank.stg_marriages st ON st.id = f.staging_id
  UNION ALL
  SELECT 'death', f.archival_id, f.scan, f.page, f.entry,
         COALESCE(f.death_date, f.burial_date), COALESCE(f.residence, f.burial_place),
         concat_ws(' ', f.deceased_name, f.spouse_or_parents),
         COALESCE(f.translation_en, f.translation_de, f.transcription_latin),
         st.expanded_latin,
         (%(q)s::text IS NOT NULL AND to_tsvector('simple', lank.fold_search_text(coalesce(st.expanded_latin, st.transcription_latin, ''))) @@ plainto_tsquery('simple', lank.fold_search_text(%(q)s::text)))
         , f.deceased_name, f.spouse_or_parents, NULL::text
  FROM lank.deaths_flat f
  JOIN lank.stg_deaths st ON st.id = f.staging_id
  UNION ALL
  SELECT 'communion', f.archival_id, f.scan, f.page, f.entry,
         f.communion_date, f.residence,
         concat_ws(' ', f.communicant_name, f.father, f.mother),
         COALESCE(f.translation_en, f.translation_de, f.transcription_latin),
         st.expanded_latin,
         (%(q)s::text IS NOT NULL AND to_tsvector('simple', lank.fold_search_text(coalesce(st.expanded_latin, st.transcription_latin, ''))) @@ plainto_tsquery('simple', lank.fold_search_text(%(q)s::text)))
         , f.communicant_name, NULL::text, NULL::text
  FROM lank.communion_flat f
  JOIN lank.stg_communion st ON st.id = f.staging_id
  UNION ALL
  SELECT 'histnotes', f.archival_id, f.scan, f.page, f.entry,
         f.event_date_text, f.place_text,
         concat_ws(' ', f.primary_name, f.section_label, f.occasion),
         COALESCE(f.translation_en, f.translation_de, f.transcription),
         st.expanded_latin,
         (%(q)s::text IS NOT NULL AND to_tsvector('simple', lank.fold_search_text(coalesce(st.expanded_latin, st.transcription, ''))) @@ plainto_tsquery('simple', lank.fold_search_text(%(q)s::text)))
         , f.primary_name, NULL::text, f.list_type
  FROM lank.histnotes_flat f
  JOIN (
    SELECT list_type, id, expanded_latin, transcription FROM lank.stg_confraternity_enrollment
    UNION ALL
    SELECT list_type, id, expanded_latin, transcription FROM lank.stg_yearly_name_roll
    UNION ALL
    SELECT list_type, id, expanded_latin, transcription FROM lank.stg_ledger_admin
  ) st ON st.list_type = f.list_type AND st.id = f.staging_id
) s
WHERE (%(q)s::text IS NULL OR s.names ILIKE '%%' || %(q)s::text || '%%'
        OR s.place_text ILIKE '%%' || %(q)s::text || '%%'
        OR s.date_text ILIKE '%%' || %(q)s::text || '%%'
        OR s.snippet ILIKE '%%' || %(q)s::text || '%%'
        OR s.names %% %(q)s::text
        OR s.fts_hit)
  AND (%(name)s::text IS NULL OR s.names ILIKE '%%' || %(name)s::text || '%%' OR s.names %% %(name)s::text)
  AND (%(place)s::text IS NULL OR s.place_text ILIKE '%%' || %(place)s::text || '%%')
  AND (%(date)s::text IS NULL OR s.date_text ILIKE '%%' || %(date)s::text || '%%')
  AND (%(kind)s::text IS NULL OR s.kind = %(kind)s::text)
ORDER BY s.date_text NULLS LAST, s.archival_id, s.scan, s.entry
LIMIT %(limit)s
"""


def _blank(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v or None


@app.get("/")
def home():
    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse("<p>Old Parish Records — missing static/index.html</p>", status_code=503)


@app.get("/health")
def health() -> dict[str, Any]:
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            """SELECT current_database() AS db,
                      current_setting('server_version') AS pg,
                      (SELECT count(*) FROM lank.stg_baptisms WHERE deleted_at IS NULL) AS baptisms,
                      (SELECT count(*) FROM lank.stg_marriages WHERE deleted_at IS NULL) AS marriages,
                      (SELECT count(*) FROM lank.stg_deaths WHERE deleted_at IS NULL) AS deaths,
                      (SELECT count(*) FROM lank.stg_communion WHERE deleted_at IS NULL) AS communion,
                      (SELECT count(*) FROM lank.stg_confraternity_enrollment WHERE deleted_at IS NULL)
                        + (SELECT count(*) FROM lank.stg_yearly_name_roll WHERE deleted_at IS NULL)
                        + (SELECT count(*) FROM lank.stg_ledger_admin WHERE deleted_at IS NULL) AS histnotes"""
        ).fetchone()
    return {
        "ok": True,
        "service": "lank-search",
        "database": row[0],
        "postgres": row[1],
        "counts": {
            "baptisms": row[2],
            "marriages": row[3],
            "deaths": row[4],
            "communion": row[5],
            "histnotes": row[6],
        },
    }


@app.get("/search")
def search(
    q: Optional[str] = None,
    name: Optional[str] = None,
    place: Optional[str] = None,
    date: Optional[str] = None,
    kind: Optional[str] = Query(None, description="baptism|marriage|death|communion|histnotes"),
    limit: int = Query(50, ge=1, le=200),
) -> JSONResponse:
    params = {
        "q": _blank(q),
        "name": _blank(name),
        "place": _blank(place),
        "date": _blank(date),
        "kind": _blank(kind),
        "limit": limit,
    }
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(UNION_SQL, params).fetchall()
        cols = ["kind", "archival_id", "scan", "page", "entry", "date_text", "place_text", "names", "snippet", "expanded_latin", "fts_hit",
                "name", "spouse", "list_type"]
        hits = [dict(zip(cols, r)) for r in rows]
    return JSONResponse({"count": len(hits), "hits": hits, "query": {k: v for k, v in params.items() if k != "limit"}})


# =============================================================================
# Owner-only edits of NAME / SPOUSE (2026-09-30). See /workspace/lank-schema/postgres/07_edit_audit.sql.
# Gate: X-OPR-Editor-Token must equal OPR_EDITOR_TOKEN from /etc/lank-search-edit.env. OPNsense injects it
# only after the dashboard cookie passes auth_request and strips any client-supplied copy. Without it: 403,
# always (VM :80/:8000 are reachable on the LAN/tailnet, bypassing OPNsense). Writes also need
# Origin/Referer https://oldparishrecords.com and Content-Type application/json.
# =============================================================================
import collections, hmac, json, re, threading, time, unicodedata
from psycopg import sql as _sql

EDIT_ENV_FILE = os.environ.get("LANK_EDIT_ENV_FILE", "/etc/lank-search-edit.env")
EDIT_ORIGIN = "https://oldparishrecords.com"
EDIT_MAX_LEN = 200
EDIT_RATE_N, EDIT_RATE_WINDOW = 30, 600          # at most 30 writes per 10 minutes (whole app)

# (kind, field) -> column. Anything else: 400.
EDIT_WHITELIST: dict[tuple[str, str], str] = {
    ("baptism", "name"): "child_name",
    ("marriage", "name"): "groom_name",
    ("marriage", "spouse"): "bride_name",
    ("death", "name"): "deceased_name",
    ("death", "spouse"): "spouse_or_parents",
    ("communion", "name"): "communicant_name",
    ("histnotes", "name"): "person_name",
}
# kind -> list of (list_type or None, table, date expression used by /search's date_text)
EDIT_TABLES: dict[str, list[tuple[Optional[str], str, str]]] = {
    "baptism": [(None, "stg_baptisms", "t.baptism_date")],
    "marriage": [(None, "stg_marriages", "t.marriage_date")],
    "death": [(None, "stg_deaths", "COALESCE(t.death_date, t.burial_date)")],
    "communion": [(None, "stg_communion", "t.communion_date")],
    "histnotes": [
        ("confraternity_enrollment", "stg_confraternity_enrollment", "t.list_date"),
        ("yearly_name_roll", "stg_yearly_name_roll", "COALESCE(t.list_date, t.year)"),
        ("ledger_admin", "stg_ledger_admin", "t.entry_date"),
    ],
}
_BIDI = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
_edit_lock = threading.Lock()
_edit_times: collections.deque = collections.deque()
_edit_cfg_cache: dict[str, Any] = {}


def _edit_cfg() -> dict[str, str]:
    """KEY=VALUE file, re-read when it changes. Missing/unreadable -> {} (editing disabled)."""
    try:
        st = os.stat(EDIT_ENV_FILE)
        sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        if _edit_cfg_cache.get("sig") == sig:
            return _edit_cfg_cache["cfg"]
        cfg = {}
        with open(EDIT_ENV_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    cfg[k.strip()] = v.strip()
        _edit_cfg_cache.update(sig=sig, cfg=cfg)
        return cfg
    except OSError:
        return {}


def _deny(code: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=code)


def _token_ok(request: Request) -> bool:
    want = _edit_cfg().get("OPR_EDITOR_TOKEN", "")
    got = request.headers.get("x-opr-editor-token", "")
    if len(want) < 32 or not got:
        return False
    return hmac.compare_digest(got.encode(), want.encode())


def _origin_ok(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is not None:
        return origin == EDIT_ORIGIN
    ref = request.headers.get("referer", "")
    return ref == EDIT_ORIGIN or ref.startswith(EDIT_ORIGIN + "/")


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    return (xff or (request.client.host if request.client else ""))[:200]


def _rate_ok() -> bool:
    now = time.monotonic()
    with _edit_lock:
        while _edit_times and _edit_times[0] <= now - EDIT_RATE_WINDOW:
            _edit_times.popleft()
        if len(_edit_times) >= EDIT_RATE_N:
            return False
        _edit_times.append(now)
        return True


def _clean_new(v: Any) -> Optional[str]:
    if not isinstance(v, str):
        return None
    v = unicodedata.normalize("NFC", v.strip())
    if not v or len(v) > EDIT_MAX_LEN:
        return None
    for ch in v:
        if unicodedata.category(ch) in ("Cc", "Zl", "Zp") or ch in _BIDI:
            return None
    return v


@app.middleware("http")
async def _edit_headers(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/edit/"):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.get("/edit/api/whoami")
def edit_whoami(request: Request):
    if not _token_ok(request):
        return _deny(403, "forbidden")
    fields: dict[str, list[str]] = {}
    for (k, f) in EDIT_WHITELIST:
        fields.setdefault(k, []).append(f)
    return {"editor": _edit_cfg().get("OPR_EDITOR_NAME") or "owner", "fields": fields, "max_len": EDIT_MAX_LEN}


@app.post("/edit/api/field")
async def edit_field(request: Request):
    # 1) injected secret header (403 no matter what else), 2) same-origin, 3) JSON only
    if not _token_ok(request):
        return _deny(403, "forbidden")
    if not _origin_ok(request):
        return _deny(403, "bad origin")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return _deny(415, "content-type must be application/json")
    cfg = _edit_cfg()
    db_url = cfg.get("EDIT_DATABASE_URL")
    if not db_url or not cfg.get("OPR_EDIT_BACKUP_DONE"):
        return _deny(503, "editing not configured (backup marker or DB URL missing)")
    raw = await request.body()
    if len(raw) > 4096:
        return _deny(413, "body too large")
    try:
        body = json.loads(raw)
        assert isinstance(body, dict)
    except Exception:
        return _deny(400, "invalid JSON")
    record, field = body.get("record"), body.get("field")
    old, new = body.get("old"), _clean_new(body.get("new"))
    page, list_type = body.get("page"), body.get("list_type")
    if not isinstance(record, str) or not (3 < len(record) <= 300) or not isinstance(field, str):
        return _deny(400, "record and field are required")
    if old is None:
        old = ""
    if not isinstance(old, str) or len(old) > 1000:
        return _deny(400, "old must be a string")
    if new is None:
        return _deny(400, f"new must be 1-{EDIT_MAX_LEN} characters after trimming, with no control characters")
    if page is not None and not isinstance(page, (str, int)):
        return _deny(400, "bad page")
    if list_type is not None and not isinstance(list_type, str):
        return _deny(400, "bad list_type")
    parts = record.split(":")
    if len(parts) < 4:
        return _deny(400, "record must be kind:archival_id:scan:entry[:date]")
    kind, archival_id, scan, entry_s = parts[0], parts[1], parts[2], parts[3]
    date_text = ":".join(parts[4:]) or None
    column = EDIT_WHITELIST.get((kind, field))
    if column is None:
        return _deny(400, "field not editable for this record kind")
    try:
        entry = int(entry_s)
    except ValueError:
        return _deny(400, "bad entry")
    tables = [t for t in EDIT_TABLES[kind] if list_type in (None, t[0])]
    if not tables:
        return _deny(400, "bad list_type")
    if new == old:
        return _deny(400, "new value is the same as the old value")
    if not _rate_ok():
        return _deny(429, "too many edits; wait a few minutes")

    def where(date_expr: str) -> tuple[_sql.Composable, list[Any]]:
        conds = [_sql.SQL("b.archival_id = %s AND t.scan = %s AND t.entry = %s AND t.deleted_at IS NULL AND b.deleted_at IS NULL")]
        args: list[Any] = [archival_id, scan, entry]
        if page is not None and str(page) != "":
            conds.append(_sql.SQL("t.page = %s")); args.append(str(page))
        if date_text:
            conds.append(_sql.SQL(date_expr + " = %s")); args.append(date_text)
        return _sql.SQL(" AND ").join(conds), args

    editor = cfg.get("OPR_EDITOR_NAME") or "owner"
    with psycopg.connect(db_url, connect_timeout=5, application_name="opr-edit") as conn:
        with conn.transaction():
            # find candidates across the allowed table(s) (no lock yet)
            found = []
            for lt, table, date_expr in tables:
                w, args = where(date_expr)
                q = _sql.SQL("SELECT t.id FROM lank.{} t JOIN lank.books b ON b.id = t.book_id WHERE ").format(_sql.Identifier(table)) + w + _sql.SQL(" LIMIT 3")
                found += [(lt, table, date_expr, r[0]) for r in conn.execute(q, args).fetchall()]
            if len(found) != 1:
                return _deny(409, "record matched %d rows; expected exactly 1 (send page/list_type)" % len(found))
            lt, table, date_expr, row_id = found[0]
            w, args = where(date_expr)
            q = (_sql.SQL("SELECT t.id, t.{col}, b.archival_id, t.scan, t.page, t.entry FROM lank.{tbl} t JOIN lank.books b ON b.id = t.book_id WHERE t.id = %s AND ")
                 .format(col=_sql.Identifier(column), tbl=_sql.Identifier(table)) + w + _sql.SQL(" FOR UPDATE OF t"))
            row = conn.execute(q, [row_id] + args).fetchone()
            if row is None:
                return _deny(409, "record changed; reload and try again")
            current = row[1] if row[1] is not None else ""
            if current != old:
                return JSONResponse(
                    {"detail": "stale: the stored value differs from the old value you sent", "current": current}, status_code=409)
            conn.execute(
                _sql.SQL("UPDATE lank.{tbl} SET {col} = %s WHERE id = %s").format(
                    tbl=_sql.Identifier(table), col=_sql.Identifier(column)), [new, row_id])
            row_pk = {"id": row_id, "archival_id": row[2], "scan": row[3], "page": row[4], "entry": row[5]}
            if lt:
                row_pk["list_type"] = lt
            audit_id = conn.execute(
                """INSERT INTO lank.edit_audit (editor, record_key, table_name, column_name, row_pk, old_value, new_value, client_ip)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s) RETURNING id""",
                [editor, record, table, column, json.dumps(row_pk), row[1], new, _client_ip(request)]).fetchone()[0]
    return {"ok": True, "record": record, "field": field, "value": new, "old": row[1], "audit_id": audit_id}


# Dashboard files and cookie login live in this same process. The routes use the
# full /dashboard prefix so nginx can proxy that prefix without stripping it.
# A failed import must stop startup: search should not stay up without login.
from dashboard_routes import router as dashboard_router

app.include_router(dashboard_router)
