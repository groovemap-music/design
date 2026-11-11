// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import { validateReviewQueue, validateTagLookup } from "./mb-tag-genre.mjs";
import { buildReviewData, itemLines, mergeExport, otherAnswer, renderDocument, renderReviewData } from "./mb-tag-review.mjs";
import { ROOT, sha256 } from "./tooling.mjs";

const V1 = resolve(ROOT, "taxonomy/mb-tag-genre/v1");
const REVIEW = resolve(ROOT, "taxonomy/mb-tag-genre/review");
const SCRIPT = resolve(ROOT, "scripts/mb-tag-review.mjs");
const lookupBytes = readFileSync(join(V1, "mb-tag-genre.json"));
const lookup = JSON.parse(lookupBytes.toString("utf8"));
const queueText = readFileSync(join(V1, "review-queue.json"), "utf8");
const queue = JSON.parse(queueText);
const tree = JSON.parse(readFileSync(join(V1, "discogs-genre-tree.json"), "utf8"));
const SHA = sha256(lookupBytes);
const AT = "2026-11-11T18:00:00.000Z";

const byTag = (tag) => lookup.rows.find((row) => row.tag === tag);
const disagree = lookup.rows.find((row) => row.bucket === "disagree" && row.proposals.claude !== null && row.proposals.claude.length > 0 && row.proposals.jev.length > 0);
const agree = lookup.rows.find((row) => row.bucket === "agree_genre");
const exportOf = (rows, over = {}) => ({ export_version: "1", queue_version: "1", lookup: { dump: lookup.source.musicbrainz.dump, sha256: SHA }, exported_at: AT, rows, ...over });
const entry = (row, decision, over = {}) => ({ tag: row.tag, decision, result: decision === "none" ? [] : row.result, reviewer: "robert", at: AT, ...over });
const merge = (exported) => mergeExport(exported, lookupBytes, lookup, queueText, tree);

test("the writer reproduces the generator's files byte for byte", () => {
  assert.equal(renderDocument(lookup, "rows"), lookupBytes.toString("utf8"));
  const raw = itemLines(queueText);
  assert.equal(renderDocument(queue, "rows", queue.rows.map((row) => raw.get(row.tag))), queueText);
});

test("accept default records Claude's answer as reviewed", () => {
  const out = merge(exportOf([entry(disagree, "accept_default")]));
  assert.deepEqual(out.errors, []);
  const row = out.lookup.rows.find((item) => item.tag === disagree.tag);
  assert.deepEqual(row.result, disagree.proposals.claude);
  assert.equal(row.review_state, "reviewed");
  assert.equal(row.reviewer, "robert");
  assert.equal(row.decision, "accept_default");
  assert.equal(row.reviewed_at, AT);
  assert.equal(out.lookup.counts.reviewed, 1);
  assert.equal(out.lookup.counts.pending, lookup.counts.pending - 1);
  assert.equal(out.queue.rows.length, queue.rows.length - 1);
  assert.equal(out.lookup.publishable, false, "a partly reviewed lookup stays committable and unpublished");
  assert.deepEqual(validateTagLookup(out.lookup, tree), []);
  assert.deepEqual(validateReviewQueue(out.queue, out.lookup), []);
});

test("accept the other model records Jev's answer when Claude is the default", () => {
  assert.notDeepEqual(disagree.proposals.jev, disagree.proposals.claude);
  const out = merge(exportOf([entry(disagree, "accept_other", { result: disagree.proposals.jev })]));
  assert.deepEqual(out.errors, []);
  assert.deepEqual(out.lookup.rows.find((item) => item.tag === disagree.tag).result, disagree.proposals.jev);
  assert.deepEqual(otherAnswer(disagree.proposals), disagree.proposals.jev);
  const wrong = merge(exportOf([entry(disagree, "accept_other", { result: disagree.proposals.claude })]));
  assert.match(wrong.errors[0], /is not/);
});

test("NONE leaves a model-proposed tag unmapped but reviewed", () => {
  const out = merge(exportOf([entry(agree, "none")]));
  assert.deepEqual(out.errors, []);
  const row = out.lookup.rows.find((item) => item.tag === agree.tag);
  assert.deepEqual(row.result, []);
  assert.equal(row.review_state, "reviewed");
  assert.equal(row.decision, "none");
});

test("pick another path takes a path in the tree and rejects one that is not", () => {
  const genre = tree.genres[0];
  const path = [genre.genre, genre.children[0].style];
  const out = merge(exportOf([entry(agree, "pick", { result: path })]));
  assert.deepEqual(out.errors, []);
  assert.deepEqual(out.lookup.rows.find((item) => item.tag === agree.tag).result, path);
  assert.deepEqual(merge(exportOf([entry(agree, "pick", { result: [genre.genre] })])).errors, []);
  for (const bad of [[genre.genre, "No Such Style"], ["No Such Genre"], [], "Rock", null]) {
    const refused = merge(exportOf([entry(agree, "pick", { result: bad })]));
    assert.match(refused.errors.join("\n"), /not a genre or style path in the tree/);
  }
});

test("an export for a tag that is not in the queue is rejected", () => {
  const unknown = merge(exportOf([{ ...entry(agree, "accept_default"), tag: "no such tag in the queue" }]));
  assert.match(unknown.errors.join("\n"), /not a tag in the queue/);
  assert.equal(unknown.lookup, undefined);
  const string = lookup.rows.find((row) => row.bucket === "string");
  assert.match(merge(exportOf([entry(string, "accept_default")])).errors.join("\n"), /not pending/);
  const none = lookup.rows.find((row) => row.bucket === "agree_none");
  assert.match(merge(exportOf([entry(none, "none")])).errors.join("\n"), /not pending/);
});

test("an export made against a different lookup is refused as stale", () => {
  const stale = merge(exportOf([entry(agree, "accept_default")], { lookup: { dump: lookup.source.musicbrainz.dump, sha256: "0".repeat(64) } }));
  assert.match(stale.errors.join("\n"), /stale export/);
  assert.equal(stale.lookup, undefined);
  // After a merge the lookup changes, so the export that was just merged is stale on a second merge.
  const first = merge(exportOf([entry(agree, "accept_default")]));
  const nextBytes = Buffer.from(renderDocument(first.lookup, "rows"));
  const again = mergeExport(exportOf([entry(disagree, "accept_default")]), nextBytes, first.lookup, queueText, tree);
  assert.match(again.errors.join("\n"), /stale export/);
});

test("a row needs a reviewer, a timestamp, a known decision and no duplicate", () => {
  assert.match(merge(exportOf([entry(agree, "accept_default", { reviewer: "" })])).errors.join("\n"), /no reviewer/);
  assert.match(merge(exportOf([entry(agree, "accept_default", { at: "yesterday" })])).errors.join("\n"), /ISO 8601/);
  assert.match(merge(exportOf([entry(agree, "approve")])).errors.join("\n"), /unknown decision/);
  assert.match(merge(exportOf([entry(agree, "accept_default"), entry(agree, "none")])).errors.join("\n"), /more than once/);
  assert.match(merge(exportOf([entry(agree, "accept_default", { result: [] })])).errors.join("\n"), /says accept_default/);
  assert.match(merge({ ...exportOf([]), export_version: "2" }).errors.join("\n"), /export_version/);
});

test("the merge is deterministic and ignores row order", () => {
  const rows = queue.rows.slice(0, 40).map((row, i) => entry(byTag(row.tag), i % 3 === 0 ? "none" : "accept_default", { at: `2026-11-11T18:00:${String(i).padStart(2, "0")}Z` }));
  const one = merge(exportOf(rows));
  const two = merge(exportOf([...rows].reverse(), { exported_at: "2026-12-01T00:00:00Z" }));
  assert.deepEqual(one.errors, []);
  const files = (out) => renderDocument(out.lookup, "rows") + renderDocument(out.queue, "rows", out.queueItems);
  assert.equal(files(one), files(two));
});

test("the lookup becomes publishable only when the queue is empty, and then needs every reviewer", () => {
  const partial = { ...lookup, rows: lookup.rows.map((row) => row), publishable: false };
  assert.deepEqual(validateTagLookup(partial, tree), [], "partial review is valid while unpublishable");
  const marked = { ...lookup, publishable: true };
  assert.match(validateTagLookup(marked, tree).join("\n"), /publishable lookup carries pending row/);
  // Review every pending row, then the merge marks it publishable.
  const all = queue.rows.map((row, i) => ({ tag: row.tag, decision: i % 2 ? "none" : "accept_default", result: i % 2 ? [] : row.default, reviewer: "robert", at: AT }));
  const done = merge(exportOf(all));
  assert.deepEqual(done.errors, []);
  assert.equal(done.lookup.publishable, true);
  assert.equal(done.lookup.counts.pending, 0);
  assert.equal(done.queue.rows.length, 0);
  assert.deepEqual(validateTagLookup(done.lookup, tree), []);
  const stripped = { ...done.lookup, rows: done.lookup.rows.map((row, i) => (i === done.lookup.rows.findIndex((r) => r.proposals && r.result.length) ? { ...row, review_state: "not_required", reviewer: null } : row)) };
  assert.match(validateTagLookup(stripped, tree).join("\n"), /unreviewed model-proposed genre row/);
});

test("the CLI merges a file, refuses a bad one without writing, and rebuilds the page data", () => {
  const dir = mkdtempSync(join(tmpdir(), "mb-review-"));
  try {
    const paths = { lookup: join(dir, "mb-tag-genre.json"), queue: join(dir, "review-queue.json"), data: join(dir, "data.js"), good: join(dir, "good.json"), bad: join(dir, "bad.json") };
    writeFileSync(paths.lookup, lookupBytes);
    writeFileSync(paths.queue, queueText);
    writeFileSync(paths.good, JSON.stringify(exportOf([entry(agree, "accept_default")])));
    writeFileSync(paths.bad, JSON.stringify(exportOf([{ ...entry(agree, "accept_default"), tag: "nope" }])));
    const run = (file) => spawnSync("node", [SCRIPT, "merge", "--export", file, "--lookup", paths.lookup, "--queue", paths.queue, "--tree", join(V1, "discogs-genre-tree.json"), "--data", paths.data], { encoding: "utf8" });
    const bad = run(paths.bad);
    assert.equal(bad.status, 1);
    assert.deepEqual(readFileSync(paths.lookup), lookupBytes, "a refused export writes nothing");
    const good = run(paths.good);
    assert.equal(good.status, 0, good.stderr);
    const merged = JSON.parse(readFileSync(paths.lookup, "utf8"));
    assert.equal(merged.counts.reviewed, 1);
    assert.match(readFileSync(paths.data, "utf8"), new RegExp(sha256(readFileSync(paths.lookup))));
    assert.equal(run(paths.good).status, 1, "the same export is now stale");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("the committed page data is the data built from the committed lookup", () => {
  assert.equal(readFileSync(join(REVIEW, "data.js"), "utf8"), renderReviewData(buildReviewData(lookupBytes, lookup, queue, tree)), "run: just tag-review-build");
});

// --- the page's logic, run without a browser ---------------------------------------------------

// core.js is a classic browser script with no DOM access: evaluating it here defines globalThis.MBReview.
(0, eval)(readFileSync(join(REVIEW, "core.js"), "utf8"));
const R = globalThis.MBReview;
const data = JSON.parse(JSON.stringify(buildReviewData(lookupBytes, lookup, queue, tree)));

test("page: every action has an undo and progress counts by decision", () => {
  const state = R.newState(data);
  state.reviewer = "robert";
  const first = data.rows[0].t;
  assert.ok(R.apply(data, state, "accept_default", undefined, AT));
  assert.equal(state.pos, 1);
  assert.ok(R.apply(data, state, "none", undefined, AT));
  assert.ok(R.apply(data, state, "skip", undefined, AT));
  assert.ok(R.apply(data, state, "pick", ["Rock", "Prog Rock"], AT));
  const c = R.counts(data, state);
  assert.deepEqual([c.decided, c.accept_default, c.none, c.skip, c.pick, c.open], [3, 1, 1, 1, 1, data.rows.length - 3]);
  for (let i = 0; i < 4; i += 1) assert.ok(R.undo(data, state));
  assert.equal(R.undo(data, state), false);
  assert.equal(R.counts(data, state).decided, 0);
  assert.equal(state.pos, 0);
  assert.equal(state.decisions[first], undefined);
  assert.ok(R.redo(data, state));
  assert.equal(state.decisions[first].action, "accept_default");
});

test("page: a skipped row comes back after the open rows", () => {
  const state = R.newState(data);
  const last = data.rows.length - 1;
  R.apply(data, state, "skip", undefined, AT);
  assert.equal(state.pos, 1);
  assert.equal(R.nextOpen(data, state, last), 1);
  for (let i = 1; i <= last; i += 1) state.decisions[data.rows[i].t] = { action: "none", result: [], at: AT, reviewer: "r" };
  assert.equal(R.nextOpen(data, state, 5), 0, "only the skipped row is left");
});

test("page: accept other is off when the other model gave no answer", () => {
  const row = { t: "x", u: 1, b: "disagree", d: ["Rock"], j: ["Rock"], c: null, k: [] };
  assert.equal(R.otherPath(row), null);
  assert.equal(R.resolve(data.rows.find((r) => r.b === "disagree" && r.c && r.c.length), "accept_other"), data.rows.find((r) => r.b === "disagree" && r.c && r.c.length).j);
});

test("page: fuzzy search finds a style through any word order and a typo-free subsequence", () => {
  const options = R.buildOptions(data.tree);
  assert.deepEqual(R.search(options, "prog rock", 3)[0].path, ["Rock", "Prog Rock"]);
  assert.deepEqual(R.search(options, "trip hop", 2).map((o) => o.label).sort(), ["Electronic \u203a Trip Hop", "Hip Hop \u203a Trip Hop"]);
  assert.deepEqual(R.search(options, "hvymtl", 3)[0].path, ["Rock", "Heavy Metal"]);
  assert.deepEqual(R.search(options, "none", 1)[0].path, []);
  assert.equal(R.search(options, "zzzzqqq", 3).length, 0);
});

test("page: an export round-trips through the merge script, and a stale file is refused on import", () => {
  const state = R.newState(data);
  state.reviewer = "robert";
  R.apply(data, state, "accept_default", undefined, AT);
  R.apply(data, state, "accept_other", undefined, AT);
  R.apply(data, state, "none", undefined, AT);
  R.apply(data, state, "skip", undefined, AT);
  const exported = R.buildExport(data, state, AT);
  assert.equal(exported.rows.length, 3, "a skip is not an export row");
  assert.equal(exported.lookup.sha256, SHA);
  const out = merge(JSON.parse(JSON.stringify(exported)));
  assert.deepEqual(out.errors, []);
  assert.equal(out.lookup.counts.reviewed, 3);

  const fresh = R.newState(data);
  assert.deepEqual(R.importProgress(data, fresh, exported), { imported: 3, skipped: 0 });
  assert.equal(R.counts(data, fresh).decided, 3);
  assert.equal(fresh.pos, 3, "resumes at the first open row; the skipped row was not exported, so it is open again");
  const stale = R.importProgress(data, R.newState(data), { ...exported, lookup: { ...exported.lookup, sha256: "f".repeat(64) } });
  assert.match(stale.error, /different lookup/);
});
