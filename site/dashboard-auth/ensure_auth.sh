#!/usr/bin/env bash
# Idempotent: starts the auth restart wrapper if missing and restores its three tailscale serve paths on :80.
# Safe to call from ensure_dashboard.sh (after tailscale serve / is up). Never touches the / or /api/approve routes.
D="$(cd "$(dirname "$0")" && pwd)"; SOCK=/run/tailscale/tailscaled.sock; L="$D/ensure.log"
log(){ echo "$(date -Is) $*" >> "$L"; }
running(){ local p; p=$(cat "$D/run_auth.pid" 2>/dev/null) && [ -n "$p" ] && tr "\0" " " < /proc/$p/cmdline 2>/dev/null | grep -q "run_auth.sh"; }
if ! running; then
  (cd "$D" && nohup setsid bash "$D/run_auth.sh" >/dev/null 2>&1 < /dev/null &); log "started run_auth.sh"; sleep 1
fi
ST=$(sudo timeout 10 tailscale --socket=$SOCK serve status 2>/dev/null)
for p in /login /logout /auth/check; do
  if ! grep -qE "^\|-- $p +proxy http://127.0.0.1:8082$p\$" <<<"$ST"; then
    sudo timeout 15 tailscale --socket=$SOCK serve --bg --http=80 --set-path=$p http://127.0.0.1:8082$p >>"$L" 2>&1; log "restored serve path $p"
  fi
done
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8082/auth/check); echo "auth-check-local:$code (401 expected without cookie)"
