#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Compact one MusicBrainz JSON dump member (release or release-group) into $W/data.
#   stream_mb.sh 20261021-001001 release-group   # cached under the mkdir lock, 1 GB
#   stream_mb.sh 20261021-001001 release         # streamed, never written (23 GB)
# bsdtar stops reading once the member is out, so curl and xz can die of SIGPIPE (141)
# after the parser has seen the whole member. Only tar and the parser must succeed.
set -euo pipefail
DUMP=$1
KIND=$2
W=${W:-$HOME/.cache/groovemap-spikes/gm-design-1h2l}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-python}
mkdir -p "$W/data"
URL=https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/$DUMP/$KIND.tar.xz
OUT=$W/data/mb_${KIND}_$DUMP.tsv.gz
if [[ $KIND == release-group ]]; then
  SRC=$("$HERE/fetch_dump.sh" "$URL" "musicbrainz_${DUMP}_release-group.tar.xz")
  READ=(cat "$SRC")
else
  READ=(curl -sfS "$URL")
fi
set +o pipefail
"${READ[@]}" | xz -dc | tar -xf - -O "mbdump/$KIND" \
  | (cd "$HERE" && "$PY" extract_mb.py "$KIND" "$OUT.part")
status=("${PIPESTATUS[@]}")
for i in 0 1; do [[ ${status[$i]} == 0 || ${status[$i]} == 141 ]] || exit "${status[$i]}"; done
[[ ${status[2]} == 0 && ${status[3]} == 0 ]] || exit 1
gzip -t "$OUT.part"
mv "$OUT.part" "$OUT"
