#!/usr/bin/env bash
# Regenerates out/status.json + out/status.js every 30 s. Optional push hook: executable push.sh (runs after each regen).
cd "$(dirname "$0")" || exit 1
while true; do
  python3 status.py >/dev/null 2>>updater.log || echo "$(date -Is) status.py failed" >>updater.log
  cp -f index.html out/index.html
  [ -x push.sh ] && ./push.sh >>updater.log 2>&1
  sleep 30
done
