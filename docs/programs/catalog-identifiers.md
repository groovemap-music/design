# Catalog-identifiers program rollout

**Status: wave 0 published 2026-09-14. Waves 1 to 5 are not started.**

This document records the rollout plan for
[ADR 0011](../adr/0011-catalog-identifiers-and-manufacturing-credits.md). The decision and
both vocabularies live in this repository; implementation is delivered as one molecule per
repository in five waves, each filed from this record after the decision was accepted.

The wave order is a dependency order, not a schedule. Every later wave consumes a contract an
earlier wave publishes, so a wave begins when the artifacts it pins exist at a reviewed commit.

| Wave | Repositories | What the wave delivers |
| --- | --- | --- |
| 0 | design | ADR 0011, both vocabularies with their schemas and fixtures, and this plan. |
| 1 | discogs-ingestion, musicbrainz-ingestion, python-libraries, database-schema | The `identifiers` and `companies` blocks on Discogs events, the MusicBrainz country and catalogue-number whitelist additions, the vendored vocabularies and runtime helpers, and the persistence contract carrying the new indexes and graph constraints. |
| 2 | discogs-sql-loader, musicbrainz-sql-loader, discogs-graph-enricher, musicbrainz-graph-enricher | Minted `barcode`, `catalog_number`, and `matrix` aliases, `Company` nodes, `CREDITED_TO` edges, and `Release.country` in both PostgreSQL and Neo4j write paths. |
| 3 | catalog-api | The barcode and catalogue-number lookup endpoint, the `country` search facet, and identifiers and companies on release detail. |
| 4 | graph-explorer, mcp-server | Consumer contracts promoted; lookup and company credits surfaced in search and the release view. |
| 5 | deployment | The smoke assertion that a barcode resolves to a release after ingestion. |

## Artifacts every wave pins

| Artifact | Owner | How a consumer pins it | How the pin is verified |
| --- | --- | --- | --- |
| `taxonomy/identifiers/v1/identifier-types.json` | design | Vendor the file byte for byte beside a source record with the design commit and SHA-256 | The repository's check gate recomputes the digest and fails on drift |
| `taxonomy/company-roles/v1/company-roles.json` | design | Vendor the file byte for byte beside a source record with the design commit and SHA-256 | The repository's check gate recomputes the digest and fails on drift |
| `groovemap.catalog-events` v1 contract with the `identifiers` and `companies` fields | discogs-ingestion, musicbrainz-ingestion | Promote `contract.json`, `source.json`, and the generated binding from a reviewed producer commit | `just source-check` (consumers) and `just contract-check` (producers) |
| Persistence contract v1 with the identifier and company GIN indexes, the `Company` constraint, and the `CREDITED_TO` and `Release.country` graph additions | database-schema | Promote `contracts/persistence/v1` from a reviewed schema commit | `just source-check` |
| `groovemap-runtime` revision that ships `common.identifiers` | python-libraries | Pin the immutable commit in `pyproject.toml` | `just source-check` compares the pin with the persistence compatibility record |
| Catalog API consumer contracts with the lookup route, the `country` facet, and the identifiers and companies fields on release detail | catalog-api | Promote the matching `contracts/catalog-api/<consumer>/v1` set | `just source-check` |

The two vocabulary digests at the commit that published this program:

```text
2df8a691173f779b2d2076f31e8abd01d160e51f4f371de99f1f8e1cb12f26a5  taxonomy/identifiers/v1/identifier-types.json
03ab8689ba14768dceffb756a71475c01797caea8d18ba9943cd5f69b3d705de  taxonomy/company-roles/v1/company-roles.json
```

Regenerate them from the exact bytes with `shasum -a 256`; `just publication-readiness` prints
the same values as `identifier_types_sha256` and `company_roles_sha256`. A consumer pins the
design commit and the digest together, so a vocabulary change is always a re-vendoring with a
new source record rather than an in-place edit.

## Wave 0: design (this repository)

Record ADR 0011, publish `taxonomy/identifiers/v1` and `taxonomy/company-roles/v1` with their
schemas and conformance fixtures, and publish this plan. Done when `just check` passes and the
publication handoff prints both vocabulary digests. Pins: none.

## Wave 1: producers, runtime, schema (parallel)

- **discogs-ingestion.** Vendor both vocabularies with a digest check each. Compute the
  additive `identifiers` and `companies` blocks at the normalization boundary, before the
  content hash is recomputed, exactly as ADR 0007 attaches the `media` block: map the raw
  `identifiers` list through the identifier vocabulary, lift a `catalog_number` item from each
  label entry's non-empty `catno`, map the raw `companies` list through the company-role
  vocabulary, and derive the sorted `aliases` list from whichever items belong to an alias
  namespace. Add a data-quality rule that surfaces `unmapped.types` and `unmapped.roles`.
  Regenerate fixtures and document both additive fields. Pins: both vocabulary digests.
- **musicbrainz-ingestion.** Widen the release field whitelist with `country`, the
  release-event list (date and area per event), and the catalogue numbers carried inside
  `label-info`; `barcode` already passes and keeps passing. Regenerate fixtures and document
  the three additive fields. Pins: neither vocabulary — this is a whitelist change only.
- **python-libraries.** Vendor both vocabularies; add `common.identifiers` with the reference
  mapper for both blocks, the alias-normalization rules (`digits_only`,
  `upper_collapse_space`, `collapse_space`), and typed accessors for the identifiers and
  companies blocks in the agent tools. Bump the synchronised version. Pins: both vocabulary
  digests.
- **database-schema.** Add GIN indexes on `data->'identifiers'` and `data->'companies'` to the
  Discogs releases table inside persistence contract v1; no new PostgreSQL column. Add the
  Neo4j `(:Company {id, name})` uniqueness constraint on `id`, document the
  `(:Release)-[:CREDITED_TO {role, role_category, source}]->(:Company)` edge shape, and add the
  `Release.country` range index. Document that the existing per-user `Release.catalog_number`
  property is unaffected. Pins: neither vocabulary — the blocks are opaque JSONB here.

## Wave 2: loaders and enrichers (parallel)

- **discogs-sql-loader.** Promote the producer and schema commits and the runtime revision.
  Mint `barcode` and `catalog_number` aliases per batch through `common.identity`, resolving
  the whole batch in the existing transaction, and backfill the alias rows for release rows
  whose content hash did not change. Pins: producer commit, schema commit, runtime revision.
  Verified by `just source-check`.
- **musicbrainz-sql-loader.** Promote the producer and schema commits and the runtime
  revision. Attach `barcode` aliases to the release's native id on release upsert. Pins:
  producer commit, schema commit, runtime revision. Verified by `just source-check`.
- **discogs-graph-enricher.** Promote the producer and schema commits and the runtime
  revision. Merge `Company` nodes and `CREDITED_TO` edges prune-then-merge in both write
  paths, following the `CREDITED_ON` and `ISSUED_ON` precedents, so a company removed upstream
  disappears rather than accumulating; write `Release.country` from the release's country.
  Pins: producer commit, schema commit, runtime revision. Verified by `just source-check`.
- **musicbrainz-graph-enricher.** Promote the producer commit. Write `mb_country` on releases
  it matches; the rule that this enricher creates no release without a Discogs identifier is
  unchanged. Pins: producer commit, schema commit, runtime revision. Verified by
  `just source-check`.

## Wave 3: API

- **catalog-api.** Promote the schema commit, the runtime revision, and both producer
  contracts. Add `GET /api/lookup/{provider}/{value}` for the `barcode` and `catalog_number`
  providers, normalising the value with the namespace's declared rule and resolving it through
  `provider_aliases`; an unsupported provider is rejected rather than silently returning
  nothing. Add a `country` search facet. Add the `identifiers` and `companies` blocks to the
  release detail response. Publish the updated consumer contracts. Pins: schema commit,
  runtime revision, both producer contracts, both vocabulary digests. Verified by
  `just source-check` and the repository's own contract check.

## Wave 4: clients (parallel)

- **graph-explorer.** Promote the routes contract. Add barcode and catalogue-number lookup to
  search and show company credits on the release view. Pins: catalog API contract commit.
  Verified by `just source-check`.
- **mcp-server.** Promote the routes contract and the agent-tools revision. Add a lookup tool
  and surface company credits in release details. Pins: catalog API contract commit, runtime
  and agent-tools revision. Verified by `just source-check`.

## Wave 5: deployment

Extend the smoke stack so a fixture barcode is asserted to resolve to a release through
`GET /api/lookup/barcode/{value}` after ingestion. Update the architecture and usage
documentation. Pins: the released images from waves 1 to 4.

## Explicit non-goals of this program

Each of these is real, each is out of scope here, and each is deferred to its own record
rather than folded into a wave, exactly as ADR 0011 records:

- **MusicBrainz manufacturing relations.** They stay in the generic relations bag. Mapping
  them onto the company-role categories means reconciling two relationship vocabularies, and
  that is a decision about equivalence, not about storage.
- **Places on releases.** Both catalogs can name where something happened, and a pressing
  plant or a studio is arguably a place with a location rather than a company with a name.
  This program models the credit, not the geography behind it.
- **ISRC minting.** The `isrc` provider namespace ADR 0009 reserved stays reserved. Minting it
  needs a recording entity to hang it on, which ADR 0009 explicitly left undecided; the
  Discogs `ISRC` identifier string is a release-level annotation and is not the same identity.
- **Identifier-driven edition matching.** A shared matrix inscription or barcode across two
  releases is strong evidence they are the same pressing. This program makes that evidence
  available and queryable; what a matcher does with it is not settled here.
- **The per-user `Release.catalog_number` property.** `catalog-api`'s live per-user Discogs
  synchronisation already writes this property from one user's collection row. It is a
  per-collection assertion, not the catalog-wide identifier record this program creates, and
  the two are deliberately left unreconciled: neither overwrites the other.
