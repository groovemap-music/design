# ADR 0016: Strata, the level-of-detail bi-temporal graph view

- Status: Accepted on 2026-10-23 (`gm-design-7w18`, epic `gm-design-t55n`); amended 2026-10-24
- Concept D's backfill branch: backfill from the MusicBrainz full export, then record live, decided by the [2026-10-24 amendment](#2026-10-24-concept-ds-backfill-branch-and-m6)

## Context

Strata is a GrooveMap graph view. It draws the graph as stacked 2D planes in 3D, and each
plane is one level of detail of the plane below it. Position on a plane is a time axis or a
cluster layout. A group's hull may contain only that group's descendants, and edges stay on
their plane where possible and must not cross. Node color is a state in a state machine.
Two clocks drive it: valid time and transaction time.

Four concepts were mocked up in the maintainer's private artifact. Its data is illustrative,
and nothing here relies on it as evidence.

- **A. Discography Strata** (graph-explorer Explore): credit, master, and release planes,
  with x as release year and color as collector state.
- **B. Genre Atlas** (graph-explorer Genres and Insights): genre, style, and master planes in
  a cluster layout, with color as lifecycle stage over valid time.
- **C. Taste Strata and the Fit landing point** (Will it fit?, Discover): B's atlas with a
  collector's items and a candidate's five Fit components drawn on it.
- **D. Identity Ledger** (operations-console): work, edition, and evidence planes, with color
  as identity state over transaction time.

Spike epic `gm-design-uq8t` asked whether each concept can be built honestly on GrooveMap's
real data, stores, and browsers. Its evidence is four spike documents:

- [`gm-design-1h2l`](../spikes/gm-design-1h2l-strata-ladder.md): how the catalog fits the
  credit, master, release ladder, which collector changes GrooveMap can author, and what a
  strata read costs on Neo4j ([harness](../spikes/gm-design-1h2l/README.md)).
- [`gm-design-on0x`](../spikes/gm-design-on0x-strata-renderer.md): concept A's renderer at
  catalog scale, its accessibility, and engine distribution
  ([harness](../spikes/gm-design-on0x/README.md)).
- [`gm-design-4804`](../spikes/gm-design-4804-strata-atlas.md): genre and style lifecycles,
  the atlas layout, and the taste projection for B and C
  ([harness](../spikes/gm-design-4804/README.md)).
- [`gm-design-loj9`](../spikes/gm-design-loj9-strata-ledger.md): the identity history concept
  D's ledger can show without edition candidates
  ([harness](../spikes/gm-design-loj9/README.md)).

Decision bead `gm-design-7xo5` gave the verdicts. Its close reason and its 2026-10-23
comments record the maintainer's choices. This record restates that evidence by citation and
does not re-derive it. Every number below is an aggregate that a cited section already
states.

Facts that bound the decision:

- [ADR 0012](0012-postgresql-property-graph-migration.md)'s 2026-10-02 amendment keeps Neo4j
  authoritative for graph reads. SQL/PGQ must not be activated.
- [ADR 0014](0014-cross-catalog-edition-candidates.md) section 6 stands at DEFER. No matching
  schema, candidate store, or review action exists or may be built until a re-run clears the
  bar.
- [ADR 0009](0009-native-identity-and-provider-aliases.md) makes the alias table the identity
  authority, in PostgreSQL. Its 2026-09-25 amendment defines supersession and re-attachment.
- Collection and wantlist reach GrooveMap only through Discogs sync. First-party outcomes go
  through activity events under [ADR 0010](0010-first-party-events-consent-and-deletion.md)
  consent.
- [ADR 0013](0013-pgvector-catalog-embeddings.md) artist embeddings exist. Nothing embeds
  genres, styles, or masters.
- No GrooveMap repository imports another's source or uses it as a Docker build context.
  Canonical brand tokens live in `brand/tokens.json`.

## Verdicts

| Concept | Verdict | Rests on |
| --- | --- | --- |
| A | **GO on 3D** (`webgl-inst`), by the maintainer's choice, on conditions | `gm-design-on0x` Verdict and section "The maintainer's judgment"; `gm-design-1h2l` Verdict |
| B | **GO** | `gm-design-4804` Verdict B |
| C | **GO in reduced scope (C′)**. Full C as mocked is **NO-GO**. Real-user validation is **DEFER** | `gm-design-4804` Verdict C; `gm-design-7xo5` comment of 2026-10-23 |
| D | **GO** by the maintainer, as a history ledger. The backfill branch was pending `gm-design-6b8u` and is decided by the [2026-10-24 amendment](#2026-10-24-concept-ds-backfill-branch-and-m6): backfill from the full export, then record live | `gm-design-7xo5` comments of 2026-10-23; `gm-design-loj9` Verdict |

The roadmap order holds, as `gm-design-7xo5`'s close reason records: M1 (this record), then
M2 and M3, then M4 and M5. M6, concept D, was filed after epic `gm-design-cgh9` finished; see the 2026-10-24 amendment.

## Decision

### 1. Renderer: three.js 0.186.1, the `webgl-inst` engine, 3D for concept A

Concept A is drawn in 3D with the `webgl-inst` renderer on three.js 0.186.1. The maintainer
walked the three collector tasks in `webgl-inst`, the 2.5D `iso` renderer, and graph-explorer's
2D `d3` graph on 2026-10-23 and judged: "I like the 3D model, not the 2.5D." That choice decides
the renderer and overrides the first pass's cost argument for 2.5D (`gm-design-on0x` section
"The maintainer's judgment" and Verdict). The GO holds only with every condition below.

- **`webgl-inst`, not the mockup engine.** `webgl-inst` uses one `InstancedMesh` per plane and
  node kind, merged edge ribbons, labels only for label candidates, and vertical links rebuilt
  only when they change. At 20,000 unaggregated nodes it holds 120 fps in Chromium and
  Firefox and 59 fps in WebKit. The mockup engine gets 4.1 to 6.0 fps there
  (`gm-design-on0x` section "Frame rate, time to first frame, and labels", Recommendation 1).
- **Resolve picking.** Picking collects every hit along the ray and takes the node whose
  projected centre is nearest the pointer. The soloed plane, then the selected node's plane,
  breaks ties. It makes 153 of 153 drill-down targets clickable at their centre, against 150
  of 153 for nearest-hit picking, and raises off-centre hits from 97.4% to 99.8%
  (`gm-design-on0x` section "The three tasks", Recommendation 3).
- **A 3, 12, 16 per-view budget, with aggregation and paged drill-in.** The budget is credits,
  masters, and releases per plane. It is also `gm-design-1h2l`'s payload default. Larger
  discographies fold into count nodes, and opening one pages its members: 8 pressings per
  page (at most 12 hold) or 8 masters per page (at most 8 hold) (`gm-design-on0x` section
  "Node budget per plane, measured", Recommendation 2).
- **The footprint check runs after aggregation.** The budget is the request and the check is
  the guarantee. A count budget alone passes 8 of 336 configurations. With the footprint
  check on the spaced icicle, all 336 pass with zero hull intrusions, overlaps, and crossings
  (`gm-design-on0x` section "Node budget per plane, measured").
- **The planar edge rule.** Lateral edges are drawn only where they cannot cross. Every other
  edge stays in the panel and the table. The rule holds same-plane crossings at 0 at every
  scale and seed (`gm-design-on0x` section "The mockup's layout at real shape").
- **Invariants are tests.** Zero hull intrusions, overlaps, and same-plane crossings, and the
  conservation of every node across pages, are Vitest properties of a GPU-free layout module
  (`gm-design-on0x` Recommendation 2).
- **The table is a first-class view, not a fallback.** It lists every credit, lane, master,
  and pressing, folded or not, with path, year, state, and blocked reason. It is the only view
  that answers "which items cannot change state, and why" at every scale. At 5,000 nodes and
  above, reaching a folded pressing takes a median of 6 to 45 openings, so the view also gets
  a search-to-focus entry point and an "only what I collect" filter (`gm-design-on0x` sections
  "Accessibility" and "The three tasks", Recommendation 6).
- **Accessibility and CSP carry over from the harness.** Keyboard navigation of planes and
  nodes, `prefers-reduced-motion` for every camera tween, CSSOM instead of inline `style`
  attributes, no `eval` or `new Function`, and an importmap hash for any future policy
  (`gm-design-on0x` section "Accessibility", Recommendation 4).

The measured costs of the choice are accepted, not a reason to re-open it. Under the budget,
`iso` reaches its first frame sooner on desktop (12 to 61 ms against 67 to 116 ms), and it
needs no third-party file, against three.js's 418,036 B gzipped (`gm-design-on0x` Verdict and
section "Vendoring cost in graph-explorer").

The budget comes from plane depth against node size, not from the renderer. B and C′, drawn at
the mockup's proportions, also need the footprint check (`gm-design-on0x` Verdict).

### 2. Engine distribution: graph-explorer produces a pinned vendored module

graph-explorer produces the engine module. A consumer takes it as a pinned vendored copy with
a `source.json` that records `producer_repository`, `producer_commit`, and `sha256`, checked by
a digest assertion beside the consumer's contract checks. That is the pattern both
repositories already use for contracts and brand assets (`gm-design-on0x` section "Engine
distribution", Recommendation 8).

three.js itself is vendored separately in each consumer, with its own license entry. In
graph-explorer that means the importmap entry `"three": "/vendor/three.module.js"`, the
`vendor-assets.json` and `ASSET_LICENSES.json` entry, the build-script changes the spike
lists, and a `source.json` with sha256 digests for both files (`gm-design-on0x` section
"Vendoring cost in graph-explorer", Recommendation 5).

operations-console promotes the engine **only when a 3D concept D view is planned**, and only
after that plan settles the module-script question. three.js 0.186 ships as ES modules only,
and the console loads classic scripts with no import map or bundler. The plan must either adopt
the console's first `<script type="module">` with an import map, or add a bundled classic
build. It must also meet the console's seven constraints (`gm-design-on0x` section
"Operations-console constraints"; `gm-design-loj9` section 7). Concept D's first build is a
table or timeline, which needs no three.js.

### 3. Routes and stores

- **A: a Neo4j query in catalog-api at `/api/explore/strata`.** The ladder read is Neo4j, as
  Explore's `expand` is, and ADR 0012's 2026-10-02 amendment stands. For a signed-in caller the
  same read returns the caller's `COLLECTED` and `WANTS` edges with `date_added`. The budget
  defaults to 3, 12, 16, and every aggregate's id is a `focus` cursor for the next page
  (`gm-design-1h2l` sections 5 and 6, Recommendation 2). The spike drafted the path as
  `/api/strata/artist/{artist_id}`; this record places it under `/api/explore/`.
  - MusicBrainz-only releases are not in Neo4j. They join through a second, PostgreSQL read by
    native id first, then by release-group sibling. 462,111 of 3,977,395 (11.62%) attach to a
    master. The sibling path needs an index on `musicbrainz.releases (release_group_mbid)` in
    database-schema (`gm-design-1h2l` section 2, Recommendation 2).
  - Latency is GO under 10,000 releases (50 ms warm p95 or less). From 10,000 releases it is
    GO with a cache (541 ms warm p95, up to 2.5 s cold), like Explore's Valkey cache, or with a
    precomputed per-artist master summary. It is DEFER for roots above 134,051 releases, which
    were not measured. M2 chooses between a summary and refusing or capping the placeholder
    roots, and repeats the latency harness on the first deployment (`gm-design-1h2l` section
    5, Verdict, Recommendation 2).
  - At the 3, 12, 16 budget every payload is under 4.5 KB, the largest root's included
    (`gm-design-1h2l` section 6).
- **B: precomputed in analytics-engine, served by catalog-api at `/api/insights/style-atlas`.**
  analytics-engine computes style-by-year counts and the atlas layout as a job, through the
  internal-insights contract, into database-schema `insights.*` tables, as it already does for
  `insights.genre_trends`. The spike proposes `insights.style_year_counts(style, year,
  release_count, master_count, computed_at)`, about 50,000 rows, plus each style's dominant
  genre and parent set. Stages take 6 ms to compute from the counts, on either side
  (`gm-design-4804` section B5, Recommendation for B 1). M4 fixes the table names.
- **C′: the existing fit route, extended.** `evidence_items` carry entity ids, Bridge returns
  its genre list as a structured array, and the overlay receives the uncapped drawable entries
  (`gm-design-4804` Recommendation for C 3).
- **D: a PostgreSQL read, as a recorded exception.** The identity history lives only in
  PostgreSQL: alias validity windows, supersessions, and their audit rows. Neo4j holds the
  current `gm_id` projection and no history. The ledger routes are therefore read-only
  PostgreSQL queries behind `require_admin`, added to catalog-api's operations-console
  contract and re-promoted there (`gm-design-loj9` section 6, Recommendation 2). This is a
  deliberate departure from the rule that Strata graph reads are Neo4j queries. It does not
  move any graph read off Neo4j, and it does not reopen ADR 0012.

### 4. State vocabularies

**A: the collector machine, observed only.** A release is `none`, `wanted`, `owned`, or
`wanted + owned`. Every edge between them is observed at Discogs sync, and none is a control.
GrooveMap's only authored actions on a release node are "Record an observation" on an owned
copy and "Sync now". There is no wantlist or collection write, and the view must not imply
one. The mockup's "Add to wantlist" and "Mark as collected" become "Open on Discogs". A
MusicBrainz-only release shows no collector state. Masters and credits roll their state up
from their releases at read time, and "redundant want" is derived the same way
(`gm-design-1h2l` section 4, Recommendations 3 and 4). If GrooveMap is ever to author wants or
owns, that is a separate decision: a Discogs write integration or a first-party wantlist.
Strata cannot carry it.

**B: lifecycle stages over release-year counts.** The stages are absent, emerging,
established, reviving, and declining, computed causally from release-year counts so the atlas
can scrub valid time (`gm-design-4804` section B4).

- A style's parents are the genres with share ≥ 0.20, and the dominant parent is its home
  sector. Secondary parents get ghost copies counted in their host hull (`gm-design-4804`
  sections B1 and B2, Recommendation for B 2).
- Emergence is the first year with 25 cumulative releases, not `first_year`, in both the
  lifecycle and the "emerges after its parent genre" rule (`gm-design-4804` section B4,
  Recommendation for B 6).
- The latest two years are marked provisional, because their counts still grow 0.8% to 1.4%
  a month (`gm-design-4804` section B4, Recommendation for B 5).
- The rule and its thresholds are shown on screen.
- The layout is the pinned geography layout: a genre ring in maximum-overlap order, sectors
  pinned from the previous month, and styles inside their sector. Lateral edges are drawn on
  demand, for the selected node only (`gm-design-4804` sections B2 and B3, Recommendation for
  B 3 and 4). M4 chooses the in-sector placement from the measured trade-off.

The rule flips 0.54% of styles between consecutive dumps against a 2% bar, and at most 4.69%
under any ±10% threshold change against a 10% bar. The layout has 0 intrusions, 0 omissions,
and a p95 monthly movement of 0.69 nearest-neighbour distances (`gm-design-4804` Verdict B).

**C′: what Fit can draw honestly.** On the atlas, Affinity is drawn as the shared genre and
style nodes, style and genre Novelty as the candidate's unheld style nodes, Bridge as the edge
between genre hulls, and Redundancy as the owned sibling under the same master. Depth and
artist or label Novelty are listed beside the map, not placed on it. A held item lands on
every style it carries, never at a centroid. Collector masters take deterministic slots in
their dominant style cell, computed with B's layout. Masterless items use concept A's "no
master" container (`gm-design-4804` sections C1 and C2, Recommendation for C 1, 2, and 4).

**D: identity states over transaction time.** An edition is `not_recorded`, `discogs_only`,
`musicbrainz_only`, `unresolved`, `split`, or `linked`, and a former item is `superseded`.
The history has one recorded repair transition: re-attachment, `split` to `linked` with the
former item superseded (`gm-design-loj9` section 4).

- **Primary parent.** 30.15% of cross-linked editions have two work parents. An edition's
  primary parent is its Discogs master, because the survivor is always on the Discogs side. The
  second parent is drawn as an explicit cross-hull `work_disagreement` edge
  (`gm-design-loj9` section 5; `gm-design-on0x` section "Operations-console constraints").
- A linked edition is one node with its two provider rows as halves, not two nodes joined by
  an edge.
- The mockup's lateral "same identifier" edges are dropped, because history cannot supply
  them. Its Discogs-side `superseded` state is dropped, because the code cannot produce it
  (`gm-design-loj9` sections 4 and 5, Recommendation 2).

### 5. Bi-temporal semantics

- **Valid time is the release year**, the first four characters of `released` kept inside
  [1860, dump year + 1]. For A, a release without a year takes its master's (`gm-design-1h2l`
  section 1.1 and Method). B's stages are computed over release year, which is steadier than
  master year: 0.54% against 1.69% flips (`gm-design-4804` section B4).
- **Transaction time for A and C′ is the collector's recorded `date_added`.** Discogs keeps it,
  and the sync copies it onto `user_collections`, `user_wantlists`, and the `COLLECTED` and
  `WANTS` edges. A "recorded as of" control replays ownership from `collection_snapshots` and
  wants from the sync's `activity.events`, which are the only record of a removal
  (`gm-design-1h2l` section 3). The upsert used to erase a recorded `date_added` when a later
  sync omitted it. That was fixed on 2026-10-23 on catalog-api `main`, separately from M2, at
  commit `32fa959` (`gm-catalog-api-2m5f`), as `gm-design-1h2l` Recommendation 2 asked.
- **Transaction time for D is GrooveMap's recorded time**: alias `valid_from` and `valid_to`,
  and supersession intervals. Work-to-edition edges have no transaction time, because loaders
  overwrite the provider rows, so `work_disagreement` is a current-state fact
  (`gm-design-loj9` section 5).

### 6. Data rules

- **The master `"0"` sentinel never reaches a strata read.** Discogs writes `0` for "no
  master". On the predecessor graph one fake master held 8,156,478 `DERIVED_FROM` edges, so a
  strata read would draw 41.8% of all releases under it (`gm-design-1h2l` section 1.4). It was
  fixed at its source on 2026-10-23, as `gm-design-1h2l` Recommendation 1 asked, not filtered
  in the strata query: discogs-graph-enricher commit `0bc0529`
  (`gm-discogs-graph-enricher-784`) drops `"0"` at projection, and a post-import cleanup
  deletes the `Master {id: "0"}` node and its edges.
- **Masterless and undated lanes are first-class.** 41.6% of releases have no master, and
  7.8% have no year even after the master's. The no-master lane is one node per credit on the
  master plane and never folds into a decade bucket. The undated lane is a strip at the left
  edge of every plane's year axis. Both are part of the route contract, not fallbacks
  (`gm-design-1h2l` section 1.1 and Verdict; `gm-design-on0x` Method and Recommendation 2).
- **Nothing uses edition candidates while ADR 0014 section 6 stands at DEFER.** No Strata
  concept reads or depends on a matching schema. Concept D's history-only ledger needs none
  (`gm-design-loj9` section 4). Candidates join D as a later layer only after a section 6
  re-run returns GO, by amendment to this record.
- **Personal layers stay out of shareable snapshots.** A collector's items, states, and
  recorded times never appear in a view that can be shared (`gm-design-4804` Recommendation
  for C 5).
- **Discover outcomes follow ADR 0010 consent.** Saves, dismissals, and hides are activity
  outcomes against an impression a recommendation or fit surface recorded. They are never
  collector state (`gm-design-1h2l` section 4, row 11; `gm-design-4804` Recommendation for
  C 5).

### 7. Concept D: GO, with the backfill branch pending

`gm-design-loj9` measured the history-only ledger as DEFER: a replay over two real dumps gave
743 works with editions changing in more than one month, against a bar of 1,000, on a
MusicBrainz interval of only four days. That DEFER stays as the record of the four-day window.
On 2026-10-23 the maintainer decided: "Please do not DEFER D. Let's change that to a GO"
(`gm-design-7xo5` comment of 2026-10-23). D is therefore GO as a history ledger whose first
build is a table or timeline.

The verdict no longer depends on further measurement. One branch is still open:
**backfill-from-fullexport or forward-only**. Follow-on spike `gm-design-6b8u` (epic
`gm-design-cgh9`) decides it with its out-of-sample run on the MusicBrainz full export
(`gm-design-7xo5` comment of 2026-10-23). M6 is filed by `/bh:replan` when `gm-design-cgh9`
finishes, and the branch is recorded here by amendment.

The branch is decided. The [2026-10-24 amendment](#2026-10-24-concept-ds-backfill-branch-and-m6)
records it, and this section is otherwise unchanged.

### Rejected alternatives and conditions for revisiting

- **2.5D (`iso`) for concept A.** Rejected by the maintainer's judgment of 2026-10-23. It is
  faster to first frame and needs no third-party file, and it reaches the same targets in the
  same number of openings. Firefox's Canvas 2D is its slow path: 8.6 fps at 5,000 and 1.3 fps
  at 20,000 unaggregated nodes (`gm-design-on0x` sections "Frame rate, time to first frame,
  and labels" and "The maintainer's judgment"). The spike records that its cost figures were
  weighed and are not a reason to re-open the choice.
- **The mockup engine, or graph-explorer's 2D `d3` graph.** The mockup engine gets 4.1 to 6.0
  fps at 20,000 nodes. The 2D graph gets 2.0 to 4.3 fps, and its force layout leaves 6 of 24
  default-drawn targets clickable at their centre (`gm-design-on0x` sections "Frame rate, time
  to first frame, and labels" and "The three tasks").
- **A node-count budget without the footprint check.** It passes 8 of 336 configurations, and
  every drill-down page size breaks it (`gm-design-on0x` section "Node budget per plane,
  measured").
- **Live lifecycle in catalog-api.** The style-by-year aggregation takes about 30 s on a full
  graph. The logged genre-trends path has a p90 of 49.0 s, a tail to 109.5 s, and 20 runs
  that failed with HTTP 503, against catalog-api's own 30 s genre-tree timeout. The answer
  changes once a month (`gm-design-4804` section B5, Recommendation for B 1). Revisit if the
  first full production load's style-by-year Cypher runs well under a second.
- **`graph.part_of` for hulls and emergence.** One single-genre document adds a parent, so
  89.6% of styles have two or more, and 445 of 757 have five or more. Under it, 274 styles
  break the emergence edge rule, against 5 under the dominant parent (`gm-design-4804` sections
  B1 and B4).
- **Co-occurrence or embedding layouts for the atlas.** Both hold still between dumps, but
  they place 48% to 62% of styles inside another genre's hull. They suit a similarity overlay,
  not the atlas (`gm-design-4804` section B3).
- **Full concept C as mocked.** Depth is 0% drawable, and 71.9% of scored Novelty has nothing
  to draw. Placing them would invent positions (`gm-design-4804` section C2, Verdict C).
  Revisit Depth or artist and label Novelty only if the atlas gains an artist or label plane.
- **A published engine package, or separate implementations.** No GrooveMap JavaScript package
  or npm publishing path exists, and the console has no vendor pipeline. Separate
  implementations would each need their own proof of the layout invariants (`gm-design-on0x`
  section "Engine distribution").
- **D's ledger on Neo4j.** Neo4j holds no identity history (`gm-design-loj9` section 6).

## Consequences

Each Strata molecule builds on fixed decisions: what is drawn, in which state vocabulary, on
which clocks, computed where. The costs are accepted: a 2,120,885 B raw three.js copy in each
consumer that draws 3D, a second PostgreSQL read in A's route for MusicBrainz-only releases, a
monthly analytics-engine job and insights tables for B, a fit-route contract change for C′,
and a recorded exception to the Neo4j rule for D.

Color as state needs tokens that do not collide with entity-type colors, because today's
Explore palette uses green for artist. Sibling bead `gm-design-17td` adds them to
`brand/tokens.json`. The program document, `docs/programs/strata.md` (`gm-design-8qcl`),
tracks delivery across repositories.

Repositories affected:

- **catalog-api** owns `/api/explore/strata` (M2), `/api/insights/style-atlas` (M4), the fit
  route change (M5), and the admin identity-ledger routes (M6).
- **graph-explorer** owns the engine module, the vendored three.js, concept A in Explore (M3),
  the Genre Atlas (M4), and Taste Strata and the Fit landing point (M5).
- **analytics-engine** owns the lifecycle and atlas-layout precompute (M4).
- **database-schema** owns the insights tables (M4) and the `release_group_mbid` index (M2).
- **operations-console** owns the ledger screen (M6), and promotes the engine only when a 3D
  view of D is planned.

### Open questions

These were not settled by the evidence, and this record does not guess them. Those marked
decided are closed by an amendment below:

- **D's backfill branch.** Settled by the 2026-10-24 amendment: backfill from the full export,
  then record live. It is no longer open.
- **Roots above 134,051 releases.** Their strata read was not measured at GrooveMap's size.
  M2 chooses a per-artist summary or a refusal or cap, and re-measures on the first deployment.
- **B's transaction time.** Decided by the [2026-10-24 amendment](#2026-10-24-activity-surface-dominant-style-and-atlas-history):
  the Genre Atlas shows the latest computation only, with no control over its monthly
  `computed_at` recomputations.
- **A strata activity surface.** Decided by the [2026-10-24 amendment](#2026-10-24-activity-surface-dominant-style-and-atlas-history):
  there is none for now. `taxonomy/events/v1` keeps ADR 0010's closed vocabulary.
- **Taste Strata's dominant style.** Decided by the [2026-10-24 amendment](#2026-10-24-activity-surface-dominant-style-and-atlas-history): the rule is
  confirmed as built, and it is stated there.
- **Real devices and real collections.** No real phone, mid-range laptop, or real user
  collection was measured. C′'s real-user validation stays DEFER (`gm-design-on0x` and
  `gm-design-4804`, "Missing evidence").

## Amendments

### 2026-10-24: Concept D's backfill branch and M6

Section 7 left one branch open: backfill-from-fullexport or forward-only. Follow-on spike
`gm-design-6b8u` (epic `gm-design-cgh9`) decided it, and this amendment records the result.
Sections 1 to 7 above stand as accepted. This amendment adds to section 7 and does not
replace any of it.

- **The branch is backfill from the full export.** The spike registered a dating proxy
  before it read any data. Proxy 1 failed its bar (precision 0.8223 against 0.90) and is not
  used. Proxy 2 was registered after that failure, has no free parameter, and was scored on
  the unseen 20261021 to 20261024 window (out of sample). Its precision was 0.912 and its
  recall 0.9771, against a bar of 0.90 for each. It clears the precision bar by 1.2 points.
  Each Discogs link is dated by the proxy's row-id creation bound, which gives the ledger the
  past 12 or more months on its first day (`gm-design-6b8u` Verdict and Recommendation 1).
  The forward-only plan was the fallback had the check failed, and it is not taken.
- **The DEFER of `gm-design-loj9` stands for its four-day window.** On 12 real months,
  proxy 2 gives 12 of 12 months with a writing run, 35,434 works with evented editions
  changing in two or more months, and 35,467 release re-attachments, against bars of 2, 1,000,
  and 1,000. These are lower bounds. The maintainer's GO of 2026-10-23 stands, and the rule
  fixed in advance now gives the same answer.
- **Backfilled events carry a provenance label.** About 9% of the links proxy 2 dates into a
  period are older links whose rows MusicBrainz replaced. The backfill therefore labels its
  events "dated from the MusicBrainz full export", not "recorded". The label lets a reader tell a
  dated event from a recorded one.
- **From the first load, live recording at load.** Link changes are recorded when
  `musicbrainz-sql-loader` loads a dump, and those diffs are exact. The maintainer decided on
  2026-10-24 that recording happens at load, not in a later job.
- **The first build is a table.** The first console screen is a paged table of works with
  their editions' identity events in transaction time, plus a per-month density strip. It uses
  `gm-design-loj9`'s state vocabulary and draft `admin_identity_ledger_*` routes. A layered
  Strata view comes later.
- **Unchanged.** The PostgreSQL-route exception for D, recorded under the routes and stores
  decision, stands as written. Edition candidates stay out while section 6 of ADR 0014 stands
  at DEFER. The console keeps classic scripts only.

M6 is filed as five epics, one per repository. The cross-repository order is held by
kickoff, not by bead dependencies, and the program document
[`docs/programs/strata.md`](../programs/strata.md) lists the epics, their order, and which
kickoffs are held.

Open questions after this amendment: the backfilled links' older months are lower bounds
because links removed since they were added are missing, and proxy 2 was scored on two short
windows (4 days in sample and 3 days out of sample). Both are recorded in `gm-design-6b8u`
"Missing evidence and failure modes".

### 2026-10-24: Activity surface, dominant style, and atlas history

The maintainer walked three of the open questions above on 2026-10-24 and decided each. The
decisions add to this record and replace none of its text. Each carries the condition under
which it is revisited, so later work does not reopen it by accident.

- **No Strata activity surface for now.** `taxonomy/events/v1` keeps ADR 0010's closed
  vocabulary. Strata nodes record no engagement events of their own, and Discover outcomes on
  a strata node stay as section 6 states them: activity outcomes against an impression a
  recommendation or fit surface recorded, never collector state. *Revisit* only when a
  concrete analytics or Discover need on Strata exists. Adding a surface then changes ADR
  0010's vocabulary and needs its own decision.
- **The dominant-style rule is confirmed exactly as built.** Taste Strata places a collector
  master in a style cell by this rule (`gm-graph-explorer-0av`):
  1. A landmark master uses its best-ranked landmark style.
  2. Any other master uses, among its drawn styles, the style in which this collector holds
     the most items. Ties are broken by style name.

  Positions therefore depend on the viewer's collection. That suits a personal layer, which
  never appears in a shareable snapshot (section 6). *Revisit* if Taste Strata is ever drawn
  in a view that is shared or compared between collectors, because then a viewer-dependent
  position stops being a fit.
- **The Genre Atlas shows the latest computation only.** It offers no control over the
  monthly `computed_at` recomputations and no comparison between months. *Revisit* if users
  ask to compare months.
