// SPDX-License-Identifier: MIT
// Today's 2D graph: graph-explorer's GraphVisualization._render (explore/static/js/graph.js) force
// simulation, SVG circles, and always-on truncated labels, with node fill switched from entity type
// to collector state so the three tasks are possible at all. "Orbit" pans the zoom transform.

import { STATES } from '../lib/model.mjs';
import { tok } from './ui.mjs';

export default class D3Graph {
  constructor(stage, view, app, { edges }) {
    const d3 = window.d3;
    Object.assign(this, { stage, view, app, d3 });
    this.labelsEl = stage.querySelector('.labels'); this.labelsEl.textContent = '';
    this.svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); stage.prepend(this.svgEl);
    const width = stage.clientWidth, height = stage.clientHeight;
    this.w = width; this.h = height;
    this.svg = d3.select(this.svgEl).attr('width', width).attr('height', height);
    this.g = this.svg.append('g');
    this.zoomB = d3.zoom().scaleExtent([0.02, 4]).on('zoom', (e) => { this.t = e.transform; this.g.attr('transform', e.transform); });
    this.svg.call(this.zoomB);
    this.t = d3.zoomIdentity;
    this.stateCol = Object.fromEntries(Object.entries(STATES).map(([k, s]) => [k, tok(s.tok)]));
    this.nodes = view.nodes.map((n) => ({ id: n.id, n, isCenter: n.id === 'c0', isCategory: n.level === 0 && n.id !== 'c0' }));
    const byId = new Map(this.nodes.map((d) => [d.id, d]));
    this.links = view.nodes.filter((n) => n.parent).map((n) => ({ source: n.parent, target: n.id })).concat(edges.map((e) => ({ source: e.na.id, target: e.nb.id, lateral: true })));
    const radius = (d) => (d.isCenter ? 28 : d.isCategory ? 22 : 14);
    this.radius = radius;
    // Same forces and constants as graph.js _render().
    this.sim = d3.forceSimulation(this.nodes)
      .force('link', d3.forceLink(this.links).id((d) => d.id).distance((d) => (d.source.isCenter || d.target.isCenter ? 120 : d.source.isCategory || d.target.isCategory ? 80 : 60)))
      .force('charge', d3.forceManyBody().strength((d) => (d.isCenter ? -400 : d.isCategory ? -200 : -80)))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius((d) => radius(d) + 5));
    this.link = this.g.append('g').selectAll('line').data(this.links).join('line').attr('stroke', tok('--vline')).attr('stroke-opacity', 0.5).attr('stroke-width', 1);
    this.node = this.g.append('g').selectAll('g').data(this.nodes).join('g').style('cursor', 'pointer').on('click', (e, d) => { e.stopPropagation(); app.select(d.n); });
    this.node.append('circle').attr('r', radius).attr('stroke', (d) => (d.n.prov === 'mb' ? tok('--s-bad') : 'rgba(255,255,255,0.3)')).attr('stroke-width', (d) => (d.n.prov === 'mb' ? 2.5 : 1));
    this.node.append('title').text((d) => `${d.n.label} [${['credit', 'master', 'release'][d.n.level]}]`);
    this.text = this.node.append('text').attr('class', 'node-label').attr('text-anchor', 'middle').attr('dy', (d) => radius(d) + 14).attr('fill', tok('--fg'))
      .style('font-size', (d) => (d.isCenter ? '13px' : '10px')).text((d) => (d.n.label.length > 20 ? d.n.label.substring(0, 18) + '...' : d.n.label));
    this.ticks = 0;
    this.sim.on('tick', () => { this.ticks++; this.dirty = true; });
    if (app.reduce) this.reduceNote = 'graph.js has no reduced-motion path; the simulation animates regardless';
    this.update();
  }

  update() {
    const set = this.selSet;
    this.node.select('circle').attr('fill', (d) => this.stateCol[this.view.state(d.n)]).attr('opacity', (d) => (set && !set.has(d.n) ? 0.18 : 1));
    this.dirty = true;
  }
  render() {
    const t0 = performance.now();
    this.link.attr('x1', (d) => d.source.x).attr('y1', (d) => d.source.y).attr('x2', (d) => d.target.x).attr('y2', (d) => d.target.y);
    this.node.attr('transform', (d) => `translate(${d.x},${d.y})`);
    this.dirty = false;
    this.lastWorkMs = performance.now() - t0;
  }
  tick() { if (this.dirty) this.render(); }
  // Settle as graph.js would (simulation 'end' -> fitToView), synchronously, capped at 300 ticks.
  settle(maxMs = 20000) {
    const t0 = performance.now();
    this.sim.stop();
    while (this.sim.alpha() > this.sim.alphaMin() && performance.now() - t0 < maxMs) { this.sim.tick(); this.ticks++; }
    this.fit(); this.render();
    return { ticks: this.ticks, ms: performance.now() - t0, settled: this.sim.alpha() <= this.sim.alphaMin() };
  }
  fit() {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const d of this.nodes) { minX = Math.min(minX, d.x); minY = Math.min(minY, d.y); maxX = Math.max(maxX, d.x); maxY = Math.max(maxY, d.y); }
    const pad = 60, scale = Math.min((this.w - pad * 2) / (maxX - minX || 1), (this.h - pad * 2) / (maxY - minY || 1), 1.5);
    this.svg.call(this.zoomB.transform, this.d3.zoomIdentity.translate(this.w / 2 - (minX + maxX) / 2 * scale, this.h / 2 - (minY + maxY) / 2 * scale).scale(scale));
  }
  orbit(d) { this.svg.call(this.zoomB.translateBy, d * 120, 0); this.dirty = true; }
  tilt(d) { this.svg.call(this.zoomB.translateBy, 0, d * 120); }
  zoom(z) { if (z === 'in') this.svg.call(this.zoomB.scaleBy, 1.4); else if (z === 'out') this.svg.call(this.zoomB.scaleBy, 0.7); else this.fit(); }
  setSolo() {}
  select(n) { this.selected = n; this.selSet = n ? this.view.cylinder(n) : null; this.update(); }
  labelBoxes() {
    const out = [];
    this.text.each(function () { const r = this.getBoundingClientRect(); if (r.width && r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight) out.push({ x: r.x, y: r.y, w: r.width, h: r.height }); });
    return out;
  }
  // Proper crossings among drawn links at their settled positions (shared endpoints excluded).
  crossings() {
    const segs = this.links.map((l) => [l.source.x, l.source.y, l.target.x, l.target.y, l.source, l.target]);
    const o = (ax, ay, bx, by, cx, cy) => Math.sign((bx - ax) * (cy - ay) - (by - ay) * (cx - ax));
    let c = 0;
    segs.sort((a, b) => Math.min(a[0], a[2]) - Math.min(b[0], b[2]));
    for (let i = 0; i < segs.length; i++) {
      const a = segs[i], amax = Math.max(a[0], a[2]);
      for (let j = i + 1; j < segs.length; j++) {
        const b = segs[j];
        if (Math.min(b[0], b[2]) > amax) break;
        if (a[4] === b[4] || a[4] === b[5] || a[5] === b[4] || a[5] === b[5]) continue;
        if (o(a[0], a[1], a[2], a[3], b[0], b[1]) * o(a[0], a[1], a[2], a[3], b[2], b[3]) < 0 && o(b[0], b[1], b[2], b[3], a[0], a[1]) * o(b[0], b[1], b[2], b[3], a[2], a[3]) < 0) c++;
      }
    }
    return c;
  }
  screenRadius(n) { const d = this.nodes.find((x) => x.n === n); return this.radius(d) * this.t.k; }
  screenPos(n) { const d = this.nodes.find((x) => x.n === n); const r = this.svgEl.getBoundingClientRect(); const [x, y] = this.t.apply([d.x, d.y]); return { x: r.left + x, y: r.top + y, ok: true }; }
  pick(cx, cy) { const el = document.elementFromPoint(cx, cy); const g = el && el.closest('g'); const d = g && this.d3.select(g).datum(); return d && d.n ? d.n : null; }
  nodesOnScreen() { let c = 0; for (const d of this.nodes) { const [x, y] = this.t.apply([d.x, d.y]); if (x >= 0 && x <= this.w && y >= 0 && y <= this.h) c++; } return c; }
  dispose() { this.sim.stop(); this.svgEl.remove(); this.labelsEl.textContent = ''; }
}
