#!/usr/bin/env bash
# Restart wrapper: keeps auth_server.py (127.0.0.1:8082) running; restarts it 2 s after any exit.
# Start detached with ensure_auth.sh (nohup). Stop: kill "$(cat run_auth.pid)" then "$(cat auth.pid)".
export OPR_SESSION_TTL="${OPR_SESSION_TTL:-86400}"   # session length (s): token expiry + cookie Max-Age
D="$(cd "$(dirname "$0")" && pwd)"
echo $$ > "$D/run_auth.pid"
trap 'kill "$(cat "$D/auth.pid" 2>/dev/null)" 2>/dev/null; exit 0' TERM INT
while true; do
  python3 "$D/auth_server.py" >>"$D/auth.log" 2>&1 &
  echo $! > "$D/auth.pid"
  wait $!; rc=$?
  echo "$(date -Is) auth_server exited (rc=$rc), restarting in 2s" >>"$D/auth.log"
  sleep 2
done
