// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import { pathInTree, treeIndex, validateReviewQueue, validateTagLookup, validateTagVocabulary } from "./mb-tag-genre.mjs";
import { ROOT } from "./tooling.mjs";

const GENERATOR = resolve(ROOT, "scripts/mb-tag-genre.py");
const SPIKE = resolve(ROOT, "taxonomy/mb-tag-genre/v1/fixtures/spike-569");
const read = (path) => JSON.parse(readFileSync(path, "utf8"));
const spikeTree = read(join(SPIKE, "discogs-genre-tree-spike.json"));
const spikeLookup = read(join(SPIKE, "mb-tag-genre.json"));
const spikeQueue = read(join(SPIKE, "review-queue.json"));
const pythonMissing = spawnSync("python3", ["--version"]).error;

function python(args, { isolated = true, env = {} } = {}) {
  return spawnSync("python3", [...(isolated ? ["-I"] : []), ...args], { encoding: "utf8", env: { ...process.env, ...env } });
}

function propose(captures, out, { vocab = join(SPIKE, "vocabulary.json"), tree = join(SPIKE, "discogs-genre-tree-spike.json"), live = false, isolated = true, env = {} } = {}) {
  const args = [GENERATOR, "propose", "--vocab", vocab, "--tree", tree, "--captures", captures, "--out-lookup", join(out, "mb-tag-genre.json"), "--out-queue", join(out, "review-queue.json")];
  if (live) args.push("--live");
  return python(args, { isolated, env });
}

function withTemp(name, body) {
  const dir = mkdtempSync(join(tmpdir(), `${name}-`));
  try {
    return body(dir);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

// --- the spike-569 regression -----------------------------------------------------------------

function loadLabels(tree) {
  const index = treeIndex(tree);
  const parents = new Map();
  for (const [genre, styles] of index) for (const style of styles) parents.set(style, [...(parents.get(style) ?? []), genre]);
  const lines = readFileSync(join(SPIKE, "labels.tsv"), "utf8").split("\n").filter((line) => line && !line.startsWith("## "));
  const header = lines[0].split("\t");
  const labels = new Map();
  for (const line of lines.slice(1)) {
    const row = Object.fromEntries(line.split("\t").map((value, i) => [header[i], value]));
    const accepted = new Set();
    for (const item of row.accepted.split(" | ").map((x) => x.trim())) {
      if (item === "NONE") accepted.add(JSON.stringify([]));
      else if (item.startsWith("G:")) accepted.add(JSON.stringify([item.slice(2)]));
      else if (item.startsWith("S:")) for (const genre of parents.get(item.slice(2)) ?? assert.fail(`unknown style ${item}`)) accepted.add(JSON.stringify([genre, item.slice(2)]));
      else if (item.startsWith("P:")) {
        const [genre, ...rest] = item.slice(2).split("/");
        const path = [genre, rest.join("/")];
        assert.ok(pathInTree(index, path), `${row.tag}: ${item} is not in the tree`);
        accepted.add(JSON.stringify(path));
      } else assert.fail(`${row.tag}: bad item ${item}`);
    }
    labels.set(row.tag, accepted);
  }
  return labels;
}

function cascadeFigures(lookup, labels, sample) {
  const byTag = new Map(sample.rows.map((row) => [row.tag, row]));
  const sizes = Object.fromEntries(sample.rows.map((row) => [row.stratum, row.stratum_size]));
  const sampled = (stratum) => sample.rows.filter((row) => row.stratum === stratum).length;
  const exact = (path, tag) => path !== null && labels.get(tag).has(JSON.stringify(path));
  const share = (rows, pick) => rows.filter((row) => exact(pick(row), row.tag)).length / rows.length;
  const estimate = (rows, strata) => strata.reduce((sum, s) => sum + (sizes[s] * rows.filter((row) => byTag.get(row.tag).stratum === s).length) / sampled(s), 0);
  const figures = {};
  for (const bucket of ["string", "agree_genre", "agree_none", "disagree"]) {
    const rows = lookup.rows.filter((row) => row.bucket === bucket);
    const entry = { n: rows.length, est_tags_ge20_uses: estimate(rows, ["head", "mid"]), est_tags_ge5_uses: estimate(rows, Object.keys(sizes)) };
    if (bucket === "string") entry.precision = share(rows, (row) => row.result);
    else {
      entry.jev_exact = share(rows, (row) => row.proposals.jev);
      entry.claude_exact = share(rows, (row) => row.proposals.claude);
    }
    if (bucket === "agree_none") entry.missed_genre = rows.filter((row) => !labels.get(row.tag).has("[]")).map((row) => row.tag).sort();
    figures[bucket] = entry;
  }
  // Auto-accepted in the spike's sense: string matches plus both agreement buckets (Jev == Claude there).
  const auto = lookup.rows.filter((row) => row.bucket !== "disagree");
  figures.auto_precision = share(auto, (row) => (row.bucket === "string" ? row.result : row.proposals.jev));
  const uses = (rows) => rows.reduce((sum, row) => sum + byTag.get(row.tag).uses, 0);
  figures.auto_use_share = uses(auto) / uses(lookup.rows);
  return figures;
}

test("the spike-569 fixture lookup, review queue and vocabulary are valid", () => {
  assert.deepEqual(validateTagLookup(spikeLookup, spikeTree), []);
  assert.deepEqual(validateReviewQueue(spikeQueue, spikeLookup), []);
  assert.deepEqual(validateTagVocabulary(read(join(SPIKE, "vocabulary.json"))), []);
  assert.equal(spikeLookup.publishable, false);
});

test("the ported cascade reproduces the spike's cascade figures from its captures", () => {
  const expected = read(join(SPIKE, "spike-summary-cascade.json")).cascade;
  const figures = cascadeFigures(spikeLookup, loadLabels(spikeTree), read(join(SPIKE, "sample.json")));
  const close = (actual, want, tolerance, label) => assert.ok(Math.abs(actual - want) <= tolerance, `${label}: ${actual} vs spike ${want}`);
  for (const bucket of ["string", "agree_genre", "agree_none", "disagree"]) {
    const got = figures[bucket];
    const want = expected[bucket];
    assert.equal(got.n, want.n, `${bucket} size`);
    close(got.est_tags_ge20_uses, want.est_tags_ge20_uses, 0.5, `${bucket} est >= 20 uses`);
    close(got.est_tags_ge5_uses, want.est_tags_ge5_uses, 0.5, `${bucket} est >= 5 uses`);
    // The cascade never asks the models about a string match, so that bucket has only its own precision.
    for (const key of bucket === "string" ? ["precision"] : ["jev_exact", "claude_exact"]) close(got[key], want[key], 0.0005, `${bucket} ${key}`);
  }
  assert.deepEqual(figures.agree_none.missed_genre, expected.agree_none.missed_genre);
  close(figures.auto_precision, expected.auto_precision, 0.0005, "auto precision");
  close(figures.auto_use_share, expected.auto_use_share, 0.0005, "auto use share");
  assert.equal(spikeQueue.rows.length, expected.agree_genre.n + expected.disagree.n);
});

// --- the generator ----------------------------------------------------------------------------

test("a replay rebuilds the committed lookup and queue byte-identically with the SDKs and the network unavailable", (t) => {
  if (pythonMissing) return t.skip("python3 is unavailable");
  withTemp("mbtag-replay", (dir) => {
    const isolated = join(dir, "isolated");
    let run = propose(join(SPIKE, "captures"), isolated);
    assert.equal(run.status, 0, run.stderr);
    assert.equal(readFileSync(join(isolated, "mb-tag-genre.json"), "utf8"), readFileSync(join(SPIKE, "mb-tag-genre.json"), "utf8"));
    assert.equal(readFileSync(join(isolated, "review-queue.json"), "utf8"), readFileSync(join(SPIKE, "review-queue.json"), "utf8"));
    assert.match(run.stderr, /"misses": 0/);

    // Outer guard, independent of the generator's own: importing either SDK, or opening any socket, fails.
    const site = join(dir, "site");
    mkdirSync(site);
    writeFileSync(join(site, "anthropic.py"), "raise SystemExit('anthropic imported during a replay')\n");
    writeFileSync(join(site, "typesafe_sdk.py"), "raise SystemExit('typesafe_sdk imported during a replay')\n");
    writeFileSync(join(site, "sitecustomize.py"), "import socket\n\ndef _refuse(self, *a, **k):\n    raise SystemExit('socket opened during a replay')\n\nsocket.socket.__init__ = _refuse\n");
    const guarded = join(dir, "guarded");
    run = propose(join(SPIKE, "captures"), guarded, { isolated: false, env: { PYTHONPATH: site } });
    assert.equal(run.status, 0, run.stderr);
    assert.equal(readFileSync(join(guarded, "mb-tag-genre.json"), "utf8"), readFileSync(join(isolated, "mb-tag-genre.json"), "utf8"));
  });
});

test("a capture miss fails the replay instead of calling out, and writes nothing", (t) => {
  if (pythonMissing) return t.skip("python3 is unavailable");
  withTemp("mbtag-miss", (dir) => {
    for (const model of ["claude-opus-5-5", "jev-1.14.0"]) {
      const captures = join(dir, `captures-${model}`);
      cpSync(join(SPIKE, "captures"), captures, { recursive: true });
      const file = join(captures, `${model}.jsonl`);
      const lines = readFileSync(file, "utf8").trimEnd().split("\n");
      writeFileSync(file, `${lines.slice(1).join("\n")}\n`);
      const out = join(dir, `out-${model}`);
      const run = propose(captures, out);
      assert.equal(run.status, 3, `${model}: ${run.stderr}`);
      assert.match(run.stderr, new RegExp(`capture miss for .*\\(${model.replaceAll(".", "\\.")}, key`));
      assert.ok(!existsSync(join(out, "mb-tag-genre.json")) && !existsSync(join(out, "review-queue.json")), "a failed replay must not write outputs");
      assert.equal(readFileSync(file, "utf8").trimEnd().split("\n").length, lines.length - 1, "a replay must not touch the captures");
    }
  });
});

test("a capture answered by another model aborts the replay", (t) => {
  if (pythonMissing) return t.skip("python3 is unavailable");
  withTemp("mbtag-pin", (dir) => {
    const captures = join(dir, "captures");
    cpSync(join(SPIKE, "captures"), captures, { recursive: true });
    const file = join(captures, "jev-1.14.0.jsonl");
    writeFileSync(file, readFileSync(file, "utf8").replace('"model": "jev-1.14.0"', '"model": "jev-1.13.0"'));
    const run = propose(captures, join(dir, "out"));
    assert.equal(run.status, 4, run.stderr);
    assert.match(run.stderr, /model pin violated.*jev-1\.13\.0/);
  });
});

// A tiny tree and vocabulary, and fake SDKs that answer from a table, exercise --live with no network.
const TINY_TREE = {
  tree_version: "1",
  license: "MIT",
  source: { name: "synthetic", url: "https://example.invalid/", license: "CC0-1.0", dump_date: "20990101", inputs: [] },
  rule: {},
  counts: {},
  genres: [
    { genre: "Electronic", records: 10, children: [{ style: "Techno", records: 6, genre_records: 6 }, { style: "House", records: 4, genre_records: 4 }] },
    { genre: "Rock", records: 10, children: [{ style: "Punk", records: 5, genre_records: 5 }, { style: "Black Metal", records: 3, genre_records: 3 }] },
  ],
};
// tag -> [Jev's answer, Claude's answer]; null for Claude is a refusal.
const ANSWERS = {
  gabber: [["Electronic", "Techno"], ["Electronic", "Techno"]],
  berlin: [[], []],
  darkwave: [["Electronic"], ["Rock", "Punk"]],
  "post-whatever": [["Rock"], null],
};
const VOCAB_TAGS = [
  { tag: "black metal", uses: 900 },
  { tag: "berlin", uses: 700 },
  { tag: "darkwave", uses: 500 },
  { tag: "gabber", uses: 300 },
  { tag: "post-whatever", uses: 40 },
  { tag: "techno", uses: 30 },
];

const FAKE_TYPESAFE = `
import json, os
ANSWERS = json.load(open(os.environ["FAKE_ANSWERS"]))
CALLS = os.environ["FAKE_CALLS"]
class RetryPolicy:
    def __init__(self, **kw): pass
class Choice:
    def __init__(self, instructions, criteria): self.instructions, self.criteria = instructions, criteria
class _O:
    def __init__(self, **kw): self.__dict__.update(kw)
class TypeSafeClient:
    def __init__(self, retry=None): pass
    def system_one(self, state, questions, model):
        open(CALLS, "a").write("jev\\n")
        tag, q = state["musicbrainz_tag"], questions["q"]
        path = ANSWERS[tag][0]
        texts = list(q.criteria.values())
        if q.instructions.startswith("\`musicbrainz_tag\` is a tag that MusicBrainz users applied to an artist, release or label. Which"):
            want = next(t for t in texts if t.startswith("Not a music genre")) if not path else path[0]
        else:
            want = path[1] if len(path) == 2 and path[1] in texts else next(t for t in texts if " in general: " in t)
        probs = {k: (0.9 if v == want else 0.1 / (len(texts) - 1)) for k, v in q.criteria.items()}
        return _O(model=os.environ.get("FAKE_JEV_MODEL", model), answers={"q": _O(probabilities=probs)}, usage=_O(input_tokens=600, output_tokens=150))
`;
const FAKE_ANTHROPIC = `
import json, os
ANSWERS = json.load(open(os.environ["FAKE_ANSWERS"]))
CALLS = os.environ["FAKE_CALLS"]
class _O:
    def __init__(self, **kw): self.__dict__.update(kw)
class _Messages:
    def create(self, model, system, messages, output_config, max_tokens):
        assert output_config["effort"] == "medium" and output_config["format"]["type"] == "json_schema"
        open(CALLS, "a").write("claude\\n")
        tag = json.loads(messages[0]["content"].split(": ", 1)[1])
        path = ANSWERS[tag][1]
        usage = _O(input_tokens=21, cache_creation_input_tokens=0, cache_read_input_tokens=400, output_tokens=9)
        reported = os.environ.get("FAKE_CLAUDE_MODEL", model)
        if path is None:
            return _O(model=reported, stop_reason="refusal", content=[], usage=usage)
        text = "NONE (not a music genre or style)" if not path else " / ".join(path) + ("" if len(path) == 2 else " (genre only)")
        lines = system[0]["text"].split("Options (id<TAB>option):\\n", 1)[1].split("\\n")
        option = next(int(line.split("\\t")[0]) for line in lines if line.split("\\t")[1] == text)
        return _O(model=reported, stop_reason="end_turn", content=[_O(type="text", text=json.dumps({"option": option}))], usage=usage)
class Anthropic:
    def __init__(self, max_retries=2): self.messages = _Messages()
`;

function tinySetup(dir) {
  writeFileSync(join(dir, "tree.json"), JSON.stringify(TINY_TREE));
  const vocab = { vocabulary_version: "1", license: "MIT", source: { dump: "20990101-000000", sample: "synthetic" }, rule: "", min_uses: 20, counts: {}, tags: VOCAB_TAGS };
  writeFileSync(join(dir, "vocab.json"), JSON.stringify(vocab));
  writeFileSync(join(dir, "answers.json"), JSON.stringify(ANSWERS));
  const site = join(dir, "site");
  mkdirSync(site);
  writeFileSync(join(site, "typesafe_sdk.py"), FAKE_TYPESAFE);
  writeFileSync(join(site, "anthropic.py"), FAKE_ANTHROPIC);
  return { site, env: { PYTHONPATH: site, FAKE_ANSWERS: join(dir, "answers.json"), FAKE_CALLS: join(dir, "calls.log") } };
}

test("--live asks the pinned models, captures every answer, and buckets the rows by the ADR 0020 cascade", (t) => {
  if (pythonMissing) return t.skip("python3 is unavailable");
  withTemp("mbtag-live", (dir) => {
    const { env } = tinySetup(dir);
    const opts = { vocab: join(dir, "vocab.json"), tree: join(dir, "tree.json") };
    const captures = join(dir, "captures");
    let run = propose(captures, join(dir, "live"), { ...opts, live: true, isolated: false, env });
    assert.equal(run.status, 0, run.stderr);
    const calls = readFileSync(env.FAKE_CALLS, "utf8").trim().split("\n");
    assert.equal(calls.filter((c) => c === "claude").length, 4, "one Claude request per non-string tag");
    assert.ok(calls.filter((c) => c === "jev").length >= 4);
    const lookup = read(join(dir, "live", "mb-tag-genre.json"));
    const rows = Object.fromEntries(lookup.rows.map((row) => [row.tag, row]));
    // String matches are accepted without review and never reach a model.
    assert.deepEqual(rows["black metal"], { tag: "black metal", uses: 900, bucket: "string", result: ["Rock", "Black Metal"], proposals: null, review_state: "not_required", reviewer: null });
    assert.deepEqual(rows.techno.result, ["Electronic", "Techno"]);
    // Both NONE: recorded unmapped with both proposals, not reviewed.
    assert.deepEqual(rows.berlin, { tag: "berlin", uses: 700, bucket: "agree_none", result: [], proposals: { jev: [], claude: [] }, review_state: "not_required", reviewer: null });
    // Agreement and disagreement: pending, Claude's answer as the default (Jev's when Claude refused).
    assert.equal(rows.gabber.bucket, "agree_genre");
    assert.equal(rows.gabber.review_state, "pending");
    assert.deepEqual(rows.darkwave.result, ["Rock", "Punk"]);
    assert.equal(rows.darkwave.bucket, "disagree");
    assert.deepEqual(rows["post-whatever"].proposals, { jev: ["Rock"], claude: null });
    assert.deepEqual(rows["post-whatever"].result, ["Rock"]);
    assert.deepEqual(validateTagLookup(lookup, TINY_TREE), []);
    const queue = read(join(dir, "live", "review-queue.json"));
    assert.deepEqual(queue.rows.map((row) => [row.tag, row.default]), [["darkwave", ["Rock", "Punk"]], ["gabber", ["Electronic", "Techno"]], ["post-whatever", ["Rock"]]]);
    assert.deepEqual(validateReviewQueue(queue, lookup), []);
    for (const model of ["jev-1.14.0", "claude-opus-5-5"]) assert.ok(existsSync(join(captures, `${model}.jsonl`)), `${model} captures written`);

    // The same captures replay with no SDK and no network, byte for byte.
    run = propose(captures, join(dir, "replay"), opts);
    assert.equal(run.status, 0, run.stderr);
    assert.equal(readFileSync(join(dir, "replay", "mb-tag-genre.json"), "utf8"), readFileSync(join(dir, "live", "mb-tag-genre.json"), "utf8"));
    assert.equal(readFileSync(join(dir, "replay", "review-queue.json"), "utf8"), readFileSync(join(dir, "live", "review-queue.json"), "utf8"));

    // A reviewed row survives a rerun and leaves the queue.
    const reviewed = structuredClone(lookup);
    const row = reviewed.rows.find((r) => r.tag === "darkwave");
    Object.assign(row, { result: ["Electronic"], review_state: "reviewed", reviewer: "Test Reviewer" });
    reviewed.counts.pending -= 1;
    reviewed.counts.reviewed += 1;
    writeFileSync(join(dir, "replay", "mb-tag-genre.json"), JSON.stringify(reviewed));
    run = propose(captures, join(dir, "replay"), opts);
    assert.equal(run.status, 0, run.stderr);
    const rerun = read(join(dir, "replay", "mb-tag-genre.json"));
    assert.deepEqual(rerun.rows.find((r) => r.tag === "darkwave"), row);
    assert.deepEqual(read(join(dir, "replay", "review-queue.json")).rows.map((r) => r.tag), ["gabber", "post-whatever"]);
    assert.deepEqual(validateTagLookup(rerun, TINY_TREE), []);
  });
});

test("--live aborts when a response reports a model other than the pinned one", (t) => {
  if (pythonMissing) return t.skip("python3 is unavailable");
  withTemp("mbtag-live-pin", (dir) => {
    const { env } = tinySetup(dir);
    const opts = { vocab: join(dir, "vocab.json"), tree: join(dir, "tree.json"), live: true, isolated: false };
    for (const [variable, model] of [["FAKE_CLAUDE_MODEL", "claude-opus-5"], ["FAKE_JEV_MODEL", "jev-1.13.0"]]) {
      const captures = join(dir, `captures-${variable}`);
      const run = propose(captures, join(dir, `out-${variable}`), { ...opts, env: { ...env, [variable]: model } });
      assert.equal(run.status, 4, run.stderr);
      assert.match(run.stderr, new RegExp(`answered by ${model.replaceAll(".", "\\.")}`));
      assert.ok(!existsSync(join(dir, `out-${variable}`, "mb-tag-genre.json")));
      for (const file of ["jev-1.14.0.jsonl", "claude-opus-5-5.jsonl"]) {
        const path = join(captures, file);
        if (existsSync(path)) assert.doesNotMatch(readFileSync(path, "utf8"), new RegExp(model.replaceAll(".", "\\.")));
      }
    }
  });
});

// --- the vocabulary step ----------------------------------------------------------------------

const MAKE_DUMP = `
import io, sys, tarfile
out = sys.argv[1]
members = [
    ("TIMESTAMP", "2099-01-01 00:00:00.000000+00\\n"),
    ("mbdump/artist_tag", "1\\t1\\t3\\t2099-01-01\\n2\\t1\\t1\\t2099-01-01\\n3\\t2\\t1\\t2099-01-01\\n4\\t3\\t0\\t2099-01-01\\n5\\t4\\t-1\\t2099-01-01\\n"),
    ("mbdump/annotation", "unrelated\\n"),
    ("mbdump/tag", "1\\trock\\t9\\n2\\tback\\\\\\\\slash\\t3\\n3\\tzero votes\\t1\\n4\\tdownvoted\\t1\\n5\\tunused\\t0\\n"),
    ("mbdump/label_tag", "1\\t2\\t2\\t2099-01-01\\n"),
    ("mbdump/release_tag", "1\\t1\\t1\\t2099-01-01\\n7\\t3\\t0\\t2099-01-01\\n"),
    ("mbdump/release_group_tag", "1\\t1\\t5\\t2099-01-01\\n"),
]
with tarfile.open(out, "w:bz2") as tar:
    for name, text in members:
        data = text.encode()
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
`;

test("the vocabulary step streams a dump, checks its SHA256SUMS, and keeps tags with min-uses or more", (t) => {
  if (pythonMissing) return t.skip("python3 is unavailable");
  withTemp("mbtag-vocab", (dir) => {
    const dump = join(dir, "mbdump-derived.tar.bz2");
    assert.equal(python(["-c", MAKE_DUMP, dump]).status, 0);
    const sha = python(["-c", "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())", dump]).stdout.trim();
    writeFileSync(join(dir, "SHA256SUMS"), `${"0".repeat(64)} *mbdump.tar.bz2\n${sha} *mbdump-derived.tar.bz2\n`);
    const out = join(dir, "vocab.json");
    const args = [GENERATOR, "vocab", "--dump", dump, "--dump-name", "20990101-000000", "--sha256sums", join(dir, "SHA256SUMS"), "--min-uses", "2", "--out", out];
    let run = python(args);
    assert.equal(run.status, 0, run.stderr);
    const vocab = read(out);
    // rock: artist x2 + release + release_group = 4 uses; back\\slash: artist + label = 2; zero and negative votes are not uses.
    assert.deepEqual(vocab.tags, [{ tag: "rock", uses: 4 }, { tag: "back\\slash", uses: 2 }]);
    assert.equal(vocab.source.sha256, sha);
    assert.equal(vocab.source.timestamp, "2099-01-01 00:00:00.000000+00");
    assert.deepEqual(vocab.counts, {
      distinct_tags_in_scope: 2,
      uses_in_scope: 6,
      tags_kept: 2,
      uses_kept: 6,
      per_scope: { artist: { uses: 3, distinct_tags: 2 }, label: { uses: 1, distinct_tags: 1 }, release: { uses: 1, distinct_tags: 1 }, release_group: { uses: 1, distinct_tags: 1 } },
    });
    assert.deepEqual(validateTagVocabulary(vocab), []);
    const schema = spawnSync("jsonschema", ["validate", resolve(ROOT, "taxonomy/mb-tag-genre/v1/mb-tag-vocabulary.schema.json"), out, "--format-assertion"], { encoding: "utf8" });
    if (!schema.error) assert.equal(schema.status, 0, schema.stdout + schema.stderr);

    rmSync(out);
    writeFileSync(join(dir, "SHA256SUMS"), `${"f".repeat(64)} *mbdump-derived.tar.bz2\n`);
    run = python(args);
    assert.equal(run.status, 5, run.stderr);
    assert.match(run.stderr, /checksum mismatch/);
    assert.ok(!existsSync(out), "a dump that fails its checksum writes no vocabulary");
  });
});

// --- the validator ----------------------------------------------------------------------------

function publishable(lookup) {
  const copy = structuredClone(lookup);
  copy.publishable = true;
  copy.source.musicbrainz.sha256 = "a".repeat(64);
  delete copy.source.musicbrainz.sample;
  return copy;
}

test("the validator rejects an unreviewed model-proposed genre row in a publishable file", () => {
  const unreviewed = publishable(spikeLookup);
  const errors = validateTagLookup(unreviewed, spikeTree);
  assert.match(errors.join("\n"), /publishable lookup carries unreviewed model-proposed genre row "#dance" -> Electronic/);
  assert.equal(errors.filter((e) => e.startsWith("publishable lookup carries")).length, spikeLookup.counts.pending);

  const reviewed = publishable(spikeLookup);
  for (const row of reviewed.rows) if (row.review_state === "pending") Object.assign(row, { review_state: "reviewed", reviewer: "Test Reviewer" });
  reviewed.counts.reviewed = reviewed.counts.pending;
  reviewed.counts.pending = 0;
  assert.deepEqual(validateTagLookup(reviewed, spikeTree), []);

  const sampleOnly = structuredClone(reviewed);
  sampleOnly.source.musicbrainz.sample = "a sample";
  sampleOnly.source.musicbrainz.sha256 = null;
  assert.match(validateTagLookup(sampleOnly, spikeTree).join("\n"), /must record the dump's sha256[\s\S]*not a sample/);
});

test("the validator enforces the cascade's bucket rules and the tree", () => {
  const mutate = (fn) => {
    const copy = structuredClone(spikeLookup);
    fn(copy.rows);
    return validateTagLookup(copy, spikeTree).join("\n");
  };
  const first = (rows, bucket) => rows.find((row) => row.bucket === bucket);
  assert.match(mutate((rows) => Object.assign(first(rows, "agree_none"), { result: ["Rock"] })), /agree_none and must stay unmapped/);
  assert.match(mutate((rows) => Object.assign(first(rows, "string"), { review_state: "pending" })), /string match, accepted without review/);
  assert.match(mutate((rows) => Object.assign(first(rows, "disagree"), { review_state: "not_required" })), /must be reviewed/);
  assert.match(mutate((rows) => Object.assign(first(rows, "disagree"), { review_state: "reviewed" })), /reviewed but names no reviewer/);
  assert.match(mutate((rows) => Object.assign(first(rows, "agree_genre"), { result: ["Rock", "Not A Style"] })), /not in the tree/);
  assert.match(mutate((rows) => rows.reverse()), /sorted by tag/);
  const queue = structuredClone(spikeQueue);
  queue.rows.pop();
  assert.match(validateReviewQueue(queue, spikeLookup).join("\n"), /not the lookup's 77 pending rows/);
});
