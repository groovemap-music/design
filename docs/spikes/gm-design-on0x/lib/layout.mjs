// SPDX-License-Identifier: MIT
// Concept A layout and its invariants, without a GPU. The icicle, hull, and point-in-polygon code is
// the mockup's (layoutTimeIcicle, hull, roundedHull, inPoly), unchanged apart from the gutter option.

export const W = 120, D = 84;

export function hull(pts) {
  pts = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const p of pts) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
  for (let i = pts.length - 1; i >= 0; i--) { const p = pts[i]; while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], p) <= 0) up.pop(); up.push(p); }
  up.pop(); lo.pop();
  return lo.concat(up);
}

export function roundedHull(points, pad) {
  const s = [];
  for (const [x, z] of points) for (let i = 0; i < 18; i++) { const a = i / 18 * Math.PI * 2; s.push([x + Math.cos(a) * pad, z + Math.sin(a) * pad]); }
  return hull(s);
}

export function inPoly(p, poly) {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, zi] = poly[i], [xj, zj] = poly[j];
    if (((zi > p[1]) !== (zj > p[1])) && (p[0] < (xj - xi) * (p[1] - zi) / (zj - zi) + xi)) c = !c;
  }
  return c;
}

// The mockup's time icicle: x is release year, z splits the depth by leaf count. Two options are new.
// `gutter` (world units) reserves space between top-level groups. `spaced` weights each node by the
// larger of its children's weights and its own footprint (2 * size + 0.6), so siblings never sit
// closer than their discs, whatever the leaf counts. gutter 0 and spaced false is the mockup.
export function layoutTimeIcicle(m, { y0, y1, gutter = 0, spaced = false }) {
  const X = (y) => -W / 2 + 6 + (y - y0) / (y1 - y0) * (W - 12);
  const kids = (n) => n.children;
  const memo = new Map();
  const leaves = spaced
    ? (n) => { if (memo.has(n)) return memo.get(n); const v = Math.max(2 * n.size + 0.6, kids(n).reduce((s, c) => s + leaves(c), 0)); memo.set(n, v); return v; }
    : (n) => (kids(n).length ? kids(n).reduce((s, c) => s + leaves(c), 0) : 1);
  const roots = m.nodes.filter((n) => n.level === 0);
  const total = roots.reduce((s, r) => s + leaves(r), 0);
  const place = (n, a, b) => {
    n.z = (a + b) / 2;
    const ks = kids(n).slice().sort((p, q) => (p.year || 0) - (q.year || 0));
    const L = leaves(n); let c = a;
    for (const k of ks) { const w = (b - a) * leaves(k) / L; place(k, c, c + w); c += w; }
  };
  const usable = Math.max(1, D - 6 - gutter * (roots.length - 1));
  let z = -D / 2 + 3;
  for (const r of roots) { const w = usable * leaves(r) / total; place(r, z, z + w); z += w + gutter; }
  const setX = (n) => {
    for (const k of n.children) setX(k);
    if (n.year != null) n.x = X(n.year);
    else { const ks = kids(n); n.x = ks.length ? ks.reduce((s, k) => s + k.x, 0) / ks.length : 0; }
  };
  roots.forEach(setX);
  m.axis = { X, y0, y1 };
}

export function layoutModel(m, opts = {}) {
  let y0 = Infinity;
  for (const n of m.nodes) if (n.year != null) y0 = Math.min(y0, n.year);
  layoutTimeIcicle(m, { y0: Math.min(1953, y0 - 2), y1: 2027, gutter: opts.gutter || 0, spaced: !!opts.spaced });
  // How much the depth axis had to shrink to fit: under 1 means footprints overlap by construction.
  if (opts.spaced) { const roots = m.nodes.filter((n) => n.level === 0); m.depthFit = (D - 6 - (opts.gutter || 0) * (roots.length - 1)) / roots.reduce((s, r) => s + spacedWeight(r), 0); }
}

function spacedWeight(n) { return Math.max(2 * n.size + 0.6, n.children.reduce((s, c) => s + spacedWeight(c), 0)); }

const visibleOn = (m, level) => m.nodes.filter((n) => n.level === level && m.vis.has(n));

// The mockup's readout: a node inside the rounded hull of a group it does not belong to.
export function hullIntrusions(m, level) {
  const ns = visibleOn(m, level);
  const byG = new Map();
  for (const n of ns) { const g = m.groupOf(n); if (!byG.has(g)) byG.set(g, []); byG.get(g).push(n); }
  const polys = [];
  for (const [g, gs] of byG) {
    const pad = Math.max(...gs.map((n) => n.size)) + 2.2;
    const poly = roundedHull(gs.map((n) => [n.x, n.z]), pad);
    let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
    for (const [x, z] of poly) { minX = Math.min(minX, x); maxX = Math.max(maxX, x); minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z); }
    polys.push({ g, poly, box: [minX, maxX, minZ, maxZ] });
  }
  let count = 0;
  for (const { g, poly, box } of polys) {
    for (const n of ns) {
      if (n.x < box[0] || n.x > box[1] || n.z < box[2] || n.z > box[3]) continue;
      if (m.groupOf(n) !== g && inPoly([n.x, n.z], poly)) count++;
    }
  }
  return { hulls: polys.length, intrusions: count, polys };
}

// Two nodes on one plane whose drawn footprints overlap (radius = size, as the meshes are scaled).
export function nodeOverlaps(m, level) {
  const ns = visibleOn(m, level);
  const cell = 2 * Math.max(...ns.map((n) => n.size), 1);
  const grid = new Map();
  const key = (x, z) => `${Math.floor(x / cell)},${Math.floor(z / cell)}`;
  for (const n of ns) { const k = key(n.x, n.z); if (!grid.has(k)) grid.set(k, []); grid.get(k).push(n); }
  let count = 0;
  for (const n of ns) {
    const cx = Math.floor(n.x / cell), cz = Math.floor(n.z / cell);
    for (let dx = -1; dx <= 1; dx++) for (let dz = -1; dz <= 1; dz++) {
      for (const o of grid.get(`${cx + dx},${cz + dz}`) || []) {
        if (o.id <= n.id) continue;
        if (Math.hypot(o.x - n.x, o.z - n.z) < o.size + n.size - 1e-9) count++;
      }
    }
  }
  return count;
}

// Which lateral edges are drawn on the plane by default. 'all' is the mockup. 'planar' keeps the
// member/collab star from the root credit, keeps a personnel edge only between masters of one credit
// that are neighbours in (x, z) order, and draws company edges only for a selected node. Edges it
// leaves off the plane stay in the panel and the table.
export function drawnEdges(m, policy = 'all', selected = null) {
  const vis = m.edges.filter((e) => m.vis.has(e.na) && m.vis.has(e.nb) && e.na.level === e.nb.level);
  if (policy === 'all') return vis;
  const rank = new Map();
  const byCredit = new Map();
  for (const n of m.nodes) if (n.level === 1 && m.vis.has(n)) { const g = n.parent; if (!byCredit.has(g)) byCredit.set(g, []); byCredit.get(g).push(n); }
  for (const list of byCredit.values()) {
    list.sort((a, b) => a.x - b.x || a.z - b.z);
    list.forEach((n, i) => rank.set(n, i));
  }
  return vis.filter((e) => {
    if (e.kind === 'member' || e.kind === 'collab') return e.na.level === 0 && (e.na.id === 'c0' || e.nb.id === 'c0');
    if (e.kind === 'personnel') return e.na.parent === e.nb.parent && Math.abs(rank.get(e.na) - rank.get(e.nb)) === 1;
    if (e.kind === 'company') return selected != null && (e.na === selected || e.nb === selected);
    return false;
  });
}

function segs(e) {
  const a = e.na, b = e.nb;
  let dx = b.x - a.x, dz = b.z - a.z; const L = Math.hypot(dx, dz) || 1; dx /= L; dz /= L;
  const sa = a.size * 1.1, sb = b.size * 1.25;
  return [a.x + dx * sa, a.z + dz * sa, b.x - dx * sb, b.z - dz * sb, L > sa + sb];
}
const orient = (ax, az, bx, bz, cx, cz) => Math.sign((bx - ax) * (cz - az) - (bz - az) * (cx - ax));
const onSeg = (ax, az, bx, bz, cx, cz) => Math.min(ax, bx) - 1e-9 <= cx && cx <= Math.max(ax, bx) + 1e-9 && Math.min(az, bz) - 1e-9 <= cz && cz <= Math.max(az, bz) + 1e-9;
export function segmentsCross(p, q) {
  const [ax, az, bx, bz] = p, [cx, cz, dx, dz] = q;
  const o1 = orient(ax, az, bx, bz, cx, cz), o2 = orient(ax, az, bx, bz, dx, dz), o3 = orient(cx, cz, dx, dz, ax, az), o4 = orient(cx, cz, dx, dz, bx, bz);
  if (o1 !== o2 && o3 !== o4 && o1 * o2 <= 0 && o3 * o4 <= 0 && (o1 || o2 || o3 || o4)) return true;
  // Collinear overlap counts as a crossing: two ribbons drawn on top of each other.
  if (!o1 && onSeg(ax, az, bx, bz, cx, cz)) return true;
  if (!o2 && onSeg(ax, az, bx, bz, dx, dz)) return true;
  if (!o3 && onSeg(cx, cz, dx, dz, ax, az)) return true;
  if (!o4 && onSeg(cx, cz, dx, dz, bx, bz)) return true;
  return false;
}

// Same-plane crossings among the drawn edges. Edges that share an endpoint node are not compared:
// the ribbons are shrunk away from the node, so they meet only at its disc.
export function samePlaneCrossings(m, edges) {
  const byLevel = [[], [], []];
  for (const e of edges) { const s = segs(e); if (s[4]) byLevel[e.na.level].push({ e, s }); }
  let count = 0;
  for (const list of byLevel) {
    const cell = 6;
    const grid = new Map();
    list.forEach((it, i) => {
      const [ax, az, bx, bz] = it.s;
      for (let gx = Math.floor(Math.min(ax, bx) / cell); gx <= Math.floor(Math.max(ax, bx) / cell); gx++)
        for (let gz = Math.floor(Math.min(az, bz) / cell); gz <= Math.floor(Math.max(az, bz) / cell); gz++) {
          const k = gx * 100003 + gz; if (!grid.has(k)) grid.set(k, []); grid.get(k).push(i);
        }
    });
    const seen = new Set();
    for (const ids of grid.values()) {
      for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
        const a = list[ids[i]], b = list[ids[j]];
        const pair = ids[i] < ids[j] ? ids[i] * 1e7 + ids[j] : ids[j] * 1e7 + ids[i];
        if (seen.has(pair)) continue; seen.add(pair);
        if (a.e.na === b.e.na || a.e.na === b.e.nb || a.e.nb === b.e.na || a.e.nb === b.e.nb) continue;
        if (segmentsCross(a.s, b.s)) count++;
      }
    }
  }
  return count;
}

export function invariants(m, { policy = 'all' } = {}) {
  const planes = [0, 1, 2].map((l) => {
    const h = hullIntrusions(m, l);
    return { level: l, nodes: m.nodes.filter((n) => n.level === l && m.vis.has(n)).length, hulls: h.hulls, intrusions: h.intrusions, overlaps: nodeOverlaps(m, l) };
  });
  const edges = drawnEdges(m, policy);
  return { planes, drawnEdges: edges.length, crossings: samePlaneCrossings(m, edges) };
}
