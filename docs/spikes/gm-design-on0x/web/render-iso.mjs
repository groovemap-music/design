// SPDX-License-Identifier: MIT
// 2.5D renderer: the same planes, hulls, edges, and labels drawn with Canvas 2D in an orthographic
// projection. The camera turns about the vertical axis and tilts, but there is no perspective and no
// depth buffer; planes paint bottom to top and nodes back to front.

import { W, D, roundedHull } from '../lib/layout.mjs';
import { STATES, EDGE_KINDS, PLANES } from '../lib/model.mjs';
import { placeLabels } from '../lib/labels.mjs';
import { tok } from './ui.mjs';

const GAP = 24, CAM = { az: 0.42, el: 0.52, zoom: 1 }, LABEL_DEPTH = 1;
const HULL_TOKS = ['--h1', '--h2', '--h3', '--h4'];

export default class IsoStrata {
  constructor(stage, view, app, { edges }) {
    Object.assign(this, { stage, view, app, drawn: edges });
    this.reduce = app.reduce;
    this.canvas = document.createElement('canvas'); stage.prepend(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    this.labelsEl = stage.querySelector('.labels'); this.labelsEl.textContent = '';
    this.cam = { ...CAM }; this.solo = null; this.selected = null; this.selSet = null;
    this.c = { planeFill: tok('--plane-fill'), planeLine: tok('--plane-line'), vline: tok('--vline'), accent: tok('--accent'), bad: tok('--s-bad') };
    this.stateCol = Object.fromEntries(Object.entries(STATES).map(([k, s]) => [k, tok(s.tok)]));
    this.edgeCol = Object.fromEntries(Object.entries(EDGE_KINDS).map(([k, s]) => [k, tok(s.tok)]));
    this.labelEls = new Map();
    this.planeEls = PLANES.map((p, i) => { const el = document.createElement('div'); el.className = 'plbl'; el.innerHTML = `L${i}<b></b>`; el.querySelector('b').textContent = p; this.labelsEl.appendChild(el); return el; });
    this.hulls = [0, 1, 2].map((l) => {
      const byG = new Map();
      for (const n of view.nodes) if (n.level === l) { const g = view.groupOf(n); if (!byG.has(g)) byG.set(g, []); byG.get(g).push(n); }
      let gi = 0;
      return [...byG].map(([g, ns]) => ({ g, ns, poly: roundedHull(ns.map((n) => [n.x, n.z]), Math.max(...ns.map((n) => n.size)) + 2.2), color: tok(HULL_TOKS[gi++ % 4]) }));
    });
    const cv = this.canvas; let down = null;
    cv.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY, moved: false }; cv.setPointerCapture(e.pointerId); });
    cv.addEventListener('pointermove', (e) => { if (!down) return; const dx = e.clientX - down.x, dy = e.clientY - down.y; if (Math.abs(dx) + Math.abs(dy) > 3) down.moved = true; this.orbit(-dx * 0.0085); this.tilt(dy * 0.006); down.x = e.clientX; down.y = e.clientY; });
    cv.addEventListener('pointerup', (e) => { if (down && !down.moved) this.app.select(this.pick(e.clientX, e.clientY)); down = null; });
    this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(stage);
    this.resize(); this.update();
  }

  resize() {
    const w = this.stage.clientWidth, h = this.stage.clientHeight, r = Math.min(devicePixelRatio || 1, 2);
    if (!w || !h) return;
    this.canvas.width = w * r; this.canvas.height = h * r; this.w = w; this.h = h; this.pr = r; this.dirty = true;
  }
  yOf(level) { return (2 - level) * GAP; }
  frame() {
    const { az, el, zoom } = this.cam, w = this.w, h = this.h;
    const ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el);
    const levels = this.solo == null ? 3 : 1;
    const s = Math.min(w / 160, h / (150 * se + (levels - 1) * GAP * ce + 40)) * zoom;
    const fy = this.solo == null ? GAP : this.yOf(this.solo);
    const cx = w / 2, cy = h / 2;
    this.P = (x, y, z) => { const xr = x * ca - z * sa, zr = x * sa + z * ca; return [cx + s * xr, cy - s * (y - fy) * ce + s * zr * se, zr]; };
    this.s = s; this.se = se;
  }
  update() { this.dirty = true; }

  render() {
    const t0 = performance.now();
    this.frame();
    const g = this.ctx, v = this.view, P = this.P, s = this.s, se = this.se, set = this.selSet;
    g.setTransform(this.pr, 0, 0, this.pr, 0, 0); g.clearRect(0, 0, this.w, this.h);
    const bw = (W + 14) / 2, bd = (D + 14) / 2;
    for (let l = 2; l >= 0; l--) {
      if (this.solo != null && l !== this.solo) continue;
      const y = this.yOf(l);
      g.beginPath(); for (const [x, z] of [[-bw, -bd], [bw, -bd], [bw, bd], [-bw, bd]]) { const p = P(x, y, z); g.lineTo(p[0], p[1]); } g.closePath();
      g.globalAlpha = 0.3; g.fillStyle = this.c.planeFill; g.fill(); g.globalAlpha = 0.9; g.strokeStyle = this.c.planeLine; g.lineWidth = 1; g.stroke();
      for (const hu of this.hulls[l]) {
        const dim = set && !hu.ns.some((n) => set.has(n));
        g.beginPath(); for (const [x, z] of hu.poly) { const p = P(x, y, z); g.lineTo(p[0], p[1]); } g.closePath();
        g.fillStyle = hu.color; g.globalAlpha = dim ? 0.03 : 0.09; g.fill(); g.strokeStyle = hu.color; g.globalAlpha = dim ? 0.12 : 0.55; g.stroke();
      }
      for (const e of this.drawn) {
        if (e.na.level !== l) continue;
        const a = P(e.na.x, y, e.na.z), b = P(e.nb.x, y, e.nb.z);
        g.globalAlpha = set && !(set.has(e.na) && set.has(e.nb)) ? 0.1 : 0.85; g.strokeStyle = this.edgeCol[e.kind]; g.lineWidth = Math.max(1, EDGE_KINDS[e.kind].w * s);
        g.setLineDash(EDGE_KINDS[e.kind].dash ? [1.4 * s, 1.2 * s] : []);
        g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
      }
      g.setLineDash([]);
      // Vertical links from this plane's nodes down to their children on the plane below.
      if (this.solo == null && l < 2) {
        g.lineWidth = 1; g.strokeStyle = this.c.vline; g.globalAlpha = set ? 0.07 : 0.32; g.beginPath();
        for (const n of v.nodes) if (n.level === l + 1) { const p = v.byId.get(n.parent); const a = P(n.x, this.yOf(n.level) + n.h, n.z), b = P(p.x, y, p.z); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); }
        g.stroke();
      }
      const ns = v.nodes.filter((n) => n.level === l).map((n) => ({ n, p: P(n.x, y + n.h, n.z) })).sort((a, b) => a.p[2] - b.p[2]);
      const byCol = new Map();
      for (const it of ns) { const k = this.stateCol[v.state(it.n)] + (set && !set.has(it.n) ? '|d' : ''); if (!byCol.has(k)) byCol.set(k, []); byCol.get(k).push(it); }
      for (const [k, list] of byCol) {
        const [col, dim] = k.split('|'); g.fillStyle = col; g.globalAlpha = dim ? 0.18 : 1; g.beginPath();
        for (const { n, p } of list) { const r = n.size * s; g.moveTo(p[0] + r, p[1]); if (n.kind === 'disc') g.ellipse(p[0], p[1], r, r * se, 0, 0, Math.PI * 2); else g.arc(p[0], p[1], r, 0, Math.PI * 2); }
        g.fill();
      }
      g.globalAlpha = 0.9; g.strokeStyle = this.c.bad; g.lineWidth = 1.2; g.beginPath();
      for (const { n, p } of ns) if (n.prov === 'mb') { const r = n.size * 1.75 * s; g.moveTo(p[0] + r, p[1]); g.ellipse(p[0], p[1], r, r * se, 0, 0, Math.PI * 2); }
      g.stroke();
    }
    if (this.selected) { const n = this.selected; const p = P(n.x, this.yOf(n.level), n.z); const r = n.size * 2.2 * s; g.globalAlpha = 1; g.strokeStyle = this.c.accent; g.lineWidth = 2; g.beginPath(); g.ellipse(p[0], p[1], r, r * se, 0, 0, Math.PI * 2); g.stroke(); }
    g.globalAlpha = 1;
    this.layoutLabels();
    this.dirty = false;
    this.lastWorkMs = performance.now() - t0;
  }

  labelEl(n) {
    let el = this.labelEls.get(n);
    if (!el) { el = document.createElement('div'); el.className = 'lbl' + (n.level === 0 ? ' l0' : ''); el.textContent = n.label; this.labelsEl.appendChild(el); this.labelEls.set(n, el); n.elW = n.label.length * (n.level === 0 ? 7.6 : 6.4) + 12; }
    return el;
  }
  layoutLabels() {
    const P = this.P, w = this.w, h = this.h, set = this.selSet;
    const depth = LABEL_DEPTH + (this.cam.zoom > 1.6 ? 3 : this.cam.zoom > 1.15 ? 1 : 0) + (this.solo != null ? 3 : 0);
    const items = [];
    const consider = new Set(this.view.nodes.filter((n) => n.level <= depth || (set && set.has(n))));
    for (const [n, el] of this.labelEls) if (!consider.has(n)) el.style.visibility = 'hidden';
    for (const n of consider) {
      if (this.solo != null && n.level !== this.solo) { if (this.labelEls.has(n)) this.labelEls.get(n).style.visibility = 'hidden'; continue; }
      const inSel = set && set.has(n);
      const p = n === this.selected ? 0 : inSel ? 0.5 + n.level * 0.1 : n.level <= depth && !set ? 1 + n.level : null;
      if (p == null) { if (this.labelEls.has(n)) this.labelEls.get(n).style.visibility = 'hidden'; continue; }
      const q = P(n.x, this.yOf(n.level) + n.h, n.z);
      const el = this.labelEl(n);
      items.push({ el, node: n, p, x: q[0] - n.elW / 2, y: q[1] - n.size * this.s - 18, w: n.elW, h: n.level === 0 ? 19 : 16 });
    }
    const placed = [];
    const bw = (W + 14) / 2, bd = (D + 14) / 2;
    this.planeEls.forEach((el, i) => {
      if (this.solo != null && i !== this.solo) { el.style.visibility = 'hidden'; return; }
      let best = null; for (const [cx, cz] of [[-bw, -bd], [bw, -bd], [bw, bd], [-bw, bd]]) { const q = P(cx, this.yOf(i), cz); if (!best || q[0] < best[0]) best = q; }
      const x = Math.max(4, best[0] + 6), y = best[1] - 22;
      el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`; el.style.visibility = 'visible';
      placed.push({ x, y, w: 150, h: 20 });
    });
    for (const it of placeLabels(items, placed, w, h)) { it.el.style.visibility = 'visible'; it.el.style.transform = `translate(${it.x.toFixed(1)}px, ${it.y.toFixed(1)}px)`; }
    for (const it of items) if (!it.shown) it.el.style.visibility = 'hidden';
    this.lastItems = items;
  }
  pick(cx, cy) {
    const r = this.canvas.getBoundingClientRect(); const x = cx - r.left, y = cy - r.top;
    let best = null, bd = Infinity;
    for (const n of this.view.nodes) { if (this.solo != null && n.level !== this.solo) continue; const p = this.P(n.x, this.yOf(n.level) + n.h, n.z); const d = Math.hypot(p[0] - x, p[1] - y); if (d < n.size * this.s + 2 && d < bd) { bd = d; best = n; } }
    return best;
  }
  tick(t) {
    if (this.tween) {
      const tw = this.tween, k = Math.min(1, (t - tw.t0) / tw.ms), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      for (const key of Object.keys(tw.to)) this.cam[key] = tw.from[key] + (tw.to[key] - tw.from[key]) * e;
      if (k >= 1) this.tween = null; this.dirty = true; this.tweenFrames = (this.tweenFrames || 0) + 1;
    }
    if (this.dirty) this.render();
  }
  animateTo(to, ms = 520) { if (this.reduce) { Object.assign(this.cam, to); this.dirty = true; return; } this.tween = { from: { ...this.cam }, to: { ...this.cam, ...to }, t0: performance.now(), ms }; }
  orbit(d) { this.cam.az += d; this.dirty = true; }
  tilt(d) { this.cam.el = Math.min(1.5, Math.max(0.12, this.cam.el + d)); this.dirty = true; }
  zoom(z) { if (z === 'in') this.animateTo({ zoom: Math.min(4, this.cam.zoom * 1.25) }); else if (z === 'out') this.animateTo({ zoom: Math.max(0.5, this.cam.zoom * 0.8) }); else this.animateTo({ ...CAM, el: this.solo == null ? CAM.el : 1.5 }); }
  setSolo(l) { this.solo = l; this.animateTo({ el: l == null ? CAM.el : 1.5 }); this.dirty = true; }
  select(n) { this.selected = n; this.selSet = n ? this.view.cylinder(n) : null; this.dirty = true; }
  labelBoxes() { return (this.lastItems || []).filter((it) => it.shown).map((it) => { const r = it.el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; }); }
  screenRadius(n) { this.frame(); return n.size * this.s * (n.kind === 'disc' ? this.se : 1); }
  screenPos(n) { this.frame(); const r = this.canvas.getBoundingClientRect(), p = this.P(n.x, this.yOf(n.level) + n.h, n.z); return { x: r.left + p[0], y: r.top + p[1], ok: true }; }
  nodesOnScreen() { this.frame(); let c = 0; for (const n of this.view.nodes) { const p = this.P(n.x, this.yOf(n.level), n.z); if (p[0] >= 0 && p[0] <= this.w && p[1] >= 0 && p[1] <= this.h) c++; } return c; }
  dispose() { this.ro.disconnect(); this.canvas.remove(); this.labelsEl.textContent = ''; }
}
