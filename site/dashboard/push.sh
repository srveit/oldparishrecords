#!/usr/bin/env bash
# Run by updater.sh after each regen: publish extra static pages.
D="$(cd "$(dirname "$0")" && pwd)"
cp -f "$D/goals.html" "$D/out/goals.html"
