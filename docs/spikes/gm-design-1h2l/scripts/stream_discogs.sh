#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Compact one Discogs dump into $W/data.
#   stream_discogs.sh 20261001 masters    # cached under the mkdir lock (about 0.6 GB)
#   stream_discogs.sh 20261001 releases   # streamed, never written (about 11 GB)
# data.discogs.com sends no Content-Length and ignores Range, so a dropped releases
# stream restarts from the top (up to 3 tries). A masters dump already in the shared
# cache is read from there. A pass succeeds only if the download,
# gzip (which checks the trailer), and the parser (which refuses a truncated document)
# all exit 0.
set -uo pipefail
DUMP=$1
KIND=$2
W=${W:-$HOME/.cache/groovemap-spikes/gm-design-1h2l}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-python}
OUT=$W/data/discogs_$DUMP
mkdir -p "$OUT"
MAX_YEAR=$(( ${DUMP:0:4} + 1 ))
URL="https://data.discogs.com/?download=data%2F${DUMP:0:4}%2Fdiscogs_${DUMP}_${KIND}.xml.gz"
if [[ $KIND == masters ]]; then
  SRC=$("$HERE/fetch_dump.sh" "$URL" "discogs_${DUMP}_masters.xml.gz") || exit 1
  gzip -dc "$SRC" | (cd "$HERE" && "$PY" extract_discogs.py masters "$OUT" --max-year "$MAX_YEAR")
  status=("${PIPESTATUS[@]}")
  [[ ${status[0]} == 0 && ${status[1]} == 0 ]] || exit 1
  exit 0
fi
# The stream holds the molecule's dumps/.fetch.lock (see fetch_dump.sh) while it talks
# to data.discogs.com, and backs off from 60 seconds, doubling, between passes.
DUMPS=${DUMPS:-$HOME/.cache/groovemap-spikes/dumps}
HOLD=
trap '[[ -n $HOLD ]] && rmdir "$DUMPS/.fetch.lock"' EXIT
wait_s=60
for attempt in 1 2 3; do
  until mkdir "$DUMPS/.fetch.lock" 2>/dev/null; do
    echo "waiting for .fetch.lock $(date -u +%H:%M:%S)" >&2
    sleep 30
  done
  HOLD=1
  echo "attempt $attempt $(date -u +%H:%M:%S)" >&2
  curl -sfSL --speed-limit 100000 --speed-time 120 "$URL" | gzip -dc \
    | (cd "$HERE" && "$PY" extract_discogs.py releases "$OUT" --max-year "$MAX_YEAR")
  status=("${PIPESTATUS[@]}")
  rmdir "$DUMPS/.fetch.lock"
  HOLD=
  echo "pipe status ${status[*]}" >&2
  [[ ${status[0]} == 0 && ${status[1]} == 0 && ${status[2]} == 0 ]] && exit 0
  sleep "$wait_s"
  wait_s=$((wait_s * 2))
done
exit 1
