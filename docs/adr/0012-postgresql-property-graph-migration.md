# ADR 0012: PostgreSQL SQL/PGQ as the catalog graph engine

- Status: Accepted; amended 2026-09-25

## Context

GrooveMap runs two stores. PostgreSQL holds the catalog entities, the native identity tables
[ADR 0009](0009-native-identity-and-provider-aliases.md) created, the first-party activity
tables [ADR 0010](0010-first-party-events-consent-and-deletion.md) created, and the two blocks
[ADR 0011](0011-catalog-identifiers-and-manufacturing-credits.md) attached to every Discogs
release. Neo4j holds every edge between those entities and nothing else.

No record explains why. The graph store predates this decision log: it was chosen before ADR
0001 and has been extended by four later records — the media projections in
[ADR 0007](0007-canonical-media-taxonomy.md), the `gm_id` property in ADR 0009, the deletion
closure in ADR 0010, and the company credits in ADR 0011 — each of which added nodes and edges
to a store nothing had ever justified keeping. The absence is the first fact this record has to
settle, because a migration cannot argue against a rationale that was never written down.

The second fact is that the split is not free. Every graph write is a second connection, a
second transaction boundary, and a second failure mode on top of the relational write that
produced the same data. `discogs-graph-enricher` and `musicbrainz-graph-enricher` exist only to
re-derive, from the same catalog events the SQL loaders already consume, edges whose entire
content is already present inside the JSONB documents PostgreSQL holds: `artists[]`, `labels[]`,
`master_id`, `genres[]`, `styles[]`, `members[]`, `groups[]`, `aliases[]`, `parentLabel`,
`sublabels[]`, `extraartists[]`, `companies[]`, and `media`. `catalog-api` writes collection and
wantlist edges into the graph that duplicate rows already in `user_collections` and
`user_wantlists`, and runs a projection job whose only purpose is to copy one identity property
across the store boundary because the alias table cannot be joined from Cypher. The cost of the
boundary is paid in operations as well as code: the release-rarity pipeline failed on a 600
second Neo4j timeout for thirty-three consecutive days before anyone was paged, because a
failure in the second store does not surface through the first store's health.

The third fact is that PostgreSQL 19 removes the reason for the boundary. `CREATE PROPERTY
GRAPH`, `ALTER PROPERTY GRAPH`, and `DROP PROPERTY GRAPH` implement the SQL/PGQ part of the SQL
standard, ISO/IEC 9075-16, and `GRAPH_TABLE` makes a property-graph pattern a relation inside an
ordinary query. A property graph is a catalog object declared over existing tables, views, or
foreign tables. Nothing is copied and nothing is materialized; the documentation compares it to
`CREATE VIEW`, and the executor rewrites a pattern into relational joins. Vertex and edge tables
carry a key that defaults to the primary key, and an edge table names its endpoints with
`SOURCE KEY (...) REFERENCES` and `DESTINATION KEY (...) REFERENCES`, which resolve against a
declared key on the vertex table rather than requiring a table-level foreign key. That last
detail is what makes the feature reachable here: GrooveMap's graph data lives in JSONB arrays
and in a polymorphic `musicbrainz.relationships` table that deliberately carries no foreign
keys, so any approach that demanded real referential constraints would have demanded a data
migration before the first query could be written. See
<https://www.postgresql.org/docs/19/ddl-property-graphs.html> and
<https://www.postgresql.org/docs/19/queries-graph.html>.

The fourth fact is the limit. `GRAPH_TABLE` supports fixed-length path patterns, label
disjunction, edge direction, a `WHERE` clause per pattern element, and a `COLUMNS` list that
projects the match into the surrounding query. It has no quantifiers, no variable-length path
patterns, and no shortest-path construct. The Cypher inventory in `catalog-api` is 25 query
modules and roughly 6,500 lines, and all but two query functions are fixed one-hop or two-hop
patterns that map onto that subset directly. The two exceptions are `find_shortest_path`, a
`shortestPath` bounded at depth 10 that surfaces as `GET /api/path`, as the `find_path`
natural-language intent, and as the `find_path` MCP tool, and `get_explore_traversal`, which
walks `*1..n`. Neither has a SQL/PGQ spelling. Both have a plausible relational spelling as a
recursive common table expression with a depth cap and cycle detection over an edge relation,
which is the standard PostgreSQL idiom and is unrelated to SQL/PGQ, but whether it holds inside
the existing request budgets at GrooveMap's edge counts is unmeasured.

The fifth fact is that the relational side is not ready to be declared over. There are no edge
tables. Every Discogs edge is implied by an array inside a document, every MusicBrainz
relationship sits in one polymorphic table keyed by entity-type pairs, and collection and
wantlist rows are keyed by the provider release id rather than by anything a vertex table would
call a key. A property graph can be declared over views that unnest and reshape all of that, and
those views are plain SQL that runs on PostgreSQL 18 today, but whether a view-backed graph
performs at tens of millions of edges or whether materialized edge tables are required is
exactly the question a declaration cannot answer on its own.

PostgreSQL 19 is not generally available at the time of this record. The production engine is
PostgreSQL 18, digest-pinned in `database-schema/scripts/test-integration.sh` and in the
deployment compose file. A decision that required the new engine to be present would be a
decision that could not be implemented for months.

## Decision

### PostgreSQL SQL/PGQ becomes the catalog graph engine, and Neo4j is retired

GrooveMap moves its entire graph into PostgreSQL. The target is a single `CREATE PROPERTY GRAPH`
catalog object over relations in a dedicated `graph` schema, queried through `GRAPH_TABLE` from
the same connection and the same transaction as every other catalog read. Neo4j is decommissioned
once the read path, the write path, and the operational surfaces no longer need it.

The argument is the one the context makes: the second store holds no fact the first store does
not already hold, and the standard now describes the traversal grammar that was the only reason
to keep it. Removing the boundary removes two enricher services, a cross-store projection job, a
dual-write path in the API, and a class of failure in which one store is broken while the other
reports healthy.

### Neo4j stays authoritative until the spike returns GO and read parity is demonstrated

Nothing in this record permits a cutover. Neo4j remains the authoritative edge store, and every
production read continues to be served from it, until two gates are passed in order.

The first gate is a feasibility spike that measures the fixed-length read families against three
shapes — views over the existing JSONB, materialized edge relations, and the current Neo4j
implementation — and that settles the variable-length question by prototyping `/api/path` and the
explore traversal as recursive common table expressions with explicit depth caps. The spike also
produces the Cypher coverage matrix that maps every query function to its `GRAPH_TABLE` spelling
or to the reason it has none, and the target relational edge model. A GO verdict is the
precondition for filing any work beyond the foundation.

The second gate is per-family read parity. A query family moves to PostgreSQL when a parity
harness proves the PostgreSQL implementation returns what the Cypher implementation returns on
the same fixtures, and when it meets a stated performance budget. Families cross one at a time.
A family that fails parity stays on Neo4j and does not block the others.

If the spike returns NO-GO, this record's decision does not survive it: the graph stays in Neo4j,
the declared property graph remains an unreferenced catalog object behind its gate, and the
program is closed with an amendment to this record rather than left open.

### The rollout is version-gated and opt-in

The `graph` schema, its vertex and edge relations, and everything else the foundation builds are
plain SQL that runs on PostgreSQL 18. Only the `CREATE PROPERTY GRAPH` statement itself is
version-specific. The schema initializer applies that statement only when two conditions hold
together: `server_version_num` reports 190000 or higher, and an explicit environment switch is
on. On PostgreSQL 18 the statement is skipped, and a production database that is never switched
on is untouched by every part of this program except the additive relations.

`CREATE PROPERTY GRAPH` has no `IF NOT EXISTS` clause in its synopsis, so idempotence is achieved
with a catalog existence check before the statement runs. The initializer's applied-twice proof
must hold on both engines: on PostgreSQL 18 because the statement never runs, and on PostgreSQL
19 because the second run finds the object and does nothing.

The deployment change that moves the pinned image to PostgreSQL 19 is prepared now and held. It
is released against a generally available PostgreSQL 19 image and not against a beta, and a
major-version upgrade runbook covering the existing compose volume is a precondition for it.

### The label mapping is the contract

Neo4j relationship types and node labels do not carry over unchanged. Three of the relationship
types are SQL reserved words, one Neo4j type covers two distinct relationships, and one Neo4j
label collides with a reserved word. Every PGQ label is written in lower snake case, so no
pattern in any `GRAPH_TABLE` query ever needs a quoted identifier.

Vertex labels:

| Neo4j node label | PGQ vertex label | Note |
| --- | --- | --- |
| `Artist` | `artist` | |
| `Label` | `label` | |
| `Master` | `master` | |
| `Release` | `release` | |
| `Genre` | `genre` | |
| `Style` | `style` | |
| `Medium` | `medium` | ADR 0007 |
| `MediaFamily` | `media_family` | ADR 0007 |
| `User` | `app_user` | `user` is reserved in PostgreSQL; this is the only vertex rename |
| `Person` | `person` | |
| `Company` | `company` | ADR 0011 |

Edge labels:

| Neo4j relationship type | PGQ edge label | Properties |
| --- | --- | --- |
| `BY` | `by_artist` | `by` is reserved |
| `ON` | `on_label` | `on` is reserved |
| `IS` | `in_genre`, `in_style` | `is` is reserved; one Neo4j type, split by endpoint |
| `DERIVED_FROM` | `derived_from` | |
| `MEMBER_OF` | `member_of` | Discogs artist-to-group membership |
| `ALIAS_OF` | `alias_of` | |
| `SUBLABEL_OF` | `sublabel_of` | |
| `PART_OF` | `part_of` | |
| `IN_FAMILY` | `in_family` | ADR 0007 |
| `ISSUED_ON` | `issued_on` | `qty`, `source`; ADR 0007 |
| `CREDITED_TO` | `credited_to` | `role`, `role_category`, `source`; ADR 0011 |
| `CREDITED_ON` | `credited_on` | `role`, `category` |
| `SAME_AS` | `same_as` | |
| `COLLECTED` | `collected` | `instance_id` |
| `WANTS` | `wants` | |
| eight MusicBrainz artist-artist types | `mb_related` | `relationship_type` carries the original type |

The eight MusicBrainz artist-to-artist relationship types — `MEMBER_OF`, `COLLABORATED_WITH`,
`TAUGHT`, `TRIBUTE_TO`, `FOUNDED`, `SUPPORTED`, `SUBGROUP_OF`, and `RENAMED_TO` — become one
`mb_related` edge label carrying the original type as a `relationship_type` property. They share
one endpoint pair and one property list, a single label is what lets a query ask for any
MusicBrainz artist relation without enumerating eight, and folding them also resolves the
collision between MusicBrainz `MEMBER_OF` and the Discogs membership edge of the same name, which
are different assertions from different catalogs. A query that wants one type filters on the
property.

The mapping is published in the schema documentation and is the contract `catalog-api` rewrites
against. Adding a label is additive; renaming one is a breaking change to every rewritten query
family. The `ExtractionCompletion` bookkeeping nodes are not projected: they record extraction
state, not catalog structure, and the relational store already tracks extraction history.

### The relational tables are not reshaped to suit the graph

The foundation declares the property graph over views in a new `graph` schema that unnest the
JSONB arrays, split `musicbrainz.relationships` by endpoint-type pair, and cast collection and
wantlist rows to the release key. No existing table changes, and no foreign key is added to
support an edge declaration, because `SOURCE KEY ... REFERENCES` resolves against a declared key
rather than a constraint. Whether those views are replaced by materialized edge tables written by
`discogs-sql-loader` and `musicbrainz-sql-loader` is the spike's decision, not this record's.

The persistence contract stays at `groovemap.persistence` v1 for the whole preparatory program.
A new schema, new views, and a conditional catalog object are additive. The contract records the
property graph as conditional on server version so a consumer can tell whether it is present.

## Consequences

`catalog-api` gains a graph-backend seam — one setting selecting Neo4j or PostgreSQL, defaulting
to Neo4j — where today every query function takes the Neo4j driver directly. That seam is the
single largest piece of preparatory work in the program and the thing that makes a per-family
migration possible instead of a single irreversible switch. One pilot family, the multi-hop
collaborator queries, is rewritten as `GRAPH_TABLE` behind it with a parity test, which is how
the seam is proved before 25 modules are rewritten through it.

The graph projections the earlier records created carry forward rather than being re-decided.
ADR 0007's `medium`, `media_family`, `in_family`, and `issued_on`; ADR 0009's `gm_id` property;
ADR 0011's `company` and `credited_to` — each becomes a PGQ label or property under the mapping
above, with the same meaning and the same source. None of those records is amended: they decided
what the graph asserts, and this record decides only which engine holds it. ADR 0009's `gm_id`
projection job becomes unnecessary once the graph is declared over the same database as the alias
table, because the property it copies becomes a column a view can select.

Ten repositories are affected before the program closes:

- **`database-schema`** owns the `graph` schema, the vertex and edge relations, the gated
  property-graph statement, and the label mapping documentation. It is the only repository that
  issues DDL.
- **`catalog-api`** owns the backend seam, the per-family `GRAPH_TABLE` rewrites, the recursive
  common table expressions that replace the two variable-length workloads, the parity harness,
  and eventually the removal of the Cypher modules and the `gm_id` projection job.
- **`discogs-sql-loader`** and **`musicbrainz-sql-loader`** write the edge relations if the spike
  chooses materialized edges over views, from the same catalog events the graph enrichers consume
  today.
- **`discogs-graph-enricher`** and **`musicbrainz-graph-enricher`** are retired. Once the SQL
  loaders are the single consumer of the catalog events, these services have no remaining
  responsibility.
- **`deployment`** carries the PostgreSQL 19 image pin, the major-version upgrade runbook, and
  finally the removal of the Neo4j service and its volume.
- **`operations-console`** loses the Neo4j health check and its graph-store views.
- **`python-libraries`** loses the shared Neo4j helper and the driver extra from
  `groovemap-runtime`.
- **`operations-toolkit`** loses the Neo4j operational entry points.

The persistence contract takes a major bump to v2 at decommission and not before. Removing the
Neo4j indexes, constraints, and the graph-store section of the contract is a removal, and ADR
0005's rule is that removals are major. Everything earlier in the program is additive and stays
in v1, which means every consumer promotes contract revisions normally until the last phase and
then promotes one breaking revision deliberately.

Two costs are accepted rather than mitigated. The first is a dual-write period: while both stores
hold edges, a write goes to both, and the two can disagree. The parity harness is what detects
that, and the window is bounded by the phase order rather than left open. The second is that
`GRAPH_TABLE` is new. GrooveMap will be an early production user of a feature whose planner
behaviour at this data scale nobody has published, which is the reason the program leads with a
measurement spike instead of a rewrite.

Deferred to their own records:

- **The variable-length path strategy.** Recursive common table expressions with depth caps and
  cycle detection are the candidate for `/api/path` and the explore traversal. The depth cap, the
  edge relation they read, and whether the existing request budgets survive are spike outputs,
  and the spike's decision is recorded where it is made.
- **The target relational edge model.** Table shapes, keys, indexes, and which loader owns each
  relation are settled by the spike. This record commits only to the label mapping those relations
  must expose.
- **Graph analytics.** Nothing in GrooveMap uses Neo4j's graph data science procedures today, and
  no equivalent is planned. If a centrality or community-detection workload is ever wanted, it
  needs its own decision about where it runs.
- **The single `apoc.meta.stats()` call.** One administrative display reads Neo4j's own metadata
  procedures. Its replacement is a catalog query against the `graph` schema, and what the
  administrative surface should show is a `catalog-api` decision rather than an engine one.

## Amendments

### 2026-09-25: MusicBrainz graph crossings resolve through native ids

[ADR 0014](0014-cross-catalog-edition-candidates.md) left one question to this record. Its
section 2 keeps a promoted edition out of the graph until "the graph's MusicBrainz views resolve
releases through native ids rather than through `discogs_release_id`", and its follow-up asks
whether they should. [ADR 0009's 2026-09-25 amendment](0009-native-identity-and-provider-aliases.md#2026-09-25-superseded-catalog-items-and-native-id-merge)
adds a second constraint: `graph.catalog_item` excludes currently superseded items. This
amendment settles both for the relational graph. It builds nothing. Promotions do not exist,
and ADR 0014 section 6's DEFER blocks them.

Where the graph actually crosses from MusicBrainz to Discogs decides the answer, so that was
inspected first. Paths are relative to each sibling repository's root, and line numbers are
at `database-schema` `4c297a1`, `catalog-api` `9ad0e09`, `musicbrainz-sql-loader` `55cbb8e`,
and `mcp-server` `c5865c1`.

- **The MusicBrainz vertices are an island.** `graph.catalog` declares `mb_artist`,
  `mb_label`, `mb_release`, and `mb_release_group` keyed on `mbid`, and the sixteen
  `mb_rel_<source>_<target>` edges, which carry the shared `mb_related` label, connect only
  those four to each other (`database-schema/src/groovemap_schema/postgres.py`,
  `_property_graph_vertices` line 4512, `_musicbrainz_relationship_edges` line 4594). No edge
  label joins an `mb_*` vertex to a Discogs vertex. `graph.mb_release` publishes
  `discogs_release_id` and no native id, although `musicbrainz.releases` carries an indexed
  `gm_item_id` (`postgres.py`, lines 1869-1880; columns lines 1402-1415; indexes lines
  1512-1525). The Discogs vertex views publish both `gm_item_id` and `gm_id`, the second read
  from current Discogs aliases through `_native_identity_join` (lines 1628-1640 and
  1660-1750).
- **The graph crosses catalogs at two places, both stored and both keyed on a Discogs id.**
  - The MusicBrainz half of `graph.issued_on` (`source = 'musicbrainz'`) is written by
    `musicbrainz-sql-loader` under `discogs_release_id`. A release with no Discogs id is
    skipped (`musicbrainz-sql-loader/brainztableinator/_record_processing.py`,
    `write_release_media`, lines 373-407; `_persistence.py`, lines 218-237). The schema's own
    projection of those rows joins the same way (`postgres.py`, `_MEDIA_SOURCE`, lines
    2210-2231).
  - The MusicBrainz half of `graph.artist_member_of` is rebuilt by
    `graph.refresh_artist_member_of()` through `musicbrainz.artists.discogs_artist_id`
    (`postgres.py`, `_DERIVED_EDGE_BOOTSTRAP`, line 2792). `discogs-sql-loader` calls it after
    extraction (`discogs-sql-loader/tableinator/graph_counters.py`, line 129).
    `graph.find_shortest_path` walks it as `MEMBER_OF` (`postgres.py`,
    `_PATH_RELATIONSHIP_TYPES`, line 3892).

  Nothing crosses at a release group. `discogs_master_id` is published on
  `graph.mb_release_group` and read by no other relation.
- **What a promotion would miss.** A promotion moves the MusicBrainz release's aliases and sets
  its `gm_item_id` (ADR 0014 section 3). It does not write `discogs_release_id`, which is the
  catalog's column. So the promoted release's media never reach `graph.issued_on`, and nothing
  else in the graph changes. A section 8 re-attachment acts only on items that already carry a
  Discogs id, so the graph already crosses those.
- **Readers.** No `catalog-api` query that reads PostgreSQL names an `mb_*` relation or
  `graph.catalog_item`. The `GRAPH_TABLE` and SQL families are in
  `catalog-api/api/queries/*_pg_queries.py`. MusicBrainz-sourced media reach three families
  through `graph.issued_on`: gaps (`gap_pg_queries.py`, line 27), label DNA
  (`label_dna_pg_queries.py`, lines 96 and 112), and the admin edge counts
  (`admin_pg_queries.py`, line 86). Explore reads the Discogs-only `graph.member_of`
  (`explore_pg_queries.py`, lines 36-40). `/api/path` is still served from Neo4j
  (`catalog-api/api/routers/explore.py`, line 589). `mcp-server` reaches all of these through
  `catalog-api`, addressing entities by Discogs id or by name
  (`mcp-server/mcp_server/tool_routing.py`, lines 89-216 and 297-318). `analytics-engine` and
  `graph-explorer` read none of these relations.
- **Neo4j.** `musicbrainz-graph-enricher` merges MusicBrainz data onto the Discogs node its
  Discogs id names, and skips a record without one
  (`musicbrainz-graph-enricher/brainzgraphinator/_projections.py`, lines 164, 197, and 209;
  `catalog-api/api/queries/musicbrainz_queries.py`, lines 12-56). The `gm_id` projection reads
  current Discogs aliases only (`catalog-api/api/projection.py`, `_SELECT_PAGE`, line 43).

#### 1. The join: native id first, Discogs id as the fallback

Each cross-catalog relation resolves a MusicBrainz row to its Discogs counterpart as follows.
It takes the row's native id from its `gm_item_id` and uses the current Discogs alias of that
native id, when one exists (`provider_aliases`, `provider = 'discogs'`, same entity kind,
`valid_to IS NULL`). When none exists, it uses the row's `discogs_*_id`. When neither resolves,
there is no crossing, which is today's behavior for an unlinked release.

This is a priority, not a union. For each row the two keys give one of three results:

- **Linked by the catalog and attached at load.** The native id is the Discogs item's, so both
  keys name the same Discogs row.
- **Split by load order.** The native id is the MusicBrainz item's own, and no Discogs alias
  points at it. The fallback names the catalog's Discogs row, as today. After a section 8
  re-attachment, the native id names the same row.
- **Promoted.** No Discogs id exists, and the native id names the promoted Discogs release.
  This is the only case in which the result changes.

Until the first promotion, the rule therefore produces exactly the rows the Discogs-id join
produces. One case needs a stated outcome: a release promoted to Discogs release A whose catalog
later links it to B. Between that catalog link and the next re-attachment run, the rule crosses
to A. It follows the alias table, which ADR 0009 makes the authority, and section 8's
contradiction revert moves it to B. The graph does not adjudicate between identity and a catalog
column.

At most one Discogs row is named. Every supersession in ADR 0009's amendment has a Discogs
survivor, ADR 0014 section 4 forbids merging two Discogs releases, and nothing moves a Discogs
alias. So a native id holds at most one current Discogs alias per kind.

The native id's Discogs alias is used rather than a comparison of the two rows' `gm_item_id`
columns. That lets `musicbrainz-sql-loader` compute the key in its own message transaction from
the alias table it already reads, without reading the Discogs catalog tables.

Rejected alternatives:

- **Keep the Discogs-id join.** A promoted edition stays invisible to the graph indefinitely.
  `/api/lookup` would answer with the promoted identity while graph reads never reflect it, so
  the two surfaces would give different answers about the same release.
- **Native id only.** Every item that load order splits would lose its crossing between a load
  and the next re-attachment run. So would every item the dependents guard skips, until the
  ADR 0009 merge lands. Today the graph crosses those through the Discogs id, so this would be
  a regression, and the fix only converges it back.
- **A plain union of both joins.** In the contradiction window above, one MusicBrainz release
  would cross to two Discogs releases at once. That asserts two editions for one release, which
  ADR 0014 section 4 exists to prevent. An `OR` across two keys also gives up the single index
  probe per row.
- **Compare the two rows' `gm_item_id` columns.** The MusicBrainz loader would have to read
  `public.releases`. That is the cross-source read ADR 0005 removed, and ADR 0014 section 8
  rejected it for the loaders.

#### 2. Where the rule is computed, and who keeps it current

- **`graph.refresh_artist_member_of()` and the phase 0 media projection.** `database-schema`
  applies the rule in the bodies it already owns. The refresh is a full rebuild, so the cost is
  paid at refresh time.
- **The MusicBrainz half of `graph.issued_on`.** `musicbrainz-sql-loader` applies the rule when
  it writes a release's rows. It still skips a release only when neither key resolves.
- **The ADR 0014 transactions.** The section 3 promotion and revert, and the section 8
  contradiction revert, change which Discogs release a MusicBrainz release crosses to. Each one
  rewrites that release's `source = 'musicbrainz'` rows in
  `graph.issued_on` inside the same transaction, beside the `gm_item_id` write in its step 3.
  The justification is the one ADR 0014 gives for step 3. Those rows are derived from
  `musicbrainz.releases.media` and the alias table, and the loader converges on the same rows
  the next time it writes that release. A plain re-attachment of a split item leaves the rows
  unchanged, because the fallback already named its Discogs release, so the section 8 job needs
  the step only on its contradiction path.
- **Artists.** No artist promotion exists (ADR 0014 section 7), and an artist re-attachment
  leaves the crossing unchanged. So the next refresh is enough for `graph.artist_member_of`. An
  amendment that adds artist promotions states whether its transaction also refreshes that
  artist's rows.

Rejected alternatives:

- **Leave `graph.issued_on` to the loader alone.** A promotion does not cause a MusicBrainz
  message. The promoted release's media would stay missing until the release happened to be
  written again, and a revert would leave rows crossing to a release it no longer describes.
- **A trigger in `database-schema` on `provider_aliases` or `musicbrainz.releases`.** Rejected
  for the reasons in ADR 0009's amendment. That repository owns DDL, not behavior, and a trigger
  cannot tell a promotion from a provider split.
- **Replace the stored crossings with views that resolve on read.** `graph.issued_on` and
  `graph.artist_member_of` became tables so that traversals read keyed rows. Resolving at read
  time would put an alias probe on every hop, including those of `graph.find_shortest_path`.

#### 3. Label mapping: no label changes; the MusicBrainz vertices gain `gm_item_id`

No label in this record's tables is added, renamed, or removed. None could be: Neo4j stores
MusicBrainz data as properties and relationships of the Discogs nodes, so no Neo4j type
corresponds to a crossing. The four `mb_*` vertex labels, which `database-schema` declares and
documents beside the mapping, each gain one property, `gm_item_id`. It has the name and `uuid`
type the Discogs vertices already publish, as SQL/PGQ requires of one property name across the
graph. A reader can then relate an `mb_release` to the Discogs `release` it describes by native
id. This is additive under this record's rule, and it stays inside persistence contract v1.
`discogs_release_id` stays on `mb_release` unchanged, because it is the catalog's assertion.

Rejected alternatives:

- **A new edge label from `mb_release` to `release`.** No Neo4j relationship type corresponds
  to it, so the parity harness would have nothing to compare it against. It would also widen
  the contract for a traversal no query family asks for, which is the reason ADR 0014 section 2
  gave for keeping candidate labels out.
- **Re-key the `mb_*` vertices on the native id.** The native id is not unique on the
  MusicBrainz side. Two MusicBrainz ids that name one Discogs artist share its native item
  (`postgres.py`, the comment above `_DERIVED_EDGE_BOOTSTRAP`). A vertex key must be unique,
  and `mbid` is the key every `mb_rel_*` edge references.

#### 4. Superseded items: `graph.catalog_item` filters through the published resolution; nothing else resolves

`graph.catalog_item` keeps an item only when the one-hop resolution ADR 0009's amendment
publishes resolves it to itself. Superseded items are therefore absent as vertices. That is one
probe per row on the resolution's partial unique index on `catalog_item_supersessions`. The
filter uses the published resolution rather than restating its predicate, so the graph and
every other reader agree on what "superseded" means. `owns` needs no filter, because the merge
transaction re-points `owned_copies` to the survivor. If an edge ever pointed at a filtered
vertex, a pattern would simply fail to match it; it would not surface a tombstone.

Nothing else in the graph reads the resolution. `gm_id` on the Discogs vertices, `gm_item_id`
on every vertex, and the native id section 1 reads never hold a superseded id. ADR 0009's
merge moves the aliases and recomputes those caches inside the transaction that opens the
supersession.

Rejected alternatives:

- **Keep superseded items as vertices, with a `superseded` or `resolved_id` property.** Every
  pattern that binds `catalog_item` would have to repeat the filter, and a pattern that forgot
  it would expose a tombstone as a live entity. ADR 0009's amendment rules that out.
- **A `superseded_by` edge label.** It would publish identity history as catalog structure
  without a Neo4j counterpart. Readers of history already resolve through the published
  resolution.
- **Resolve every native-id column in the graph.** That adds a probe per vertex row for a value
  the merge transaction already guarantees. It would also hide a cache-recompute bug that should
  surface as a parity or test failure.

#### 5. Query cost

- **Traversals.** No traversal plan changes. The rule runs when a crossing row is written or
  refreshed. `GRAPH_TABLE` patterns and `graph.find_shortest_path` read keyed rows, as they do
  today.
- **Writes.** A loader write of a release's media costs one more index probe, on
  `provider_aliases (native_id)`, before the Discogs-id fallback. The refresh of
  `graph.artist_member_of` joins the same index during a rebuild that is already full.
- **Vertices.** `gm_item_id` on the `mb_*` views is a column of the base table. `graph.catalog_item`
  gains an anti-probe per row, and it is read only through `owns`.

The spike gates in this record are unaffected. Until the first promotion, the crossings are
row-for-row the rows they replace.

Rejected alternative:

- **Cross at read time, in each query family, through the alias table.** Rejected in section 2.
  It is the same work repeated on every request instead of once per write.

#### 6. Consumers

- **`catalog-api` read paths need no change.** Gaps, label DNA, and the admin counts start
  counting a promoted release's MusicBrainz media, and nothing else they return changes. Explore
  and `/api/path` are unaffected for releases, because neither `graph.issued_on` nor an `mb_*`
  vertex is on the traversal surface. For artists, `/api/path` would change only after artist
  promotions exist.
- **The parity harness.** Neo4j never shows a promoted edition. The enricher has no PostgreSQL
  access by design (ADR 0009), and the `gm_id` projection writes one property only. So
  MusicBrainz-sourced media on a promoted release is an expected divergence. The harness names
  it, rather than letting a family fail parity on it.
- **`mcp-server`, `graph-explorer`, `analytics-engine`, and the graph enrichers need no change.**
  The MCP tools address entities by Discogs id or name through `catalog-api`, and the outcome
  tool's contract is settled by ADR 0009's amendment.

Rejected alternative:

- **Make Neo4j show promoted editions too.** The enricher would have to read the alias table,
  which is the cross-store coupling ADR 0009 refused it. Or the projection job would have to
  write relationships, and ADR 0009 limits it to one property. Neo4j is retiring under this
  record, so both costs buy a feature for the store being removed.

#### 7. Timing: with the first promotion, not before ADR 0014 section 6 returns GO

- **The native-id crossing is not built while section 6 stands at DEFER.** It is part of the
  implementation that a GO releases. The promotion action in `catalog-api` is not enabled on a
  deployment until the schema bodies, the loader change, and the transaction step in section 2
  are released there. That is the precondition ADR 0014 section 2 set for a promoted edition to
  reach the graph.
- **The `graph.catalog_item` filter is not tied to promotions.** It ships with
  `catalog_item_supersessions` and the published resolution, as ADR 0009's amendment already
  requires. It must be released before `catalog-api` writes the first supersession, whichever
  cause writes it.
- **A NO-GO closes the native-id crossing.** No promotion would ever exist, and until one
  exists the Discogs-id join is exact. The `gm_item_id` property on the `mb_*` vertices is the
  only part worth keeping without promotions. It may ship with the filter.

Rejected alternatives:

- **Build the crossing now.** Until a promotion exists it produces exactly today's rows. So the
  work buys nothing before GO, and a NO-GO wastes it.
- **Enable promotions first and add the crossing afterwards.** Every promotion in the gap would
  be served as identity by lookups and missing from the graph, the inconsistency section 1
  rejects. The transaction step would also have to backfill rows for promotions made before it
  existed.

#### Consequences of this amendment

A promoted edition reaches the relational graph in the same transaction that makes it identity,
and it leaves again in the transaction that reverts it. The graph keeps crossing catalogs where
it did before, at the same traversal cost. No label changes. The costs accepted are one stored
edge class that `catalog-api` rewrites outside its loader, a fallback rule to state wherever a
crossing is computed, and a divergence from Neo4j that the parity harness has to name.

Implementation work implied, as planning inputs. None is filed by this amendment:

- **`database-schema`**, released by a section 6 GO: the rule in the
  `graph.refresh_artist_member_of()` and phase 0 media bodies; the grant `catalog-api` needs to
  rewrite `source = 'musicbrainz'` rows of `graph.issued_on`; the `docs/architecture.md` rows.
  With the ADR 0009 merge work (`gm-database-schema-wfmw`), independent of GO: `gm_item_id` on
  the four `mb_*` views, and the `graph.catalog_item` filter through the published resolution.
- **`musicbrainz-sql-loader`**, released by GO: the rule in `write_release_media`.
- **`catalog-api`**, released by GO: the `graph.issued_on` step in the promote, revert, and
  contradiction-revert transactions, and the promoted-release exception in the
  parity harness.

`mcp-server`, `graph-explorer`, `analytics-engine`, `discogs-sql-loader`, and the graph
enrichers need no change.
