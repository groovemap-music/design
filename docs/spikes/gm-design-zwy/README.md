# Harness for spike gm-design-zwy

This is throwaway code for
[Semantica for cross-catalog identity matching](../gm-design-zwy-semantica-identity-matching.md).
It is not a product package, and no GrooveMap service depends on it. Semantica is
installed only into this harness's isolated Python 3.13 environment. The committed
outputs are the aggregate metrics in `results/`, which contain no ids, names,
barcodes, or catalogue numbers. Dump extracts, sampled pairs, and rankings stay under
`~/.cache/groovemap-spikes/gm-design-zwy/`, outside the repository.

## Files

| File | Role |
| --- | --- |
| `scripts/normalize.py` | Folding, the ADR 0011 barcode and catalogue-number rules plus the two named spike extensions, format families, and the script classifier copied from gm-design-e0b.1 |
| `scripts/extract_mb_releases.py` | Streams a dump-order prefix of the MusicBrainz release JSON dump and keeps releases with a Discogs relation |
| `scripts/sample_queries.py` | Draws the dev, test, and extra non-Latin query sets, and the blocking-key set |
| `scripts/extract_discogs_releases.py` | Streams the whole Discogs releases dump and keeps the targets, every release sharing a blocking key with a query, and a 1% background sample |
| `scripts/extract_discogs_masters.py` | Adds Discogs masters as release-vs-master hard negatives |
| `scripts/matching.py` | The matching unit (`View`), the deterministic baseline, and the Semantica entity encoding |
| `scripts/run_method.py` | Runs one method over one query batch and writes rankings and a timing and RSS record |
| `scripts/run_all.sh` | Every measured configuration |
| `scripts/evaluate.py` | Coverage, ranking, review burden, hard-negative classes, and slices |
| `scripts/license_check.py` | Runs the installed inventory through catalog-api's own license policy (adapted from gm-design-chw.2) |
| `tests/` | Tests over invented fixtures only |
| `results/*.json` | Aggregate metrics, timing records, and the license inventory |

## Reproducing

The runs use Python 3.13 (Semantica 0.7.0 declares `>=3.10,<3.14`) with `uv`. The
virtualenv lives outside the worktree so the repository secret scan never walks it.

```bash
cd docs/spikes/gm-design-zwy
export UV_PROJECT_ENVIRONMENT=~/.cache/groovemap-spikes/gm-design-zwy/.venv
W=~/.cache/groovemap-spikes/gm-design-zwy
mkdir -p $W/data $W/runs
uv sync
uv run pytest

# 1. MusicBrainz: a 600,000-line dump-order prefix, never written to disk.
curl -s https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/20260923-001002/release.tar.xz \
  | xz -dc | tar -xf - -O mbdump/release \
  | uv run python scripts/extract_mb_releases.py --max-scan 600000 > $W/data/mb_linked.jsonl

# 2. Queries and blocking keys.
uv run python scripts/sample_queries.py $W/data/mb_linked.jsonl \
  --test 10000 --dev 2000 --nonlatin-extra 1000 --seed 20260924 --out-dir $W/data

# 3. Discogs: the whole releases dump, streamed, never written to disk.
curl -sL 'https://data.discogs.com/?download=data%2F2026%2Fdiscogs_20260901_releases.xml.gz' \
  | gzip -dc \
  | uv run python scripts/extract_discogs_releases.py $W/data/blocking_keys.json $W/data/pool_releases.jsonl.gz

# 4. Discogs masters (from the shared dump cache, read-only).
gzip -dc ~/.cache/groovemap-spikes/dumps/discogs_20260901_masters.xml.gz \
  | uv run python scripts/extract_discogs_masters.py $W/data/blocking_keys.json \
      $W/data/pool_releases.jsonl.gz $W/data/pool_masters.jsonl.gz

# 5. Every configuration, then the metrics.
PY="uv run python" scripts/run_all.sh all
uv run python scripts/evaluate.py --queries $W/data/queries_test.jsonl \
  --pool $W/data/pool_releases.jsonl.gz $W/data/pool_masters.jsonl.gz \
  --run baseline=$W/runs/baseline_10k.jsonl.gz --run semantica_rerank=$W/runs/semrerank_10k.jsonl.gz \
  --out results/eval_full_10k.json
uv run python scripts/collect_results.py $W/runs results/

# 6. License inventory against catalog-api's policy (read-only use of that checkout).
uv run python scripts/license_check.py /path/to/catalog-api results/licenses.json
```

Every process caps BLAS and OpenMP at 4 threads. Semantica is pure Python here, so
each run uses one core.
