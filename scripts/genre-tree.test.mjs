// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import { gzipSync } from "node:zlib";

import { MAX_CHILDREN, validateGenreTree } from "./genre-tree.mjs";
import { ROOT } from "./tooling.mjs";

const treePath = resolve(ROOT, "taxonomy/mb-tag-genre/v1/discogs-genre-tree.json");
const tree = JSON.parse(readFileSync(treePath, "utf8"));

test("the committed Discogs genre tree is valid and records its dump", () => {
  assert.deepEqual(validateGenreTree(tree), []);
  assert.match(tree.source.dump_date, /^[0-9]{8}$/);
  assert.equal(tree.rule.share_threshold, "0.20");
  for (const input of tree.source.inputs) assert.match(input.sha256, /^[0-9a-f]{64}$/);
});

test("every genre has at most 255 children, the TypeSafe Choice limit", () => {
  assert.equal(MAX_CHILDREN, 255);
  for (const entry of tree.genres) assert.ok(entry.children.length <= 255, `${entry.genre} has ${entry.children.length} children`);
});

test("the validator rejects an over-limit genre, a junk genre and a below-share non-dominant parent", () => {
  const over = structuredClone(tree);
  over.genres[0].children = Array.from({ length: 256 }, (_, i) => ({ style: `s${String(i).padStart(3, "0")}`, records: 1, genre_records: 1 }));
  assert.match(validateGenreTree(over).join("\n"), /over the 255-option Choice limit/);

  const junk = structuredClone(tree);
  junk.rule.dropped_genres = [junk.genres[0].genre];
  assert.match(validateGenreTree(junk).join("\n"), /dropped junk genre is present/);

  const weak = {
    ...structuredClone(tree),
    genres: [
      { genre: "A", records: 100, children: [{ style: "S", records: 100, genre_records: 90 }] },
      { genre: "B", records: 100, children: [{ style: "S", records: 100, genre_records: 10 }] },
    ],
  };
  assert.match(validateGenreTree(weak).join("\n"), /B\/S is below the 0.20 share/);
});

function xml(kind, records) {
  const body = records
    .map(([genres, styles]) => `<${kind}><genres>${genres.map((g) => `<genre>${g}</genre>`).join("")}</genres><styles>${styles.map((s) => `<style>${s}</style>`).join("")}</styles></${kind}>`)
    .join("");
  return gzipSync(Buffer.from(`<${kind}s>${body}</${kind}s>`));
}

test("the generator rebuilds the tree byte-identically from a dump stream, applying the share rule", (t) => {
  const probe = spawnSync("python3", ["--version"]);
  if (probe.error) return t.skip("python3 is unavailable");
  const dir = mkdtempSync(join(tmpdir(), "genre-tree-"));
  try {
    // Style X: 7 records Rock, 2 Pop, 1 Jazz -> Rock (0.7) and Pop (0.2) kept, Jazz (0.1) dropped.
    // Style Y: only genre "1" (junk) plus Rock -> Rock is the dominant parent. Style Z: one Jazz record.
    const masters = [
      ...Array.from({ length: 4 }, () => [["Rock"], ["X"]]),
      [["Pop"], ["X"]],
      [["1", "Rock"], ["Y"]],
    ];
    const releases = [
      ...Array.from({ length: 3 }, () => [["Rock"], ["X"]]),
      [["Pop"], ["X"]],
      [["Jazz"], ["X"]],
      [["Jazz"], ["Z"]],
      [["Rock"], []],
    ];
    writeFileSync(join(dir, "m.xml.gz"), xml("master", masters));
    writeFileSync(join(dir, "r.xml.gz"), xml("release", releases));
    const outputs = [join(dir, "a.json"), join(dir, "b.json")];
    for (const out of outputs) {
      const run = spawnSync("python3", ["-I", resolve(ROOT, "scripts/discogs-genre-tree.py"), "--dump-date", "20990101", "--masters", join(dir, "m.xml.gz"), "--releases", join(dir, "r.xml.gz"), "--out", out], { encoding: "utf8" });
      assert.equal(run.status, 0, run.stderr);
    }
    const first = readFileSync(outputs[0], "utf8");
    assert.equal(first, readFileSync(outputs[1], "utf8"), "two runs must be byte-identical");
    const built = JSON.parse(first);
    assert.deepEqual(validateGenreTree(built), []);
    const byGenre = Object.fromEntries(built.genres.map((g) => [g.genre, g.children.map((c) => c.style)]));
    assert.deepEqual(byGenre, { Jazz: ["Z"], Pop: ["X"], Rock: ["X", "Y"] });
    assert.deepEqual(built.counts, { genres: 3, styles: 3, pairs: 4, styles_with_2plus_parents: 1, max_children: 2 });
    for (const input of built.source.inputs) assert.match(input.sha256, /^[0-9a-f]{64}$/);
    // The committed sample fixture was produced before the iterparse root was cleared; same records, same tree.
    const sample = JSON.parse(readFileSync(resolve(ROOT, "taxonomy/mb-tag-genre/v1/fixtures/discogs-genre-tree-sample.json"), "utf8"));
    assert.deepEqual(built.genres, sample.genres);
    assert.deepEqual(built.counts, sample.counts);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
