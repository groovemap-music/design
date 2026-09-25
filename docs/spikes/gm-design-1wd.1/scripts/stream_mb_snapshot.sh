#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Stream one MusicBrainz release JSON dump into a compact per-release snapshot.
# Nothing but the compact gzip JSONL is written; the dump itself never touches disk.
#   stream_mb_snapshot.sh 20260919-001001
set -euo pipefail
DUMP=$1
W=${W:-$HOME/.cache/groovemap-spikes/gm-design-1wd.1}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-python}
mkdir -p "$W/data"
URL=https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/$DUMP/release.tar.xz
# bsdtar stops reading once mbdump/release is out, so curl and xz can die of SIGPIPE
# (141) after the parser has seen the whole member. Only tar and the parser must succeed.
set +o pipefail
curl -sfS "$URL" | xz -dc | tar -xf - -O mbdump/release \
  | (cd "$HERE" && "$PY" extract_mb_snapshot.py "$W/data/mb_$DUMP.jsonl.gz.part")
status=("${PIPESTATUS[@]}")
for i in 0 1; do [[ ${status[$i]} == 0 || ${status[$i]} == 141 ]] || exit "${status[$i]}"; done
[[ ${status[2]} == 0 && ${status[3]} == 0 ]] || exit 1
gzip -t "$W/data/mb_$DUMP.jsonl.gz.part"
mv "$W/data/mb_$DUMP.jsonl.gz.part" "$W/data/mb_$DUMP.jsonl.gz"
