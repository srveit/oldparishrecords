import json, time, sys, urllib.request, urllib.parse, ssl
import os
# Proxmox API token secret comes from the environment (never committed).
# Box-local original read it from /home/box/agent-data/box-secrets.json (card.PROXMOX_API_TOKEN_SECRET).
sec = os.environ.get('PROXMOX_API_TOKEN_SECRET') or sys.exit('set PROXMOX_API_TOKEN_SECRET')
PVE_TOKEN_ID = os.environ.get('PROXMOX_API_TOKEN_ID', 'sitehost@pve@pam!api')
H = {'Authorization': 'PVEAPIToken=' + PVE_TOKEN_ID + '=' + sec}
B = 'https://pve.veithome.com/api2/json/nodes/pve/qemu/107/agent'
def req(method, url, data=None):
    body = None; h = dict(H)
    if data is not None:
        body = json.dumps(data).encode(); h['Content-Type'] = 'application/json'
    r = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print('HTTP', e.code, e.reason, file=sys.stderr)
        if e.code in (401, 403): sys.exit(99)
        raise
def run(cmd, timeout=600):
    pid = req('POST', B + '/exec', {'command': ['bash', '-c', cmd]})['data']['pid']
    t0 = time.time()
    while True:
        d = req('GET', B + '/exec-status?pid=%d' % pid)['data']
        if d.get('exited'):
            return d.get('exitcode'), d.get('out-data', ''), d.get('err-data', '')
        if time.time() - t0 > timeout: raise TimeoutError
        time.sleep(0.5)
def put(local, remote, chunk=30000):
    import hashlib
    data = open(local, 'rb').read()
    run(f"rm -f {remote}")
    for i in range(0, len(data), chunk):
        c, o, e = run(f"python3 -c \"open('{remote}','ab').write(bytes.fromhex('{data[i:i+chunk].hex()}'))\"")
        assert c == 0, e
    c, o, e = run(f"sha256sum {remote}")
    local_h = hashlib.sha256(data).hexdigest()
    print('sha local', local_h, 'remote', o.split()[0], 'OK' if o.split()[0] == local_h else 'MISMATCH')
if __name__ == '__main__':
    if sys.argv[1] == 'put': put(sys.argv[2], sys.argv[3])
    else:
        c, o, e = run(sys.argv[2] if sys.argv[1] == 'run' else open(sys.argv[2]).read())
        print(o, end=''); print(e, end='', file=sys.stderr); print('[exit', c, ']')
