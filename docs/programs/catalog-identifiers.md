# Catalog-identifiers program rollout

**Status (2026-09-21): waves 0–4 implemented; wave 5's released-image, disposable
identifier-lookup smoke passed. This records release verification, not a production rollout.**

This document preserves the rollout plan for
[ADR 0011](../adr/0011-catalog-identifiers-and-manufacturing-credits.md). The decision and
both vocabularies live in this repository; implementation was delivered as one molecule per
repository in five waves. The planned wave sections below remain as execution history. This
status section records the maintained result rather than rewriting those sections into
retrospective prose.

| Wave | Implemented evidence | Released / smoke-tested evidence |
| --- | --- | --- |
| 0 | design (`d06e1571f6acce6a246e4c0b6be866ecbea44c72`) published ADR 0011, both v1 vocabularies, schemas, fixtures, and this plan; the additive MusicBrainz source followed at `5bfdf1005c5d95c99143e8c2acd189e127e1cb10`. | Published source artifacts; no image or runtime smoke for this wave. |
| 1 | discogs-ingestion (`84dd280206cb830533d0d6691764218700d6f785`, re-vendor `f2970659f5ee64f6fd0cd0a4bbd958421dbc47f0`) attaches `identifiers`/`companies`; python-libraries (`381e71b4b5d2e4251cb349962a6d100ff2db964a`, follow-on `7abcb3ba9f467d9bdcd5b3df0b1a342a2efda73b`) ships `common.identifiers`; database-schema (`03e8aba11f72d26237f7dfbbecf234ae9437e85e`) adds the GIN indexes, Company constraint, `CREDITED_TO`, and country index. musicbrainz-ingestion (`d24d03a46415a8d3ddd6d2832c767ac742a7dd4c`, producer follow-on `ae01d967e72e18c82cac2e844daa1dfeb81a32a6`) now computes the additive `identifiers` block before the content hash. | Producer code merged; the digest-pinned deployment smoke below verifies the released Discogs lookup path, not every producer path. |
| 2 | discogs-sql-loader `v0.3.0` (`fa13a00525e1041d422c80b898a5391acd7b6b26`), musicbrainz-sql-loader `v0.3.0` (`2c6436e41ae5b5b4fad10a8258c8939235dbbf51`, transition `55cbb8ef209e54aac0a65b94d95eec74b4494ead`), discogs-graph-enricher `v0.3.0` (`79077febc908db217ff87b3c8db21f903794acfc`), musicbrainz-graph-enricher `v0.3.0` (`306bfdcc9b902ada04cb6ff339061f2ff99c9a18`). Both SQL loaders mint barcode/catalogue-number aliases; graph enrichers project credits and country. The MusicBrainz loader now consumes the producer block unchanged and synthesizes one only for legacy events lacking it. | The released `discogs-sql-loader:v0.3.0` and `discogs-graph-enricher:v0.3.0` digests were exercised in wave 5; MusicBrainz's transition is merged and tested in its repository, not claimed as part of that smoke. |
| 3 | catalog-api (`a28ecb6afe14f3eefd365e114aa6c143b81cec24`) published `GET /api/lookup/{provider}/{value}`, the country search facet, and identifier/company/country release detail. | Released `catalog-api:v0.4.0` digest was exercised by the wave-5 lookup smoke. |
| 4 | graph-explorer `v0.2.0` (`9a739075a102e927753811c61151a2c2132f5d74`) implements lookup and release-view credits. mcp-server (`a1595ade2b18968fa2ffddd79d554ed5d6414977`, completion `c5865c10ec2ed9e62dd98d1bc88525eb956caf94`) provides `lookup_release` and documents/tests unchanged `companies` pass-through in `docs/tools.md` and `tests/test_server.py`. **Complete.** | MCP completion is merged test/doc evidence; no separate client-image smoke is claimed here. |
| 5 | deployment (`a57c353db9d30e6e6832a64231a63bd74ce5ce14`, verification `36b89a9b2e76b677bedaa05064a5c326cb89c10b`) extended `tests/deploy/test_media_smoke.py` and `scripts/smoke_media.py` to assert alias minting, native-id resolution, and HTTP lookup. | `docs/maintenance.md` records the 2026-09-21 disposable, digest-pinned GHCR smoke: **15/15 PASS**, including barcode `5 012394 144777` → normalized `5012394144777` → Discogs release `999000001`; containers, volumes, and network were torn down, with no production Compose change. |

**Implementation note (MusicBrainz identifiers, waves 1 and 2).** The initial wave-1 delivery
only widened raw fields, and the initial wave-2 loader assembled the block downstream. The
merged follow-ons closed that gap: `musicbrainz-ingestion` attaches the vocabulary-mapped
block before recomputing the content hash (`src/musicbrainz/jsonl_parser.rs`,
`src/musicbrainz/identifiers.rs`; `ae01d967e72e18c82cac2e844daa1dfeb81a32a6`), and
`musicbrainz-sql-loader` promotes that producer contract and passes its block to
`alias_refs_for_release`, building a compatibility block only when the event omits it
(`contracts/catalog-events/v1/source.json`, `brainztableinator/_record_processing.py`;
`55cbb8ef209e54aac0a65b94d95eec74b4494ead`). The wave-5 disposable smoke below covers
the Discogs barcode path; it does not establish a released MusicBrainz-path smoke result.

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

The following sequence is complete, superseding the original future-tense consumer-pin
proposal. The merged source records and consumer revisions are:

1. **python-libraries** already pinned design commit
   `5bfdf1005c5d95c99143e8c2acd189e127e1cb10` and identifier digest
   `87b844a20f35d45e7ba176df58d6ccf3d7bc88beecda90457b1a2afb3432fb34` in its
   identifier source record before the later runtime follow-on
   `7abcb3ba9f467d9bdcd5b3df0b1a342a2efda73b`,
   which added MusicBrainz-source validation coverage. It was not awaiting a digest bump.
2. **discogs-ingestion** re-vendored the identifier vocabulary at
   `f2970659f5ee64f6fd0cd0a4bbd958421dbc47f0`:
   `contracts/catalog-events/vocab/source.json` pins that same design commit and digest;
   the separate company-role source remains at the original design commit and unchanged digest.
3. **musicbrainz-ingestion** at
   `ae01d967e72e18c82cac2e844daa1dfeb81a32a6`
   vendors the identifier vocabulary under `contracts/catalog-events/vocab/identifiers-source.json`
   at the same design commit and digest, and publishes the producer-owned block. The loader's
   `55cbb8ef209e54aac0a65b94d95eec74b4494ead`
   promotion consumes it while retaining the explicit legacy fallback.

The merged MCP completion is
`c5865c10ec2ed9e62dd98d1bc88525eb956caf94`:
`docs/tools.md` describes the top-level `companies` block, and `tests/test_server.py` asserts
unchanged pass-through and a company-credit docstring. The released-image evidence is in
deployment's `docs/maintenance.md` at `36b89a9b2e76b677bedaa05064a5c326cb89c10b`:
GHCR index digests `sha256:09f55827f972ec289baad7128acca061739fd9d4d350f23f3d6d22afeafee7e6`
(`discogs-sql-loader:v0.3.0`), `sha256:e95fabb7633859c94e0913f9122ccbaed18a04a017c486886c38840c230ff80d`
(`discogs-graph-enricher:v0.3.0`), and
`sha256:4889f1ce04568a335bdfe698e11a3c8133238e0b0b61c91447ea4448a3e3ae43`
(`catalog-api:v0.4.0`) passed the 15/15 disposable barcode-lookup smoke. That record also
documents teardown and explicitly says no live Compose project was changed.

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
