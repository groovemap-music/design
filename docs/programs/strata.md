# Strata program rollout

**Status: M1 to M5 filed on 2026-10-23. M6 (concept D) filed on 2026-10-24 as five epics, the
last two with held kickoffs that were later released. All fourteen epics in the Molecules table
were closed by 2026-10-25. The first-deployment checks remain open. Bead state is authoritative;
this document records order and handoffs, not progress.**

This document tracks delivery of [ADR 0016](../adr/0016-strata-graph-view.md), which decides
that Strata, the level-of-detail bi-temporal graph view, is built as concepts A, B, C′, and D
across five repositories. The decision, the verdicts, and the evidence live in that record
and in the four spike documents below. This document carries the molecule list, the
cross-repository order, the artifacts that unblock each molecule, and the checks the spikes
defer to the first deployment.

The order is a dependency order, not a schedule. A molecule starts when the artifact it
consumes exists at a reviewed commit, not when the previous molecule is declared finished.

Evidence:

- [`gm-design-1h2l`](../spikes/gm-design-1h2l-strata-ladder.md): the credit, master, release
  ladder, collector changes, and strata read cost ([harness](../spikes/gm-design-1h2l/README.md)).
- [`gm-design-on0x`](../spikes/gm-design-on0x-strata-renderer.md): concept A's renderer at
  catalog scale, accessibility, and engine distribution ([harness](../spikes/gm-design-on0x/README.md)).
- [`gm-design-4804`](../spikes/gm-design-4804-strata-atlas.md): lifecycles, atlas layout, and
  taste projection for B and C′ ([harness](../spikes/gm-design-4804/README.md)).
- [`gm-design-loj9`](../spikes/gm-design-loj9-strata-ledger.md): the identity history for
  concept D ([harness](../spikes/gm-design-loj9/README.md)).

## Molecules

Each epic is filed in its owning repository. Read one with `bh plan show <epic>` from that
repository's checkout.

| Molecule | Concept | Repository | Epic | Delivers |
| --- | --- | --- | --- | --- |
| M1 | all | design | `gm-design-t55n` | ADR 0016, this program document (`gm-design-8qcl`), state-color tokens (`gm-design-17td`) |
| M2 | A | database-schema | `gm-database-schema-b0mk` | `musicbrainz.releases (release_group_mbid)` index (`gm-database-schema-kk3f`); M4's insights tables (`gm-database-schema-0bv9`) |
| M2 | A | catalog-api | `gm-catalog-api-bcre` | `GET /api/explore/strata` (`gm-catalog-api-absv`), then caching and the large-root policy (`gm-catalog-api-owym`) |
| M3 | A | graph-explorer | `gm-graph-explorer-5dd` | The three.js `webgl-inst` engine and Discography Strata in Explore |
| M4 | B | catalog-api | `gm-catalog-api-3s01` | The internal-insights 1.2.0 producer endpoint (`gm-catalog-api-hfg2`) and the `GET /api/insights/style-atlas` proxy (`gm-catalog-api-kw87`) |
| M4 | B | analytics-engine | `gm-analytics-engine-1i8` | Style-year counts and parent shares, lifecycle stages and the pinned layout, and `GET /api/insights/style-atlas` |
| M4 | B | graph-explorer | `gm-graph-explorer-q3e` | The Genre Atlas in Genres and Insights |
| M5 | C′ | catalog-api | `gm-catalog-api-r8c7` | The extended Fit route (`gm-catalog-api-l23k`) and the taste projection route (`gm-catalog-api-qcnx`) |
| M5 | C′ | graph-explorer | `gm-graph-explorer-lyd` | Taste Strata, the Fit landing point, and Discover outcomes |
| M6 | D | database-schema | `gm-database-schema-09mv` | `public.identity_link_events`, the ledger table and its contract |
| M6 | D | catalog-api | `gm-catalog-api-za77` | The one-time full-export backfill command |
| M6 | D | musicbrainz-sql-loader | `gm-musicbrainz-sql-loader-nxc` | Link-change recording at load |
| M6 | D | catalog-api | `gm-catalog-api-cn2v` | The three `admin_identity_ledger_*` routes (kickoff was held, since released) |
| M6 | D | operations-console | `gm-operations-console-6qpy` | Contract promotion, the proxy, and the Ledger tab (kickoff was held, since released) |

The child beads inside each epic carry their own dependencies. Notable in-epic order:

- **M3 (graph-explorer).** The collector state machine (`gm-graph-explorer-8jx`) and the pure
  layout module (`gm-graph-explorer-uii`) precede the renderer (`gm-graph-explorer-k5q`).
  Explore integration (`gm-graph-explorer-1v9`) follows the renderer. The accessible table
  (`gm-graph-explorer-v6f`) and the Playwright coverage (`gm-graph-explorer-gka`) close it.
- **M4 (analytics-engine).** The counts and parents computation (`gm-analytics-engine-m86`)
  precedes the lifecycle and layout computation (`gm-analytics-engine-cvk`), which precedes the
  read endpoint (`gm-analytics-engine-21z`).
- **M5 (graph-explorer).** The Taste Strata layer (`gm-graph-explorer-0av`) precedes the Fit
  landing point (`gm-graph-explorer-332`).

## Dependency order

```text
M1 design ──┬─ tokens ───────────────────────────────► M3 state machine
            └─ ADR 0016 (decisions every molecule reads)

M2 database-schema index ─► M2 catalog-api route ─► M3 graph-explorer (Explore integration)

M3 engine ─────────────────────────────────────────► M4 Genre Atlas ─► M5 Taste Strata

M4 database-schema tables ─► M4 analytics-engine ─► M4 catalog-api proxy ─► M4 Genre Atlas
M4 catalog-api 1.2.0 producer ─► M4 analytics-engine
M5 catalog-api routes ─────────────────────────────────────────────────► M5 Taste Strata
```

In words:

1. **M1** comes first. It fixes what is drawn, in which state vocabulary, on which clocks,
   computed where, and with which colors.
2. **M2 and M3** follow. M3's engine, layout, and state machine need only M1 and can start
   beside M2. M3's Explore integration (`gm-graph-explorer-1v9`) needs M2's route promoted.
3. **M4 and M5** follow M3, because the Genre Atlas and Taste Strata reuse its engine. M5 also
   starts after M4 lands, because C′ layers the collector's taste on the Genre Atlas.
4. **M6** follows its own order, below, and does not block M1 to M5.

## Handoffs

Every cross-repository dependency below is a pin that the consumer verifies with its own
check gate. No repository imports another's source or uses it as a Docker build context.

| # | Handoff | From | To | Unblocks |
| --- | --- | --- | --- | --- |
| H1 | database-schema revision carrying the `release_group_mbid` index (`gm-database-schema-kk3f`) | database-schema | catalog-api: bump the schema pin | The MusicBrainz sibling join in `gm-catalog-api-absv` |
| H2 | Graph-explorer contract promoted with `/api/explore/strata`, the contract staying at `"version": 1` | catalog-api (M2) | graph-explorer: promote `contracts/catalog-api/graph-explorer/v1` | `gm-graph-explorer-1v9`, Explore integration |
| H3 | database-schema revision carrying the Genre Atlas `insights` tables (`gm-database-schema-0bv9`) | database-schema | analytics-engine: bump the schema pin | `gm-analytics-engine-m86` |
| H4 | `internal-insights` contract 1.2.0 with `/api/internal/insights/style-year-counts` (`gm-catalog-api-hfg2`) | catalog-api | analytics-engine: promote the contract, `source.json` and digests | `gm-analytics-engine-m86` |
| H5 | analytics-engine serving `GET /api/insights/style-atlas` (`gm-analytics-engine-21z`) | analytics-engine | catalog-api: the proxy (`gm-catalog-api-kw87`) forwards to it | A working proxy in a deployed stack |
| H6 | Graph-explorer contract promoted with `/api/insights/style-atlas` (`gm-catalog-api-kw87`) | catalog-api (M4) | graph-explorer: promote the contract | `gm-graph-explorer-cnn`, the Genre Atlas view |
| H7 | Graph-explorer contract promoted with the extended Fit route and `/api/user/taste-projection` (`gm-catalog-api-l23k`, `gm-catalog-api-qcnx`) | catalog-api (M5) | graph-explorer: promote the contract | `gm-graph-explorer-0av` and `gm-graph-explorer-332` |
| H8 | State-color tokens in `brand/tokens.json` and regenerated brand assets (`gm-design-17td`) | design | graph-explorer: promote the brand assets | `gm-graph-explorer-8jx`, token-driven state colors |

Notes on the handoffs:

- **database-schema revisions.** Consumers pin database-schema by git revision, so each
  consumer molecule bumps its pin after the schema bead lands. catalog-api takes the index
  (H1). analytics-engine takes the tables (H3). The two schema beads are independent; H1 is
  needed in M2 and H3 in M4.
- **catalog-api graph-explorer contract.** Additive routes keep the contract at
  `"version": 1`. Each route that M2, M4, and M5 add is registered in
  `api/contracts/graph-explorer/v1/routes.json` with the contract's revision bumped, and
  graph-explorer promotes it with `scripts/check-contracts.py`.
- **internal-insights 1.2.0.** catalog-api bumps the producer contract and regenerates its
  bindings and digests. analytics-engine promotes it, and `just contract-check` there must
  pass before the computation lands.
- **Brand tokens.** `brand/tokens.json` is canonical in this repository. graph-explorer
  promotes the regenerated brand assets with its brand promotion check, and the state colors
  must resolve from the promoted tokens.
- **Engine distribution.** graph-explorer produces the engine module and vendors three.js
  0.186.1 itself. A consumer takes the engine as a pinned vendored copy with a `source.json`
  that records `producer_repository`, `producer_commit`, and `sha256`. operations-console
  promotes it only when a 3D concept D view is planned (ADR 0016 section 2).

### One catalog-api molecule at a time

M2 (`gm-catalog-api-bcre`), M4 (`gm-catalog-api-3s01`), and M5 (`gm-catalog-api-r8c7`) all
edit the graph-explorer contract registry, and M4 also edits the internal-insights contract.
They run one at a time, in this order, so no two molecules rewrite the same contract files:

1. A, which is M2: `/api/explore/strata`, then caching and the large-root policy.
2. B, which is M4: the internal-insights 1.2.0 producer, then the `/api/insights/style-atlas`
   proxy.
3. C′, which is M5: the Fit route extension and the taste projection route.

This is the dispatch order. It matches the dependency order except that M5's catalog-api work
does not itself need M4's, so it may be reordered only by deciding, in the dispatching
session, that the contract file conflict is acceptable.

## First-deployment checks

The spikes measured on a predecessor graph and on dumps, not on a deployed GrooveMap. Each of
the checks below is deferred to the first deployed environment that holds a full production
load. The last column names what the result informs.

| Check | Run by | Source | Informs |
| --- | --- | --- | --- |
| Re-run the strata read latency harness against the deployed catalog, which holds the placeholder roots at full size | M2, `gm-catalog-api-owym` | [`latency.py`](../spikes/gm-design-1h2l/scripts/latency.py) | The latency verdict in `gm-design-1h2l` section 5 (50 ms warm p95 or less under 10,000 releases; 541 ms warm p95 with a cache from 10,000) and the large-root policy |
| Run the collector `date_added` check once real users have synced | M2 | [`collector_time.sql`](../spikes/gm-design-1h2l/scripts/collector_time.sql) | Whether the collector's recorded `date_added` survives sync, which A's transaction-time clock depends on |
| Time the style-by-year Cypher on the first full production load. Confirm it fits analytics-engine's default 900 s read budget | M4, `gm-analytics-engine-m86` | [`predecessor_neo4j_timing.sh`](../spikes/gm-design-4804/scripts/predecessor_neo4j_timing.sh) runs it unchanged | Whether the producer endpoint fits the budget as designed |
| Confirm the catalog-api read of the table serves under its route budget | M4, `gm-catalog-api-kw87` and `gm-analytics-engine-21z` | `gm-design-4804` section B5, Recommendation for B 1 | Whether the stored table serves under the route budget |
| If the style-by-year Cypher instead runs well under a second, revisit computing lifecycle live | M4 | `gm-design-4804` section B5 | ADR 0016's rejected alternative "Live lifecycle in catalog-api", which it says to revisit in that case |

The 4804 numbers the check compares against: the predecessor's aggregation took about 30 s on
a full graph, the logged genre-trends path has a tail to 109.5 s, and catalog-api's own
genre-tree timeout is 30 s. The latency numbers for A are in `gm-design-1h2l` section 5: GO
under 10,000 releases, GO with a cache from 10,000 releases, and DEFER for roots above 134,051
releases, which were not measured.

The `gm-catalog-api-owym` acceptance criteria require the route docs to reference the latency
check. Keep that reference pointing at this section.

## Open questions from ADR 0016

These were not settled by the evidence. Each is owned by a record, not by a guess. Rows marked
decided name the amendment to ADR 0016 or the merged bead that closed them.

| Question | Decided by |
| --- | --- |
| D's backfill branch: backfill-from-fullexport or forward-only | Decided: backfill from the full export, then record live. `gm-design-6b8u` in epic `gm-design-cgh9`, recorded by the 2026-10-24 amendment to ADR 0016 |
| Roots above 134,051 releases: a per-artist master summary, or a refusal or cap | Decided: a root above 134,051 releases is refused with a 422, not capped, and no summary is built yet. The first-deployment latency check confirms or moves the ceiling. Recorded by `gm-catalog-api-owym` in catalog-api's route documentation |
| Whether the Genre Atlas offers a control over its monthly `computed_at` recomputations | Decided: the atlas shows the latest computation only, with no control. Revisit if users ask to compare months. Recorded by the [2026-10-24 amendment](../adr/0016-strata-graph-view.md#2026-10-24-activity-surface-dominant-style-and-atlas-history) to ADR 0016 |
| A strata activity surface: `taxonomy/events/v1` has none, so a strata node cannot carry Discover outcomes today. Adding one changes ADR 0010's closed vocabulary | Decided: none for now. Revisit only when a concrete analytics or Discover need on Strata exists, as its own decision. Recorded by the [2026-10-24 amendment](../adr/0016-strata-graph-view.md#2026-10-24-activity-surface-dominant-style-and-atlas-history). M5's Discover outcomes (`gm-graph-explorer-07j`) follow ADR 0010 consent and are never collector state |
| Taste Strata's dominant style for a non-landmark collector master | Decided: confirmed as built in `gm-graph-explorer-0av`. Revisit if Taste Strata is drawn in a shared view. Recorded by the [2026-10-24 amendment](../adr/0016-strata-graph-view.md#2026-10-24-activity-surface-dominant-style-and-atlas-history) |
| Real devices and real collections: no real phone, mid-range laptop, or real user collection was measured. C′'s real-user validation stays DEFER | Later evidence, after M5 ships |
| M4 fixes the insights table names and the in-sector placement from the measured trade-off | Decided: `gm-database-schema-0bv9` added `insights.style_year_counts`, `insights.style_parents`, and `insights.style_atlas_layout`, with the genre ring later split into `insights.genre_atlas_sectors`, and `gm-analytics-engine-cvk` places nodes by lean × emergence rank, with co-tag MDS recorded as the measured alternative |

## M6: concept D

Concept D, the Identity Ledger, is GO as a history ledger whose first build is a table
(ADR 0016 section 7). Spike `gm-design-6b8u` (epic `gm-design-cgh9`) decided the open
backfill branch, and the [2026-10-24 amendment](../adr/0016-strata-graph-view.md#2026-10-24-concept-ds-backfill-branch-and-m6)
records it: backfill from the MusicBrainz full export, labeled "dated from the MusicBrainz
full export", then record live at load. The first console screen is a paged table plus a
per-month density strip.

M6 is five epics, one per repository. Read one with `bh plan show <epic>` from that
repository's checkout.

| Order | Repository | Epic | Delivers | Kickoff |
| --- | --- | --- | --- | --- |
| 1 | database-schema | `gm-database-schema-09mv` | `public.identity_link_events`. This table is the contract the other four read or write | Open |
| 2 | catalog-api | `gm-catalog-api-za77` | The one-time full-export backfill command | Open |
| 3 | musicbrainz-sql-loader | `gm-musicbrainz-sql-loader-nxc` | Recording link changes at load, from exact diffs | Open |
| 4 | catalog-api | `gm-catalog-api-cn2v` | The three read-only `admin_identity_ledger_*` routes behind `require_admin` | Held, then released |
| 5 | operations-console | `gm-operations-console-6qpy` | Contract promotion, the proxy, and the Ledger tab | Held, then released |

The order is held by kickoff, not by bead dependencies, because the epics live in different
repositories. Epic 1 comes first, because every other epic consumes its table. Epics 2 and 3
follow it. Epics 4 and 5 wait: their kickoffs stay held until
the catalog-api and operations-console work already under way in those repositories has
reached its main branch, so the ledger routes and the Ledger tab are built on top of it and
not beside it. Epic 5 also follows epic 4, because it promotes the contract that epic 4
extends.

What is already fixed, and what M6 inherits:

- Read-only PostgreSQL routes behind `require_admin`, added to catalog-api's
  operations-console contract and re-promoted there. This is the recorded exception to the
  rule that Strata graph reads are Neo4j queries.
- The ledger screen belongs to operations-console. It promotes the engine only when a 3D view
  of D is planned, and only after that plan settles the module-script question.
- The console keeps classic scripts only, with no ES modules.
- No edition candidates, while ADR 0014 section 6 stands at DEFER.

## Explicit non-goals of this program

- Authoring collection or wantlist changes. The collector machine is observed only, and the
  view must not imply a write. A Discogs write integration or a first-party wantlist is a
  separate decision.
- Moving any graph read off Neo4j, or reopening ADR 0012.
- Edition candidates or any matching schema, while ADR 0014 section 6 stands at DEFER.
- Placing Depth or artist and label Novelty on the atlas. Full concept C as mocked is NO-GO.
- Publishing an engine package. The engine is distributed as a pinned vendored module.
