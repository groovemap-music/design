#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Compact one Discogs dump into $W/data/discogs_<kind>_<dump>.tsv.gz.
#   stream_discogs.sh 20260901 releases
# A dump already in the shared cache (~/.cache/groovemap-spikes/dumps/
# discogs_<dump>_<kind>.xml.gz, complete when it has no .lock beside it) is read from there.
# Anything else is streamed, never written. Every request to data.discogs.com holds the
# molecule's dumps/.fetch.lock for its whole duration. A failed pass (including HTTP 429)
# backs off from 60 seconds, doubling, for up to 5 passes. A pass counts only if curl, gzip
# (which checks the trailer), and the extractor (which refuses a truncated document) all
# exit 0. The server ignores Range, so a pass always starts from the top.
set -uo pipefail
DUMP=$1
KIND=$2
W=${W:-$HOME/.cache/groovemap-spikes/gm-design-loj9}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-python}
DUMPS=$HOME/.cache/groovemap-spikes/dumps
CACHED=$DUMPS/discogs_${DUMP}_${KIND}.xml.gz
OUT=$W/data/discogs_${KIND}_${DUMP}.tsv.gz
mkdir -p "$W/data" "$DUMPS"

if [[ -s $CACHED && ! -e $CACHED.lock ]]; then
  gzip -dc "$CACHED" | "$PY" "$HERE/extract_discogs.py" "$KIND" "$OUT.part"
  status=("${PIPESTATUS[@]}")
  [[ ${status[0]} == 0 && ${status[1]} == 0 ]] || exit 1
  mv "$OUT.part" "$OUT"
  exit 0
fi

URL="https://data.discogs.com/?download=data%2F${DUMP:0:4}%2Fdiscogs_${DUMP}_${KIND}.xml.gz"
wait_s=60
HOLD=
trap '[[ -n $HOLD ]] && rmdir "$DUMPS/.fetch.lock"' EXIT
for attempt in 1 2 3 4 5; do
  until mkdir "$DUMPS/.fetch.lock" 2>/dev/null; do
    echo "waiting for .fetch.lock $(date -u +%H:%M:%S)" >&2
    sleep 30
  done
  HOLD=1
  echo "attempt $attempt $(date -u +%H:%M:%S)" >&2
  curl -sfSL --speed-limit 100000 --speed-time 120 "$URL" | gzip -dc | "$PY" "$HERE/extract_discogs.py" "$KIND" "$OUT.part"
  status=("${PIPESTATUS[@]}")
  rmdir "$DUMPS/.fetch.lock"
  HOLD=
  echo "pipe status ${status[*]}" >&2
  if [[ ${status[0]} == 0 && ${status[1]} == 0 && ${status[2]} == 0 ]]; then
    mv "$OUT.part" "$OUT"
    exit 0
  fi
  echo "backing off ${wait_s}s" >&2
  sleep "$wait_s"
  wait_s=$((wait_s * 2))
done
exit 1
