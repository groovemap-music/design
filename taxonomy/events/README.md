# First-party event vocabulary

[`v1/event-types.json`](v1/event-types.json) is the closed version 1 event-type vocabulary that [ADR 0010](../../docs/adr/0010-first-party-events-consent-and-deletion.md) makes authoritative for every producer and every reader of the `activity` schema. It names the six surfaces, the sixteen event types those surfaces emit, the two consent purposes an envelope can snapshot, and the payload schema each type carries as an inline `$defs` entry.

Three schemas accompany it:

- [`v1/event-types.schema.json`](v1/event-types.schema.json) validates the vocabulary document itself.
- [`v1/event-envelope.schema.json`](v1/event-envelope.schema.json) validates the typed envelope every row of `activity.events` carries.
- [`v1/impression.schema.json`](v1/impression.schema.json) validates the row of `activity.impressions` that records a ranked item as it was shown.

[`v1/fixtures/`](v1/fixtures/event-search-query.json) holds the conformance suite: one valid example per event type, valid examples of both envelopes, and the rejections the contract must produce. Each file holds a name, the envelope it exercises, whether it is valid, and the document itself; an invalid file also names the rejection it proves. `just events` validates all three schemas as JSON Schema 2020-12 documents, validates the vocabulary, proves every valid document against its envelope and every payload against the schema its event type names, and proves that every invalid document is rejected.

## Naming rule

Event ids are lowercase `<surface>.<past-tense verb>`: an event names something that happened, not something a user might do. The verb's final word is a regular past tense ending in `ed` or one of the irregular forms the vocabulary declares (`shown`, `hidden`). Two version 1 types, `search.query` and `search.result_impression`, name the record rather than the act; they are carried forward verbatim from ADR 0010, the vocabulary declares them as a closed pair, and the check gate rejects any new type that is not a past-tense verb.

Adding a type is additive within version 1 and requires a new surface or a new verb under that rule. Renaming or removing a type is a new vocabulary version, because a stored `event_type` is historical data that the immutability trigger will not let anyone rewrite.

## Envelope rules

- Every column ADR 0010 names is present on the wire. A column whose value is unknown at write time is an explicit `null`, so a row never omits a field it simply lacks a value for.
- `occurred_at` and `recorded_at` are separate, which is what keeps a late or replayed write honest. `idempotency_key` is unique together with `occurred_at`, which is what makes a retried write safe inside a partitioned table.
- `consent_purposes` is the snapshot of the purposes active at the moment of the write. It is required and may be empty. An empty array records that no purpose was active, which is not the same as the field being absent, and the check gate proves that an envelope missing the field is rejected.
- Events reference `subject_id`, never a user id. The link between the two lives in `activity.user_subjects` and is one row to remove.
- An impression carries `policy_id`, `candidate_set_id`, `position`, and `propensity` because none of the four can be recovered after the request returns. Positions are one-based. Outcomes are not columns on the impression: opened, saved, dismissed, and hidden are events whose payload carries the `impression_id`, which keeps the impression row immutable and lets one impression carry several outcomes.

## Vendoring rule

The vocabulary is vendored verbatim, byte for byte, into every repository that writes or reads first-party events, beginning with `python-libraries`, `catalog-api`, and `analytics-engine`. A vendored copy sits beside a source record naming the design commit and the SHA-256 of this file, and each repository's check gate fails when the copy's digest differs from that record. Compute the digest from the exact bytes of the file:

```console
shasum -a 256 taxonomy/events/v1/event-types.json
```

`just publication-readiness` prints the same digest as `event_types_sha256` next to the catalog, media, and identity digests, so consumers can pin a reviewed commit and its vocabularies together.

## Current promotion record

The canonical v1 bytes have SHA-256
`f64f03164c208477e8ae9c6bc547bba7342f23df96f6b10f21f7fa6f1d21ba74`.
No consumer has vendored the vocabulary yet; the first source records are written in wave 1
of the [native identity and first-party events program](../../docs/programs/native-identity-and-events.md).
Consumer source records are promotion provenance; each consumer remains responsible for
reviewing and validating its vendored copy.

## Changing the vocabulary

Add the surface or the type in `event-types.json`, add its payload schema under `$defs`, add the matching envelope enumeration, add a valid fixture for the new type, and run `just check`. The fixtures are synthetic and carry no real subject, session, or catalog identifier.
