#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the mb-tag-genre/v1 proposals: MusicBrainz tags onto the Discogs genre/style tree (ADR 0020).

Offline tooling. No service imports this file. It has three subcommands:

``vocab``
    Stream one ``mbdump-derived.tar.bz2`` (a path or a pipe), check its SHA-256 against the export's
    ``SHA256SUMS``, and write the tag vocabulary with ``--min-uses`` or more uses. A *use* is one
    (entity, tag) row with a positive vote count in ``artist_tag``, ``label_tag``, ``release_tag`` or
    ``release_group_tag``. Only per-tag aggregates are kept; the dump is never written to disk.

``propose``
    Run the ADR 0020 cascade over the vocabulary and write the lookup and the review queue:

    1. Normalized string match against the tree's genre and style names: accepted, no review.
    2. Otherwise Jev beam K=3 (``jev-1.14.0``) and flat Claude (``claude-opus-5-5``, effort medium).
    3. Both NONE: recorded unmapped, not reviewed.
    4. Same genre or style, or a disagreement: pending review, with Claude's answer as the default.

    Every model response is a capture keyed on (model, tag, options digest). By default the run
    replays captures only, blocks the network, and fails on the first capture miss. ``--live`` is
    the only way to make a paid call, and the operator runs it from their own terminal.

``estimate``
    Count the string matches, model tags and capture misses for a vocabulary, and estimate the
    requests, tokens and dollars a ``--live`` run would spend. Makes no calls.

The prompts, option order, cache keys and beam scoring are ported unchanged from the spike harness
in musicbrainz-graph-enricher (spikes/tag-mapping at ee3efa8a764d180b73ea2dec85fa3d4af08d72d1), so
the spike's captures replay here. Python standard library only, except the two SDKs that ``--live``
imports (``typesafe-sdk`` and ``anthropic``).
"""

import argparse
import bz2
import hashlib
import json
import math
import os
import re
import socket
import sys
import tarfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

JEV_MODEL = "jev-1.14.0"
CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_EFFORT = "medium"
BEAM = 3
NONE_LABEL = "__NONE__"
GENRE_ONLY = "__GENRE_ONLY__"
SCOPES = ("artist", "label", "release", "release_group")
DUMP_FILE = "mbdump-derived.tar.bz2"
EXIT_CAPTURE_MISS = 3
EXIT_MODEL_MISMATCH = 4
EXIT_CHECKSUM = 5

# Prompts, verbatim from the spike (jev_beam.py, flat_claude.py). Changing a word changes every
# capture key, so it is a new capture set and must be measured again.
ROOT_INSTRUCTIONS = (
    "`musicbrainz_tag` is a tag that MusicBrainz users applied to an artist, release or label. "
    "Which Discogs music genre does the tag name or belong to? Choose the not-a-genre option when the "
    "tag is not a music genre or style."
)
NONE_TEXT = (
    "Not a music genre or style: a place, nationality, language, year or decade, person or band name, "
    "record label, instrument, voice type, mood, opinion, release format, or personal note"
)
CLAUDE_SCHEMA = {
    "type": "object",
    "properties": {"option": {"type": "integer"}},
    "required": ["option"],
    "additionalProperties": False,
}

# Cost model for ``estimate``. Means measured by the spike on its 200-tag sample (summary.json at
# ee3efa8a); list prices read 2026-11-01 (Jev: docs.typesafe.ai/models, input only, output free;
# Claude Opus 5.5: $4 input, $5 5-minute cache write, $0.20 cache read, $20 output per MTok).
JEV_USD_PER_MTOK_IN = 0.042
JEV_MEAN_REQUESTS_PER_TAG = 3.29
JEV_MEAN_INPUT_TOKENS_PER_TAG = 5022
OPUS_IN, OPUS_CACHE_WRITE, OPUS_CACHE_READ, OPUS_OUT = 4.00, 5.00, 0.20, 20.00
CLAUDE_SPIKE_SYSTEM_TOKENS = 18901
CLAUDE_SPIKE_SYSTEM_CHARS = 35246  # len(system_prompt) for the spike's masters-only tree (1,292 options)
CLAUDE_MEAN_INPUT_TOKENS = 21
CLAUDE_MEAN_OUTPUT_TOKENS = 53
SECONDS_PER_TAG_JEV = 0.229  # spike: 5.81 s wall for 200 tags at 8 workers, scaled to one worker
SECONDS_PER_TAG_CLAUDE = 1.95  # spike: p50 1.786 s, mean about 1.95 s per request


class CaptureMiss(Exception):
    pass


class ModelMismatch(Exception):
    pass


# --- shared -----------------------------------------------------------------------------------


def norm(text):
    text = text.lower().replace("&", " and ").replace("'n'", " and ").replace(" n ", " and ")
    return re.sub(r"[^0-9a-zÀ-￿]+", "", text)


def gmean(probs):
    return math.exp(sum(math.log(max(p, 1e-9)) for p in probs) / len(probs)) if probs else 1.0


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_text_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def render(document, list_key):
    """Pretty-print the header keys and put each item of ``document[list_key]`` on its own line."""
    parts = []
    for key in sorted(document):
        if key != list_key:
            value = json.dumps(document[key], indent=1, ensure_ascii=False, sort_keys=True).replace("\n", "\n ")
            parts.append(f" {json.dumps(key)}: {value}")
    items = ",\n".join("  " + json.dumps(item, ensure_ascii=False) for item in document[list_key])
    parts.append(f" {json.dumps(list_key)}: [\n{items}\n ]" if items else f" {json.dumps(list_key)}: []")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def block_network():
    """Replay mode: any socket connection or name lookup is a bug, so make it fail loudly."""

    def refuse(*_args, **_kwargs):
        raise RuntimeError("network access attempted in replay mode (use --live for paid calls)")

    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.create_connection = refuse
    socket.getaddrinfo = refuse


# --- tree --------------------------------------------------------------------------------------


class Tree:
    """The Discogs genre tree in file order. Option order is part of every capture key."""

    def __init__(self, path):
        self.path = Path(path)
        doc = load_json(path)
        self.doc = doc
        self.genres = [entry["genre"] for entry in doc["genres"]]
        self.styles = {entry["genre"]: [c["style"] for c in entry["children"]] for entry in doc["genres"]}
        self.weight = {(entry["genre"], c["style"]): c["genre_records"] for entry in doc["genres"] for c in entry["children"]}

    def paths(self):
        """Flat option list for Claude: NONE, then each genre followed by its styles."""
        out = [()]
        for genre in self.genres:
            out.append((genre,))
            out.extend((genre, style) for style in self.styles[genre])
        return out

    def contains(self, path):
        if len(path) == 0:
            return True
        if len(path) == 1:
            return path[0] in self.styles
        return len(path) == 2 and path[1] in self.styles.get(path[0], [])

    def string_table(self):
        """Normalized name -> path. A genre name wins over a style; a style under several genres goes
        to the genre with the most records carrying the pair (first genre in file order on a tie)."""
        table = {}
        for genre in self.genres:
            for style in self.styles[genre]:
                key = norm(style)
                current = table.get(key)
                if current is None or self.weight[(genre, style)] > self.weight.get(current, 0):
                    table[key] = (genre, style)
        for genre in self.genres:
            table[norm(genre)] = (genre,)
        return table


# --- captures ----------------------------------------------------------------------------------


class Captures:
    """One JSONL file per model, one record per line, sorted by id (the sha256 cache key). The field is
    not called `key`, so secret scanners do not read a 64-hex cache key as an API key."""

    def __init__(self, directory, model, live):
        self.path = Path(directory) / f"{model}.jsonl"
        self.model = model
        self.live = live
        self.lock = threading.Lock()
        self.records = {}
        self.new = 0
        self.stats = {"hits": 0, "misses": 0}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    self.records[record["id"]] = record

    def get(self, key, what):
        with self.lock:
            record = self.records.get(key)
            if record is not None:
                self.stats["hits"] += 1
                if record.get("model") != self.model:
                    raise ModelMismatch(f"capture {key[:12]} for {what} was answered by {record.get('model')!r}, not {self.model}")
                return record
            self.stats["misses"] += 1
        if not self.live:
            raise CaptureMiss(f"capture miss for {what} ({self.model}, key {key[:12]}); a replay never calls out, rerun with --live to pay for it")
        return None

    def put(self, key, record):
        with self.lock:
            self.records[key] = {"id": key, **record}
            self.new += 1
            due = self.new % 100 == 0
        if due:
            self.save()

    def save(self):
        with self.lock:
            lines = [json.dumps(self.records[k], ensure_ascii=False, sort_keys=True) for k in sorted(self.records)]
        if lines or self.path.exists():
            write_text_atomic(self.path, "\n".join(lines) + ("\n" if lines else ""))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Jev beam K=3 ------------------------------------------------------------------------------


def genre_instructions(genre):
    return (
        f"`musicbrainz_tag` is a tag that MusicBrainz users applied to an artist, release or label, and it "
        f"belongs to the Discogs genre {genre}. Which {genre} style does the tag name? Choose the genre-only "
        f"option when the tag names {genre} itself or no listed style fits."
    )


def genre_only_text(genre):
    return f"{genre} in general: the tag names the genre itself, or none of the listed styles fits"


class Jev:
    def __init__(self, captures, live):
        self.captures = captures
        self.client = None
        if live:
            from typesafe_sdk import RetryPolicy, TypeSafeClient  # noqa: PLC0415 - only with --live

            self.client = TypeSafeClient(retry=RetryPolicy(max_retries=5, backoff_initial=1.0, backoff_max=20.0))

    def choose(self, tag, node, instructions, labels, descriptions):
        state = {"musicbrainz_tag": tag}
        criteria = {f"c{i}": descriptions.get(label, label) for i, label in enumerate(labels)}
        key = hashlib.sha256(json.dumps([JEV_MODEL, state, instructions, criteria], ensure_ascii=False).encode()).hexdigest()
        record = self.captures.get(key, f"jev {tag!r} at {node}")
        if record is None:
            record = self.call(tag, node, state, instructions, criteria, labels)
            self.captures.put(key, record)
        if record["n"] != len(labels):
            raise ValueError(f"capture {key[:12]} has {record['n']} options, the question has {len(labels)}")
        dense = [0.0] * len(labels)
        for index, p in record["p"].items():
            dense[int(index)] = p
        return dict(zip(labels, dense))

    def call(self, tag, node, state, instructions, criteria, labels):
        from typesafe_sdk import Choice  # noqa: PLC0415 - only with --live

        start = time.perf_counter()
        response = self.client.system_one(state=state, questions={"q": Choice(instructions=instructions, criteria=criteria)}, model=JEV_MODEL)
        latency = time.perf_counter() - start
        if response.model != JEV_MODEL:
            raise ModelMismatch(f"asked for {JEV_MODEL}, answered by {response.model}")
        probs = response.answers["q"].probabilities
        sparse = {}
        for i in range(len(labels)):
            p = round(float(probs[f"c{i}"]), 6)
            if p:
                sparse[str(i)] = p
        return {
            "tag": tag,
            "node": node,
            "model": response.model,
            "n": len(labels),
            "p": sparse,
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "latency_s": round(latency, 4),
            "at": now(),
        }


def jev_root(jev, tree, tag):
    return jev.choose(tag, "ROOT", ROOT_INSTRUCTIONS, [*tree.genres, NONE_LABEL], {NONE_LABEL: NONE_TEXT})


def jev_styles(jev, tree, tag, genre):
    return jev.choose(tag, genre, genre_instructions(genre), [*tree.styles[genre], GENRE_ONLY], {GENRE_ONLY: genre_only_text(genre)})


def to_path(labels):
    return [x for x in labels if x not in (NONE_LABEL, GENRE_ONLY)]


def jev_beam(jev, tree, tag):
    root = jev_root(jev, tree, tag)
    first = sorted(root.items(), key=lambda kv: (-kv[1], kv[0]))[:BEAM]
    cands = [{"labels": [g], "probs": [p]} for g, p in first if g == NONE_LABEL]
    for g, p in first:
        if g != NONE_LABEL:
            dist = jev_styles(jev, tree, tag, g)
            cands.extend({"labels": [g, s], "probs": [p, q]} for s, q in dist.items())
    for c in cands:
        c["score"] = gmean(c["probs"])
    cands.sort(key=lambda c: (-c["score"], c["labels"]))
    top = cands[:BEAM]
    second = cands[1]["score"] if len(cands) > 1 else 1e-9
    return {
        "path": to_path(top[0]["labels"]),
        "separation": round(top[0]["score"] / max(second, 1e-9), 6),
        "top3": [{"path": to_path(c["labels"]), "score": round(c["score"], 6)} for c in top],
    }


# --- flat Claude -------------------------------------------------------------------------------


def system_prompt(options):
    lines = [
        f"{i}\t{'NONE (not a music genre or style)' if not p else ' / '.join(p) + ('' if len(p) == 2 else ' (genre only)')}"
        for i, p in enumerate(options)
    ]
    return (
        "You map MusicBrainz user tags onto the Discogs genre/style taxonomy.\n"
        "A tag was applied by MusicBrainz users to an artist, release or label. Pick exactly one option id:\n"
        "- a 'Genre / Style' option when the tag names that style (or a close equivalent of it);\n"
        "- a 'Genre (genre only)' option when the tag names the genre itself, or a genre-like sound in that genre "
        "that none of its styles matches;\n"
        "- option 0 (NONE) when the tag is not a music genre or style: a place, nationality, language, year or "
        "decade, person or band name, record label, instrument, voice type, mood, opinion, release format, or "
        "personal note.\n"
        "Many styles appear under more than one genre; pick the genre that fits the tag best.\n\n"
        "Options (id<TAB>option):\n" + "\n".join(lines)
    )


class Claude:
    def __init__(self, captures, tree, live):
        self.captures = captures
        self.options = tree.paths()
        self.system = system_prompt(self.options)
        self.list_sha = hashlib.sha256(self.system.encode()).hexdigest()[:16]
        self.client = None
        if live:
            import anthropic  # noqa: PLC0415 - only with --live

            self.client = anthropic.Anthropic(max_retries=5)

    def key(self, tag):
        return hashlib.sha256(json.dumps([CLAUDE_MODEL, CLAUDE_EFFORT, self.list_sha, tag], ensure_ascii=False).encode()).hexdigest()

    def ask(self, tag):
        key = self.key(tag)
        record = self.captures.get(key, f"claude {tag!r}")
        if record is None:
            record = self.call(tag)
            self.captures.put(key, record)
        if record.get("effort") != CLAUDE_EFFORT:
            raise ModelMismatch(f"capture {key[:12]} was run at effort {record.get('effort')!r}, not {CLAUDE_EFFORT}")
        option = record.get("option")
        if option is None or not 0 <= option < len(self.options):
            return None  # refusal or invalid answer: no proposal
        path = list(self.options[option])
        if record.get("path") != path:
            raise ValueError(f"capture {key[:12]} for {tag!r} names option {option} as {record.get('path')}, the list says {path}")
        return path

    def call(self, tag):
        start = time.perf_counter()
        # No server-side fallbacks: the model is pinned, and an answer from another model aborts.
        response = self.client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8000,
            system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": CLAUDE_EFFORT, "format": {"type": "json_schema", "schema": CLAUDE_SCHEMA}},
            messages=[{"role": "user", "content": f"MusicBrainz tag: {json.dumps(tag, ensure_ascii=False)}"}],
        )
        latency = time.perf_counter() - start
        if response.model != CLAUDE_MODEL:
            raise ModelMismatch(f"asked for {CLAUDE_MODEL}, answered by {response.model}")
        option = None
        if response.stop_reason != "refusal":
            text = next((b.text for b in response.content if b.type == "text"), "")
            try:
                option = int(json.loads(text)["option"])
            except (ValueError, KeyError, TypeError):
                option = None
        usage = response.usage
        return {
            "tag": tag,
            "model": response.model,
            "effort": CLAUDE_EFFORT,
            "list_sha": self.list_sha,
            "stop_reason": response.stop_reason,
            "option": option,
            "path": list(self.options[option]) if option is not None and 0 <= option < len(self.options) else None,
            "input_tokens": usage.input_tokens,
            "cache_creation_input_tokens": usage.cache_creation_input_tokens or 0,
            "cache_read_input_tokens": usage.cache_read_input_tokens or 0,
            "output_tokens": usage.output_tokens,
            "latency_s": round(latency, 4),
            "at": now(),
        }


# --- vocab -------------------------------------------------------------------------------------


class HashingReader:
    """File-like wrapper that hashes the raw (compressed) bytes as they are read."""

    def __init__(self, raw):
        self.raw = raw
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        chunk = self.raw.read(size)
        self.digest.update(chunk)
        return chunk


COPY_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\"}


def copy_unescape(field):
    """Decode one PostgreSQL COPY text-format field (the mbdump format)."""
    if "\\" not in field:
        return field
    out, i = [], 0
    while i < len(field):
        ch = field[i]
        if ch == "\\" and i + 1 < len(field):
            nxt = field[i + 1]
            if nxt in COPY_ESCAPES:
                out.append(COPY_ESCAPES[nxt])
                i += 2
                continue
            octal = re.match(r"[0-7]{1,3}", field[i + 1 :])
            if octal:
                out.append(chr(int(octal.group(), 8)))
                i += 1 + len(octal.group())
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def expected_sha(sums_path, name=DUMP_FILE):
    for line in Path(sums_path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0].lower()
    raise SystemExit(f"{name} is not listed in {sums_path}")


def stream_vocab(dump_path):
    """Return (sha256, timestamp, names, uses_by_id, per_scope) from one streamed dump."""
    names = {}
    uses = Counter()
    per_scope = {}
    timestamp = None
    wanted = {f"mbdump/{scope}_tag": scope for scope in SCOPES}
    with open(dump_path, "rb") as raw:
        hashed = HashingReader(raw)
        with bz2.BZ2File(hashed) as decompressed, tarfile.open(fileobj=decompressed, mode="r|") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                if member.name == "TIMESTAMP":
                    timestamp = archive.extractfile(member).read().decode("utf-8").strip()
                elif member.name == "mbdump/tag":
                    for line in archive.extractfile(member):
                        tid, name, _ = line.decode("utf-8").rstrip("\n").split("\t")
                        names[int(tid)] = copy_unescape(name)
                elif member.name in wanted:
                    rows = 0
                    distinct = set()
                    for line in archive.extractfile(member):
                        _, tid, count, _ = line.split(b"\t")
                        if int(count) <= 0:
                            continue
                        rows += 1
                        t = int(tid)
                        distinct.add(t)
                        uses[t] += 1
                    per_scope[wanted[member.name]] = {"uses": rows, "distinct_tags": len(distinct)}
        while hashed.read(1 << 20):  # the hash covers trailing bytes past the bzip2 stream
            pass
    missing = sorted(set(wanted.values()) - set(per_scope)) + ([] if names else ["tag"])
    if missing:
        raise SystemExit(f"the dump has no table for: {', '.join(missing)}")
    return hashed.digest.hexdigest(), timestamp, names, uses, per_scope


def cmd_vocab(args):
    want = expected_sha(args.sha256sums)
    sha, timestamp, names, uses_by_id, per_scope = stream_vocab(args.dump)
    if sha != want:
        print(f"checksum mismatch: {DUMP_FILE} streamed as {sha}, SHA256SUMS says {want}", file=sys.stderr)
        return EXIT_CHECKSUM
    uses = Counter()
    for tid, n in uses_by_id.items():
        uses[names[tid]] += n
    ranked = sorted(uses.items(), key=lambda kv: (-kv[1], kv[0]))
    kept = [(tag, n) for tag, n in ranked if n >= args.min_uses]
    total = sum(uses.values())
    doc = {
        "vocabulary_version": "1",
        "license": "MIT",
        "source": {
            "name": "MusicBrainz full export",
            "url": f"https://data.metabrainz.org/pub/musicbrainz/data/fullexport/{args.dump_name}/",
            "license": "CC0-1.0",
            "dump": args.dump_name,
            "file": DUMP_FILE,
            "sha256": sha,
            "timestamp": timestamp,
            "scopes": [f"{scope}_tag" for scope in SCOPES],
        },
        "rule": "A use is one (entity, tag) row with a positive vote count; tags with min_uses or more uses are kept.",
        "min_uses": args.min_uses,
        "counts": {
            "distinct_tags_in_scope": len(uses),
            "uses_in_scope": total,
            "tags_kept": len(kept),
            "uses_kept": sum(n for _, n in kept),
            "per_scope": per_scope,
        },
        "tags": [{"tag": tag, "uses": n} for tag, n in kept],
    }
    write_text_atomic(args.out, render(doc, "tags"))
    print(json.dumps({"dump": args.dump_name, "sha256": sha, **{k: v for k, v in doc["counts"].items() if k != "per_scope"}}), file=sys.stderr)
    return 0


# --- propose -----------------------------------------------------------------------------------


def load_vocab(path):
    vocab = load_json(path)
    tags = [row for row in vocab["tags"] if row["uses"] >= vocab["min_uses"]]
    return vocab, tags


def split_string_matches(tree, tags):
    table = tree.string_table()
    matched, rest = {}, []
    for row in tags:
        path = table.get(norm(row["tag"]))
        if path:
            matched[row["tag"]] = list(path)
        else:
            rest.append(row)
    return matched, rest


def bucket_of(jev_path, claude_path):
    if jev_path == claude_path:
        return "agree_none" if jev_path == [] else "agree_genre"
    return "disagree"


def carry_reviews(previous_path):
    """Reviewed rows of an existing lookup, by tag, so a rerun never throws a review away."""
    if not previous_path or not Path(previous_path).exists():
        return {}
    previous = load_json(previous_path)
    return {row["tag"]: row for row in previous.get("rows", []) if row.get("review_state") == "reviewed"}


def cmd_propose(args):
    if args.limit and not args.live:
        print("--limit is a smoke run for --live; a replay always covers the whole vocabulary", file=sys.stderr)
        return 2
    if not args.live:
        block_network()
    tree = Tree(args.tree)
    vocab, tags = load_vocab(args.vocab)
    matched, model_tags = split_string_matches(tree, tags)
    if args.limit:
        model_tags = model_tags[: args.limit]
    jev_caps = Captures(args.captures, JEV_MODEL, args.live)
    claude_caps = Captures(args.captures, CLAUDE_MODEL, args.live)
    jev = Jev(jev_caps, args.live)
    claude = Claude(claude_caps, tree, args.live)
    results = {}
    started = time.perf_counter()
    stop = threading.Event()  # set on the first failure so no worker starts another (paid) tag

    def run(row):
        if stop.is_set():
            return
        try:
            results[row["tag"]] = (jev_beam(jev, tree, row["tag"]), claude.ask(row["tag"]))
        except BaseException:
            stop.set()
            raise

    try:
        if model_tags:
            run(model_tags[0])  # warms Claude's prompt cache before the fan-out
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for future in [pool.submit(run, row) for row in model_tags[1:]]:
                future.result()
    except CaptureMiss as error:
        print(str(error), file=sys.stderr)
        return EXIT_CAPTURE_MISS
    except ModelMismatch as error:
        print(f"model pin violated, aborting: {error}", file=sys.stderr)
        return EXIT_MODEL_MISMATCH
    finally:
        if args.live:
            jev_caps.save()
            claude_caps.save()
    stats = {"jev": jev_caps.stats, "claude": claude_caps.stats, "new_captures": jev_caps.new + claude_caps.new, "wall_s": round(time.perf_counter() - started, 2)}
    if args.limit:
        print(json.dumps({"smoke_run_tags": len(model_tags), **stats}), file=sys.stderr)
        return 0

    reviews = carry_reviews(args.out_lookup)
    rows, queue, dropped_reviews = [], [], []
    for row in tags:
        tag, uses = row["tag"], row["uses"]
        if tag in matched:
            rows.append({"tag": tag, "uses": uses, "bucket": "string", "result": matched[tag], "proposals": None, "review_state": "not_required", "reviewer": None})
            continue
        beam, claude_path = results[tag]
        jev_path = beam["path"]
        bucket = bucket_of(jev_path, claude_path)
        proposals = {"jev": jev_path, "claude": claude_path}
        if bucket == "agree_none":
            rows.append({"tag": tag, "uses": uses, "bucket": bucket, "result": [], "proposals": proposals, "review_state": "not_required", "reviewer": None})
            continue
        default = claude_path if claude_path is not None else jev_path
        prior = reviews.get(tag)
        if prior and prior.get("proposals") == proposals and tree.contains(tuple(prior["result"])):
            rows.append({**prior, "uses": uses, "bucket": bucket})
            continue
        if prior:
            dropped_reviews.append(tag)
        rows.append({"tag": tag, "uses": uses, "bucket": bucket, "result": default, "proposals": proposals, "review_state": "pending", "reviewer": None})
        queue.append({"tag": tag, "uses": uses, "bucket": bucket, "default": default, "jev": jev_path, "claude": claude_path, "jev_top3": beam["top3"], "jev_separation": beam["separation"]})
    rows.sort(key=lambda r: r["tag"])
    queue.sort(key=lambda r: (-r["uses"], r["tag"]))
    counts = Counter(r["bucket"] for r in rows)
    states = Counter(r["review_state"] for r in rows)
    tree_ref = {"file": tree.path.name, "dump_date": tree.doc["source"]["dump_date"], "sha256": sha256_file(tree.path)}
    lookup = {
        "lookup_version": "1",
        "license": "MIT",
        "decision": "docs/adr/0020-mb-tag-genre-lookup.md",
        "publishable": False,
        "source": {"musicbrainz": {**vocab["source"], "min_uses": vocab["min_uses"]}, "tree": tree_ref},
        "models": {"jev": {"model": JEV_MODEL, "beam_width": BEAM}, "claude": {"model": CLAUDE_MODEL, "effort": CLAUDE_EFFORT, "list_sha": claude.list_sha}},
        "counts": {
            "tags": len(rows),
            "string": counts["string"],
            "agree_genre": counts["agree_genre"],
            "agree_none": counts["agree_none"],
            "disagree": counts["disagree"],
            "pending": states["pending"],
            "reviewed": states["reviewed"],
        },
        "rows": rows,
    }
    review_queue = {
        "queue_version": "1",
        "lookup": {"file": Path(args.out_lookup).name, "dump": vocab["source"]["dump"], "tree_dump_date": tree_ref["dump_date"]},
        "default_rule": "Claude's answer is the default; Jev's when Claude gave no valid answer.",
        "counts": {"rows": len(queue), "agree_genre": sum(q["bucket"] == "agree_genre" for q in queue), "disagree": sum(q["bucket"] == "disagree" for q in queue)},
        "rows": queue,
    }
    write_text_atomic(args.out_lookup, render(lookup, "rows"))
    write_text_atomic(args.out_queue, render(review_queue, "rows"))
    summary = {**lookup["counts"], "review_queue": len(queue), "reviews_reset": dropped_reviews, **stats}
    print(json.dumps(summary), file=sys.stderr)
    return 0


# --- estimate ----------------------------------------------------------------------------------


def cmd_estimate(args):
    block_network()
    tree = Tree(args.tree)
    vocab, tags = load_vocab(args.vocab)
    matched, model_tags = split_string_matches(tree, tags)
    claude = Claude(Captures(args.captures, CLAUDE_MODEL, True), tree, live=False)
    jev_caps = Captures(args.captures, JEV_MODEL, True)
    jev_done = {r["tag"] for r in jev_caps.records.values() if r.get("node") == "ROOT"}
    claude_misses = [r for r in model_tags if claude.key(r["tag"]) not in claude.captures.records]
    jev_misses = [r for r in model_tags if r["tag"] not in jev_done]
    system_tokens = round(CLAUDE_SPIKE_SYSTEM_TOKENS * len(claude.system) / CLAUDE_SPIKE_SYSTEM_CHARS)
    per_tag_claude = (system_tokens * OPUS_CACHE_READ + CLAUDE_MEAN_INPUT_TOKENS * OPUS_IN + CLAUDE_MEAN_OUTPUT_TOKENS * OPUS_OUT) / 1e6
    claude_usd = len(claude_misses) * per_tag_claude + (system_tokens * OPUS_CACHE_WRITE / 1e6 if claude_misses else 0)
    jev_tokens = round(len(jev_misses) * JEV_MEAN_INPUT_TOKENS_PER_TAG)
    out = {
        "dump": vocab["source"]["dump"],
        "min_uses": vocab["min_uses"],
        "tags": len(tags),
        "string_matches": len(matched),
        "model_tags": len(model_tags),
        "jev": {
            "model": JEV_MODEL,
            "tags_to_call": len(jev_misses),
            "requests": round(len(jev_misses) * JEV_MEAN_REQUESTS_PER_TAG),
            "input_tokens": jev_tokens,
            "usd": round(jev_tokens / 1e6 * JEV_USD_PER_MTOK_IN, 2),
        },
        "claude": {
            "model": CLAUDE_MODEL,
            "effort": CLAUDE_EFFORT,
            "requests": len(claude_misses),
            "system_prompt_tokens_est": system_tokens,
            "cache_read_tokens": system_tokens * max(len(claude_misses) - 1, 0),
            "input_tokens": CLAUDE_MEAN_INPUT_TOKENS * len(claude_misses),
            "output_tokens": CLAUDE_MEAN_OUTPUT_TOKENS * len(claude_misses),
            "usd": round(claude_usd, 2),
        },
        "wall_hours_est": round(len(claude_misses) * (SECONDS_PER_TAG_JEV + SECONDS_PER_TAG_CLAUDE) / args.workers / 3600, 2),
    }
    out["usd_total"] = round(out["jev"]["usd"] + out["claude"]["usd"], 2)
    print(json.dumps(out, indent=1))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    vocab = sub.add_parser("vocab", help="stream mbdump-derived.tar.bz2 into the >= min-uses tag vocabulary")
    vocab.add_argument("--dump", required=True, help="path to mbdump-derived.tar.bz2 (may be a pipe)")
    vocab.add_argument("--dump-name", required=True, help="full export name, e.g. 20261111-002335")
    vocab.add_argument("--sha256sums", required=True, help="the export's SHA256SUMS file (may be a pipe)")
    vocab.add_argument("--min-uses", type=int, default=20)
    vocab.add_argument("--out", required=True)

    propose = sub.add_parser("propose", help="run the cascade and write the lookup and the review queue")
    estimate = sub.add_parser("estimate", help="count capture misses and estimate a --live run's cost")
    for p in (propose, estimate):
        p.add_argument("--vocab", required=True)
        p.add_argument("--tree", required=True)
        p.add_argument("--captures", required=True, help="directory of <model>.jsonl captures")
        p.add_argument("--workers", type=int, default=4)
    propose.add_argument("--out-lookup", required=True)
    propose.add_argument("--out-queue", required=True)
    propose.add_argument("--live", action="store_true", help="allow paid Jev and Claude calls on capture misses")
    propose.add_argument("--limit", type=int, default=0, help="with --live: capture only the first N model tags, write no lookup")

    args = parser.parse_args(argv)
    return {"vocab": cmd_vocab, "propose": cmd_propose, "estimate": cmd_estimate}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
