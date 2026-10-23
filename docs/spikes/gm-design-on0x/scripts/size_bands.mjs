// SPDX-License-Identifier: MIT
// Quick count of the credit -> master -> release shape.
//   node scripts/size_bands.mjs --label <source> --releases <tsv.gz> --master-col <i> --credits <tsv.gz>
// --releases has one row per release with its master (Discogs master or MusicBrainz release group)
// in column i, empty when it has none. --credits has (master, artist) rows. Both are read-only.
// Prints aggregate counts only: no id, name, or title leaves this process.

import { createReadStream } from 'node:fs';
import { createGunzip } from 'node:zlib';
import { createInterface } from 'node:readline';

const arg = (k) => { const i = process.argv.indexOf(`--${k}`); if (i < 0) throw new Error(`missing --${k}`); return process.argv[i + 1]; };
const LABEL = arg('label'), RELEASES = arg('releases'), COL = +arg('master-col'), CREDITS = arg('credits');

async function* rows(path) {
  const rl = createInterface({ input: createReadStream(path).pipe(createGunzip()), crlfDelay: Infinity });
  for await (const line of rl) if (line) yield line.split('\t');
}

// Fixture scales are 50, 500, 5,000, and 20,000 nodes; a band runs to the geometric midpoint.
export const BANDS = [['b50', 1, 158], ['b500', 159, 1581], ['b5000', 1582, 10000], ['b20000', 10001, Infinity]];
const BUCKETS = [[1, 1], [2, 2], [3, 4], [5, 9], [10, 30], [31, 100], [101, 400], [401, 1000], [1001, 5000]];

const relPerMaster = new Map();
let releases = 0, masterless = 0;
for await (const row of rows(RELEASES)) {
  const master = row[COL];
  releases++;
  if (!master) { masterless++; continue; }
  relPerMaster.set(master, (relPerMaster.get(master) || 0) + 1);
}
const mastersOf = new Map();
let masterArtistRows = 0;
for await (const [master, artist] of rows(CREDITS)) {
  masterArtistRows++;
  if (!mastersOf.has(artist)) mastersOf.set(artist, []);
  mastersOf.get(artist).push(master);
}
const band = (n) => BANDS.find(([, lo, hi]) => n >= lo && n <= hi)[0];
const out = new Map(BANDS.map(([name, lo, hi]) => [name, { name, nodes: [lo, hi === Infinity ? 1000000 : hi], credits: 0, buckets: BUCKETS.map(([a, b]) => [a, b, 0]) }]));
const sizes = [];
for (const ms of mastersOf.values()) {
  const rel = ms.reduce((s, m) => s + (relPerMaster.get(m) || 0), 0);
  const n = 1 + ms.length + rel;
  sizes.push([n, ms.length, rel]);
  const b = out.get(band(n));
  b.credits++;
  for (const m of ms) {
    const k = Math.max(1, relPerMaster.get(m) || 0);
    const bucket = b.buckets.find(([lo, hi]) => k >= lo && k <= hi) || b.buckets[b.buckets.length - 1];
    bucket[2]++;
  }
}
sizes.sort((a, b) => b[0] - a[0]);
const q = (p) => sizes[Math.min(sizes.length - 1, Math.floor((1 - p) * sizes.length))][0];
const rpm = [...relPerMaster.values()].sort((a, b) => a - b);
console.log(JSON.stringify({
  source: LABEL,
  releases, masterless_releases: masterless, masters_with_releases: relPerMaster.size, master_artist_rows: masterArtistRows, credits_with_masters: mastersOf.size,
  releases_per_master: { p50: rpm[Math.floor(rpm.length * 0.5)], p90: rpm[Math.floor(rpm.length * 0.9)], p99: rpm[Math.floor(rpm.length * 0.99)], p999: rpm[Math.floor(rpm.length * 0.999)], max: rpm[rpm.length - 1] },
  credit_nodes: { p50: q(0.5), p90: q(0.9), p99: q(0.99), p999: q(0.999), p9999: q(0.9999) },
  largest_credits: sizes.slice(0, 10).map(([nodes, masters, rel]) => ({ nodes, masters, releases: rel })),
  bands: [...out.values()].map((b) => ({ name: b.name, nodes: b.nodes, credits: b.credits, share: +(b.credits / mastersOf.size).toFixed(6), releases_per_master: b.buckets.filter((x) => x[2] > 0) })),
}, null, 1));
