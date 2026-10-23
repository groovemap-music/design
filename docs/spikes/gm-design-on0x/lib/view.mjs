// SPDX-License-Identifier: MIT
// The drawn view of a Model. Without a budget every visible node is drawn, as in the mockup. With a
// budget [credits, masters, releases] the aggregation rule below collapses nodes into count nodes
// until each plane fits. Count nodes keep their members, so the table and the tasks still reach them.

import { SIZES } from './model.mjs';

const summarize = (states) => {
  const own = states.filter((s) => s === 'owned').length;
  if (own && own === states.length) return 'owned';
  if (own) return 'partial';
  return states.includes('wanted') ? 'wanted' : 'none';
};

export class View {
  constructor(model, { budget = null, pinned = new Set(), keepOriginal = true, focus = null, sizeScale = 1 } = {}) {
    this.model = model;
    this.budget = budget;
    this.pinned = focus ? new Set([...pinned, focus.id]) : pinned;
    this.focus = focus;
    this.nodes = [];
    this.byId = new Map();
    this.rep = new Map();
    if (!budget) this.identity();
    else this.aggregate(budget, keepOriginal);
    for (const n of this.nodes) { n.children = []; n.size = SIZES[n.level] * sizeScale; n.h = n.kind === 'disc' ? 0.5 : n.size * 1.05; }
    for (const n of this.nodes) if (n.parent) this.byId.get(n.parent).children.push(n);
    this.vis = new Set(this.nodes);
    this.edges = model.edges.filter((e) => model.vis.has(e.na) && model.vis.has(e.nb)).map((e) => {
      const a = this.rep.get(e.na), b = this.rep.get(e.nb);
      return a && b && !a.agg && !b.agg ? { ...e, na: a, nb: b } : null;
    }).filter(Boolean);
  }

  add(vn) { this.nodes.push(vn); this.byId.set(vn.id, vn); for (const m of vn.members) this.rep.set(m, vn); return vn; }
  own(n, parent) { return this.add({ id: n.id, level: n.level, parent, year: n.year, label: n.label, sub: n.sub, kind: n.kind, prov: n.prov, ref: n, members: [n] }); }

  identity() {
    const m = this.model;
    for (const n of m.nodes) if (m.vis.has(n)) this.own(n, n.parent || null);
  }

  aggregate([b0, b1, b2], keepOriginal) {
    const m = this.model;
    const vis = (n) => m.vis.has(n);
    const memo = new Map(), stMemo = new Map();
    const size = (n) => { if (!memo.has(n)) memo.set(n, 1 + n.children.filter(vis).reduce((s, k) => s + size(k), 0)); return memo.get(n); };
    const stateOf = (x) => { if (!stMemo.has(x)) stMemo.set(x, m.state(x)); return stMemo.get(x); };
    const credits = m.nodes.filter((n) => n.level === 0 && vis(n)).sort((a, b) => (a.id === 'c0' ? -1 : b.id === 'c0' ? 1 : size(b) - size(a)));
    // 1. Credits: keep the root and the largest credits, fold the rest into one "+k credits" node.
    const puMemo = new Map();
    const pinnedUnder = (n) => { if (!this.pinned.size) return false; if (!puMemo.has(n)) puMemo.set(n, this.pinned.has(n.id) || n.children.some(pinnedUnder)); return puMemo.get(n); };
    let kept = credits;
    if (credits.length > b0) {
      const must = credits.filter((c, i) => i === 0 || pinnedUnder(c));
      const rest = credits.filter((c) => !must.includes(c));
      kept = must.concat(rest.slice(0, Math.max(0, b0 - 1 - must.length)));
    }
    const folded = credits.filter((c) => !kept.includes(c));
    for (const c of kept) this.own(c, null);
    if (folded.length) {
      const members = folded.flatMap((c) => [c, ...c.children.filter(vis), ...c.children.filter(vis).flatMap((k) => k.children.filter(vis))]);
      this.add({ id: 'agg:credits', level: 0, parent: null, label: `+${folded.length} other credits`, sub: `${members.filter((x) => x.level === 1).length} masters, ${members.filter((x) => x.level === 2).length} releases`, kind: 'ico', agg: true, count: folded.length, members, aggState: summarize(folded.map((c) => m.state(c))) });
    }
    // 2. Masters: coarsen one credit at a time, largest first, until the plane fits. Uncollected
    //    masters fold first, by decade, then by quarter century, then into one node per credit;
    //    only then do masters with collector state fold, in the same three steps. Pinned masters
    //    never fold.
    const mastersOf = (c) => c.children.filter(vis);
    const grain = new Map(kept.map((c) => [c, 0]));
    const STEPS = [null, { span: 10, all: false }, { span: 25, all: false }, { span: 1000, all: false }, { span: 10, all: true }, { span: 25, all: true }, { span: 1000, all: true }];
    const planMemo = new Map();
    const plan = (c) => {
      const key = c.id + ':' + grain.get(c);
      if (planMemo.has(key)) return planMemo.get(key);
      const res = planRaw(c); planMemo.set(key, res); return res;
    };
    const planRaw = (c) => {
      const g = STEPS[grain.get(c)];
      const ms = mastersOf(c);
      if (!g) return { single: ms, buckets: new Map() };
      const single = [], buckets = new Map();
      for (const x of ms) {
        const fold = !this.pinned.has(x.id) && !pinnedUnder(x) && (g.all || stateOf(x) === 'none');
        if (!fold) { single.push(x); continue; }
        const k = Math.floor(x.year / g.span) * g.span;
        if (!buckets.has(k)) buckets.set(k, []);
        buckets.get(k).push(x);
      }
      for (const [k, list] of buckets) if (list.length < 2) { single.push(...list); buckets.delete(k); }
      return { single, buckets };
    };
    const perPage = this.focus ? this.focus.per || Math.max(1, Math.floor(b2 / 2)) : 0;
    const relMemo = new Map();
    const releasesFor = (x) => {
      if (relMemo.has(x)) return relMemo.get(x);
      const rs = x.children.filter(vis).sort((a, b) => a.year - b.year);
      const keep = rs.filter((r, i) => (keepOriginal && i === 0) || r.hist.length || this.pinned.has(r.id));
      const fold = rs.filter((r) => !keep.includes(r));
      const v = this.focus && x.id === this.focus.id ? Math.min(rs.length, perPage) + 1 : fold.length >= 2 ? keep.length + 1 : rs.length;
      relMemo.set(x, v);
      return v;
    };
    const count = () => {
      let l1 = 0, l2 = 0;
      for (const c of kept) { const p = plan(c); l1 += p.single.length + p.buckets.size; l2 += p.single.reduce((s, x) => s + releasesFor(x), 0); }
      return [l1, l2];
    };
    for (let guard = 0; guard < 1000; guard++) {
      const [l1, l2] = count();
      if (l1 <= b1 && l2 <= b2) break;
      const cands = kept.filter((c) => grain.get(c) < STEPS.length - 1);
      if (!cands.length) break;
      const load = (c) => { const p = plan(c); return p.single.length + p.buckets.size + p.single.reduce((s, x) => s + releasesFor(x), 0); };
      cands.sort((a, b) => load(b) - load(a));
      grain.set(cands[0], grain.get(cands[0]) + 1);
    }
    // 3. Releases: keep the original pressing and every pressing with recorded state, fold the rest
    //    of a master's pressings into one "+k pressings" node. With a focus (the collector opened a
    //    master's count node) that master shows its pressings a page at a time (b2 / 2 per page by
    //    default) and the plan above has already folded other masters to make room.
    for (const c of kept) {
      const p = plan(c);
      for (const x of p.single) {
        this.own(x, c.id);
        if (this.focus && x.id === this.focus.id) {
          const rs = x.children.filter(vis).sort((a, b) => a.year - b.year);
          const per = perPage, from = (this.focus.page || 0) * per;
          const page = rs.slice(from, from + per), rest = rs.length - from - page.length;
          for (const r of page) this.own(r, x.id);
          if (rest > 0) this.add({ id: `agg:${x.id}`, level: 2, parent: x.id, year: rs[rs.length - 1].year, label: `+${rest} more pressings`, sub: 'Next page', kind: 'disc', agg: true, count: rest, members: rs.slice(from + per), aggState: 'none', next: true });
          continue;
        }
        const rs = x.children.filter(vis).sort((a, b) => a.year - b.year);
        const keep = rs.filter((r, i) => (keepOriginal && i === 0) || r.hist.length || this.pinned.has(r.id));
        const fold = rs.filter((r) => !keep.includes(r));
        if (fold.length < 2) { for (const r of rs) this.own(r, x.id); continue; }
        for (const r of keep) this.own(r, x.id);
        const mb = fold.filter((r) => r.prov === 'mb').length;
        const years = fold.map((r) => r.year).sort((a, b) => a - b);
        this.add({ id: `agg:${x.id}`, level: 2, parent: x.id, year: years[Math.floor(years.length / 2)], label: `+${fold.length} pressings`, sub: mb ? `${mb} MusicBrainz only` : 'Not collected', kind: 'disc', agg: true, count: fold.length, members: fold, aggState: 'none' });
      }
      for (const [k, list] of p.buckets) {
        const span = STEPS[grain.get(c)].span;
        const members = list.flatMap((x) => [x, ...x.children.filter(vis)]);
        const yrs = list.map((x) => x.year).sort((a, b) => a - b);
        this.add({ id: `agg:${c.id}:${k}`, level: 1, parent: c.id, year: yrs[Math.floor(yrs.length / 2)], label: span >= 1000 ? `${list.length} masters` : `${list.length} masters, ${k}s`, sub: `${members.length - list.length} releases`, kind: 'sphere', agg: true, count: list.length, members, aggState: summarize(list.map((x) => m.state(x))) });
      }
    }
  }

  state(vn) { return vn.agg ? this.aggState(vn) : this.model.state(vn.ref); }
  aggState(vn) {
    const top = vn.members.filter((x) => x.level === vn.level);
    return vn.level === 2 ? (top.some((x) => this.model.recorded(x) !== 'none') ? 'partial' : 'none') : summarize(top.map((x) => this.model.state(x)));
  }
  groupOf(n) { let p = n; while (p.parent) p = this.byId.get(p.parent); return p.id; }
  primary(n) { return n; }
  cylinder(n) {
    const set = new Set();
    const up = (x) => { set.add(x); if (x.parent) up(this.byId.get(x.parent)); };
    const down = (x) => { set.add(x); for (const c of x.children) down(c); };
    up(n); down(n);
    return set;
  }
  perPlane() { return [0, 1, 2].map((l) => this.nodes.filter((n) => n.level === l).length); }
}
