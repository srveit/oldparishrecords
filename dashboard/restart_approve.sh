#!/usr/bin/env bash
# One-command restart of the approve server: stop by PID, wait for exit (KILL after 5s), start, health-check (retry once).
# Prints the gap and the new PID; exit 0 only if the new server answers. Usage: ./restart_approve.sh
source "$(dirname "$(readlink -f "$0")")/svc_lib.sh"
old=$(svc_pids approve_server.py | xargs); t0=$(date +%s.%N)
svc_stop approve_server.py
if ensure_svc approve approve_server.py approve_ok "$D/approve.log" "$D/approve.pid"; then
  t1=$(date +%s.%N); new=$(svc_pids approve_server.py | xargs)
  msg="restart_approve: old pid(s) ${old:-none} -> new ${new}, healthy; gap $(awk "BEGIN{printf \"%.2f\", $t1-$t0}")s (stop+start+health)"
  slog "$msg"; echo "$msg"; exit 0
fi
echo "restart_approve: FAILED, approve server not healthy (see $SVC_LOG, $D/approve.log)"; exit 1
