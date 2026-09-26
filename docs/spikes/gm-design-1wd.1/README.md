# Harness for spike gm-design-1wd.1

This is throwaway code for
[Deterministic edition candidates on newly linked releases](../gm-design-1wd.1-unlinked-edition-candidates.md).
It is not a product package, and no GrooveMap service depends on it. It re-runs the
[gm-design-zwy](../gm-design-zwy/README.md) deterministic baseline, copied rather than
imported, with the Semantica code removed. The committed outputs are the aggregate
metrics in `results/`, which contain no ids, names, barcodes, or catalogue numbers.
The snapshots, queries, pool, and rankings stay under
`~/.cache/groovemap-spikes/gm-design-1wd.1/`, outside the repository.

## What changed from zwy

| Change | Why |
| --- | --- |
| `extract_mb_snapshot.py` and `mb_record.py` read the **whole** MusicBrainz dump and keep every release, linked or not | The time-split needs both populations in two snapshots. zwy read a 600,000-line prefix of linked releases only |
| `build_timesplit.py` joins two snapshots | The query is the **earlier** record (what a matcher saw while the release was unlinked). The label is the later snapshot's Discogs relation |
| `matching.comparison` returns the per-field comparison vector, and `baseline_score` is a function of it | ADR 0014 section 4 defines ambiguity by field equality, not score equality. The scores are identical to zwy's (pinned by `tests/test_matching.py`) |
| `run_baseline.py` writes each query's candidates as an unordered set | zwy sorted equal scores by key, so its recall@1 rested on id order |
| `evaluate.py` computes every metric from score groups | It reports unique-top, expected (random order within a tie), guaranteed, and top-group recall. The id-order numbers appear only as a labelled diagnostic. `tests/test_evaluate.py::test_no_tie_is_broken_by_id_or_insertion_order` asserts that swapping which tied candidate holds the lower id, or shuffling candidate order, changes no metric |
| `extract_discogs_releases.py --background-mod 0` | Only the keyed baseline runs here, and it never reaches an unkeyed background record |
| `extract_discogs_releases.py` fails unless the raw stream ends in `</releases>` | `recover=True` closes a truncated document on its own. A dropped download on the first pass here parsed as a clean 1.8M-release pool |

`normalize.py` and `extract_discogs_masters.py` are zwy's, unchanged.

## Files

| File | Role |
| --- | --- |
| `scripts/stream_mb_snapshot.sh` | Streams one MusicBrainz `release.tar.xz` into a compact snapshot and never writes the dump |
| `scripts/extract_mb_snapshot.py`, `scripts/mb_record.py` | One compact record per release (zwy's field set) |
| `scripts/build_timesplit.py` | The newly linked population, its exclusions, the dev/test split by MBID hash, the blocking keys, and the later records for the edit census |
| `scripts/stream_discogs_releases.sh` | Streams the Discogs releases dump into the extractor with whole-stream retries and completeness checks |
| `scripts/extract_discogs_releases.py`, `scripts/extract_discogs_masters.py` | zwy's keyed Discogs pool: every release sharing a barcode, catalogue-number, or title key with any query, plus the targets and their masters |
| `scripts/matching.py` | zwy's `View`, blocking, and score, plus the section 4 comparison vector |
| `scripts/run_baseline.py` | The baseline over one split. Writes candidates with score and comparison vector |
| `scripts/evaluate.py` | Coverage, tie-aware recall, review queue (members and section 4 groups), ambiguity, hard negatives, slices, field agreement (copy bias), and the edit census |
| `scripts/collect_results.py` | Evaluates dev and test, chooses the threshold on dev, adds 95% intervals, and writes `results/` |
| `scripts/run_all.sh` | Baseline on dev and test, then `collect_results.py` |
| `tests/` | Tests over invented fixtures only |
| `results/eval_dev.json`, `results/eval_test.json` | Aggregate metrics per split |
| `results/sample_stats.json` | Population and exclusion counts from the join |

## Reproducing

```bash
cd docs/spikes/gm-design-1wd.1
export UV_PROJECT_ENVIRONMENT=~/.cache/groovemap-spikes/gm-design-1wd.1/.venv
W=~/.cache/groovemap-spikes/gm-design-1wd.1
mkdir -p $W/data $W/runs
uv sync
uv run pytest

# 1. Two MusicBrainz snapshots, each about 36 minutes and about 700 MB of compact gzip.
#    They can run in parallel. The dumps are never written to disk.
PY="uv run python" scripts/stream_mb_snapshot.sh 20260919-001001
PY="uv run python" scripts/stream_mb_snapshot.sh 20260923-001002

# 2. The time-split join (about 1 minute, 1.3 GB peak RSS).
(cd scripts && uv run python build_timesplit.py $W/data/mb_20260919-001001.jsonl.gz \
  $W/data/mb_20260923-001002.jsonl.gz --dev-mod 5 --out-dir $W/data)

# 3. Discogs releases: the whole dump, streamed, never written to disk. The server
#    ignores Range, so a dropped connection restarts the whole stream (up to 3 tries).
#    A pass succeeds only if curl and gzip exit 0 and the raw bytes end in </releases>.
PY="uv run python" scripts/stream_discogs_releases.sh

# 4. Discogs masters, read-only from the shared dump cache.
gzip -dc ~/.cache/groovemap-spikes/dumps/discogs_20260901_masters.xml.gz \
  | (cd scripts && uv run python extract_discogs_masters.py $W/data/blocking_keys.json \
      $W/data/pool_releases.jsonl.gz $W/data/pool_masters.jsonl.gz)

# 5. Runs and metrics.
PY="uv run python" scripts/run_all.sh
```

A wider split reuses step 1 for a later dump, then passes `20260919-001001` as the
earlier snapshot and the later dump as the later one in step 2. Once the Discogs
`20261001` dump is out, use it in step 3 so September's new Discogs releases are
reachable.

Every process caps OpenMP at 4 threads. Everything is single-threaded Python apart from
the curl, xz, tar, and gzip stages.
