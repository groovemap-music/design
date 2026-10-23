#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Stream one whole Discogs releases dump into compact arrays, never writing the dump:
# data.discogs.com ignores Range, so a dropped connection cannot resume, and the shared
# disk is too tight to keep a releases dump. The global $DUMPS/.fetch.lock is held for
# the whole stream (discogs_fetch_lock.sh). Success needs curl, gzip (which checks the
# trailer), and the extractor (which checks for </releases>) all to exit 0, and an HTTP
# 200. A 429 backs off exponentially from 60 s, then stops with exit 75.
# Optional second consumer (another spike sharing the one stream): a file
# $W/tee_cmd_<date> holding one shell command that reads the decompressed XML on stdin.
# The stream is tee'd through a FIFO into it, and the pass fails unless it exits 0 too,
# so neither consumer gets a silently truncated pass.
# Usage: PY="uv run python" stream_releases.sh 20261001
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=discogs_fetch_lock.sh
source "$HERE/discogs_fetch_lock.sh"
DATE=$1
W=${W:-$HOME/.cache/groovemap-spikes/gm-design-4804}
PY=${PY:-python}
URL="https://data.discogs.com/?download=data%2F${DATE:0:4}%2Fdiscogs_${DATE}_releases.xml.gz"
OUT="$W/data/releases_${DATE}.npz"
[[ -s "$OUT" ]] && { echo "$OUT exists"; exit 0; }
mkdir -p "$W/data"
HDR=$(mktemp)
trap 'rm -f "$HDR"; release_fetch_lock' EXIT
trap 'exit 143' TERM INT HUP  # so the EXIT trap releases the locks
acquire_fetch_lock "discogs_${DATE}_releases.xml.gz (streamed)"
TEE_FILE="$W/tee_cmd_${DATE}"
for attempt in 0 1 2; do
  echo "attempt $((attempt + 1)) $(date -u +%FT%TZ)" >&2
  if [[ -s "$TEE_FILE" ]]; then
    FIFO=$(mktemp -u)
    mkfifo "$FIFO"
    echo "tee consumer: $(cat "$TEE_FILE")" >&2
    bash -c "$(cat "$TEE_FILE")" < "$FIFO" &
    tee_pid=$!
    curl -sSL -D "$HDR" --speed-limit 100000 --speed-time 120 "$URL" | gzip -dc \
      | tee "$FIFO" | $PY "$HERE/extract_dump.py" releases "$OUT"
    status=("${PIPESTATUS[@]}")
    wait "$tee_pid"
    status+=("$?")
    rm -f "$FIFO"
  else
    curl -sSL -D "$HDR" --speed-limit 100000 --speed-time 120 "$URL" | gzip -dc \
      | $PY "$HERE/extract_dump.py" releases "$OUT"
    status=("${PIPESTATUS[@]}")
  fi
  code=$(http_status "$HDR")
  echo "pipe status ${status[*]} http $code $(date -u +%FT%TZ)" >&2
  ok=1
  for s in "${status[@]}"; do [[ $s == 0 ]] || ok=0; done
  if [[ $code == 200 && $ok == 1 ]]; then exit 0; fi
  rm -f "$OUT"
  if [[ $code == 429 ]]; then
    backoff_or_stop "$attempt" "$HDR"
  else
    sleep 60
  fi
done
exit 1
