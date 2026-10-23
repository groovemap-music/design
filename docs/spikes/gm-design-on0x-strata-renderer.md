# Spike: concept A's strata renderer at catalog scale

Status: **NO-GO for a 3D (WebGL) renderer for concept A.** Provisional: the maintainer has not yet
signed off on the task comparison. At the size where the strata layout stays legible, a 2.5D
Canvas renderer does everything the 3D one does. It loads faster, needs no new dependency, and
lets more of the targets be clicked. Whether the strata view itself beats today's 2D graph on the
collector tasks is **DEFER** until that sign-off.  
Evidence date: 2026-10-22  
Spike: `gm-design-on0x` (epic `gm-design-uq8t`)  
Harness: [gm-design-on0x/](gm-design-on0x/README.md)  
Related: `gm-design-1h2l` measures the full credit → master → release ladder. This spike uses
only a quick count of it.

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

The harness adds three things the mockup lacks. Each is measured both with and without.

- **The planar edge rule.** Member and shared-credit edges radiate from the root credit. A
  shared-personnel edge is drawn only between masters of one credit that are neighbours in
  (year, depth) order. Company edges are drawn only for the selected node. Every other lateral
  edge stays in the panel and the table. A chain over points sorted by x cannot cross itself,
  and credit bands do not overlap in depth, so the rule holds crossings at zero by construction.
- **The spaced icicle.** Each node gets at least its own footprint (2 × size + 0.6) of depth,
  instead of one share per leaf.
- **The aggregation rule** (`lib/view.mjs`), under a per-plane node budget `b0, b1, b2`:
  1. Credits: keep the root and the largest credits, and fold the rest into one "+k other
     credits" node.
  2. Masters: coarsen one credit at a time, largest first. Uncollected masters fold first, by
     decade, then by quarter century, then into one node per credit. Masters with collector
     state fold last, in the same three steps.
  3. Releases: keep the original pressing and every pressing with recorded state, and fold the
     rest into one "+k pressings" node per master.

  Opening a count node drills down a page at a time. A pressings node pages its master's
  pressings. A masters or credits node pins half a plane's budget of its members, and the rule
  folds something else to make room. Every node stays reachable: the test asserts that each
  visible model node is either drawn or held by exactly one count node.

### Fixtures and size bands

The fixtures are synthetic, at 50, 500, 5,000, and 20,000 nodes. The layout work uses 10 seeds per
scale, and the browsers use seed 1. A fixture has √n / 2 credits (4 to 71), with masters spread
over them on a Zipf curve. Releases per master are drawn from the real distribution of the
matching size band. A collector holds or wants a pressing of about 30% of a small discography's
masters, capped near 40 masters. 6% of reissues exist only in MusicBrainz, which blocks every
collection transition on them (CFG_A's `discogsGate`). Names are invented syllables.

The size bands come from a quick count over MusicBrainz, not Discogs. data.discogs.com answered
429 to every request on 2026-10-22, and the disk had 15 GiB free, which rules out caching the
11 GB releases dump. Two inputs were used:

- the MusicBrainz `20261021-001001` release-group dump, from the shared cache, for each release
  group's artist credits;
- gm-design-1h2l's compact stream of the release dump, for each release's release group.

In this count, a release group stands in for a master and an artist credit for a credit.
MusicBrainz's special-purpose artists ("Various Artists", "[unknown]", and the others) are
dropped. Only the aggregate histogram is committed (`results/size_bands.json`).

### Renderers

All four renderers draw the same model and the same view, and use the same label placement and
panel. Only `d3` has its own layout.

| Renderer | What it is |
| --- | --- |
| `webgl` | The mockup engine as is, on three.js 0.186.1: four meshes and one DOM label per node, vertical lines rebuilt on every camera move |
| `webgl-inst` | The same scene with one `InstancedMesh` per plane and node kind, merged edge ribbons, and labels created only for candidates |
| `iso` | 2.5D: Canvas 2D, orthographic. It turns and tilts, has no perspective, and paints bottom plane to top |
| `d3` | graph-explorer's `GraphVisualization._render` force graph (same forces, radii, and truncated always-on labels), with node fill switched from entity type to collector state. "Orbit" pans the zoom transform |

### Browsers and measurements

Playwright 1.64.1 drove Chromium 156, Firefox 157, and WebKit 27.2 on one Apple M1 Pro laptop
(10 cores, 32 GiB). All three ran headed: headless Chromium falls back to SwiftShader and
throttles animation frames. Each browser reported the M1's GPU through WebGL. Other spike
developers were streaming and parsing dumps on the same machine. The 1-minute load average was
between 4.8 and 23.5 across the runs, and each run records it.

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

`scripts/check_a11y_tasks.mjs` runs each renderer at every scale under the budget. It checks
four things:

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

For each target, the script records whether the default view draws it and whether it can be
clicked at its projected position. Perspective and overlap can hide it. Where the default view
folds a target, the script also records how many count-node openings bring it on screen.

## Evidence

### Size bands

| | MusicBrainz 20261021 |
| --- | ---: |
| Releases | 5,867,935 |
| Release groups with releases | 4,589,277 |
| Credits with at least one release group | 1,127,651 |
| Releases per release group: p50, p90, p99, p99.9, max | 1, 2, 5, 15, 294 |
| Nodes per credit (1 + release groups + releases): p50, p90, p99, p99.9, p99.99 | 5, 20, 115, 431, 1,452 |
| Largest credits (nodes) | 15,136; 14,661; 14,614; 10,290; 6,944 |
| Credits by band: ≤ 158 / 159 to 1,581 / 1,582 to 10,000 / > 10,000 nodes | 99.40% / 0.59% (6,637) / 95 / 4 |

In the largest credits, masters dominate. The largest has 6,320 release groups and 8,815
releases. The master plane, not the release plane, is the one under most pressure. Discogs holds
3.3 times as many releases (19,417,067 in `20260901`), so its large credits carry more pressings
per master. gm-design-1h2l measures that. These bands also count only a credit's own release
groups. Concept A adds group and collaboration credits on top.

### The mockup's layout at real shape

Medians over 10 seeds (`results/layout.json`). Only the 50-node scale is near the mockup's own
demo (3 credits, 12 masters, 27 releases).

| Scale | Nodes per plane (L0 / L1 / L2) | Hull intrusions | Node overlaps | Crossings, all edges (mockup) | Crossings, planar rule | Edges drawn, all / planar |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 50 | 4 / 21 / 25 | 0 / 0 / 0 | 0 / 4 / 0 | 0 | 0 | 14 / 11 |
| 500 | 11 / 176 / 314 | 6 / 97 / 132 | 6 / 375 / 255 | 92 | 0 | 135 / 90 |
| 5,000 | 35 / 1,857 / 3,143 | 182 / 5,481 / 7,726 | 146 / 34,470 / 27,252 | 9,433 | 0 | 1,371 / 944 |
| 20,000 | 71 / 7,324 / 12,638 | 1,094 / 49,057 / 70,180 | 815 / 492,879 / 430,712 | 153,971 | 0 | 5,444 / 3,742 |

- The mockup's readouts fail at 500 nodes. Even at 50, a real-shaped discography (21 masters)
  overlaps master spheres on the master plane.
- The planar edge rule holds same-plane crossings at **0 at every scale and seed, without
  aggregation**. It drops about a third of the lateral edges from the plane, and the panel and
  the table keep them.
- The spaced icicle changes nothing here (`results/layout.json`, `raw.spaced`). The planes are
  simply full.

### Node budget per plane, measured

The sweep tried 1,512 configurations: 6 credit budgets × 7 master budgets × 9 release budgets ×
gutter {0, 4} × node size {mockup, half}. Each ran on 4 scales × 10 seeds. A configuration passes
only if all 40 fixtures fit the budget with zero hull intrusions, zero node overlaps, and zero
crossings.

| | Mockup node sizes | Half-size nodes |
| --- | --- | --- |
| Passing configurations | 54 of 756 | (best only recorded) |
| Best budget `b0, b1, b2` | **3, 12, 16** (largest drawn: 3 / 12 / 13). The other frontier point is 6, 12, 16 (6 / 12 / 10) | 3, 25, 30 (3 / 25 / 29) |
| What fails just above | 3, 16, x: 4 master overlaps. 3, 20, x: 7 to 8. 3, 25, 16: 10 | |

At the mockup's proportions, a plane of 78 depth units holds about 14 master spheres
(78 / 5.4) or 23 release discs before two of the same year must touch. That makes **about 28
drawn nodes per view** the measured legibility budget. Halving node radii roughly doubles it, at
the cost of 3 to 7 px release discs on a laptop screen. Gutters between credit groups never
helped, because they spend depth the planes do not have.

Drill-down at the 3, 12, 16 budget:

| Opening a count node | Result over 40 fixtures |
| --- | --- |
| Pin every pressing of the largest "+k pressings" node | Breaks the layout: 23 overlaps, release plane up to 32 |
| Page that master's pressings (`focus`) | Holds at 0 / 0 / 0 for pages up to **15** pressings |
| Pin one page of the largest masters count node | Holds for pages up to **8** masters. 10 per page breaks it (26 violations, 30 over budget) |

Under the rule, at 500 nodes and above the default view is the root credit, one or two more
credits, a "+k other credits" node, and decade buckets of masters. Few or no pressings are drawn
until a master is opened: none at 500 and 5,000, and 6 at 20,000 (seed 1).

### Frame rate, time to first frame, and labels

Each cell is time to first frame (ms) · median / 5th-percentile fps · label share. "budget" is
3, 12, 16 on the spaced icicle. Full data is in `results/perf.json`: 192 runs, no page errors,
and **no CSP violations**.

#### Desktop (1440 × 900)

| Renderer | Scale | Drawn per plane | Chromium | Firefox | WebKit |
| --- | ---: | --- | --- | --- | --- |
| `webgl` | 500 | 11 / 176 / 313 | 135 · 120 / 103 · 7% | 196 · 101 / 57 · 7% | 165 · 59 / 56 · 7% |
| `webgl` | 5,000 | 35 / 1,902 / 3,063 | 705 · 13 / 12 · 1% | 892 · 10 / 8.5 · 1% | 687 · 15 / 12 · 1% |
| `webgl` | 20,000 | 71 / 7,183 / 12,746 | 2,383 · 3.4 / 3.1 · 0% | 3,198 · 2.4 / 2.4 · 0% | 2,336 · 3.5 / 2.8 · 0% |
| `webgl` | 20,000 budget | 3 / 12 / 6 | 140 · 120 / 103 · 67% | 174 · 120 / 100 · 67% | 113 · 59 / 56 · 67% |
| `webgl-inst` | 5,000 | 35 / 1,902 / 3,063 | 182 · 120 / 110 · 1% | 223 · 120 / 63 · 1% | 272 · 59 / 53 · 1% |
| `webgl-inst` | 20,000 | 71 / 7,183 / 12,746 | 462 · 119 / 58 · 0% | 927 · 40 / 30 · 0% | 724 · 32 / 30 · 0% |
| `webgl-inst` | 20,000 budget | 3 / 12 / 6 | 102 · 120 / 111 · 67% | 158 · 120 / 110 · 67% | 126 · 59 / 59 · 67% |
| `iso` | 5,000 | 35 / 1,902 / 3,063 | 144 · 120 / 101 · 1% | 119 · 8.6 / 7.5 · 1% | 191 · 59 / 59 · 1% |
| `iso` | 20,000 | 71 / 7,183 / 12,746 | 450 · 30 / 24 · 0% | 614 · 1.2 / 1.1 · 0% | 643 · 21 / 20 · 0% |
| `iso` | 20,000 budget | 3 / 12 / 6 | 54 · 120 / 100 · 62% | 60 · 120 / 99 · 62% | 73 · 59 / 59 · 62% |
| `d3` | 500 | 500 nodes | 54 · 120 / 99 · 0% | 45 · 120 / 101 · 0% | 70 · 59 / 59 · 0% |
| `d3` | 5,000 | 5,000 nodes | 367 · 12 / 11 · 0% | 355 · 10 / 9.2 · 0% | 397 · 7.8 / 6.6 · 0% |
| `d3` | 20,000 | 20,000 nodes | 1,538 · 2.6 / 2.1 · 0% | 1,423 · 2.3 / 1.8 · 0% | 1,627 · 1.8 / 1.5 · 0% |
| `d3` | 20,000 budget | 21 nodes | 62 · 120 / 101 · 100% | 58 · 120 / 102 · 100% | 55 · 59 / 59 · 100% |

#### Phone (390 × 844; Chromium at 4× CPU throttling, Firefox and WebKit unthrottled)

| Renderer | Scale | Chromium (4×) | Firefox | WebKit |
| --- | ---: | --- | --- | --- |
| `webgl` | 20,000 | 7,701 · 0.9 / 0.8 · 0% | 2,128 · 2.9 / 2.0 · 0% | 2,359 · 3.4 / 2.8 · 0% |
| `webgl-inst` | 20,000 | 2,032 · 24 / 17 · 0% | 552 · 40 / 40 · 0% | 780 · 32 / 26 · 0% |
| `iso` | 20,000 | 1,830 · 8.6 / 6.0 · 0% | 428 · 2.6 / 2.4 · 0% | 643 · 21 / 19 · 0% |
| `d3` | 20,000 | 5,229 · 0.7 / 0.6 · 0% | 1,491 · 2.4 / 2.2 · 0% | 1,782 · 1.7 / 1.5 · 0% |
| `webgl` | 20,000 budget | 385 · 120 / 100 · 33% | 123 · 120 / 102 · 29% | 114 · 59 / 56 · 33% |
| `webgl-inst` | 20,000 budget | 358 · 120 / 109 · 33% | 124 · 120 / 109 · 29% | 116 · 59 / 59 · 33% |
| `iso` | 20,000 budget | 214 · 120 / 60 · 29% | 59 · 120 / 99 · 29% | 53 · 59 / 59 · 29% |
| `d3` | 20,000 budget | 211 · 120 / 99 · 5% | 58 · 120 / 99 · 5% | 55 · 59 / 59 · 5% |

`results/perf.json` holds every scale for both viewports. What it shows:

- **Under the budget, speed is not the constraint.** Every renderer in every browser and both
  viewports holds the display cap at the median, with a 5th percentile of at least 50 fps.
  Time to first frame stays under 400 ms on the throttled phone. On desktop, `iso` and `d3` take
  13 to 73 ms, and the two WebGL renderers take 65 to 174 ms.
- **Unaggregated, nothing is legible.** At 500 nodes and above, under 7% of drawn nodes carry a
  clean label in any renderer. Only `webgl-inst` stays interactive at 20,000 (119 fps in Chromium
  and 32 to 40 in Firefox and WebKit). The mockup engine (`webgl`) manages 2.4 to 3.5 fps there,
  spending 207 to 348 ms of JavaScript per frame. Today's 2D graph manages 1.8 to 2.6 fps and had
  not settled after 20 s.
- **Firefox's Canvas 2D is the slow path for `iso`.** It drops to 8.6 fps at 5,000 unaggregated
  nodes, where Chromium and WebKit hold the cap. Under the budget it does not show.
- **Labels under the budget.** The mockup labels credits and masters only, until the camera zooms
  or a node is selected (`labelDepth` 1). So 3D and 2.5D show 44% to 100% of drawn nodes labeled
  on desktop and 22% to 53% on the phone. d3 labels everything, but on the phone its fit-to-view
  shrinks text below 8 px (0% to 85%).
- **The layout checks** read 0 hull intrusions and 0 same-plane crossings in every budgeted run.
  Unaggregated, at 500 nodes and above, the planes had 229 to 116,582 intrusions. The d3 graph's links cross 193 to
  129,671 times unaggregated and 0 to 2 times under the budget.

### Accessibility

`results/a11y_tasks.json`, in Chromium, for all 16 renderer-and-scale pairs:

| Requirement | Mockup | Harness (all four renderers) | graph-explorer's 2D graph today |
| --- | --- | --- | --- |
| Keyboard navigation of planes and nodes | Arrows orbit, PageUp/PageDown go to parent or first child. No sibling step, and no way into a count node | **Demonstrated.** PageDown / PageUp / `[` `]` / Enter / Escape reach a credit, a master (Enter opens a folded one), a pressing, and back up, at every scale. Plane buttons, zoom, sliders, and the table are in the tab order. The panel is `aria-live` | **Missing.** The only key handler is Escape to leave fullscreen (`graph.js` `_initControls`) |
| Reduced-motion mode | Skips tweens and the pulse when `prefers-reduced-motion` matches | **Demonstrated.** A camera reset animates 63 frames normally and 0 under `reduce`, for `webgl`, `webgl-inst`, and `iso` | **Missing.** `zoomIn`/`fitToView` use 300 and 500 ms transitions, and the simulation animates regardless |
| Non-visual equivalent with states and blocked reasons | A nested outline with states, but no blocked reasons | **Demonstrated.** A table of every credit, master, and pressing, folded or not, with path, year, state, and blocked reason. It matches the model on every row and every blocked reason at all four scales (50 to 20,000 rows, 76 and 333 blocked at 5,000 and 20,000). It renders in at most 77 ms | **Missing** for this data |

### The three tasks

These are reachability numbers. They say whether the renderer puts the answer in front of the
collector, not whether it is pleasant. They are the same for every renderer wherever the view
decides, and they differ in the clickable columns.

| Scale (budget 3, 12, 16) | Task 1: owned masters with a gap, drawn by default | Task 1: openings to reach them, median / max | Task 2: blocked pressings, drawn by default | Task 2: openings, median / max | Task 3: openings to reach a folded pressing, median / max |
| ---: | --- | --- | --- | --- | --- |
| 50 | (none in fixture) | | (none) | | 1 / 3 |
| 500 | 0 of 7 | 2 / 5 | 0 of 7 | 4 / 10 | 5 / 9 |
| 5,000 | 0 of 4 | 8 / 16 | 0 of 76 | 14 / 33 | 24 / 36 |
| 20,000 | 0 of 10 | 31 / 70 | 0 of 333 | 54 / 117 | 56 / 159 |

Clickable after reaching the target (where the renderers differ):

| Renderer | Task 1 masters at 500 | Task 2 at 500 | Pressings drawn by default at 50 / 500 / 5,000 / 20,000 |
| --- | --- | --- | --- |
| `webgl`, `webgl-inst` | 4 of 7 | 6 of 7 | 10 of 11, 8 of 8, 6 of 6, 6 of 6 |
| `iso` | 7 of 7 | 7 of 7 | 11 of 11, 8 of 8, 6 of 6, 6 of 6 |
| `d3` | 7 of 7 | 7 of 7 | 2 of 11, 5 of 8, 1 of 6, 3 of 6 |

The WebGL misses are perspective occlusion: a node nearer the camera covers the target. The d3
misses are its force layout stacking pressings on one another.

What the views show, from the walk-throughs (screenshots at 5,000 under the budget, kept outside
the repository):

- **Task 1.** In every renderer the answer comes from the panel, not the picture. The selected
  master lists its pressings with their states ("2 not owned"). On the planes, 3D and 2.5D show
  the missing pressings as grey discs about 6 px across under the selected master, which is
  readable only after a zoom. d3 draws them as full-size circles beside the master.
- **Task 2.** A red ring marks a blocked pressing only once it is drawn. Under the budget, every
  blocked pressing starts folded, and its count node says "k MusicBrainz only". The table is the
  only view that answers the question at a glance at any scale.
- **Task 3.** All three renderers highlight the selected pressing's cylinder: its master and its
  credit. In 3D the vertical links read most clearly. In 2.5D they are the same lines, flatter.
  d3 shows the path as two short links. PageUp twice walks it by keyboard in every renderer.
- **Navigation is the real cost.** At 5,000 and 20,000 nodes, a target folded under "+k other
  credits" needs one opening per credit page (1 credit per page at `b0` = 3). That is where the
  medians of 8 to 56 openings come from. The 6, 12, 16 frontier point would show three credits
  per page. A search-to-focus entry point would replace the chain entirely.

**The maintainer's judgment on these tasks is pending.** It has not been given, and nothing here
stands in for it. To review: run `node scripts/serve.mjs 8765` in the harness and open
`/web/index.html?r=<renderer>&n=5000&budget=3,12,16&spaced=1` for `webgl-inst`, `iso`, and `d3`.

### Vendoring cost in graph-explorer

`results/vendoring.json`. This is needed only if a WebGL renderer is chosen.

| Item | three.js 0.186.1 |
| --- | --- |
| Files | `three.module.js` (662,772 B) and `three.core.js` (1,458,113 B). 0.186 ships no minified build, and graph-explorer copies files without a bundler |
| Total | 2,120,885 B raw. 418,036 B gzip -9. 313,372 B brotli. For scale: d3 7.9.0 is 279,706 B, and Plotly is 4.29 MB |
| License | MIT. `LICENSE` sha256 `8b378ebe…5bc` |
| `vendor-assets.json` / `ASSET_LICENSES.json` | One new asset entry (`three`, `0.186.1`, MIT, package `LICENSE`, two outputs) |
| Scripts that change | `explore/package.json` (dependency). `explore/scripts/vendor-licenses.mjs` (`REQUIRED_PACKAGES`). `scripts/build-web-assets.sh` (two `cp` lines, and the vendor file count goes from 6 to 8). `scripts/build-image.sh` (the license count goes from 10 to 11) |
| Importmap coverage test | The engine must `import … from 'three'` as a module, so `index.html` needs `"three": "/vendor/three.module.js"`. `importmap-coverage.test.js` then covers it with no change, and fails if the entry is missing. `three.module.js` reaches `three.core.js` by a relative import, which needs no entry. The test that the importmap comes before the first module script is unaffected |
| CSP compatibility | graph-explorer sends no Content-Security-Policy today, so nothing breaks now. Neither three.js file contains `eval`, `new Function`, string timers, workers, or WebAssembly. The one `URL.createObjectURL` in `three.core.js` is inside a doc comment. Every harness page ran under `script-src 'self'` plus an importmap hash, and `style-src 'self'`, with no violations. Two constraints apply for any future policy. First, the inline importmap (graph-explorer already has one) needs a hash or nonce. Second, the mockup's panel writes `style="…"` attributes through `innerHTML`, which `style-src 'self'` blocks. The port uses CSSOM instead. d3 7.9.0 contains one `new Function` (d3-dsv's row parser), which Explore never calls |

The 2.5D renderer adds no third-party file at all.

### Engine distribution

| Option | Fit with the repository rules | Cost |
| --- | --- | --- |
| **Pinned vendored copy with `source.json` and digest checks** (the contracts pattern) | Both AGENTS.md files forbid a source import or Docker build-context dependency on another GrooveMap repository. Both already accept promoted, pinned copies: graph-explorer's `contracts/catalog-api/graph-explorer/v1/source.json` and `scripts/promote-brand.sh`, and operations-console's `contracts/*/source.json`, which `scripts/check-contracts.py` verifies by SHA-256. A promoted engine module is the same shape | A promote script and one digest assertion in the consumer. Both repositories are AGPL-3.0-only, so copying the producer's file raises no license question |
| Published package | Not forbidden. The Python precedent is `groovemap-runtime`, a git dependency pinned by commit in both `pyproject.toml` files. But no GrooveMap JavaScript package or npm publishing path exists, and AGENTS.md says migration work must not publish artifacts. operations-console has no vendor pipeline to copy a package's files into `dashboard/static` | A new repository or package, a release flow, and a vendor pipeline in operations-console, all for one module |
| Separate implementations | Allowed | The layout invariants, the aggregation rule, the state-machine guards, and the table are this spike's GO criteria. Two copies that drift apart would each need their own proof |

## Verdict: NO-GO on 3D for concept A

| Question | Answer |
| --- | --- |
| 1. Can a 3D strata view stay legible and interactive at real scale? | **Interactive: yes**, with instancing (`webgl-inst` holds 119 fps in Chromium at 20,000 nodes). The mockup engine as is does not (2.4 to 3.5 fps). **Legible: no.** The mockup's own readouts fail from 500 nodes, about the top 0.6% of credits. The layout holds zero intrusions, overlaps, and crossings only up to a measured budget of about **3 credits, 12 masters, and 16 pressings** per view. Past that, every real discography has to be aggregated and drilled into |
| 2. Does 3D beat 2.5D or 2D on the tasks? | **No, on this evidence.** Under the budget, 2.5D draws the same view. It is faster to first frame (15 to 73 ms against 65 to 174 ms on desktop), holds the same frame rates, lets more targets be clicked (7 of 7 against 4 of 7), and costs no 418 KB (gzip) dependency. In every renderer the tasks are answered by the panel and the table. Whether the strata view beats today's 2D graph enough to build is **DEFER**: the maintainer's task judgment is pending |
| 3. One engine for graph-explorer and operations-console? | **Pinned vendored copy with `source.json` and a digest check** |

Per concept, as the epic asks:

- **A.** 3D does not earn its cost: NO-GO on WebGL, and the view is DEFER as above.
- **B, C, and D** were not measured here. What carries over: the per-plane budget comes from the
  depth of a plane against the size of a node, not from the renderer, so any concept drawn at the
  mockup's proportions holds tens of nodes per plane. And 3D's costs (a 2.1 MB dependency,
  perspective occlusion, and WebGL in the end-to-end matrix) do not depend on the concept. A
  concept-B atlas or a concept-D ledger would need a task that only perspective can answer
  before 3D earns its place. Their own spikes (gm-design-4804, gm-design-loj9) can run their
  layouts through this harness's sweep.

The NO-GO is provisional on the maintainer's sign-off of the task comparison. If the walk-through
finds that 3D orbit answers a task the 2.5D view cannot, this verdict should be revisited with
that task added to the harness.

## Recommendation

1. **Renderer.** Build concept A's strata view, if the maintainer wants it, as a 2.5D Canvas
   renderer. Do not vendor three.js for it. Keep `webgl-inst` as the reference if a later concept
   shows a perspective-only task.
2. **Layout rules for M3.** These are tested properties, not tuning:
   - the planar edge rule;
   - the aggregation rule, with the budget expressed as plane depth over node footprint (3, 12,
     16 at the mockup's proportions);
   - paged drill-down: at most 15 pressings or 8 masters per page;
   - the invariant checks as Vitest properties.

   Re-run the sweep if the plane proportions or node sizes change.
3. **Navigation before rendering.** At 5,000 nodes and above, the tasks take 8 to 56 openings
   through count nodes. Give the strata view a search-to-focus entry point (open the view on a
   named master or pressing) and an "only what I collect" filter, so that the drawn ~28 nodes
   are the right ones. Ship the table as a first-class view, not a fallback. It is the only view
   that answers task 2 at every scale.
4. **Route shape for M2.** `catalog-api`'s strata route should return the aggregated view
   (counts per fold, with paging cursors), not 20,000 nodes. The budget is small enough that the
   payload is always a few kilobytes.
5. **Distribution.** graph-explorer produces the engine module (M3). operations-console promotes
   it with `source.json` holding `producer_repository`, `producer_commit`, and `sha256`, plus a
   digest assertion beside its contract checks. The 2.5D renderer keeps the copied artifact free
   of third-party code.
6. **Accessibility to carry into M3.** Keyboard traversal including siblings and drill-down
   (Enter), reduced motion for every camera and layout animation, and the table with blocked
   reasons. graph-explorer's current 2D graph has none of the three.

## Missing evidence and DEFER items

- **The maintainer's judgment on the three tasks.** Pending. The reachability numbers and
  observations above are the spike developer's own.
- **Discogs size bands.** DEFER. data.discogs.com returned 429 throughout, so the bands are
  MusicBrainz-based. gm-design-1h2l's Discogs pass will show larger pressings-per-master tails.
  Those tails make the release plane fold sooner. They do not move the budget, which comes from
  geometry.
- **Real phones.** Not measured. The phone rows are a 390 × 844 viewport on a laptop. Only
  Chromium could add CPU throttling. No iPhone Safari or mid-range Android numbers exist, and
  none are estimated.
- **A mid-range laptop.** Not measured. The only machine was an M1 Pro, shared with other spike
  runs at load averages from 4.8 to 23.5. Absolute frame rates under the budget sit at the display
  cap, which leaves headroom. The unaggregated figures are this machine's alone.
- **Concepts B, C, and D.** Not measured here (see Verdict).
- **Fixture assumptions.** The number of related credits (√n / 2), the collector's 30% / 40-master
  interest, and the 6% MusicBrainz-only share are invented. The budget does not depend on them.
  The drill-down action counts do.

## Sources

- Strata mockup, the maintainer's private artifact. The agents' copy is outside the repository.
- [three.js r186 release](https://github.com/mrdoob/three.js/releases), [MIT license](https://github.com/mrdoob/three.js/blob/dev/LICENSE)
- [Playwright: emulation](https://playwright.dev/docs/emulation),
  [Chrome DevTools Protocol `Emulation.setCPUThrottlingRate`](https://chromedevtools.github.io/devtools-protocol/tot/Emulation/#method-setCPUThrottlingRate)
- [MusicBrainz JSON dumps](https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/)
- graph-explorer at `ad8e462` (`explore/static/js/graph.js`, `explore/vendor-assets.json`,
  `explore/__tests__/importmap-coverage.test.js`, `scripts/build-web-assets.sh`, `AGENTS.md`).
  operations-console at its current `main` (`AGENTS.md`, `scripts/check-contracts.py`).
