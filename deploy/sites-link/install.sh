#!/usr/bin/env bash
# Install the OPR sites<->box segmentation link on sites (run as root from the repo checkout).
#   sudo SVC_USER=<user that runs approve_server.py> deploy/sites-link/install.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
ENVF=/etc/opr-sites-link.env
if [ ! -f $ENVF ]; then
  install -m 600 -o root -g root "$HERE/opr-sites-link.env.example" $ENVF
  echo "Wrote template $ENVF: fill in OPR_WEBHOOK_URL/KEY, OPR_SEGSYNC_TOKEN, OPR_ENTRIES/OPR_DASH, then re-run."; exit 1
fi
grep -q '^OPR_WEBHOOK_KEY=.\+' $ENVF && grep -q '^OPR_SEGSYNC_TOKEN=.\+' $ENVF || { echo "$ENVF is missing OPR_WEBHOOK_KEY or OPR_SEGSYNC_TOKEN"; exit 1; }
SVC_USER=${SVC_USER:-$(ps -o user= -p "$(pgrep -f approve_server.py | head -1)" 2>/dev/null || stat -c %U /opt/oldparishrecords/dashboard)}
SVC_USER=$(echo $SVC_USER | tr -d ' ')
echo "service user: $SVC_USER"
unit() {  # name script description
cat > /etc/systemd/system/$1.service <<UNIT
[Unit]
Description=$3
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=$SVC_USER
EnvironmentFile=$ENVF
StateDirectory=opr-sites-link
StateDirectoryMode=0750
ExecStart=/usr/bin/python3 $HERE/$2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
}
unit opr-notify-forwarder opr_notify_forwarder.py "OPR sites -> box: forward notify_queue lines to the Grok routine webhook"
unit opr-seg-pull opr_seg_pull.py "OPR box -> sites: pull Entry Segmenter output from the box seg-sync endpoint"
systemctl daemon-reload
systemctl enable --now opr-notify-forwarder.service opr-seg-pull.service
systemctl --no-pager status opr-notify-forwarder.service opr-seg-pull.service | head -30
