# ADR 0010: First-party events, consent, and deletion closure

- Status: Accepted

## Context

GrooveMap keeps no record of what it showed a user or what the user did next. Recommendations
are computed on request and cached in Redis under per-user keys with a 28-day expiry, rarity
is computed on read, and search results are never logged. The only append-only writer anywhere
in the system is `admin_audit_log` in `catalog-api`, which records administrative actions
through a single `INSERT` that never raises to its caller. There is no impression record, no
feedback record, and no product-event record of any kind.

The consequence is that recommendation quality cannot be measured, only asserted. Evaluating a
ranking policy offline against logged behaviour requires knowing which candidates were
considered, in what position each was shown, and with what probability the policy that was
live at the time would have chosen it. None of those can be reconstructed after the fact: the
candidate set is gone once the request returns, position is not stored anywhere, and the
propensity belongs to a policy version that may no longer exist. A log that omits them is not
a smaller log, it is an unusable one.

The same absence has a second face. There is no account deletion path and no data export path.
`extraction_history.triggered_by` and `admin_audit_log.admin_id` reference `users` with no
cascade rule, Neo4j carries `COLLECTED` edges written by `catalog-api` that the schema never
declared, and the per-user Redis snapshots outlive anything a relational delete would touch.
Adding a behavioural log to that situation without deciding erasure first would mean creating
personal data the system has no way to remove.

This record therefore decides logging and erasure together. Following the European Data
Protection Board's guidance on pseudonymisation, a pseudonymous subject identifier does not
take the data outside the scope of personal data: it reduces linkability, and it is treated
here as a containment measure rather than an exemption. The envelope column sets below, like
the alias table in [ADR 0009](0009-native-identity-and-provider-aliases.md), are this
organization's own design, informed by the envelope practice CloudEvents and Snowplow
self-describing events established: a small set of typed envelope columns every event carries,
with the type-specific body kept separate and versioned.

## Decision

### Two append-only tables in an `activity` schema

Both tables are range-partitioned by month on `occurred_at`, so retention and archival act on
whole partitions rather than on row deletes.

`activity.events` carries the typed envelope: `event_id` (UUID version 7), `event_type`,
`schema_version`, `subject_id`, `session_id`, `occurred_at`, `recorded_at`, `producer`,
`consent_purposes` (snapshotted at write), `model_version`, `feature_version`,
`idempotency_key` (unique together with `occurred_at`), and a `payload` JSONB body. Splitting
`occurred_at` from `recorded_at` keeps a late or replayed write honest, and the idempotency key
scoped to the occurrence time is what makes a retried write safe inside a partitioned table.

`activity.impressions` carries what a shown recommendation needs for later evaluation:
`impression_id`, `subject_id`, `surface`, `policy_id`, `candidate_set_id`, `position`,
`item_id` (the native identifier from ADR 0009), `score`, `propensity`, `request_id`, and
`occurred_at`. The four fields that justify a separate table are `policy_id`,
`candidate_set_id`, `position`, and `propensity`: each describes the decision as it was made,
and none can be recovered afterwards from the catalog or from the outcome. Everything else
about an impression is derivable later; these are not.

Outcomes are not columns on the impression. Opened, saved, dismissed, and hidden are events in
`activity.events` whose payload carries the `impression_id`, which keeps the impression row
immutable and lets one impression carry several outcomes over time.

### Immutability enforced by the database

A `BEFORE UPDATE OR DELETE` trigger on both tables raises unless the session-local setting
`groovemap.erasure` is on. Only the erasure procedure sets it. The guarantee is therefore a
property of the database rather than a convention the application is trusted to keep, and a
mistaken migration or an ad hoc session cannot quietly rewrite history.

Database role separation would be a second, independent layer here. It is a deployment concern
and is not decided in this record.

### Pseudonymous subjects and per-purpose consent

`activity.user_subjects` links `users.id` to a `subject_id` UUID. Events and impressions
reference `subject_id` only and never the user id, so the behavioural tables can be read,
joined, and analysed without carrying account identity, and the link is one row to remove.

`activity.consent_grants` records `(user_id, purpose, granted_at, revoked_at)` with the purpose
drawn from exactly two values: `product_analytics` and `model_training`. Consent is enforced
twice. Writers snapshot the purposes active at the moment of the write onto the row, which is
what makes an old row interpretable years later without reconstructing the grant history.
Training-time readers filter against the grant table again, so a revocation is honoured going
forward for data that was lawfully collected before it. Neither check replaces the other: the
snapshot records what was true, the re-check enforces what is true now.

### Erasure, with its cross-store closure

Erasure is a hard delete, keyed by `subject_id`, executed under the trigger bypass. It is not
a flag, and the tables are not tombstoned: the point of the immutability trigger is that the
erasure procedure is the only path that can remove a row, and the point of erasure is that the
row is gone.

The procedure covers every store that holds something keyed to the user:

- `activity.events` and `activity.impressions` rows for the subject, hard deleted.
- The `activity.user_subjects` link row, removed, so the pseudonym cannot be re-associated.
- The user's Neo4j subgraph, removed with `DETACH DELETE` on the `User` node, which takes the
  `COLLECTED` edges with it.
- Every user-keyed Redis snapshot and cache key, deleted rather than left to expire.
- The `users` row, soft-erased in place: the email replaced by an opaque marker, the password
  cleared, `is_active` set false. This is deliberate. Two foreign keys to `users` carry no
  cascade rule, and soft-erasing the row in place means erasure needs no constraint change and
  cannot orphan an administrative audit trail that exists for a different purpose.
- `activity.erasures`, which records `subject_id`, `requested_at`, `completed_at`, the row
  counts removed, and the model versions that had already been trained before the erasure ran.

That last field is the honest part of the record. A model trained before an erasure is not
retrained by deleting rows, and naming the affected versions is what makes the residual
question answerable rather than invisible.

### Export

Export is JSON Lines, one object per event and per impression, served by a `catalog-api`
endpoint and covering everything keyed to the requesting user's subject. JSON Lines is chosen
because the natural unit is a row, the result streams without being materialised, and the same
file is readable by a person and by a tool.

### Transport and observability

Events are written in process to PostgreSQL by `catalog-api`, following the `admin_audit_log`
writer that already exists there: a single `INSERT` that never raises to the caller, so a
logging failure degrades the record and never the request. No broker is introduced. The frozen
`groovemap.catalog-events` v1 envelope from [ADR 0005](0005-source-owned-catalog-ingestion.md)
is untouched, and this decision adds no new exchange, queue, or consumer to it; catalog
ingestion and product behaviour are different streams with different owners, and merging them
would make one contract answer to two release trains.

Partition creation is a function owned by `database-schema`, invoked by the writer before
insert, so a write into a month that has no partition creates it rather than failing. Partition
maintenance and retention scheduling are deployment's.

Observability is deliberately thin: one counter, registered in the closed `groovemap.*` catalog
that [ADR 0006](0006-opentelemetry-metrics.md) defines, with `event_type` as its only
attribute. Attribute values stay low-cardinality, so no subject id, session id, item id, or
request id is ever an attribute. The event tables are the analytical record; metrics only say
whether the writer is working.

### Closed event-type vocabulary, version 1

Version 1 covers only surfaces that exist today:

```
search.query
search.result_impression
recommendation.shown
recommendation.opened
recommendation.saved
recommendation.dismissed
recommendation.hidden
collection.item_added
collection.item_removed
collection.item_updated
wantlist.item_added
wantlist.item_removed
consent.granted
consent.revoked
account.export_requested
account.erasure_requested
```

The naming rule is `<surface>.<past-tense verb>`: an event names something that happened, not
something a user might do. Adding a type is additive within version 1 and requires a new
surface or a new verb under that rule. Renaming or removing a type is a new vocabulary version,
because a stored `event_type` is historical data that cannot be rewritten under the
immutability trigger.

The vocabulary is published in this repository under `taxonomy/events/v1` and vendored byte for
byte with a source record and a digest check, the same way [ADR 0007](0007-canonical-media-taxonomy.md)
publishes the media taxonomy, so every producer and every reader agrees on the closed set
without a shared runtime dependency between them.

## Consequences

Recommendation quality becomes measurable rather than asserted, because the fields an offline
evaluation needs are logged at the moment they exist. The behavioural record is immutable by
construction, which makes it evidence rather than mutable state. And erasure is specified
across every store before the first event is written, so the system never accumulates personal
data it has no procedure to remove.

The costs are real and accepted. Logging is on the request path, and although the writer never
raises, it is still work the request does. Consent enforced in two places can disagree, and the
disagreement is intentional: a row's snapshot says what was permitted at write time and the
grant table says what is permitted now. Hard-delete erasure inside a partitioned, trigger-
protected table is more mechanism than a soft flag, and it is the mechanism that makes the
deletion claim true. An impression row and its outcome events are separate records, so any
analysis joins them.

Deferred to their own decisions:

- **Database role separation** for the `activity` schema, as a second enforcement layer under
  the immutability trigger.
- **Retention periods** per table and per purpose, and the partition-drop schedule that
  implements them.
- **Model retraining policy after an erasure**, which the `activity.erasures` record makes
  answerable but does not answer.
- **Client-side event batching.** Every event in version 1 is written server side from
  `catalog-api`; a browser or client-originated batching path is a different trust boundary and
  needs its own record.
