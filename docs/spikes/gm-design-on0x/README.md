# Harness for spike gm-design-on0x

This is throwaway code for
[Concept A's strata renderer at catalog scale](../gm-design-on0x-strata-renderer.md). It is not a
product package, and no GrooveMap service depends on it. It ports the Strata mockup's engine
(`class Strata` and `CFG_A` in the maintainer's `groovemap-strata.html`, three.js r128) into
modules that keep layout apart from rendering. The layout invariants then run under `node --test`
without a GPU.

Every fixture is generated from a seed. Names are invented syllables, and no id, title, or name
from Discogs or MusicBrainz is used. The only real-data input is `results/size_bands.json`, and it
holds aggregate counts only. Dumps, intermediate files, npm packages, and browsers stay under
`~/.cache/groovemap-spikes/`.

## Files

| File | Role |
| --- | --- |
| `lib/rng.mjs` | Seeded PRNG and invented-word labels |
| `lib/fixture.mjs` | Synthetic credit → master → release discographies at 50, 500, 5,000, and 20,000 nodes. Releases per master, the masterless share, and the undated share come from the measured size band. Each credit with masterless releases gets a no-master lane node, and undated releases and masters carry `undated` |
| `lib/model.mjs` | CFG_A's state machine: derived master and credit states, transitions, the Discogs-alias guard, the redundant-want redirect, and the read-only past |
| `lib/layout.mjs` | The mockup's time icicle, hull, and point-in-polygon code, the undated lane at the left edge of the year axis, and the invariants: hull intrusions, node overlaps, same-plane edge crossings, and the planar edge rule |
| `lib/view.mjs` | What gets drawn: every node (the mockup) or the aggregation rule under a per-plane node budget, with paged drill-down. `fitView` tightens the budget until each plane's footprints fit its depth |
| `lib/labels.mjs` | The mockup's greedy label placement and an overlap census |
| `web/` | The harness page. One renderer per load: `webgl` (the mockup engine as is), `webgl-inst` (the same scene with instancing and occlusion-resolving picking), `iso` (2.5D Canvas 2D), and `d3` (graph-explorer's force graph) |
| `scripts/serve.mjs` | Static server with a strict Content-Security-Policy. It serves vendor files only when their SHA-256 matches the pins |
| `scripts/size_bands_discogs.py` | The size bands: a read-only query over gm-design-1h2l's Discogs database |
| `scripts/layout_sweep.mjs` | Raw invariants per scale, then the budget sweep and drill-down checks |
| `scripts/measure_perf.mjs` | Playwright frame-rate and label matrix |
| `scripts/check_a11y_tasks.mjs` | Keyboard, reduced motion, the table against the model, and task reachability |
| `scripts/vendor_cost.mjs` | three.js bytes, digests, license digest, and CSP-relevant constructs |
| `test/layout.test.mjs` | The invariants as assertions |
| `results/*.json` | Aggregate outputs that the spike document cites |

## Setup

The repository has no package manifest, so the harness's packages go into a cache prefix. The
versions are exact. `serve.mjs` refuses vendor files whose digest has moved.

```sh
P=~/.cache/groovemap-spikes/gm-design-on0x/node
mkdir -p $P && cd $P && echo '{"private":true}' > package.json
npm install --no-audit --no-fund playwright@1.64.1 three@0.186.1 d3@7.9.0
npx playwright install chromium firefox webkit
```

`playwright install` can garbage-collect browser revisions that other checkouts' Playwright
versions use. Afterwards, re-run their own `playwright install`.

## Reproducing

Run everything from this directory. Node 24 or later is assumed.

```sh
# 1. Size bands (aggregate counts only) from gm-design-1h2l's Discogs 20261001 database,
#    opened read-only. See gm-design-1h2l's README for how it is built.
uv run --no-project --with duckdb==2.0.0 python -I scripts/size_bands_discogs.py \
  ~/.cache/groovemap-spikes/gm-design-1h2l/spike.duckdb > results/size_bands.json

# 2. Layout invariants and the budget sweep (10 seeds per scale; about 4 and 9 minutes on an M1 Pro).
LAYOUT=mockup SEEDS=10 node scripts/layout_sweep.mjs > results/layout-mockup.json
LAYOUT=spaced SEEDS=10 node scripts/layout_sweep.mjs > results/layout.json
node --test test/*.test.mjs

# 3. Browser measurements. Browsers run headed, so windows open on the screen. Keep the machine
#    otherwise idle and on mains power.
node scripts/measure_perf.mjs --budget 3,12,16 --layout spaced > results/perf.json
node scripts/check_a11y_tasks.mjs --budget 3,12,16 --layout spaced > results/a11y_tasks.json
node scripts/vendor_cost.mjs > results/vendoring.json

# 4. Walk the three tasks by hand.
node scripts/serve.mjs 8765
# then open http://127.0.0.1:8765/web/index.html?r=webgl-inst&n=5000&budget=3,12,16&spaced=1
```

Step 2's chosen layout and budget feed steps 3 and 4. The values shown are the ones in
`results/layout.json`. If a re-run picks a different budget, pass that one instead.

### Harness page parameters

| Parameter | Values |
| --- | --- |
| `r` | `webgl`, `webgl-inst`, `iso`, `d3` |
| `n` | target node count (the fixture lands within one node of it) |
| `seed` | fixture seed, default 1 |
| `budget` | `b0,b1,b2` per-plane node budget. Omit it to draw everything, as the mockup does |
| `spaced` | `1` for the spaced icicle, with `fitView`'s footprint check |
| `pick` | `depth` (the mockup: nearest hit) or `resolve` (all hits, nearest projected centre). The default is `resolve` for `webgl-inst` and `depth` for `webgl` |
| `gutter` | world units between top-level groups |
| `edges` | `planar` (default) or `all` (the mockup) |

`window.__h.app` exposes `orbitFor(ms)`, `census()`, and the model, view, and renderer to the
measurement scripts.

## Shared data

The harness reads gm-design-1h2l's DuckDB file (`~/.cache/groovemap-spikes/gm-design-1h2l/spike.duckdb`)
read-only and downloads nothing. The molecule's convention for the shared dump cache
(`~/.cache/groovemap-spikes/dumps/`) is a `dumps/<file>.lock` directory made with `mkdir` around
a download to `<file>.part`, verified and renamed before the lock is removed, and
`dumps/.fetch.lock` around every request to data.discogs.com. Releases dumps are streamed, never
cached.
