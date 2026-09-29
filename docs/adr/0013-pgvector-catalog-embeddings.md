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
  recall preconditions. *Superseded in part by the 2026-09-29 amendment below: the maintainer's
  serving-mode verdict is to serve precomputed monthly exact top-10 lists, not the live HNSW
  index. This follow-up is rescoped accordingly and tracked as `gm-catalog-api-2zsq`.*
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

## Amendment: non-Latin identity candidates (2026-09-25)

The "Identity candidates" section left a generator neither adopted nor disproven, and named a
properly powered non-Latin evaluation against a realistic pool as the condition for revisiting
it. That evaluation is the spike `gm-design-e0b.1`
([`docs/spikes/gm-design-e0b.1-nonlatin-identity.md`](../spikes/gm-design-e0b.1-nonlatin-identity.md)).
It held out MusicBrainz-to-Discogs links from the `20260923` MusicBrainz and 2026-09-01
Discogs dumps: 5,000 sampled non-Latin artists against a pool of 1,098,846 Discogs artists,
and all 1,592 usable non-Latin labels against every Discogs label, 2,415,477 after
de-duplication. It compared `pg_trgm`, `multilingual-e5-small`, `bge-m3`, and rank fusion of
each model with `pg_trgm`.

**The verdict is GO, scoped.** A non-Latin identity candidate generator is adopted for
Cyrillic, Hebrew, and Japanese kana names. Han is excluded. The owner made the decision on
2026-09-25 under `gm-design-e0b.2`.

**The bar applied was the one this ADR set, unchanged:** best fused recall@10 at least 5 points
above `pg_trgm` recall@10, on the aggregate of artists or of labels. Best fused is the better of
the two fusions.

| Kind | Queries | Pool | `pg_trgm` recall@10 | Best fused recall@10 | Gain | Against the bar |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Artists | 5,000 | 1,098,846 | 54.44% | 58.40% (RRF with bge-m3) | +3.96 points | Misses by 1.04 points |
| Labels | 1,592 | 2,415,477 | 73.18% | 80.03% (RRF with bge-m3) | +6.85 points | Clears |

Labels clear the bar, so the "artists or labels" condition is met. Artists are a near-miss,
not a NO-GO. Both gains are far smaller than the 9.6 and 16.7 points this ADR recorded on the
thin samples of `gm-design-chw.3`, which confirms that the 20,000-name pool flattered every
method.

The aggregates are not what scopes the generator. The per-script cells are:

| Cell | Queries | `pg_trgm` recall@10 | Best fused gain | Best dense-alone gain |
| --- | ---: | ---: | ---: | ---: |
| Artist, Cyrillic | 1,358 | 87.63% | +4.20 | +7.07 (`bge-m3`) |
| Artist, Hebrew | 583 | 57.29% | +6.69 | +14.92 (`e5-small`) |
| Artist, Japanese kana | 588 | 48.13% | +11.90 | +14.29 (`e5-small`) |
| Label, Cyrillic | 672 | 94.79% | +1.79 | +1.19 (`bge-m3`) |
| Label, Hebrew | 175 | 54.86% | +16.00 | +17.71 (`bge-m3`) |
| Label, Japanese kana | 239 | 51.46% | +17.99 | +20.50 (`e5-small`) |
| Artist, Han | 1,917 | 26.03% | +0.42 | +0.47 (`bge-m3`) |
| Label, Han | 360 | 51.94% | +5.00 | +5.56 (`bge-m3`) |

In the three scoped scripts, every cell but label Cyrillic gains well past 5 points by at least
one method. Label Cyrillic gains little because `pg_trgm` already recalls 94.79%. Dense retrieval
alone sometimes beats fusion, so the retrieval policy is a per-cell choice, not a fixed fusion.

**Han is excluded because the target is out of reach, not because the matcher is weak.** Han is
38% of the artist sample and 23% of the label sample. Discogs stores 73.7% of the Han artist
targets and 45.8% of the Han label targets romanized, and on those every method recalls 0% to
7.9% at 10, both embedding models included. Where Discogs also stores the name in Han, every
method recalls 95.9% to 99.2%. Label Han's +5.00 points sits exactly on the bar only because its
romanized share is smaller. No name-similarity method crosses that script gap, and a
transliteration bridge would need its own spike and decision.

**The prize is the unlinked population.** In the `20260923` MusicBrainz dump, 131,112 artists
and 5,339 labels are non-Latin and have no Discogs link, about 2.6 and 3.3 times the number
already linked. The spike did not break them down by script, so the scoped share is not yet
sized.

**Precondition: validated through HNSW on the text vectors before it ships.** Every dense number
in the spike is exact cosine over the full pool. Its side-check comparing pgvector HNSW to exact
search failed on a container shared-memory limit, so the gap is unmeasured, not small. Before the
generator ships, its recall is measured through pgvector HNSW on the `e5-small` or `bge-m3` text
vectors, at the index shape this ADR adopts. `gm-analytics-engine-ieu.3` measures HNSW against
exact search on the 128-dimension FastRP graph vectors only. It is related, and may inform the
procedure, but it is not a substitute, because recall does not transfer across that difference
in dimension and distribution.

The spike also confirms two findings this ADR already recorded. Embeddings add candidates to
`pg_trgm` and never replace it. Namesakes defeat every name method: with a colliding name,
`pg_trgm` recall@1 falls to 19.7% for artists and 48.9% for labels, against 54.7% and 73.1%
without one.

**Ownership and storage are ADR 0014's, not this ADR's.** The "Identity candidates" section
placed any generator's output in `provider_aliases` as `source = 'inference'`, and the spike's
recommendation 6 proposed the same. Both are superseded by
[ADR 0014](0014-cross-catalog-edition-candidates.md). Its sections 1 to 3 make the producer an
`analytics-engine` batch job, keep candidates in the `matching` schema, and write identity only
on a person's reviewed acceptance in `catalog-api`. Its section 7 admits artist and label
candidates only by amendment. That amendment is ADR 0014's 2026-09-25 "Artist and label
candidates for three scripts" (`gm-design-gcj`), which sets the population,
namesake rule, per-cell bars, and rule version for these three scripts, including the HNSW
precondition above. This amendment decides that a generator is worth building and for which
scripts. It does not decide how, and it files no implementation beads.

The "Identity candidates" revisit condition under "Rejected alternatives and conditions for
revisiting" is met for the three scoped scripts and still stands for Han, Latin-script names,
and the thinly sampled scripts. The "Non-Latin identity evaluation" follow-up is done.

## Amendment: as-built embedding graph and measured preconditions (2026-09-26)

The "Similar-item retrieval" decision and two of the "Preconditions before production use" —
ANN recall on real embeddings and churn — were set against the chw.2 spike's own graph (about
32.8 million nodes, 10.2 million artist rows, about 9.4 million servable) and against synthetic
vectors, because no real embedding existed yet. `gm-analytics-engine-ieu.3` and
`gm-analytics-engine-ste` measured the graph, the two preconditions, and the proxy-benchmark
recall gain against the embeddings that ship, over the real 2026-08 and 2026-09 Discogs dumps
([`recall_and_churn.md`](https://github.com/groovemap-music/analytics-engine/blob/main/docs/recall_and_churn.md),
[`embedding_quality.md`](https://github.com/groovemap-music/analytics-engine/blob/main/docs/embedding_quality.md),
[`embeddings.md`](https://github.com/groovemap-music/analytics-engine/blob/main/docs/embeddings.md)).
This amendment records what was measured. It reopens no part of the adoption decision, and it
does not decide how `catalog-api` should proceed against the recall precondition below; that
decision belongs to the maintainer.

### The as-built graph is narrower than the spike's, and smaller than its own earlier extrapolation

The shipped pipeline (`gm-analytics-engine-ieu`, widened by `gm-analytics-engine-ieu.6`) reads
nine relations from the `graph` schema: the eight main-artist relations (`by_artist`,
`on_label`, `derived_from`, `in_genre`, `in_style`, `master_by_artist`, `master_in_genre`,
`master_in_style`) plus one release-level credited-artist relation, `graph.credited_on` joined
to `graph.same_as` on person name, filtered to a whole-string role match rather than the
spike's own per-token split on comma. It carries no per-track credit and no track-performer
relation; neither reaches the embedding graph today. The schema and loader derivation for both
have already landed — `gm-database-schema-ug3v` and `gm-discogs-sql-loader-b2a` — but reading
them into the graph the embedding pipeline builds is still pending, as `gm-analytics-engine-x3d`.

On the real dumps:

| | 2026-08 dump | 2026-09 dump |
| --- | ---: | ---: |
| Total vertices | 30,121,572 | 30,240,002 |
| Total edges | 173,511,755 | not separately totalled |
| Distinct artists embedded (main + credited) | 6,869,453 | 6,896,892 |

This is smaller than the 32.8 million nodes and 10.2 million artist rows this ADR quotes from
the chw.2 spike's own graph — not because the shipped graph is missing something the spike's
was right to include, but because that figure was itself the spike's coarse, pre-dump
extrapolation and was never checked against a real dump before this measurement. The spike's
own real-dump-derived counts elsewhere in this ADR — 19,417,067 releases, 10,203,002 artists,
2,415,476 labels, 2,589,349 masters — are the whole-catalog artist count, not the
graph-embedded count; the two were never the same figure.

### ANN recall@10 ≥ 0.95: measured on real vectors, not met

The "ANN recall on real embeddings" precondition is closed by measurement, not by passing.
Swept over `ef_search` on both months' real FastRP vectors, at this ADR's fixed HNSW
parameters (`m = 16, ef_construction = 64`):

| `ef_search` | August recall@10 | September recall@10 |
| --- | ---: | ---: |
| 40 | 0.60695 | 0.59755 |
| 100 | 0.6796 | 0.67555 |
| 200 | 0.7357 | 0.73395 |
| 400 | 0.7846 | 0.78235 |
| 800 | 0.83385 | 0.83 |
| 1000 (pgvector's hard cap) | **0.8429** | **0.8405** |

No swept `ef_search` reaches 0.95 in either month, and 1000 is pgvector's own maximum, so there
is no larger value left to try. The production `ef_search` this precondition asked the pipeline
to fix is therefore: none, at this bar.

The shortfall has a diagnosed structural cause. FastRP's shipped iteration weights, `0,1,1,1,1`
— adopted unchanged from the chw.2 spike — put zero weight on a node's own projection row
(`k = 0`): an artist's vector depends only on its neighbours' structure, never its own
identity, so two artists with identical neighbourhoods within the propagation radius get
byte-identical vectors by construction. Measured on the August vectors: 2,659,206 of 6,869,453
(38.7%) are exact byte-duplicates of at least one other vector, in 753,588 groups, the largest
with 818 members. Over the 2,000-query recall sample, the 10th-vs-11th exact-cosine gap has
median 0.0017, and 17.5% of queries have an exact (within 1e-6) tie at or adjacent to the
10th-place score — so a real share of the recall "misses" are the ANN index and the exact
brute-force computation validly disagreeing on which member of a tied group lands at position
10 versus 11, not the ANN index failing to find a genuinely closer neighbour. A tie-tolerant
recomputation (counting a hit within 1e-4 of the true 10th-place score) was started but not
completed; the raw 0.84 figures above are expected to understate it, by an unmeasured amount.
This is a property of the shipped FastRP configuration itself, not an artifact of the ieu.6
credit-edge widening or of this measurement: it would apply equally to the narrower pre-ieu.6
graph.

### Churn: the seed-stability fix holds on real embeddings

The "Churn" precondition — deterministic, per-node-key-hashed projections in place of a global
random stream, measured month over month on real dumps — is closed and met. On a 10,000-artist
common sample (the August ∩ September intersection), mean top-10 Jaccard is 0.9083 on exact
cosine and 0.8026 on the served ANN index at `ef_search = 1000`. This is the outcome the
hashed-projection requirement in "Similar-item retrieval" was written to fix: the spike's own
unpinned, per-run random projection replaced about 72% of a list across seeds (Jaccard 0.28) at
comparable recall. The gap between the exact figure and the ANN figure here is the same tie
structure described above: the ANN index's arbitrary tie-breaking among near-tied candidates
can flip between months even when the underlying embeddings barely move.

### Recommendation quality on the chw.2 proxy benchmark: the gate is still met, at a smaller margin

`gm-analytics-engine-ste` re-ran the chw.2 spike's own proxy benchmark against the shipped
September embedding, rather than the spike's from-scratch training run, on the same held-out
test split and the same all-artist-heuristic baseline this ADR's "Similar-item retrieval" gate
uses:

| Model | Recall@10 | vs. all-artist heuristic |
| --- | ---: | ---: |
| All-artist heuristic | 0.1799 | -- |
| Shipped FastRP alone | 0.2430 | +35.1% [+28.8%, +41.1%] |
| Shipped FastRP fused, α = 0.8 (dev-selected) | 0.2533 | +40.8% [+35.0%, +46.7%] |
| *Spike's own fused FastRP, α = 0.9 (for reference)* | *0.3173* | *+76.4% [+69.4%, +83.6%]* |

The "relative recall@10 gain of at least 10%" bar this ADR applied is still met, at +40.8%
against the same baseline. It sits 6.4 points below the spike's own fused figure. The
evaluation cannot isolate a single cause, since the shipped embedding was built once, not
ablated, but it lists the shipped graph's known differences from the spike's as the plausible
contributors: no track-level edges at all (the spike's own ablation found removing credit edges
alone cost about 10 points of recall@10 on a comparable configuration; track-edge removal was
never isolated), the whole-string role filter, name-join rather than direct-id credit
resolution, and the wider nine-relation graph itself. 11.5% of the benchmark's subset artists
have no shipped vector and fall back to an all-zero row, which dilutes the comparison further
but concentrates in artists the benchmark's own query set does not draw from.

### Operational: HNSW build memory and pipeline peak memory

Building a full month's HNSW index at this ADR's fixed parameters needs materially more
`maintenance_work_mem` than `database-schema`'s documented 2 GB operator value: at 2 GB the
build slowed to a disk-spilling-consistent 15,000–18,000 tuples/minute from about 3.4 million
of 6,869,453 tuples on, and was killed at 52.3% after about 1h25m; at 4.5 GB it also slowed,
from about 5.3 million tuples (77%) on. At 8 GB with parallel HNSW build workers enabled
(`max_parallel_maintenance_workers = 4`), on a 6-CPU host, both months completed at full speed
with no slowdown: 552.8 s (August, 6,869,453 rows) and 596.1 s (September, 6,896,892 rows).
This is a finding about the shape of the sizing problem at this row count, not a specific
replacement value for the production host, whose CPU count and available memory were not
available to test against. It also assumes the per-`model_version` partial index shape
`gm-database-schema-19g5` adds; the "Build memory" precondition text above was written against
a plain, whole-table index, which is a different and larger build.

The embedding pipeline's own peak memory for a full month's compute is estimated, not yet
measured end to end against a real streaming PostgreSQL read: `estimate_peak_bytes()` against
the real August graph shape (30,121,572 nodes, 173,511,755 directed edges, 6,869,453 artist
rows) predicts about 7.55 GB (build 3.62 GB, compute 7.55 GB), within the 12 GB budget this
ADR's FastRP configuration already carries. `gm-deployment-cy6` will measure the real pipeline
end to end.

### Status: the serving precondition remains open

The "ANN recall on real embeddings" precondition asked for a production `ef_search` fixed by
measurement before the artist index serves traffic. That measurement is now done, and its
answer is that no swept `ef_search`, up to pgvector's own cap, reaches the 0.95 bar this ADR
set. Whether and how `catalog-api` (`gm-catalog-api-2zsq`) proceeds against that gap is not
decided by this amendment; it is the maintainer's decision, informed by the tie-structure
finding above. Options the measurement surfaces, stated neutrally:

- Give a node's own projection non-zero weight (a change to the shipped FastRP configuration)
  and re-measure recall against the new vectors.
- Over-fetch through the ANN index and re-rank the candidates by exact cosine before returning
  the top 10.
- Accept the measured ~0.84 recall@10 at pgvector's `ef_search` cap, at the query latency that
  implies.
- Raise `m` and/or `ef_construction` beyond this ADR's fixed HNSW parameters and re-measure.

None of these is applied by this amendment.

## Amendment: as-built edges-v3 embedding, FastRP self term, and precomputed similar-artist serving (2026-09-29)

The previous amendment left the graph narrower than `gm-analytics-engine-x3d`'s track-level
widening (then pending), left the "ANN recall on real embeddings" precondition open, and left
`catalog-api`'s (`gm-catalog-api-2zsq`) path against that gap to the maintainer. Two further
`analytics-engine` beads closed both: `gm-analytics-engine-i37`
([`docs/embedding_weight_sweep.md`](https://github.com/groovemap-music/analytics-engine/blob/main/docs/embedding_weight_sweep.md))
landed x3d's wider graph and swept FastRP's step-0 weight; `gm-analytics-engine-8ts`
([`docs/embedding_tie_break.md`](https://github.com/groovemap-music/analytics-engine/blob/main/docs/embedding_tie_break.md))
added a genuine FastRP self term and rendered the maintainer's serving-mode verdict. This
amendment records what was built and measured, and the serving decision that follows from it.
It reopens no part of the adoption decision.

### As-built: edges-v3 graph and FastRP algorithm v2 with a self term

`gm-analytics-engine-x3d` has now landed and is read into the embedding graph, which the
previous amendment described as still pending. The shipped graph is **edges-v3**: on top of
edges-v2's release-level `graph.credited_on` (joined to `graph.same_as`), it adds
`graph.track_credited_on` — track and sub-track credits, resolved through `same_as` the same
way — and `graph.track_by_artist`, track performers. Both are new relations at the graph edge,
not new preconditions on the pgvector extension itself.

`gm-analytics-engine-8ts` gives FastRP a genuine self term, distinct from the `w0` weight this
ADR previously described: FastRP's sum has no `k = 0`/self term in the first place — the term
that `w0` scales is `P¹R`, the one-hop neighbour mean, not a node's own untransformed projection
(see the duplicate-vector finding below). `FastRPConfig.self_weight` adds `self_weight *
normalize(R[v])`, `R[v]` the node's own hashed projection row, on top of the existing sum; the
default (`0.0`) is bit-identical to the prior formula. This is `FASTRP_ALGORITHM_VERSION = 2`,
named **FastRP algorithm v2** below and in the stored `model_version`.

The as-built configuration, chosen by `i37`'s winner-selection rule (`w0 = 0`, ranked by chw.2
fused recall@10) and then carried into `8ts`'s self-term measurement, is:

- `w0 = 0` (`i37`'s winner across `w0 ∈ {0, 0.1, 0.25}`, by 0.32 points of fused recall@10 over
  the runner-up `w0 = 0.25`, outside the sweep's 0.001 tie band).
- `self_weight = 0.05` (`8ts`; `0.02`/`0.1` were not swept, for time-budget reasons).
- Edges-v3, as above.
- Stored `model_version`:
  `fastrp-v2:dim=128:weights=0,1,1,1,1:beta=0:self=0.05:proj=achlioptas-s3:rows=splitmix64(blake2b64(kind,key)):seed=20260924:edges-v3@discogs_2026{08,09}01`.
- Artist rows embedded: 9,330,617 (August dump) and **9,366,416** (September dump) — the figure
  this amendment cites elsewhere as ~9.37M is the September count.

### The duplicate-vector finding: FastRP's `k = 0` term carries no node identity

`i37` diagnosed why the shipped edges-v2/edges-v3 embeddings, at every `w0` this ADR or its
prior amendments considered, produce exact duplicate vectors for artists with identical one-hop
neighbourhoods (the "as-built" amendment above already found this at 38.7% for edges-v2):
FastRP's sum is `sum_k w_k * normalize((P^(k+1) R)[v])`, and the `k = 0` term `w0` weights is
`P¹R`, the one-hop neighbour mean — never the node's own raw projection `R`. Reweighting `w0`
across `{0, 0.1, 0.25}` therefore cannot touch the mechanism: **the duplicate-vector share on
edges-v3 is 42.22% at every swept `w0`, identical to eleven decimal places**
(`shipped_file_dup_group_pct = 0.42218656527747644` in all three of `i37`'s per-weight quality
files), against edges-v2's 38.7%. Widening the credit-edge scope did not shrink the tie
structure and plausibly worsened it.

`8ts`'s self term fixes this directly: `self_weight * normalize(R[v])` is distinct per node with
overwhelming probability, regardless of neighbourhood identity. **Measured duplicate-vector
share with `self_weight = 0.05`: 0.0%**, down from 42.22%.

**This supersedes, without erasing, the previous amendment's duplicate-vector numbers.** The
"as-built" amendment's 38.7% (edges-v2, `self_weight = 0`, the pre-`i37`/`8ts` graph) and its
recall and churn figures measured against that graph are superseded by edges-v3 and then by the
self term, as detailed below; they remain accurate descriptions of what was measured at the
time.

### Measured quality: the chw.2 gate is still met, at a margin closer to the spike's own

| Configuration | Embedding alone | Fused @ dev-selected α | Gain over all-artist heuristic (0.1799), 95% CI |
| --- | ---: | ---: | --- |
| Edges-v2, `self_weight = 0` (previous amendment) | 0.2430 | 0.2533 (α=0.8) | +40.8% [+35.0%, +46.7%] |
| Edges-v3, `w0 = 0`, `self_weight = 0` (`i37`) | 0.2626 | 0.2719 (α=0.8) | +51.17% [+44.65%, +57.75%] |
| **Edges-v3, `w0 = 0`, `self_weight = 0.05` (`8ts`, as built)** | 0.2613 | **0.2723** (α=0.8) | **+51.4% [+45.0%, +57.9%]** |
| *Spike's own fused FastRP, `w0,1,1,1,1`, α=0.9 (for reference)* | -- | *0.3173* | *+76.4% [+69.4%, +83.6%]* |

The "relative recall@10 gain of at least 10%" bar this ADR's "Similar-item retrieval" section
applies is still met, at +51.4% against the all-artist heuristic (reproduced as 0.1799,
17.988%, by both `i37` and `8ts`). This **supersedes the previous amendment's 0.2533/+40.8%
figure**, which was measured against the narrower edges-v2 graph before `i37` or `8ts` ran; it
is not wrong, only superseded by the wider graph and then the self term. The self term's own
effect on this benchmark is small (0.2719 → 0.2723): chw.2's queries are active seed artists who
almost always have a distinguishing neighbourhood already, so only 0.1% of test queries had a
shipped vector in a duplicate group even at 42.2% overall duplication — the benchmark mostly
confirms the self term does not hurt the signal chw.2 measures, while directly fixing an
artifact chw.2 could not see in the first place.

### Serving decision: precomputed monthly exact top-10 lists, not the live HNSW index

The self term also improves recall and churn measurably, though not enough to clear the
maintainer's ANN-serving bar. Against edges-v3 with `self_weight = 0` (`i37`) vs.
`self_weight = 0.05` (`8ts`), both months, `m = 16, ef_construction = 64`:

| Metric | `self_weight = 0` (`i37`) | `self_weight = 0.05` (`8ts`) |
| --- | ---: | ---: |
| Strict recall@10, `ef_search = 1000` (Aug / Sept) | 0.7953 / 0.7952 | **0.8335 / 0.8290** |
| Exact churn (Aug→Sept, raw vectors) | 0.8886 | **0.9519** |
| ANN churn, `ef_search = 1000` | 0.6888 | **0.7243** |
| Index/exact churn gap | 0.1998 | 0.2276 (wider) |

`8ts` rendered the maintainer's three-threshold "D serving-mode verdict" against these
`self_weight = 0.05` numbers (serve from the index only if all three hold):

| Threshold | Required | Measured | Result |
| --- | --- | ---: | --- |
| ANN churn at a named `ef_search` | ≥ 0.85 | 0.7243 (`ef_search=1000`) | **FAIL** |
| ANN churn within 0.05 of exact churn | gap ≤ 0.05 | 0.2276 | **FAIL** |
| Strict recall@10 at a named `ef_search` | ≥ 0.85 | 0.8335 (Aug), 0.8290 (Sept), both at `ef_search=1000`, pgvector's maximum | **FAIL** |

**Decision: do not serve similar-artist results from the live ANN index.** GrooveMap serves
precomputed monthly exact top-10 lists instead, computed once per monthly dump directly from
the raw embeddings — `8ts` measured this at 361.4 s (August) and 283.8 s (September), well
within a monthly batch job's budget — and stored as a static lookup
(`public.artist_similar_artists`, `public.artist_embedding_releases`). Fusion with the
`heuristics-2026-09` weights happens at serve time from those precomputed lists, using the
stored embedding vectors for the point cosines the fusion needs. The HNSW index this ADR
adopts is still built (the self term makes its own build meaningfully more expensive — see
"Memory findings" below — precisely because it now has real work to do per candidate) but is
optional and non-serving: nothing in the production path queries it.

**The self term is adopted regardless of this verdict.** It is what makes the precomputed exact
list trustworthy month to month: zero duplicate-vector ties (down from 42.22%), 3.4–3.8 points
more strict recall at every swept `ef_search`, and exact churn up to 0.9519 (up from 0.8886).
Reverting to `self_weight = 0` to avoid the heavier index build would reintroduce the
duplicate-vector problem into the same list this decision serves.

**This resolves the previous amendment's "Status: the serving precondition remains open"
section**, without adopting any of its four options as stated. `8ts` tried the first
("give a node's own projection non-zero weight") and it was necessary but not sufficient — the
ANN index still fails all three thresholds even with it — so the path taken is closest to
"accept the measured recall," except that GrooveMap accepts it by not serving through the ANN
index at all rather than by serving at pgvector's `ef_search` cap. The four listed options
remain accurate as a statement of what was on the table at the time; they are superseded as a
description of what happens next by the decision above.

### Memory findings

FastRP's own peak process memory, `self_weight = 0.05`, edges-v3, both months (the same
`AdjacencyBuilder.build()` phase `i37` reports below): **10.70 GB (September) to 12.01 GB
(August)**, within this ADR's 12 GB FastRP budget. For context, `i37`'s own measurement of the
same phase, at `self_weight = 0` and across the `w0` sweep, was markedly higher — 17.27 GB
(September) to 19.26 GB (August) — and `i37`'s FastRP-alone figures (post-parse, parser freed)
ranged 9.87–10.65 GB (August, by `w0`) to 11.66–14.33 GB (September, by `w0`), with September's
`w0 = 0.1`/`w0 = 0.25` landing 4.2 GB above `i37`'s own pre-measurement estimate and eating past
the 12 GB budget. `8ts` attributes the gap between its own lower numbers and `i37`'s to host
conditions at run time, consistent with `i37`'s own note that this phase's peak varies with host
state, not with FastRP configuration — the improvement is not claimed as a consequence of the
self term or of a memory-guard fix `8ts` made to the pipeline's own footprint-tracking code
(`process_footprint_bytes()`, commit `66608ed`), unrelated to the FastRP algorithm itself.

**HNSW build memory, once ties are broken, is heavier than this ADR's preconditions assumed.**
With duplicate vectors eliminated, the `m = 16` build itself got measurably more expensive:
August's build exhausted `maintenance_work_mem = 8 GB` near the end (about 9.15M of its
9,330,617 rows already inserted) and fell into IO-bound behaviour for its last stretch, taking
82.4 minutes against September's 42.3 minutes for an almost identical row count at the same
settings — HNSW's graph-construction bookkeeping can no longer short-circuit comparisons among
now-distinct candidate vectors. `8ts`'s recommendation: **budget approximately 10 GB of
`maintenance_work_mem` for production HNSW builds on this catalog once ties are broken**, up
from the 8 GB used throughout both `i37` and `8ts`. Separately, `i37` found the larger-index
variant (`m = 32, ef_construction = 128`) does not fit an 8 GB `maintenance_work_mem` at this
scale at all: September's `w0 = 0` build overflowed at about 6.1M of 9,366,416 tuples, fell to
an on-disk build path (about 80 tuples/s), and was abandoned after about 4h50m at roughly 75%
complete; it was not measured to completion by either bead.

### Latency: a real quiet-host measurement, finally

`8ts` ran the first latency pass not measured under host load. Mean and p95 per-query ANN
latency, September index, `self_weight = 0.05`:

| `ef_search` | Mean (ms) | p95 (ms) |
| --- | ---: | ---: |
| 200 | 24.8 | 32.8 |
| 400 | 38.7 | 46.3 |
| 800 | 69.8 | 84.1 |
| 1000 | **84.7** | **101.2** |

These supersede `i37`'s own "upper bounds only" figures (91–296 ms mean at `ef_search = 1000`,
measured under sustained host load) as the first real off-load characterization of this index.
Given the serving decision above, this latency does not gate anything in production: nothing
queries the ANN index at serve time, and the precomputed-list job's own exact-computation cost
(361.4 s / 283.8 s per month) is the number that matters for serving.

### Follow-ups updated

The "Follow-ups" list's kNN retrieval item is rescoped, marked in place above: `catalog-api`
(`gm-catalog-api-2zsq`) now serves similar artists from the precomputed monthly exact top-10
lists this amendment decides, not from the live index. The "ANN recall on real embeddings"
precondition under "Preconditions before production use" is closed by this amendment's serving
decision, not by a passing measurement: no `ef_search` cleared the bar on either the `i37` or
`8ts` configuration, and the decision above is to not depend on the index for serving rather
than to keep sweeping toward it.
