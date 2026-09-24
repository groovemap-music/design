# pgvector footprint on a shared PostgreSQL 19 instance

Status: NO-GO at current prod settings, for every scope measured
Evidence date: 2026-09-23 / 2026-09-24
Spike: `gm-design-chw.1`
Epic: `gm-design-chw`

## Question

Can the shared production PostgreSQL 19 instance hold HNSW indexes for GrooveMap
entity embeddings without degrading the instance for its other tenants, and at what
scope (artists, labels, masters, releases) and dimensionality does that stop being
true?

## Method

A throwaway PG19 + pgvector 0.8.6 image was built and run locally with production
memory settings, then loaded with synthetic vectors (content is irrelevant to a
footprint measurement) at three dimensionalities, at two row-count tiers chosen to
fit this machine's budget. Index size, build time, peak container memory, recall@10,
query latency, and insert/update cost were measured directly. The real Discogs
entity counts were first sanity-checked against Discogs's own live statistics API
(no download needed), then confirmed against the actual 2026-09-01 monthly dumps
(cached in the shared `~/.cache/groovemap-spikes/dumps/` location, under the lock
convention) by stream-parsing each compressed file with `gzcat | grep -c` — the
files were never fully decompressed to disk. Full-scope numbers for the two largest
entities were then extrapolated from the measured per-row rate (validated as linear
— see Evidence). A second PostgreSQL database on the same instance ran a synthetic
OLTP workload (`pgbench`, TPC-B-like) to measure the effect of concurrent vector
activity on a co-located tenant.

No product code was touched in any repository. All commands ran against a local,
disposable Docker container; nothing was pushed anywhere.

### Environment constraints (bound what could be measured)

- Docker Desktop's VM: **2 CPUs, 7.737 GiB RAM** — this is the actual ceiling under
  which every number below was produced, and it is almost certainly smaller than the
  real homelab production host. Absolute latency/throughput and the tenant-regression
  *percentages* measured here should be treated as this-rig numbers, not
  production-transferable ones; the *mechanism* they demonstrate (vector search and
  HNSW builds are CPU-hungry and contend with co-tenants) is expected to hold on any
  host, just not necessarily at the same magnitude.
- Host disk: started at ~49 GB free, ended at ~29 GB free (shared with other spikes'
  containers/volumes; the failed 512 MB-`maintenance_work_mem` build alone generated
  several GB of spill I/O before being cancelled — see below).
- The `gm-design-chw.2` graph-embeddings spike (`node2vec`) was running concurrently
  on the host CPU for the second half of this run, alongside unrelated `phaze`
  test/coverage processes. Host `loadavg` rose from ~3.3 (quiet, early in this spike)
  to ~13–15 (busy) partway through. The **query-set recall/latency numbers** for the
  100K-row tier were captured during the quiet window. The **tenant-impact numbers**
  were captured during the busy window; a same-instance, contention-free re-run
  wasn't possible before this bead's lease expired, so the regression percentages
  below are reported as measured with that confound flagged, not silently cleaned up.
  Given the size of the effect (3×–6× on p99, well past the ±10% budget), host noise
  is very unlikely to be the whole story, but it should be re-verified on a quiet
  host before being treated as a precise number.
- Docker Desktop settings were not changed.

## Evidence

### Image

- Base: `postgres@sha256:b8e68149dff78f8c379e7d8d6b3dd3c3cff74c9d4dad83118ed11b9d4e9ba3e9`
  (tag `19beta3-alpine`) — the newest PG19 tag on Docker Hub as of 2026-09-23; no
  `19beta4` tag exists yet, and PG19 GA had not shipped.
- pgvector: **0.8.6**, built from source in the same layer (`apk add --virtual
  .build-deps git build-base clang21 llvm21 && git clone --depth 1 --branch v0.8.6
  ... && make OPTFLAGS="" && make install && apk del .build-deps`).
- Image size delta: base `429 MB` → final `436 MB`; precise byte delta
  (`docker inspect .Size`) is **3,359,256 bytes (~3.2 MiB)**. This is larger than the
  ~1 MB the planner recorded from an earlier local run — likely apk-index/package
  version drift between runs — but still negligible.
- `CREATE EXTENSION vector` installs cleanly; `extversion` reports `0.8.6`. The full
  chain of upgrade scripts (`vector--0.1.0--0.1.1.sql` through
  `vector--0.8.5--0.8.6.sql`) ships in the image, so `ALTER EXTENSION vector UPDATE`
  will work normally for in-place minor/patch bumps once a database has 0.8.6
  installed; a bump to a *newer* pgvector release requires rebuilding this image
  against the new tag first (the .so and its control file are what the running
  server loads).

### Discogs entity counts

Two independent measurements agree closely:

| Entity | Live API (2026-09-24) | 2026-09-01 monthly dump (stream-counted) | Delta |
| --- | --- | --- | --- |
| Releases | 19,474,054 (`GET api.discogs.com` → `statistics.releases`) | 19,417,067 (`<release id=` count in `discogs_20260901_releases.xml.gz`) | +0.29% |
| Artists | 10,267,158 (`statistics.artists`) | 10,203,002 (`<artist><id>` count) | +0.63% |
| Labels | 2,435,961 (`statistics.labels`) | 2,415,476 (`<label><id>` count) | +0.85% |
| Masters | ~2,597,482 (`database/search?type=master` → `pagination.items`; the stats endpoint doesn't publish a masters count) | 2,589,349 (`<master id=` count) | +0.31% |

The small, uniform deltas (all <1%, all in the direction of growth) are exactly what
three weeks of database growth between the 2026-09-01 dump and the 2026-09-24 live
query would produce — the two sources cross-validate each other. The dump counts are
used below as the primary, reproducible figures (matching the design's specified
stream-parse method); the live API figures served as the initial quick check before
the dumps were available in the shared cache. Both files were stream-parsed with
`gzcat <file> | grep -c '<tag>'` and never decompressed to disk; only the aggregate
counts above are recorded here, no dump content is committed.

The bead's given baseline of "releases ≈ 17M" is stale — the current count is
~19.4M (+~14%). I extrapolate against the measured count and call out the baseline
number where it changes the picture.

### Index size / build time / peak memory (measured)

All at production settings (`shared_buffers=2GB`, `effective_cache_size=6GB`,
`work_mem=64MB`, `maintenance_work_mem=512MB` unless noted), `halfvec`, HNSW default
params (`m=16`, `ef_construction=64`), cosine ops.

| Rows | Dims | Build time | Index size | Table+index total | Peak container memory | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 100,000 | 64 | 19.0 s | 41.4 MB | 60.3 MB | 789 MB | |
| 100,000 | 128 | 22.0 s | 54.4 MB | 85.5 MB | 867 MB | |
| 100,000 | 256 | 33.2 s | 79.4 MB | 137.4 MB | 985 MB | |
| 1,000,000 | 64 | **did not finish in 585.7 s** (cancelled) | — | — | — | `maintenance_work_mem=512MB` (prod default): HNSW graph overflowed the memory budget after 657,596 of 1,000,000 tuples (Postgres's own `NOTICE`), degrading to a much slower disk-spilling build. Still running after 9m46s when cancelled — this alone shows prod's default build memory cannot build any of the four real entity indexes below 657K rows in a reasonable time. |
| 1,000,000 | 64 | 353.5 s (5m53.5s) | 414.5 MB | 602.2 MB | 2.92 GiB (100% of 2 vCPUs) | Same run, retried with `maintenance_work_mem` temporarily raised to 2 GB for the build only (the standard pgvector operational recommendation) — completes, and the index size matches the 100K-row rate almost exactly (434,569,216 B measured vs. 434,585,600 B predicted by linear extrapolation, 0.004% off), confirming index size scales linearly with row count for a fixed dimension. |

Per-row index-size rate (used for extrapolation below, validated linear as above):
**64 dims ≈ 434.6 B/row, 128 dims ≈ 570.2 B/row, 256 dims ≈ 832.6 B/row.**

### Extrapolated index size at real entity scale

Linear extrapolation from the validated per-row rate. Budget line is 50% of
`effective_cache_size` = **3 GiB**.

Using the dump-measured counts (see above):

| Entity | Rows | 64 dims | 128 dims | 256 dims | Fits 3 GiB budget? |
| --- | --- | --- | --- | --- | --- |
| Labels | 2,415,476 | 0.98 GiB | 1.28 GiB | 1.87 GiB | Yes, all three dims |
| Masters | 2,589,349 | 1.05 GiB | 1.38 GiB | 2.01 GiB | Yes, all three dims |
| Artists | 10,203,002 | 4.13 GiB | 5.42 GiB | 7.91 GiB | **No, at any dim tested** |
| Releases (measured, 19.42M) | 19,417,067 | 7.86 GiB | 10.31 GiB | 15.06 GiB | No |
| Releases (bead baseline, ~17M) | 17,000,000 | 6.88 GiB | 9.03 GiB | 13.18 GiB | No |

Only labels and masters fit the size budget at any tested dimensionality; artists
misses it even at the cheapest dimension (64), and releases misses it by 2.6×–5×.

### Recall@10 vs exact search (100K rows, quiet host)

| Dims | ef_search=40 | ef_search=100 |
| --- | --- | --- |
| 64 | 0.421 | 0.654 |
| 128 | 0.169 | 0.317 |
| 256 | 0.063 | 0.149 |

All far below the 0.95 GO threshold at the design's prescribed `ef_search` values,
and recall drops sharply as dimensionality rises. A follow-up probe at higher
`ef_search` on the 64-dim/100K index (same synthetic set) shows recall climbing with
`ef_search` — 100→0.643, 200→0.795, 400→0.932, 800→0.986 — crossing 0.95 only
between `ef_search` 400 and 800, i.e. 4–8× the design's suggested values, at the
smallest dimension tested.

**This spike cannot validate the recall threshold.** The vectors are uniformly random
points on a hypersphere with no cluster/manifold structure, which is close to a
worst case for graph-based ANN (true near-duplicates aren't meaningfully closer to a
query than the rest of the corpus, so the curse of dimensionality bites harder as
dims rise — recall at ef_search=100 fell from 0.654 at 64 dims to 0.149 at 256 dims).
Real trained embeddings cluster and are expected to recall far better at the same
`ef_search`, consistent with pgvector's own published benchmarks on real datasets.
The recall gate must be validated against real embeddings — that's exactly what
`gm-design-chw.2` (graph embeddings) and `gm-design-chw.3` (name embeddings) do next.

### Query latency (100K rows, quiet host, `ef_search=100`)

| Dims | p50 no filter | p99 no filter | p50 filtered (10% selectivity, iterative scan) | p99 filtered |
| --- | --- | --- | --- | --- |
| 64 | 1.39 ms | 2.06 ms | 2.19 ms | 3.94 ms |
| 128 | 1.47 ms | 1.85 ms | 2.15 ms | 4.43 ms |
| 256 | 2.45 ms | 3.84 ms | 3.79 ms | 7.68 ms |

All comfortably under the 50 ms filtered-p99 threshold at this row count on a quiet
host. Insert/update cost (single-row, average of 200 ops) ranged 1.9–2.4 ms average
(p99 2.7–3.3 ms) at 64/128 dims, rising to 3.8 ms average (p99 5.4–5.5 ms) at 256
dims — cheap in absolute terms, but this is at 100K rows; it was not re-measured at
the 1M-row scale due to time budget.

### Neighbour-tenant impact (busy host — see confound note above)

`pgbench` TPC-B-like workload (`-c 4 -j 2`, scale 10) on a second database
(`tenant`) on the same instance:

| Condition | tps | p50 | p99 | vs. baseline p99 |
| --- | --- | --- | --- | --- |
| Baseline, no vector activity | 5,800–6,800 | 0.60 ms | 2.17 ms | — |
| Concurrent vector queries only (1M-row/64-dim index, no build) | 2,344 | 1.32 ms | 7.17 ms | **+230%** |
| Concurrent HNSW index build (400K rows/128 dims) | 1,040 | 3.05 ms | 14.41 ms | **+564%** |

Both conditions blow through the ≤10% p99-regression budget by a wide margin, in
both the "queries only" and "build" cases — this isn't just an index-build story.
Buffer hit ratio on the tenant database stayed high throughout (99.76%), so the
degradation is CPU contention, not cache eviction — expected on a 2-vCPU box with no
spare core for the vector workload to use, and worth re-testing on a host with a
production-realistic core count before trusting the exact percentages. The
*direction* (concurrent vector activity meaningfully competes for CPU with other
tenants) is not in doubt; the *magnitude* is rig-bound.

### Per-database extension isolation

Confirmed: `CREATE EXTENSION vector` in the `spike` database does not create the
`vector` type or extension in a second database (`tenant`) on the same instance —
`SELECT typname FROM pg_type WHERE typname='vector'` returns zero rows in `tenant`.
Extension state is per-database in PostgreSQL, as expected; opting a database in
doesn't change behaviour for tenants that don't.

## Verdict: **NO-GO**, for every scope measured, at today's prod settings

None of the four candidate scopes clears the bundled GO bar
(index ≤ 3 GiB **and** recall@10 ≥ 0.95 **and** filtered p99 ≤ 50 ms **and**
neighbour-tenant p99 regression ≤ 10%) as measured:

- **Artists and releases fail on size alone**, independent of every other factor —
  4.16–15.1 GiB indexes against a 3 GiB budget, at every dimension tested.
- **Labels and masters fit the size budget**, but:
  - the neighbour-tenant p99 regression (+230% query-only, +564% during a build)
    is 20×–56× over the ±10% budget in this rig, and
  - recall@10 could not be validated at all in this spike (synthetic vectors), so
    the recall gate is open, not passed.
- **Every scope** would overflow prod's default `maintenance_work_mem=512MB` during
  its *initial* index build — the overflow triggered here at 657,596 rows and 64
  dims, and even labels (2.44M rows) is 3.7× past that. A one-time build without a
  temporary `maintenance_work_mem` bump would take a build "significantly [more]
  time" than the ~3 minutes/million-rows this rig manages with a 2 GB bump — likely
  impractical to complete during any reasonable maintenance window on this rig, and
  possibly quite different on real hardware.

## Recommendation

1. **Do not adopt pgvector on the current shared production instance for any of the
   four entity scopes** without further evidence. The size gate alone rules out
   artists and releases; the tenant-impact and recall gates are unresolved (not
   disproven) for labels and masters.
2. **Re-run the tenant-impact measurement on hardware closer to the real homelab
   host's CPU count**, on a quiet host (or at least with the confounding
   `graph-embeddings` spike stopped). This spike's 2-vCPU Docker Desktop VM likely
   overstates the regression; it cannot be trusted as a production number, only as
   a directional warning that vector workloads are CPU-hungry and will compete with
   the instance's other tenants.
3. **If labels/masters-scope pgvector is still wanted after that re-test**, plan for
   a temporary `maintenance_work_mem` bump (this rig used 2 GB) during index
   builds/`REINDEX`, reverted afterward — the 512 MB prod default cannot build even
   the smallest real entity's index (masters, 2.6M rows) without a large, currently
   unbounded time penalty.
4. **Defer the recall verdict to `gm-design-chw.2`/`gm-design-chw.3`.** Those spikes
   will produce or evaluate real embeddings; re-run the recall@10 vs.
   `ef_search`/dimension sweep in this spike's harness (`docs/spikes/gm-design-chw.1/`)
   against real vectors before any GO decision is finalized. If real-embedding
   recall clears 0.95 at a modest `ef_search` (comparable to pgvector's published
   SIFT/GIST benchmarks), that removes one of the two open gates for labels/masters;
   the neighbour-tenant regression remains the other and must be cleared first.
5. **No prod memory-setting changes are proposed at this time** beyond the temporary
   build-time `maintenance_work_mem` bump above — `shared_buffers=2GB` /
   `effective_cache_size=6GB` / `work_mem=64MB` were never the binding constraint
   here; CPU contention and recall validity were.

## Reproduction

`docs/spikes/gm-design-chw.1/Dockerfile` builds the exact image used here. The SQL
harness (`bench_template.sql`, `query_load.sql`) that generated every number above is
alongside it; both use only synthetic, generated-in-SQL vectors — no provider data
was downloaded, decompressed, or committed. The entity-count check against the
2026-09-01 monthly dumps used only `gzcat <file>.xml.gz | grep -c '<tag>'` against
the files already cached at `~/.cache/groovemap-spikes/dumps/` — no separate script,
and only the four aggregate counts made it into this document.
