#!/usr/bin/env python3
"""OPR dashboard cookie login service (stdlib only).

Listens on 127.0.0.1:8082 (never 0.0.0.0). Published to the tailnet via `tailscale serve` on :80:
    /login       -> http://127.0.0.1:8082/login
    /logout      -> http://127.0.0.1:8082/logout
    /auth/check  -> http://127.0.0.1:8082/auth/check
OPNsense nginx exposes these as https://oldparishrecords.com/dashboard/{login,logout} and uses
/auth/check as its auth_request target for everything else under /dashboard/.

Endpoints (paths as the box sees them; nginx strips the /dashboard prefix):
    GET  /login        HTML form (hidden `next`); 303 to next if already signed in
    POST /login        username/password/next (form-urlencoded) -> 303 + Set-Cookie, or 401 form, or 429
    GET|POST /logout   clears the cookie, 303 /dashboard/login?loggedout=1
    ANY  /auth/check   204 if opr_dash_session cookie is valid and unexpired, else 401 (empty body)
Never sends WWW-Authenticate. Never logs passwords, cookies or tokens.

Credential file (re-read when its mtime/size changes): OPR_CRED_FILE, lines `username=...` / `password=...`
(split on the FIRST '=' or ':'; '#' lines ignored). Signing key: OPR_SESSION_KEY_FILE, created mode 600 with
32 random bytes (hex) if missing, re-read when it changes -> replacing/deleting+restarting the key revokes all sessions.
Token = base64url("v1|user|expiry|nonce") + "." + base64url(HMAC-SHA256(key, payload)).
"""
import base64, collections, hashlib, hmac, html, http.server, os, secrets, sys, threading, time, urllib.parse

HOST = os.environ.get('OPR_AUTH_HOST', '127.0.0.1')
PORT = int(os.environ.get('OPR_AUTH_PORT', '8082'))
CRED_FILE = os.environ.get('OPR_CRED_FILE', '/home/box/agent-data/secrets/opr-dashboard-basicauth.txt')
KEY_FILE = os.environ.get('OPR_SESSION_KEY_FILE', '/home/box/agent-data/secrets/opr-dashboard-session-key')
COOKIE = 'opr_dash_session'
COOKIE_PATH = '/dashboard/'
TTL = int(os.environ.get('OPR_SESSION_TTL', str(24 * 3600)))
DEFAULT_NEXT = '/dashboard/'
LOGIN_URL = '/dashboard/login'
WINDOW = 300                                     # rate-limit window (s)
MAX_FAIL_IP = int(os.environ.get('OPR_MAX_FAIL_IP', '5'))
MAX_FAIL_GLOBAL = int(os.environ.get('OPR_MAX_FAIL_GLOBAL', '30'))
MAX_BODY = 8192

_lock = threading.Lock()
_fail_ip = collections.defaultdict(collections.deque)
_fail_all = collections.deque()
_cache = {}                                      # path -> (stat signature, value)


def log(msg):
    sys.stderr.write('%s %s\n' % (time.strftime('%Y-%m-%dT%H:%M:%S%z'), msg)); sys.stderr.flush()


def _sig(path):
    st = os.stat(path); return (st.st_mtime_ns, st.st_size, st.st_ino)


def load_cred():
    """(username, password) as bytes; cached until the file changes."""
    sig = _sig(CRED_FILE)
    c = _cache.get(CRED_FILE)
    if c and c[0] == sig: return c[1]
    user = pw = None
    with open(CRED_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\r\n')
            if not line.strip() or line.lstrip().startswith('#'): continue
            cut = min([i for i in (line.find('='), line.find(':')) if i >= 0], default=-1)
            if cut < 0: continue
            k, v = line[:cut].strip().lower(), line[cut + 1:]
            if k.startswith('user'): user = v.strip()
            elif k.startswith('pass'): pw = v          # password taken verbatim after the first separator
    if not user or not pw: raise RuntimeError('credential file missing user/pass line')
    val = (user.encode(), pw.encode()); _cache[CRED_FILE] = (sig, val); return val


def load_key():
    if not os.path.exists(KEY_FILE):
        os.makedirs(os.path.dirname(KEY_FILE), mode=0o700, exist_ok=True)
        try:
            fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f: f.write(secrets.token_hex(32) + '\n')
            log('created new session signing key file (mode 600)')
        except FileExistsError: pass
    sig = _sig(KEY_FILE)
    c = _cache.get(KEY_FILE)
    if c and c[0] == sig: return c[1]
    raw = open(KEY_FILE, 'rb').read().strip()
    if len(raw) < 32: raise RuntimeError('session key too short')
    _cache[KEY_FILE] = (sig, raw); return raw


def b64e(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()
def b64d(s): return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def make_token(user):
    payload = ('v1|%s|%d|%s' % (user.decode(), int(time.time()) + TTL, secrets.token_urlsafe(16))).encode()
    return b64e(payload) + '.' + b64e(hmac.new(load_key(), payload, hashlib.sha256).digest())


def token_ok(tok):
    try:
        p64, s64 = tok.split('.', 1)
        payload = b64d(p64)
        if not hmac.compare_digest(hmac.new(load_key(), payload, hashlib.sha256).digest(), b64d(s64)): return False
        ver, user, exp, _nonce = payload.decode().split('|')
        return ver == 'v1' and int(exp) > time.time() and hmac.compare_digest(user.encode(), load_cred()[0])
    except Exception:
        return False


def creds_ok(user, pw):
    cu, cp = load_cred()
    h = lambda b: hashlib.sha256(b).digest()     # equal-length digests -> no length leak
    a = hmac.compare_digest(h(user.encode()), h(cu))
    b = hmac.compare_digest(h(pw.encode()), h(cp))
    return a & b


def safe_next(n):
    if not n or len(n) > 2000 or not n.startswith('/dashboard/') or n.startswith('//'): return DEFAULT_NEXT
    if any(ch in n for ch in '\\\r\n\t') or any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in n): return DEFAULT_NEXT
    path = urllib.parse.unquote(n.split('?', 1)[0].split('#', 1)[0])
    if any(seg in ('.', '..') for seg in path.split('/')) or '\\' in path: return DEFAULT_NEXT
    if path.rstrip('/') in ('/dashboard/login', '/dashboard/logout'): return DEFAULT_NEXT
    return n


def prune(dq, now):
    while dq and dq[0] <= now - WINDOW: dq.popleft()


def limited(ip):
    now = time.time()
    with _lock:
        prune(_fail_all, now); dq = _fail_ip.get(ip)
        if dq is not None:
            prune(dq, now)
            if not dq: _fail_ip.pop(ip, None)
        return len(_fail_all) >= MAX_FAIL_GLOBAL or (dq is not None and len(dq) >= MAX_FAIL_IP)


def record_fail(ip):
    now = time.time()
    with _lock:
        _fail_all.append(now); _fail_ip[ip].append(now)
        if len(_fail_ip) > 10000:                  # memory bound
            for k in [k for k, d in _fail_ip.items() if not d or d[-1] <= now - WINDOW]: _fail_ip.pop(k, None)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="robots" content="noindex,nofollow">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Sign in</title>
<style>
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%%}
body{margin:0;min-height:100vh;min-height:100dvh;display:flex;align-items:center;justify-content:center;
padding:max(16px,env(safe-area-inset-top)) max(16px,env(safe-area-inset-right)) max(16px,env(safe-area-inset-bottom)) max(16px,env(safe-area-inset-left));
background:#f3f4f6;font:17px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#111827}
form{background:#fff;padding:28px 24px 24px;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.12);width:min(380px,100%%)}
h1{font-size:21px;margin:0 0 18px}label{display:block;font-size:16px;font-weight:600;color:#374151;margin:14px 0 6px}
input[type=text],input[type=password]{width:100%%;min-height:48px;padding:11px 12px;border:1px solid #9ca3af;border-radius:8px;font-size:17px;background:#fff;color:#111827}
input:focus{outline:3px solid #0b4f8a;outline-offset:1px;border-color:#0b4f8a}
button{margin-top:22px;width:100%%;min-height:48px;padding:12px;border:0;border-radius:8px;background:#0b4f8a;color:#fff;font-size:17px;font-weight:600;cursor:pointer;touch-action:manipulation}
button:hover,button:focus-visible{background:#083a66}
.msg{display:flex;gap:8px;align-items:flex-start;padding:10px 12px;border-radius:8px;font-size:16px;margin-bottom:8px;border-left:5px solid}
.msg::before{font-weight:700;flex:none}
.err{background:#fdf0e6;color:#8a3a00;border-color:#d55e00}.err::before{content:"\\2716";color:#d55e00}
.ok{background:#e8f1fa;color:#0b4f8a;border-color:#0b4f8a}.ok::before{content:"\\2713"}
</style></head><body>
<form method="post" action="login" autocomplete="on">
<h1>Status dashboard</h1>
%(msg)s
<label for="u">Username</label><input id="u" name="username" type="text" autocomplete="username" autocapitalize="none" spellcheck="false" required value="%(user)s"%(ufocus)s>
<label for="p">Password</label><input id="p" name="password" type="password" autocomplete="current-password" required%(pfocus)s>
<input type="hidden" name="next" value="%(next)s">
<button type="submit">Sign in</button>
</form></body></html>
"""


class H(http.server.BaseHTTPRequestHandler):
    server_version = 'opr-auth'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):            # path only, no query string, never bodies/cookies
        log('%s %s %s %s' % (self.client_ip(), self.command, self.path.split('?', 1)[0], args[1] if len(args) > 1 else ''))

    def client_ip(self):
        ip = (self.headers.get('X-Real-IP') or '').strip()
        if not ip:
            ip = (self.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
        return ip[:64] or self.client_address[0]

    def common_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Robots-Tag', 'noindex, nofollow')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')

    def send(self, code, body=b'', ctype=None, headers=()):
        self.send_response(code)
        self.common_headers()
        for k, v in headers: self.send_header(k, v)
        if ctype:
            self.send_header('Content-Type', ctype)
            if ctype.startswith('text/html'):
                self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.send_header('X-Frame-Options', 'DENY')
        if code != 204: self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD' and body: self.wfile.write(body)

    def route(self):
        u = urllib.parse.urlsplit(self.path)
        return u.path, urllib.parse.parse_qs(u.query, keep_blank_values=True)

    def raw_next(self):
        """`next` from the query. nginx sends login?next=$request_uri UNescaped (it has no urlencode), so a
        raw next like /dashboard/x/?a=1&b=2 would be split by parse_qs. If the query starts with next= and the
        value is not percent-encoded (does not start with %2F), take everything after next= verbatim."""
        qs = urllib.parse.urlsplit(self.path).query
        if qs.startswith('next='):
            v = qs[5:]
            if v.startswith('/'): return v
            return urllib.parse.unquote(v.split('&', 1)[0])
        return (urllib.parse.parse_qs(qs, keep_blank_values=True).get('next') or [''])[0]

    def cookie_tokens(self):
        out = []
        for h in self.headers.get_all('Cookie') or []:
            for part in h.split(';'):
                k, _, v = part.strip().partition('=')
                if k == COOKIE and v: out.append(v.strip().strip('"'))
        return out

    def signed_in(self):
        return any(token_ok(t) for t in self.cookie_tokens()[:5])

    def page(self, code, nxt, msg='', cls='err', user=''):
        m = '<div class="msg %s" role="alert">%s</div>' % (cls, html.escape(msg)) if msg else ''
        body = PAGE % {'msg': m, 'next': html.escape(nxt, quote=True), 'user': html.escape(user, quote=True),
                       'ufocus': '', 'pfocus': ''}
        self.send(code, body.encode(), 'text/html; charset=utf-8')

    def cookie_header(self, value, max_age):
        return ('Set-Cookie', '%s=%s; Path=%s; HttpOnly; Secure; SameSite=Strict; Max-Age=%d' % (COOKIE, value, COOKIE_PATH, max_age))

    # ---- methods ----
    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        path, q = self.route()
        if path == '/auth/check': return self.check()
        if path == '/logout': return self.logout()
        if path == '/login':
            nxt = safe_next(self.raw_next())
            if self.signed_in(): return self.send(303, headers=[('Location', nxt)])
            if 'loggedout' in q: return self.page(200, nxt, 'You have been signed out.', 'ok')
            return self.page(200, nxt)
        self.send(404, b'not found\n', 'text/plain; charset=utf-8')

    def do_POST(self):
        path, _ = self.route()
        if path == '/auth/check': return self.check()
        if path == '/logout': return self.logout()
        if path != '/login': return self.send(404, b'not found\n', 'text/plain; charset=utf-8')
        try: n = int(self.headers.get('Content-Length') or 0)
        except ValueError: n = -1
        if n < 0 or n > MAX_BODY:
            self.close_connection = True
            return self.send(413, b'too large\n', 'text/plain; charset=utf-8')
        raw = self.rfile.read(n) if n else b''
        f = urllib.parse.parse_qs(raw.decode('utf-8', 'replace'), keep_blank_values=True)
        user = (f.get('username') or [''])[0][:200]
        pw = (f.get('password') or [''])[0][:1000]
        nxt = safe_next((f.get('next') or [''])[0])
        ip = self.client_ip()
        if limited(ip):
            log('login rate-limited ip=%s' % ip)
            return self.page(429, nxt, 'Too many failed attempts. Please wait a few minutes and try again.', user=user)
        try: ok = creds_ok(user, pw)
        except Exception as e:
            log('credential load error: %s' % type(e).__name__)
            return self.page(503, nxt, 'Sign-in is temporarily unavailable.', user=user)
        if not ok:
            record_fail(ip); log('login failed ip=%s' % ip)
            return self.page(401, nxt, 'Incorrect username or password.', user=user)
        with _lock: _fail_ip.pop(ip, None)
        log('login ok ip=%s' % ip)
        self.send(303, headers=[self.cookie_header(make_token(load_cred()[0]), TTL), ('Location', nxt)])

    def do_PUT(self): self.other()
    def do_DELETE(self): self.other()
    def do_PATCH(self): self.other()
    def do_OPTIONS(self): self.other()

    def other(self):
        if self.route()[0] == '/auth/check': return self.check()
        self.send(405, b'method not allowed\n', 'text/plain; charset=utf-8', [('Allow', 'GET, POST')])

    def check(self):
        self.send(204 if self.signed_in() else 401)

    def logout(self):
        self.send(303, headers=[self.cookie_header('', 0), ('Location', LOGIN_URL + '?loggedout=1')])


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == '__main__':
    load_key(); load_cred()                        # fail fast; creates key if missing
    log('opr dashboard auth listening on %s:%d' % (HOST, PORT))
    Server((HOST, PORT), H).serve_forever()
