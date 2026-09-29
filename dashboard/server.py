#!/usr/bin/env python3
"""Serves out/ on 127.0.0.1:8080 (reached only via tailscale serve) and stores Site features descriptions at /api/features.
GET is open; POST (writes features_desc.json) needs X-OPR-Approve: 1 and an allowed Origin/Referer, like approve_server.py.
No page currently calls /api/features (checked 2026-09-29)."""
import http.server, json, os, threading
D = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(D, 'out'); F = os.path.join(D, 'features_desc.json')
lock = threading.Lock()
ALLOWED_ORIGINS = {'http://grokbot-box.taileabb91.ts.net', 'https://grokbot-box.taileabb91.ts.net', 'http://grokbot-box',
                   'https://oldparishrecords.com', 'https://www.oldparishrecords.com'}
def _origin_ok(h):
    o = h.get('Origin')
    if o is not None: return o in ALLOWED_ORIGINS
    return h.get('Referer', '').startswith(tuple(x + '/' for x in ALLOWED_ORIGINS))
def load():
    try: return json.load(open(F))
    except Exception: return {}
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s, *a, **k): super().__init__(*a, directory=OUT, **k)
    def cors(s):
        o = s.headers.get('Origin')
        if o in ALLOWED_ORIGINS:
            s.send_header('Access-Control-Allow-Origin', o); s.send_header('Vary', 'Origin')
            s.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'); s.send_header('Access-Control-Allow-Headers', 'Content-Type, X-OPR-Approve')
    def js(s, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode(); s.send_response(code); s.cors()
        s.send_header('Content-Type', 'application/json; charset=utf-8'); s.send_header('Cache-Control', 'no-store'); s.send_header('Content-Length', str(len(b))); s.end_headers(); s.wfile.write(b)
    def do_OPTIONS(s): s.send_response(204); s.cors(); s.end_headers()
    def do_GET(s):
        if s.path.split('?')[0] == '/api/features': return s.js(load())
        return super().do_GET()
    def do_POST(s):
        if s.path.split('?')[0] != '/api/features': return s.js({'error': 'not found'}, 404)
        if not _origin_ok(s.headers): return s.js({'error': 'origin/referer not allowed'}, 403)
        if s.headers.get('X-OPR-Approve') != '1': return s.js({'error': 'missing X-OPR-Approve header'}, 403)
        try:
            n = int(s.headers.get('Content-Length', 0)); body = json.loads(s.rfile.read(min(n, 200000)) or b'{}')
            key = str(body['feature'])[:300]; text = str(body.get('description', ''))[:20000]
        except Exception: return s.js({'error': 'bad request'}, 400)
        with lock:
            d = load()
            if text.strip(): d[key] = text
            else: d.pop(key, None)
            tmp = F + '.tmp'; json.dump(d, open(tmp, 'w'), ensure_ascii=False, indent=1); os.replace(tmp, F)
        s.js({'ok': True})
http.server.ThreadingHTTPServer(('127.0.0.1', 8080), H).serve_forever()   # loopback only: tailscale serve proxies here
