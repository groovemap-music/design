#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Stream the whole Discogs releases dump into the keyed pool, retrying the whole
# stream on failure: data.discogs.com sends no Content-Length and ignores Range, so a
# dropped connection cannot be resumed, and disk is too tight to keep the dump.
# Success needs curl, gzip (which checks the gzip trailer), and the parser (which
# checks for </releases>) to all exit 0.
set -uo pipefail
W=${W:-$HOME/.cache/groovemap-spikes/gm-design-1wd.1}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-python}
URL='https://data.discogs.com/?download=data%2F2026%2Fdiscogs_20260901_releases.xml.gz'
for attempt in 1 2 3; do
  echo "attempt $attempt $(date)" >&2
  curl -sfSL --speed-limit 100000 --speed-time 120 "$URL" | gzip -dc \
    | (cd "$HERE" && "$PY" extract_discogs_releases.py --background-mod 0 \
        "$W/data/blocking_keys.json" "$W/data/pool_releases.jsonl.gz.part")
  status=("${PIPESTATUS[@]}")
  echo "pipe status ${status[*]}" >&2
  if [[ ${status[0]} == 0 && ${status[1]} == 0 && ${status[2]} == 0 ]]; then
    mv "$W/data/pool_releases.jsonl.gz.part" "$W/data/pool_releases.jsonl.gz"
    exit 0
  fi
done
exit 1
