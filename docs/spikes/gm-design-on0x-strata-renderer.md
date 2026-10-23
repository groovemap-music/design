# Spike: concept A's strata renderer at catalog scale

Status: **GO on a 3D WebGL renderer for concept A.** The maintainer chose it after walking
the three collector tasks in the harness on 2026-10-23. The GO is conditional on the
Recommendation: the instanced renderer, the per-view budget with the footprint check and both
lanes, and occlusion-resolving picking.  
Evidence date: 2026-10-23 (first pass 2026-10-22)  
Spike: `gm-design-on0x` (epic `gm-design-uq8t`)  
Harness: [gm-design-on0x/](gm-design-on0x/README.md)  
Related: `gm-design-1h2l` (the credit → master → release ladder and route cost, whose Discogs
database this spike's size bands are read from) and `gm-design-loj9` (concept D, whose
operations-console constraints are in section "Operations-console constraints").

## Question

Concept A, Discography Strata, draws one credit's discography on three stacked planes: artist
credits, then masters, then releases. x is release year, and the color of each node is its
collector state. The spike asks three things.

1. Can a 3D strata view stay legible and interactive at GrooveMap's real scale in the browsers
   graph-explorer supports?
2. Does it beat a 2.5D or a 2D alternative on real collector tasks?
3. How can one engine reach both graph-explorer and operations-console without a
   cross-repository source import?

## Method

### The port

The mockup's engine (`class Strata`, `CFG_A`, three.js r128 from a CDN) is split in two. GPU-free
modules hold the model, the layout, and the readouts. The renderers only draw. The time icicle,
`hull`, `roundedHull`, `inPoly`, `ribbon`, the label placement, and CFG_A's state machine are
copied unchanged. The mockup's two on-screen readouts, "nodes in a foreign hull" and "lateral
edges between planes", become `lib/layout.mjs` functions and `node --test` assertions. A third
check is added: node overlap, meaning two discs on one plane closer than their radii. The mockup
never counts it.

The harness adds what the mockup lacks. Each addition is measured with and without.

- **The planar edge rule.** Member and shared-credit edges radiate from the root credit. A
  shared-personnel edge is drawn only between masters of one credit that are neighbours in
  (year, depth) order. Company edges are drawn only for the selected node. Every other lateral
  edge stays in the panel and the table. A chain over points sorted by x cannot cross itself,
  and credit bands do not overlap in depth, so the rule holds crossings at zero by construction.
- **Two lanes from gm-design-1h2l.** 41.6% of Discogs releases have no master, and 7.8% have no
  year even after taking their master's. The `0` master id is Discogs's "no master" sentinel
  and counts as none.
  - **The no-master lane** is one node per credit on the master plane, "Releases without a
    master". It parents that credit's masterless releases. It never folds into a decade bucket,
    and its pressings never trigger the redundant-want redirect, because they share no master.
  - **The undated lane** is a strip at the left edge of every plane, outside the year axis. It
    holds undated releases, masters with no year, and their count nodes.
- **The aggregation rule** (`lib/view.mjs`), under a per-plane node budget `b0, b1, b2`:
  1. Credits: keep the root and the largest credits, and fold the rest into one "+k other
     credits" node.
  2. Masters: coarsen one credit at a time, largest first. Uncollected masters fold first, by
     decade, then by quarter century, then into one node per credit.
  3. Releases: keep the original pressing and every pressing with recorded state, and fold the
     rest into one "+k pressings" node per master or lane. If the plane is still over budget,
     drop the original pressing, then fold pressings with collector state too. The count node
     says how many it holds with state.
  4. Only then do masters with collector state fold, in the same three steps as uncollected
     masters.

  Opening a count node drills down a page at a time. A pressings node pages its master's or
  lane's pressings. Pages wrap, and the "more" node holds everything not on the page. A masters
  or credits node pins half a plane's budget of its members, and the rule folds something else
  to make room. Every node stays reachable: the tests assert that each visible model node is
  either drawn or held by exactly one count node, on every page.
- **The footprint check** (`fitView`). A node budget counts nodes, but overlap is about
  footprint. On the spaced icicle, each node gets at least its own footprint (2 × size + 0.6)
  of depth. A view fits when every plane's footprints fit the plane's depth, and then no two
  discs on a plane can touch, whatever their years. `fitView` tightens the fullest plane's
  budget until the view fits.
- **Occlusion-resolving picking** in `webgl-inst`. The mockup takes the nearest ray hit, so a
  node nearer the camera wins even when the pointer is on the centre of the node behind it.
  `resolve` collects every hit along the ray and takes the node whose projected centre is
  closest to the pointer. It prefers the soloed plane, then the selected node's plane.

### Fixtures and size bands

The fixtures are synthetic, at 50, 500, 5,000, and 20,000 nodes. The layout work uses 10 seeds per
scale, and the browsers use seed 1. A fixture has √n / 2 credits (4 to 71), with masters spread
over them on a Zipf curve. A collector holds or wants a pressing of about 30% of a small
discography's masters, capped near 40 masters. 6% of reissues exist only in MusicBrainz, which
blocks every collection transition on them (CFG_A's `discogsGate`). Names are invented
syllables.

The shape comes from Discogs `20261001`. `scripts/size_bands_discogs.py` runs one read-only query
over gm-design-1h2l's database (`load_db.py` output) and reads the ladder the way 1h2l reads the
graph: an artist's releases are its release-level `BY` edges, and its masters are the distinct
masters of those releases. An artist's size in nodes is 1 + masters + releases. For each fixture
scale, the fixture takes the shape of artists within a factor of 1.6 of that scale:

- the releases-per-master histogram, as each artist's own bucket shares averaged over artists;
- the masterless share;
- the undated share, split between masterless releases and whole masters with no year in 1h2l's
  measured ratio (13.8% of masterless releases are undated against 7.8% of all).

Averaging over artists keeps a placeholder-sized root of 1.36 million releases from setting the
shape. Only aggregates are committed (`results/size_bands.json`).

The first pass used MusicBrainz bands (release group for master). Their per-release input has
since been deleted, so they are no longer reproducible and are dropped.

### Renderers

All four renderers draw the same model and the same view, and use the same label placement and
panel. Only `d3` has its own layout.

| Renderer | What it is |
| --- | --- |
| `webgl` | The mockup engine as is, on three.js 0.186.1: four meshes and one DOM label per node, vertical lines rebuilt on every camera move, nearest-hit picking |
| `webgl-inst` | The same scene with one `InstancedMesh` per plane and node kind, merged edge ribbons, labels created only for candidates, and `resolve` picking. `webgl-inst:depth` is the same renderer with the mockup's nearest-hit picking, kept as the occlusion baseline |
| `iso` | 2.5D: Canvas 2D, orthographic. It turns and tilts, has no perspective, and paints bottom plane to top |
| `d3` | graph-explorer's `GraphVisualization._render` force graph (same forces, radii, and truncated always-on labels), with node fill switched from entity type to collector state. "Orbit" pans the zoom transform |

### Browsers and measurements

Playwright 1.64.1 drove Chromium 156, Firefox 157, and WebKit 27.2 on one Apple M1 Pro laptop
(10 cores, 32 GiB). All three ran headed: headless Chromium falls back to SwiftShader and
throttles animation frames. Each browser reported the M1's GPU through WebGL. For this re-run the
other spikes' streams were done, and the 1-minute load average stayed between 3.5 and 10.7. Each
run records it.

- **Desktop** is 1440 × 900 at device pixel ratio 2. **Phone** is 390 × 844 at device pixel ratio
  3, with `isMobile` and touch. Chromium's phone runs add 4× CPU throttling through CDP.
  Playwright has no CPU throttling for Firefox or WebKit, so their phone runs are viewport-only.
  Firefox has no `isMobile` either. These are emulations on a laptop, not phone numbers.
- **Time to first frame**: from the fixture being in memory (the point an API response would
  land) to the second animation frame after the first render. It covers model, view,
  aggregation, layout, scene, first draw, and labels.
- **Frame rate while orbiting**: one turn per 8 s for 4 s. It reports the median and the
  5th-percentile frame rate over every animation-frame interval. The display caps it at 120 Hz in
  Chromium and Firefox and at 60 Hz in WebKit.
- **Labels**: measured after the orbit with the camera reset. For d3, the graph is first settled
  and fit, as graph.js does on `end`. The figure is the share of drawn, on-screen nodes whose
  label is shown, is at least 8 CSS px tall, and overlaps no other shown label.
- **Hull intrusions and same-plane crossings**: from `lib/layout.mjs` on the same view. d3 has no
  hulls, so it reports link crossings at its settled positions.
- **Content-Security-Policy**: every page is served with `default-src 'self'; script-src 'self'
  'sha256-<importmap>'; style-src 'self'` and the rest of a strict policy. Every
  `securitypolicyviolation` event is recorded.

### Accessibility and tasks

`scripts/check_a11y_tasks.mjs` runs each renderer at every scale under the 3, 12, 16 budget, in
Chromium. It checks four things:

- keyboard navigation across planes and nodes;
- camera-reset animation frames, with and without `prefers-reduced-motion: reduce`;
- the table against the model as oracle, for every row and every blocked reason;
- the three collector tasks, as reachability.

1. **Find a missing pressing of an owned master.** The targets are owned masters with at least
   one pressing that is not owned, and those pressings.
2. **See which items cannot change state, and why.** The targets are pressings whose every
   transition is blocked.
3. **Trace a release to its credit.** The targets are pressings. Selecting one must highlight its
   master and credit.

For each target the script records four things:
- whether the default view draws it;
- how many count-node openings bring it on screen, if the default view folds it, up to a cap of
  200;
- whether a click on its projected centre picks it;
- the share of 8 points at 60% of its drawn radius that still pick it. A pointer is rarely on
  the exact centre, and occlusion shows here first.

## Evidence

### Size bands

Discogs `20261001`, through gm-design-1h2l's database (`results/size_bands.json`).

| | Count |
| --- | ---: |
| Releases | 19,492,392 |
| No master (the `0` sentinel) | 8,108,112 (41.60%) |
| No year of their own / still none after the master's year | 2,593,700 (13.31%) / 1,524,526 (7.82%) |
| Artists with at least one release | 2,882,133 |
| Nodes per artist (1 + masters + releases): p50, p90, p99, p99.9, p99.99 | 3, 13, 103, 668, 3,465 |
| Releases per master: p50, p90, p99, p99.9, max | 2, 7, 32, 112, 1,542 |
| Largest artists (nodes) | 1,530,999; 97,046; 66,145; 62,128; 51,667 |

| Band (nodes) | Artists | Fixture shape, from artists of | Masterless share | Undated share | Mean releases per master |
| --- | ---: | --- | ---: | ---: | ---: |
| 1 to 158 (99.41%) | 2,864,988 | 31 to 80 nodes (77,635) | 37.6% | 6.8% | 4.1 |
| 159 to 1,581 (0.56%) | 16,239 | 312 to 800 (5,104) | 19.3% | 6.7% | 8.1 |
| 1,582 to 10,000 | 853 | 3,125 to 8,000 (261) | 12.6% | 6.0% | 15.5 |
| > 10,000 | 53 | 12,500 to 32,000 (31) | 19.4% | 9.9% | 13.2 |

On Discogs, masters are fewer and larger than MusicBrainz release groups. A 20,000-node fixture
now has 1,486 master-plane nodes (71 of them no-master lanes) and 18,443 releases. The first
pass, on MusicBrainz bands, had 7,183 masters and 12,746 releases. The release plane carries the pressure, and the no-master lane carries a fifth of it.

### The mockup's layout at real shape

Medians over 10 seeds (`results/layout.json`, `raw.mockup`). Only the 50-node scale is near the
mockup's own demo (3 credits, 12 masters, 27 releases).

| Scale | Nodes per plane (L0 / L1 / L2) | Hull intrusions | Node overlaps | Crossings, all edges (mockup) | Crossings, planar rule | Edges drawn, all / planar |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 50 | 4 / 10 / 36 | 0 / 0 / 0 | 0 / 0 / 6 | 0 | 0 | 7 / 4 |
| 500 | 11 / 55 / 436 | 4 / 39 / 194 | 4 / 27 / 612 | 56 | 0 | 52 / 22 |
| 5,000 | 35 / 320 / 4,649 | 96 / 908 / 11,345 | 80 / 838 / 88,703 | 5,712 | 0 | 433 / 142 |
| 20,000 | 71 / 1,351 / 18,689 | 672 / 9,177 / 102,524 | 527 / 13,864 / 1,069,478 | 86,010 | 0 | 1,742 / 583 |

- On real-shaped data the mockup's readouts fail from 500 nodes. Even at 50, releases of one
  year overlap on the release plane.
- The planar edge rule holds same-plane crossings at **0 at every scale and seed, without
  aggregation**. The panel and the table keep the edges it drops.

### Node budget per plane, measured

Every sweep configuration ran on 4 scales × 10 seeds. A configuration passes only if all 40
fixtures fit the budget with zero hull intrusions, zero node overlaps, and zero crossings
(`results/layout.json`, `results/layout-mockup.json`).

| | Mockup icicle, counts only | Spaced icicle with the footprint check |
| --- | --- | --- |
| Configurations passing (mockup node sizes) | 8 of 336 | 336 of 336 |
| Largest drawn view that holds | 3 / 12 / 25 (budget 3, 12, 25). The frontier also has 4 / 16 / 16, and 4 / 12 / 20 with gutter 4 | 6 / 12 / 21 (requested 6, 12, 25). The check holds every request at or below this |
| Half-size nodes | 4 / 30 / 40 | 3 / 23 / 36 |
| Drill-down: page a master's pressings | Breaks at every page size tried, 2 to 20 (1 intrusion, 6 overlaps at the default page) | Holds for pages up to **12** pressings |
| Drill-down: pin one page of a masters count node | Breaks at every page size tried, 2 to 12 (3 violations at 2 per page) | Holds for pages up to **8** masters. 10 per page goes over budget, and 12 breaks (221 violations) |
| Drill-down: pin every pressing of the largest count node | 21,309 overlaps | 21,306 overlaps. Hundreds of pressings cannot fit one plane, so drill-down has to page |

- **A count budget alone does not hold the invariants.** On the mockup icicle, whether a view
  overlaps depends on its years, and so does whether drill-down breaks it. The footprint check
  makes the guarantee geometric. Every requested budget then holds, and the measured figure
  becomes the largest view the planes can carry.
- **The 3, 12, 16 budget from the first pass still holds** under both lanes, on both layouts.
  gm-design-1h2l's payload rule already defaults to it. The default view at 3, 12, 16 draws
  3 / 6 / 13 nodes at 50, 3 / 12 / 10 at 500, 3 / 10 / 2 at 5,000, and 3 / 12 / 2 at 20,000.
- **The budget did not change much with the lanes, but where it goes did.** At 5,000 nodes and
  above, the default view spends its release plane on the lanes' and masters' count nodes. A
  collector reaches pressings by opening them.

### Frame rate, time to first frame, and labels

Each cell is time to first frame (ms) · median / 5th-percentile fps · label share. "budget" is
3, 12, 16 on the spaced icicle with the footprint check. Full data is in `results/perf.json`:
192 runs, no page errors, and **no CSP violations**.

#### Desktop (1440 × 900)

| Renderer | Scale | Drawn per plane | Chromium | Firefox | WebKit |
| --- | ---: | --- | --- | --- | --- |
| `webgl` | 500 | 11 / 53 / 436 | 112 · 120 / 99 · 4% | 136 · 120 / 100 · 4% | 166 · 59 / 59 · 4% |
| `webgl` | 5,000 | 35 / 272 / 4,693 | 432 · 24 / 24 · 1% | 561 · 17 / 17 · 1% | 658 · 18 / 17 · 1% |
| `webgl` | 20,000 | 71 / 1,486 / 18,443 | 1,540 · 6.0 / 5.5 · 0% | 1,930 · 4.1 / 3.9 · 0% | 2,311 · 4.3 / 3.8 · 0% |
| `webgl` | 20,000 budget | 3 / 12 / 2 | 88 · 120 / 99 · 76% | 108 · 120 / 107 · 76% | 115 · 59 / 56 · 76% |
| `webgl-inst` | 5,000 | 35 / 272 / 4,693 | 159 · 120 / 99 · 1% | 190 · 120 / 108 · 1% | 205 · 59 / 59 · 1% |
| `webgl-inst` | 20,000 | 71 / 1,486 / 18,443 | 403 · 120 / 104 · 0% | 489 · 120 / 60 · 0% | 469 · 59 / 50 · 0% |
| `webgl-inst` | 20,000 budget | 3 / 12 / 2 | 96 · 120 / 97 · 76% | 116 · 120 / 106 · 76% | 112 · 59 / 50 · 76% |
| `iso` | 5,000 | 35 / 272 / 4,693 | 85 · 120 / 100 · 1% | 89 · 8.6 / 7.5 · 1% | 115 · 59 / 59 · 1% |
| `iso` | 20,000 | 71 / 1,486 / 18,443 | 309 · 60 / 55 · 0% | 357 · 1.3 / 1.2 · 0% | 365 · 44 / 37 · 0% |
| `iso` | 20,000 budget | 3 / 12 / 2 | 36 · 120 / 96 · 71% | 49 · 120 / 109 · 71% | 61 · 59 / 56 · 71% |
| `d3` | 500 | 500 nodes | 40 · 120 / 100 · 0% | 44 · 120 / 102 · 0% | 59 · 59 / 56 · 0% |
| `d3` | 5,000 | 5,000 nodes | 253 · 20 / 15 · 0% | 337 · 12 / 11 · 0% | 373 · 8.1 / 7.6 · 0% |
| `d3` | 20,000 | 20,000 nodes | 988 · 4.3 / 3.5 · 0% | 1,366 · 2.9 / 2.6 · 0% | 1,506 · 2.0 / 1.9 · 0% |
| `d3` | 20,000 budget | 17 nodes | 48 · 120 / 99 · 88% | 55 · 120 / 98 · 88% | 57 · 59 / 56 · 88% |

#### Phone (390 × 844; Chromium at 4× CPU throttling, Firefox and WebKit unthrottled)

| Renderer | Scale | Chromium (4×) | Firefox | WebKit |
| --- | ---: | --- | --- | --- |
| `webgl` | 20,000 | 4,201 · 1.8 / 1.3 · 0% | 1,921 · 4.0 / 3.9 · 0% | 2,252 · 4.3 / 3.2 · 0% |
| `webgl-inst` | 20,000 | 1,196 · 60 / 39 · 0% | 490 · 120 / 111 · 0% | 451 · 59 / 50 · 0% |
| `iso` | 20,000 | 978 · 20 / 13 · 0% | 370 · 1.8 / 1.6 · 0% | 347 · 48 / 42 · 0% |
| `d3` | 20,000 | 3,138 · 1.2 / 1.0 · 0% | 1,384 · 2.7 / 2.5 · 0% | 1,507 · 2.0 / 1.9 · 0% |
| `webgl` | 20,000 budget | 257 · 120 / 103 · 35% | 112 · 120 / 107 · 35% | 100 · 59 / 53 · 35% |
| `webgl-inst` | 20,000 budget | 236 · 120 / 101 · 35% | 115 · 120 / 111 · 35% | 104 · 59 / 56 · 35% |
| `iso` | 20,000 budget | 122 · 120 / 103 · 35% | 49 · 120 / 117 · 35% | 50 · 59 / 56 · 35% |
| `d3` | 20,000 budget | 128 · 120 / 102 · 6% | 50 · 120 / 98 · 6% | 44 · 59 / 53 · 6% |

`results/perf.json` holds every scale for both viewports. What it shows:

- **Under the budget, speed is not the constraint.** Every renderer in every browser and both
  viewports holds the display cap at the median, with a 5th percentile of at least 50 fps.
  - Time to first frame on desktop: `webgl-inst` 67 to 116 ms, `iso` 12 to 61 ms.
  - Time to first frame on the throttled phone: under 260 ms for every renderer.
- **`webgl-inst` is the only renderer that stays interactive unaggregated.** At 20,000 nodes it
  holds 120 fps in Chromium and Firefox and 59 in WebKit, at 4 to 5 ms of JavaScript per frame.
  The mockup engine (`webgl`) gets 4.1 to 6.0 fps there, at 158 to 201 ms per frame. Today's 2D
  graph gets 2.0 to 4.3 fps and had not settled after 20 s.
- **Unaggregated, nothing is legible.** At 500 nodes and above, at most 4% of drawn nodes carry a
  clean label in any renderer.
- **Firefox's Canvas 2D is the slow path for `iso`.** It manages 8.6 fps at 5,000 and 1.3 at
  20,000 unaggregated, where Chromium holds 60 to 120.
- **Labels under the budget.** The mockup labels credits and masters only, until the camera zooms
  or a node is selected (`labelDepth` 1). 3D and 2.5D show 41% to 77% of drawn nodes labeled on
  desktop and 20% to 40% on the phone. d3 labels everything. On desktop that is 80% to 100%
  clean, but on the phone its fit-to-view shrinks text below 8 px (0% to 100%).
- **The layout checks** read 0 hull intrusions and 0 same-plane crossings in every budgeted run.
  Unaggregated, at 500 nodes and above, the planes had 267 to 112,889 intrusions. The 2D graph's
  links cross 116 to 45,366 times unaggregated and 0 to 4 times under the budget.

### Accessibility

`results/a11y_tasks.json`, in Chromium, for all 20 renderer-and-scale runs:

| Requirement | Mockup | Harness (all renderers) | graph-explorer's 2D graph today |
| --- | --- | --- | --- |
| Keyboard navigation of planes and nodes | Arrows orbit, PageUp/PageDown go to parent or first child. No sibling step, and no way into a count node | **Demonstrated** at every scale. PageDown / PageUp / `[` `]` / Enter / Escape reach a credit, a master (Enter opens a folded one), a pressing, and back up. Plane buttons, zoom, sliders, and the table are in the tab order. The panel is `aria-live` | **Missing.** The only key handler is Escape to leave fullscreen (`graph.js` `_initControls`) |
| Reduced-motion mode | Skips tweens and the pulse when `prefers-reduced-motion` matches | **Demonstrated.** A camera reset animates 63 frames normally and 0 under `reduce` in `webgl`, `webgl-inst`, and `iso` | **Missing.** `zoomIn`/`fitToView` use 300 and 500 ms transitions, and the simulation animates regardless |
| Non-visual equivalent with states and blocked reasons | A nested outline with states, but no blocked reasons | **Demonstrated.** A table of every credit, lane, master, and pressing, folded or not, with path, year, state, and blocked reason. It matches the model on every row and blocked reason at all four scales (50 to 20,000 rows, 277 and 1,042 blocked at 5,000 and 20,000). It renders in at most 87 ms | **Missing** for this data |

### The three tasks

These are reachability numbers. They say whether the view puts the answer in front of the
collector, not whether it is pleasant. Which targets are drawn, and how many openings reach the
rest, depend on the view and not the renderer, so they are the same for all of them. The
renderers differ in what can be clicked.

Budget 3, 12, 16; openings are median / max, for up to 12 targets per task and scale:

| Scale | Task 1: owned masters with a gap, drawn by default | Openings | Task 1: their missing pressings, drawn | Openings | Task 2: blocked pressings, drawn | Openings | Task 3: openings to a folded pressing |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 50 | 3 of 3 | | 2 of 7 | 1 / 1 | 0 of 2 | 1 / 1 | 2 / 4 |
| 500 | 6 of 15 | 5 / 10 | 0 of 166 | 7 / 11 | 0 of 28 | 6 / 11 | 6 / 28 |
| 5,000 | 2 of 36 | 7 / 34 | 0 of 663 | 6 / 7 | 0 of 277 | 19 / 31 | 13 / 146 (10 of 12 reached) |
| 20,000 | 2 of 51 | 16 / 36 | 0 of 2,823 | 45 / 139 | 0 of 1,042 | 40 / 64 | 20 / 67 (11 of 12 reached) |

3 of the 156 targets needed more than the 200-opening cap. Each was a pressing 270 to 345 deep
in a master of 736 pressings, paged 8 at a time. Paging alone does not reach the far end of a
large master. That is what search-to-focus is for (Recommendation 6).

Clicking, over every task, scale, and target:

| Renderer | Drawn by default: a click on the centre picks it | Reached by drill-down: a click on the centre picks it | Off-centre clicks that pick it (8 points at 60% of the radius) |
| --- | --- | --- | --- |
| `webgl` (the mockup's nearest-hit picking) | 24 of 24 | 150 of 153 | 97.4% |
| `webgl-inst:depth` (nearest hit) | 24 of 24 | 150 of 153 | 97.4% |
| **`webgl-inst` (`resolve`)** | **24 of 24** | **153 of 153** | **99.8%** |
| `iso` | 24 of 24 | 153 of 153 | 99.2% |
| `d3` | 6 of 24 | 135 of 153 | 89.1% |

- **Occlusion is fixed, not accepted.** The 3 misses with nearest-hit picking are perspective
  occlusion: a node nearer the camera covers the target's centre. `resolve` picking reaches 153
  of 153, matching 2.5D, and catches off-centre clicks slightly more often than 2.5D does. The
  first pass's 4 of 7 came from the same cause, on MusicBrainz-shaped data.
- **d3 misses come from its force layout stacking circles on one another.** That is not
  occlusion in depth, and no picking rule fixes it.
- **In every renderer, the task answers come from the panel and the table.** The selected
  master lists its pressings with their states. Selecting a pressing highlights its master and
  credit, and PageUp twice walks the same path by keyboard. Under the budget, every blocked
  pressing starts folded, and its count node names how many it holds. The table answers task 2
  at every scale.

### The maintainer's judgment

The maintainer walked the three tasks in `webgl-inst`, `iso`, and `d3` on 2026-10-23, served from
this harness. Their judgment, verbatim:

> I like the 3D model, not the 2.5D.

### Vendoring cost in graph-explorer

`results/vendoring.json`.

| Item | three.js 0.186.1 |
| --- | --- |
| Files | `three.module.js` (662,772 B) and `three.core.js` (1,458,113 B). 0.186 ships no minified build, and graph-explorer copies files without a bundler |
| Total | 2,120,885 B raw. 418,036 B gzip -9. 313,372 B brotli. For scale: d3 7.9.0 is 279,706 B, and Plotly is 4.29 MB |
| License | MIT. `LICENSE` sha256 `8b378ebe…5bc` |
| `vendor-assets.json` / `ASSET_LICENSES.json` | One new asset entry (`three`, `0.186.1`, MIT, package `LICENSE`, two outputs) |
| Scripts that change | `explore/package.json` (dependency). `explore/scripts/vendor-licenses.mjs` (`REQUIRED_PACKAGES`). `scripts/build-web-assets.sh` (two `cp` lines, and the vendor file count goes from 6 to 8). `scripts/build-image.sh` (the license count goes from 10 to 11) |
| Importmap coverage test | The engine must `import … from 'three'` as a module, so `index.html` needs `"three": "/vendor/three.module.js"`. `importmap-coverage.test.js` then covers it with no change, and fails if the entry is missing. `three.module.js` reaches `three.core.js` by a relative import, which needs no entry. The test that the importmap comes before the first module script is unaffected |
| CSP compatibility | graph-explorer sends no Content-Security-Policy today, so nothing breaks now. Neither three.js file contains `eval`, `new Function`, string timers, workers, or WebAssembly. The one `URL.createObjectURL` in `three.core.js` is inside a doc comment. Every harness page ran under `script-src 'self'` plus an importmap hash, and `style-src 'self'`, with no violations. Two constraints apply for any future policy. First, the inline importmap (graph-explorer already has one) needs a hash or nonce. Second, the mockup's panel writes `style="…"` attributes through `innerHTML`, which `style-src 'self'` blocks. The port uses CSSOM instead. d3 7.9.0 contains one `new Function` (d3-dsv's row parser), which Explore never calls |

### Operations-console constraints

From gm-design-loj9's section 7, read against operations-console at `5bf0f48`:

1. **No cross-repository source.** The engine must arrive as an artifact the console pins: a
   vendored file with commit and digest provenance, an npm dependency in `package-lock.json`, or
   a CDN URL with SRI (Chart.js, Luxon, and its adapter come from jsdelivr today).
2. **Classic scripts only.** FastAPI `StaticFiles` serves `dashboard/static/` unbundled.
   `admin.js` loads as a classic `<script>`. There is no ES module, import map, or worker.
3. **No CSP yet, but CSP-ready.** It must work under `script-src 'self'` (plus a pinned CDN host),
   with no `eval`, no `new Function`, and no inline script.
4. **Licence recorded.** The console is AGPL-3.0-only. The engine needs a permissive licence and
   an entry in `THIRD_PARTY_NOTICES.md`, which today also misses the three CDN libraries.
5. **Testable without WebGL.** Vitest runs in jsdom, which has no WebGL, so layout and state
   must test without a GL context. A vendored engine must be excluded from coverage.
6. **Five browser projects.** chromium, firefox, webkit, iphone, and ipad. The view must render
   in all five or fall back to the table. New modules go into `scripts/e2e-coverage-sources.mjs`.
7. **Hidden-tab mount.** Admin tabs start `display:none`, so the view must size itself when its
   tab is first shown.

What this means for a 3D view in operations-console:

- **three.js 0.186 ships as ES modules only.** `three.module.js` imports `./three.core.js`.
  `three.cjs` is a deprecated Node stub that re-exports the ES module through `require`. There is
  no global (`THREE`) build. A classic-script
  console cannot load it as is. A 3D view there needs one of two things. Either the console
  adopts its first `<script type="module">` with an import map (constraint 2 changes), or it
  gets a bundled classic build, which adds the bundler the console does not have.
- **The harness already meets 3 and 5, and is built for 7.** three.js and the engine have no
  `eval` or `new Function` and ran under a strict policy. The layout, state, and table modules
  are GPU-free and run under `node --test`. Every renderer resizes from a `ResizeObserver`, so
  it redraws when its tab first gets a size. That has not been tested against a
  `display:none` tab.
- **Concept D does not need any of this yet.** The dispatcher records concept D as GO as a
  history ledger whose first build is a table or timeline. That build needs no three.js in the
  console. The constraints above bind only when a 3D view of D is planned.
- **Concept D's layout needs a primary-parent rule.** 30.15% of cross-linked editions have two
  work parents (gm-design-loj9). The hull invariant needs the Discogs master as the primary
  parent and the second parent drawn as a flagged cross-hull edge.

### Engine distribution

| Option | Fit with the repository rules | Cost |
| --- | --- | --- |
| **Pinned vendored copy with `source.json` and digest checks** (the contracts pattern) | Both AGENTS.md files forbid a source import or Docker build-context dependency on another GrooveMap repository. Both already accept promoted, pinned copies: graph-explorer's `contracts/catalog-api/graph-explorer/v1/source.json` and `scripts/promote-brand.sh`, and operations-console's `contracts/*/source.json`, which `scripts/check-contracts.py` verifies by SHA-256. A promoted engine module is the same shape | A promote script and one digest assertion in the consumer. Both repositories are AGPL-3.0-only, so copying the producer's file raises no license question. three.js itself is vendored separately in each consumer, with its own `ASSET_LICENSES` or `THIRD_PARTY_NOTICES` entry |
| Published package | Not forbidden. The Python precedent is `groovemap-runtime`, a git dependency pinned by commit in both `pyproject.toml` files. But no GrooveMap JavaScript package or npm publishing path exists, and AGENTS.md says migration work must not publish artifacts. operations-console has no vendor pipeline to copy a package's files into `dashboard/static` | A new repository or package, a release flow, and a vendor pipeline in operations-console, all for one module |
| Separate implementations | Allowed | The layout invariants, the footprint check, the aggregation rule, the state-machine guards, and the table are this spike's GO criteria. Two copies that drift apart would each need their own proof |

## Verdict: GO on a 3D WebGL renderer for concept A

**The maintainer's choice decides this verdict.** On 2026-10-23 they walked the three tasks in
the harness and judged: "I like the 3D model, not the 2.5D." That choice **overrides the cost
argument** the first pass made, and the measurements that argument rested on are kept here
unchanged as evidence:

- under the budget, `iso` reaches its first frame sooner (12 to 61 ms against 67 to 116 ms on
  desktop);
- `iso` needs no third-party file, against three.js's 418 KB gzipped;
- the 2.5D comparison stays in every table above.

The cost is real and accepted. It is not a reason to re-open the choice.

| Question | Answer |
| --- | --- |
| 1. Can a 3D strata view stay legible and interactive at real scale? | **Yes, on conditions.** Interactive: `webgl-inst` holds the display cap at 20,000 unaggregated nodes in Chromium and Firefox and 59 fps in WebKit. The mockup engine as is does not (4.1 to 6.0 fps). Legible: only through the per-view budget, both lanes, the footprint check, and paged drill-down. Every real discography past about 50 nodes is aggregated |
| 2. Does 3D beat 2.5D or 2D on the tasks? | **The maintainer judged 3D the better view** of the three. On the measured side, 3D and 2.5D reach the same targets in the same number of openings, and they differ only in clicking and cost. With occlusion-resolving picking, every reached target can be clicked in `webgl-inst` (153 of 153), as in `iso` (153 of 153) |
| 3. One engine for graph-explorer and operations-console? | **A pinned vendored copy with `source.json` and a digest check.** graph-explorer produces it, and the console promotes it. For the console, a 3D view also needs a module-script path (see above) |

Per concept, as the epic asks:

- **A.** GO on 3D (`webgl-inst`), by the maintainer's choice, on the Recommendation's conditions.
- **D.** GO as a history ledger. Its first build is a table or timeline, so it needs no 3D.
- **B and C** were not measured here. The per-plane budget comes from the depth of a plane
  against the size of a node, not from the renderer. Any concept drawn at the mockup's
  proportions holds tens of nodes per plane and needs the footprint check. Their own spike
  (gm-design-4804) can run its layout through this harness's sweep.

## Recommendation

The GO's conditions, for M3:

1. **Use `webgl-inst`.** It means `InstancedMesh` per plane and node kind, merged edge ribbons,
   labels created only for label candidates, and vertical links rebuilt only when they change.
   The mockup engine as it stands is out: 4.1 to 6.0 fps at 20,000 nodes.
2. **Keep the 3, 12, 16 per-view budget.** It is gm-design-1h2l's payload default, and it holds
   with both lanes. Larger discographies go through aggregation and paged drill-in.
   - Pages of 8 pressings (at most 12 hold), or 8 masters (at most 8 hold).
   - The no-master lane is one node per credit on the master plane, and never folds into a
     bucket.
   - The undated lane is a strip at the left edge of the year axis.
   - The footprint check runs after aggregation. It is the guarantee; the counts are the
     request.
   - The invariants are Vitest properties: zero hull intrusions, overlaps, and same-plane
     crossings, plus conservation of every node across pages.
3. **Fix perspective occlusion, don't accept it.** Ship `resolve` picking: every hit along the
   ray, the node with the nearest projected centre wins, and the soloed or selected plane breaks
   ties. Measured, it makes every target that drill-down reaches clickable at its centre: 153 of 153, against 150 of 153 for nearest-hit picking. That matches 2.5D's 153 of 153. Off-centre hits rise from 97.4% to 99.8%, above 2.5D's 99.2%. A hover list of everything under the pointer is the
   next step if real use still finds stacked nodes.
4. **Keep what is already right.** That is reduced motion for every camera tween, CSSOM instead
   of inline `style` attributes, no `eval` or `new Function`, and the importmap hash for any
   future CSP.
5. **Vendor three.js 0.186.1** as a pinned copy with:
   - the importmap entry `"three": "/vendor/three.module.js"`;
   - the `vendor-assets.json` and `ASSET_LICENSES.json` entry;
   - the build-script changes listed above;
   - a `source.json` with sha256 digests for both files: `9052042d…12ea` for
     `three.module.js` and `9edde002…69e6` for `three.core.js`.
6. **Navigation is the remaining cost.** At 5,000 nodes and above, reaching a folded pressing
   takes a median of 6 to 45 openings, and up to 146. 3 of 96 targets at those scales needed more than 200 openings. Give the view a search-to-focus entry point (open it on a named master
   or pressing) and an "only what I collect" filter. Ship the table as a first-class view, not a
   fallback. It is the only view that answers task 2 at every scale.
7. **Route shape for M2.** gm-design-1h2l's payload rule (credits/masters/releases budget,
   aggregate ids as `focus` cursors, a no-master aggregate per credit) is the matching server
   side. At 3, 12, 16 it stays under 31 entries and 4.5 KB for every sampled artist.
8. **Distribution.** graph-explorer produces the engine module. operations-console promotes it
   with `source.json` holding `producer_repository`, `producer_commit`, and `sha256`, plus a
   digest assertion beside its contract checks. It does so only when a 3D view of concept D is
   planned, and that plan must first settle the module-script question.

## Missing evidence

- **Real phones.** Not measured. The phone rows are a 390 × 844 viewport on a laptop. Only
  Chromium could add CPU throttling. No iPhone Safari or mid-range Android numbers exist, and
  none are estimated.
- **A mid-range laptop.** Not measured. The only machine was an M1 Pro. Under the budget every
  renderer sits at the display cap, which leaves headroom. The unaggregated figures are this
  machine's alone.
- **Concepts B and C.** Not measured here (see Verdict).
- **Fixture assumptions.** These are invented: the number of related credits (√n / 2), the
  collector's 30% / 40-master interest, the 6% MusicBrainz-only share, and the split of undated
  releases between masterless releases and whole masters. The footprint guarantee does not
  depend on them. The drill-down action counts do.

## Sources

- Strata mockup, the maintainer's private artifact. The agents' copy is outside the repository.
- gm-design-1h2l's harness and Discogs `20261001` database (`load_db.py`), read-only.
- gm-design-loj9, section 7: operations-console constraints.
- [three.js releases](https://github.com/mrdoob/three.js/releases), [MIT license](https://github.com/mrdoob/three.js/blob/dev/LICENSE)
- [Playwright: emulation](https://playwright.dev/docs/emulation),
  [Chrome DevTools Protocol `Emulation.setCPUThrottlingRate`](https://chromedevtools.github.io/devtools-protocol/tot/Emulation/#method-setCPUThrottlingRate)
- graph-explorer at `ad8e462` (`explore/static/js/graph.js`, `explore/vendor-assets.json`,
  `explore/__tests__/importmap-coverage.test.js`, `scripts/build-web-assets.sh`, `AGENTS.md`).
  operations-console's `AGENTS.md` and `scripts/check-contracts.py`.
