# OPNsense nginx spec: cookie login for https://oldparishrecords.com/dashboard/

For: OPNsense Steward. Replaces HTTP basic auth on the two dashboard locations with a cookie session
checked through `auth_request`. The box side is already live and tested (see the last section).

The box (<BOX_TAILNET_IP>, `tailscale serve` :80) serves these paths. nginx strips the `/dashboard` prefix:
(Repo copy: `<BOX_TAILNET_IP>` / `<BOX_TAILNET_HOST>` are placeholders for the box's tailnet address and MagicDNS name; the real values are in the live copy on the box, which is not synced.)

| Public URL | Box path | Auth |
|---|---|---|
| `/dashboard/login` (GET form, POST credentials) | `/login` | none (it's the login page) |
| `/dashboard/logout` | `/logout` | none |
| (internal subrequest only) | `/auth/check` → 204 valid / 401 invalid, empty body | none |
| `/dashboard/*` (everything else) | `/*` | `auth_request` |

Cookie set by the box: `opr_dash_session=<HMAC token>; Path=/dashboard/; HttpOnly; Secure; SameSite=Strict; Max-Age=43200`.
The box never sends `WWW-Authenticate`, so browsers will never show the basic-auth pop-up again.

Current layout, from reading nginx.conf (read-only):
* vhost `oldparishrecords.com` = server UUID `c2ddec18-2d85-4a0a-a744-0337db66a8da`. nginx.conf already has
  `include c2ddec18-2d85-4a0a-a744-0337db66a8da_pre/*.conf;` inside that server block, and currently no such directory exists.
* UI location `oldparishrecords-dashboard` (`/dashboard/`): its custom include is `f4b3d162-bdbc-42f6-84d1-4bcfcde773a3_post/opr-dashboard.conf`.
* UI location `oldparishrecords-dashboard-redirect` (`= /dashboard`): its custom include is `fab5ecb1-b320-4a9d-ba24-a885fa5c7954_post/opr-dashboard.conf`.
* http level: nginx.conf has `include http_post/*.conf;` at http scope, and the `http_post/` directory doesn't exist yet.
* `auth_request` is compiled in, because the plugin's own `/opnsense-auth-request` uses it.

All paths below are relative to `/usr/local/etc/nginx/`.

**Validated:** I pasted blocks 1–4 verbatim into a scratch nginx 1.26 on the box. The only change was pointing
`<BOX_TAILNET_IP>` at a local forwarder into the same tailscale serve. `nginx -t` passed, and every test at the bottom
behaved as expected: 301, 302 with next, 401 JSON for API/JSON/non-GET/HEAD, login 200, wrong password 401,
login 303 with the cookie, 200 with the cookie, logout, limit_req 429s, and no WWW-Authenticate anywhere.

---

## 0. OPNsense UI changes (both dashboard locations)

In Services → Nginx → Configuration → HTTP(S) → Locations, edit **oldparishrecords-dashboard** (`/dashboard/`) and
**oldparishrecords-dashboard-redirect** (`= /dashboard`). Clear **Basic Authentication** (the `opr-dashboard-users`
user list) on both so the generated blocks no longer contain `auth_basic` / `auth_basic_user_file`. Save.
After this change, the `opr-dashboard-users` userlist and its htpasswd file on OPNsense are unused. Keep them
until the cookie login is verified, then delete them if you like.

## 1. http level: `http_post/opr-dashboard-auth.conf` (new file)

`limit_req_zone` and `map` are only valid in `http {}`. The plugin generates nginx.conf from its template, but it
already emits `include http_post/*.conf;` at http scope, so a file in that directory is the plugin-compatible place
for them. The plugin also has UI support for request limiting (Access → Limit Zones / Limit Requests, depending on
the version), but it can't express the POST-only key below, so use this file. Check that the file survives
**Apply** and a plugin config regen, the same way the existing `*_post/opr-dashboard.conf` files do.

```nginx
# managed by OPNsense Steward -- OPR dashboard cookie login (http level)

# Rate-limit only POSTs to /dashboard/login (credential attempts). GETs of the form are not counted.
map $request_method $opr_dash_login_key {
    default "";                 # empty key = not limited
    POST    $binary_remote_addr;
}
limit_req_zone $opr_dash_login_key zone=opr_dash_login:1m rate=10r/m;

# Decide whether an unauthenticated request gets JSON 401 (API/XHR/non-GET) or a 302 to the login page.
map $request_method $opr_dash_nonget {
    default 1;
    GET     0;
}
map $http_accept $opr_dash_html {
    default       0;
    "~*text/html" 1;
}
map $uri $opr_dash_apiish {
    default                 0;
    "~^/dashboard/api/"     1;
    "~\.(json|js)$"         1;
}
# "<nonget><html><apiish>": only a GET that accepts text/html and is not an API/.json/.js path gets the redirect.
map "$opr_dash_nonget$opr_dash_html$opr_dash_apiish" $opr_dash_want_json {
    default 1;
    "010"   0;
}
```

## 2. vhost level: `c2ddec18-2d85-4a0a-a744-0337db66a8da_pre/opr-dashboard-auth.conf` (new dir + file)

Create the directory `c2ddec18-2d85-4a0a-a744-0337db66a8da_pre/` (the server block already includes `*.conf` from it).
These are custom locations. They are not UI locations because the plugin UI can't express `internal`,
named locations, or `limit_req` with a custom zone.

```nginx
# managed by OPNsense Steward -- OPR dashboard cookie login (oldparishrecords.com server level)

# Subrequest target for auth_request. The box answers 204 (valid cookie) or 401 (no/invalid/expired cookie).
location = /_opr_dash_auth {
    internal;
    proxy_pass http://<BOX_TAILNET_IP>/auth/check;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header Host <BOX_TAILNET_HOST>;
    proxy_set_header Cookie $http_cookie;
    proxy_set_header Authorization "";
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Original-URI $request_uri;
    proxy_http_version 1.1;
    proxy_connect_timeout 5s;
    proxy_read_timeout 10s;
}

# Where an auth_request 401 lands (error_page 401 = @opr_dash_login in the /dashboard/ location).
location @opr_dash_login {
    default_type application/json;                    # (default_type is not allowed inside "if")
    add_header Cache-Control "no-store" always;
    add_header X-Robots-Tag "noindex, nofollow" always;
    if ($opr_dash_want_json) {
        add_header Cache-Control "no-store" always;
        add_header X-Robots-Tag "noindex, nofollow" always;
        return 401 '{"error":"login required"}';
    }
    # nginx has no built-in urlencode. $request_uri is passed as-is, and the box treats everything after
    # "next=" as the value when it starts with "/". It validates the value (must start with /dashboard/, not //,
    # no dot segments) and falls back to /dashboard/.
    return 302 /dashboard/login?next=$request_uri;
}

# Login page + credential POST. No auth_request here.
location = /dashboard/login {
    limit_req zone=opr_dash_login burst=5 nodelay;
    limit_req_status 429;
    client_max_body_size 8k;
    proxy_pass http://<BOX_TAILNET_IP>/login;          # query string (?next=...) is passed through
    proxy_set_header Host <BOX_TAILNET_HOST>;
    proxy_set_header X-Real-IP $remote_addr;          # box rate-limits per this IP (5 fails / 5 min, 30 global)
    proxy_set_header X-Forwarded-For $remote_addr;    # set, not appended: a client can't spoof it
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix /dashboard;
    proxy_set_header Authorization "";
    proxy_http_version 1.1;
    proxy_cache off;
    proxy_buffering off;
    proxy_read_timeout 30s;
    proxy_hide_header Cache-Control;
    proxy_hide_header X-Robots-Tag;                   # box sends one too; avoid a duplicate header
    add_header Cache-Control "no-store" always;
    add_header X-Robots-Tag "noindex, nofollow" always;
}

location = /dashboard/logout {
    proxy_pass http://<BOX_TAILNET_IP>/logout;
    proxy_set_header Host <BOX_TAILNET_HOST>;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Prefix /dashboard;
    proxy_set_header Authorization "";
    proxy_http_version 1.1;
    proxy_cache off;
    proxy_hide_header Cache-Control;
    proxy_hide_header X-Robots-Tag;                   # box sends one too; avoid a duplicate header
    add_header Cache-Control "no-store" always;
    add_header X-Robots-Tag "noindex, nofollow" always;
}
```

Why the `add_header` lines repeat: `add_header` isn't inherited into a block that defines its own, and an `if`
block counts as its own block. Repeating them keeps the headers on every response.

Exact-match locations (`=`) win over the `/dashboard/` prefix location, so `/dashboard/login` and `/dashboard/logout`
never reach `auth_request`. `/dashboard/login/` (with a trailing slash) is **not** exempt. It falls into the protected location,
which is fine.

## 3. Replace `f4b3d162-bdbc-42f6-84d1-4bcfcde773a3_post/opr-dashboard.conf` (main `/dashboard/` location)

This is the existing file with two lines added (`auth_request`, `error_page 401`). Everything else is unchanged.

```nginx
# managed by /home/grok-ro/bin/add-opr-dashboard.py -- location oldparishrecords-dashboard (/dashboard/)
# Proxies to the box tailscale serve; /dashboard prefix stripped by proxy_pass URI.
# Cookie login: every request is checked by /_opr_dash_auth (box /auth/check). Unauthenticated -> @opr_dash_login.
auth_request /_opr_dash_auth;
error_page 401 = @opr_dash_login;
proxy_set_header Host <BOX_TAILNET_HOST>;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host $host;
proxy_set_header X-Forwarded-Prefix /dashboard;
proxy_set_header Authorization "";
proxy_http_version 1.1;
proxy_cache off;
proxy_buffering off;
proxy_request_buffering on;
proxy_read_timeout 60s;
proxy_pass http://<BOX_TAILNET_IP>/;
add_header X-Robots-Tag "noindex, nofollow" always;
proxy_hide_header Cache-Control;
add_header Cache-Control "no-store" always;
```

Notes:
* A location-level `error_page` replaces all inherited server-level `error_page`s for this location only
  (the 403/404/5xx OPNsense pages). That's harmless, because backend 404s were already passed through (`proxy_intercept_errors off`).
* If the box is unreachable, `auth_request` returns 500 and the user sees the OPNsense 5xx page. The request is never
  passed through unauthenticated.

## 4. Replace `fab5ecb1-b320-4a9d-ba24-a885fa5c7954_post/opr-dashboard.conf` (`= /dashboard`)

No auth is needed any more, so use a plain redirect:

```nginx
# managed by OPNsense Steward -- location oldparishrecords-dashboard-redirect (= /dashboard)
add_header X-Robots-Tag "noindex, nofollow" always;
add_header Cache-Control "no-store" always;
return 301 https://$host/dashboard/;
```

## 5. Apply

`nginx -t`, then Apply in the UI (or `configctl nginx restart`). Then run the tests below.

---

## Tests (run from anywhere on the internet; the password is read from a file and never echoed)

Use the default curl user agent. The vhost returns 418 for python-requests/Python-urllib user agents.

```sh
U=https://oldparishrecords.com; J=$(mktemp); PF=/path/to/file-containing-only-the-password   # mode 600, no newline

# /dashboard -> 301 /dashboard/, no auth, no WWW-Authenticate
curl -sI $U/dashboard | grep -iE '^HTTP|^location|www-auth|cache-control|x-robots'

# Unauthenticated HTML navigation (GET; note curl -I sends HEAD, which counts as non-GET -> 401 JSON) -> 302 to login with next; no WWW-Authenticate
curl -s -D- -o /dev/null -H 'Accept: text/html' "$U/dashboard/segmentation/?x=1" | grep -iE '^HTTP|^location|www-auth|cache-control|x-robots'
#   expect: 302, Location: https://oldparishrecords.com/dashboard/login?next=/dashboard/segmentation/?x=1

# Unauthenticated API / JSON / non-GET -> 401 JSON
curl -si "$U/dashboard/status.json"         | grep -iE '^HTTP|content-type|www-auth|^\{'
curl -si -X POST "$U/dashboard/api/approve" | grep -iE '^HTTP|content-type|www-auth|^\{'
curl -si -H 'Accept: application/json' "$U/dashboard/" | grep -iE '^HTTP|^\{'
#   expect: 401, application/json, {"error":"login required"}, and no WWW-Authenticate

# Login page (no auth) -> 200 with noindex meta
curl -si "$U/dashboard/login?next=/dashboard/" | grep -iE '^HTTP|x-robots|cache-control|www-auth|name="robots"'

# Wrong password -> 401 with inline error, no WWW-Authenticate
curl -si --data-urlencode username=oprdash --data-urlencode password=wrong "$U/dashboard/login" \
  | grep -iE '^HTTP|www-auth|Incorrect'

# Correct password -> 303 + cookie with Path=/dashboard/; HttpOnly; Secure; SameSite=Strict; Max-Age=43200
curl -si -c "$J" --data-urlencode username=oprdash --data-urlencode "password@$PF" \
  --data-urlencode next=/dashboard/ "$U/dashboard/login" | grep -iE '^HTTP|^location|^set-cookie' | sed -E 's/(opr_dash_session=)[^;]*/\1<token>/'

# With the cookie: dashboard and JSON load
curl -s -b "$J" -o /dev/null -w '%{http_code}\n' "$U/dashboard/"             # 200
curl -s -b "$J" -o /dev/null -w '%{http_code}\n' "$U/dashboard/status.json"  # 200
curl -sI -b "$J" "$U/dashboard/" | grep -iE 'cache-control|x-robots'          # no-store / noindex

# Logout -> 303 to /dashboard/login?loggedout=1 and Max-Age=0 cookie; after that the jar can't reach the dashboard
curl -si -b "$J" -c "$J" "$U/dashboard/logout" | grep -iE '^HTTP|^location|^set-cookie'
curl -s -b "$J" -o /dev/null -w '%{http_code}\n' -H 'Accept: text/html' "$U/dashboard/"   # 302

# nginx limit_req on login POSTs (10r/m, burst 5): a quick burst of ~8 POSTs should produce 429s
for i in $(seq 1 8); do curl -s -o /dev/null -w '%{http_code} ' --data 'username=x&password=y' "$U/dashboard/login"; done; echo
#   (the box's own limiter also returns 429 after 5 failures per IP in 5 min; wait 5 minutes afterwards before logging in from that IP)

# Nothing should ever carry WWW-Authenticate
for p in /dashboard /dashboard/ /dashboard/status.json /dashboard/login /dashboard/logout; do curl -sI "$U$p" | grep -i www-auth; done; echo "(no lines above = good)"

rm -f "$J"
```
