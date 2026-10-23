# Harness for spike gm-design-4804

This is throwaway code for
[Genre and style lifecycles and taste projections for Strata concepts B and C](../gm-design-4804-strata-atlas.md).
It is not a product package, and no GrooveMap service depends on it. The committed
outputs are the aggregate numbers in `results/`. They contain no ids, no names of
releases, artists, or labels, and no per-style rows. The compact arrays, aggregates,
vectors, and the predecessor CSV stay under `~/.cache/groovemap-spikes/gm-design-4804/`,
outside the repository.

## Files

| File | Role |
| --- | --- |
| `scripts/discogs_fetch_lock.sh` | The shared fetch discipline for every spike that reads `data.discogs.com` (below) |
| `scripts/fetch_dump.sh` | Fetches one dump file into the shared cache `~/.cache/groovemap-spikes/dumps/` under the per-file and global locks |
| `scripts/stream_releases.sh` | Streams a whole releases dump into `extract_dump.py` and never writes the dump. An optional second consumer can share the stream (below) |
| `scripts/extract_dump.py` | One pass over a releases or masters XML stream into compact integer arrays: year, master, genre bitmask, styles, main artists, and labels |
| `scripts/aggregate.py` | Folds one dump's arrays into style x genre, style x year (release year and master year), genre x year, style co-tagging, the `graph.part_of` rule, and `first_year` |
| `scripts/lifecycle.py` | The lifecycle rule (stages and thresholds), flip shares, and the parent-order check |
| `scripts/layout.py` | Genre ring, the geography layout with the three placement rules, the co-occurrence layout, Procrustes alignment, hull intrusions, omissions, edge crossings, displacement, and kNN overlap |
| `scripts/fastrp.py` | Rebuilds ADR 0013-style FastRP artist vectors from one dump (documented production configuration, reduced edge set) and averages them up to styles |
| `scripts/taste.py` | Concept C: a copy of `cratefit_v0`'s evidence rules and the mapping of each evidence entry onto the atlas |
| `scripts/measure_atlas.py` | Concept B: every number in `results/atlas.json` from two dumps' aggregates and vectors |
| `scripts/measure_taste.py` | Concept C: synthetic collectors and candidates over one dump, giving `results/taste_<dump>.json` |
| `scripts/predecessor_costs.sh` | Read-only: logged insights computation durations from the predecessor deployment's PostgreSQL, and its stored genre-trends snapshot for the cross-check |
| `scripts/predecessor_neo4j_timing.sh` | Read-only: times the style-by-year aggregation on the predecessor's full Neo4j graph (300 s cap) |
| `scripts/crosscheck_predecessor.py` | Compares this harness's genre x decade counts with the predecessor's stored snapshot |
| `tests/` | Tests over invented fixtures and synthetic aggregates only |
| `results/atlas.json` | Concept B aggregates: multi-parent, placement rules, lifecycle stability and sensitivity, layout stability |
| `results/taste_20261001.json` | Concept C aggregates |
| `results/fastrp_<dump>.json` | Graph size, time, and peak RSS of each FastRP rebuild |
| `results/predecessor_costs.json`, `results/predecessor_neo4j.json`, `results/predecessor_crosscheck.json` | Predecessor-schema measurements (labelled as such in the spike document) |

## Shared fetch convention

This molecule adopted it on 2026-10-23, after `data.discogs.com` rate-limited the shared
host (HTTP 429 with `retry-after: 3330`). It is implemented once, in
`scripts/discogs_fetch_lock.sh`:

1. **One request at a time across all spikes.** Hold the global lock directory
   `~/.cache/groovemap-spikes/dumps/.fetch.lock` (`mkdir` is atomic) for the whole life
   of every request to `data.discogs.com`, including a full releases stream. The holder
   writes `owner.txt` (pid, spike, file, start time). Waiters poll every 30 s.
2. **Fetch a cached file once.** A file kept in `dumps/` has its own lock
   `dumps/<file>.lock`. The holder downloads to `<file>.part`, checks the gzip trailer,
   and renames it. Everyone else waits for `<file>`. A finished file is never rewritten.
   Releases dumps (about 11 GB each) are never cached: the shared disk cannot hold them.
3. **Read the status without touching the body.** Every `curl` writes its headers with
   `-D`, so the HTTP status and `Retry-After` are known even for a stream.
4. **Back off, then stop.** On HTTP 429, back off 60, 120, 240 s (at most `MAX_429`=3
   retries). A `Retry-After` longer than the next back-off stops with exit code 75 and is
   reported to the dispatcher before any retry: a ban is a data-access problem for a
   person, not something to retry through.
5. **Share a stream instead of fetching twice.** `stream_releases.sh` reads an optional
   `$W/tee_cmd_<date>`: one shell command that reads decompressed XML on stdin. The stream
   is `tee`'d to it through a FIFO. The pass succeeds only if curl, gzip, tee, the
   extractor, and that command all exit 0, and all exit codes are logged. A spike that
   only needs fields the arrays already carry should read the finished
   `releases_<date>.npz` instead.
6. **Release on every exit.** `TERM`, `INT`, and `HUP` run the `EXIT` trap, which removes
   both locks.

## Reproducing

```bash
cd docs/spikes/gm-design-4804
export UV_PROJECT_ENVIRONMENT=~/.cache/groovemap-spikes/gm-design-4804/.venv
W=~/.cache/groovemap-spikes/gm-design-4804
D=~/.cache/groovemap-spikes/dumps
mkdir -p $W/data
uv sync
uv run pytest

# 1. Masters, cached once in the shared dump directory (about 630 MB each), then
#    extracted (about 85 s each).
for d in 20260901 20261001; do
  scripts/fetch_dump.sh $d masters
  gzip -dc $D/discogs_${d}_masters.xml.gz | uv run python scripts/extract_dump.py masters $W/data/masters_$d.npz
done

# 2. Releases, streamed and never written (about 23 minutes each on this host).
for d in 20260901 20261001; do PY="uv run python" scripts/stream_releases.sh $d; done

# 3. Aggregates (about 17 s, 4.3 GB peak RSS each).
for d in 20260901 20261001; do
  uv run python scripts/aggregate.py $W/data/releases_$d.npz $W/data/masters_$d.npz $W/data/aggregates_$d.npz
done

# 4. FastRP rebuilds (about 30 minutes and 7.4 GB peak RSS each on a loaded host).
for d in 20260901 20261001; do
  (cd scripts && OMP_NUM_THREADS=4 uv run python fastrp.py $W/data/releases_$d.npz $W/data/masters_$d.npz \
     $W/data/aggregates_$d.npz $W/data/vectors_$d.npz)
  cp $W/data/vectors_$d.stats.json results/fastrp_$d.json
done

# 5. Concept B and concept C.
(cd scripts && uv run python measure_atlas.py $W/data/aggregates_20260901.npz $W/data/aggregates_20261001.npz \
   ../results/atlas.json --vectors $W/data/vectors_20260901.npz $W/data/vectors_20261001.npz)
(cd scripts && uv run python measure_taste.py $W/data/releases_20261001.npz $W/data/masters_20261001.npz \
   $W/data/aggregates_20261001.npz ../results/taste_20261001.json)

# 6. Predecessor-schema measurements (read-only, maintainer-authorized; placeholders).
export PRED_HOST=<host> PRED_CONTAINER=<container> PRED_USER=<user> PRED_DB=<database>
scripts/predecessor_costs.sh > results/predecessor_costs.json
scripts/predecessor_costs.sh --genre-trends > $W/data/predecessor_genre_trends.csv
(cd scripts && uv run python crosscheck_predecessor.py $W/data/aggregates_20261001.npz \
   $W/data/predecessor_genre_trends.csv ../results/predecessor_crosscheck.json)
CYPHER_CMD=<read-only cypher runner> scripts/predecessor_neo4j_timing.sh > results/predecessor_neo4j.json
```

`measure_taste.py` reads the 20261001 releases arrays. To save disk, the arrays were
deleted after that run and the FastRP rebuild, so re-running step 5 for concept C means
re-running step 2 for 20261001 first. Every random draw uses the fixed seed 4804.
