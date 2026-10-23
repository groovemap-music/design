#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Fetch one Discogs dump file into the shared cache $DUMPS, under the conventions in
# discogs_fetch_lock.sh: the per-file lock $DUMPS/<file>.lock (exactly one spike
# downloads a given file; the others wait for it), and the global $DUMPS/.fetch.lock
# around the request. The holder writes <file>.part, checks the gzip trailer, and renames
# it to <file>. A finished <file> is never rewritten.
# Usage: fetch_dump.sh 20261001 masters
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=discogs_fetch_lock.sh
source "$HERE/discogs_fetch_lock.sh"
DATE=$1 KIND=$2
FILE="discogs_${DATE}_${KIND}.xml.gz"
URL="https://data.discogs.com/?download=data%2F${DATE:0:4}%2F${FILE}"
mkdir -p "$DUMPS"
[[ -s "$DUMPS/$FILE" ]] && { echo "$DUMPS/$FILE"; exit 0; }
until mkdir "$DUMPS/$FILE.lock" 2>/dev/null; do
  [[ -s "$DUMPS/$FILE" ]] && { echo "$DUMPS/$FILE"; exit 0; }
  sleep 30
done
HDR=$(mktemp)
trap 'rm -f "$DUMPS/$FILE.part" "$HDR"; rmdir "$DUMPS/$FILE.lock" 2>/dev/null; release_fetch_lock' EXIT
trap 'exit 143' TERM INT HUP  # so the EXIT trap releases the locks
acquire_fetch_lock "$FILE"
for attempt in 0 1 2 3 4 5; do
  echo "attempt $((attempt + 1)) $(date -u +%FT%TZ)" >&2
  if curl -sSL -D "$HDR" --speed-limit 100000 --speed-time 120 -o "$DUMPS/$FILE.part" "$URL" \
     && [[ $(http_status "$HDR") == 200 ]] && gzip -t "$DUMPS/$FILE.part"; then
    mv "$DUMPS/$FILE.part" "$DUMPS/$FILE"
    echo "$DUMPS/$FILE"
    exit 0
  fi
  rm -f "$DUMPS/$FILE.part"
  if [[ $(http_status "$HDR") == 429 ]]; then
    backoff_or_stop "$attempt" "$HDR"
  else
    echo "status $(http_status "$HDR"); retrying in 60s" >&2
    sleep 60
  fi
done
exit 1
