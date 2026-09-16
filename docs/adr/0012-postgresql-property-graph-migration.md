# ADR 0012: PostgreSQL SQL/PGQ as the catalog graph engine

- Status: Accepted

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
