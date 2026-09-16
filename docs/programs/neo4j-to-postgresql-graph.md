# Neo4j to PostgreSQL graph-migration program

**Status: phases 0 and 1 filed 2026-09-15. Phases 2 to 5 are scoped here and are not filed.
Phase 2 onward is filed only after the phase 1 decision closes GO.**

This document records the rollout plan for
[ADR 0012](../adr/0012-postgresql-property-graph-migration.md), which decides that the GrooveMap
catalog graph moves out of Neo4j and into PostgreSQL as a SQL/PGQ property graph. The decision
itself, its label mapping, and its list of affected repositories live in that record. This
document carries only the order of delivery.

The phase order is a dependency order, not a schedule. Every later phase consumes something an
earlier phase publishes, so a phase begins when its entry criteria hold at a reviewed commit and
not when the previous phase is declared finished.

Two properties of this program differ from the earlier rollouts in this directory. The first is
that it is gated in the middle: phases 0 and 1 are filed now, and phases 2 to 5 are scoped here
but deliberately not filed, because a feasibility spike sits between them and can close the
program instead of continuing it. The second is that it depends on a PostgreSQL release that is
not yet generally available. Everything phase 0 builds runs on PostgreSQL 18, and the one
statement that does not is gated on the server version and an explicit switch, so preparatory
work ships dark into an unchanged production engine.

| Phase | Repositories | What the phase delivers | Filed |
| --- | --- | --- | --- |
| 0 Foundation | database-schema, catalog-api, design, deployment | The PostgreSQL 19 integration tier, the `graph` schema relations, the version-gated property graph, the catalog-api backend seam with one pilot family, ADR 0012 and this plan, and a held deployment pin. | Yes |
| 1 Feasibility spike | database-schema | Performance of views against materialized edges against Neo4j, the Cypher coverage matrix and target edge model, the variable-length path strategy, and the GO/NO-GO decision. | Yes |
| 2 Relational edge model | database-schema, discogs-sql-loader, musicbrainz-sql-loader | Edge and name-keyed vertex relations in `graph`, written by the SQL loaders, with a dual-write period. | After GO |
| 3 Read migration | catalog-api | Per-family `GRAPH_TABLE` rewrites behind the seam, the two recursive traversals, the parity harness, performance budgets, and the flipped default. | After phase 2 |
| 4 Write cutover | catalog-api, discogs-graph-enricher, musicbrainz-graph-enricher | Collection and wantlist edges become views, both graph enrichers retire, and the `gm_id` projection job retires. | After phase 3 |
| 5 Decommission | deployment, database-schema, operations-console, python-libraries, operations-toolkit, design | Neo4j removed everywhere, persistence contract major bump, and an amendment to ADR 0012. | After phase 4 |

## Phase 0: foundation

**Repositories.** `database-schema`, `catalog-api`, `design`, `deployment`.

**Entry criteria.** ADR 0012 accepted. None other; this phase is the program's root and pins
nothing upstream.

**What it delivers.**

- **`database-schema`.** A PostgreSQL 19 integration tier alongside the existing PostgreSQL 18
  tier, so both engines are exercised by the same schema tests. A `graph` schema holding vertex
  and edge views derived from the relations that already exist: the Discogs JSONB arrays
  unnested, `musicbrainz.relationships` split by endpoint-type pair, and the collection and
  wantlist rows cast to the release key. A `CREATE PROPERTY GRAPH` statement declaring the ADR
  0012 labels over those views with explicit `KEY ... REFERENCES`, applied only when
  `server_version_num` is 190000 or higher and an explicit environment switch is on, and made
  idempotent by a catalog existence check rather than by an `IF NOT EXISTS` clause the statement
  does not have. The label mapping published as schema documentation. Persistence contract v1 is
  unchanged in version and records the property graph as conditional on server version.
- **`catalog-api`.** A graph-backend seam, one setting selecting Neo4j or PostgreSQL and
  defaulting to Neo4j, in front of the query functions that today take the Neo4j driver directly.
  One pilot family, the multi-hop collaborator queries, implemented as `GRAPH_TABLE` behind the
  seam, with a parity test that runs both implementations against the same fixtures and compares
  results.
- **`design`.** ADR 0012 and this document.
- **`deployment`.** A major-version upgrade runbook covering the existing compose volume, by
  `pg_upgrade` or by dump and restore. The image pin change itself is prepared and held.

**Exit criteria.** The schema initializer applies twice with no effect the second time, on both
engines. The property graph exists in a PostgreSQL 19 integration run and does not exist in a
PostgreSQL 18 one. The pilot family returns results identical to its Cypher implementation on the
parity fixtures. Every repository's own check gate passes. The deployment pin is not released.

**What gates it.** Nothing gates phase 0 from starting. It gates itself from being finished: the
deployment pin bump is held until PostgreSQL 19 is generally available, and is released against a
generally available image rather than a beta.

## Phase 1: feasibility spike

**Repositories.** `database-schema`, as an explicitly time-boxed spike whose deliverable is
evidence and a decision rather than shipped code.

**Entry criteria.** The `graph` schema views and the gated property graph from phase 0 are merged
and available at a revision the spike can apply.

**What it delivers.**

- A performance comparison of the hot fixed-length read families in three shapes: `GRAPH_TABLE`
  over the phase 0 views, `GRAPH_TABLE` over materialized edge relations, and the current Neo4j
  implementation. Measured at representative scale, which for GrooveMap means tens of millions of
  edges rather than a fixture set.
- A Cypher coverage matrix mapping every one of the query functions in `catalog-api` to its
  `GRAPH_TABLE` spelling, or to the reason it has none. Includes the handful that use unbound
  relationship types and the one administrative display that reads Neo4j's own metadata
  procedures.
- A target relational edge model: the edge and vertex relations, their keys, their indexes, and
  which loader writes each one.
- A prototype of the two variable-length workloads as recursive common table expressions, with
  measured latency and a proposed depth cap for each.
- A decision recording GO or NO-GO with the evidence behind it.

**Exit criteria.** The decision is recorded. On GO, phases 2 to 5 are filed against the edge model
and the depth caps the spike produced. On NO-GO, the program closes: the graph stays in Neo4j, the
declared property graph remains an unreferenced catalog object behind its gate, and ADR 0012 takes
an amendment recording what was measured and why the decision did not survive it.

**The GO/NO-GO questions.** These are the questions the spike exists to answer, and no phase after
this one is filed until all three have answers.

1. Can `GRAPH_TABLE` serve the hot fixed-length read families at GrooveMap scale, and does that
   require materialized edge relations rather than views over JSONB? A yes that depends on
   materialization is still a yes, but it makes phase 2 a precondition for phase 3 rather than a
   parallel track.
2. Can `/api/path` and the explore traversal be served by recursive common table expressions over
   edge relations within the existing request budgets, and with what depth caps? See the section
   below.
3. What is the target relational edge model, and which loader writes each relation?

## The two variable-length workloads

`GRAPH_TABLE` supports fixed-length path patterns only. It has no quantifiers, no variable-length
path patterns, and no shortest-path construct, so two workloads in `catalog-api` have no SQL/PGQ
spelling at all. They are the sharpest open question in this program and the reason phase 1 exists
as a spike rather than as design work.

- **Shortest path.** `find_shortest_path` uses Cypher's `shortestPath` bounded at depth 10. It
  surfaces three ways: as `GET /api/path`, as the `find_path` natural-language intent, and as the
  `find_path` MCP tool. All three move together.
- **Explore traversal.** `get_explore_traversal` walks `*1..n` from a starting node.

The candidate strategy for both is a recursive common table expression over the edge relations,
with an explicit depth cap and cycle detection on the accumulated path, which is the standard
PostgreSQL idiom and is independent of SQL/PGQ. What is unknown is whether that holds inside the
existing request budgets at GrooveMap's edge counts, and what depth cap each workload can afford.
Two sub-questions stay open until the spike answers them:

- Whether a recursive traversal needs materialized edge relations, or whether it can run over the
  phase 0 views. A recursive query that re-unnests JSONB at every level is the shape most likely
  to fail the budget.
- Whether the depth cap the budget allows is the depth the product needs. If the affordable cap is
  below 10, `/api/path` changes behaviour rather than merely changing engine, and that is a product
  decision rather than a migration one.

Until both are settled, these two families stay on Neo4j regardless of how many other families
have crossed. Phase 3 flips the default per family, so a slow traversal does not hold back the
fixed-length reads.

## Phase 2: relational edge model

**Repositories.** `database-schema`, `discogs-sql-loader`, `musicbrainz-sql-loader`.

**Entry criteria.** Phase 1 closed GO, and the target edge model is recorded.

**What it delivers.** The edge and name-keyed vertex relations the spike specified, in the `graph`
schema, replacing the phase 0 views where the spike found views insufficient. The SQL loaders
write them from the same catalog events the graph enrichers consume today, which is what makes the
enrichers redundant in phase 4 rather than merely duplicated. Media, credits, and company edges
included. The `gm_id` becomes a column on the vertex relations rather than a property a separate
job copies across stores. A dual-write period runs while both stores hold edges.

**Exit criteria.** Every edge label in the ADR 0012 mapping is populated by a loader. Row counts
and spot-checked edges agree with Neo4j. The property graph declared over the new relations serves
the pilot family with the same results it served from views. Persistence contract stays v1; every
change here is additive.

**What gates it.** The GO verdict, and the edge model. Filed only after both exist.

## Phase 3: read migration

**Repositories.** `catalog-api`.

**Entry criteria.** Phase 2 merged and released at a revision the catalog-api integration test can
apply, and PostgreSQL 19 generally available and pinned in deployment.

**What it delivers.** The query families rewritten as `GRAPH_TABLE` behind the phase 0 seam, one
family at a time, in the order the coverage matrix sets. The two variable-length workloads
implemented as recursive common table expressions with the caps phase 1 measured. A parity harness
that runs both implementations against the same fixtures for every family. A stated performance
budget per family. The default backend flips from Neo4j to PostgreSQL once every family has crossed.

**Exit criteria.** Every family passes parity and meets its budget, or is explicitly recorded as
staying on Neo4j with a reason. The default is flipped. Neo4j still runs and can still serve, so
the flip is reversible by a setting.

**What gates it.** A family crosses on its own parity result. The default flips only when no
family is left behind, because a mixed default is a configuration nobody can reason about.

## Phase 4: write cutover

**Repositories.** `catalog-api`, `discogs-graph-enricher`, `musicbrainz-graph-enricher`.

**Entry criteria.** Phase 3's default flipped and stable in production for a stated soak period.

**What it delivers.** Collection and wantlist edges stop being written to Neo4j and become views
over `user_collections` and `user_wantlists`, which already hold the same rows. Both graph
enrichers retire, since the SQL loaders became the single consumer of the catalog events in phase
2. The `gm_id` projection job retires, since the property became a column in phase 2.

**Exit criteria.** Nothing writes to Neo4j. The enricher services are removed from the deployment
topology. The erasure closure [ADR 0010](../adr/0010-first-party-events-consent-and-deletion.md)
requires is re-proved against the new edge relations, because the user subgraph it deletes has
moved.

**What gates it.** The soak period, and the erasure closure proof. A deletion guarantee that was
proved against Neo4j is not inherited by the replacement.

## Phase 5: decommission

**Repositories.** `deployment`, `database-schema`, `operations-console`, `python-libraries`,
`operations-toolkit`, `design`.

**Entry criteria.** Phase 4 complete, and a retention decision on the Neo4j volume.

**What it delivers.** The Neo4j service and its volume removed from deployment. The graph-store
section of the persistence contract removed, with the contract taking its major bump to v2. The
Neo4j health check and graph-store views removed from `operations-console`. The shared Neo4j
helper and the driver extra removed from `groovemap-runtime`. The Neo4j operational entry points
removed from `operations-toolkit`. The Cypher modules removed from `catalog-api`. An amendment to
ADR 0012 recording completion, and the repository catalog updated.

**Exit criteria.** No repository declares a Neo4j dependency. Every consumer has promoted the v2
contract. The catalog and the architecture documentation describe one store.

**What gates it.** The contract major bump. It is the only breaking change in the program, it is
deliberate, and it happens here rather than being spread across earlier phases.

## Explicit non-goals of this program

- **Graph analytics.** Nothing uses Neo4j's graph data science procedures today and no equivalent
  is planned. A future centrality or community-detection workload needs its own decision about
  where it runs.
- **Reshaping the existing tables to suit the graph.** The `graph` schema is additive.
  `SOURCE KEY ... REFERENCES` resolves against a declared key rather than a table-level foreign
  key, so no constraint is added to `musicbrainz.relationships` or to any JSONB-backed table to
  make an edge declarable.
- **Re-deciding what the graph asserts.** The projections ADR 0007, ADR 0009, and ADR 0011 created
  carry forward under the ADR 0012 label mapping with the same meaning and the same source. None of
  those records is amended by this program.
- **The administrative metadata display.** One `catalog-api` surface reads Neo4j's own metadata
  procedures for an administrative statistics panel. Replacing it is a catalog query, and what the
  panel should show once there is one store is a product decision recorded where it is made.
