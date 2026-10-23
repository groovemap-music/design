#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Compact one MusicBrainz JSON dump member into $W/data/mb_<kind>_<dump>.tsv.gz.
#   stream_mb.sh 20261017-001001 release   # 23 GB, streamed, never written
# A member already in the shared cache (~/.cache/groovemap-spikes/dumps/
# musicbrainz_<dump>_<kind>.tar.xz) is read from there instead of downloaded. tar stops
# reading once the member is out, so curl and xz may die of SIGPIPE (141) after the
# extractor has seen everything. Only tar and the extractor must exit 0.
set -euo pipefail
DUMP=$1
KIND=$2
W=${W:-$HOME/.cache/groovemap-spikes/gm-design-loj9}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-python}
CACHED=$HOME/.cache/groovemap-spikes/dumps/musicbrainz_${DUMP}_${KIND}.tar.xz
mkdir -p "$W/data"
OUT=$W/data/mb_${KIND}_${DUMP}.tsv.gz
if [[ -s $CACHED && ! -e $CACHED.lock ]]; then
  READ=(cat "$CACHED")
else
  READ=(curl -sfSL --speed-limit 100000 --speed-time 120 "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/$DUMP/$KIND.tar.xz")
fi
set +o pipefail
"${READ[@]}" | xz -dc -T0 | tar -xf - -O "mbdump/$KIND" | "$PY" "$HERE/extract_mb.py" "$KIND" "$OUT.part"
status=("${PIPESTATUS[@]}")
echo "pipe status ${status[*]}" >&2
for i in 0 1; do [[ ${status[$i]} == 0 || ${status[$i]} == 141 ]] || exit "${status[$i]}"; done
[[ ${status[2]} == 0 && ${status[3]} == 0 ]] || exit 1
gzip -t "$OUT.part"
mv "$OUT.part" "$OUT"
