# sites-link: OPR dashboard on sites <-> Entry Segmenter on the Grok box

**(A) sites -> box (wake):** `opr_notify_forwarder.py` (systemd `opr-notify-forwarder`) tails
`/opt/oldparishrecords/dashboard/notify_queue.jsonl` and POSTs every new line (incl. `segmentation_requested`
from rowedit/updaterow and `segmentation_correction` from a Correct click) to the Grok routine webhook
"OPR approval webhook (server watcher)", same URL + `Authorization: Bearer` key as the box's
`opr_webhook_watcher.py`. Payload `{"source":"opr-sites-forwarder","host","kind","event_id","event":<line>}`.
De-duplicated by line id (state `/var/lib/opr-sites-link/forwarded_ids.json`); first start baselines old lines.

**(B) box -> sites (data):** `opr_seg_pull.py` (systemd `opr-seg-pull`, every 60 s) pulls from the box's
read-only endpoint `http://100.120.170.46/seg-sync/` (tailscale serve on grokbot-box, tailnet only, Host header
`grokbot-box.taileabb91.ts.net`, `Authorization: Bearer <OPR_SEGSYNC_TOKEN>`): crops in each book dir,
`entries/manifest.jsonl`, `entries/_qc/*`, `entries/_corrections/**`, `entries/_overrides/*`, and the
segmentation fields of the box's `overrides.json`. Merge rules are in the script docstring (sites crop locks,
sites corrections and newer sites seg stages are kept). Backups in `entries/_sync_backups/`.
Box side: `/workspace/opr-seg-sync/seg_sync_server.py` on 127.0.0.1:8090.

Install (root, from the repo checkout): `sudo deploy/sites-link/install.sh` (first run writes the
`/etc/opr-sites-link.env` template; fill it, re-run). Check first:
`set -a; . /etc/opr-sites-link.env; set +a; python3 deploy/sites-link/opr_seg_pull.py --once --dry-run -v` and
`python3 deploy/sites-link/opr_notify_forwarder.py --test` (posts a `selftest` payload, not a real request).
