#!/usr/bin/env python3
"""Fix the name_frequency bug in-place: it must count collisions in the
candidate pool against the CORRECT target's normalized name, not the (often
differently spelled) MusicBrainz query name. Patches queries_<kind>.jsonl and,
if present, results_<kind>.json (joined by mbid), without re-running any
embeddings.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter

DISCOGS_DISAMBIGUATOR = re.compile(r"\s*\(\d+\)$")


def normalize(name: str) -> str:
    if not name:
        return ""
    # Discogs appends "(2)", "(3)", ... to disambiguate same-named artists/labels;
    # strip it so "Josh Wink" and "Josh Wink (2)" collide on the base name they
    # actually share, which is the real source of retrieval ambiguity.
    name = DISCOGS_DISAMBIGUATOR.sub("", name)
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().strip()


def main() -> None:
    candidates_path, queries_path = sys.argv[1], sys.argv[2]
    results_path = sys.argv[3] if len(sys.argv) > 3 else None

    name_counts: Counter[str] = Counter()
    with open(candidates_path) as f:
        for line in f:
            rec = json.loads(line)
            name_counts[normalize(rec["name"])] += 1

    fixed_freq: dict[str, str] = {}
    queries = []
    with open(queries_path) as f:
        for line in f:
            q = json.loads(line)
            freq = "common" if name_counts[normalize(q["correct_name"])] > 1 else "rare"
            q["name_frequency"] = freq
            fixed_freq[q["mbid"]] = freq
            queries.append(q)
    with open(queries_path, "w") as f:
        for q in queries:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(f"patched {queries_path}: common={sum(1 for v in fixed_freq.values() if v == 'common')} "
          f"rare={sum(1 for v in fixed_freq.values() if v == 'rare')}", file=sys.stderr)

    if results_path:
        with open(results_path) as f:
            data = json.load(f)
        n_changed = 0
        for row in data["results"]:
            new_freq = fixed_freq.get(row["mbid"])
            if new_freq is not None and new_freq != row.get("name_frequency"):
                n_changed += 1
            if new_freq is not None:
                row["name_frequency"] = new_freq
        with open(results_path, "w") as f:
            json.dump(data, f)
        print(f"patched {results_path}: {n_changed} rows changed", file=sys.stderr)


if __name__ == "__main__":
    main()
