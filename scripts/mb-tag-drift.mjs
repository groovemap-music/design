// SPDX-License-Identifier: MIT

// Offline drift check for mb-tag-genre (ADR 0020). It compares the committed lookup with a newer tag
// vocabulary (built by `mb-tag-genre.py vocab` from a newer dump), a newer Discogs genre tree, or both.
// It reads local files only: no network, no model calls, and it never runs the generator.
//
// Exit status: 0 no broken paths (other drift is review work, not failure), 1 a lookup result or proposal
// names a tree path the newer tree no longer has, 2 bad usage or unreadable input.

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { byCodepoint, pathInTree, treeIndex, validateTagVocabulary } from "./mb-tag-genre.mjs";

export const REPORT_VERSION = "1";
export const EXIT_BROKEN_PATHS = 1;
export const EXIT_USAGE = 2;

const show = (path) => (path.length === 0 ? "NONE" : path.join(" / "));

// Where a style now lives in the tree, so a reviewer sees the likely replacement for a moved style.
function styleParents(index) {
  const parents = new Map();
  for (const [genre, styles] of index) for (const style of styles) parents.set(style, [...(parents.get(style) ?? []), genre]);
  return parents;
}

export function diffVocabulary(lookup, vocabulary) {
  const minUses = lookup.source.musicbrainz.min_uses;
  const known = new Map(lookup.rows.map((row) => [row.tag, row]));
  const next = new Map(vocabulary.tags.map((row) => [row.tag, row.uses]));
  const newTags = [];
  for (const [tag, uses] of next) if (!known.has(tag) && uses >= minUses) newTags.push({ tag, uses });
  newTags.sort((a, b) => b.uses - a.uses || byCodepoint(a.tag, b.tag));
  const fellBelow = [];
  const vanished = [];
  let up = 0;
  let down = 0;
  let unchanged = 0;
  let usesBefore = 0;
  let usesAfter = 0;
  for (const row of lookup.rows) {
    if (!next.has(row.tag)) {
      vanished.push({ tag: row.tag, uses: row.uses, review_state: row.review_state, mapped: row.result.length > 0 });
      continue;
    }
    const uses = next.get(row.tag);
    if (uses < minUses) {
      fellBelow.push({ tag: row.tag, uses_before: row.uses, uses_after: uses, review_state: row.review_state, mapped: row.result.length > 0 });
      continue;
    }
    usesBefore += row.uses;
    usesAfter += uses;
    if (uses > row.uses) up += 1;
    else if (uses < row.uses) down += 1;
    else unchanged += 1;
  }
  const bySize = (a, b) => (b.uses ?? b.uses_before) - (a.uses ?? a.uses_before) || byCodepoint(a.tag, b.tag);
  fellBelow.sort(bySize);
  vanished.sort(bySize);
  return {
    new_tags: newTags,
    fell_below_scope: fellBelow,
    vanished,
    use_changes: { tags_compared: up + down + unchanged, up, down, unchanged, uses_before: usesBefore, uses_after: usesAfter, uses_delta: usesAfter - usesBefore },
  };
}

export function diffTree(lookup, tree) {
  const index = treeIndex(tree);
  const parents = styleParents(index);
  const broken = [];
  for (const row of lookup.rows) {
    const fields = [["result", row.result], ["jev", row.proposals?.jev], ["claude", row.proposals?.claude]];
    for (const [field, path] of fields) {
      if (!Array.isArray(path) || pathInTree(index, path)) continue;
      const style = path[1] ?? path[0];
      broken.push({
        tag: row.tag,
        field,
        path,
        review_state: row.review_state,
        genre_missing: !index.has(path[0]),
        candidates: (parents.get(style) ?? []).map((genre) => [genre, style]),
      });
    }
  }
  return { broken_paths: broken, tree: { dump_date: tree.source?.dump_date ?? null, genres: index.size, styles: parents.size } };
}

// Genres and styles that the old tree had and the new one lacks, or the reverse: context for the reviewer.
export function treeChanges(oldTree, newTree) {
  const names = (tree) => {
    const index = treeIndex(tree);
    const genres = new Set(index.keys());
    const pairs = new Set();
    for (const [genre, styles] of index) for (const style of styles) pairs.add(`${genre} / ${style}`);
    return { genres, pairs };
  };
  const a = names(oldTree);
  const b = names(newTree);
  const minus = (x, y) => [...x].filter((value) => !y.has(value)).sort(byCodepoint);
  return {
    genres_added: minus(b.genres, a.genres),
    genres_removed: minus(a.genres, b.genres),
    pairs_added: minus(b.pairs, a.pairs).length,
    pairs_removed: minus(a.pairs, b.pairs),
  };
}

// The review work the existing generator and queue take: tags to propose (run `propose` on the newer
// vocabulary, which carries reviewed rows and replays captures) and reviewed rows that need a second look.
export function reviewWork(report) {
  const reverify = new Map();
  for (const item of report.broken_paths ?? []) {
    const entry = reverify.get(item.tag) ?? { tag: item.tag, reasons: ["path_not_in_tree"], review_state: item.review_state, paths: [], candidates: [] };
    entry.paths.push({ field: item.field, path: item.path });
    for (const candidate of item.candidates) if (!entry.candidates.some((c) => c.join() === candidate.join())) entry.candidates.push(candidate);
    reverify.set(item.tag, entry);
  }
  for (const row of [...(report.fell_below_scope ?? []), ...(report.vanished ?? [])]) {
    if (row.review_state !== "reviewed" || !row.mapped) continue;
    const entry = reverify.get(row.tag) ?? { tag: row.tag, reasons: [], review_state: row.review_state, paths: [], candidates: [] };
    entry.reasons.push("out_of_scope_but_mapped");
    reverify.set(row.tag, entry);
  }
  return {
    review_work_version: REPORT_VERSION,
    lookup: report.lookup,
    inputs: report.inputs,
    propose: (report.new_tags ?? []).map(({ tag, uses }) => ({ tag, uses })),
    reverify: [...reverify.values()].sort((a, b) => byCodepoint(a.tag, b.tag)),
  };
}

export function driftReport(lookup, { vocabulary = null, tree = null, oldTree = null } = {}) {
  const report = {
    report_version: REPORT_VERSION,
    lookup: { dump: lookup.source.musicbrainz.dump, tree_dump_date: lookup.source.tree.dump_date, min_uses: lookup.source.musicbrainz.min_uses, tags: lookup.rows.length },
    inputs: { vocabulary_dump: vocabulary?.source?.dump ?? null, tree_dump_date: tree?.source?.dump_date ?? null },
  };
  if (vocabulary) Object.assign(report, diffVocabulary(lookup, vocabulary));
  if (tree) {
    Object.assign(report, diffTree(lookup, tree));
    if (oldTree) report.tree_changes = treeChanges(oldTree, tree);
  }
  report.broken = (report.broken_paths ?? []).length;
  return report;
}

export function summarize(report) {
  const lines = [`mb-tag-genre drift: lookup dump ${report.lookup.dump}, tree ${report.lookup.tree_dump_date}, ${report.lookup.tags} tags (min_uses ${report.lookup.min_uses})`];
  if (report.new_tags) {
    lines.push(`  vocabulary ${report.inputs.vocabulary_dump}: ${report.new_tags.length} new tags, ${report.fell_below_scope.length} fell below scope, ${report.vanished.length} vanished`);
    const u = report.use_changes;
    lines.push(`  use counts over ${u.tags_compared} shared tags: ${u.up} up, ${u.down} down, ${u.unchanged} unchanged, total ${u.uses_delta >= 0 ? "+" : ""}${u.uses_delta}`);
  }
  if (report.broken_paths) {
    lines.push(`  tree ${report.inputs.tree_dump_date}: ${report.broken_paths.length} lookup paths no longer exist`);
    for (const item of report.broken_paths.slice(0, 20)) lines.push(`    BROKEN ${JSON.stringify(item.tag)} ${item.field}: ${show(item.path)}${item.candidates.length ? ` (now under ${item.candidates.map(show).join(", ")})` : ""}`);
    if (report.broken_paths.length > 20) lines.push(`    ... and ${report.broken_paths.length - 20} more in the JSON report`);
  }
  lines.push(report.broken > 0 ? "  RESULT: broken paths, cut a new version or re-review the rows above" : "  RESULT: no broken paths");
  return lines.join("\n");
}

function parseArgs(argv) {
  const found = {};
  const flags = { "--lookup": "lookup", "--tree": "oldTree", "--new-vocab": "newVocab", "--new-tree": "newTree", "--out": "out", "--out-review": "outReview" };
  for (let i = 0; i < argv.length; i += 1) {
    const key = flags[argv[i]];
    if (!key || i + 1 >= argv.length) return null;
    found[key] = argv[(i += 1)];
  }
  if (!found.lookup || (!found.newVocab && !found.newTree)) return null;
  return found;
}

const USAGE = "usage: mb-tag-drift.mjs --lookup FILE [--tree OLD_TREE] (--new-vocab FILE | --new-tree FILE | both) [--out report.json] [--out-review review-work.json]";

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (error) {
    throw new Error(`cannot read ${path}: ${error.message}`);
  }
}

export function main(argv) {
  const found = parseArgs(argv);
  if (!found) {
    console.error(USAGE);
    return EXIT_USAGE;
  }
  try {
    const lookup = readJson(found.lookup);
    const vocabulary = found.newVocab ? readJson(found.newVocab) : null;
    const tree = found.newTree ? readJson(found.newTree) : null;
    const oldTree = found.oldTree ? readJson(found.oldTree) : null;
    if (!Array.isArray(lookup.rows) || !lookup.source?.musicbrainz || !lookup.source?.tree) throw new Error(`${found.lookup} is not an mb-tag-genre lookup`);
    if (vocabulary) {
      const errors = validateTagVocabulary(vocabulary);
      if (errors.length > 0) throw new Error(`${found.newVocab} is not a valid vocabulary:\n- ${errors.join("\n- ")}`);
    }
    if (tree && !Array.isArray(tree.genres)) throw new Error(`${found.newTree} is not a Discogs genre tree`);
    const report = driftReport(lookup, { vocabulary, tree, oldTree });
    const text = `${JSON.stringify(report, null, 2)}\n`;
    if (found.out) writeFileSync(found.out, text);
    else process.stdout.write(text);
    if (found.outReview) writeFileSync(found.outReview, `${JSON.stringify(reviewWork(report), null, 2)}\n`);
    console.error(summarize(report));
    return report.broken > 0 ? EXIT_BROKEN_PATHS : 0;
  } catch (error) {
    console.error(error.message);
    return EXIT_USAGE;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exitCode = main(process.argv.slice(2));
