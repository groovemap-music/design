// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import { validateReviewQueue, validateTagLookup } from "./mb-tag-genre.mjs";
import { buildReviewData, itemLines, mergeExport, otherAnswer, renderDocument, renderReviewData, rowHash } from "./mb-tag-review.mjs";
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
const exportOf = (rows, over = {}) => ({ export_version: "1", queue_version: "1", lookup: { dump: lookup.source.musicbrainz.dump, tree_dump_date: lookup.source.tree.dump_date }, exported_at: AT, rows, ...over });
const entry = (row, decision, over = {}) => ({ tag: row.tag, h: rowHash(row), decision, result: decision === "none" ? [] : row.result, reviewer: "robert", at: AT, ...over });
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
  assert.match(merge(exportOf([entry(string, "accept_default")])).errors.join("\n"), /not a queue row/);
  const none = lookup.rows.find((row) => row.bucket === "agree_none");
  assert.match(merge(exportOf([entry(none, "none")])).errors.join("\n"), /not a queue row/);
});

// A second sitting: the operator merges an export, keeps the old lookup's decisions in the page, and exports again.
const asMerged = (out) => ({ bytes: Buffer.from(renderDocument(out.lookup, "rows")), lookup: out.lookup, queueText: renderDocument(out.queue, "rows", out.queueItems) });
const mergeOn = (state, exported, flags) => mergeExport(exported, state.bytes, state.lookup, state.queueText, tree, flags);

test("decisions made after an export survive merging that export", () => {
  const [a, b, c] = queue.rows.slice(0, 3).map((row) => byTag(row.tag));
  const exportA = exportOf([entry(a, "accept_default")]);
  const exportLater = exportOf([entry(a, "accept_default"), entry(b, "none"), entry(c, "accept_default")]);
  const afterA = merge(exportA);
  assert.deepEqual(afterA.errors, []);
  const state = asMerged(afterA);
  assert.notEqual(sha256(state.bytes), SHA, "the merge changed the lookup");
  // The later export, made against the pre-merge page, still merges: a is already merged and identical.
  const later = mergeOn(state, exportLater);
  assert.deepEqual(later.errors, []);
  assert.equal(later.merged, 2);
  assert.equal(later.unchanged, 1);
  assert.equal(later.lookup.counts.reviewed, 3);
});

test("merging the same export again is a no-op", () => {
  const exported = exportOf(queue.rows.slice(0, 5).map((row) => entry(byTag(row.tag), "accept_default")));
  const first = merge(exported);
  const state = asMerged(first);
  const again = mergeOn(state, exported);
  assert.deepEqual(again.errors, []);
  assert.equal(again.merged, 0);
  assert.equal(again.unchanged, 5);
  assert.equal(renderDocument(again.lookup, "rows"), state.bytes.toString("utf8"));
  assert.equal(renderDocument(again.queue, "rows", again.queueItems), state.queueText);
});

test("a conflicting decision for a reviewed tag is rejected, and only --skip-rejected applies the rest", () => {
  const [a, b] = queue.rows.slice(0, 2).map((row) => byTag(row.tag));
  const state = asMerged(merge(exportOf([entry(a, "accept_default")])));
  const mixed = exportOf([entry(a, "none"), entry(b, "accept_default")]);
  const refused = mergeOn(state, mixed);
  assert.match(refused.errors.join("\n"), /conflicts with the lookup: it is already reviewed as/);
  assert.equal(refused.lookup, undefined);
  const partial = mergeOn(state, mixed, { skipRejected: true });
  assert.deepEqual(partial.errors, []);
  assert.equal(partial.rejected.length, 1);
  assert.equal(partial.merged, 1);
  assert.deepEqual(partial.lookup.rows.find((row) => row.tag === a.tag).result, a.proposals.claude ?? a.proposals.jev, "the reviewed answer is untouched");
  assert.equal(partial.lookup.rows.find((row) => row.tag === b.tag).review_state, "reviewed");
});

test("a row decided against a different row hash is rejected", () => {
  const out = merge(exportOf([entry(agree, "accept_default", { h: "0".repeat(16) })]));
  assert.match(out.errors.join("\n"), /decided against a different row/);
  assert.equal(out.lookup, undefined);
  const changed = JSON.parse(JSON.stringify(lookup));
  const row = changed.rows.find((item) => item.tag === agree.tag);
  row.proposals.jev = ["Jazz"];
  const out2 = mergeExport(exportOf([entry(agree, "accept_default")]), lookupBytes, changed, queueText, tree);
  assert.match(out2.errors.join("\n"), /decided against a different row/);
});

test("an export for a different queue_version, dump or tree is refused outright", () => {
  const version = merge(exportOf([entry(agree, "accept_default")], { queue_version: "2" }));
  assert.match(version.errors.join("\n"), /queue_version/);
  const dump = merge(exportOf([entry(agree, "accept_default")], { lookup: { dump: "20200101-000000", tree_dump_date: lookup.source.tree.dump_date } }));
  assert.match(dump.errors.join("\n"), /names dump/);
  const treeDate = merge(exportOf([entry(agree, "accept_default")], { lookup: { dump: lookup.source.musicbrainz.dump, tree_dump_date: "20200101" } }));
  assert.match(treeDate.errors.join("\n"), /tree dump/);
  assert.equal(merge(exportOf([entry(agree, "accept_default")], { queue_version: "2" })).lookup, undefined);
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
  const all = queue.rows.map((row, i) => ({ tag: row.tag, h: rowHash(byTag(row.tag)), decision: i % 2 ? "none" : "accept_default", result: i % 2 ? [] : row.default, reviewer: "robert", at: AT }));
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
    assert.match(readFileSync(paths.data, "utf8"), /"merged":\{"total":1,/);
    assert.equal(run(paths.good).status, 0, "the same export again is a no-op");
    assert.equal(JSON.parse(readFileSync(paths.lookup, "utf8")).counts.reviewed, 1);
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
  assert.equal(exported.lookup.dump, lookup.source.musicbrainz.dump);
  assert.ok(exported.rows.every((row) => /^[0-9a-f]{16}$/.test(row.h)));
  const out = merge(JSON.parse(JSON.stringify(exported)));
  assert.deepEqual(out.errors, []);
  assert.equal(out.lookup.counts.reviewed, 3);

  const fresh = R.newState(data);
  assert.deepEqual(R.importProgress(data, fresh, exported), { imported: 3, skipped: 0 });
  assert.equal(R.counts(data, fresh).decided, 3);
  assert.equal(fresh.pos, 3, "resumes at the first open row; the skipped row was not exported, so it is open again");
  assert.match(R.importProgress(data, R.newState(data), { ...exported, queue_version: "2" }).error, /different queue/);
  const edited = { ...exported, rows: exported.rows.map((row, i) => (i === 0 ? { ...row, h: "0".repeat(16) } : row)) };
  assert.deepEqual(R.importProgress(data, R.newState(data), edited), { imported: 2, skipped: 1 });
});

test("page: after a merge and reload, merged rows are done, unmerged decisions stay and counts are right", () => {
  const old = JSON.parse(JSON.stringify(data));
  const state = R.newState(old);
  state.reviewer = "robert";
  for (const action of ["accept_default", "none", "accept_default", "skip"]) R.apply(old, state, action, undefined, AT);
  const exportA = R.buildExport(old, { ...state, decisions: Object.fromEntries(Object.entries(state.decisions).slice(0, 2)) }, AT);
  const out = merge(JSON.parse(JSON.stringify(exportA)));
  assert.deepEqual(out.errors, []);
  const fresh = JSON.parse(JSON.stringify(buildReviewData(Buffer.from(renderDocument(out.lookup, "rows")), out.lookup, out.queue, tree)));
  assert.equal(R.storageKey(fresh), R.storageKey(old), "the progress key is stable across a merge");
  assert.equal(fresh.rows.length, old.rows.length - 2);
  assert.equal(fresh.total, old.total);
  const reloaded = JSON.parse(JSON.stringify(state));
  assert.deepEqual(R.reconcile(fresh, reloaded), { merged: 2, changed: 0 });
  const c = R.counts(fresh, reloaded);
  assert.deepEqual([c.total, c.decided, c.accept_default, c.none, c.skip], [old.total, 3, 2, 1, 1]);
  assert.equal(c.open, old.total - 3);
  assert.ok(reloaded.decisions[old.rows[2].t], "the unmerged decision is kept");
  const next = R.buildExport(fresh, reloaded, AT);
  assert.equal(next.rows.length, 1);
  assert.deepEqual(merge(next).errors, [], "and it merges");
  const stale = JSON.parse(JSON.stringify(state));
  const edited = JSON.parse(JSON.stringify(fresh));
  edited.rows.find((row) => row.t === old.rows[2].t).h = "0".repeat(16);
  assert.deepEqual(R.reconcile(edited, stale), { merged: 2, changed: 1 }, "a row that changed needs review again");
});
