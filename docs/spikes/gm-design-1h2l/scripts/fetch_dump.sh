#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Download one dump into the shared cache under the molecule's mkdir locks, so spike
# developers fetching at the same time never race, truncate each other, or stack
# requests on a rate-limited host.
#   fetch_dump.sh <url> <file-name>
# - <file>.lock: mkdir is atomic. Whoever creates it downloads to <file>.part, checks it,
#   renames it, and removes the lock. A file is complete when it has no .lock beside it.
# - .fetch.lock: held for the whole of any request to data.discogs.com, which answers
#   parallel or repeated requests with a 429 and an hour-long retry-after.
# Everyone else waits. A lock left by a dead process is removed by hand.
set -euo pipefail
URL=$1
NAME=$2
DUMPS=${DUMPS:-$HOME/.cache/groovemap-spikes/dumps}
mkdir -p "$DUMPS"
DEST=$DUMPS/$NAME
LOCK=$DEST.lock
HELD=()
release() { for held in ${HELD[@]+"${HELD[@]}"}; do rmdir "$held" 2>/dev/null || true; done; HELD=(); }
trap release EXIT
acquire() {
  until mkdir "$1" 2>/dev/null; do
    echo "waiting for $(basename "$1") $(date -u +%H:%M:%S)" >&2
    sleep 30
  done
  HELD+=("$1")
}
until [[ -s $DEST && ! -e $LOCK ]]; do
  if mkdir "$LOCK" 2>/dev/null; then
    HELD+=("$LOCK")
    [[ $URL == https://data.discogs.com/* ]] && acquire "$DUMPS/.fetch.lock"
    echo "fetching $NAME $(date -u +%H:%M:%S)" >&2
    curl -sfSL --speed-limit 100000 --speed-time 120 -o "$DEST.part" "$URL"
    case $NAME in
      *.gz) gzip -t "$DEST.part" ;;
      *.xz) xz -t "$DEST.part" ;;
    esac
    mv "$DEST.part" "$DEST"
    release
  else
    echo "waiting for $NAME.lock $(date -u +%H:%M:%S)" >&2
    sleep 30
  fi
done
echo "$DEST"
