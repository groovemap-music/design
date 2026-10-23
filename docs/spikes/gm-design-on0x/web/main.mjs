// SPDX-License-Identifier: MIT
// Harness entry: builds fixture -> model -> view -> layout, mounts one renderer, and exposes
// window.__h for scripts/measure.mjs. Query: ?r=webgl|webgl-inst|iso|d3&n=500&seed=1
// &budget=b0,b1,b2&gutter=0&edges=planar|all

import { generate } from '../lib/fixture.mjs';
import { Model } from '../lib/model.mjs';
import { fitView } from '../lib/view.mjs';
import { hullIntrusions, drawnEdges, samePlaneCrossings } from '../lib/layout.mjs';
import { overlapCensus } from '../lib/labels.mjs';
import { Chrome } from './ui.mjs';

const P = new URLSearchParams(location.search);
const opts = {
  r: P.get('r') || 'webgl',
  n: +(P.get('n') || 500),
  seed: +(P.get('seed') || 1),
  budget: P.get('budget') ? P.get('budget').split(',').map(Number) : null,
  gutter: +(P.get('gutter') || 0),
  edges: P.get('edges') || 'planar',
  spaced: P.get('spaced') === '1',
  pick: P.get('pick') || null,
};
const REDUCE = matchMedia('(prefers-reduced-motion: reduce)').matches;
const RENDERERS = { webgl: './render-webgl.mjs', 'webgl-inst': './render-webgl.mjs', iso: './render-iso.mjs', d3: './render-d3.mjs' };

class App {
  constructor() {
    this.opts = opts; this.reduce = REDUCE; this.selected = null; this.pinned = new Set(); this.flash = '';
    this.metrics = { opts, reduce: REDUCE, ua: navigator.userAgent, dpr: devicePixelRatio, viewport: [innerWidth, innerHeight] };
    this.errors = [];
    addEventListener('error', (e) => this.errors.push(String(e.message)));
    this.csp = [];
    document.addEventListener('securitypolicyviolation', (e) => this.csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  }

  async boot() {
    const t0 = performance.now();
    const bands = await (await fetch('/results/size_bands.json')).json();
    const fx = generate({ nodes: opts.n, seed: opts.seed, bands });
    const t1 = performance.now();
    this.metrics.generateMs = t1 - t0;
    this.metrics.fixtureNodes = fx.nodes.length;
    this.model = new Model(fx);
    const tm = performance.now();
    this.Renderer = (await import(RENDERERS[opts.r])).default;
    const t2 = performance.now();
    this.build();
    await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
    const t3 = performance.now();
    // Time to first frame: data in memory -> model, view, layout, scene, first render, labels -> the
    // second animation frame after the first render (the first one that can show it).
    this.metrics.modelMs = tm - t1;
    this.metrics.ttffMs = (tm - t1) + (t3 - t2);
    this.metrics.buildMs = this.buildMs;
    this.chrome.renderPanel();
    this.loop();
    return this.metrics;
  }

  build() {
    const tb = performance.now();
    if (this.renderer) this.renderer.dispose();
    this.view = this.viewFor({ pinned: this.pinned, focus: this.focus });
    const edges = drawnEdges(this.view, opts.edges, this.selected);
    const inv = { perPlane: this.view.perPlane(), hulls: 0, intrusions: 0, edges: edges.length, crossings: samePlaneCrossings(this.view, edges) };
    for (const l of [0, 1, 2]) { const h = hullIntrusions(this.view, l); inv.hulls += h.hulls; inv.intrusions += h.intrusions; }
    this.inv = inv;
    if (!this.chrome) this.chrome = new Chrome(this);
    this.chrome.readout(inv);
    this.renderer = new this.Renderer(document.querySelector('.stage'), this.view, this, { mode: opts.r === 'webgl-inst' ? 'inst' : 'mesh', edges, pick: opts.pick });
    this.renderer.render();
    this.buildMs = performance.now() - tb;
  }

  loop() {
    const step = (t) => {
      if (this.spin) this.renderer.orbit(this.spin.rate * (t - (this.spin.last ?? t)));
      if (this.spin) this.spin.last = t;
      this.renderer.tick(t);
      if (this.frameHook) this.frameHook(t);
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // Orbit at one turn per 8 s for `ms`, recording every animation-frame interval.
  orbitFor(ms) {
    return new Promise((resolve) => {
      const deltas = []; let last = null; let start = null;
      const work = [];
      this.spin = { rate: (Math.PI * 2) / 8000 };
      this.frameHook = (t) => {
        if (last != null) deltas.push(t - last);
        last = t; if (start == null) start = t;
        if (this.renderer.lastWorkMs != null) work.push(this.renderer.lastWorkMs);
        if (t - start >= ms) { this.spin = null; this.frameHook = null; resolve({ deltas, work }); }
      };
    });
  }

  census() {
    const r = this.renderer;
    const all = r.labelBoxes();
    // A label under 8 CSS px tall is not legible text, so it does not count as shown.
    const boxes = all.filter((b) => b.h >= 8);
    const c = overlapCensus(boxes);
    return { d3Crossings: r.crossings ? r.crossings() : undefined, onScreen: r.nodesOnScreen(), labelsRendered: all.length, labelsShown: c.boxes, overlapPairs: c.pairs, cleanLabels: c.clean, perPlane: this.view.perPlane(), inv: this.inv };
  }

  select(n) { this.selected = n || null; this.flash = ''; this.renderer.select(this.selected); this.chrome.renderPanel(); }
  transition(i) {
    const n = this.selected; if (!n || !n.ref) return;
    const res = this.model.applyTransition(n.ref, i);
    this.flash = res.ok ? `Recorded: ${res.to}${res.warn ? ' (' + res.warn + ')' : ''}` : res.reason;
    this.renderer.update(); this.chrome.renderPanel();
  }
  viewFor({ pinned, focus }) {
    return fitView(this.model, { budget: opts.budget, pinned, focus, spaced: opts.spaced, gutter: opts.gutter });
  }

  // Drill-down. A pressings count node pages its master's pressings onto the release plane. A
  // masters or credits count node pins one page of its members (half the plane's budget) and the
  // aggregation rule folds everything else to make room; the rest of the group stays folded.
  // `seen` remembers what earlier pages showed, so opening the same count node again moves on to
  // the next page instead of swapping two pages back and forth.
  drill(state, n) {
    const seen = state.seen || new Set();
    if (n.level === 2) return { pinned: state.pinned, seen, focus: { id: n.parent, page: n.next && state.focus ? state.focus.page + 1 : 0 }, keep: n.parent };
    const b = opts.budget || [8, 40, 80];
    const top = n.members.filter((x) => x.level === n.level).sort((a, c) => (a.year || 0) - (c.year || 0));
    let fresh = top.filter((x) => !seen.has(x.id));
    if (!fresh.length) { for (const x of top) seen.delete(x.id); fresh = top; }
    const page = fresh.slice(0, Math.max(1, Math.floor(b[n.level] / 2)));
    for (const x of page) seen.add(x.id);
    return { pinned: new Set(page.map((x) => x.id)), seen, focus: null, keep: page[0].id };
  }
  expand(n) {
    if (!n || !n.agg) return;
    const next = this.drill({ pinned: this.pinned, focus: this.focus, seen: this.seen }, n);
    this.pinned = next.pinned; this.focus = next.focus; this.seen = next.seen;
    this.selected = null; this.build();
    this.select(this.view.byId.get(next.keep) || null);
  }
  setValid(V) { this.model.V = V; this.model.computeVis(); this.selected = null; this.build(); this.chrome.renderPanel(); }
  setTx(T) { this.model.T = T; this.renderer.update(); this.chrome.renderPanel(); }
  setSolo(l) { this.renderer.setSolo(l); }
  zoom(z) { this.renderer.zoom(z); }
  orbit(d) { this.renderer.orbit(d); }
  tilt(d) { this.renderer.tilt(d); }
}

const app = new App();
window.__h = { app, ready: app.boot().catch((e) => { app.errors.push(String(e && e.stack || e)); throw e; }) };
