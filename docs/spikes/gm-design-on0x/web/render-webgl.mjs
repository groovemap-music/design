// SPDX-License-Identifier: MIT
// three.js renderer. mode 'mesh' is the mockup's Strata engine ported as-is: four meshes and one DOM
// label per node, vertical lines rebuilt on every camera move. mode 'inst' is the same scene drawn
// with InstancedMesh per plane and kind, merged edge ribbons, vertical lines rebuilt only when they
// change, and labels created only for label candidates.

import * as THREE from 'three';
import { W, D, UNDATED_X, roundedHull } from '../lib/layout.mjs';
import { STATES, EDGE_KINDS, PLANES } from '../lib/model.mjs';
import { placeLabels } from '../lib/labels.mjs';
import { tok } from './ui.mjs';

const GAP = 24, CAM = { az: 0.42, el: 0.52, r: 210 }, LABEL_DEPTH = 1;
const HULL_TOKS = ['--h1', '--h2', '--h3', '--h4'];
const GEOS = {};
function geo(kind) {
  if (GEOS[kind]) return GEOS[kind];
  let g;
  switch (kind) {
    case 'ico': g = new THREE.IcosahedronGeometry(1, 0); break;
    case 'disc': g = new THREE.CylinderGeometry(1, 1, 0.34, 32); break;
    case 'torus': g = new THREE.TorusGeometry(1, 0.075, 8, 56); break;
    case 'circle': g = new THREE.CircleGeometry(1, 36); break;
    default: g = new THREE.SphereGeometry(1, 24, 16);
  }
  return (GEOS[kind] = g);
}
// The mockup's ribbon(), returning raw positions so the instanced mode can merge them.
function ribbon(pos, ax, az, bx, bz, w, dash, shrinkA, shrinkB, arrow) {
  let dx = bx - ax, dz = bz - az; const L = Math.hypot(dx, dz) || 1; dx /= L; dz /= L;
  const nx = -dz * w / 2, nz = dx * w / 2;
  const sx = ax + dx * shrinkA, sz = az + dz * shrinkA;
  const len = Math.max(0.1, L - shrinkA - shrinkB);
  const quad = (t0, t1) => {
    const x0 = sx + dx * t0, z0 = sz + dz * t0, x1 = sx + dx * t1, z1 = sz + dz * t1;
    pos.push(x0 + nx, 0, z0 + nz, x1 + nx, 0, z1 + nz, x1 - nx, 0, z1 - nz, x0 + nx, 0, z0 + nz, x1 - nx, 0, z1 - nz, x0 - nx, 0, z0 - nz);
  };
  const body = arrow ? Math.max(0, len - 2.4) : len;
  if (dash) { for (let t = 0; t < body; t += 2.6) quad(t, Math.min(body, t + 1.4)); } else quad(0, body);
  if (arrow) {
    const hx = sx + dx * body, hz = sz + dz * body, tx = sx + dx * len, tz = sz + dz * len, aw = Math.max(w * 2.2, 1.1);
    pos.push(hx - dz * aw, 0, hz + dx * aw, tx, 0, tz, hx + dz * aw, 0, hz - dx * aw);
  }
  return pos;
}
const geomOf = (pos) => { const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); return g; };

export default class WebGLStrata {
  constructor(stage, view, app, { mode, edges, pick }) {
    Object.assign(this, { stage, view, app, mode, drawn: edges });
    this.pickMode = pick || (mode === 'inst' ? 'resolve' : 'depth');
    this.reduce = app.reduce;
    this.canvas = document.createElement('canvas');
    stage.prepend(this.canvas);
    this.labelsEl = stage.querySelector('.labels');
    this.labelsEl.textContent = '';
    this.cam = { ...CAM, fy: 1, spread: 1 };
    this.solo = null; this.selected = null; this.selSet = null; this.hover = null;
    this.c = { planeFill: tok('--plane-fill'), planeLine: tok('--plane-line'), vline: tok('--vline'), accent: tok('--accent'), bad: tok('--s-bad'), canvas: tok('--canvas') };
    this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, 1, 1, 3000);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x334455, 0.85));
    const dl = new THREE.DirectionalLight(0xffffff, 0.75); dl.position.set(40, 140, 80); this.scene.add(dl);
    this.target = new THREE.Vector3();
    this.buildPlanes();
    if (mode === 'inst') this.buildInstanced(); else this.buildMeshes();
    this.buildEdges();
    this.buildLabels();
    this.bindPointer();
    this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(stage);
    this.resize();
    this.update();
    this.applyCam();
  }

  yOf(level) { return (2 - level) * GAP * this.cam.spread; }

  buildPlanes() {
    this.planes = [];
    const ticks = []; for (let y = 1960; y <= 2020; y += 10) ticks.push(y);
    for (let i = 0; i < 3; i++) {
      const g = new THREE.Group();
      const fill = new THREE.Mesh(new THREE.PlaneGeometry(W + 14, D + 14), new THREE.MeshBasicMaterial({ color: this.c.planeFill, transparent: true, opacity: 0.3, depthWrite: false, side: THREE.DoubleSide }));
      fill.rotation.x = -Math.PI / 2; g.add(fill);
      const bw = (W + 14) / 2, bd = (D + 14) / 2;
      g.add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-bw, 0, -bd), new THREE.Vector3(bw, 0, -bd), new THREE.Vector3(bw, 0, bd), new THREE.Vector3(-bw, 0, bd)]), new THREE.LineBasicMaterial({ color: this.c.planeLine, transparent: true, opacity: 0.9 })));
      const pts = [];
      for (const t of ticks) { const x = this.view.axis.X(t); pts.push(new THREE.Vector3(x, 0.01, -bd), new THREE.Vector3(x, 0.01, bd)); }
      // The edge of the undated lane, between UNDATED_X and the first year.
      const ux = (UNDATED_X + this.view.axis.X(this.view.axis.y0)) / 2;
      pts.push(new THREE.Vector3(ux, 0.01, -bd), new THREE.Vector3(ux, 0.01, bd));
      g.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: this.c.planeLine, transparent: true, opacity: 0.35 })));
      const hulls = new THREE.Group(); g.add(hulls);
      this.scene.add(g);
      this.planes.push({ g, hulls });
    }
    this.vMain = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: this.c.vline, transparent: true }));
    this.vHi = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: this.c.accent, transparent: true, opacity: 0.75 }));
    this.scene.add(this.vMain, this.vHi);
  }

  // The mockup: mesh, halo, ring, and selection torus per node.
  buildMeshes() {
    this.pickables = [];
    for (const n of this.view.nodes) {
      const mesh = new THREE.Mesh(geo(n.kind), new THREE.MeshStandardMaterial({ roughness: 0.42, metalness: 0.08, transparent: true }));
      mesh.scale.setScalar(n.size); mesh.position.set(n.x, n.h, n.z); mesh.userData.node = n;
      const halo = new THREE.Mesh(geo('circle'), new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false }));
      halo.rotation.x = -Math.PI / 2; halo.scale.setScalar(n.size * 1.35); halo.position.set(n.x, 0.05, n.z);
      const ring = new THREE.Mesh(geo('torus'), new THREE.MeshBasicMaterial({ transparent: true }));
      ring.rotation.x = Math.PI / 2; ring.scale.setScalar(n.size * 1.75); ring.position.set(n.x, 0.15, n.z);
      const sel = new THREE.Mesh(geo('torus'), new THREE.MeshBasicMaterial({ transparent: true }));
      sel.rotation.x = Math.PI / 2; sel.scale.setScalar(n.size * 2.2); sel.position.set(n.x, 0.2, n.z); sel.visible = false;
      this.planes[n.level].g.add(mesh, halo, ring, sel);
      n.gl = { mesh, halo, ring, sel };
    }
  }

  buildInstanced() {
    this.inst = [];
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), qx = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2), qr = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2), s = new THREE.Vector3(), p = new THREE.Vector3();
    for (let l = 0; l < 3; l++) {
      const ns = this.view.nodes.filter((n) => n.level === l);
      const byKind = new Map();
      for (const n of ns) { if (!byKind.has(n.kind)) byKind.set(n.kind, []); byKind.get(n.kind).push(n); }
      for (const [kind, list] of byKind) {
        const im = new THREE.InstancedMesh(geo(kind), new THREE.MeshStandardMaterial({ roughness: 0.42, metalness: 0.08 }), list.length);
        list.forEach((n, i) => { im.setMatrixAt(i, m4.compose(p.set(n.x, n.h, n.z), q.identity(), s.setScalar(n.size))); im.setColorAt(i, new THREE.Color()); });
        im.userData.nodes = list;
        this.planes[l].g.add(im); this.inst.push(im);
      }
      if (!ns.length) continue;
      const halo = new THREE.InstancedMesh(geo('circle'), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.16, depthWrite: false }), ns.length);
      ns.forEach((n, i) => { halo.setMatrixAt(i, m4.compose(p.set(n.x, 0.05, n.z), qx, s.setScalar(n.size * 1.35))); halo.setColorAt(i, new THREE.Color()); });
      halo.userData.nodes = ns; halo.userData.halo = true;
      this.planes[l].g.add(halo); this.inst.push(halo);
      const gated = ns.filter((n) => n.prov === 'mb');
      if (gated.length) {
        const ring = new THREE.InstancedMesh(geo('torus'), new THREE.MeshBasicMaterial({ color: this.c.bad, transparent: true, opacity: 0.9 }), gated.length);
        gated.forEach((n, i) => ring.setMatrixAt(i, m4.compose(p.set(n.x, 0.15, n.z), qr, s.setScalar(n.size * 1.75))));
        this.planes[l].g.add(ring);
      }
    }
    this.selRing = new THREE.Mesh(geo('torus'), new THREE.MeshBasicMaterial({ color: this.c.accent }));
    this.selRing.rotation.x = Math.PI / 2; this.selRing.visible = false; this.scene.add(this.selRing);
    this.pickables = this.inst.filter((im) => !im.userData.halo);
  }

  buildEdges() {
    this.edgeMeshes = [];
    if (this.mode === 'inst') {
      const groups = new Map();
      for (const e of this.drawn) {
        const def = EDGE_KINDS[e.kind]; const key = `${e.na.level}:${e.kind}`;
        if (!groups.has(key)) groups.set(key, []);
        ribbon(groups.get(key), e.na.x, e.na.z, e.nb.x, e.nb.z, def.w, !!def.dash, e.na.size * 1.1, e.nb.size * 1.25, def.arrow);
      }
      for (const [key, pos] of groups) {
        const [l, kind] = key.split(':');
        const mm = new THREE.Mesh(geomOf(pos), new THREE.MeshBasicMaterial({ color: tok(EDGE_KINDS[kind].tok), transparent: true, opacity: 0.85, depthWrite: false, side: THREE.DoubleSide }));
        mm.position.y = 0.3; this.planes[+l].g.add(mm); this.edgeMeshes.push(mm);
      }
      return;
    }
    for (const e of this.drawn) {
      const def = EDGE_KINDS[e.kind];
      e.solid = new THREE.Mesh(geomOf(ribbon([], e.na.x, e.na.z, e.nb.x, e.nb.z, def.w, false, e.na.size * 1.1, e.nb.size * 1.25, def.arrow)), new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide }));
      e.dashed = new THREE.Mesh(geomOf(ribbon([], e.na.x, e.na.z, e.nb.x, e.nb.z, def.w, true, e.na.size * 1.1, e.nb.size * 1.25, def.arrow)), new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false, side: THREE.DoubleSide }));
      for (const mm of [e.solid, e.dashed]) { mm.position.y = 0.3; this.planes[e.na.level].g.add(mm); }
    }
  }

  buildLabels() {
    this.labelEls = new Map();
    if (this.mode === 'mesh') for (const n of this.view.nodes) this.labelEl(n);
    this.planeEls = PLANES.map((p, i) => { const el = document.createElement('div'); el.className = 'plbl'; el.innerHTML = `L${i}<b></b><span></span>`; el.querySelector('b').textContent = p; this.labelsEl.appendChild(el); return el; });
    this.tagPool = [];
  }
  labelEl(n) {
    let el = this.labelEls.get(n);
    if (!el) {
      el = document.createElement('div'); el.className = 'lbl' + (n.level === 0 ? ' l0' : ''); el.textContent = n.label; el.style.visibility = 'hidden';
      this.labelsEl.appendChild(el); this.labelEls.set(n, el);
      n.elW = n.label.length * (n.level === 0 ? 7.6 : 6.4) + 12;
    }
    return el;
  }

  bindPointer() {
    const cv = this.canvas; let down = null;
    cv.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY, moved: false }; cv.setPointerCapture(e.pointerId); });
    cv.addEventListener('pointermove', (e) => {
      if (!down) return;
      const dx = e.clientX - down.x, dy = e.clientY - down.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) down.moved = true;
      this.cam.az -= dx * 0.0085; this.cam.el = Math.min(1.38, Math.max(0.12, this.cam.el + dy * 0.006));
      down.x = e.clientX; down.y = e.clientY; this.applyCam();
    });
    cv.addEventListener('pointerup', (e) => { if (down && !down.moved) this.app.select(this.pick(e.clientX, e.clientY)); down = null; });
  }
  // 'depth' is the mockup: the nearest hit wins, so a node in front hides the one the collector
  // aimed at. 'resolve' collects every hit along the ray and takes the node whose projected centre
  // is closest to the pointer, preferring the soloed plane, then the selected node's plane.
  pick(cx, cy) {
    const rect = this.canvas.getBoundingClientRect();
    const ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2(((cx - rect.left) / rect.width) * 2 - 1, -((cy - rect.top) / rect.height) * 2 + 1), this.camera);
    const hits = this.mode === 'inst'
      ? ray.intersectObjects(this.pickables, false).map((h) => h.object.userData.nodes[h.instanceId])
      : ray.intersectObjects(this.view.nodes.map((n) => n.gl.mesh), false).map((h) => h.object.userData.node);
    if (this.pickMode !== 'resolve' || hits.length < 2) return hits[0] || null;
    const seen = new Set(), cands = [];
    for (const n of hits) {
      if (seen.has(n) || (this.solo != null && n.level !== this.solo)) continue;
      seen.add(n);
      const p = this.screenPos(n);
      const plane = this.selected && n.level === this.selected.level ? 0 : 1;
      cands.push({ n, d: Math.hypot(p.x - cx, p.y - cy), plane });
    }
    cands.sort((a, b) => a.d - b.d || a.plane - b.plane);
    this.lastHits = cands.map((c) => c.n);
    return cands.length ? cands[0].n : null;
  }

  resize() {
    const w = this.stage.clientWidth, h = this.stage.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); this.dirty = true;
  }
  applyCam() {
    const c = this.cam;
    for (let i = 0; i < 3; i++) this.planes[i].g.position.y = this.yOf(i);
    const ty = (2 - c.fy) * GAP * c.spread;
    this.target.set(0, ty, 0);
    this.camera.position.set(c.r * Math.cos(c.el) * Math.sin(c.az), ty + c.r * Math.sin(c.el), c.r * Math.cos(c.el) * Math.cos(c.az));
    this.camera.lookAt(this.target);
    if (this.mode === 'mesh' || this.vertDirty) this.rebuildVertical();
    this.dirty = true;
  }
  rebuildVertical() {
    const main = [], hi = [], set = this.selSet;
    for (const n of this.view.nodes) {
      if (!n.parent || this.solo != null) continue;
      const p = this.view.byId.get(n.parent);
      const seg = [n.x, this.yOf(n.level) + n.h, n.z, p.x, this.yOf(p.level) + 0.05, p.z];
      if (set && set.has(n) && set.has(p)) hi.push(...seg); else main.push(...seg);
    }
    this.vMain.geometry.dispose(); this.vMain.geometry = geomOf(main);
    this.vHi.geometry.dispose(); this.vHi.geometry = geomOf(hi);
    this.vMain.material.opacity = set ? 0.07 : 0.32;
    this.vertDirty = false;
  }

  // Colors, dimming, and hulls after any state or selection change (the mockup's update()).
  update() {
    const v = this.view, set = this.selSet;
    const col = new THREE.Color(), bg = new THREE.Color(this.c.canvas);
    const colorOf = (n) => col.set(tok(STATES[v.state(n)].tok));
    if (this.mode === 'inst') {
      for (const im of this.inst) {
        im.userData.nodes.forEach((n, i) => { colorOf(n); if (set && !set.has(n)) col.lerp(bg, 0.8); im.setColorAt(i, col); });
        if (im.instanceColor) im.instanceColor.needsUpdate = true;
      }
      if (this.selected) { const n = this.selected; this.selRing.visible = true; this.selRing.scale.setScalar(n.size * 2.2); this.selRing.position.set(n.x, this.yOf(n.level) + 0.2, n.z); } else this.selRing.visible = false;
    } else {
      for (const n of v.nodes) {
        const g = n.gl; colorOf(n);
        const dim = set && !set.has(n);
        g.mesh.material.color.copy(col); g.mesh.material.emissive.copy(col).multiplyScalar(0.22);
        g.mesh.material.wireframe = !!(n.ref && !v.model.known(n.ref));
        g.mesh.material.opacity = dim ? 0.18 : 1; g.mesh.material.depthWrite = !dim;
        g.halo.material.color.copy(col); g.halo.material.opacity = dim ? 0 : 0.16;
        g.ring.visible = n.prov === 'mb'; g.ring.material.color.set(this.c.bad); g.ring.material.opacity = dim ? 0.2 : 0.9;
        g.sel.visible = this.selected === n; g.sel.material.color.set(this.c.accent);
      }
      for (const e of this.drawn) {
        const def = EDGE_KINDS[e.kind]; const dim = set && !(set.has(e.na) && set.has(e.nb));
        e.solid.visible = !def.dash; e.dashed.visible = !!def.dash;
        for (const mm of [e.solid, e.dashed]) { mm.material.color.set(tok(def.tok)); mm.material.opacity = dim ? 0.1 : 0.85; }
      }
    }
    this.hullTags = [];
    let tagIdx = 0;
    for (let i = 0; i < 3; i++) {
      const P = this.planes[i];
      for (const ch of P.hulls.children.slice()) { P.hulls.remove(ch); ch.geometry.dispose(); ch.material.dispose(); }
      const byG = new Map();
      for (const n of v.nodes) if (n.level === i) { const g = v.groupOf(n); if (!byG.has(g)) byG.set(g, []); byG.get(g).push(n); }
      let gi = 0;
      for (const [g, ns] of byG) {
        const pad = Math.max(...ns.map((n) => n.size)) + 2.2;
        const poly = roundedHull(ns.map((n) => [n.x, n.z]), pad);
        const color = tok(HULL_TOKS[gi++ % 4]);
        const groupDim = set && !ns.some((n) => set.has(n));
        const fill = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(poly.map(([x, z]) => new THREE.Vector2(x, -z)))), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: groupDim ? 0.03 : 0.09, depthWrite: false, side: THREE.DoubleSide }));
        fill.rotation.x = -Math.PI / 2; fill.position.y = 0.02;
        const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(poly.map(([x, z]) => new THREE.Vector3(x, 0.08, z))), new THREE.LineBasicMaterial({ color, transparent: true, opacity: groupDim ? 0.12 : 0.55 }));
        P.hulls.add(fill, line);
        let front = poly[0]; for (const p of poly) if (p[1] > front[1]) front = p;
        let tag = this.tagPool[tagIdx];
        if (!tag) { tag = document.createElement('div'); tag.className = 'tag'; this.labelsEl.appendChild(tag); this.tagPool.push(tag); }
        tagIdx++;
        const label = v.byId.get(g).label;
        tag.textContent = label; tag.style.color = color;
        this.hullTags.push({ el: tag, level: i, x: front[0], z: front[1] + 0.5, w: label.length * 6.2 + 18, dim: groupDim });
      }
    }
    for (let j = tagIdx; j < this.tagPool.length; j++) this.tagPool[j].style.visibility = 'hidden';
    this.planeEls.forEach((el, i) => { el.querySelector('span').textContent = v.nodes.filter((n) => n.level === i).length; });
    this.vertDirty = true; this.rebuildVertical();
    this.dirty = true;
  }

  layoutLabels() {
    const w = this.stage.clientWidth, h = this.stage.clientHeight;
    const v3 = new THREE.Vector3();
    const proj = (x, y, z) => { v3.set(x, y, z).project(this.camera); return { x: (v3.x + 1) / 2 * w, y: (1 - v3.y) / 2 * h, ok: v3.z < 1 && v3.z > -1 }; };
    const zoomBonus = this.cam.r < CAM.r * 0.62 ? 3 : this.cam.r < CAM.r * 0.85 ? 1 : 0;
    const depth = LABEL_DEPTH + zoomBonus + (this.solo != null ? 3 : 0);
    const items = [];
    const consider = this.mode === 'mesh' ? this.view.nodes : this.view.nodes.filter((n) => n.level <= depth || (this.selSet && this.selSet.has(n)) || n === this.hover);
    if (this.mode === 'inst') { const cs = new Set(consider); for (const [n, el] of this.labelEls) if (!cs.has(n)) el.style.visibility = 'hidden'; }
    for (const n of consider) {
      let p = null;
      const el = this.mode === 'mesh' ? this.labelEls.get(n) : null;
      if (this.solo != null && n.level !== this.solo) { if (el) el.style.visibility = 'hidden'; continue; }
      const inSel = this.selSet && this.selSet.has(n);
      if (n === this.hover || n === this.selected) p = 0;
      else if (inSel) p = 0.5 + n.level * 0.1;
      else if (n.level <= depth && !(this.selSet && !inSel)) p = 1 + n.level;
      if (p == null) { if (el) el.style.visibility = 'hidden'; continue; }
      const s = proj(n.x, this.yOf(n.level) + n.h + n.size * 1.25, n.z);
      if (!s.ok) { if (el) el.style.visibility = 'hidden'; continue; }
      const lel = this.labelEl(n);
      items.push({ el: lel, node: n, p, x: s.x - n.elW / 2, y: s.y - 18, w: n.elW, h: n.level === 0 ? 19 : 16 });
    }
    for (const t of this.hullTags) {
      if (this.solo != null && t.level !== this.solo) { t.el.style.visibility = 'hidden'; continue; }
      const s = proj(t.x, this.yOf(t.level), t.z);
      if (!s.ok || t.dim) { t.el.style.visibility = 'hidden'; continue; }
      items.push({ el: t.el, p: 2.5 + t.level * 0.01, x: s.x - t.w / 2, y: s.y - 2, w: t.w, h: 17 });
    }
    const placed = [];
    const bw = (W + 14) / 2, bd = (D + 14) / 2;
    this.planeEls.forEach((el, i) => {
      let best = null;
      for (const [cx, cz] of [[-bw, -bd], [bw, -bd], [bw, bd], [-bw, bd]]) { const s = proj(cx, this.yOf(i), cz); if (s.ok && s.x >= 0 && (!best || s.x < best.x)) best = s; }
      if (!best || (this.solo != null && i !== this.solo)) { el.style.visibility = 'hidden'; return; }
      const x = Math.max(4, best.x + 6), y = best.y - 22;
      el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`; el.style.visibility = 'visible';
      placed.push({ x, y, w: 150, h: 20 });
    });
    for (const it of placeLabels(items, placed, w, h)) { it.el.style.visibility = 'visible'; it.el.style.transform = `translate(${it.x.toFixed(1)}px, ${it.y.toFixed(1)}px)`; }
    for (const it of items) if (!it.shown) it.el.style.visibility = 'hidden';
    this.lastItems = items;
  }

  tick(t) {
    let need = this.dirty;
    if (this.tween) {
      const tw = this.tween, k = Math.min(1, (t - tw.t0) / tw.ms), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      for (const key of Object.keys(tw.to)) this.cam[key] = tw.from[key] + (tw.to[key] - tw.from[key]) * e;
      this.applyCam(); if (k >= 1) this.tween = null; need = true;
      this.tweenFrames = (this.tweenFrames || 0) + 1;
    }
    if (need) this.render();
  }
  render() {
    const t0 = performance.now();
    this.renderer.render(this.scene, this.camera); this.layoutLabels(); this.dirty = false;
    this.lastWorkMs = performance.now() - t0;
  }
  animateTo(to, ms = 520) {
    if (this.reduce) { Object.assign(this.cam, to); this.applyCam(); return; }
    this.tween = { from: { ...this.cam }, to: { ...this.cam, ...to }, t0: performance.now(), ms };
  }

  orbit(d) { this.cam.az += d; this.applyCam(); }
  tilt(d) { this.cam.el = Math.min(1.45, Math.max(0.12, this.cam.el + d)); this.applyCam(); }
  zoom(z) {
    if (z === 'in') this.animateTo({ r: Math.max(60, this.cam.r * 0.8) });
    else if (z === 'out') this.animateTo({ r: Math.min(380, this.cam.r * 1.25) });
    else this.animateTo({ az: CAM.az, el: this.solo == null ? CAM.el : 1.5, r: CAM.r });
  }
  setSolo(level) {
    this.solo = level;
    this.planes.forEach((p, i) => { p.g.visible = level == null || i === level; });
    this.vertDirty = true;
    if (level == null) this.animateTo({ fy: 1, el: CAM.el, r: CAM.r }); else this.animateTo({ fy: level, el: 1.5, r: CAM.r * 0.92 });
    this.applyCam();
  }
  select(n) { this.selected = n; this.selSet = n ? this.view.cylinder(n) : null; this.update(); }

  labelBoxes() {
    return (this.lastItems || []).filter((it) => it.shown && it.node && it.el.style.visibility === 'visible').map((it) => { const r = it.el.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; });
  }
  screenRadius(n) {
    const a = this.screenPos(n), r = this.canvas.getBoundingClientRect(), v3 = new THREE.Vector3(n.x + n.size, this.yOf(n.level) + n.h, n.z).project(this.camera);
    return Math.hypot(r.left + (v3.x + 1) / 2 * r.width - a.x, r.top + (1 - v3.y) / 2 * r.height - a.y);
  }
  screenPos(n) {
    const r = this.canvas.getBoundingClientRect(), v3 = new THREE.Vector3(n.x, this.yOf(n.level) + n.h, n.z).project(this.camera);
    return { x: r.left + (v3.x + 1) / 2 * r.width, y: r.top + (1 - v3.y) / 2 * r.height, ok: v3.z < 1 && v3.z > -1 };
  }
  nodesOnScreen() {
    const w = this.stage.clientWidth, h = this.stage.clientHeight, v3 = new THREE.Vector3();
    let c = 0;
    for (const n of this.view.nodes) { v3.set(n.x, this.yOf(n.level) + n.h, n.z).project(this.camera); const x = (v3.x + 1) / 2 * w, y = (1 - v3.y) / 2 * h; if (v3.z < 1 && x >= 0 && x <= w && y >= 0 && y <= h) c++; }
    return c;
  }
  dispose() {
    this.ro.disconnect(); this.renderer.dispose(); this.canvas.remove(); this.labelsEl.textContent = '';
  }
}
