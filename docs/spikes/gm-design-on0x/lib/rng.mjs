// SPDX-License-Identifier: MIT
// Seeded PRNG (mulberry32) and invented-word labels. Nothing here is drawn from a real catalog.

export function rng(seed) {
  let a = seed >>> 0;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  next.int = (lo, hi) => lo + Math.floor(next() * (hi - lo + 1));
  next.pick = (list) => list[Math.floor(next() * list.length)];
  next.chance = (p) => next() < p;
  return next;
}

const SYL = ['ka', 'lo', 'mi', 'ren', 'to', 'sa', 'vel', 'or', 'nu', 'qui', 'da', 'zen', 'pha', 'lu', 'mar', 'ost', 'ira', 'bel', 'cor', 'tem'];

export function word(r, min = 2, max = 4) {
  let s = '';
  const n = r.int(min, max);
  for (let i = 0; i < n; i++) s += r.pick(SYL);
  return s[0].toUpperCase() + s.slice(1);
}

// Title lengths follow a 1 to 5 word spread, which puts most labels between 8 and 30 characters.
export function title(r) {
  const n = r.pick([1, 2, 2, 2, 3, 3, 3, 4, 5]);
  return Array.from({ length: n }, () => word(r, 1, 3)).join(' ');
}
