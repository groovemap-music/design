// SPDX-License-Identifier: MIT
// Synthetic concept A discographies: credit -> master -> release, with collector state and history.
// Shapes come from the aggregate histograms in results/size_bands.json. Names are invented words.

import { rng, title, word } from './rng.mjs';

export const SCALES = [50, 500, 5000, 20000];
export const TX = { min: 2010, max: 2026.8 };
const FORMATS = ['Original LP', 'CD reissue', 'Remaster', 'Box set', 'Deluxe edition', 'Cassette', 'Digital release', '2xLP reissue', 'Promo', 'Club edition'];

// Pick a value from [[lo, hi, weight], ...] buckets, uniform inside the chosen bucket.
export function sampler(buckets, r) {
  const total = buckets.reduce((s, b) => s + b[2], 0);
  return () => {
    let x = r() * total;
    for (const [lo, hi, w] of buckets) {
      if ((x -= w) < 0) return lo + Math.floor(r() * (hi - lo + 1));
    }
    const [lo, hi] = buckets[buckets.length - 1];
    return r.int(lo, hi);
  };
}

// The histogram band whose node range contains n, so a 20,000-node fixture borrows the shape of
// the largest real discographies rather than the catalog-wide median.
export function bandFor(bands, n) {
  const b = bands.bands.find((x) => n >= x.nodes[0] && n <= x.nodes[1]) || bands.bands[bands.bands.length - 1];
  const w = b.releases_per_master.reduce((s, x) => s + x[2], 0);
  return { ...b, mean_releases_per_master: b.releases_per_master.reduce((s, [lo, hi, c]) => s + c * (lo + hi) / 2, 0) / w };
}

export function generate({ nodes: N, seed = 1, bands }) {
  const r = rng(seed * 7919 + N);
  const band = bandFor(bands, N);
  const relPerMaster = sampler(band.releases_per_master, r);
  const C = Math.max(1, Math.min(80, Math.round(Math.sqrt(N) / 2)));
  const out = [];
  const edges = [];
  const start = r.int(1952, 1985);
  for (let i = 0; i < C; i++) {
    out.push({ id: `c${i}`, level: 0, label: i === 0 ? word(r) + ' ' + word(r) : word(r) + (r.chance(0.5) ? ' ' + r.pick(['Quartet', 'Trio', 'Ensemble', 'Group', 'Orchestra', '& ' + word(r)]) : ''), sub: i === 0 ? 'Artist' : 'Related credit', kind: 'ico' });
    if (i > 0) edges.push({ a: 'c0', b: `c${i}`, kind: r.chance(0.4) ? 'member' : 'collab' });
  }
  // Credit weights fall off as a Zipf curve: the root credit carries most of the discography.
  const weights = Array.from({ length: C }, (_, i) => 1 / Math.pow(i + 1, 1.1));
  const wsum = weights.reduce((s, w) => s + w, 0);
  const pickCredit = () => { let x = r() * wsum; for (let i = 0; i < C; i++) if ((x -= weights[i]) < 0) return i; return 0; };
  let left = N - C;
  let m = 0, rel = 0;
  // A collector holds or wants a pressing of about 30% of a small discography's masters, capped near
  // 40 masters for a large one: nobody collects a quarter of a 7,000-master catalogue.
  const expectMasters = Math.max(1, (N - C) / (1 + band.mean_releases_per_master));
  const pInterest = Math.min(0.3, 40 / expectMasters);
  const masters = [];
  while (left >= 2) {
    const ci = m < C ? m : pickCredit();
    const year = Math.min(2026, start + Math.floor(Math.pow(r(), 1.4) * Math.min(55, 2026 - start)));
    const id = `m${m++}`;
    const master = { id, level: 1, parent: `c${ci}`, label: title(r), year, kind: 'sphere', sub: `Master · ${year}` };
    out.push(master); masters.push(master);
    left--;
    const k = Math.max(1, Math.min(left, relPerMaster()));
    const interest = r.chance(pInterest);
    let ownedIdx = -1;
    if (interest) ownedIdx = r.chance(0.7) ? r.int(0, k - 1) : -1;
    for (let j = 0; j < k; j++) {
      const ry = j === 0 ? year : Math.min(2026, year + Math.floor(Math.pow(r(), 0.7) * (2027 - year)));
      const prov = j > 0 && r.chance(0.06) ? 'mb' : 'discogs';
      const node = { id: `r${rel++}`, level: 2, parent: id, year: ry, label: `${j === 0 ? 'Original LP' : r.pick(FORMATS)} ${ry}`, kind: 'disc', prov, hist: [] };
      if (prov === 'mb' && r.chance(0.3)) node.known = Math.max(ry, TX.min) + r() * Math.max(0.1, TX.max - Math.max(ry, TX.min));
      if (prov === 'discogs') {
        if (j === ownedIdx) {
          const t = TX.min + r() * (TX.max - TX.min - 0.2);
          if (r.chance(0.3)) node.hist.push([t - Math.min(1.5, t - TX.min) * r(), 'wanted']);
          node.hist.push([t, 'owned']);
        } else if (interest && ownedIdx === -1 && j === 0) node.hist.push([TX.min + r() * (TX.max - TX.min), 'wanted']);
        else if (interest && ownedIdx >= 0 && r.chance(0.04)) node.hist.push([TX.min + r() * (TX.max - TX.min), 'redundant']);
      }
      node.hist.sort((a, b) => a[0] - b[0]);
      out.push(node);
      if (r.chance(0.05) && rel > 1) edges.push({ a: node.id, b: `r${r.int(0, rel - 2)}`, kind: 'company' });
    }
    left -= k;
  }
  // Shared personnel: chronological neighbours within a credit often share players, and a few links
  // reach anywhere in the discography, as real line-ups do.
  const byCredit = new Map();
  for (const ms of masters) { if (!byCredit.has(ms.parent)) byCredit.set(ms.parent, []); byCredit.get(ms.parent).push(ms); }
  for (const list of byCredit.values()) {
    list.sort((a, b) => a.year - b.year);
    for (let i = 1; i < list.length; i++) if (r.chance(0.5)) edges.push({ a: list[i - 1].id, b: list[i].id, kind: 'personnel' });
  }
  for (const ms of masters) if (r.chance(0.15)) { const o = r.pick(masters); if (o !== ms) edges.push({ a: ms.id, b: o.id, kind: 'personnel' }); }
  return { nodes: out, edges, seed, scale: N, band: band.name };
}
