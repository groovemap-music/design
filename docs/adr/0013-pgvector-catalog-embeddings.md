# ADR 0013: pgvector in PostgreSQL for catalog embeddings

- Status: Accepted

## Context

The product roadmap plans `item_embeddings`, `collection_embeddings`, and nearest-neighbour
baselines for its first model phase, and defers one question to a later decision: whether a
dedicated feature store, vector database, or model-serving service is warranted. This record
is that decision.

A survey of self-hostable vector databases concluded that nothing in GrooveMap needs vectors
today, and that when embeddings arrive the natural home is pgvector inside the PostgreSQL
instance GrooveMap already runs rather than a new store. Three facts pointed that way before
any measurement. [ADR 0012](0012-postgresql-property-graph-migration.md) is consolidating the
catalog graph onto one engine, and a vector store would reopen the second-store boundary that
record closes. The dependency-license policy `catalog-api` enforces rejects GPL and AGPL
dependencies and non-OSI model terms. And the deployment is a single host, where a second
stateful service is a second thing to back up, monitor, and upgrade.

That survey was an argument, not evidence. Three spikes turned it into three questions, each
with a proposed GO bar that the maintainer reserved the right to lower:

1. **Footprint.** What does pgvector cost on the shared production PostgreSQL 19 instance,
   and at which entity scopes and dimensionalities? See
   [the footprint spike](../spikes/gm-design-chw.1-pgvector-shared-footprint.md).
2. **Similar-item retrieval.** Do learned graph embeddings retrieve similar artists better than
   the frozen `heuristics-2026-09` weights behind `GET /api/recommend/similar/artist/{id}`? See
   [the graph-embeddings spike](../spikes/gm-design-chw.2-graph-embeddings-vs-heuristics.md).
3. **Identity candidates.** Does multilingual name-embedding retrieval, fused with `pg_trgm`,
   find the right Discogs entity for a MusicBrainz entity more often than `pg_trgm` alone? See
   [the identity spike](../spikes/gm-design-chw.3-identity-name-embeddings.md).

Some facts were settled before the spikes ran. pgvector 0.8.6 builds from source on the
official, unmodified `postgres` 19 Alpine image: the compiler toolchain is installed as a
throwaway virtual package, `make install` runs, and the toolchain is removed in the same layer,
adding about 3 MiB. Upstream CI passes on PostgreSQL 19. The production PostgreSQL is a shared
instance with other tenants, so the extension has to be created per database and must not
change behaviour for a database that does not opt in; the footprint spike confirmed that it
does not. PostgreSQL 19 was still in beta when the spikes ran, and every spike used the same
digest-pinned `19beta3-alpine` image.

The Discogs entity counts that size everything below come from the 2026-09-01 monthly dumps,
stream-counted without decompressing to disk, and agree with the live statistics API to within
1%: 19,417,067 releases, 10,203,002 artists, 2,415,476 labels, and 2,589,349 masters.

## Decision

### pgvector is adopted, in the existing PostgreSQL, for artists, labels, and masters

GrooveMap stores and searches catalog embeddings with the pgvector extension, version 0.8.6,
inside the same PostgreSQL 19 database as the catalog. Releases are not in scope.

The index shape is the one the footprint spike measured: `halfvec` columns, HNSW with pgvector's
default build parameters (`m = 16`, `ef_construction = 64`), and cosine distance. The starting
dimensionality is 128, the width the graph-embeddings spike selected. Filtered queries use
pgvector's iterative index scans. The extrapolated index sizes, validated as linear in row
count to within 0.004% at one million rows, are:

| Entity | Rows (2026-09-01 dump) | 64 dims | 128 dims | 256 dims | Scope |
| --- | ---: | ---: | ---: | ---: | --- |
| Labels | 2,415,476 | 0.98 GiB | 1.28 GiB | 1.87 GiB | Adopted |
| Masters | 2,589,349 | 1.05 GiB | 1.38 GiB | 2.01 GiB | Adopted |
| Artists | 10,203,002 | 4.13 GiB | 5.42 GiB | 7.91 GiB | Adopted; exceeds the proposed bar |
| Releases | 19,417,067 | 7.86 GiB | 10.31 GiB | 15.06 GiB | Not adopted |

Only artists have a measured use today, similar-artist retrieval below. Of the roughly 10.2
million artist rows, about 9.4 million have a main-artist release and can be served. Labels and
masters sit inside the approved footprint, but no spike measured a retrieval use for either. Their
embeddings are populated when a use arrives with its own evaluation, and the extension scope does
not have to be re-decided when that happens.

### The size bar actually applied

The footprint spike proposed a per-index budget of 3 GiB, half of `effective_cache_size`,
bundled with three other bars: ANN recall@10 of at least 0.95 against exact search, a filtered
p99 of at most 50 ms, and a neighbour-tenant p99 regression of at most 10%. Measured against that
bundle, every scope was a NO-GO.

The maintainer lowered the size bar and did not lower the other three. Artists are admitted at
4.13 to 7.91 GiB across the dimensions measured, and 5.42 GiB at the 128 dimensions adopted.
Releases are excluded at 7.86 to 15.06 GiB. The bar applied is therefore a scope rather than a
number: the artists index is the largest one admitted, and nothing larger is in scope. The three
remaining bars were not passed. The spike could not settle them, so they carry forward as
preconditions below rather than as met criteria.

| Bar (as proposed) | Measured | Applied |
| --- | --- | --- |
| Index at most 3 GiB | Labels and masters fit. Artists 4.13 to 7.91 GiB, releases 7.86 to 15.06 GiB | Lowered by the maintainer to admit artists; releases excluded |
| ANN recall@10 at least 0.95 | Not measurable: synthetic vectors are a worst case, 0.149 to 0.654 at `ef_search` 100 | Unchanged; open |
| Filtered p99 at most 50 ms | 3.94 to 7.68 ms at 100,000 rows on a quiet host | Unchanged; met at small scale, not measured at full scale |
| Neighbour-tenant p99 regression at most 10% | +230% during queries, +564% during a build, on a 2-CPU VM under host load | Unchanged; inconclusive, re-measure on production hardware |

### Similar-item retrieval: GO, through FastRP graph embeddings

Artist similarity is the first use of the extension. Embeddings are computed with FastRP, a
very sparse random projection of powers of the normalized adjacency matrix. It is about forty
lines of numpy and scipy, both BSD-licensed, with no torch, no GPU, and no model weights. The
selected configuration is 128 dimensions, iteration weights `0,1,1,1,1`, degree normalization
β = 0, and credit and track edges included. Removing those edges costs 10 points of recall@10.

The gate the maintainer applied measures against the fair baseline, the `heuristics-2026-09`
weights scored over every artist, and not against the production path. The production path's
candidate generator keeps only the 500 most prolific artists per genre. That cap, not the
weights, costs the served endpoint almost all of its recall: 0.0092 recall@10 against 0.1799 for
the same weights over every artist. Beating the production path would have measured that cap.

| Criterion (proposed, not lowered) | Measured against the all-artist heuristic, 4,721 test queries | Result |
| --- | --- | --- |
| Relative recall@10 gain of at least 10% | 0.1799 to 0.3173 for fused FastRP 128 at α = 0.9: **+76.4%** (95% CI +69.4% to +83.6%) | Met |
| No media family regresses by more than 2 points | Worst delta +0.0 points (video, one query). The smallest real gain is shellac, +1.1 points on nine queries | Met |

The result has hard limits, and this record adopts it only with them attached:

- **The gain is recurrence, not discovery.** Most of it comes from ranking an artist's past
  collaborators highly and seeing them recur after the cut. On collaborators with no pre-cut
  link, fused FastRP scores 0.0134 recall@10 against the heuristic's 0.0311, 57% worse. No
  method tested exceeded 0.037 on that view.
- **The ground truth is a proxy.** "Artists a seed works with after 2023-01-01" stands in for
  "items a collector later wanted", which a Discogs dump cannot supply. The spike does not show
  that embeddings produce better user-perceived similarity, and nothing built on this record
  may claim that they do. That claim needs first-party co-collection evidence from
  [ADR 0010](0010-first-party-events-consent-and-deletion.md) events.
- **Lists churn across projections.** A new random projection replaces about 72% of an
  artist's top ten (Jaccard 0.28) while recall stays within 0.003. The implementation must
  derive each node's projection row from a hash of its provider identifier, not from a global
  random stream, and must measure month-over-month top-10 churn across two real dumps before
  any list is shown to a user.
- **ANN loss is not in these numbers.** The spike ranked by exact brute-force cosine.

FastRP has no training state. A monthly dump load is a full recompute, estimated at about ten
minutes, column-blocked, for the whole catalog. It was not run at full scale.

Node2Vec is rejected. Its best test recall@10 was 0.1914, below the all-artist heuristic on
digital and tape. It cost 73 minutes and 8.7 GB of memory on a 2.85-million-node subset, and at
full scale its parameters and optimizer state alone come to about 50 GB, which does not fit the
32 GB host.

### Identity candidates: not adopted now, not disproven

No embedding-based candidate generator writes `source = 'inference'` rows to `provider_aliases`
([ADR 0009](0009-native-identity-and-provider-aliases.md)). The proposed bar was a gain of at
least 5 points in recall@10 for the fused method over `pg_trgm` alone, per entity kind. It was
not lowered, and it was not met:

| Kind | Queries | `pg_trgm` recall@10 | Best fused recall@10 | Gain |
| --- | ---: | ---: | ---: | ---: |
| Artists | 5,000 | 97.56% | 97.92% (RRF with bge-m3) | +0.36 points |
| Labels | 5,000 | 98.42% | 98.96% (RRF with bge-m3) | +0.54 points |

The result is not a disproof, because the evaluation has limitations the spike doc does not
discuss:

- **Selection bias.** The ground truth is MusicBrainz entities that editors have already linked
  to Discogs, and that population skews easy: about four in five queries are exact or
  case-and-diacritic-only matches, where `pg_trgm` is already at 100%. The entities a production
  generator would actually face are the unlinked ones, which are probably harder, with more
  transliteration and more non-Latin names.
- **Pool size.** Each kind was searched against a pool of 20,000 names, not the roughly 10.2
  million Discogs artists. At full scale there are far more near-names and namesakes, so
  trigram recall is likely lower than measured, and the headroom for any other method is
  likely larger.
- **The non-Latin signal.** On non-Latin names, fusion cleared the bar decisively: +9.6 points
  for artists (n = 198) and +16.7 points for labels (n = 54). Those samples are too small to
  decide on, but they sit exactly where the selection bias says the real workload lies.
- **Embeddings only supplement trigrams.** Dense embeddings alone lose to `pg_trgm` at recall@1
  in every slice. If embeddings are ever adopted for identity, they add candidates to trigram
  matching and never replace it.
- **Namesakes defeat every name method.** The main failure mode is Discogs's `(2)`-suffixed
  namesake collisions, where recall@1 is 30% to 50% for every method. That is a disambiguation
  problem that needs discography, date, or country evidence, and no name embedding solves it.

Any generator adopted later stays inside ADR 0009's boundary: `source = 'inference'` behind a
confidence floor or a review queue, never auto-promoted to `catalog`.

### No dedicated feature store, vector database, or model-serving service

This answers the roadmap's deferral. None of the three is warranted:

- **Vector database.** pgvector in the existing PostgreSQL holds every adopted scope. A
  dedicated engine is a fallback, not a plan (see the rejected alternatives).
- **Feature store.** Embeddings are ordinary tables owned by `database-schema`, beside the
  catalog they describe. Each vector carries lineage: the source dump it was computed from and
  a `model_version` row naming the method, its parameters, and the projection seed rule.
  Nothing needs a separate store to provide that.
- **Model serving.** FastRP runs as a batch job in `analytics-engine`, and retrieval is a SQL
  query from `catalog-api`. Nothing is inferred online. The only online-inference use evaluated,
  name embeddings for identity, is not adopted.

### Preconditions before production use

The extension is adopted, but these items are open and each must be closed before the matching
step. None of them reopens the adoption decision:

- **ANN recall on real embeddings.** Before the artist index serves traffic, re-run the
  footprint spike's recall@10 sweep over `ef_search` against real FastRP vectors, and fix the
  production `ef_search` from that measurement. The synthetic vectors could not validate recall;
  on them, recall only crossed 0.95 between `ef_search` 400 and 800 at 64 dimensions.
- **Tenant impact on production hardware.** Before the first production index build, re-measure
  neighbour-tenant p99 during both queries and builds on the real host, quiet and with a
  realistic core count. The spike's +230% and +564% came from a two-CPU VM with other spikes
  running beside it. They are a direction to heed, not a magnitude to plan around.
- **Build memory.** The production default `maintenance_work_mem` of 512 MB overflows during
  the initial HNSW build of every adopted scope: the spike's build overflowed at 657,596 rows.
  Initial builds and rebuilds raise it to about 2 GB for that session only and revert it. No
  standing memory setting changes.
- **Churn.** Deterministic projections and a measured month-over-month churn figure come before
  any similar-artist list built from embeddings is exposed to a user.

### Images, data rights, and notices

- **Images.** The shared production instance is built and operated in the homelab, which
  carries its own PostgreSQL 19 and pgvector build and receives a request for it. `deployment`
  gets a PostgreSQL 19 and pgvector image built locally from the official Alpine image for
  development and CI. That image is never published. As ADR 0012 requires of the deployment
  pin, it moves to a generally available PostgreSQL 19 image, not a beta.
- **Data rights.** Embeddings computed from Discogs or MusicBrainz dumps are provider-derived
  data. They fall under the same quarantine as the dumps: they are never committed or published,
  and the lineage columns above let them be recomputed or purged with the source they came from.
- **Notices.** certifi, orjson, and tqdm are MPL-2.0 transitive dependencies of the FastRP
  harness. Any shipped pipeline that pulls them in lists them in its `THIRD_PARTY_NOTICES.md`,
  as the dependency-license policy requires. pgvector itself is under the PostgreSQL License.

### Rejected alternatives and conditions for revisiting

- **pgvectorscale.** Version 0.9.1 ships for PostgreSQL 14 through 18 only and pins a pgrx
  release without PostgreSQL 19 support. The community PostgreSQL 19 port
  ([timescale/pgvectorscale#281](https://github.com/timescale/pgvectorscale/issues/281)) is
  unreviewed and reports a silent buffer-lock renumbering hazard. Revisit when upstream releases
  PostgreSQL 19 support, and only if a scope outgrows in-memory HNSW. Releases are the likely
  case.
- **A dedicated vector engine.** Qdrant, under Apache-2.0, is the named fallback. Revisit only
  if the tenant re-measurement on production hardware shows that vector queries or builds
  cannot be kept within the neighbour-tenant budget by scheduling, session limits, or index
  parameters, or if real-embedding recall cannot reach an acceptable level at an affordable
  `ef_search`. Either would be a new record, because it reopens ADR 0012's one-engine argument.
- **AGPL- and SSPL-licensed stores.** Rejected by the dependency-license policy: AGPL is
  excluded, and SSPL is not an OSI licence. Revisit only if that policy changes.
- **Node2Vec and other trained graph embeddings.** Rejected on quality, cost, and fit, as above.
  Revisit if first-party events show that discovery, where fused Node2Vec was the only method to
  improve, matters to users, and a method is found that fits the host.
- **Releases in scope.** Revisit when a release-level use case is evidenced and either the
  instance's memory budget or an on-disk index such as pgvectorscale's makes a 10 to 15 GiB
  index affordable.
- **Identity candidates.** Revisit when a properly powered non-Latin-only evaluation, drawn
  against a realistic candidate pool, clears the 5-point bar, for a generator scoped to
  non-Latin names or to weak trigram matches.

## Consequences

The roadmap's deferral is closed. GrooveMap adds one extension, not one service. The vector
workload shares the catalog's connection, transactions, backups, and health signal, which is
the same argument ADR 0012 makes for the graph. The cost it accepts is the one the footprint
spike warned about: vector queries and index builds are CPU-heavy and compete with the other
tenants of a shared instance. That cost is bounded by the preconditions above rather than
assumed away.

The similar-artist result is adopted narrowly. It licenses an embedding pipeline and an ANN
index. It does not license a claim of better or more surprising recommendations, and the served
lists do not change until churn is measured. The largest single improvement the spikes found
needs no vectors at all: scoring every artist instead of the 500 most prolific per genre takes
the production endpoint from 0.009 to 0.18 recall@10.

Repositories affected:

- **`database-schema`** creates the `vector` extension in GrooveMap's database only, and owns
  the embedding tables, their lineage and `model_version` columns, and the HNSW indexes.
- **`analytics-engine`** owns the FastRP pipeline, its deterministic projection, the monthly
  recompute, and the churn measurement.
- **`catalog-api`** owns kNN retrieval behind the similar-artist endpoint, and separately the
  candidate-generator fix.
- **`deployment`** carries the locally built development and CI image.

### Follow-ups

These are the implementation work for the replan of this molecule. Each becomes its own bead:

- **Deployment development image.** A locally built, unpublished PostgreSQL 19 and pgvector
  0.8.6 image for development and CI in `deployment`, built from the official Alpine image.
- **Homelab production image request.** A request to the homelab to add pgvector 0.8.6 to the
  shared production PostgreSQL 19 build, with the build-memory and tenant-impact preconditions
  attached.
- **Schema extension and embedding tables.** `database-schema` creates the extension per
  database and adds embedding tables for the adopted scopes, with lineage (source dump) and
  `model_version`, and the `halfvec` HNSW index definitions.
- **FastRP pipeline.** `analytics-engine` implements FastRP at 128 dimensions with per-node-id
  hashed projections, the monthly recompute, the real-embedding ANN recall sweep, the
  month-over-month churn measurement, and MPL notices.
- **kNN retrieval.** `catalog-api` serves similar artists from the index, behind the churn and
  recall preconditions.
- **Candidate-generator fix.** `catalog-api` replaces the top-500-per-genre candidate generator
  with scoring over every artist. This is independent of vectors and can ship first.
- **Non-Latin identity evaluation.** Re-run the identity harness on a non-Latin-only sample
  sized in the low thousands, against a realistic candidate pool.
- **Shared ground truth.** Share the identity spike's ground-truth construction, held-out
  MusicBrainz-to-Discogs URL relations stratified by script, with `gm-design-zwy`.

## Amendment: embedding pipeline data access (2026-09-24)

The FastRP pipeline needs every edge of the catalog graph (about 32.8 million nodes at full
scale) and writes one embedding row per served artist. Today `analytics-engine` reads catalog
data only through `catalog-api` over HTTP and writes only its own `insights` and `activity`
schemas. Paging the whole graph through HTTP is impractical at that size, so the pipeline
reads and writes PostgreSQL directly, under a dedicated least-privilege role:

- `database-schema` defines a `NOLOGIN` group role for the pipeline with `SELECT` on the graph
  edge and vertex relations the pipeline reads, and `SELECT`, `INSERT`, `UPDATE`, `DELETE` on
  the embedding tables only. It holds no other privilege. As with `pg_trgm`, the role and its
  grants are guarded, so an initializer without `CREATEROLE` still produces a working schema.
- The login that is a member of that role is provisioned where credentials live: `deployment`
  for development and CI, and the homelab for the shared production instance. No catalog-table
  write privilege is granted to `analytics-engine`.
- `catalog-api` remains the only service that serves catalog data to users. It reads the
  embedding tables to answer similar-item queries.

A paged export and ingest API on `catalog-api` was rejected for this workload because of its
volume. Running the pipeline inside `database-schema` was rejected because the roadmap assigns
offline features and embeddings to `analytics-engine`.
