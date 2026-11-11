// SPDX-License-Identifier: MIT
// Review page logic for mb-tag-genre/v1 (ADR 0020), with no DOM access so scripts/mb-tag-review.test.mjs can
// run it. It makes no network calls. Loaded as a classic script: it defines window.MBReview.
(function (root) {
  "use strict";

  var EXPORT_VERSION = "1";
  var ACTIONS = ["accept_default", "accept_other", "none", "pick", "skip"];

  function pathText(path) {
    if (path === null || path === undefined) return "no answer";
    if (path.length === 0) return "NONE";
    return path.join(" › ");
  }

  function samePath(a, b) {
    return JSON.stringify(a) === JSON.stringify(b);
  }

  // The proposal that is not the default (Claude is the default, Jev's when Claude gave no answer).
  function otherPath(row) {
    if (row.c === null) return null;
    return samePath(row.c, row.d) ? row.j : row.c;
  }

  function resolve(row, action, picked) {
    if (action === "accept_default") return row.d;
    if (action === "accept_other") return otherPath(row);
    if (action === "none") return [];
    if (action === "pick") return picked;
    return null;
  }

  // Every path a reviewer may pick: NONE, each genre alone, and each genre with each of its styles.
  function buildOptions(tree) {
    var options = [{ path: [], label: "NONE", hay: "none unmapped" }];
    tree.forEach(function (entry) {
      options.push({ path: [entry[0]], label: entry[0], hay: entry[0].toLowerCase() });
      entry[1].forEach(function (style) {
        options.push({ path: [entry[0], style], label: entry[0] + " › " + style, hay: (style + " " + entry[0]).toLowerCase() });
      });
    });
    return options;
  }

  // Each whitespace-separated token must match in order as a subsequence. Substrings, word starts and
  // short names score higher. Returns -1 for no match.
  function fuzzyScore(query, hay) {
    var tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
    if (tokens.length === 0) return 0;
    var total = 0;
    for (var t = 0; t < tokens.length; t += 1) {
      var token = tokens[t];
      var at = hay.indexOf(token);
      if (at >= 0) {
        total += 100 + (at === 0 || hay.charAt(at - 1) === " " ? 50 : 0) - at;
        continue;
      }
      var pos = 0;
      var run = 0;
      var best = 0;
      for (var i = 0; i < token.length; i += 1) {
        var found = hay.indexOf(token.charAt(i), pos);
        if (found < 0) return -1;
        run = found === pos && i > 0 ? run + 1 : 0;
        best += 1 + run * 2 - Math.min(found - pos, 5) * 0.1;
        pos = found + 1;
      }
      total += best;
    }
    return total - hay.length * 0.05;
  }

  function search(options, query, limit) {
    var scored = [];
    options.forEach(function (option, order) {
      var score = fuzzyScore(query, option.hay);
      if (score >= 0) scored.push({ option: option, score: score, order: order });
    });
    scored.sort(function (a, b) {
      return b.score - a.score || a.order - b.order;
    });
    return scored.slice(0, limit).map(function (item) {
      return item.option;
    });
  }

  function newState(data) {
    return { lookupSha: data.lookup.sha256, reviewer: "", decisions: {}, undo: [], redo: [], pos: 0, exportedAt: 0 };
  }

  // The first row after `from` (wrapping) with no decision, else the first skipped one, else -1.
  function nextOpen(data, state, from) {
    var n = data.rows.length;
    for (var pass = 0; pass < 2; pass += 1) {
      for (var step = 1; step <= n; step += 1) {
        var i = (from + step) % n;
        var entry = state.decisions[data.rows[i].t];
        if (pass === 0 ? entry === undefined : entry !== undefined && entry.action === "skip") return i;
      }
    }
    return -1;
  }

  // Record an action for the row at `pos`. Returns the new state's position (the next open row).
  function apply(data, state, action, picked, now) {
    var row = data.rows[state.pos];
    if (!row || ACTIONS.indexOf(action) < 0) return false;
    var result = resolve(row, action, picked);
    if (action !== "skip" && result === null) return false;
    state.undo.push({ tag: row.t, prev: state.decisions[row.t], pos: state.pos });
    state.redo = [];
    state.decisions[row.t] = { action: action, result: result, at: now, reviewer: state.reviewer };
    var next = nextOpen(data, state, state.pos);
    if (next >= 0) state.pos = next;
    return true;
  }

  function undo(data, state) {
    var last = state.undo.pop();
    if (!last) return false;
    state.redo.push({ tag: last.tag, prev: state.decisions[last.tag], pos: last.pos });
    if (last.prev === undefined) delete state.decisions[last.tag];
    else state.decisions[last.tag] = last.prev;
    state.pos = last.pos;
    return true;
  }

  function redo(data, state) {
    var last = state.redo.pop();
    if (!last) return false;
    state.undo.push({ tag: last.tag, prev: state.decisions[last.tag], pos: last.pos });
    if (last.prev === undefined) delete state.decisions[last.tag];
    else state.decisions[last.tag] = last.prev;
    state.pos = last.pos;
    var next = nextOpen(data, state, state.pos);
    if (next >= 0 && state.decisions[data.rows[last.pos].t] !== undefined) state.pos = next;
    return true;
  }

  function counts(data, state) {
    var out = { total: data.rows.length, decided: 0, accept_default: 0, accept_other: 0, none: 0, pick: 0, skip: 0 };
    Object.keys(state.decisions).forEach(function (tag) {
      var action = state.decisions[tag].action;
      out[action] += 1;
      if (action !== "skip") out.decided += 1;
    });
    out.open = out.total - out.decided;
    return out;
  }

  // The export file the merge script reads. Skips are not decisions and are left out. Rows are sorted by tag
  // so the same decisions always make the same file.
  function buildExport(data, state, now) {
    var rows = [];
    Object.keys(state.decisions).forEach(function (tag) {
      var entry = state.decisions[tag];
      if (entry.action === "skip") return;
      rows.push({ tag: tag, decision: entry.action, result: entry.result, reviewer: entry.reviewer, at: entry.at });
    });
    rows.sort(function (a, b) {
      return a.tag < b.tag ? -1 : a.tag > b.tag ? 1 : 0;
    });
    return {
      export_version: EXPORT_VERSION,
      queue_version: data.queue_version,
      lookup: { dump: data.lookup.dump, sha256: data.lookup.sha256 },
      exported_at: now,
      rows: rows,
    };
  }

  // Fold a progress file into the state. A file made against another lookup is refused. For a tag decided in
  // both, the later decision wins. Returns { error } or { imported, skipped }.
  function importProgress(data, state, file) {
    if (!file || file.export_version !== EXPORT_VERSION || !Array.isArray(file.rows)) return { error: "This is not a review export file." };
    if (!file.lookup || file.lookup.sha256 !== data.lookup.sha256) {
      return { error: "This file was made against a different lookup (" + String(file.lookup && file.lookup.sha256).slice(0, 12) + "), this page is built for " + data.lookup.sha256.slice(0, 12) + "." };
    }
    var known = {};
    data.rows.forEach(function (row) {
      known[row.t] = row;
    });
    var imported = 0;
    var skipped = 0;
    file.rows.forEach(function (entry) {
      var row = known[entry.tag];
      if (!row || ACTIONS.indexOf(entry.decision) < 0 || entry.decision === "skip" || !Array.isArray(entry.result)) {
        skipped += 1;
        return;
      }
      var have = state.decisions[entry.tag];
      if (have && have.action !== "skip" && have.at >= entry.at) return;
      state.decisions[entry.tag] = { action: entry.decision, result: entry.result, at: entry.at, reviewer: entry.reviewer || state.reviewer };
      imported += 1;
    });
    if (imported > 0) {
      state.undo = [];
      state.redo = [];
      var first = nextOpen(data, state, -1);
      if (first >= 0) state.pos = first;
    }
    return { imported: imported, skipped: skipped };
  }

  root.MBReview = {
    EXPORT_VERSION: EXPORT_VERSION,
    pathText: pathText,
    samePath: samePath,
    otherPath: otherPath,
    resolve: resolve,
    buildOptions: buildOptions,
    fuzzyScore: fuzzyScore,
    search: search,
    newState: newState,
    nextOpen: nextOpen,
    apply: apply,
    undo: undo,
    redo: redo,
    counts: counts,
    buildExport: buildExport,
    importProgress: importProgress,
  };
})(typeof window !== "undefined" ? window : globalThis);
