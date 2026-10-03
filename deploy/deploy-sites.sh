#!/usr/bin/env bash
# Deploy this working tree to the sites server. Does not touch the Grok VM.
#
#   deploy/deploy-sites.sh
#   deploy/deploy-sites.sh --dry-run
#
# Syncs the tree to /opt/oldparishrecords (host "sites", override with
# SITES_HOST and SITES_DEST). Generated dashboard output, logs, and pid
# files stay on the server.
#
# Nginx is restarted only when an installed config's contents change:
#   deploy/nginx/oldparishrecords.com.conf
#     -> /etc/nginx/sites-available/oldparishrecords.com
#   deploy/nginx/opr-dashboard-http.conf
#     -> /etc/nginx/conf.d/opr-dashboard-http.conf
# The http file stays in conf.d. map and limit_req_zone are already loaded
# from there; a second copy under sites-enabled would fail nginx -t.
# A failed nginx -t restores the previous files and does not restart.
#
# One app process: systemd lank-search (uvicorn app:app on 127.0.0.1:8000).
# It serves search and /dashboard/ (files and login). Dashboard helpers stay in
# site/dashboard/server.py and are imported; that file is not started here.
# site/lank-search/app.py and dashboard_routes.py are copied to /opt/lank-search/.
# The static UI, venv, and env files there are left alone. The repo copies under
# site/sitehost and site/pve are older and are not installed.
# lank-search is restarted when those two files change, or when :8000 is not
# already answering /dashboard/login. Nginx is restarted after that check, and
# only when a config changed. server.py on 8080 is stopped only after the live
# vhost serves /dashboard/login from lank-search.
# This script does not start the approve server or the status updater.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${SITES_HOST:-sites}"
DEST="${SITES_DEST:-/opt/oldparishrecords}"
DRY=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY=1
elif [[ $# -gt 0 ]]; then
  echo "usage: deploy/deploy-sites.sh [--dry-run]" >&2
  exit 2
fi

SSH=(ssh -o BatchMode=yes "$HOST")
SCP=(scp -o BatchMode=yes)

RSYNC_EXCLUDES=(
  --exclude .git/
  --exclude __pycache__/
  --exclude '*.pyc'
  --exclude .venv/
  --exclude venv/
  --exclude '*.log'
  --exclude '*.pid'
  --exclude out/
  --exclude _selftest/
  --exclude _approve_backups/
  --exclude 'notify_queue*'
  --exclude auto_transcribe_sent.json
  --exclude overrides.json
  --exclude records.json
  --exclude matricula_pg.json
  --exclude .env
  --exclude '.env.*'
  --exclude '*.bak*'
  --exclude '*~'
)

# Move server-only runtime out of the pre-move directories before rsync
# deletes dashboard/ and dashboard-auth/.
preserve_runtime() {
  "${SSH[@]}" bash -s -- "$DEST" "$DRY" <<'EOF'
set -euo pipefail
DEST=$1
DRY=$2
move() {
  local src=$1 dest=$2
  if [[ ! -e $src || -e $dest ]]; then
    return 0
  fi
  if [[ $DRY == 1 ]]; then
    echo "would move $src -> $dest"
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  mv "$src" "$dest"
  echo "moved $src -> $dest"
}
move "$DEST/dashboard/out" "$DEST/site/dashboard/out"
move "$DEST/dashboard/updater.log" "$DEST/site/dashboard/updater.log"
move "$DEST/dashboard-auth/auth.log" "$DEST/site/dashboard-auth/auth.log"
# Pid files and bytecode are excluded from rsync, so they would keep the
# pre-move directories from being removed. The running auth process is
# found from /proc, not from these pid files.
scrub() {
  local dir=$1
  [[ -d $dir ]] || return 0
  if [[ $DRY == 1 ]]; then
    echo "would remove $dir/__pycache__ and $dir/*.pid"
    return 0
  fi
  rm -rf "$dir/__pycache__"
  rm -f "$dir/"*.pid
}
scrub "$DEST/dashboard"
scrub "$DEST/dashboard-auth"
EOF
}

nginx_changed=0
NGINX_BACKUPS=()

install_nginx() {
  local src=$1 dest=$2
  local local_hash remote_hash tmp
  local_hash="$(shasum -a 256 "$src" | awk '{print $1}')"
  remote_hash="$("${SSH[@]}" "sudo sha256sum $(printf %q "$dest") 2>/dev/null" | awk '{print $1}')"
  if [[ -n $remote_hash && $local_hash == "$remote_hash" ]]; then
    echo "nginx unchanged: $dest"
    return 1
  fi
  echo "nginx update: $dest"
  if [[ $DRY == 1 ]]; then
    return 0
  fi
  tmp="$("${SSH[@]}" mktemp /tmp/opr-nginx.XXXXXX)"
  "${SCP[@]}" "$src" "$HOST:$tmp"
  "${SSH[@]}" "sudo cp -a $(printf %q "$dest") $(printf %q "$dest").bak-deploy 2>/dev/null || true; sudo cp $(printf %q "$tmp") $(printf %q "$dest"); rm -f $(printf %q "$tmp")"
  NGINX_BACKUPS+=("$dest")
  return 0
}

restore_nginx() {
  local dest
  for dest in "${NGINX_BACKUPS[@]}"; do
    echo "restoring $dest" >&2
    "${SSH[@]}" "sudo cp -a $(printf %q "$dest").bak-deploy $(printf %q "$dest")"
  done
}

if install_nginx "$ROOT/deploy/nginx/oldparishrecords.com.conf" /etc/nginx/sites-available/oldparishrecords.com; then
  nginx_changed=1
fi
if install_nginx "$ROOT/deploy/nginx/opr-dashboard-http.conf" /etc/nginx/conf.d/opr-dashboard-http.conf; then
  nginx_changed=1
fi

if [[ $nginx_changed == 1 && $DRY == 0 ]]; then
  if ! "${SSH[@]}" sudo nginx -t; then
    echo "nginx -t failed; previous configs restored, nginx not restarted" >&2
    restore_nginx
    exit 1
  fi
  echo "nginx config staged; restart waits until lank-search serves /dashboard/login"
elif [[ $nginx_changed == 1 ]]; then
  echo "dry-run: nginx would be tested and restarted after lank-search serves /dashboard/login"
else
  echo "nginx left running"
fi

preserve_runtime

item="$(mktemp /tmp/opr-deploy.XXXXXX)"
trap 'rm -f "$item"' EXIT
rsync_flags=(-a --delete --itemize-changes "${RSYNC_EXCLUDES[@]}")
if [[ $DRY == 1 ]]; then
  rsync_flags+=(--dry-run)
fi
rsync "${rsync_flags[@]}" "$ROOT/" "$HOST:$DEST/" | tee "$item"

search_differs() {
  local src=$1 dest=$2 local_hash remote_hash
  local_hash="$(shasum -a 256 "$src" | awk '{print $1}')"
  remote_hash="$("${SSH[@]}" "sha256sum $(printf %q "$dest") 2>/dev/null || true" | awk '{print $1}')"
  if [[ -n $remote_hash && $local_hash == "$remote_hash" ]]; then
    echo "lank-search unchanged: $dest"
    return 1
  fi
  echo "lank-search update: $dest"
  return 0
}

search_changed=0
if search_differs "$ROOT/site/lank-search/app.py" /opt/lank-search/app.py; then
  search_changed=1
fi
if search_differs "$ROOT/site/lank-search/dashboard_routes.py" /opt/lank-search/dashboard_routes.py; then
  search_changed=1
fi

if [[ $DRY == 1 ]]; then
  echo "dry-run: lank-search would be restarted when those files differ or :8000/dashboard/login is not 200"
  echo "dry-run: server.py on 8080 would be stopped only after the vhost serves login from lank-search"
  echo "dry-run: nginx restart skipped until a real deploy"
  exit 0
fi

if ! "${SSH[@]}" bash -s -- "$DEST" "$search_changed" <<'EOF'
set -euo pipefail
DEST=$1
SEARCH_CHANGED=$2
APP=/opt/lank-search
code() { curl -s -o /dev/null -w '%{http_code}' --max-time "$1" "$2" || true; }
backend_header() {
  { curl -sI --max-time 5 http://127.0.0.1:8000/dashboard/login || true; } \
    | tr -d '\r' | awk 'tolower($1)=="x-opr-backend:" {print $2}'
}
ready() {
  [[ $(code 5 http://127.0.0.1:8000/health) == 200 ]] \
    && [[ $(code 5 http://127.0.0.1:8000/dashboard/login) == 200 ]] \
    && [[ $(backend_header) == lank-search ]] \
    && [[ $(code 5 http://127.0.0.1:8000/dashboard/status.js) == 200 ]] \
    && [[ $(code 15 'http://127.0.0.1:8000/search?limit=1') == 200 ]] \
    && [[ $(code 5 http://127.0.0.1:8000/) == 200 ]] \
    && [[ $(code 5 http://127.0.0.1:8000/edit/api/whoami) == 403 ]]
}
redact_log() {
  sudo journalctl -u lank-search -n 40 --no-pager 2>/dev/null \
    | sed -E 's#(postgres(ql)?://)[^[:space:]]+#\1[redacted]#g; s#(OPR_[A-Z0-9_]*(TOKEN|KEY|PASSWORD)=)[^[:space:]]+#\1[redacted]#g' >&2 || true
}
rollback() {
  echo "rolling lank-search back" >&2
  if [[ -f $APP/app.py.bak-deploy ]]; then
    cp -a "$APP/app.py.bak-deploy" "$APP/app.py"
  fi
  if [[ -f $APP/dashboard_routes.py.bak-deploy ]]; then
    cp -a "$APP/dashboard_routes.py.bak-deploy" "$APP/dashboard_routes.py"
  else
    rm -f "$APP/dashboard_routes.py"
  fi
  sudo systemctl restart lank-search
  sleep 0.5
  if [[ $(code 5 http://127.0.0.1:8000/health) != 200 ]]; then
    echo "search did not recover after rollback" >&2
    redact_log
    exit 1
  fi
  echo "search recovered on the previous app" >&2
  exit 1
}
if [[ $SEARCH_CHANGED == 0 ]] && ready; then
  echo "lank-search left running"
  exit 0
fi
[[ -f $DEST/site/lank-search/app.py && -f $DEST/site/lank-search/dashboard_routes.py ]] \
  || { echo "missing site/lank-search app files" >&2; exit 1; }
cp -a "$APP/app.py" "$APP/app.py.bak-deploy"
if [[ -f $APP/dashboard_routes.py ]]; then
  cp -a "$APP/dashboard_routes.py" "$APP/dashboard_routes.py.bak-deploy"
else
  rm -f "$APP/dashboard_routes.py.bak-deploy"
fi
cp "$DEST/site/lank-search/app.py" "$APP/app.py"
cp "$DEST/site/lank-search/dashboard_routes.py" "$APP/dashboard_routes.py"
chmod 644 "$APP/app.py" "$APP/dashboard_routes.py"
if ! sudo systemctl restart lank-search; then
  echo "lank-search restart failed" >&2
  redact_log
  rollback
fi
ok=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if ready; then
    ok=1
    break
  fi
  sleep 0.4
done
if [[ $ok != 1 ]]; then
  echo "lank-search did not serve search and /dashboard/login" >&2
  redact_log
  rollback
fi
echo "lank-search restarted"
EOF
then
  echo "lank-search update failed; nginx not restarted" >&2
  if [[ $nginx_changed == 1 ]]; then
    restore_nginx
  fi
  exit 1
fi

if [[ $nginx_changed == 1 ]]; then
  if ! "${SSH[@]}" sudo nginx -t; then
    echo "nginx -t failed; previous configs restored, nginx not restarted" >&2
    restore_nginx
    exit 1
  fi
  "${SSH[@]}" sudo systemctl restart nginx
  "${SSH[@]}" sudo systemctl is-active nginx
  echo "nginx restarted"
fi

if ! "${SSH[@]}" bash -s -- "$DEST" <<'EOF'
set -euo pipefail
DEST=$1
D=$DEST/site/dashboard
page=$({ curl -s --max-time 5 -H 'Host: oldparishrecords.com' http://127.0.0.1/dashboard/login || true; })
case "$page" in
  *'<!-- opr-lank -->'*) ;;
  *) echo "vhost /dashboard/login is not served by lank-search" >&2; exit 1 ;;
esac
unset page
for path in / /health /dashboard/ /dashboard/login /dashboard/status.js; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H 'Host: oldparishrecords.com' "http://127.0.0.1$path" || true)
  [[ $code == 200 ]] || { echo "vhost $path returned $code" >&2; exit 1; }
done
check=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H 'Host: oldparishrecords.com' http://127.0.0.1/dashboard/auth/check || true)
[[ $check == 401 ]] || { echo "vhost auth check returned $check" >&2; exit 1; }
edit=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H 'Host: oldparishrecords.com' http://127.0.0.1/edit/api/whoami || true)
[[ $edit == 403 ]] || { echo "vhost edit whoami returned $edit" >&2; exit 1; }

stop_matching() {
  local pid cmd cwd
  for pid in /proc/[0-9]*; do
    pid=${pid#/proc/}
    [[ -r /proc/$pid/cmdline ]] || continue
    cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)
    cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || true)
    case "$cmd" in
      *run_auth.sh*|*auth_server.py*|*"python3 $D/server.py"*) printf '%s\n' "$pid"; continue ;;
    esac
    case "$cwd:$cmd" in
      "$D:python3 server.py"*|"$D:"*"$D/server.py"*) printf '%s\n' "$pid" ;;
    esac
  done
}
# The deploy shell's cmdline does not contain these names. Match the listeners only.
if [[ -n $(stop_matching) ]]; then
  for pid in $(stop_matching); do
    kill "$pid" 2>/dev/null || true
  done
  sleep 0.4
  if [[ -n $(stop_matching) ]]; then
    for pid in $(stop_matching); do
      kill -9 "$pid" 2>/dev/null || true
    done
    sleep 0.2
  fi
fi
if [[ -n $(stop_matching) ]]; then
  echo "dashboard listener still running" >&2
  exit 1
fi
if ss -ltn | awk '$4 ~ /:8080$/ {found=1} END {exit !found}'; then
  echo "127.0.0.1:8080 still listening" >&2
  exit 1
fi
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -H 'Host: oldparishrecords.com' http://127.0.0.1/dashboard/ || true)
[[ $code == 200 ]] || { echo "dashboard failed after stopping the old listener ($code)" >&2; exit 1; }
echo "stopped the separate dashboard listener"
EOF
then
  echo "cutover check failed" >&2
  if [[ $nginx_changed == 1 ]]; then
    echo "restoring nginx and restarting it so /dashboard/ stays on the previous upstream" >&2
    restore_nginx
    if "${SSH[@]}" sudo nginx -t; then
      "${SSH[@]}" sudo systemctl restart nginx
    else
      echo "restored nginx config failed nginx -t; left the running nginx as it is" >&2
    fi
  fi
  exit 1
fi
