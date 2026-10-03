#!/usr/bin/env python3
"""Sites -> box wake link. Tails the sites dashboard notify_queue.jsonl and POSTs each NEW line to the
"OPR approval webhook (server watcher)" routine (same URL + auth as the box's opr_webhook_watcher.py), so the
coordinator on the Grok box is woken and dispatches the Entry Segmenter (segmentation_requested,
segmentation_correction) or handles the other kinds. Stdlib only. De-duplicates by line id.

Payload: {"source": "opr-sites-forwarder", "host": <nodename>, "kind": <kind|action>, "event_id": <id>, "event": <notify line>}
event_id = line "id" > "change_id" > "sha1-" + sha1(raw line)[:16]  (same rule as opr_webhook_watcher.py).

Env (/etc/opr-sites-link.env):
  OPR_WEBHOOK_URL, OPR_WEBHOOK_KEY      (required to post; copy from the box: /home/box/agent-data/secrets/opr-webhook.env)
  OPR_WEBHOOK_HEADER (Authorization)  OPR_WEBHOOK_SCHEME ("Bearer ")
  OPR_QUEUE   (default /opt/oldparishrecords/dashboard/notify_queue.jsonl)
  OPR_FWD_STATE (default /var/lib/opr-sites-link/forwarded_ids.json)
  OPR_ACTIONS (comma list of kind/action values, "*" = all; default "*")
  OPR_POLL_SECONDS (5)  OPR_MAX_BACKOFF (300)
First run without a state file baselines the existing lines (not posted) unless --backfill.
--test posts one {"kind": "selftest", "test": true} payload and exits (not a segmentation request).
"""
import argparse, hashlib, json, os, signal, time, urllib.error, urllib.request

E = os.environ.get
QUEUE = E('OPR_QUEUE', '/opt/oldparishrecords/dashboard/notify_queue.jsonl')
STATE = E('OPR_FWD_STATE', '/var/lib/opr-sites-link/forwarded_ids.json')
URL, KEY = E('OPR_WEBHOOK_URL', ''), E('OPR_WEBHOOK_KEY', '')
HEADER, SCHEME = E('OPR_WEBHOOK_HEADER', 'Authorization'), E('OPR_WEBHOOK_SCHEME', 'Bearer ')
ACTIONS = {a.strip() for a in E('OPR_ACTIONS', '*').split(',') if a.strip()}
POLL, MAX_BACKOFF = float(E('OPR_POLL_SECONDS', '5')), float(E('OPR_MAX_BACKOFF', '300'))
HOST = os.uname().nodename
RUN = True

def log(m): print(time.strftime('%Y-%m-%dT%H:%M:%S%z'), m, flush=True)

def event_id(ev, raw):
    if ev.get('id'): return str(ev['id'])
    if ev.get('change_id'): return str(ev['change_id'])
    return 'sha1-' + hashlib.sha1(raw.encode()).hexdigest()[:16]

def matches(ev): return '*' in ACTIONS or ev.get('kind') in ACTIONS or ev.get('action') in ACTIONS

def read_queue():
    out = []
    try:
        with open(QUEUE, encoding='utf-8') as f:
            for n, raw in enumerate(f, 1):
                raw = raw.strip()
                if not raw: continue
                try: ev = json.loads(raw)
                except ValueError: log(f'skip unparsable line {n}'); continue
                if isinstance(ev, dict): out.append((event_id(ev, raw), ev))
    except FileNotFoundError: log(f'queue not found: {QUEUE}')
    return out

def load_state():
    try:
        with open(STATE) as f: return set(json.load(f).get('posted', [])), True
    except FileNotFoundError: return set(), False

def save_state(ids):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w') as f: json.dump({'posted': sorted(ids)}, f, indent=0)
    os.replace(tmp, STATE)

def post(payload):
    if not URL or not KEY: raise RuntimeError('OPR_WEBHOOK_URL / OPR_WEBHOOK_KEY not set')
    req = urllib.request.Request(URL, data=json.dumps(payload, ensure_ascii=False).encode(), method='POST',
        headers={'Content-Type': 'application/json', 'User-Agent': 'opr-sites-forwarder/1', HEADER: f'{SCHEME}{KEY}'})
    with urllib.request.urlopen(req, timeout=20) as r: return r.status, r.read(500).decode('utf-8', 'replace')

def post_with_retry(payload, tries=None):
    delay, n = 5.0, 0
    while RUN:
        n += 1
        try:
            st, body = post(payload)
            if 200 <= st < 300: return st, body
            err = f'HTTP {st}'
        except urllib.error.HTTPError as e:
            err = f'HTTP {e.code}'
            if e.code in (400, 401, 403, 404, 410, 422): delay = MAX_BACKOFF
        except Exception as e: err = repr(e)
        log(f'post attempt {n} failed: {err}; retry in {delay:.0f}s')
        if tries and n >= tries: raise RuntimeError(err)
        t = 0
        while RUN and t < delay: time.sleep(1); t += 1
        delay = min(delay * 2, MAX_BACKOFF)
    raise SystemExit(0)

def main():
    global RUN
    ap = argparse.ArgumentParser()
    ap.add_argument('--test', action='store_true'); ap.add_argument('--once', action='store_true')
    ap.add_argument('--backfill', action='store_true'); a = ap.parse_args()
    if a.test:
        p = {'source': 'opr-sites-forwarder', 'host': HOST, 'kind': 'selftest', 'test': True,
             'note': 'TEST ONLY - link check from sites; not a segmentation request, no action needed',
             'event_id': 'selftest-' + time.strftime('%Y%m%dT%H%M%S'), 'event': {'kind': 'selftest', 'test': True, 'queue': QUEUE,
             'time': time.strftime('%Y-%m-%dT%H:%M:%S%z')}}
        st, body = post_with_retry(p, tries=3); log(f'test POST -> HTTP {st} {body[:200]!r}'); return
    def stop(*_):
        global RUN
        RUN = False
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    posted, had = load_state()
    if not had and not a.backfill:
        posted = {i for i, _ in read_queue()}; save_state(posted)
        log(f'first run: baselined {len(posted)} existing queue ids (not posted)')
    log(f'watching {QUEUE} actions={sorted(ACTIONS)} url_set={bool(URL)} key_set={bool(KEY)}')
    while RUN:
        for i, ev in read_queue():
            if i in posted or not RUN: continue
            if matches(ev):
                kind = ev.get('kind') or ev.get('action')
                st, _ = post_with_retry({'source': 'opr-sites-forwarder', 'host': HOST, 'kind': kind, 'event_id': i, 'event': ev})
                log(f'posted {i} kind={kind} code={ev.get("code")} -> HTTP {st}')
            posted.add(i); save_state(posted)
        if a.once: break
        for _ in range(int(POLL)):
            if not RUN: break
            time.sleep(1)
    log('stopped')

if __name__ == '__main__': main()
