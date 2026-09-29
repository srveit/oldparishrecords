#!/usr/bin/env bash
# Shared by ensure_dashboard.sh and restart_approve.sh: "running" means answering HTTP, not a pgrep hit or a LISTEN socket.
# Live values are FIXED: inherited env can never redirect the checks or leak into the started servers. Only with SVC_SCRATCH=1
# (scratch tests) are D, APPROVE_PORT, HTTP_PORT, SVC_LOG taken from the environment, and then all four must be set.
if [ "${SVC_SCRATCH:-0}" = 1 ]; then
  : "${D:?}" "${APPROVE_PORT:?}" "${HTTP_PORT:?}" "${SVC_LOG:?}"
  case "$D" in /workspace/horn-wilmes/*) echo "svc_lib: SVC_SCRATCH=1 with the live dashboard dir; refusing" >&2; exit 2;; esac
else
  D=/workspace/horn-wilmes/dashboard; APPROVE_PORT=8081; HTTP_PORT=8080; SVC_LOG=$D/ensure.log
  unset OPR_PORT OPR_RUN_STATUS OPR_ENTRIES OPR_DASH OPR_STAGEA OPR_STAGEB OPR_BACKUPS OPR_EXTRA_ORIGINS OPR_W OPR_APPROVE_URL
fi
slog(){ echo "$(date -Is) $*" >> "$SVC_LOG"; }
# Health checks: the approve server answers GET /api/approve with 405 {"error": "POST only"}; the http server serves index.html (200).
approve_ok(){ curl -s --max-time 2 "http://127.0.0.1:$APPROVE_PORT/api/approve" 2>/dev/null | grep -q '"POST only"'; }
http_ok(){ [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://127.0.0.1:$HTTP_PORT/index.html" 2>/dev/null)" = 200 ]; }
# PIDs of a service: processes whose command line STARTS with "python3 <script>" (never matches a shell that merely mentions it).
svc_pids(){ pgrep -f "^python3 $D/$1( |\$)" 2>/dev/null; }
wait_gone(){ local s=$1 n=$2 i; for ((i=0;i<n*10;i++)); do [ -z "$(svc_pids $s)" ] && return 0; sleep 0.1; done; return 1; }
wait_ok(){ local f=$1 n=$2 i; for ((i=0;i<n*10;i++)); do $f && return 0; sleep 0.1; done; return 1; }
# Start one instance; the pid file gets the real python PID (exec, no wrapper subshell).
svc_start(){ local s=$1 log=$2 pidf=$3; ( cd "$D" && exec nohup python3 "$D/$s" >>"$log" 2>&1 ) & echo $! > "$pidf"; }
svc_stop(){ local s=$1 p; p=$(svc_pids $s); [ -z "$p" ] && return 0; kill $p 2>/dev/null
  wait_gone $s 5 || { slog "$s: pid(s) $p ignored TERM for 5s, sending KILL"; kill -9 $(svc_pids $s) 2>/dev/null; wait_gone $s 2; }; }
# ensure_svc <name> <script> <healthfn> <log> <pidfile>: no-op when healthy. Otherwise give a dying/starting process up to 5s
# (to exit or become healthy), stop a hung one, start, verify health within 5s, retry once. Returns 0 only if healthy.
ensure_svc(){ local name=$1 s=$2 f=$3 log=$4 pidf=$5 i try
  $f && return 0
  for ((i=0;i<50;i++)); do [ -z "$(svc_pids $s)" ] && break; $f && return 0; sleep 0.1; done
  [ -n "$(svc_pids $s)" ] && { slog "$name: pid(s) $(svc_pids $s) alive but not answering for 5s; stopping"; svc_stop $s; }
  for try in 1 2; do
    svc_start $s "$log" "$pidf"
    local k np=$(cat "$pidf"); for ((k=0;k<50;k++)); do $f && break; kill -0 $np 2>/dev/null || break; sleep 0.1; done
    if $f; then slog "started $name (pid $np, healthy, attempt $try)"; return 0; fi
    slog "$name: attempt $try not healthy ($(kill -0 $np 2>/dev/null && echo "no answer in 5s" || echo "exited at once"; true))"; svc_stop $s
  done
  slog "$name: FAILED to start healthy after 2 attempts"; return 1; }
