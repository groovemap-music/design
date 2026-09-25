#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Run the baseline over the dev and test splits, then evaluate. Rankings and timing
# records go to $W/runs (outside the repository); only aggregates reach results/.
set -euo pipefail
W=${W:-$HOME/.cache/groovemap-spikes/gm-design-1wd.1}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-python}
D=$W/data
R=$W/runs
mkdir -p "$R"
export OMP_NUM_THREADS=4
for split in dev test; do
  /usr/bin/time -l "$PY" "$HERE/run_baseline.py" --queries "$D/queries_$split.jsonl" \
    --pool "$D/pool_releases.jsonl.gz" "$D/pool_masters.jsonl.gz" \
    --out "$R/baseline_$split.jsonl.gz" --timing-out "$R/baseline_$split.timing.json" 2> "$R/baseline_$split.log"
done
(cd "$HERE" && "$PY" collect_results.py "$W" "$HERE/../results")
