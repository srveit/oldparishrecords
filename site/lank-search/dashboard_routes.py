"""Dashboard routes for the lank-search process.

Nginx proxies /dashboard/... without stripping the prefix, so these paths are
the public URIs. Login, cookies, and files stay in site/dashboard/server.py.
Importing this module does not listen on a port and does not read secrets
until a request needs them.
"""
from __future__ import annotations

import importlib.util
import json
import mimetypes
import os
import sys
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter(include_in_schema=False)

_CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
_MEDIA = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".map": "application/json; charset=utf-8",
}


def _load_dash():
    candidates = []
    env = os.environ.get("OPR_DASHBOARD_DIR")
    if env:
        candidates.append(Path(env) / "server.py")
    candidates.append(Path("/opt/oldparishrecords/site/dashboard/server.py"))
    here = Path(__file__).resolve().parent
    candidates.append(here.parent / "dashboard" / "server.py")
    candidates.append(here / "server.py")
    for path in candidates:
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("opr_dashboard_server", path)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules["opr_dashboard_server"] = mod
        spec.loader.exec_module(mod)
        return mod
    raise RuntimeError("dashboard server.py not found")


dash = _load_dash()
dash.log("dashboard routes mounted from %s" % dash.HERE)


def _client_ip(request: Request) -> str:
    ip = (request.headers.get("x-real-ip") or "").strip()
    if not ip:
        ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not ip and request.client:
        ip = request.client.host or ""
    return ip[:64]


def _cookie_tokens(request: Request) -> list[str]:
    out = []
    for part in (request.headers.get("cookie") or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == dash.COOKIE and value:
            out.append(value.strip().strip('"'))
    return out


def _signed_in(request: Request) -> bool:
    return any(dash.token_ok(token) for token in _cookie_tokens(request)[:5])


def _raw_next(request: Request) -> str:
    query = request.url.query
    if query.startswith("next="):
        value = query[5:]
        if value.startswith("/"):
            return value
        return urllib.parse.unquote(value.split("&", 1)[0])
    return (urllib.parse.parse_qs(query, keep_blank_values=True).get("next") or [""])[0]


def _cookie(value: str, max_age: int) -> str:
    return "%s=%s; Path=%s; HttpOnly; Secure; SameSite=Strict; Max-Age=%d" % (
        dash.COOKIE, value, dash.COOKIE_PATH, max_age)


def _auth(code: int, body: bytes | None = None, media_type: str | None = None, extra=(), html: bool = False):
    headers = {
        "Cache-Control": "no-store",
        "X-Robots-Tag": "noindex, nofollow",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-OPR-Backend": "lank-search",
    }
    if html:
        headers["Content-Security-Policy"] = _CSP
        headers["X-Frame-Options"] = "DENY"
    for key, value in extra:
        headers[key] = value
    if body is None:
        return Response(status_code=code, headers=headers, media_type=media_type)
    return Response(content=body, status_code=code, headers=headers, media_type=media_type)


def _page(code: int, nxt: str, msg: str = "", cls: str = "err", user: str = ""):
    import html as htmlmod
    note = '<div class="msg %s" role="alert">%s</div>' % (cls, htmlmod.escape(msg)) if msg else ""
    body = dash.PAGE % {
        "msg": note,
        "next": htmlmod.escape(nxt, quote=True),
        "user": htmlmod.escape(user, quote=True),
        "ufocus": "",
        "pfocus": "",
    }
    body = body.replace("</form>", "</form><!-- opr-lank -->", 1)
    return _auth(code, body.encode(), "text/html; charset=utf-8", html=True)


def _cors(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin")
    if origin in dash.ALLOWED_ORIGINS:
        return {
            "Access-Control-Allow-Origin": origin,
            "Vary": "Origin",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-OPR-Approve",
        }
    return {}


def _json(obj, code: int, request: Request):
    body = json.dumps(obj, ensure_ascii=False).encode()
    headers = {"Cache-Control": "no-store", "X-OPR-Backend": "lank-search"}
    headers.update(_cors(request))
    return Response(content=body, status_code=code, headers=headers, media_type="application/json; charset=utf-8")


def _safe_file(rel: str) -> Path | None:
    if not rel or rel.endswith("/"):
        rel = (rel or "") + "index.html"
    if rel.startswith("/") or "\\" in rel or "\x00" in rel or "//" in rel:
        return None
    parts = rel.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return None
    root = Path(dash.OUT).resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        return None
    if target.is_dir():
        target = (target / "index.html").resolve()
        if root not in target.parents:
            return None
    if not target.is_file():
        return None
    return target


def _file_response(target: Path):
    media = _MEDIA.get(target.suffix.lower())
    if media is None:
        guessed = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if guessed.startswith("text/") or guessed in ("application/javascript", "application/json"):
            media = guessed + "; charset=utf-8"
        else:
            media = guessed
    return Response(
        content=target.read_bytes(),
        media_type=media,
        headers={"X-Content-Type-Options": "nosniff", "X-OPR-Backend": "lank-search"},
    )


@router.api_route("/dashboard/auth/check", methods=["GET", "POST", "HEAD", "OPTIONS", "PUT", "DELETE", "PATCH"])
def auth_check(request: Request):
    return _auth(204 if _signed_in(request) else 401)


@router.api_route("/dashboard/logout", methods=["GET", "POST", "HEAD"])
def logout():
    return _auth(303, extra=[("Set-Cookie", _cookie("", 0)), ("Location", dash.LOGIN_URL + "?loggedout=1")])


@router.api_route("/dashboard/login", methods=["GET", "HEAD"])
def login_get(request: Request):
    query = urllib.parse.parse_qs(request.url.query, keep_blank_values=True)
    nxt = dash.safe_next(_raw_next(request))
    if _signed_in(request):
        return _auth(303, extra=[("Location", nxt)])
    if "loggedout" in query:
        return _page(200, nxt, "You have been signed out.", "ok")
    return _page(200, nxt)


@router.post("/dashboard/login")
async def login_post(request: Request):
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = -1
    if length < 0 or length > dash.MAX_BODY:
        return _auth(413, b"too large\n", "text/plain; charset=utf-8")
    raw = await request.body() if length else b""
    if len(raw) > dash.MAX_BODY:
        return _auth(413, b"too large\n", "text/plain; charset=utf-8")
    form = urllib.parse.parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
    user = (form.get("username") or [""])[0][:200]
    password = (form.get("password") or [""])[0][:1000]
    nxt = dash.safe_next((form.get("next") or [""])[0])
    ip = _client_ip(request)
    if dash.limited(ip):
        dash.log("login rate-limited ip=%s" % ip)
        return _page(429, nxt, "Too many failed attempts. Please wait a few minutes and try again.", user=user)
    try:
        ok = dash.creds_ok(user, password)
    except Exception as exc:
        dash.log("credential load error: %s" % type(exc).__name__)
        return _page(503, nxt, "Sign-in is temporarily unavailable.", user=user)
    if not ok:
        dash.record_fail(ip)
        dash.log("login failed ip=%s" % ip)
        return _page(401, nxt, "Incorrect username or password.", user=user)
    with dash._auth_lock:
        dash._fail_ip.pop(ip, None)
    dash.log("login ok ip=%s" % ip)
    token = dash.make_token(dash.load_cred()[0])
    return _auth(303, extra=[("Set-Cookie", _cookie(token, dash.TTL)), ("Location", nxt)])


@router.get("/dashboard/api/features")
def features_get(request: Request):
    return _json(dash.load_features(), 200, request)


@router.post("/dashboard/api/features")
async def features_post(request: Request):
    if not dash.origin_ok(request.headers):
        return _json({"error": "origin/referer not allowed"}, 403, request)
    if request.headers.get("x-opr-approve") != "1":
        return _json({"error": "missing X-OPR-Approve header"}, 403, request)
    raw = await request.body()
    try:
        body = json.loads(raw[:200000] or b"{}")
        key = str(body["feature"])[:300]
        text = str(body.get("description", ""))[:20000]
    except Exception:
        return _json({"error": "bad request"}, 400, request)
    with dash._features_lock:
        data = dash.load_features()
        if text.strip():
            data[key] = text
        else:
            data.pop(key, None)
        tmp = dash.FEATURES + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, dash.FEATURES)
    return _json({"ok": True}, 200, request)


@router.options("/dashboard/api/features")
def features_options(request: Request):
    return Response(status_code=204, headers=_cors(request))


@router.api_route("/dashboard", methods=["GET", "HEAD"])
def dashboard_root():
    return _auth(302, extra=[("Location", "/dashboard/")])


@router.api_route("/dashboard/", methods=["GET", "HEAD"])
def dashboard_index():
    target = _safe_file("")
    if target is None:
        return _auth(404, b"not found\n", "text/plain; charset=utf-8")
    return _file_response(target)


@router.api_route("/dashboard/{rel:path}", methods=["GET", "HEAD"])
def dashboard_file(rel: str):
    target = _safe_file(rel)
    if target is None:
        return _auth(404, b"not found\n", "text/plain; charset=utf-8")
    return _file_response(target)
