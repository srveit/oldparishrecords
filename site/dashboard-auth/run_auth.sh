#!/usr/bin/env bash
# Restart wrapper for the one dashboard process (files + login) on 127.0.0.1:8080.
# Start detached with ensure_auth.sh (nohup). Stop: kill "$(cat run_auth.pid)" then "$(cat auth.pid)".
export OPR_SESSION_TTL="${OPR_SESSION_TTL:-86400}"   # session length (s): token expiry + cookie Max-Age
# On sites the credential files live here. The Grok box keeps the auth_server.py defaults.
if [[ -z ${OPR_CRED_FILE:-} && -f /home/sveit/opr-secrets/basicauth.txt ]]; then
  export OPR_CRED_FILE=/home/sveit/opr-secrets/basicauth.txt
  export OPR_SESSION_KEY_FILE="${OPR_SESSION_KEY_FILE:-/home/sveit/opr-secrets/session-key}"
fi
D="$(cd "$(dirname "$0")/../dashboard" && pwd)"
WRAP="$(cd "$(dirname "$0")" && pwd)"
echo $$ > "$WRAP/run_auth.pid"
trap 'kill "$(cat "$WRAP/auth.pid" 2>/dev/null)" 2>/dev/null; exit 0' TERM INT
while true; do
  python3 "$D/server.py" >>"$D/http.log" 2>&1 &
  echo $! > "$WRAP/auth.pid"
  wait $!; rc=$?
  echo "$(date -Is) server.py exited (rc=$rc), restarting in 2s" >>"$D/http.log"
  sleep 2
done
