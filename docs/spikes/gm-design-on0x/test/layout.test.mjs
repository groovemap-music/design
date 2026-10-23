// SPDX-License-Identifier: MIT
// GPU-free assertions for the strata layout: the mockup readouts (hull intrusions, same-plane edge
// crossings) become invariants, together with node overlap and the aggregation budget.
//   node --test test/

import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { generate, SCALES } from '../lib/fixture.mjs';
import { Model, DISCOGS_BLOCK, PAST_BLOCK } from '../lib/model.mjs';
import { fitView } from '../lib/view.mjs';
import { hull, inPoly, layoutModel, invariants, drawnEdges, samePlaneCrossings, segmentsCross, UNDATED_X } from '../lib/layout.mjs';
import { placeLabels, overlapCensus } from '../lib/labels.mjs';

const HERE = dirname(dirname(fileURLToPath(import.meta.url)));
const bands = JSON.parse(readFileSync(join(HERE, 'results/size_bands.json'), 'utf8'));
const measured = JSON.parse(readFileSync(join(HERE, 'results/layout.json'), 'utf8'));
const BEST = measured.sweep.best;
const build = (n, seed, opts = {}) => {
  const m = new Model(generate({ nodes: n, seed, bands }));
  const v = fitView(m, { ...opts, spaced: measured.layout === 'spaced' });
  return { m, v };
};

test('ported geometry helpers behave as the mockup', () => {
  assert.deepEqual(hull([[0, 0], [2, 0], [2, 2], [0, 2], [1, 1]]).length, 4);
  assert.equal(inPoly([1, 1], [[0, 0], [2, 0], [2, 2], [0, 2]]), true);
  assert.equal(inPoly([3, 1], [[0, 0], [2, 0], [2, 2], [0, 2]]), false);
  assert.equal(segmentsCross([0, 0, 2, 2, false], [0, 2, 2, 0, false]), true);
  assert.equal(segmentsCross([0, 0, 1, 0, false], [2, 0, 3, 0, false]), false);
  assert.equal(segmentsCross([0, 0, 2, 0, false], [1, 0, 3, 0, false]), true, 'collinear overlap is a crossing');
});

test('fixtures are deterministic and hit their scale', () => {
  for (const n of SCALES) {
    const a = generate({ nodes: n, seed: 3, bands }), b = generate({ nodes: n, seed: 3, bands });
    assert.deepEqual(a, b);
    assert.ok(Math.abs(a.nodes.length - n) <= 1, `${n}: ${a.nodes.length}`);
    assert.ok(a.nodes.every((x) => !/\d{5,}/.test(x.label)), 'labels carry no id-like numbers');
  }
});

test('state machine guards match CFG_A', () => {
  const { m } = build(500, 1);
  const mb = m.nodes.find((x) => x.prov === 'mb' && m.recorded(x) === 'none');
  assert.equal(m.blockedReason(mb), DISCOGS_BLOCK);
  const ownedMaster = m.nodes.find((x) => x.level === 1 && x.children.some((k) => m.recorded(k) === 'owned') && x.children.some((k) => k.prov === 'discogs' && m.recorded(k) === 'none'));
  const sib = ownedMaster.children.find((k) => k.prov === 'discogs' && m.recorded(k) === 'none');
  const res = m.applyTransition(sib, 0);
  assert.equal(res.to, 'redundant', 'a want beside an owned pressing is recorded as redundant');
  m.T = 2015;
  assert.equal(m.blockedReason(sib), PAST_BLOCK);
});

test('the mockup layout breaks its own readouts past mockup scale', () => {
  const { v } = build(500, 1);
  const inv = invariants(v, { policy: 'all' });
  assert.ok(inv.planes.some((p) => p.intrusions > 0));
  assert.ok(inv.crossings > 0);
});

test('the planar edge rule draws no same-plane crossing at any scale, unaggregated', () => {
  for (const n of SCALES) for (const seed of [1, 2]) {
    const { v } = build(n, seed);
    assert.equal(samePlaneCrossings(v, drawnEdges(v, 'planar')), 0, `${n}/${seed}`);
  }
});

test('aggregation keeps every plane under the measured budget with the invariants at zero', () => {
  for (const n of SCALES) for (const seed of [1, 2, 3]) {
    const { m, v } = build(n, seed, { budget: BEST.budget, gutter: BEST.gutter });
    v.perPlane().forEach((c, l) => assert.ok(c <= BEST.budget[l], `${n}/${seed} plane ${l}: ${c}`));
    const inv = invariants(v, { policy: 'planar' });
    for (const p of inv.planes) { assert.equal(p.intrusions, 0, `${n}/${seed} L${p.level} intrusions`); assert.equal(p.overlaps, 0, `${n}/${seed} L${p.level} overlaps`); }
    assert.equal(inv.crossings, 0);
    // Nothing is lost: every visible model node is drawn or held by exactly one count node.
    const held = new Map();
    for (const x of v.nodes) for (const mem of x.members) held.set(mem, (held.get(mem) || 0) + 1);
    for (const x of m.nodes) if (m.vis.has(x)) assert.equal(held.get(x), 1, `${x.id} held ${held.get(x)}`);
  }
});

test('paging through a master keeps every pressing in the view', () => {
  const m = new Model(generate({ nodes: 5000, seed: 1, bands }));
  const big = m.nodes.filter((x) => x.level === 1).sort((a, b) => b.children.length - a.children.length)[0];
  for (let page = 0; page < 4; page++) {
    const v = fitView(m, { budget: BEST.budget, focus: { id: big.id, page }, spaced: measured.layout === 'spaced' });
    const held = new Map();
    for (const x of v.nodes) for (const mem of x.members) held.set(mem, (held.get(mem) || 0) + 1);
    for (const x of m.nodes) if (m.vis.has(x)) assert.equal(held.get(x), 1, `page ${page}: ${x.id} held ${held.get(x)}`);
  }
});

test('the no-master and undated lanes are always drawn or reachable', () => {
  for (const n of SCALES) for (const seed of [1, 2]) {
    const { m, v } = build(n, seed, { budget: BEST.budget, gutter: BEST.gutter });
    const lanes = m.nodes.filter((x) => x.lane === 'nomaster' && m.vis.has(x));
    assert.ok(lanes.length > 0, `${n}/${seed}: fixture has a no-master lane`);
    for (const lane of lanes) {
      const rep = v.rep.get(lane);
      assert.ok(rep, `${lane.id} reachable`);
      if (!rep.agg) assert.equal(rep.lane, 'nomaster', 'a drawn lane stays a lane, never a decade bucket');
    }
    const undated = m.nodes.filter((x) => x.undated && m.vis.has(x));
    assert.ok(undated.length > 0, `${n}/${seed}: fixture has undated nodes`);
    for (const x of v.nodes) if (x.undated) assert.equal(x.x, UNDATED_X, `${x.id} sits in the undated lane`);
  }
});

test('label placement never shows two overlapping labels below priority 0', () => {
  const items = Array.from({ length: 200 }, (_, i) => ({ p: 1 + (i % 3), x: (i * 37) % 600, y: (i * 53) % 400, w: 80, h: 16 }));
  const shown = placeLabels(items, [], 800, 600);
  assert.equal(overlapCensus(shown).pairs, 0);
  assert.ok(shown.length < items.length);
});
