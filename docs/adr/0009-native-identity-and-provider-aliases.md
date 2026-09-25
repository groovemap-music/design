# ADR 0009: Native identity and provider aliases

- Status: Accepted; amended 2026-09-25

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

## Amendments

### 2026-09-25: Superseded catalog items and native-id merge

This record defined how a native id is minted and how provider identifiers alias it, but not
what happens when two native catalog items turn out to be one.
[ADR 0014](0014-cross-catalog-edition-candidates.md) now produces that situation in two ways,
and in both the MusicBrainz side's native item is the one superseded:

- **Edition promotion** (ADR 0014 section 3): a reviewer accepts a candidate, and the
  MusicBrainz release's aliases move to the Discogs release's native id. It can be reverted.
- **Catalog re-attachment** (ADR 0014 section 8): a MusicBrainz release, release group,
  artist, or label loaded before its Discogs counterpart minted its own item, and the job moves
  its aliases to the Discogs item the catalog link names. A later catalog link that contradicts
  a promotion also moves the aliases, from one Discogs item to another.

Both leave the former native id with no alias pointing at it. Both refuse an item whose former
native id has a dependent in `artifacts`, `owned_copies`, `observations`, `user_collections`,
or `user_wantlists`, and leave it to this decision. The `catalog-api` re-attachment molecule
(`gm-catalog-api-sv35`) implements that guard now.

What references a native catalog item id today decides the rule, so it was inspected first.
Paths are relative to each sibling repository's root.

- **Catalog-keyed caches of the alias table.** Every provider-keyed entity table carries
  `gm_item_id` (`database-schema/src/groovemap_schema/postgres.py`, lines 4820-4830 for the
  Discogs tables, 1402-1415 for `musicbrainz.*`). So do `user_collections` and
  `user_wantlists` (lines 257 and 315), which `catalog-api`'s sync fills by resolving the row's
  Discogs release id through `provider_aliases` (`catalog-api/api/syncer.py`, `_alias_refs`
  line 246, and lines 352 and 387) and refreshes on every sync (lines 119 and 142). Neo4j's
  `gm_id` property is filled from current Discogs aliases only (`catalog-api/api/projection.py`,
  `_SELECT_PAGE`), and the PostgreSQL graph views read it through the same join
  (`postgres.py`, `_native_identity_join`, around line 1637).
- **Asserted references.** `artifacts.item_id` and `owned_copies.item_id` are foreign keys to
  `catalog_items` (`postgres.py`, lines 351-390). The sync sets an owned copy's item from its
  collection row (`syncer.py`, lines 167-172), but a copy with no collection row, and every
  artifact, has no alias behind its item: the reference is the fact. No writer creates
  artifacts yet.
- **Transitive references.** `observations` point at an owned copy or an artifact, never at a
  catalog item (`postgres.py`, lines 412-427; `catalog-api/api/routers/observations.py`), and
  `collection_snapshots.copy_ids` lists owned copies (line 392).
- **Immutable history.** `activity.impressions.item_id` (`postgres.py`, around line 999) and the
  `item_id` in event payloads (`syncer.py`, lines 403 and 730; `catalog-api/api/routers/activity.py`,
  line 81) record native ids under [ADR 0010](0010-first-party-events-consent-and-deletion.md)'s
  immutability trigger.
- **Public emitters.** Search (`catalog-api/api/queries/search_queries.py`, line 561),
  recommendations (`catalog-api/api/routers/recommend.py`, lines 136-141 and 216-232), the
  user's collection and wantlist (`catalog-api/api/routers/user.py`, lines 81-83;
  `catalog-api/api/queries/user_queries.py`, lines 44-49), gaps
  (`catalog-api/api/queries/gap_queries.py`, lines 33-35), fit (`catalog-api/api/routers/fit.py`,
  lines 145-152), and lookup (`catalog-api/api/routers/lookup.py`, line 329) all emit `gm_id`,
  and all resolve it from a current alias at request time. The one public input that takes a
  native catalog id is the outcome endpoint `POST /api/activity/events`
  (`catalog-api/api/routers/activity.py`, lines 47-85). `graph-explorer` echoes a stored
  `gm_id` into it (`explore/static/js/api-client.js`, line 625; `search.js`, line 767), and so
  does `mcp-server`'s outcome tool (`mcp_server/tool_routing.py`, lines 327-359). The
  similar-artist response, `gm_id` included, is cached in Redis and replayed into new
  impressions (`recommend.py`, lines 108-149).
- **Erasure.** The erasure procedure hard-deletes every user-owned table
  (`catalog-api/api/routers/activity.py`, `_USER_OWNED_DELETES`, lines 294-302), while
  `admin_audit_log` survives it by design (`postgres.py`, line 555).
- **Not affected.** `python-libraries/src/common/identity.py` resolves and attaches through
  current alias rows only (`resolve_aliases` line 256, `attach_aliases` line 325), so it follows
  a moved alias without change. `analytics-engine` stores no native catalog id of its own; it
  reads `activity.impressions.item_id` directly (`insights/activity.py`, line 67).

One consequence follows from those facts. A collection or wantlist row reaches a catalog item
only through its Discogs release id, and in both causes the Discogs item is the survivor. So
today the guard can only be tripped by an owned copy or an artifact created directly against a
MusicBrainz-side item, and no such writer exists yet. Most guarded skips should therefore be
rare now. The rule below is still needed, because the writers ADR 0009 planned for — copies a
user creates without Discogs, and user-created artifacts — will make those references
ordinary.

#### 1. Representation: a supersession record; the superseded item is kept, never deleted

A superseded catalog item keeps its `catalog_items` row, its kind, and its id. A new table,
`catalog_item_supersessions`, records that it now resolves to another item. It has these
columns: `id` (UUID version 7), `superseded_id` and `survivor_id` (both foreign keys to
`catalog_items`), `cause`, `decision_ref`, `valid_from`, `valid_to`, and `via_id`. The `cause`
vocabulary is closed at `edition_promotion` and `catalog_reattachment`. `decision_ref` names
what authorized the row: the `matching` decision row for a promotion, or the
`admin_audit_log` entry for a re-attachment run. Like `provider_aliases`, the table has a
partial unique index on `superseded_id WHERE valid_to IS NULL`, so an item has at most one
current survivor, and history is recorded by closing rows rather than rewriting them. The
writer enforces that both items have the same kind and that the two ids differ.

Resolution is always one hop. A current survivor is never itself currently superseded: when an
item B that survives A is superseded into C, the same transaction closes A → B and opens A → C
with `via_id` naming the B → C row. The resolved id of any native id is the `survivor_id` of
its current row, or the id itself when there is none, which is one index probe. `database-schema`
publishes that resolution once, as a view or function, so readers do not each rewrite it.

Lookups by provider identifier need no change. The ADR 0014 transactions move the aliases, so
`catalog-api/api/identity.py` (`_SELECT_NATIVE_IDS`) and
`catalog-api/api/queries/lookup_queries.py` already answer with the survivor, and
`releases_for_native_id` follows the rewritten `gm_item_id` columns. The Neo4j projection
reads current Discogs aliases, which never point at a superseded item, so it never projects
one. In the PostgreSQL property graph ([ADR 0012](0012-postgresql-property-graph-migration.md)),
the `graph.catalog_item` view (`postgres.py`, around line 1973) excludes currently superseded
items. That way the `catalog_item` vertex and the `owns` edge never expose a tombstone as a
live entity.

Reversal closes the supersession row, sets its `valid_to`, and runs inside the revert
transaction ADR 0014 section 3 already defines. It moves back the rows the merge moved (see
section 2), recomputes the caches, and re-opens the rows the merge closed by chain compression:
it closes every open row whose `via_id` is the reverted row and re-opens its predecessor. A
merge whose survivor has since been superseded again is reverted after the later merge, in
reverse order. The former id then resolves to itself again.

Rejected alternatives:

- **Hard merge: rewrite every reference and delete the superseded `catalog_items` row.** A
  promotion could not be reverted exactly, and immutable activity rows cannot be rewritten. A
  deleted id would then leave those rows holding an identifier nothing resolves.
- **Leave it orphaned (the status quo).** Guarded items would stay split forever. The barcode
  or catalogue-number alias a MusicBrainz-first item won would stay on the wrong item. And an id
  already written to an impression would resolve to an item that no alias, catalog row, or
  response names.
- **A `superseded_by` column on `catalog_items`.** An in-place value keeps no history of a
  promotion and its reversal. This record chose validity intervals for aliases so that an
  identity decision stays auditable, and the same argument applies here.
- **A `provider_aliases` row mapping the old native id to the survivor.** The provider vocabulary
  is closed and names external namespaces. A native id is not one, and every alias read, which
  does not filter on source, would start serving it as a provider identifier.

#### 2. Dependents move to the survivor in the same transaction, and user-owned rows are only re-pointed

Each class of reference found above is handled once:

- **Caches of the alias table** (`gm_item_id` on the entity tables, `user_collections`, and
  `user_wantlists`) are recomputed from the moved aliases inside the merge transaction, and
  recomputed again on reversal. They are not ledgered, because the alias table can always
  reproduce them. The next sync would converge on the same value anyway.
- **Asserted references** (`artifacts.item_id`, `owned_copies.item_id`) that point at the
  superseded id are re-pointed to the survivor. Each re-pointed row is written to a ledger,
  `catalog_item_moves`: the supersession id, the table (closed at `artifacts` and
  `owned_copies`), the row id, the owning `user_id` (for an artifact, its `created_by`), and
  the time. Reversal moves back exactly the ledgered rows that still point at the survivor. A
  row created against the survivor after the merge is never moved back.
- **Transitive references** (`observations`, `collection_snapshots.copy_ids`) are not touched.
  Owned copies and artifacts keep their ids, so an observation still names its copy, and a
  snapshot's content hash stays true.
- **Immutable history** (`activity.impressions`, `activity.events`) is never rewritten. Section
  4 says how it is read.

No uniqueness rule can make a move fail. `artifacts` and `owned_copies` have no uniqueness on
the item, and the collection and wantlist constraints are on provider ids, not on
`gm_item_id` (`postgres.py`, lines 241 and 302). Two copies ending on one item is correct,
because the user owns two copies. Two artifacts ending on one item stay two artifacts:
merging artifacts is not decided here.

The service is `catalog-api` (section 3), and the transaction is the one that moves the
aliases. It locks both `catalog_items` rows first, so a concurrent merge or revert of either
item serializes behind it.

User-owned data is protected under ADR 0010 as follows:

- A merge never deletes, merges, or de-duplicates a user-owned row. It changes no
  user-authored value: condition, rating, notes, `acquired_at`, and observation values stay as
  they are. It never changes a row's `user_id` or id. The only column it writes on a user-owned
  row is the catalog-item reference.
- A merge emits no event on a user's behalf. `collection.item_updated` names something the user
  did, and a catalog repair is not that. Writing it would put a fact into the behavioural record
  that did not happen, carrying a consent snapshot the user never exercised.
- A merge needs no consent purpose. The two purposes gate product analytics and model training.
  Keeping stored data pointed at the right catalog item is neither.
- The ledger is personal data keyed to a user, so it joins the erasure closure. The erasure
  procedure deletes a user's `catalog_item_moves` rows with the other user-owned tables, and
  export includes them. The audit entries a merge writes to `admin_audit_log` carry per-table
  counts and never a user id or a user-owned row id, because that table outlives erasure by
  ADR 0010's design.

Rejected alternatives:

- **Leave dependents on the superseded id and resolve every read.** Every reader of
  `owned_copies` and `artifacts` would have to resolve, and the property graph's `owns` edge
  would point at a tombstone. Read-time resolution is kept only for history that cannot move.
- **Ask each affected user to confirm the move.** The user did not assert which catalog item
  describes their copy; the catalog or a reviewer did. Nothing the user wrote changes, and
  gating a catalog repair on every owner's response would leave the item split indefinitely.
- **A `previous_item_id` column on each dependent row instead of a ledger.** One column cannot
  hold a chain of merges or tell a second merge's rows from the first's. It would also widen
  two user-owned tables to record a catalog event.
- **Ledger the caches too.** They are derivable from the alias table, so recording them adds
  personal data to erase and nothing to restore.

#### 3. Executor: `catalog-api`, as further steps of the ADR 0014 transactions; the guard is removed

The merge is not a separate job. It is four steps appended to each transaction ADR 0014
already assigns to `catalog-api`: the section 3 promotion and revert, the section 8
re-attachment, and the section 8 contradiction revert. After ADR 0014's three alias steps,
the transaction does the following:

4. Locks both catalog items.
5. Opens the supersession row and compresses chains, or closes it on revert.
6. Re-points and ledgers the asserted references, or moves them back.
7. Recomputes the caches.

In a contradiction revert, the former MusicBrainz item's supersession into the first Discogs
item is closed, and a new one into the second Discogs item is opened. The ledgered rows move
with it.

ADR 0014's dependents guard is removed in the same `catalog-api` change that adds these steps,
and not before. Until that change ships, the guard stays, so no item is ever re-attached
without its dependents. Removing the guard also releases the section 8 items it skipped. A skip
writes nothing, so a skipped item still matches the job's population predicate, which selects
a MusicBrainz alias that resolves to a native id other than its Discogs alias's. The first
re-attachment run after the change therefore processes every item earlier runs skipped. No
separate release list is needed. The operator compares that run's merged-with-dependents count
against the skip reports of earlier runs. The read-only census should report, for each split
item, the dependents a merge would move. For promotions, the review action shows the reviewer
how many dependents accepting will move, and records the count on the decision row.

Rejected alternatives:

- **A separate merge job that runs after the alias move.** Between the two transactions, the
  aliases would name the survivor while copies and artifacts still pointed at an item no alias
  names. A failure between them would leave exactly the state the guard exists to prevent.
- **A trigger in `database-schema` on `provider_aliases`.** That repository owns DDL, not
  behaviour, and ADR 0013 and ADR 0014 rejected placing jobs there. A trigger also cannot tell
  a merge from a provider split, which closes and opens aliases in the same way.
- **The loaders.** Rejected for ADR 0014 section 8's ADR 0005 reasons.
- **Keep the guard, and route guarded items to a manual operator queue.** A catalog link needs
  no judgement, and the dependents need none either once their move is exact and reversible.

#### 4. Public contract: old ids keep resolving, and history is read through the resolution

- **No response newly emits a superseded id from PostgreSQL.** Every emitter listed above
  resolves `gm_id` from a current alias, and aliases move before the merge commits. A cached
  payload, such as the similar-artist cache, can still carry one until it expires. That is
  accepted without a cache sweep, because every input path accepts a superseded id.
- **An endpoint that addresses a catalog item by native id accepts a superseded id and answers
  as the survivor.** It returns `200` with the survivor's representation, whose `gm_id` is the
  survivor's, and an additive field naming the id that was requested and resolved. An unknown
  id is `404` as today. A reverted supersession resolves to the id itself again. No endpoint
  addressed this way exists today; this is the rule any new one follows.
- **The outcome endpoint records `item_id` verbatim.** An outcome has to carry the id its
  impression recorded, which may predate the merge or come from a cached payload. It is
  therefore validated as a UUID and never rejected or rewritten for being superseded.
  `graph-explorer` and `mcp-server` need no change.
- **Readers of activity history resolve at read time.** Offline evaluation and training join
  `item_id` through the resolution in section 1 as of the analysis, and apply ADR 0010's
  consent re-check unchanged. A merge writes no activity row, never sets `groovemap.erasure`,
  adds no event type to `taxonomy/events/v1`, and leaves every consent snapshot as written.
  Export returns item ids as recorded.

All of this is additive: two new tables, a resolution, a filtered view, and an optional
response field. It stays inside persistence contract v1 and inside `catalog-api`'s current API
contract.

Rejected alternatives:

- **HTTP `301` or `308` to the survivor.** Both declare the move permanent, and a promotion can
  be reverted. Clients and intermediaries would keep a redirect that a revert has made false.
- **`404` or `410` for a superseded id.** A client holding an id from a recent response, or an
  outcome for an impression already shown, would fail because of an identity change it cannot
  act on.
- **Rewrite activity rows to the survivor.** The immutability trigger exists to prevent it, and
  the rewritten row would misstate what was shown.

#### 5. Scope: every catalog kind, both causes, catalog items only

The rule applies to all four catalog kinds (`release`, `master`, `artist`, and `label`) and to
both causes. Section 8 splits all four kinds. Artist and label ids reach impressions through
search and recommendations even though no user-owned table references them. A merge joins two
items of the same kind only.

It applies to `catalog_items` only. Artifacts, owned copies, snapshots, and observations are
identities a user originates, and joining two of them is not a catalog decision. No user
action supersedes a catalog item.

The `cause` vocabulary is closed at the two ADR 0014 causes. Another cause, such as acting on a
provider's own upstream merge, joins by amendment to this record. The same applies to artist
and label promotions, which ADR 0014 section 7 leaves to an amendment. When they arrive, they
use this rule, and its exact reversal is what makes a wrong namesake merge recoverable.

Rejected alternatives:

- **Releases only.** Section 8 splits release groups, artists, and labels too. Their former ids
  are already in impressions, and they would resolve to nothing.
- **Re-attachments only, keeping the guard for promotions.** Reviewers would then be pushed to
  reject correct candidates exactly for the releases people own, which are the ones worth
  getting right. The ledger makes reversing a promotion exact, so the guard protects nothing
  that reversal does not.
- **One merge mechanism for all five native entities.** Merging two users' copies, or two
  user-created artifacts, is a question about user assertions, with its own consent and
  ownership rules, and it is not settled here.

#### Consequences of this amendment

ADR 0014's orphaned-native-id friction is resolved. A superseded id stays resolvable, and
whatever a user owns follows the catalog to the surviving item without a user-authored value
changing. The costs accepted are two small tables, one more closure in the erasure procedure,
and a resolution step for anyone reading activity history. No new record is needed: the rule
completes this record's identity model and changes no decision in it.

Implementation work implied, as planning inputs. None is filed by this amendment:

- **`database-schema`**: `catalog_item_supersessions` and `catalog_item_moves` with their
  indexes, the published resolution, the `graph.catalog_item` filter, and read access to the
  resolution for the role `analytics-engine` uses to read `activity`.
- **`catalog-api`**: merge steps 4-7 in the section 8 re-attachment, replacing the dependents
  guard, coordinated with `gm-catalog-api-sv35`; the same steps in the section 3 promote and
  revert actions when those are built; dependents counts in the census and the review action;
  the erasure and export extensions for `catalog_item_moves`; and the resolution rule on any
  endpoint addressed by native id.
- **`analytics-engine`**: resolving `item_id` through the resolution in offline evaluation.
- **`deployment`**: an erasure smoke assertion that a user's ledger rows are removed.

`python-libraries`, `graph-explorer`, `mcp-server`, the loaders, and the graph enrichers need
no change.
