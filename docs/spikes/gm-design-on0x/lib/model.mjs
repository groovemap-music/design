// SPDX-License-Identifier: MIT
// Concept A's state machine and visibility, ported from the mockup's Strata class and CFG_A so
// that layout, tasks, and the accessible table run without a GPU. Renderers read this model.

export const STATES = {
  none: { label: 'Not collected', tok: '--s-neutral' },
  wanted: { label: 'Wanted', tok: '--s-warn' },
  redundant: { label: 'Redundant want', tok: '--s-purple' },
  owned: { label: 'Owned', tok: '--s-good' },
  partial: { label: 'Partly owned', tok: '--s-cyan' },
};
export const LEGEND = ['owned', 'partial', 'wanted', 'redundant', 'none'];
export const PLANES = ['Artist credits', 'Masters', 'Releases'];
export const SIZES = [4.2, 2.4, 1.35];
export const EDGE_KINDS = {
  member: { label: 'Member of', tok: '--s-purple', w: 0.7, arrow: true },
  collab: { label: 'Shared credit', tok: '--s-pink', w: 0.7 },
  personnel: { label: 'Shared personnel', tok: '--accent', w: 0.5 },
  company: { label: 'Shared company credit', tok: '--s-info', w: 0.4, dash: true },
};
export const DISCOGS_BLOCK = 'No Discogs alias for this pressing. The wantlist and collection sync through Discogs, so the edge that would carry this change does not exist (ADR 0009).';
export const PAST_BLOCK = 'History is read-only. Move "Recorded as of" to today to record a change.';

const TRANSITIONS = [
  { from: ['none'], to: 'wanted', label: 'Add to wantlist', guard: (n, m) => discogsGate(n) || (siblingOwned(n, m) ? { redirect: 'redundant', warn: 'You own another pressing of this master, so this want is recorded as redundant (DERIVED_FROM sibling).' } : null) },
  { from: ['none', 'wanted', 'redundant'], to: 'owned', label: 'Mark as collected', guard: (n) => discogsGate(n) },
  { from: ['wanted', 'redundant'], to: 'none', label: 'Remove from wantlist' },
  { from: ['owned'], to: 'none', label: 'Remove from collection' },
];
const discogsGate = (n) => (n.prov === 'mb' ? { block: DISCOGS_BLOCK } : null);
const siblingOwned = (n, m) => m.byId.get(n.parent).children.some((k) => k !== n && m.recorded(k) === 'owned');

export class Model {
  constructor(fixture, { V = 2026, T = 2026.8, txMax = 2026.8 } = {}) {
    this.nodes = fixture.nodes.map((n) => ({ ...n, hist: (n.hist || []).map((h) => h.slice()) }));
    this.byId = new Map(this.nodes.map((n) => [n.id, n]));
    for (const n of this.nodes) { n.children = []; n.ghosts = []; }
    for (const n of this.nodes) if (n.parent) this.byId.get(n.parent).children.push(n);
    this.edges = fixture.edges.map((e) => ({ ...e, na: this.byId.get(e.a), nb: this.byId.get(e.b) })).filter((e) => e.na && e.nb);
    this.L = 3;
    this.V = V; this.T = T; this.txMax = txMax;
    for (const n of this.nodes) { n.size = SIZES[n.level] * (n.scale || 1); n.h = n.kind === 'disc' ? 0.5 : n.size * 1.05; }
    this.computeVis();
  }

  recorded(n) {
    let s = n.base || 'none';
    for (const h of n.hist) if (h[0] <= this.T + 1e-9) s = h[1];
    return s;
  }

  // CFG_A.derive: a master is owned when any pressing is owned; a credit is owned when every master is.
  state(n) {
    if (n.level === 1) {
      const ss = n.children.map((k) => this.recorded(k));
      return ss.includes('owned') ? 'owned' : ss.includes('wanted') ? 'wanted' : ss.includes('redundant') ? 'redundant' : 'none';
    }
    if (n.level === 0) {
      const ss = n.children.map((k) => this.state(k));
      if (!ss.length) return 'none';
      const own = ss.filter((s) => s === 'owned').length;
      return own === ss.length ? 'owned' : own ? 'partial' : ss.includes('wanted') ? 'wanted' : 'none';
    }
    return this.recorded(n);
  }

  known(n) { return n.known == null || n.known <= this.T + 1e-9; }

  computeVis() {
    this.vis = new Set();
    const order = this.nodes.slice().sort((a, b) => b.level - a.level);
    for (const n of order) {
      const ks = n.children;
      const v = ks.length ? ks.some((c) => this.vis.has(c)) && (n.year == null || n.year <= this.V) : (n.year == null || n.year <= this.V);
      if (v) this.vis.add(n);
    }
    return this.vis;
  }

  // Everything above and below n: the "cylinder" the mockup highlights on selection.
  cylinder(n) {
    const set = new Set();
    const up = (x) => { set.add(x); if (x.parent) up(this.byId.get(x.parent)); };
    const down = (x) => { set.add(x); for (const c of x.children) down(c); };
    up(n); down(n);
    return set;
  }

  groupOf(n) { let p = n; while (p.parent) p = this.byId.get(p.parent); return p.id; }

  transitionsFor(n) {
    if (n.level !== 2) return [];
    const s = this.recorded(n);
    return TRANSITIONS.map((t, i) => ({ ...t, i })).filter((t) => t.from.includes(s));
  }

  // Why n cannot change state right now, or null when at least one transition is open.
  blockedReason(n) {
    if (n.level !== 2) return null;
    if (this.T < this.txMax - 1e-6) return PAST_BLOCK;
    const trs = this.transitionsFor(n);
    const open = trs.filter((t) => !(t.guard && t.guard(n, this) && t.guard(n, this).block));
    if (open.length) return null;
    const g = trs.map((t) => t.guard && t.guard(n, this)).find((x) => x && x.block);
    return g ? g.block : null;
  }

  guardFor(n, t) { return t.guard ? t.guard(n, this) : null; }

  applyTransition(n, i) {
    const t = TRANSITIONS[i];
    const g = t.guard ? t.guard(n, this) : null;
    if (g && g.block) return { ok: false, reason: g.block };
    const to = (g && g.redirect) || t.to;
    n.hist.push([this.txMax, to]);
    return { ok: true, to, warn: g && g.warn };
  }

  // Lateral edges of n (on its own plane), for the panel and the table.
  lateral(n) { return this.edges.filter((e) => e.na === n || e.nb === n); }
}
