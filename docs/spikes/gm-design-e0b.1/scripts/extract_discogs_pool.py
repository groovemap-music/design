#!/usr/bin/env python3
"""Stream a Discogs XML dump and build a REALISTIC-scale candidate pool: every
target record (the correct answer for some query) is always kept; every other
record is kept with probability --sample-prob (Bernoulli sampling, O(1)
memory, single pass). Never writes the decompressed dump to disk -- curl and
gunzip are piped directly into this process's stdin, and lxml.etree.iterparse
processes one element at a time, clearing as it goes (matches
gm-design-chw.3's extract_discogs_targets.py method, generalized to a big
non-target sample instead of target-only filtering).

For labels the epic calls for the WHOLE corpus as the pool, so pass
--sample-prob 1.0. For artists the epic calls for "at least 1M", so pick a
probability against the known population size (see the spike doc for the
exact figure and margin used) to land comfortably above 1,000,000 rows.

Usage:
    curl -sL <artists.xml.gz url> | gunzip -c \
        | python3 extract_discogs_pool.py artist targets.json pool_artist.jsonl --sample-prob 0.108 --seed 20260924
"""
from __future__ import annotations

import argparse
import json
import random
import sys

from lxml import etree


def load_targets(path: str) -> set[str]:
    with open(path) as f:
        return set(json.load(f))


def text_of(el, tag: str) -> str | None:
    child = el.find(tag)
    return child.text if child is not None else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind")
    ap.add_argument("targets_path")
    ap.add_argument("out_path")
    ap.add_argument("--sample-prob", type=float, required=True)
    ap.add_argument("--seed", type=int, default=20260924)
    args = ap.parse_args()

    targets = load_targets(args.targets_path)
    rng = random.Random(args.seed)

    scanned = 0
    kept = 0
    targets_found = 0

    context = etree.iterparse(sys.stdin.buffer, events=("end",), tag=args.kind, recover=True)
    with open(args.out_path, "w") as out:
        for _, el in context:
            scanned += 1
            disc_id = text_of(el, "id")
            is_target = disc_id in targets
            keep = is_target or rng.random() < args.sample_prob
            if keep:
                kept += 1
                if is_target:
                    targets_found += 1
                record = {
                    "discogs_id": disc_id,
                    "kind": args.kind,
                    "name": text_of(el, "name"),
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
            if scanned % 1000000 == 0:
                print(f"...scanned {scanned} {args.kind} records, kept {kept} (targets found {targets_found}/{len(targets)})", file=sys.stderr)

    print(
        f"DONE kind={args.kind} scanned={scanned} kept={kept} targets_found={targets_found}/{len(targets)} "
        f"sample_prob={args.sample_prob}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
