# Media-taxonomy program rollout

This document is the rollout plan for [ADR 0007](../adr/0007-canonical-media-taxonomy.md). The decision and the vocabulary live in this repository; the implementation is delivered as one molecule per repository, in five waves. Each wave pins the artifacts the previous wave produced, so a wave is filed only after the wave it depends on has merged. It records what each repository changes, what it pins, and how it verifies the pin.

## Artifacts every wave pins

| Artifact | Owner | How a consumer pins it | How the pin is verified |
| --- | --- | --- | --- |
| `taxonomy/media/v1/media-taxonomy.json` | design | Vendor the file byte for byte beside a source record with the design commit and SHA-256 | The repository's check gate recomputes the digest and fails on drift |
| `groovemap.catalog-events` v1 contract with the `media` field | discogs-ingestion, musicbrainz-ingestion | Promote `contract.json`, `source.json`, and the generated binding from a reviewed producer commit | `just source-check` (consumers) and `just contract-check` (producers) |
| Persistence contract v1 with the media columns and graph constraints | database-schema | Promote `contracts/persistence/v1` from a reviewed schema commit | `just source-check` |
| `groovemap-runtime` revision that ships `common.media` | python-libraries | Pin the immutable commit in `pyproject.toml` | `just source-check` compares the pin with the persistence compatibility record |
| Catalog API consumer contracts with the `media` routes and parameters | catalog-api | Promote the matching `contracts/catalog-api/<consumer>/v1` set | `just source-check` |

The vocabulary digest at the commit that published this document:

```text
73677c6e577a9098136582539f5515814b8b73e4069a74fd6424d6b74e4553ac  taxonomy/media/v1/media-taxonomy.json
```

Regenerate it from the exact bytes with `shasum -a 256`; `just publication-readiness` prints the same value as `media_taxonomy_sha256`.

## Wave 0: design (this repository)

Record ADR 0007, publish the vocabulary with its two schemas and the conformance fixtures, and publish this rollout plan. Done when `just check` passes and the publication handoff prints the vocabulary digest.

## Wave 1: producers, runtime, schema (parallel)

- **discogs-ingestion.** Vendor the vocabulary with a digest check; add a Rust mapper that turns normalised `formats` into the canonical block and attach it after record normalisation and before the content hash is recomputed; add a warning-level extraction rule that flags Discogs format names the vocabulary does not know; regenerate fixtures and document the additive field. Pins: vocabulary digest.
- **musicbrainz-ingestion.** Keep the raw medium list (format, position, title, track count; never tracks) in release events; vendor the vocabulary; add the Rust mapper copy and attach the canonical block in the parser; regenerate fixtures and document both additive fields. Pins: vocabulary digest.
- **python-libraries.** Vendor the vocabulary; add `common.media` with the Discogs and MusicBrainz mappers, family helpers, and the legacy shim from raw format names; expose a `media` filter and a typed media block in the agent tools; bump the synchronised version. Pins: vocabulary digest.
- **database-schema.** Add `Medium` and `MediaFamily` constraints and the `media_families` index to Neo4j; add `media` JSONB columns with GIN indexes on the families list to the Discogs and MusicBrainz release tables, user collections, and user wantlists; add the media columns to the precomputed rarity table; keep persistence contract v1. Pins: none beyond ADR 0007.

## Wave 2: loaders, enrichers, toolkit (parallel)

- **discogs-graph-enricher.** Promote the producer contract; merge `Medium`, `MediaFamily`, `IN_FAMILY`, and `ISSUED_ON` in both write paths; set `media_families`; keep `formats` for one minor version; derive a block from raw names when an event predates the field. Pins: producer commit, schema commit, runtime revision.
- **discogs-sql-loader.** Promote the producer and schema commits; write the `media` column in both upsert paths; document the column. Pins: producer commit, schema commit, runtime revision.
- **musicbrainz-sql-loader.** Promote the producer and schema commits; write `media` on release upsert. Pins: producer commit, schema commit, runtime revision.
- **musicbrainz-graph-enricher.** Promote the producer commit; merge `ISSUED_ON` edges tagged `source: musicbrainz` and a media summary onto matched releases; keep the Discogs-identifier rule. Pins: producer commit, schema commit, runtime revision.
- **operations-toolkit.** Add `media` to the debug-message field specifications and example payloads for both providers. Pins: both producer commits.

## Wave 3: API and analytics

- **catalog-api.** Promote the schema and producer contracts and the runtime revision; store canonical media on collection and wantlist synchronisation with a backfill; add the collection media endpoint and `media` filters with `formats` as a deprecated alias; split rarity into a media-neutral core and per-family extensions with pressing scarcity gated to grooved families; report label DNA by family; expose media in natural-language queries, search, and autocomplete; publish the updated consumer contracts; retire vinyl-specific names from the documentation. Pins: schema commit, both producer commits, runtime revision.
- **analytics-engine.** Promote the internal insights contract and the schema commit; persist and expose media families, family signals, and medium rarity through a typed model. Pins: catalog API contract commit, schema commit, runtime revision.

## Wave 4: clients and site (parallel)

- **graph-explorer.** Promote the routes contract; family-grouped multi-select media filter, grouped media badges, and a search facet. Pins: catalog API contract commit.
- **mcp-server.** Promote the routes contract and the agent-tools revision; add a `media` filter to search and document the block in release details. Pins: catalog API contract commit, runtime and agent-tools revision.
- **operations-console.** Promote the console contract; show media mapping coverage and the top unmapped names per extraction in the data-quality view. Pins: catalog API contract commit.
- **Public site.** Replace record-centric copy with media-neutral copy. Pins: none.

## Wave 5: deployment

Cut both extractor services over to per-source images pinned by digest, as ADR 0005 prescribes, one source at a time; remove the cross-source health wait; extend the smoke stack so a fixture release is asserted to carry canonical media in PostgreSQL and `Medium` nodes with `ISSUED_ON` edges in Neo4j; update the architecture and usage documentation. Pins: released images from waves 1 to 4.

## Explicit non-goals of this program

Two adjacent gaps were found while planning and are tracked separately rather than folded into these waves:

- MusicBrainz events are published with an empty content hash. The fix lands in `musicbrainz-ingestion` as its own change before wave 1 attaches the canonical block, so the block is covered by the hash from the first release that carries it.
- The retired combined ingestion repository still carried an unfinished metrics epic from before the ADR 0005 split. It was closed as superseded by the completed metrics work in the two source-owned repositories.

Also outside this program: MusicBrainz recordings, works, and tracks; creating MusicBrainz-only entities in the graph; per-medium telemetry; and any vinyl-specific service. Each of those is a later decision with its own record.
