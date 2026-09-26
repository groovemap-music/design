#!/usr/bin/env python3
"""Join the non-Latin, Discogs-linked MusicBrainz ground truth with the
extracted Discogs target records and the realistic-scale candidate pool, to
build the final query set and candidate pool for one entity kind.

Unlike gm-design-chw.3's build_dataset.py (proportional-to-population script
stratification over ALL scripts, 20k capped candidate pool), this spike's
query population is already non-Latin-only by construction (see
extract_mb_nonlatin.py) and the candidate pool is the realistic-scale one
built by extract_discogs_pool.py (>=1M artists / all labels), not a 20k cap.

Usage:
    python3 build_dataset.py artist linked_nonlatin_artist.jsonl discogs_targets_artist.jsonl \
        pool_artist.jsonl candidates_artist.jsonl queries_artist.jsonl --sample 5000 --seed 20260924
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
from collections import Counter

from script_util import script_of

DISCOGS_DISAMBIGUATOR = re.compile(r"\s*\(\d+\)$")


def normalize(name: str) -> str:
    if not name:
        return ""
    name = DISCOGS_DISAMBIGUATOR.sub("", name)
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind")
    ap.add_argument("mb_linked_nonlatin_path")
    ap.add_argument("discogs_targets_path")
    ap.add_argument("pool_path")
    ap.add_argument("candidates_out")
    ap.add_argument("queries_out")
    ap.add_argument("--sample", type=int, default=5000, help="query sample cap (low thousands per entity type)")
    ap.add_argument("--seed", type=int, default=20260924)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    discogs_by_id: dict[str, dict] = {}
    with open(args.discogs_targets_path) as f:
        for line in f:
            rec = json.loads(line)
            discogs_by_id[rec["discogs_id"]] = rec

    total_mb_nonlatin_linked = 0
    mb_links: list[dict] = []
    with open(args.mb_linked_nonlatin_path) as f:
        for line in f:
            total_mb_nonlatin_linked += 1
            rec = json.loads(line)
            if rec["discogs_id"] in discogs_by_id:
                mb_links.append(rec)

    print(
        f"[{args.kind}] mb_nonlatin_linked={total_mb_nonlatin_linked} "
        f"usable(discogs record recovered)={len(mb_links)}",
        file=sys.stderr,
    )

    rng.shuffle(mb_links)
    sample_n = min(args.sample, len(mb_links))
    sampled = mb_links[:sample_n]
    if sample_n < args.sample:
        print(
            f"[{args.kind}] WARNING: only {sample_n} usable non-Latin linked queries available "
            f"(requested {args.sample}) -- flagged, not padded",
            file=sys.stderr,
        )

    # candidate pool = the realistic-scale pool (already contains every sampled query's
    # correct target, by construction of extract_discogs_pool.py) -- load directly.
    candidates: list[dict] = []
    pool_ids: set[str] = set()
    with open(args.pool_path) as f:
        for line in f:
            rec = json.loads(line)
            if rec["discogs_id"] in pool_ids:
                continue
            pool_ids.add(rec["discogs_id"])
            candidates.append(rec)

    query_target_ids = {rec["discogs_id"] for rec in sampled}
    missing_targets = query_target_ids - pool_ids
    if missing_targets:
        print(
            f"[{args.kind}] WARNING: {len(missing_targets)} sampled query targets missing from pool "
            f"(dropping those queries)",
            file=sys.stderr,
        )
        sampled = [rec for rec in sampled if rec["discogs_id"] not in missing_targets]

    name_counts = Counter(normalize(c["name"]) for c in candidates if c.get("name"))

    with open(args.candidates_out, "w") as f:
        for c in candidates:
            f.write(json.dumps({"discogs_id": c["discogs_id"], "kind": args.kind, "name": c["name"]}, ensure_ascii=False) + "\n")

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
                        "name_frequency": "common" if name_counts[target_norm] > 1 else "rare",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    print(
        f"[{args.kind}] candidate_pool={len(candidates)} queries_sampled={len(sampled)}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
