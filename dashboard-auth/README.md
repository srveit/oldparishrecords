# dashboard-auth: cookie login for the OPR status dashboard

This replaces the HTTP basic-auth pop-up on https://oldparishrecords.com/dashboard/ with a login page and a signed
session cookie. OPNsense nginx checks the cookie on every dashboard request with `auth_request`.

```
browser ──TLS──> OPNsense nginx (oldparishrecords.com)
                   /dashboard/login, /dashboard/logout ──────────────> box /login, /logout      (no auth)
                   /dashboard/*  ── auth_request /_opr_dash_auth ───> box /auth/check (204 / 401)
                                 └─ 204: proxy ─────────────────────> box /* (dashboard, /api/approve)
                                 └─ 401: @opr_dash_login → 302 /dashboard/login?next=… (HTML GET)
                                                            or 401 {"error":"login required"} (API/JSON/non-GET)
box = the Grok box (<BOX_TAILNET_IP>), `tailscale serve` on :80
```

## Files
| File | Purpose |
|---|---|
| `auth_server.py` | stdlib-only auth service on **127.0.0.1:8082** (never 0.0.0.0) |
| `run_auth.sh` | restart wrapper: restarts `auth_server.py` 2 s after any exit; writes `run_auth.pid`, `auth.pid`, `auth.log` |
| `ensure_auth.sh` | idempotent: starts `run_auth.sh` (nohup + setsid) if it isn't running, and restores the 3 serve paths |
| `NGINX-SPEC.md` | exact OPNsense nginx directives + test curls |

Live copy on the box: `/workspace/opr-dashboard-auth/`.

## Endpoints (box paths; nginx strips `/dashboard`)
* `GET /login`: HTML form (`noindex,nofollow`, no external links). It keeps `next` in a hidden field. If the
  browser already has a valid cookie, it returns a 303 to `next`. `?loggedout=1` shows "You have been signed out."
* `POST /login`: form-urlencoded `username`, `password`, `next`. The username and password are compared in
  constant time (SHA-256 digests + `hmac.compare_digest`).
  * success: `Set-Cookie: opr_dash_session=<token>; Path=/dashboard/; HttpOnly; Secure; SameSite=Strict; Max-Age=43200` + 303 to `next`
  * failure: 401 with the form and an inline error
  * rate limited: 429 with the form and an inline message
  * No endpoint ever sends `WWW-Authenticate`.
* `GET|POST /logout`: sends the same cookie with `Max-Age=0`, then 303 to `/dashboard/login?loggedout=1`. Only
  this browser is signed out. Other sessions stay valid until they expire.
* `ANY /auth/check`: 204 if an `opr_dash_session` cookie is validly signed, unexpired, and for the current
  username. Otherwise 401 with an empty body.

`next` validation: the value must be a relative path starting with `/dashboard/`. These values are rejected and
replaced with `/dashboard/`: anything starting with `//`, containing a backslash or control characters, containing
`.`/`..` segments (including `%2e%2e`), or pointing at `/dashboard/login`. nginx sends `login?next=$request_uri`
unescaped, so when the query starts with `next=/`, everything after `next=` is taken verbatim. Percent-encoded
values (`next=%2Fdashboard%2F…`, as sent by the page JS) are decoded.

Rate limits (in memory, reset on restart):
* 5 failed logins per client IP per 5 minutes
* 30 failed logins in total per 5 minutes

The client IP is taken from `X-Real-IP` (OPNsense sets it to `$remote_addr`), then the first `X-Forwarded-For`
entry, then the TCP peer. Once a limit is hit, even correct passwords get a 429 until the window passes. nginx adds
its own `limit_req` (10 POSTs/min, burst 5) on `/dashboard/login`.

## Secrets (never in git)
* Credentials: `/home/box/agent-data/secrets/opr-dashboard-basicauth.txt` (mode 600). It has a `#` comment line,
  `username=…`, and `password=…`. Each line is split on the first `=` (or `:`), and the password is used verbatim.
  The file is re-read whenever its mtime, size, or inode changes, so a password change takes effect without a restart.
* Session signing key: `/home/box/agent-data/secrets/opr-dashboard-session-key` (mode 600, 32 random bytes as hex).
  It's created automatically on first start if missing and re-read whenever it changes.

Token format: `base64url("v1|<user>|<expiry-epoch>|<nonce>") . base64url(HMAC-SHA256(key, payload))`.

### Key rotation = sign everyone out
Replacing the key invalidates every existing session immediately. No restart is needed, because the key is
re-read when it changes:
```sh
K=/home/box/agent-data/secrets/opr-dashboard-session-key
python3 -c 'import secrets;print(secrets.token_hex(32))' > $K.new && chmod 600 $K.new && mv $K.new $K
```
Deleting the key and restarting the service (`kill "$(cat auth.pid)"`, and the wrapper restarts it) also works.
Changing the username in the credential file also invalidates all sessions. Changing only the password does not;
rotate the key as well if you want that.

## tailscale serve routes (:80, tailnet only, never Funnel)
```
|-- /            proxy http://127.0.0.1:8080              (dashboard static server, unchanged)
|-- /login       proxy http://127.0.0.1:8082/login
|-- /logout      proxy http://127.0.0.1:8082/logout
|-- /auth/check  proxy http://127.0.0.1:8082/auth/check
|-- /api/approve proxy http://127.0.0.1:8081/api/approve  (unchanged)
```
The serve path `/login` matches `/login` and `/login/…` only. `/loginx`, `/auth` and `/auth/other` still go to `/`.
Commands used (they're also in `ensure_auth.sh`):
```sh
sudo tailscale --socket=/run/tailscale/tailscaled.sock serve --bg --http=80 --set-path=/login      http://127.0.0.1:8082/login
sudo tailscale --socket=/run/tailscale/tailscaled.sock serve --bg --http=80 --set-path=/logout     http://127.0.0.1:8082/logout
sudo tailscale --socket=/run/tailscale/tailscaled.sock serve --bg --http=80 --set-path=/auth/check http://127.0.0.1:8082/auth/check
```
The tailnet URL http://<BOX_TAILNET_HOST>/ is still unauthenticated by design. Only the public
OPNsense path is behind the login.

## Run / restart
```sh
bash /workspace/opr-dashboard-auth/ensure_auth.sh     # start if needed + restore serve paths (idempotent)
kill "$(cat /workspace/opr-dashboard-auth/auth.pid)"  # restart the server (wrapper brings it back in ~2 s)
kill "$(cat /workspace/opr-dashboard-auth/run_auth.pid)"  # stop for good (wrapper stops the server too)
tail -f /workspace/opr-dashboard-auth/auth.log        # IP, method, path (no query), status. Never passwords/cookies.
```
There's no systemd on the box, so the service follows the pattern `dashboard/ensure_dashboard.sh` uses: nohup + an
idempotent ensure script. To bring it back after a box restart, call `ensure_auth.sh` at the end of
`ensure_dashboard.sh`.

Environment overrides (for scratch testing): `OPR_AUTH_HOST`, `OPR_AUTH_PORT`, `OPR_CRED_FILE`,
`OPR_SESSION_KEY_FILE`, `OPR_SESSION_TTL`, `OPR_MAX_FAIL_IP`, `OPR_MAX_FAIL_GLOBAL`.

## Page contract (dashboard pages)
* Login is the sibling page `login` next to `api/` (page-relative). Logout is the sibling `logout`.
* A 401 during polling or Approve means the session expired. The page should navigate to
  `login?next=<encodeURIComponent(location.pathname + location.search)>`.

## Caveat: SameSite=Strict
If you follow a link to the dashboard from another site (e.g. an email), the browser doesn't send the cookie on
that first navigation, so you land on the login page even though you're signed in. Reloading, or opening the
dashboard from a bookmark or the address bar, works normally.
