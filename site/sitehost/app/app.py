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
         f.archival_id, f.scan, f.page, f.entry,
         f.baptism_date AS date_text,
         f.parents_residence AS place_text,
         concat_ws(' ', f.child_name, f.father, f.mother, f.godfather, f.godmother) AS names,
         COALESCE(f.translation_en, f.translation_de, f.transcription_latin) AS snippet,
         st.expanded_latin,
         (%(q)s::text IS NOT NULL AND to_tsvector('simple', lank.fold_search_text(coalesce(st.expanded_latin, st.transcription_latin, ''))) @@ plainto_tsquery('simple', lank.fold_search_text(%(q)s::text))) AS fts_hit
  FROM lank.baptisms_flat f
  JOIN lank.stg_baptisms st ON st.id = f.staging_id
  UNION ALL
  SELECT 'marriage', f.archival_id, f.scan, f.page, f.entry,
         f.marriage_date, COALESCE(f.marriage_place, f.groom_residence, f.bride_residence),
         concat_ws(' ', f.groom_name, f.bride_name, f.groom_father, f.bride_father, f.witness_1, f.witness_2),
         COALESCE(f.translation_en, f.translation_de, f.transcription_latin),
         st.expanded_latin,
         (%(q)s::text IS NOT NULL AND to_tsvector('simple', lank.fold_search_text(coalesce(st.expanded_latin, st.transcription_latin, ''))) @@ plainto_tsquery('simple', lank.fold_search_text(%(q)s::text)))
  FROM lank.marriages_flat f
  JOIN lank.stg_marriages st ON st.id = f.staging_id
  UNION ALL
  SELECT 'death', f.archival_id, f.scan, f.page, f.entry,
         COALESCE(f.death_date, f.burial_date), COALESCE(f.residence, f.burial_place),
         concat_ws(' ', f.deceased_name, f.spouse_or_parents),
         COALESCE(f.translation_en, f.translation_de, f.transcription_latin),
         st.expanded_latin,
         (%(q)s::text IS NOT NULL AND to_tsvector('simple', lank.fold_search_text(coalesce(st.expanded_latin, st.transcription_latin, ''))) @@ plainto_tsquery('simple', lank.fold_search_text(%(q)s::text)))
  FROM lank.deaths_flat f
  JOIN lank.stg_deaths st ON st.id = f.staging_id
  UNION ALL
  SELECT 'communion', f.archival_id, f.scan, f.page, f.entry,
         f.communion_date, f.residence,
         concat_ws(' ', f.communicant_name, f.father, f.mother),
         COALESCE(f.translation_en, f.translation_de, f.transcription_latin),
         st.expanded_latin,
         (%(q)s::text IS NOT NULL AND to_tsvector('simple', lank.fold_search_text(coalesce(st.expanded_latin, st.transcription_latin, ''))) @@ plainto_tsquery('simple', lank.fold_search_text(%(q)s::text)))
  FROM lank.communion_flat f
  JOIN lank.stg_communion st ON st.id = f.staging_id
  UNION ALL
  SELECT 'histnotes', f.archival_id, f.scan, f.page, f.entry,
         f.event_date_text, f.place_text,
         concat_ws(' ', f.primary_name, f.section_label, f.occasion),
         COALESCE(f.translation_en, f.translation_de, f.transcription),
         st.expanded_latin,
         (%(q)s::text IS NOT NULL AND to_tsvector('simple', lank.fold_search_text(coalesce(st.expanded_latin, st.transcription, ''))) @@ plainto_tsquery('simple', lank.fold_search_text(%(q)s::text)))
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
        cols = ["kind", "archival_id", "scan", "page", "entry", "date_text", "place_text", "names", "snippet", "expanded_latin", "fts_hit"]
        hits = [dict(zip(cols, r)) for r in rows]
    return JSONResponse({"count": len(hits), "hits": hits, "query": {k: v for k, v in params.items() if k != "limit"}})
