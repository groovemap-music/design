#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Run every measured configuration for spike gm-design-zwy. Rankings and timing
# records go to $W/runs (outside the repository). Sections can run separately:
#   run_all.sh full | bounded | ablation | slices | all
# Each run is its own process under /usr/bin/time -l, so peak RSS is per run.
set -euo pipefail

W=${W:-$HOME/.cache/groovemap-spikes/gm-design-zwy}
HERE=$(cd "$(dirname "$0")" && pwd)
PY=${PY:-python}
D=$W/data
R=$W/runs
mkdir -p "$R"
POOL=("$D/pool_releases.jsonl.gz" "$D/pool_masters.jsonl.gz")
export OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4

run() {
  local name=$1 method=$2 queries=$3
  shift 3
  if [[ -s "$R/$name.timing.json" ]]; then
    echo "skip $name (done)"
    return
  fi
  echo "run $name"
  /usr/bin/time -l "$PY" "$HERE/run_method.py" "$method" --queries "$queries" --pool "${POOL[@]}" \
    --out "$R/$name.jsonl.gz" --timing-out "$R/$name.timing.json" "$@" 2> "$R/$name.log"
}

full() {
  run baseline_10k baseline "$D/queries_test.jsonl"
  run baseline_1k baseline "$D/queries_test.jsonl" --limit 1000
  run semrerank_10k semantica_rerank "$D/queries_test.jsonl"
  run semrerank_1k semantica_rerank "$D/queries_test.jsonl" --limit 1000
  run baseline_kindblind_10k baseline "$D/queries_test.jsonl" --kind-blind
  run semrerank_kindblind_10k semantica_rerank "$D/queries_test.jsonl" --kind-blind
  run semrerank_raw_10k semantica_rerank "$D/queries_test.jsonl" --raw
}

bounded() {
  local b=(--limit 1000 --bounded-pool 20000)
  run baseline_b1k baseline "$D/queries_test.jsonl" "${b[@]}"
  run semrerank_b1k semantica_rerank "$D/queries_test.jsonl" "${b[@]}"
  run blocking_b1k semantica_blocking "$D/queries_test.jsonl" "${b[@]}"
  run native_b1k semantica_native "$D/queries_test.jsonl" "${b[@]}"
  run exhaustive_b1k semantica_exhaustive "$D/queries_test.jsonl" "${b[@]}"
}

ablation() {
  for drop in barcode catno title artist descriptors barcode,catno title,artist; do
    local tag=${drop//,/+}
    run "baseline_drop_${tag}_10k" baseline "$D/queries_test.jsonl" --drop "$drop"
    run "semrerank_drop_${tag}_10k" semantica_rerank "$D/queries_test.jsonl" --drop "$drop"
  done
}

ablation_exhaustive() {
  local b=(--limit 1000 --bounded-pool 20000)
  for drop in barcode catno title artist descriptors barcode,catno title,artist; do
    local tag=${drop//,/+}
    run "exhaustive_drop_${tag}_b1k" semantica_exhaustive "$D/queries_test.jsonl" "${b[@]}" --drop "$drop"
  done
}

slices() {
  run baseline_dev baseline "$D/queries_dev.jsonl"
  run semrerank_dev semantica_rerank "$D/queries_dev.jsonl"
  run baseline_nonlatin baseline "$D/queries_test_nonlatin.jsonl"
  run semrerank_nonlatin semantica_rerank "$D/queries_test_nonlatin.jsonl"
}

case "${1:-all}" in
  full) full ;;
  bounded) bounded ;;
  ablation) ablation ;;
  ablation_exhaustive) ablation_exhaustive ;;
  slices) slices ;;
  all) full; bounded; ablation; slices; ablation_exhaustive ;;
  *) echo "unknown section $1" >&2; exit 2 ;;
esac
