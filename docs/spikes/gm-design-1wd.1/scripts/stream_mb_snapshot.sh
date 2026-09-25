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
curl -sfS "$URL" | xz -dc | tar -xf - -O mbdump/release \
  | (cd "$HERE" && "$PY" extract_mb_snapshot.py "$W/data/mb_$DUMP.jsonl.gz.part")
mv "$W/data/mb_$DUMP.jsonl.gz.part" "$W/data/mb_$DUMP.jsonl.gz"
