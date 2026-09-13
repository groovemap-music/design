# ADR 0009: Native identity and provider aliases

- Status: Accepted

## Context

Every catalog entity GrooveMap stores is keyed by the identifier of the provider it came
from. In PostgreSQL the Discogs-sourced tables key artists, labels, masters, and releases on
`data_id`, the Discogs numeric identifier held as a string. `user_collections.release_id` is a
bare Discogs BIGINT, and the identity of an owned physical copy is the nullable Discogs
`instance_id` carried on that same row. In Neo4j, `Release.id` is the same Discogs identifier
stringified, and the uniqueness constraints are declared on it. MusicBrainz identifiers live
only in a separate `musicbrainz.*` family of tables keyed on `mbid`, carrying `discogs_*_id`
cross-reference columns and served by a dedicated API router; the two catalogs are joined by
convention at read time rather than by a shared key.

That shape has three consequences. A provider identifier is a foreign namespace: it changes
meaning when the provider merges, splits, or deletes a record, and GrooveMap cannot assert an
identity the provider has not assigned. An entity no provider knows — a pressing a user holds
that was never catalogued, or a user's own observation about a copy — has nowhere to live,
because there is no identifier to mint for it. And a second catalog can only be attached by
adding another cross-reference column, which is why MusicBrainz coverage is a parallel schema
rather than more evidence about one entity.

The gap is widest at the copy. What a user owns is a physical object with a condition, a
purchase history, a matrix inscription, and a location, and it is currently represented by a
nullable integer that Discogs assigns to a row in a user's Discogs collection. A user who has
never used Discogs cannot own anything at all, and a user who stops using Discogs loses the
identity of everything they own.

Without a recorded decision, `database-schema`, the two SQL loaders, and `catalog-api` would
each choose a key shape, a minting point, and an alias rule independently, and the provider
identifier would stay load-bearing in exactly the places that are hardest to change later.
The alias table described below, including its column set and its uniqueness rule, is this
organization's own design; the only external commitment is the key format.

## Decision

### Five native entities, each keyed by a UUID version 7

GrooveMap mints its own identifiers for five entities. Each is a UUID version 7 as specified
in RFC 9562: time-ordered, so index locality and insert ordering behave like a sequence
without a central allocator, and opaque, so it carries no provider meaning.

| Entity | What it identifies |
| --- | --- |
| `catalog_items` | A catalog entity of kind `release`, `master`, `artist`, or `label`. |
| `artifacts` | One specific edition of a release-kind item; user-creatable when no catalog match exists. |
| `owned_copies` | A physical copy a user holds, first class, replacing the bare Discogs `instance_id` as the identity of the copy. |
| `collection_snapshots` | A user's collection membership at an instant, content-hashed. |
| `observations` | User-captured evidence about an owned copy or artifact: kind, value, source, confidence, `observed_at`. |

Deployment pins PostgreSQL 18 and Python 3.14, so both sides generate the same format from a
standard facility: a `uuidv7()` column default in the database, and `uuid.uuid7()` in a
service. No application-side identifier library is introduced.

Making the owned copy first class is the substantive change in this list. A copy exists
because a user says it does, not because a provider listed it, and the observation record is
what lets a user assert a fact about their own copy — a matrix inscription, a grading, a
purchase price — without that fact having to be true of the edition in general.

### One alias table, and provider identifiers are never primary keys

Provider identifiers are demoted to evidence. A single `provider_aliases` table maps them to
native identifiers with these columns: `provider`, `external_id`, `entity_kind`, the native
id, `valid_from`, `valid_to`, `confidence`, `source`, and `asserted_at`. The `provider`
vocabulary is closed: `discogs`, `musicbrainz`, `wikidata`, `barcode`, `catalog_number`,
`isrc`, `matrix`. The `source` vocabulary is closed at `catalog`, `user`, and `inference`, so
an alias a person asserted and an alias a matching heuristic proposed are never confused.

Barcodes, catalogue numbers, ISRCs, and matrix inscriptions are providers in this table for
the same reason Discogs is: they are external namespaces that identify an entity without
belonging to GrooveMap. Treating them uniformly means a new identifier source is a row, not a
column.

Uniqueness is on `(provider, entity_kind, external_id)` for the currently valid row. That
constraint is what makes concurrent lookup-or-create idempotent: a writer resolves an alias by
selecting, inserting with `ON CONFLICT DO NOTHING`, and re-selecting, and two writers racing on
the same provider identifier converge on one native id instead of minting two. The validity
interval is what lets a provider's merge or split be recorded as a new row rather than an
in-place rewrite, so an identifier that was once correct stays auditable.

### Minting happens at ingest, through the shared runtime helper

The SQL loaders mint the native catalog item on every artist, label, master, release, and
release-group upsert, and write the native id into an additive nullable column on the
provider-keyed row. Both loaders are Python services consuming the `groovemap-runtime` package
released by `python-libraries`, so the lookup-or-create logic is one helper, `common.identity`,
rather than two implementations. The helper vendors the provider vocabulary byte for byte with
a digest check, following the pattern [ADR 0007](0007-canonical-media-taxonomy.md) established
for the media taxonomy; the vocabulary itself is published in this repository under
`taxonomy/identity/v1`.

The helper must offer a bulk resolve — one `SELECT` for the batch's provider identifiers, one
`INSERT ... ON CONFLICT DO NOTHING` for the misses, one re-select — and not only a per-row
call. `discogs-sql-loader` upserts up to a hundred rows per transaction through `executemany`
with `ON CONFLICT (data_id)`, while `musicbrainz-sql-loader` upserts one row per message with
`ON CONFLICT (mbid)`; a per-row alias lookup would turn one batched write into a hundred
round trips. Nothing in either loader's design guarantees a single instance, so the helper is
specified to be correct under an unspecified number of concurrent writers, which is what the
uniqueness rule above buys.

`catalog-api` mints owned copies, collection snapshots, and observations, because those
entities originate there. It resolves catalog items through the alias table and does not mint
them from provider identifiers, with one bounded exception: rows loaded before minting existed
are backfilled through the same helper, and that fallback path is removed once the backfill
completes.

### Expand only, inside persistence contract v1

This decision changes no existing column, key, constraint, or relationship. Native identifiers
arrive as additive nullable columns on the provider-keyed tables and as new tables; API
responses gain native identifiers as additional fields beside the provider identifiers they
already return. All of that is additive and therefore stays inside persistence contract v1 as
`database-schema` defines it; under [ADR 0001](0001-repository-ownership-boundary.md) that
repository owns runnable persistence initialization and schema compatibility, so the contract
decision is made in one place and consumed by pin everywhere else.

Contraction — making a native identifier the primary key, dropping a provider-keyed column,
or changing a relationship's semantics — is explicitly not decided here. It requires a new
major contract version and the expand, migrate, contract rollout that version implies, with
every consumer promoted in between. Deciding the expand half now and leaving the contract half
to its own record is what keeps this program from blocking on a simultaneous cutover across
every consumer.

### Graph projection

Neo4j nodes keep their provider `id` property and its constraints, and gain an additive
`gm_id` property with a range index. PostgreSQL's alias table remains the authority: the graph
holds a projection of identity, never the source of it.

The projection is a named maintenance job owned by `catalog-api`, which already holds both a
PostgreSQL session and a Neo4j session, and it runs after the loaders mint. The graph
enrichers do not do this work: they have no PostgreSQL access by design, and giving them
alias-table reads to populate `gm_id` would create exactly the cross-store coupling their
boundary exists to prevent.

The job's scope is that one property. It reads the alias table and sets `gm_id` on nodes that
already exist; it creates no node, writes no relationship, and changes no other property, so a
failed or lagging run leaves a stale property rather than a mutated graph.

## Consequences

Identity stops being borrowed. A copy, a snapshot, and an observation can exist for a user who
has no Discogs account, a second catalog becomes more aliases rather than a parallel schema,
and a provider's merge or deletion becomes an alias-validity change instead of a broken key.

The cost is a period of dual identity. Every row that matters carries both a provider
identifier and a native one, every read path has to resolve which it holds, and API responses
carry both until a future contraction decision removes the older field. The alias table is on
the ingest write path, so its uniqueness rule and its bulk resolve are performance-relevant,
not merely correctness-relevant; a per-row implementation would be a visible regression in
loader throughput.

Four things this record deliberately does not decide:

- **Contraction.** When and how provider-keyed columns stop being primary keys, and the
  contract version that carries it.
- **Recordings and works as native kinds.** The five entities cover what both catalogs
  currently deliver and what users currently assert. Recordings and works are a natural sixth
  and seventh, and adding a `kind` value is additive, but the modelling question of how they
  relate to artifacts is unresolved and is not settled by silence here.
- **Enricher-side minting.** The enrichers stay free of PostgreSQL under this decision. If
  graph-only entities ever need native identifiers minted where no relational row exists, that
  requires its own decision about which store is authoritative for them.
- **The `COLLECTED` edge shape.** `catalog-api` writes `COLLECTED {instance_id}` edges that
  `database-schema` never declared. Declaring that edge and bringing it under a named owner is
  a real gap, and an explicit non-goal of this program; it is a separate follow-on with its own
  record.
