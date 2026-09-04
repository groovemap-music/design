# ADR 0005: Source-owned catalog ingestion repositories

- Status: Accepted

## Context

The combined `catalog-ingestion` repository publishes two independently sourced event
streams. Discogs and MusicBrainz have different acquisition formats, entity vocabularies,
state roots, consumers, and release risk, while the shared repository makes either source's
change part of one image and one release boundary. The split must improve ownership without
changing the established v1 wire contract or the deployment identities on which operators
and consumers depend.

## Decision

### Repository lineage and ownership

Rename the existing `catalog-ingestion` repository to `discogs-ingestion`. Its Git history,
tags, releases, issues, and Beadhive lineage move with the rename; historical references to
`catalog-ingestion` remain valid records and are not rewritten. Existing historical bead
identifiers remain immutable. The renamed hive becomes the Discogs hive.

Create `musicbrainz-ingestion` as a new repository with a freshly initialized Beadhive
project and hive identity. Do not clone the Discogs project identifier, issue database, or
historical bead namespace into it. Seed its source from the reviewed split revision and
record that revision in its initial provenance.

Each producer owns its source-specific acquisition, parsing, normalization, orchestration,
tests, contract manifest, generated bindings, deterministic fixtures, image, and release.
`discogs-ingestion` owns the Discogs extraction rules. `musicbrainz-ingestion` owns the
MusicBrainz extraction rules. (Superseded 2026-09-04: see Amendments — the two producers do
not coordinate with each other.)

```mermaid
flowchart LR
    D[discogs-ingestion] -->|Discogs v1 events| DG[discogs-graph-enricher]
    D -->|Discogs v1 events| DS[discogs-sql-loader]
    M[musicbrainz-ingestion] -->|MusicBrainz v1 events| MG[musicbrainz-graph-enricher]
    M -->|MusicBrainz v1 events| MS[musicbrainz-sql-loader]
```

### Frozen compatibility boundary

The source-owned contracts compose to the existing `groovemap.catalog-events` v1 contract.
The event envelope remains unversioned on the wire and keeps these three shapes:

- data: `type`, `id`, and `sha256`, with source-specific additive fields;
- file completion: `type`, `data_type`, `timestamp`, `total_processed`, and `file`; and
- extraction completion: `type`, `version`, `timestamp`, `started_at`, and
  `record_counts`.

Exchanges remain durable fanout exchanges named `{exchange_prefix}-{entity}`. Discogs keeps
the `groovemap-discogs` prefix and the `artists`, `labels`, `masters`, and `releases`
entities. MusicBrainz keeps the `groovemap-musicbrainz` prefix and the `artists`, `labels`,
`release-groups`, and `releases` entities. Consumer queues remain
`{exchange_prefix}-{consumer}-{entity}`, with `.dlx` and `.dlq` suffixes for their dead-letter
exchange and queue. The registered consumers remain `graphinator` and `tableinator` for
Discogs, and `brainzgraphinator` and `brainztableinator` for MusicBrainz.

Deployment keeps the Compose service, container, and hostname identities
`extractor-discogs` / `groovemap-extractor-discogs` and
`extractor-musicbrainz` / `groovemap-extractor-musicbrainz`. Both services keep port 8000
and `GET /health`, `GET /ready`, `GET /metrics`, and `POST /trigger`; trigger requests retain
the optional `force_reprocess` boolean and their accepted/conflict semantics.

Discogs keeps the `discogs_data` volume mounted at `/discogs-data` and its
`extractor_discogs_logs` volume. MusicBrainz keeps the `musicbrainz_data` volume mounted at
`/musicbrainz-data` and its `extractor_musicbrainz_logs` volume. Existing marker names, JSON
fields, phase states, legacy loading behavior, source-byte provenance, file-granular resume,
and durable-write semantics remain compatible.

A file remains complete only after its `file_complete` event is broker-accepted. An
extraction remains complete only after every file succeeds and `extraction_complete` is
broker-accepted. Producer completion must continue to precede the durable completed marker.

(Superseded 2026-09-04: see Amendments. MusicBrainz no longer polls Discogs health before a
run; the two extractors run concurrently and independently.)

### Cutover and rollback

Rehearse each new image against an isolated broker with source-matching consumers and compare
the frozen fixtures, exchange/queue declarations, completion ordering, marker restart, health,
trigger, and shutdown behavior before production cutover.

Cut over one source at a time. Stop the old source mode, verify it is no longer publishing,
deploy the matching source-owned image by immutable digest, and observe its consumers before
starting the other source's cutover. Never dual-run an old and new producer for the same
source against production exchanges: duplicated data and completion events would make parity
evidence ambiguous and consume retry budgets.

Rollback is also source-local: stop the new producer, verify quiescence, and restore the last
known-good combined image digest for that source with the same service name, endpoints,
volumes, exchanges, queues, and markers. A mutable tag is not a rollback target.

### Shared implementation

Small mechanisms used by both Rust producers, including batching, AMQP publication, health
and trigger handling, state persistence, polite HTTP behavior, and shutdown helpers, are
copied into each repository and evolve locally. No third shared Rust crate and no third
contract repository are introduced. At this scale, source-local duplication keeps validation,
release, rollback, and ownership atomic; a shared package would couple both producers to a
third release train without removing their source-specific behavior.

## Consequences

Each event stream has one producer, contract owner, image, release, and rollback boundary.
Consumers promote artifacts only from their matching producer, while services that compose
the full catalog can pin both source contracts explicitly. Compatibility is intentionally
conservative during the split; future breaking changes require a new contract version and a
coordinated producer/consumer rollout.

## Amendments

### 2026-09-04: MusicBrainz-to-Discogs health advisory dropped

The original decision gave `musicbrainz-ingestion` a MusicBrainz-to-Discogs health
coordination behavior: before every initial, periodic, or triggered run, MusicBrainz would
poll Discogs's `/health` endpoint and delay its own run while Discogs reported `running`.
That coordination was dropped at the split and never shipped: `musicbrainz-ingestion`
v0.2.1 has no `DISCOGS_HEALTH_URL` configuration, and deployment's cutover tests assert
that no cross-source health polling is wired between the two extractors.

The two extractors run concurrently and independently, with no health advisory or
scheduling coordination between them. This is safe because the split left no shared state
for the advisory to protect: each producer owns its own source data, markers, exchanges,
queues, and consumers outright, so a concurrent Discogs run cannot corrupt or race
MusicBrainz's extraction, or vice versa. The advisory existed only while both sources lived
in the same repository and shared implicit assumptions about run ordering; once ownership
split cleanly, there was nothing left for it to serialize against.

The mermaid diagram edge `D -. health advisory .-> M` and the "MusicBrainz continues to
poll Discogs health" paragraph above are superseded by this amendment and should be read as
historical context only, not current behavior.
