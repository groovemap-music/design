# Spike: genre and style lifecycles and taste projection for Strata concepts B and C

Status: **B GO**, under the conditions in its Recommendation. **C NO-GO as mocked up.**
Only three of the five Fit components, plus style-level novelty, can be drawn on the
atlas without inventing positions.  
Evidence date: 2026-10-23  
Spike: `gm-design-4804` (epic `gm-design-uq8t`)  
Harness: [gm-design-4804/](gm-design-4804/README.md)  
Related: [ADR 0010](../adr/0010-first-party-events-consent-and-deletion.md),
[ADR 0012](../adr/0012-postgresql-property-graph-migration.md),
[ADR 0013](../adr/0013-pgvector-catalog-embeddings.md)

## Question

Concept B, the Genre Atlas, draws genres, then styles, then landmark masters in a
cluster layout. Each style is coloured by a lifecycle stage over valid time. Concept C,
Taste Strata and the Fit landing point, overlays a collector's items and a candidate
record's five Fit components on B's map.

- **B:** can the lifecycle stages and the cluster layout come from catalog data stably
  enough to show as fact? This covers four things: which genre a style belongs under,
  how stages are defined, how stable they are, and which layout source holds still
  between dumps.
- **C:** can C place a collector's items and a candidate's Affinity, Novelty, Bridge,
  Depth, and Redundancy on that atlas without inventing positions?

## Method

Two consecutive Discogs monthly dumps, `20260901` and `20261001`, were each streamed
once and never written to disk. The masters dumps were cached once in the shared spike
cache. Fetching followed the shared lock and back-off convention in the
[harness README](gm-design-4804/README.md#shared-fetch-convention). One pass per dump
keeps year, master, genres, styles, main artists, and labels as integer arrays. From
those come style x genre, style x year (release year and master year), style
co-tagging, the product's `graph.part_of` rule, and graphinator's `first_year`. Every
number below is in `results/` and is reproduced by the README's commands.

The existing routes were read in catalog-api and analytics-engine. Each route's
relevance:

| Route | What it returns today | What B or C needs from it |
| --- | --- | --- |
| `/api/genre-tree` | Every genre with every style that co-occurs on any release, counted live with a 30 s Cypher timeout | A parent rule, not just co-occurrence |
| `/api/explore/genre-emergence` | `first_year` per genre and style (minimum release year > 0) | A lifecycle, not just a first sighting |
| `/api/insights/genre-trends` | Genre x decade release counts, precomputed by analytics-engine into `insights.genre_trends` | Style x year counts (decades and genres are too coarse) |
| `/api/user/taste/*` (heatmap, fingerprint, card, blind spots) | Genre x decade, top genre per year, top labels | Nothing at style level. The style folding lives in the fit route's collection read |
| `/api/fit/release/{id}` | Five scored components with `evidence_items` (`dimension`, `entity`, `kind`), capped at 3 per component | Evidence that maps to atlas nodes and edges |

Concept C uses **synthetic collectors only**. GrooveMap has never been deployed, so no
real user data exists, and none was read under ADR 0010 or otherwise. The 120
synthetic collectors come in sizes 50, 300, and 2,000. Each draws 80% of its items from
one to three seed styles, weighted by style size, and the rest uniformly from the
20261001 catalogue. Each collector receives 30 candidates: 10 in-taste, 10 from the
seed's strongest co-tagged style, and 10 random. That is 3,600 Fit evaluations. They
are scored by a copy of `cratefit_v0`'s evidence rules (`scripts/taste.py`).

**Predecessor-schema measurements.** For cost only, the maintainer authorized read-only
queries against the predecessor deployment, which ran an earlier version of GrooveMap's
schema. On the predecessor's full graph, the measured query reads the same `Release`,
`Style`, and `Genre` labels, the same `IS` relationship, and the same `Release.year`
property as catalog-api's queries. The predecessor has RANGE indexes on `Release.year`
and on `Genre`/`Style` `first_year`. A whole-graph aggregation uses none of them. The
predecessor lacks GrooveMap's `Medium`/`ISSUED_ON`, which no measured query reads. Every
number from it is labelled as a predecessor-schema measurement. Live GrooveMap services
do not exist.

## Evidence

Both dumps hold 757 styles and 16 genres, with identical name sets. Releases number
19,417,067 (0901) and 19,492,392 (1001). Of the 1001 releases, 84.7% have a style and
25.5% carry two or more genres. As a cross-check, this harness's genre x decade counts
agree with the predecessor's stored `insights.genre_trends` (the same Cypher catalog-api
runs) to a median of 0.08%, and to 0.21% at p90 on cells with at least 10k releases
(`results/predecessor_crosscheck.json`).

### B1. Multi-parent styles

`share(s, g)` is the fraction of style s's releases that also carry genre g. A style's
parents are the genres at or above the stated share. Because releases carry several
genres, shares do not sum to one.

| Rule | Styles with 2+ parents | Release-weighted | Secondary (style, genre) pairs |
| --- | ---: | ---: | ---: |
| `graph.part_of` (any single-genre document) | **89.6%** (mean 6.5 parents) | 99.6% | — |
| share >= 0.05 | 82.8% | 80.0% | 2,026 |
| share >= 0.10 | 69.8% | 71.8% | 1,112 |
| **share >= 0.20 (stated)** | **46.0%** | **41.7%** | **470** |
| share >= 0.30 | 28.8% | 28.3% | 256 |

- The dominant parent is clear-cut. Its median share is 0.992, and its 10th percentile
  is 0.892. Among multi-parent styles at 0.20, the mean split is 0.93 for the top
  parent and 0.40 for the second, and 91 styles have three or more parents.
- Between dumps, 1 style changed dominant parent and 6 changed parent set at 0.20.
- **`graph.part_of` cannot define hulls.** One single-genre document is enough to add a
  parent, so 445 of 757 styles have five or more parents. The mockup's "PART_OF"
  hulls and its emergence edge rule both have to move to the share rule.

### B2. Placement rule, by hull intrusions and crossings

Measured on the geography layout of the later dump, with the ring pinned from the
earlier one, at share 0.20. The L1 edges are each style's top 3 co-tagged styles by
lift, with at least 50 shared releases: 1,428 edges. An intrusion is a drawn node
inside the hull of a genre that is not one of its parents. An omission is a (style,
parent) pair with no drawn copy inside that parent's hull, which breaks the cylinder
property.

| Rule | Drawn nodes | Intruding nodes | Omitted parent pairs | Edge crossings | Edges through a foreign hull |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dominant parent | 757 | 0 | 470 of 1,227 | 21,577 | 52 |
| **Ghost copies** | 1,227 (470 ghosts) | **0** | **0** | **11,976** | **8** |
| Shared border region | 757 | 0 | 306 | 21,218 | 59 |

**Ghost copies win on every hull and crossing measure.** The border rule reaches only
parents that are adjacent on the genre ring, and 306 pairs are not. Ghosts cost 62% more
L1 nodes at 0.20, or 34% at 0.30.

No rule reaches zero crossings. Within a single hull, the ghost layout still has 10,099
crossings among 1,363 intra-hull edges. When each sector is placed by co-tag MDS
instead (below), the total is 5,722, of which 4,152 are intra-hull. The engine's "no
same-plane crossing" property cannot hold for the full L1 co-tag edge set. Lateral
edges have to be drawn on demand, meaning the selected node's edges only, which is a
star and has no crossings.

### B3. Layout source and stability

Stability is measured from 0901 to 1001. Displacement is in units of the earlier
layout's median nearest-neighbour distance (NN). The two free layouts are first
Procrustes-aligned (rotation, reflection, scale), which is their best case.
The stability bar: p95 displacement no more than 1 NN, and no more than 5% of styles
moving more than 1 NN.

| Source | Intruding nodes | Omitted pairs | p95 displacement | Styles moving > 1 NN | kNN-10 Jaccard |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Geography (pinned ring, ghosts, lean x emergence ranks)** | **0** | **0** | **0.69** | **1.7%** | **0.921** |
| Geography, ghosts, co-tag MDS inside each sector (frame pinned) | 0 | 0 | 1.13 | 5.9% | 0.893 |
| Co-occurrence (Hellinger co-tag MDS) | 467 (62%) | 228 | 0.55 | 2.0% | 0.910 |
| FastRP artist vectors averaged up to styles, then PCA | 363 (48%) | 280 | 0.41 | 1.5% | 0.935 |

- **All three sources hold still between dumps. Only geography respects the hulls.**
  Co-occurrence and the embedding place 48-62% of styles inside another genre's hull,
  because similarity and genre membership disagree.
- The genre ring order, an exact maximum-weight cycle over genre overlap, did not change
  between dumps. The widest sector is 45 degrees, so convex hulls never wrap.
- One style changed its dominant genre and jumped sectors (max displacement 10 NN).
  That is the expected cost of a month in which the data really changed.
- The embedding numbers come from a **reconstruction**, `scripts/fastrp.py`, built to
  the documented production configuration. It uses 128 dimensions, weights 0,1,1,1,1,
  self 0.05, and a keyed Achlioptas projection. It covers the edge relations the arrays
  carry and omits edges-v3's credited and track-level artists: 26.3M nodes and 244-245M
  adjacency entries per dump. The production vectors in `public.artist_embeddings`
  were not reachable. Because the projection is keyed, style vectors compare directly
  across dumps: median cosine 1.0000, p05 0.9997. Each rebuild takes 20-29 minutes, with
  a peak RSS of 7.4-13.4 GB (`results/fastrp_*.json`).

### B4. Lifecycle rule and its stability

The rule (`scripts/lifecycle.py`) is causal, so the stage in year y reads only years up
to y and the atlas can scrub valid time. Let c(y) be the 3-year trailing mean of yearly
releases, P(y) the running peak of c, T(y) the trough since the style was last active,
and y0 the first year with at least 25 cumulative releases.

| Stage | Condition |
| --- | --- |
| absent | y < y0 |
| emerging | c >= 0.5 P and y - y0 < 10 |
| established | c >= 0.5 P and y - y0 >= 10 |
| reviving | c < 0.5 P, c >= 1.5 T, and c >= 0.25 P |
| declining | otherwise |

The stated bar was fixed before the real-data run. **A rule is not a GO if more than 2%
of styles change stage between consecutive dumps, or more than 10% change under any
single ±10% threshold change.**

| Basis | Flip between dumps, 2025 | Flip, 2024 | Flip, all style-years 1950-2025 | Worst ±10% threshold change, 2025 | Worst ±10%, all style-years |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Release year** | **0.54% (4 styles)** | 0.67% | 0.70% | **4.69%** (`active_share` x0.9) | 4.11% |
| Master year | 1.69% (12 styles) | 1.13% | 0.94% | 4.65% (`active_share` x1.1) | 4.13% |

**Release-year lifecycle passes both bars.** Master year passes too, with less margin.
`active_share` is the only threshold above 2%. The other four stay at or below 1.5%
(`results/atlas.json`).

- **Recent years are provisional.** Catalogue entry lags release. In one month, 2025's
  tagged count grew 1.39% and 2024's grew 0.78%, while 2019-2021 grew 0.17-0.24%. Tagged
  releases per year peak in 2020 and fall every year after, because of lag rather than
  music. In 2025, 410 of 757 styles read "declining", against 376 in 2015 and 2020.
- **`first_year` is not an emergence date.** For 46.6% of styles, graphinator's
  `first_year` comes more than 10 years before the 25-release emergence year (median
  gap 9 years). Single mis-dated releases set it. It changed for 44 styles between
  dumps, against 34 for the emergence year.
- **The mockup's edge rule** says a style cannot emerge before every parent genre has.
  Under `graph.part_of`, 274 styles (36%) break it, against 5 under the dominant parent.

### B5. Where lifecycle is computed: measured cost

| Measurement | Value |
| --- | --- |
| Release-style tags a style-by-year aggregation reads (1001 dump) | 29.6M (26.4M dated in the predecessor graph) |
| Output | 49,525 non-empty style-year cells through 2025 (125,662 dense rows) |
| Predecessor Neo4j, style-by-year aggregation, full graph, warm, 2 runs | **32.2 s wall time each**. Helper round trip 1.56 s, so about 30.6 s of query (`results/predecessor_neo4j.json`) |
| Predecessor Neo4j, the genre-trends Cypher, same session | 31.9 s |
| Predecessor production log, 142 genre-trends runs, 2026-05-27 to 2026-10-22 | p50 30.1 s, p90 49.0 s, max 109.5 s. **20 further runs failed with HTTP 503** (`results/predecessor_costs.json`). Durations include API overhead |
| Harness, the same aggregation from compact arrays | 9-17 s per dump (aggregate.py, all aggregates together) |
| Stage computation from yearly counts | 6 ms for 757 styles x 166 years |
| How often the answer changes | Once per dump (monthly). 0.54% of stages move per dump |

A cold run could not be separated, because the predecessor's own scheduled genre-trends
job had run that day.

### C1. Placing the collector's items

Across 94,000 synthetic held items (`results/taste_20261001.json`):

| Plane | Placeable from catalog data | Note |
| --- | ---: | --- |
| L0 genre | 100% | 3.1% are genre-only (no style), so they land on L0 only |
| L1 style | 96.9% | An item lands on 2.36 style nodes on average. 24.9% land in two or more genre hulls at once |
| L2 master | 61.9% have a master | **Only 4.35% are among B's landmark masters** (top 25 per style, 15,125 masters) |

Items are placed on genre and style nodes, never at invented positions. A held item
lands on every style it carries. A centroid would be an invented position. L2 is
different. B shows landmark masters only, so 95.6% of held masters have no position on
B's map. C needs a deterministic per-master rule, for example inside its dominant style
cell, ordered by year. Masterless releases (38.1%) need concept A's synthetic "no
master" container.

### C2. Mapping the five Fit components onto the atlas

A Fit evidence entry is drawable when it names a genre or style node (a position), a
pair of genre hulls (an edge), or a release whose master is on L2. Artists and labels
have no plane on the atlas.

| Component | Scored (> 0) | Entries that are positions or edges | Scored evaluations with any drawable evidence | Gap |
| --- | ---: | ---: | ---: | --- |
| **Affinity** | 99.4% | 86.3% | 99.8% | 60% of the weight (artist 0.35, label 0.25) is not drawable. On average 83.5% of an affinity score comes from genre and style |
| **Novelty** | 94.4% | 17.5% | **28.1%** | **82.5% of entries are new artists or labels. 71.9% of scored novelty has nothing to draw**, and the 3-entry cap hides the drawable part in a further 5.9% |
| **Bridge** | 27.6% | 100% (the genre pair; the second entry is the caveat sentence) | 100% | The rendered genre list parsed back unambiguously against the 16 known genres in every case, even with a genre whose name contains commas. The "no shared artist or label" condition is not visible |
| **Depth** | 35.9% | **0%** | **0%** | Depth is artist and label threads only. The mockup's "a column you have already started" is not what Depth measures |
| **Redundancy** | 1.0% | 94.6% | 94.6% | Title-only duplicates (no master) have no position |

Affinity, Bridge, and Redundancy map onto atlas positions and edges. Novelty maps only
for its style and genre part. Depth does not map at all.

## Verdict B: GO

The lifecycle can be derived and shown as fact, and so can a stable, hull-correct atlas
layout:

- Lifecycle over release-year counts flips 0.54% of styles between consecutive dumps
  (bar 2%) and at most 4.69% under any ±10% threshold change (bar 10%).
- The pinned geography layout with ghost copies has 0 intrusions and 0 omissions. It
  moves 1.7% of styles by more than one nearest-neighbour distance per month (p95 0.69
  NN). It also has the fewest crossings and foreign-hull edges of the three placement
  rules.

The conditions are in the Recommendation: the share rule instead of `graph.part_of`,
provisional recent years, and edges drawn on demand.

## Verdict C: NO-GO as mocked up

C promises that "Fit's five components become things you can see". That holds for
Affinity, Bridge, and Redundancy. It does not hold for Depth (0% drawable) or for most of
Novelty (71.9% of scored cases have nothing on the map), and drawing them would invent
positions. Collector items do place honestly on L0 and L1. L2 needs a per-master
position rule beyond B's landmarks. A reduced C is buildable on this evidence. Real-user
validation is **DEFER**: no real collections exist.

## Recommendation

**For B (M4):**

1. **Compute lifecycle in analytics-engine, as a precompute into a database-schema
   insights table**, the existing `genre_trends` pattern, not live in catalog-api.
   - The query takes about 30 s on a full graph, with a logged tail to 110 s. That is
     already at catalog-api's own 30 s genre-tree timeout, and the logged predecessor
     path failed 20 of 162 times.
   - The answer changes once a month, while requests come per page view.
   - Proposed table: `insights.style_year_counts(style, year, release_count,
     master_count, computed_at)`, about 50k rows, plus the dominant genre and parent
     set per style at share 0.20.
   - Stages can be computed from it by analytics-engine or by catalog-api on read: 6 ms
     for every style and year.
   - **First-deployment check:** on the first full production load, time the
     style-by-year Cypher (`scripts/predecessor_neo4j_timing.sh` runs it unchanged).
     Confirm it fits analytics-engine's default 900 s read budget, and confirm the
     catalog-api read of the table serves under its route budget. If the Cypher instead
     runs well under a second, revisit live.
2. **Parents:** use share >= 0.20 with the dominant parent as the home sector. Do not
   use `graph.part_of` for hulls or for the emergence edge rule. Draw ghost copies under
   secondary parents, counted as members of their host hull.
3. **Layout:**
   - Use the geography layout: a genre ring in exact maximum-overlap order, sectors
     sized by the square root of membership, and styles inside their sector.
   - Pin the ring order and each sector's frame from the previous month, and recompute
     monthly.
   - In-sector placement is a measured trade-off for M4's renderer: lean x emergence
     ranks are steadier (p95 0.69 NN), while co-tag MDS halves crossings (11,976 down to
     5,722) at p95 1.13 NN.
   - The embedding and co-occurrence layouts are stable but break hulls for about half
     the styles, so they suit a similarity overlay, not the atlas.
4. **Lateral edges on demand:** no layout makes the L1 co-tag set crossing-free.
5. **Stage display:**
   - Show the rule and its thresholds on screen, as the mockup's risk note asks.
   - Mark the latest two years provisional, because their counts still grow
     0.8-1.4% a month.
   - Use release year for the stage. It is more stable than master year: 0.54% against
     1.69% flips.
6. **Emergence:** use the 25-release emergence year, not `first_year`, in both the
   lifecycle and the "emerges after its parent genre" rule.

**For C (M5), replan to the reduced scope:**

1. On the atlas:
   - Affinity, drawn as the shared genre and style nodes.
   - Style and genre Novelty, drawn as the candidate's unheld style nodes.
   - Bridge, drawn as the edge between genre hulls.
   - Redundancy, drawn as the owned sibling under the same master.
2. Beside the atlas, as a list rather than positions: Depth (artist and label threads)
   and artist or label Novelty.
3. **Fit route change:**
   - `evidence_items` must carry entity ids. Artists and labels are named by display
     name today.
   - Bridge needs the genre list as a structured array, not the rendered
     "A, B and C" string.
   - The overlay needs the uncapped drawable entries. The 3-entry cap hides drawable
     Novelty in 5.9% of scored cases.
4. **L2 positions:** a deterministic per-master rule inside the dominant style cell,
   computed with B's layout, so collector masters (95.6% of them non-landmark) never get
   ad hoc positions.
5. Keep personal layers out of shareable snapshots, and keep Discover outcomes under
   ADR 0010 consent, as the mockup states.

## Missing evidence and failure modes

- **Production artist vectors.** The embedding arm is a reconstruction with a reduced
  edge set. Its stability matches analytics-engine's measured month-over-month behaviour
  in spirit, not bit for bit. It changes no decision: the embedding loses on hull
  intrusions, not on stability.
- **Cold Neo4j timing.** Only warm runs could be timed. The predecessor's 142 logged runs
  bound the tail.
- **Real collections.** None exist, so C's numbers come from synthetic collectors.
  Their focus (80% from seed styles) shapes the Bridge and Depth rates. It does not
  shape what is drawable, which follows from the evidence kinds.
- **Two dumps, one pair.** Stability is measured on one consecutive pair. A third dump
  would show whether 0.54% is typical.
- **Landmark rule.** 25 masters per style by release count is this spike's choice. The
  L2 conclusion, that most collector masters are not landmarks, holds for any small
  per-style landmark set.

## Sources

- catalog-api: `api/routers/explore.py` (`/api/genre-tree`, `/api/explore/genre-emergence`),
  `api/queries/genre_tree_queries.py`, `api/queries/neo4j_queries.py`
  (`get_genre_emergence`), `api/queries/insights_neo4j_queries.py` (`query_genre_trends`),
  `api/routers/taste.py`, `api/queries/taste_queries.py`, `api/fit.py`,
  `api/routers/fit.py`, `api/queries/fit_queries.py`.
- analytics-engine: `insights/computations.py`, `docs/architecture.md`,
  `docs/embeddings.md`, `docs/recall_and_churn.md`.
- database-schema: `src/groovemap_schema/postgres.py` (`graph.part_of`,
  `insights.genre_trends`). discogs-sql-loader: `tableinator/graph_counters.py`.
  discogs-graph-enricher: `graphinator/graphinator.py` (`compute_genre_style_stats`).
- Discogs monthly dumps `20260901` and `20261001` (releases streamed, masters cached).
- The predecessor deployment's PostgreSQL `insights.computation_log` and
  `insights.genre_trends`, and its Neo4j graph, read-only and maintainer-authorized.
