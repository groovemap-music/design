// SPDX-License-Identifier: MIT
// GPU-free layout evidence: invariants of the raw mockup layout at each scale, then a sweep over
// node budgets and group gutters to find the largest budget the aggregation rule holds at zero hull
// intrusions, zero node overlaps, and zero same-plane crossings.
//   node scripts/layout_sweep.mjs > results/layout.json

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { generate, SCALES } from '../lib/fixture.mjs';
import { Model } from '../lib/model.mjs';
import { View } from '../lib/view.mjs';
import { layoutModel, invariants } from '../lib/layout.mjs';

const HERE = dirname(dirname(fileURLToPath(import.meta.url)));
const bands = JSON.parse(readFileSync(join(HERE, 'results/size_bands.json'), 'utf8'));
// LAYOUT=spaced runs the sweep on the spaced icicle; the raw section always reports both.
const SPACED = process.env.LAYOUT === 'spaced';
const SEEDS = Array.from({ length: +(process.env.SEEDS || 10) }, (_, i) => i + 1);
const models = new Map();
for (const n of SCALES) for (const s of SEEDS) models.set(`${n}:${s}`, new Model(generate({ nodes: n, seed: s, bands })));

const check = (m, budget, gutter, pinned, focus, sizeScale = 1, spaced = SPACED) => {
  const v = new View(m, { budget, pinned, focus, sizeScale });
  layoutModel(v, { gutter, spaced });
  const all = invariants(v, { policy: 'all' });
  const planar = invariants(v, { policy: 'planar' });
  return { v, perPlane: v.perPlane(), intrusions: planar.planes.map((p) => p.intrusions), overlaps: planar.planes.map((p) => p.overlaps), crossingsAll: all.crossings, crossings: planar.crossings, drawnEdges: planar.drawnEdges, edgesAll: all.drawnEdges };
};
const sum = (a) => a.reduce((s, x) => s + x, 0);

// 1. The mockup layout, unaggregated.
const raw = (spaced) => SCALES.map((n) => {
  const rows = SEEDS.map((s) => check(models.get(`${n}:${s}`), null, 0, undefined, null, 1, spaced));
  const med = (f) => { const xs = rows.map(f).sort((a, b) => a - b); return xs[xs.length >> 1]; };
  return {
    scale: n,
    perPlane: [0, 1, 2].map((l) => med((r) => r.perPlane[l])),
    intrusions: [0, 1, 2].map((l) => med((r) => r.intrusions[l])),
    overlaps: [0, 1, 2].map((l) => med((r) => r.overlaps[l])),
    crossingsAllEdges: med((r) => r.crossingsAll), crossingsPlanar: Math.max(...rows.map((r) => r.crossings)),
    edgesAll: med((r) => r.edgesAll), edgesPlanar: med((r) => r.drawnEdges),
  };
});

// 2. Budget sweep. A configuration passes only if every scale and seed holds all three at zero.
const B0 = [3, 4, 5, 6, 8, 10], B1 = [12, 16, 20, 25, 30, 40, 50], B2 = [16, 20, 25, 30, 40, 50, 60, 80, 100], GUTTERS = [0, 4];
const sweep = [];
// sizeScale 0.5 halves every node's radius (the mockup's sizes are 4.2, 2.4, 1.35 world units).
for (const sizeScale of [1, 0.5]) for (const gutter of GUTTERS) for (const b0 of B0) for (const b1 of B1) for (const b2 of B2) {
  let worst = { intrusions: 0, overlaps: 0, crossings: 0, overBudget: 0 }, maxPlane = [0, 0, 0];
  for (const m of models.values()) {
    const r = check(m, [b0, b1, b2], gutter, undefined, null, sizeScale);
    worst.intrusions = Math.max(worst.intrusions, sum(r.intrusions));
    worst.overlaps = Math.max(worst.overlaps, sum(r.overlaps));
    worst.crossings = Math.max(worst.crossings, r.crossings);
    r.perPlane.forEach((c, l) => { maxPlane[l] = Math.max(maxPlane[l], c); if (c > [b0, b1, b2][l]) worst.overBudget++; });
  }
  sweep.push({ sizeScale, gutter, budget: [b0, b1, b2], pass: !worst.intrusions && !worst.overlaps && !worst.crossings && !worst.overBudget, worst, maxPlane });
}
const bestAt = (scale) => sweep.filter((x) => x.pass && x.sizeScale === scale).sort((a, b) => sum(b.maxPlane) - sum(a.maxPlane) || a.gutter - b.gutter)[0] || null;
const halfSize = bestAt(0.5);
const passing = sweep.filter((x) => x.pass && x.sizeScale === 1);
const best = passing.slice().sort((a, b) => sum(b.maxPlane) - sum(a.maxPlane) || a.gutter - b.gutter)[0] || null;
// Passing configurations that no other passing configuration beats on every plane.
const dominated = (a, b) => b.maxPlane.every((x, i) => x >= a.maxPlane[i]) && b.maxPlane.some((x, i) => x > a.maxPlane[i]);
const frontier = passing.filter((a) => !passing.some((b) => dominated(a, b)))
  .map(({ gutter, budget, maxPlane }) => ({ gutter, budget, maxPlane }))
  .filter((a, i, all) => all.findIndex((b) => b.maxPlane.join() === a.maxPlane.join()) === i)
  .sort((a, b) => sum(b.maxPlane) - sum(a.maxPlane));
// Per plane, the largest drawn count any passing configuration reached.
const perPlaneMax = [0, 1, 2].map((l) => Math.max(0, ...passing.map((x) => x.maxPlane[l])));
// What fails first at budgets just above the best one.
const near = best ? sweep.filter((x) => x.sizeScale === 1 && x.gutter === best.gutter && !x.pass && x.budget.every((b, i) => b >= best.budget[i]) && sum(x.budget) - sum(best.budget) <= 20).slice(0, 8) : [];

// 3. Expansion: open the largest release count node in every fixture at the best budget, first by
//    pinning every pressing it holds, then as a focused, paged drill-down (View focus).
const expand = (mode) => {
  let worst = { intrusions: 0, overlaps: 0, crossings: 0 }, maxPlane = [0, 0, 0], opened = 0;
  for (const m of models.values()) {
    const first = check(m, best.budget, best.gutter);
    const agg = first.v.nodes.filter((n) => n.agg && n.level === 2).sort((a, b) => b.count - a.count)[0];
    if (!agg) continue;
    opened++;
    const r = mode === 'pin' ? check(m, best.budget, best.gutter, new Set(agg.members.map((x) => x.id))) : check(m, best.budget, best.gutter, new Set(), { id: agg.parent, page: 0 });
    worst.intrusions = Math.max(worst.intrusions, sum(r.intrusions)); worst.overlaps = Math.max(worst.overlaps, sum(r.overlaps)); worst.crossings = Math.max(worst.crossings, r.crossings);
    r.perPlane.forEach((c, l) => { maxPlane[l] = Math.max(maxPlane[l], c); });
  }
  return { opened, worst, maxPlane };
};
const expansion = best ? { pinAll: expand('pin'), focusPaged: expand('focus') } : null;
// The largest drill-down page that holds the invariants at the best budget.
let pageMax = 0;
if (best) for (const per of [2, 4, 6, 8, 10, 12, 15, 20]) {
  let bad = 0;
  for (const m of models.values()) {
    const first = check(m, best.budget, best.gutter);
    for (const agg of first.v.nodes.filter((n) => n.agg && n.level === 2)) {
      const r = check(m, best.budget, best.gutter, new Set(), { id: agg.parent, page: 0, per });
      bad += sum(r.intrusions) + sum(r.overlaps) + r.crossings;
    }
  }
  if (bad === 0) pageMax = per; else break;
}

// Opening the largest masters count node: pin one page of its masters, as the harness does.
const bucketOpen = (per) => {
  let bad = 0, opened = 0, over = 0, maxPlane = [0, 0, 0];
  for (const m of models.values()) {
    const first = check(m, best.budget, best.gutter);
    const agg = first.v.nodes.filter((n) => n.agg && n.level === 1).sort((a, b) => b.count - a.count)[0];
    if (!agg) continue;
    opened++;
    const page = agg.members.filter((x) => x.level === 1).sort((a, b) => a.year - b.year).slice(0, per);
    const r = check(m, best.budget, best.gutter, new Set(page.map((x) => x.id)));
    bad += sum(r.intrusions) + sum(r.overlaps) + r.crossings;
    r.perPlane.forEach((c, l) => { maxPlane[l] = Math.max(maxPlane[l], c); if (c > best.budget[l]) over++; });
  }
  return { per, opened, violations: bad, overBudget: over, maxPlane };
};
const masterPages = best ? [2, 4, 6, 8, 10, 12].map(bucketOpen) : [];

console.log(JSON.stringify({ seeds: SEEDS.length, bands: bands.source, layout: SPACED ? 'spaced' : 'mockup', raw: { mockup: raw(false), spaced: raw(true) }, sweep: { configurations: sweep.length, passing: passing.length, best, frontier, perPlaneMax, nearFailures: near, halfSize }, expansion, drillDownPageMax: pageMax, masterPages }, null, 1));
