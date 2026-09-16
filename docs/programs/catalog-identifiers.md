# Catalog-identifiers program rollout

**Status: waves 0 to 3 and 5 completed 2026-09-15. Wave 4 open: `mcp-server` has not yet
surfaced company credits in release details.**

This document preserves the rollout plan for
[ADR 0011](../adr/0011-catalog-identifiers-and-manufacturing-credits.md). The decision and
both vocabularies live in this repository; implementation was delivered as one molecule per
repository in five waves. The planned wave sections below remain as execution history. This
status section records the maintained result rather than rewriting those sections into
retrospective prose.

| Wave | Repositories (revision or tag) | Completed result |
| --- | --- | --- |
| 0 | design (`d06e1571f6acce6a246e4c0b6be866ecbea44c72`) | Published ADR 0011, `taxonomy/identifiers/v1`, `taxonomy/company-roles/v1` with their schemas and fixtures, and this plan. |
| 1 | discogs-ingestion (`84dd280206cb830533d0d6691764218700d6f785`), python-libraries (`381e71b4b5d2e4251cb349962a6d100ff2db964a`), database-schema (`03e8aba11f72d26237f7dfbbecf234ae9437e85e`), musicbrainz-ingestion (`d24d03a46415a8d3ddd6d2832c767ac742a7dd4c`) | `discogs-ingestion` attached the `identifiers` and `companies` blocks and vendored both vocabularies; `python-libraries` shipped `common.identifiers`; `database-schema` added the `idx_releases_identifiers`/`idx_releases_companies` GIN indexes, the `Company` uniqueness constraint, the `CREDITED_TO` edge, and the `Release.country` index. `musicbrainz-ingestion` widened the release field whitelist (`country`, `release-events`, `label-info[].catalog-number`) but does not itself compute the additive `identifiers` block — see the implementation note below the table. |
| 2 | discogs-sql-loader `v0.3.0` (`fa13a00525e1041d422c80b898a5391acd7b6b26`), musicbrainz-sql-loader `v0.3.0` (`2c6436e41ae5b5b4fad10a8258c8939235dbbf51`), discogs-graph-enricher `v0.3.0` (`79077febc908db217ff87b3c8db21f903794acfc`), musicbrainz-graph-enricher `v0.3.0` (`306bfdcc9b902ada04cb6ff339061f2ff99c9a18`) | Both SQL loaders mint `barcode`/`catalog_number` aliases through `common.identifiers`; both graph enrichers merge `Company` nodes and `CREDITED_TO` edges and write `Release.country`/`mb_country`. `musicbrainz-sql-loader` additionally assembles the `identifiers` block itself, from the raw fields `musicbrainz-ingestion` widened in wave 1, via `common.identifiers` — see the note below. |
| 3 | catalog-api `v0.3.0` (`a28ecb6afe14f3eefd365e114aa6c143b81cec24`) | Published `GET /api/lookup/{provider}/{value}` for the `barcode` and `catalog_number` providers, the `country` search facet, and the `identifiers`/`companies`/`country` blocks on release detail (`api/routers/lookup.py`, `api/queries/search_queries.py`, `api/routers/explore.py`). |
| 4 | graph-explorer `v0.2.0` (`9a739075a102e927753811c61151a2c2132f5d74`), mcp-server `v0.2.2` (`a1595ade2b18968fa2ffddd79d554ed5d6414977`) | `graph-explorer` promoted the routes contract, added barcode/catalogue-number lookup to search, and renders company credits on the release view (`explore/static/js/app.js`'s `_releaseCredits`). `mcp-server`'s `v0.2.0` added the `lookup_release` tool, but `get_release_details` documents only the ADR 0007 media block — the CHANGELOG's `v0.2.0` feature list and the tool docstring show no company-credit surfacing was added. **Open.** |
| 5 | deployment (`a57c353db9d30e6e6832a64231a63bd74ce5ce14`) | Extended the smoke stack (`tests/deploy/test_media_smoke.py`, `scripts/smoke_media.py`) to assert a minted `barcode` alias row, its resolution to the release's native id, and `GET /api/lookup/barcode/{value}` resolving to that release after ingestion. |

**Implementation note (MusicBrainz identifiers, waves 1 and 2).** The wave-1 text below asks
`musicbrainz-ingestion` to compute the additive `identifiers` block itself, mapped through the
identifier vocabulary's `musicbrainz` section, at the normalization boundary before the content
hash is recomputed — exactly as `discogs-ingestion` does for Discogs events. In the delivered
system, `musicbrainz-ingestion` widened the field whitelist only (`country`, `release-events`,
`label-info[].catalog-number`, alongside the pre-existing `barcode`); `musicbrainz-sql-loader`
builds a minimal `identifiers` block from those same raw fields and validates it with
`common.identifiers.alias_refs_for_release` itself, in wave 2, rather than consuming a block
`musicbrainz-ingestion` already published on the event
(`contracts/catalog-events/v1/source.json`'s `migration_transform` in `musicbrainz-sql-loader`
records the promoted producer revision as carrying `country`, `release_events`, and
`catalog_numbers` — not an `identifiers` block). The observable outcome the plan wanted — a
MusicBrainz barcode minting the same `barcode` alias a Discogs one does — is delivered and is
asserted end to end by the wave-5 smoke stack, but the block is not covered by the producer's
content hash the way the plan intended. That gap is real and is left to its own record rather
than reopening this one.

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
87b844a20f35d45e7ba176df58d6ccf3d7bc88beecda90457b1a2afb3432fb34  taxonomy/identifiers/v1/identifier-types.json
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
  `label-info`; `barcode` already passes and keeps passing. Compute the additive `identifiers`
  block at the normalization boundary, before the content hash is recomputed: map the
  release's `barcode` and each `label-info[].catalog-number` through the identifier
  vocabulary's `musicbrainz` section exactly as `discogs-ingestion` maps its own raw
  `identifiers` list, and derive `aliases` the same way, so a MusicBrainz barcode mints the
  same `barcode` alias a Discogs one does. Add a data-quality rule that surfaces
  `unmapped.types`. Regenerate fixtures and document the four additive fields. Pins: the
  identifier vocabulary digest; the company-role vocabulary is not pinned — MusicBrainz
  manufacturing relations remain out of scope (see Explicit non-goals).
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

## Post-wave-0 addition: MusicBrainz as an identifier source

`musicbrainz-ingestion` needed the identifier vocabulary to name its own release fields, and
`taxonomy/identifiers/v1/identifier-types.json` had no `musicbrainz` section when wave 1 needed
one — the vocabulary mapped only the Discogs field names (`identifiers`, `labels[].catno`).
This addition closes that gap additively, within version 1: `identifier-block.schema.json`'s
`source.provider` enum now admits `musicbrainz` alongside `discogs`, and `source.field` admits
the MusicBrainz fields that yield identifiers (`barcode` and `label-info[].catalog-number`);
`identifier-types.json` gained a `musicbrainz` section mapping those two field names onto the
existing `barcode` and `catalog_number` canonical types — no canonical type was added. No
existing type, Discogs mapping, alias namespace, or normalization rule changed.

The vocabulary's SHA-256 moved to

```text
87b844a20f35d45e7ba176df58d6ccf3d7bc88beecda90457b1a2afb3432fb34
```

as a result, on design main commit `5bfdf1005c5d95c99143e8c2acd189e127e1cb10` (merged
2026-09-16); `just publication-readiness` prints the same value as `identifier_types_sha256`.
The company-role vocabulary digest is unchanged
(`03ab8689ba14768dceffb756a71475c01797caea8d18ba9943cd5f69b3d705de`).

As of this record, `discogs-ingestion` and `python-libraries` still pin the pre-addition
digest (`2df8a691173f779b2d2076f31e8abd01d160e51f4f371de99f1f8e1cb12f26a5`, design commit
`d06e1571f6acce6a246e4c0b6be866ecbea44c72`) — harmless today, since neither consumes the new
`musicbrainz` section. A future re-vendoring should pick up the addition in this order,
mirroring the events program's fit-surface sequencing:

1. **python-libraries** — bump the vendored copy first; `common.identifiers.alias_refs_for_release`
   already validates any well-formed `identifiers` block regardless of which vocabulary section
   produced it, so this re-vendoring is a digest bump with no mapper change required.
2. **discogs-ingestion** — bump the vendored copy; its own Discogs-only mapping is unaffected
   by the addition.
3. **musicbrainz-ingestion** — vendor the vocabulary for the first time and compute the
   additive `identifiers` block itself at the normalization boundary, closing the wave-1 gap
   this record's completed-result table notes: today that block is instead assembled
   downstream, in `musicbrainz-sql-loader`.

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
