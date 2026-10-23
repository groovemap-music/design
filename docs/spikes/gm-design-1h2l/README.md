# Harness for spike gm-design-1h2l

This is throwaway code for
[Measure how the catalog fits the credit, master, release ladder and what a strata route costs on Neo4j](../gm-design-1h2l-strata-ladder.md).
It is not a product package, and no GrooveMap service depends on it. The ingestion and
graph rules it needs are restated rather than imported (see each script's docstring for
the file it restates). The committed outputs are the aggregate numbers in `results/`,
which contain no ids, names, or titles. The compact extracts, the DuckDB file, and the
latency sample stay under `~/.cache/groovemap-spikes/gm-design-1h2l/`, outside the
repository.

## Files

| File | Role |
| --- | --- |
| `scripts/fetch_dump.sh` | Downloads one dump into the shared cache `~/.cache/groovemap-spikes/dumps/` under the mkdir lock (below) |
| `scripts/stream_discogs.sh`, `scripts/extract_discogs.py` | Discogs masters (cached) and releases (streamed, never written) into compact TSVs: releases, release-level `BY` artists, release-level credits, masters, master artists |
| `scripts/discogs_rules.py` | The graph's release-year rule and the role split |
| `scripts/stream_mb.sh`, `scripts/extract_mb.py`, `scripts/mb_links.py` | MusicBrainz release groups (cached) and releases (streamed) into compact TSVs, with musicbrainz-ingestion's Discogs cross-reference rule |
| `scripts/load_db.py` | Loads the TSVs into one DuckDB file |
| `scripts/ladder_stats.py` | Masterless share, masters per artist, releases per master, credit fan-out, size bands -> `results/ladder.json` |
| `scripts/mb_attach.py` | How MusicBrainz-only releases attach to a master -> `results/mb_attach.json` |
| `scripts/payload_model.py` | The draft payload and its aggregation rule; payload bytes per band and budget -> `results/payload.json`; writes the latency sample |
| `scripts/latency.py` | The candidate strata queries beside today's explore and expand, through a Bolt driver in READ sessions -> `results/latency.json` (for the first deployment) |
| `scripts/latency_shell.py` | The same queries, timed server-side through a read-only cypher-shell wrapper -> `results/latency_predecessor.json` (what this spike ran) |
| `scripts/predecessor_checks.cypher` | Version, constraints, indexes, hardware, edge counts, the `0` master, the largest roots, and collector edges on the predecessor graph |
| `scripts/collector_time.sql` | The read-only, aggregate-only count of collection and wantlist rows with a usable recorded time, for GrooveMap's schema |
| `scripts/collector_time_predecessor.sql` | The same count, translated to the predecessor schema |
| `tests/` | Tests over invented fixtures only. `tests/test_cypher.py` runs only against an empty throwaway Neo4j |

## The shared dump cache and its lock

`fetch_dump.sh` is the mkdir-lock convention for `~/.cache/groovemap-spikes/dumps/`.
`mkdir <file>.lock` is atomic, so whoever creates it downloads to `<file>.part`, checks
the archive (`gzip -t` or `xz -t`), renames it, and removes the lock. Anyone else
waits while the lock exists and then reads the finished file. A lock left by a dead
process is removed by hand. Files the disk cannot hold, which here means the Discogs
releases dump (about 11 GB) and the MusicBrainz release dump (23 GB), are streamed and
never cached.

`data.discogs.com` rate-limits by address. A `429` carries a `retry-after` of about an
hour, and retrying early extends it, so wait it out instead of looping.

## Reproducing

```bash
cd docs/spikes/gm-design-1h2l
export UV_PROJECT_ENVIRONMENT=~/.cache/groovemap-spikes/gm-design-1h2l/.venv
export W=~/.cache/groovemap-spikes/gm-design-1h2l PY="uv run python"
mkdir -p $W/data $W/runs
uv sync
uv run pytest

# 1. MusicBrainz: release groups (1.3 GB, cached), then releases (23 GB, streamed,
#    about 35 minutes; xz is the bottleneck).
scripts/stream_mb.sh 20261021-001001 release-group
scripts/stream_mb.sh 20261021-001001 release

# 2. Discogs: masters (cached), then releases (streamed, up to three whole-stream tries).
scripts/stream_discogs.sh 20261001 masters
scripts/stream_discogs.sh 20261001 releases

# 3. Load once, then the aggregates.
(cd scripts && $PY load_db.py $W/data/discogs_20261001 \
  $W/data/mb_release_20261021-001001.tsv.gz $W/data/mb_release-group_20261021-001001.tsv.gz $W/spike.duckdb)
(cd scripts && $PY ladder_stats.py $W/spike.duckdb ../results/ladder.json)
(cd scripts && $PY mb_attach.py $W/spike.duckdb ../results/mb_attach.json)
(cd scripts && $PY payload_model.py $W/spike.duckdb ../results/payload.json \
  --sample 300 --budgets 0,500,2000,3/12/16,6/12/16 --sample-out $W/data/latency_sample.tsv)
```

### Latency on the predecessor graph (what this spike ran)

The predecessor's Neo4j is reachable only through a wrapper that runs cypher-shell in
READ access mode and keeps the credential inside the container. It reads Cypher on
stdin and takes a timeout in seconds. Every statement here is read-only and bounded.

```bash
CYPHER="<read-only cypher-shell wrapper>"
$CYPHER 300 < scripts/predecessor_checks.cypher
(cd scripts && GM_CYPHER_CMD="$CYPHER 3000" $PY latency_shell.py \
  $W/data/latency_sample.tsv ../results/latency_predecessor.json --per-band 30 --repeats 5)
<read-only psql wrapper> < scripts/collector_time_predecessor.sql
```

### Latency through a Bolt driver (for the first deployment)

```bash
NEO4J_URI=bolt://<host>:7687 NEO4J_USER=<read-only user> NEO4J_PASSWORD=<...> \
  uv run python scripts/latency.py $W/data/latency_sample.tsv results/latency.json \
  --repeats 5 --expected-releases <releases.total from results/ladder.json>
```

The instance must hold the whole catalog: the output records its Release count beside
the dump's and sets `full_catalog`. The harness opens READ sessions only.

### Collection and wantlist recorded time on GrooveMap (for the first deployment)

```bash
psql "$GM_READONLY_DSN" -X -A -F $'\t' -f scripts/collector_time.sql
```

### The Cypher check against a throwaway Neo4j

`tests/test_cypher.py` checks that the latency harness's queries parse and return the
planes the payload rule needs. It writes an invented graph, so it refuses a database
that holds any node:

```bash
docker run -d --name gm-spike-neo4j -p 127.0.0.1:17687:7687 -e NEO4J_AUTH=neo4j/throwaway-spike neo4j:2026.09.0-community
GM_SPIKE_NEO4J_URI=bolt://127.0.0.1:17687 GM_SPIKE_NEO4J_PASSWORD=throwaway-spike uv run pytest tests/test_cypher.py
docker rm -f gm-spike-neo4j
```

DuckDB runs with 4 threads and an 8 GB memory limit (`load_db.connect`). Everything
else is single-threaded Python apart from the curl, xz, tar, and gzip stages.
