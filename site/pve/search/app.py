from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import psycopg
from fastapi import FastAPI, Query
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
         archival_id, scan, page, entry,
         baptism_date AS date_text,
         parents_residence AS place_text,
         concat_ws(' ', child_name, father, mother, godfather, godmother) AS names,
         COALESCE(translation_en, translation_de, transcription_latin) AS snippet
  FROM lank.baptisms_flat
  UNION ALL
  SELECT 'marriage', archival_id, scan, page, entry,
         marriage_date, COALESCE(marriage_place, groom_residence, bride_residence),
         concat_ws(' ', groom_name, bride_name, groom_father, bride_father, witness_1, witness_2),
         COALESCE(translation_en, translation_de, transcription_latin)
  FROM lank.marriages_flat
  UNION ALL
  SELECT 'death', archival_id, scan, page, entry,
         COALESCE(death_date, burial_date), COALESCE(residence, burial_place),
         concat_ws(' ', deceased_name, spouse_or_parents),
         COALESCE(translation_en, translation_de, transcription_latin)
  FROM lank.deaths_flat
  UNION ALL
  SELECT 'communion', archival_id, scan, page, entry,
         communion_date, residence,
         concat_ws(' ', communicant_name, father, mother),
         COALESCE(translation_en, translation_de, transcription_latin)
  FROM lank.communion_flat
  UNION ALL
  SELECT 'histnotes', archival_id, scan, page, entry,
         event_date_text, place_text,
         concat_ws(' ', primary_name, section_label, occasion),
         COALESCE(translation_en, translation_de, transcription)
  FROM lank.histnotes_flat
) s
WHERE (%(q)s::text IS NULL OR s.names ILIKE '%%' || %(q)s::text || '%%'
        OR s.place_text ILIKE '%%' || %(q)s::text || '%%'
        OR s.date_text ILIKE '%%' || %(q)s::text || '%%'
        OR s.snippet ILIKE '%%' || %(q)s::text || '%%'
        OR s.names %% %(q)s::text)
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
        cols = ["kind", "archival_id", "scan", "page", "entry", "date_text", "place_text", "names", "snippet"]
        hits = [dict(zip(cols, r)) for r in rows]
    return JSONResponse({"count": len(hits), "hits": hits, "query": {k: v for k, v in params.items() if k != "limit"}})
