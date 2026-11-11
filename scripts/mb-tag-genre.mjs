// SPDX-License-Identifier: MIT

// Structural checks for mb-tag-genre/v1 (ADR 0020) that the JSON Schemas cannot express. The rule that
// matters most: a file marked publishable carries no model-proposed row that a person has not reviewed.

const BUCKETS = ["string", "agree_genre", "agree_none", "disagree"];

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const show = (path) => (path === null ? "no answer" : path.length === 0 ? "NONE" : path.join(" / "));
// Code point order, the order Python's sorted() gives the generator (UTF-16 order differs past U+FFFF).
export function byCodepoint(a, b) {
  const x = Array.from(a, (ch) => ch.codePointAt(0));
  const y = Array.from(b, (ch) => ch.codePointAt(0));
  for (let i = 0; i < Math.min(x.length, y.length); i += 1) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
}

export function treeIndex(tree) {
  return new Map((tree.genres ?? []).map((entry) => [entry.genre, new Set((entry.children ?? []).map((child) => child.style))]));
}

export function pathInTree(index, path) {
  if (path.length === 0) return true;
  if (!index.has(path[0])) return false;
  return path.length === 1 || index.get(path[0]).has(path[1]);
}

// Claude's answer is the default; Jev's when Claude gave no valid answer.
export function defaultAnswer(proposals) {
  return proposals.claude ?? proposals.jev;
}

export function validateTagLookup(lookup, tree) {
  const errors = [];
  const rows = lookup.rows ?? [];
  const index = tree ? treeIndex(tree) : null;
  const minUses = lookup.source?.musicbrainz?.min_uses ?? 1;
  const tags = rows.map((row) => row.tag);
  if (!same(tags, [...tags].sort(byCodepoint))) errors.push("rows must be sorted by tag");
  if (new Set(tags).size !== tags.length) errors.push("tags must be unique");
  if (tree && lookup.source?.tree?.dump_date !== tree.source?.dump_date) errors.push(`source.tree.dump_date ${lookup.source?.tree?.dump_date} is not the tree's ${tree.source?.dump_date}`);

  const counts = { tags: rows.length, string: 0, agree_genre: 0, agree_none: 0, disagree: 0, pending: 0, reviewed: 0 };
  for (const row of rows) {
    const where = `row ${JSON.stringify(row.tag)}`;
    if (BUCKETS.includes(row.bucket)) counts[row.bucket] += 1;
    if (row.review_state === "pending" || row.review_state === "reviewed") counts[row.review_state] += 1;
    if (row.uses < minUses) errors.push(`${where} has ${row.uses} uses, under min_uses ${minUses}`);
    const paths = [row.result, row.proposals?.jev, row.proposals?.claude].filter((path) => Array.isArray(path));
    if (index) for (const path of paths) if (!pathInTree(index, path)) errors.push(`${where} names ${show(path)}, which is not in the tree`);

    if (row.review_state === "reviewed" && !row.reviewer) errors.push(`${where} is reviewed but names no reviewer`);
    if (row.review_state !== "reviewed" && (row.decision !== undefined || row.reviewed_at !== undefined)) errors.push(`${where} carries a review decision but is ${row.review_state}`);
    if (row.review_state !== "reviewed" && row.reviewer !== null) errors.push(`${where} names a reviewer but is ${row.review_state}`);

    switch (row.bucket) {
      case "string":
        if (row.proposals !== null) errors.push(`${where} is a string match but carries model proposals`);
        if (row.result.length === 0) errors.push(`${where} is a string match with a NONE result`);
        if (row.review_state !== "not_required") errors.push(`${where} is a string match, accepted without review, but is ${row.review_state}`);
        break;
      case "agree_none":
        if (!row.proposals || row.proposals.jev.length !== 0 || !same(row.proposals.claude, [])) errors.push(`${where} is agree_none but a model named a genre`);
        if (row.result.length !== 0) errors.push(`${where} is agree_none and must stay unmapped, not ${show(row.result)}`);
        if (row.review_state !== "not_required") errors.push(`${where} is agree_none, recorded unmapped without review, but is ${row.review_state}`);
        break;
      case "agree_genre":
      case "disagree": {
        if (!row.proposals) {
          errors.push(`${where} is ${row.bucket} but carries no model proposals`);
          break;
        }
        const agree = same(row.proposals.jev, row.proposals.claude);
        if (row.bucket === "agree_genre" && (!agree || row.proposals.jev.length === 0)) errors.push(`${where} is agree_genre but the models do not name the same genre or style`);
        if (row.bucket === "disagree" && agree) errors.push(`${where} is disagree but the models agree`);
        if (row.review_state === "not_required") errors.push(`${where} carries a model proposal and must be reviewed`);
        if (row.review_state === "pending" && !same(row.result, defaultAnswer(row.proposals))) {
          errors.push(`${where} is pending with ${show(row.result)}, not the default ${show(defaultAnswer(row.proposals))}`);
        }
        break;
      }
      default:
        errors.push(`${where} has unknown bucket ${row.bucket}`);
    }
  }
  for (const [key, value] of Object.entries(counts)) {
    if (lookup.counts?.[key] !== value) errors.push(`counts.${key} is ${lookup.counts?.[key]}, expected ${value}`);
  }

  if (lookup.publishable === true) {
    const source = lookup.source?.musicbrainz ?? {};
    if (!source.sha256) errors.push("a publishable lookup must record the dump's sha256");
    if (source.sample) errors.push("a publishable lookup must be built from a whole dump, not a sample");
    for (const row of rows) {
      if (row.proposals !== null && row.result.length > 0 && !(row.review_state === "reviewed" && row.reviewer)) {
        errors.push(`publishable lookup carries unreviewed model-proposed genre row ${JSON.stringify(row.tag)} -> ${show(row.result)}`);
      } else if (row.review_state === "pending") {
        errors.push(`publishable lookup carries pending row ${JSON.stringify(row.tag)}`);
      }
    }
  }
  return errors;
}

// The review queue is exactly the lookup's pending rows, most-used first, with the same proposals.
export function validateReviewQueue(queue, lookup) {
  const errors = [];
  const pending = (lookup.rows ?? []).filter((row) => row.review_state === "pending");
  const expected = [...pending].sort((a, b) => b.uses - a.uses || byCodepoint(a.tag, b.tag));
  const rows = queue.rows ?? [];
  if (!same(rows.map((row) => row.tag), expected.map((row) => row.tag))) {
    errors.push(`queue rows are not the lookup's ${expected.length} pending rows, most-used first`);
    return errors;
  }
  rows.forEach((row, i) => {
    const want = expected[i];
    const where = `queue row ${JSON.stringify(row.tag)}`;
    if (row.uses !== want.uses || row.bucket !== want.bucket) errors.push(`${where} does not match the lookup's uses or bucket`);
    if (!same(row.jev, want.proposals.jev) || !same(row.claude, want.proposals.claude)) errors.push(`${where} proposals differ from the lookup`);
    if (!same(row.default, defaultAnswer(want.proposals))) errors.push(`${where} default is not Claude's answer`);
    if (!same(row.jev_top3?.[0]?.path, row.jev)) errors.push(`${where} jev_top3 does not start with Jev's answer`);
  });
  const counts = { rows: rows.length, agree_genre: rows.filter((row) => row.bucket === "agree_genre").length, disagree: rows.filter((row) => row.bucket === "disagree").length };
  for (const [key, value] of Object.entries(counts)) {
    if (queue.counts?.[key] !== value) errors.push(`queue counts.${key} is ${queue.counts?.[key]}, expected ${value}`);
  }
  if (queue.lookup?.dump !== lookup.source?.musicbrainz?.dump) errors.push("queue names a different dump than the lookup");
  return errors;
}

export function validateTagVocabulary(vocabulary) {
  const errors = [];
  const tags = vocabulary.tags ?? [];
  const order = tags.map((row) => [row.uses, row.tag]);
  const expected = [...order].sort((a, b) => b[0] - a[0] || byCodepoint(a[1], b[1]));
  if (!same(order, expected)) errors.push("tags must be sorted by uses descending, then tag");
  if (new Set(tags.map((row) => row.tag)).size !== tags.length) errors.push("tags must be unique");
  for (const row of tags) if (row.uses < vocabulary.min_uses) errors.push(`tag ${JSON.stringify(row.tag)} has ${row.uses} uses, under min_uses ${vocabulary.min_uses}`);
  if (vocabulary.counts?.tags_kept !== tags.length) errors.push(`counts.tags_kept is ${vocabulary.counts?.tags_kept}, expected ${tags.length}`);
  const uses = tags.reduce((sum, row) => sum + row.uses, 0);
  if (vocabulary.counts?.uses_kept !== uses) errors.push(`counts.uses_kept is ${vocabulary.counts?.uses_kept}, expected ${uses}`);
  if (!vocabulary.source?.sample && !vocabulary.source?.sha256) errors.push("a dump vocabulary must record the dump's sha256");
  return errors;
}
