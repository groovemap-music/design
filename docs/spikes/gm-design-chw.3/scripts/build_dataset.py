#!/usr/bin/env python3
"""Join the MusicBrainz ground-truth (mbid -> discogs_id) with the extracted
Discogs target records to build the final query set and candidate pool for
one entity kind (artist or label).

Scoping decision (documented in the spike report): the full Discogs corpus
(~9M artists) is out of the Docker-VM / CPU-thread budget to embed, so the
candidate pool is capped at --candidate-pool entries: the correct target of
every sampled query, plus random distractors drawn from the rest of the
MusicBrainz-linked Discogs population (itself already hundreds of thousands
of real, previously-linked names for labels, more for artists). This is an
optimistic upper bound on true full-corpus recall -- stated as a limitation,
not hidden.

Query set = a stratified-by-script sample of the MusicBrainz side of the
remaining links, capped at --sample.

Usage:
    python3 build_dataset.py artist data/artists_linked.jsonl data/artists_discogs_targets.jsonl \
        data/candidates_artist.jsonl data/queries_artist.jsonl \
        --sample 4000 --candidate-pool 20000 --seed 20260924
"""
from __future__ import annotations

import argparse
import json
import random
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


LATIN_BLOCKS = (
    (0x0041, 0x024F),  # Basic Latin + Latin-1 Supplement + Latin Extended A/B
    (0x1E00, 0x1EFF),  # Latin Extended Additional
)


def script_of(name: str) -> str:
    has_non_latin = False
    has_alpha = False
    for ch in name:
        if not ch.isalpha():
            continue
        has_alpha = True
        cp = ord(ch)
        if not any(lo <= cp <= hi for lo, hi in LATIN_BLOCKS):
            has_non_latin = True
            break
    if not has_alpha:
        return "unknown"
    return "non_latin" if has_non_latin else "latin"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind")
    ap.add_argument("mb_linked_path")
    ap.add_argument("discogs_targets_path")
    ap.add_argument("candidates_out")
    ap.add_argument("queries_out")
    ap.add_argument("--sample", type=int, default=4000, help="query sample size")
    ap.add_argument("--candidate-pool", type=int, default=20000, help="total candidate pool size")
    ap.add_argument("--seed", type=int, default=20260924)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    discogs_by_id: dict[str, dict] = {}
    with open(args.discogs_targets_path) as f:
        for line in f:
            rec = json.loads(line)
            discogs_by_id[rec["discogs_id"]] = rec

    total_mb_linked = 0
    mb_links: list[dict] = []
    with open(args.mb_linked_path) as f:
        for line in f:
            total_mb_linked += 1
            rec = json.loads(line)
            if rec["discogs_id"] in discogs_by_id:
                mb_links.append(rec)

    print(
        f"[{args.kind}] mb_linked={total_mb_linked} discogs_targets_found={len(discogs_by_id)} "
        f"usable_links(mb-side has discogs record)={len(mb_links)}",
        file=sys.stderr,
    )

    # 1. stratified query sample by script bucket, proportional to population
    buckets: dict[str, list[dict]] = {"latin": [], "non_latin": [], "unknown": []}
    for rec in mb_links:
        buckets[script_of(rec["name"] or "")].append(rec)
    for b in buckets.values():
        rng.shuffle(b)

    total = len(mb_links)
    sample_n = min(args.sample, total)
    sampled: list[dict] = []
    for items in buckets.values():
        take = round(sample_n * len(items) / total) if total else 0
        sampled.extend(items[:take])
    rng.shuffle(sampled)
    sampled = sampled[:sample_n]

    # 2. candidate pool = correct targets of sampled queries + random distractors
    query_target_ids = {rec["discogs_id"] for rec in sampled}
    remaining_ids = [i for i in discogs_by_id if i not in query_target_ids]
    rng.shuffle(remaining_ids)
    distractor_n = max(0, args.candidate_pool - len(query_target_ids))
    pool_ids = query_target_ids | set(remaining_ids[:distractor_n])
    candidates = [discogs_by_id[i] for i in pool_ids]

    name_counts = Counter(normalize(c["name"]) for c in candidates if c.get("name"))

    with open(args.candidates_out, "w") as f:
        for c in candidates:
            f.write(
                json.dumps(
                    {"discogs_id": c["discogs_id"], "kind": args.kind, "name": c["name"]},
                    ensure_ascii=False,
                )
                + "\n"
            )

    with open(args.queries_out, "w") as f:
        for rec in sampled:
            target = discogs_by_id[rec["discogs_id"]]
            mb_name = rec["name"] or ""
            target_name = target.get("name") or ""
            mb_norm = normalize(mb_name)
            target_norm = normalize(target_name)
            if mb_name == target_name:
                match_class = "exact"
            elif mb_norm == target_norm:
                match_class = "diacritic_or_case_only"
            else:
                match_class = "other_mismatch"
            f.write(
                json.dumps(
                    {
                        "mbid": rec["mbid"],
                        "kind": args.kind,
                        "query_name": mb_name,
                        "correct_discogs_id": rec["discogs_id"],
                        "correct_name": target_name,
                        "script": script_of(mb_name),
                        "match_class": match_class,
                        # collisions in the candidate pool for the CORRECT target's name -- this
                        # is what makes a query ambiguous for a name-string retriever, not how
                        # common the (possibly quite different) MB-side spelling is.
                        "name_frequency": "common" if name_counts[target_norm] > 1 else "rare",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    print(
        f"[{args.kind}] candidate_pool={len(candidates)} queries_sampled={len(sampled)} "
        f"(scripts: {[(k, len(v)) for k, v in buckets.items()]})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
