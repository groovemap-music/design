# Native identity and first-party events program rollout

**Status: wave 0 published 2026-09-13. Waves 1 to 4 are not started.**

This document records the rollout plan for
[ADR 0009](../adr/0009-native-identity-and-provider-aliases.md) and
[ADR 0010](../adr/0010-first-party-events-consent-and-deletion.md). Both decisions and both
vocabularies live in this repository; implementation is delivered as one molecule per
repository in four waves, each filed from this record after the decisions were accepted.

The wave order is a dependency order, not a schedule. Every later wave consumes a contract an
earlier wave publishes, so a wave begins when the artifacts it pins exist at a reviewed commit.

| Wave | Repositories | What the wave delivers |
| --- | --- | --- |
| 0 | design | ADR 0009, ADR 0010, both vocabularies with their schemas and fixtures, and this plan. |
| 1 | database-schema, python-libraries | The identity and `activity` persistence contract, and the shared runtime helpers that mint and validate against it. |
| 2 | discogs-sql-loader, musicbrainz-sql-loader, catalog-api | Native identifiers minted at ingest, and the event, consent, export, and erasure surfaces. |
| 3 | analytics-engine, graph-explorer, mcp-server | The read path for logged behaviour and the clients that emit outcome events. |
| 4 | deployment | The telemetry entry, partition maintenance, and the erasure and export smoke boundary. |

## Artifacts every wave pins

| Artifact | Owner | How a consumer pins it | How the pin is verified |
| --- | --- | --- | --- |
| `taxonomy/identity/v1/identity-vocabulary.json` | design | Vendor the file byte for byte beside a source record with the design commit and SHA-256 | The repository's check gate recomputes the digest and fails on drift |
| `taxonomy/events/v1/event-types.json` with both envelope schemas | design | Vendor the vocabulary and the schemas byte for byte beside the same source record | The repository's check gate recomputes the digest and validates its own fixtures against the vendored schemas |
| Persistence contract v1 with the identity tables, the `activity` schema, and the Neo4j `gm_id` indexes | database-schema | Promote `contracts/persistence/v1` from a reviewed schema commit | `just source-check` |
| `groovemap-runtime` revision that ships `common.identity` and `common.events` | python-libraries | Pin the immutable commit in `pyproject.toml` | `just source-check` compares the pin with the persistence compatibility record |
| Catalog API consumer contracts with the native identifier fields and the event, consent, export, and erasure routes | catalog-api | Promote the matching `contracts/catalog-api/<consumer>/v1` set | `just source-check` |

The two vocabulary digests at the commit that published this program:

```text
001db32e91c851d49d252c945c1862e47763462acd44fc6ca84df13bae12e3de  taxonomy/identity/v1/identity-vocabulary.json
f64f03164c208477e8ae9c6bc547bba7342f23df96f6b10f21f7fa6f1d21ba74  taxonomy/events/v1/event-types.json
```

Regenerate them from the exact bytes with `shasum -a 256`; `just publication-readiness` prints
the same values as `identity_vocabulary_sha256` and `event_types_sha256`. A consumer pins the
design commit and the digest together, so a vocabulary change is always a re-vendoring with a
new source record rather than an in-place edit.

## Wave 0: design (this repository)

Record both decisions, publish `taxonomy/identity/v1` and `taxonomy/events/v1` with their
schemas and conformance fixtures, and publish this plan. Done when `just check` passes and the
publication handoff prints both vocabulary digests. Pins: none.

## Wave 1: schema and runtime (parallel)

- **database-schema.** Add the five native tables (`catalog_items`, `artifacts`,
  `owned_copies`, `collection_snapshots`, `observations`) with `uuidv7()` defaults, and
  `provider_aliases` with the validity interval and the uniqueness rule on
  `(provider, entity_kind, external_id)` for the currently valid row. Add the additive nullable
  native-identifier columns to the provider-keyed catalog and collection tables. Add the
  `activity` schema: `events` and `impressions` range-partitioned by month on `occurred_at`,
  the `BEFORE UPDATE OR DELETE` immutability trigger that only the erasure procedure may
  bypass, the partition-creation function the writer invokes before insert, `user_subjects`,
  `consent_grants`, and `erasures`. Add the Neo4j `gm_id` range indexes. Persistence contract
  v1 stays: everything here is additive. Pins: both vocabulary digests. Verified by the
  repository's own check gate and its schema tests.
- **python-libraries.** Add `common.identity` to `groovemap-runtime`: the vendored identity
  vocabulary with its digest check, lookup-or-create against `provider_aliases`, and the bulk
  resolve that answers a batch in one `SELECT`, one `INSERT ... ON CONFLICT DO NOTHING`, and
  one re-select. Add `common.events`: the vendored event vocabulary, the envelope model, and
  validation against the published schemas. Bump the synchronised version. Pins: both
  vocabulary digests, the schema commit. Verified by `just source-check` and the digest check
  in the repository's own gate.

## Wave 2: loaders and API (parallel)

- **discogs-sql-loader.** Promote the schema commit and the runtime revision together, because
  the repository's contract check couples the persistence source record, the compatibility
  record, and the runtime pin. Mint through `common.identity` on every artist, label, master,
  and release upsert, resolving the whole batch inside the existing transaction rather than
  per row, and write the native identifier column. Pins: schema commit, runtime revision.
  Verified by `just source-check`.
- **musicbrainz-sql-loader.** Promote the same schema commit and runtime revision. Mint per
  message on artist, label, release, and release-group upsert, and write the native identifier
  column. Pins: schema commit, runtime revision. Verified by `just source-check`.
- **catalog-api.** Promote the schema commit and the runtime revision. Resolve catalog items
  through the alias table on read paths and return native identifiers beside the provider
  identifiers already returned. Mint owned copies, collection snapshots, and observations.
  Add the event recorder, following the existing administrative audit writer: a single
  `INSERT` that never raises to the caller. Log impressions on the search and recommendation
  paths with the policy, candidate set, position, score, and propensity. Emit the collection
  and wantlist events. Add the consent endpoints, the JSON Lines export endpoint, and the
  erasure procedure with its Neo4j and Redis closure. Own the `gm_id` projection job, whose
  scope is that one property. Publish the updated consumer contracts. Pins: schema commit,
  runtime revision, both vocabulary digests. Verified by `just source-check` and the
  repository's contract check.

## Wave 3: analytics and clients

- **analytics-engine.** Promote the catalog API internal-insights contract, the schema commit,
  and the runtime revision. Add the read path over `activity.events` and `activity.impressions`
  and the training-time consent filter that re-checks the grant table rather than trusting the
  snapshot alone. Pins: catalog API contract commit, schema commit, runtime revision. Verified
  by `just source-check`.
- **graph-explorer.** Promote the routes contract and emit recommendation outcome events
  through the API rather than writing them directly. Pins: catalog API contract commit.
  Verified by `just source-check`.
- **mcp-server.** Promote the routes contract and the agent-tools revision, and emit the same
  outcome events through the API. Pins: catalog API contract commit, runtime and agent-tools
  revision. Verified by `just source-check`.

## Wave 4: deployment

Register the single low-cardinality event-writer counter in the closed telemetry catalog that
[ADR 0006](../adr/0006-opentelemetry-metrics.md) defines, with `event_type` as its only
attribute. Schedule partition maintenance and retention for the `activity` tables. Extend the
smoke stack so an erasure request is asserted to leave no row in either activity table, no
subject link, no user subgraph in Neo4j, and no user-keyed Redis key, and so an export request
returns JSON Lines. Update the runbook and the architecture documentation. Pins: the released
images from waves 1 to 3.

## Post-wave-0 addition: the fit surface

`catalog-api` had no `fit` surface in the vocabulary when it needed one, and aliased fit
impressions to `recommendation` (`SURFACE_FIT = SURFACE_RECOMMENDATION`, policy id
`cratefit_v0`); `graph-explorer` posts the fit pane's outcome events under the same
`recommendation` terms for the same reason. This addition closes that gap additively, within
version 1: `taxonomy/events/v1/event-types.json` now declares a `fit` surface with its own
`fit.shown`, `fit.opened`, `fit.saved`, `fit.dismissed`, and `fit.hidden` event types, mirroring
the `recommendation` surface's structure and payload schemas. No existing surface, type, or
payload schema changed.

The vocabulary's SHA-256 moved to
`920a63d1eda5e909e6d6bd4850df005a17e592fbfc6f8f3152a15833f74fa8ad` as a result; `just
publication-readiness` prints the same value as `event_types_sha256`. Consumers re-vendor in
this order, because each is where the `recommendation` alias for fit currently lives or is
consumed:

1. **python-libraries** — bump the vendored copy in `common.events` first, since
   `catalog-api` and `graph-explorer` both pin a `groovemap-runtime` revision rather than the
   vocabulary directly.
2. **catalog-api** — promote the runtime revision, retire the `SURFACE_FIT =
   SURFACE_RECOMMENDATION` alias and the `cratefit_v0` policy id's borrowed surface, and emit
   `fit.*` events under the new `fit` surface instead.
3. **graph-explorer** — promote the routes contract once `catalog-api` publishes it, and post
   the fit pane's outcome events as `fit.opened` / `fit.saved` / `fit.dismissed` / `fit.hidden`
   instead of the borrowed `recommendation.*` terms.

## Explicit non-goals of this program

Three adjacent gaps were found while planning. Each is real, each is out of scope here, and
each is filed as its own record rather than folded into a wave:

- **The two foreign keys to `users` that carry no cascade rule.** `extraction_history` and the
  administrative audit log both reference `users` without one. ADR 0010 works around that by
  soft-erasing the `users` row in place, which is what lets erasure need no constraint change
  and lets an administrative audit trail that exists for a different purpose survive. Deciding
  the cascade rule itself belongs to `database-schema` in its own record.
- **The undeclared `COLLECTED` edge in the graph schema.** `catalog-api` writes
  `COLLECTED {instance_id}` edges that `database-schema` never declared. Erasure removes them
  with `DETACH DELETE` on the user node, so the deletion closure holds, but declaring the edge
  and bringing it under a named owner is a separate follow-on.
- **Recordings and works as native kinds.** The eight entity kinds in the identity vocabulary
  cover what both catalogs deliver today and what users assert today. Adding a kind is
  additive, but how recordings and works relate to artifacts is an unresolved modelling
  question and is not settled by silence here.

Also outside this program, each already recorded as deferred in the decision it belongs to:
contraction of the provider-keyed columns and the contract version that carries it,
enricher-side minting, database role separation for the `activity` schema, retention periods
and the partition-drop schedule, model retraining policy after an erasure, and client-side
event batching.
