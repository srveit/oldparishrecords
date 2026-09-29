#!/usr/bin/env python3
"""Local preview mimicking production: / -> static/index.html, /static/* files,
/health, /search and /record proxied to https://oldparishrecords.com."""
import http.server, os, urllib.request, urllib.error, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
UP = 'https://oldparishrecords.com'
TYPES = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.png': 'image/png'}

class H(http.server.BaseHTTPRequestHandler):
    def send(self, code, body, ctype):
        self.send_response(code); self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store'); self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/':
            return self.file(os.path.join(ROOT, 'index.html'))
        if path.startswith('/static/'):
            fp = os.path.normpath(os.path.join(ROOT, path[len('/static/'):]))
            if not fp.startswith(ROOT): return self.send(404, b'{"detail":"Not Found"}', 'application/json')
            return self.file(fp)
        if path in ('/health', '/search', '/record'):
            try:
                with urllib.request.urlopen(urllib.request.Request(UP + self.path, headers={'User-Agent': 'opr-local-preview/1.0', 'Accept': 'application/json'}), timeout=20) as r:
                    return self.send(r.status, r.read(), r.headers.get('Content-Type', 'application/json'))
            except urllib.error.HTTPError as e:
                return self.send(e.code, e.read(), e.headers.get('Content-Type', 'application/json'))
            except Exception as e:
                return self.send(502, ('{"detail":"%s"}' % e).encode(), 'application/json')
        self.send(404, b'{"detail":"Not Found"}', 'application/json')
    def file(self, fp):
        if not os.path.isfile(fp): return self.send(404, b'{"detail":"Not Found"}', 'application/json')
        with open(fp, 'rb') as f: body = f.read()
        self.send(200, body, TYPES.get(os.path.splitext(fp)[1], 'application/octet-stream'))

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
http.server.ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
