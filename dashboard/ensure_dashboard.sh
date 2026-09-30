#!/usr/bin/env bash
# Idempotent: brings the status dashboard back after a restart of this computer.
# Starts (only if missing) tailscaled, tailscale serve on :80, the updater loop, the http server on :8080, and the approve endpoint on 127.0.0.1:8081.
D=/workspace/horn-wilmes/dashboard; L=$D/ensure.log; SOCK=/run/tailscale/tailscaled.sock
log(){ echo "$(date -Is) $*" >> $L; }
# Health-checked start/wait/retry helpers (approve_ok, http_ok, ensure_svc); "running" = answering HTTP, not pgrep.
source $D/svc_lib.sh
[ -x /usr/sbin/tailscaled ] || { sudo install -m755 /home/box/tailscale/tailscaled /usr/sbin/tailscaled; sudo install -m755 /home/box/tailscale/tailscale /usr/bin/tailscale; log "reinstalled tailscale binaries"; }
if ! pgrep -f "tailscaled --tun=userspace" >/dev/null; then
  sudo mkdir -p /var/lib/tailscale /run/tailscale
  [ -s /var/lib/tailscale/tailscaled.state ] || sudo cp -a /home/box/tailscale/tailscaled.state /var/lib/tailscale/ 2>/dev/null
  sudo nohup /usr/sbin/tailscaled --tun=userspace-networking --state=/var/lib/tailscale/tailscaled.state --socket=$SOCK >/workspace/tailscaled.log 2>&1 &
  sleep 4; sudo timeout 20 tailscale --socket=$SOCK up --hostname=grokbot-box --timeout=15s >>$L 2>&1; log "started tailscaled"
fi
if ! pgrep -f "updater.sh" >/dev/null; then (cd $D && nohup ./updater.sh >/dev/null 2>&1 & echo $! > updater.pid); log "started updater"; fi
ensure_svc http server.py http_ok $D/http.log $D/http.pid || echo "http server on :8080 NOT healthy (see $L)"
if ! sudo timeout 10 tailscale --socket=$SOCK serve status 2>/dev/null | grep -q 8080; then
  sudo timeout 15 tailscale --socket=$SOCK serve --bg --http=80 8080 >>$L 2>&1; log "restored serve"
fi
# Approve endpoint (approve_server.py, 127.0.0.1:8081 only) + its tailnet-only serve path (never Funnel).
ensure_svc approve approve_server.py approve_ok $D/approve.log $D/approve.pid || echo "approve server on :8081 NOT healthy (see $L)"
# (restart: use ./restart_approve.sh, never kill + ensure by hand)
if ! sudo timeout 10 tailscale --socket=$SOCK serve status 2>/dev/null | grep -q /api/approve; then
  sudo timeout 15 tailscale --socket=$SOCK serve --bg --http=80 --set-path=/api/approve http://127.0.0.1:8081/api/approve >>$L 2>&1; log "restored approve path"
fi
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8080/index.html); echo "local:$code approve:$(approve_ok && echo ok || echo DOWN)"
# Login service (Site Host): restores the auth service on 127.0.0.1:8082 and its /login, /logout, /auth/check serve paths (idempotent).
[ -x /workspace/opr-dashboard-auth/ensure_auth.sh ] && /workspace/opr-dashboard-auth/ensure_auth.sh
# OPR approval webhook watcher (Chief Geneologist): keeps the approved-transcription -> webhook poster running (idempotent).
[ -x /workspace/opr-approval-webhook/ensure_watcher.sh ] && /workspace/opr-approval-webhook/ensure_watcher.sh
