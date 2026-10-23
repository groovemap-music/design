// SPDX-License-Identifier: MIT
// Stream the MusicBrainz release-group JSON dump member from stdin and write (rg_mbid, artist_mbid)
// pairs, gzipped, to the path given. Ids stay in the work directory outside the repository. Credits
// to MusicBrainz's special-purpose artists ("Various Artists", "[unknown]") are dropped: no
// discography view is rooted at them.
//   xz -dc release-group.tar.xz | tar -xOf - mbdump/release-group | node scripts/mb_rg_artists.mjs out.tsv.gz

import { createWriteStream } from 'node:fs';
import { createGzip } from 'node:zlib';

const SPECIAL = new Set(['Various Artists', '[unknown]', '[no artist]', '[anonymous]', '[traditional]', '[data]', '[dialogue]']);
const gz = createGzip();
gz.pipe(createWriteStream(process.argv[2]));
let groups = 0, pairs = 0, dropped = 0;
// Split on \n only: readline also breaks on U+2028 and U+2029, which occur raw inside JSON strings.
async function* lines(stream) {
  let rest = '';
  stream.setEncoding('utf8');
  for await (const chunk of stream) {
    const parts = (rest + chunk).split('\n');
    rest = parts.pop();
    yield* parts;
  }
  if (rest) yield rest;
}
for await (const line of lines(process.stdin)) {
  if (!line) continue;
  let d;
  try { d = JSON.parse(line); } catch (e) { throw new Error(`record ${groups + 1}: ${e.message.slice(0, 120)} (line length ${line.length})`); }
  groups++;
  const seen = new Set();
  for (const ac of d['artist-credit'] || []) {
    const a = ac.artist;
    if (!a || seen.has(a.id)) continue;
    seen.add(a.id);
    if (SPECIAL.has(a.name)) { dropped++; continue; }
    if (!gz.write(`${d.id}\t${a.id}\n`)) await new Promise((r) => gz.once('drain', r));
    pairs++;
  }
}
gz.end();
await new Promise((r) => gz.on('finish', r));
process.stderr.write(JSON.stringify({ groups, pairs, droppedSpecialCredits: dropped }) + '\n');
