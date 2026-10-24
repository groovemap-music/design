#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Stream one MusicBrainz full export into $W/data/mbhist_<part>_<dump>.npz, never writing it.
#   stream_mb_history.sh 20261021-002201 core      # mbdump.tar.bz2, 7 GB
#   stream_mb_history.sh 20261021-002201 derived   # mbdump-derived.tar.bz2, 0.5 GB
set -euo pipefail
DUMP=$1
PART=$2
W=${W:-$HOME/.cache/groovemap-spikes/gm-design-6b8u}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-python}
FILE=mbdump.tar.bz2
[[ $PART == derived ]] && FILE=mbdump-derived.tar.bz2
OUT=$W/data/mbhist_${PART}_${DUMP}.npz
mkdir -p "$W/data"
curl -sfSL --speed-limit 100000 --speed-time 120 "https://data.metabrainz.org/pub/musicbrainz/data/fullexport/$DUMP/$FILE" \
  | bzip2 -dc | (cd "$HERE" && "$PY" extract_mb_history.py "$PART" "$OUT.part.npz")
mv "$OUT.part.npz" "$OUT"
