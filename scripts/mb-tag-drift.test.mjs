// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import { diffTree, diffVocabulary, driftReport, reviewWork, summarize, treeChanges } from "./mb-tag-drift.mjs";
import { ROOT } from "./tooling.mjs";

const SCRIPT = resolve(ROOT, "scripts/mb-tag-drift.mjs");

const tree = (genres, date = "20261101") => ({ source: { dump_date: date }, genres: Object.entries(genres).map(([genre, styles]) => ({ genre, children: styles.map((style) => ({ style })) })) });
const row = (tag, uses, result, state = "reviewed") => ({ tag, uses, result, proposals: { jev: result, claude: result }, review_state: state });
const lookup = {
  source: { musicbrainz: { dump: "D1", min_uses: 20 }, tree: { dump_date: "20261101" } },
  rows: [row("house", 500, ["Electronic", "House"]), row("kept", 100, ["Rock"]), row("dwindling", 30, ["Rock"]), row("gone", 90, ["Jazz", "Bop"]), row("junk", 25, [], "not_required"), row("lost", 22, ["Jazz"])],
};
const oldTree = tree({ Electronic: ["House", "Techno"], Rock: ["Punk"], Jazz: ["Bop"] });
const vocab = (tags) => ({ min_uses: 5, source: { dump: "D2", sha256: "x" }, counts: { tags_kept: tags.length, uses_kept: tags.reduce((s, t) => s + t[1], 0) }, tags: tags.map(([tag, uses]) => ({ tag, uses })).sort((a, b) => b.uses - a.uses || (a.tag < b.tag ? -1 : 1)) });
const newVocab = vocab([["house", 600], ["kept", 100], ["dwindling", 25], ["junk", 20], ["fresh", 80], ["fresher", 21], ["lost", 19], ["tiny", 5]]);

test("vocabulary drift: new tags, fell below scope, vanished, use changes", () => {
  const d = diffVocabulary(lookup, newVocab);
  assert.deepEqual(d.new_tags, [{ tag: "fresh", uses: 80 }, { tag: "fresher", uses: 21 }]);
  assert.deepEqual(d.fell_below_scope.map((r) => r.tag), ["lost"]);
  assert.deepEqual(d.vanished.map((r) => r.tag), ["gone"]);
  assert.deepEqual(d.use_changes, { tags_compared: 4, up: 1, down: 2, unchanged: 1, uses_before: 655, uses_after: 745, uses_delta: 90 });
});

test("a tag under the lookup's min_uses is not a new tag", () => {
  assert.equal(diffVocabulary(lookup, newVocab).new_tags.some((t) => t.tag === "tiny"), false);
});

test("tree drift: paths missing from the newer tree, with where the style moved", () => {
  const next = tree({ Electronic: ["Techno"], "House Music": ["House"], Rock: ["Punk"] }, "20270101");
  const d = diffTree(lookup, next);
  const broken = d.broken_paths.filter((b) => b.tag === "house").map((b) => b.field);
  assert.deepEqual(broken, ["result", "jev", "claude"]);
  assert.deepEqual(d.broken_paths[0].candidates, [["House Music", "House"]]);
  assert.equal(d.broken_paths.find((b) => b.tag === "gone").genre_missing, true);
  assert.equal(d.broken_paths.some((b) => b.tag === "kept"), false);
  assert.deepEqual(d.tree, { dump_date: "20270101", genres: 3, styles: 3 });
});

test("an unchanged tree has no broken paths; tree changes list what moved", () => {
  assert.equal(driftReport(lookup, { tree: oldTree }).broken, 0);
  const changes = treeChanges(oldTree, tree({ Electronic: ["House"], Folk: [] }));
  assert.deepEqual(changes.genres_added, ["Folk"]);
  assert.deepEqual(changes.genres_removed, ["Jazz", "Rock"]);
  assert.deepEqual(changes.pairs_removed, ["Electronic / Techno", "Jazz / Bop", "Rock / Punk"]);
});

test("review work lists tags to propose and rows to re-check", () => {
  const report = driftReport(lookup, { vocabulary: newVocab, tree: tree({ Electronic: ["Techno"], Rock: ["Punk"] }), oldTree });
  const work = reviewWork(report);
  assert.deepEqual(work.propose, [{ tag: "fresh", uses: 80 }, { tag: "fresher", uses: 21 }]);
  const tags = work.reverify.map((r) => r.tag);
  assert.deepEqual(tags, ["gone", "house", "lost"]);
  assert.match(summarize(report), /RESULT: broken paths/);
});

function run(files, args) {
  const dir = mkdtempSync(join(tmpdir(), "mb-drift-"));
  try {
    const paths = {};
    for (const [name, value] of Object.entries(files)) {
      paths[name] = join(dir, `${name}.json`);
      writeFileSync(paths[name], JSON.stringify(value));
    }
    const out = join(dir, "report.json");
    const review = join(dir, "review.json");
    const argv = args(paths).concat(["--out", out, "--out-review", review]);
    const result = spawnSync(process.execPath, [SCRIPT, ...argv], { encoding: "utf8" });
    const read = (p) => { try { return JSON.parse(readFileSync(p, "utf8")); } catch { return null; } };
    return { status: result.status, stderr: result.stderr, report: read(out), review: read(review) };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("exit 0 when only tags drifted, and the JSON and review files are written", () => {
  const r = run({ lookup, vocab: newVocab }, (p) => ["--lookup", p.lookup, "--new-vocab", p.vocab]);
  assert.equal(r.status, 0);
  assert.equal(r.report.new_tags.length, 2);
  assert.equal(r.review.propose.length, 2);
  assert.match(r.stderr, /2 new tags, 1 fell below scope, 1 vanished/);
});

test("exit 1 on a broken path, 0 with the same tree", () => {
  const broken = run({ lookup, oldTree, next: tree({ Electronic: ["Techno"], Rock: ["Punk"], Jazz: ["Bop"] }) }, (p) => ["--lookup", p.lookup, "--tree", p.oldTree, "--new-tree", p.next]);
  assert.equal(broken.status, 1);
  assert.equal(broken.report.broken_paths[0].tag, "house");
  const clean = run({ lookup, oldTree }, (p) => ["--lookup", p.lookup, "--new-tree", p.oldTree]);
  assert.equal(clean.status, 0);
});

test("exit 2 on bad usage and unreadable or invalid input", () => {
  assert.equal(spawnSync(process.execPath, [SCRIPT, "--lookup", "x"], { encoding: "utf8" }).status, 2);
  assert.equal(run({ lookup }, (p) => ["--lookup", p.lookup, "--new-vocab", join(tmpdir(), "no-such-vocab.json")]).status, 2);
  const unsorted = { ...newVocab, tags: [...newVocab.tags].reverse() };
  assert.equal(run({ lookup, vocab: unsorted }, (p) => ["--lookup", p.lookup, "--new-vocab", p.vocab]).status, 2);
});

test("the committed v1 lookup has no drift against its own tree", () => {
  const base = resolve(ROOT, "taxonomy/mb-tag-genre/v1");
  const result = spawnSync(process.execPath, [SCRIPT, "--lookup", join(base, "mb-tag-genre.json"), "--new-tree", join(base, "discogs-genre-tree.json"), "--new-vocab", join(base, "mb-tag-vocabulary.json")], { encoding: "utf8" });
  assert.equal(result.status, 0);
  const report = JSON.parse(result.stdout);
  assert.equal(report.new_tags.length, 0);
  assert.equal(report.vanished.length, 0);
});
