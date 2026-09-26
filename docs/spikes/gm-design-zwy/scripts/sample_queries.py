#!/usr/bin/env python3
"""Sample dev and test query sets from the extracted MusicBrainz linked releases and
emit the blocking-key set the Discogs extraction pass keeps records for.

Only MusicBrainz releases with exactly one Discogs release relation become queries:
a release linked to several Discogs releases has no single correct edition, and one
linked only to a Discogs master is a release-vs-master modelling error on the
MusicBrainz side (both are counted in the report, not scored). The sample is
stratified by the title's script bucket in proportion to the linked population, and
the dev/test split is by a hash of the MBID so it is stable across reruns.

Because the proportional sample leaves the non-Latin slice thin, ``--nonlatin-extra``
draws a further non-Latin-only slice from the remaining population.

Usage:
    python3 sample_queries.py mb_linked.jsonl --test 10000 --dev 2000 --seed 20260924 --out-dir data/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from normalize import barcode_key, catno_key, script_bucket, title_key


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mb_linked")
    ap.add_argument("--test", type=int, default=10000)
    ap.add_argument("--dev", type=int, default=2000)
    ap.add_argument("--nonlatin-extra", type=int, default=1000,
                    help="extra non-Latin-title queries, disjoint from dev/test, scored as their own slice")
    ap.add_argument("--seed", type=int, default=20260924)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out = Path(args.out_dir)

    stats: Counter[str] = Counter()
    target_fanin: Counter[str] = Counter()
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    with open(args.mb_linked) as f:
        for line in f:
            rec = json.loads(line)
            stats["linked_records"] += 1
            ids = rec["discogs_release_ids"]
            if not ids:
                stats["excluded_master_or_other_link_only"] += 1
                continue
            if len(ids) > 1:
                stats["excluded_multi_release_link"] += 1
                continue
            rec["target_discogs_id"] = ids[0]
            rec["script"] = script_bucket(rec["title"])
            target_fanin[ids[0]] += 1
            by_bucket[rec["script"]].append(rec)
    eligible = sum(len(v) for v in by_bucket.values())
    stats["eligible_single_link"] = eligible
    stats["targets_linked_from_multiple_mb_releases"] = sum(1 for c in target_fanin.values() if c > 1)

    rng = random.Random(args.seed)
    want = args.test + args.dev
    sampled: list[dict] = []
    for bucket, recs in sorted(by_bucket.items()):
        k = min(len(recs), round(want * len(recs) / eligible))
        sampled.extend(rng.sample(recs, k))
        stats[f"population_{bucket}"] = len(recs)
    rng.shuffle(sampled)

    def split_of(rec: dict) -> int:
        return int(hashlib.sha256(rec["native_id"].encode()).hexdigest(), 16)

    sampled.sort(key=split_of)
    dev, test = sampled[: args.dev], sampled[args.dev : args.dev + args.test]
    taken = {r["native_id"] for r in sampled}
    rest = [r for r in by_bucket.get("non_latin", []) if r["native_id"] not in taken]
    nonlatin = rng.sample(rest, min(len(rest), args.nonlatin_extra))

    keys = {"targets": set(), "barcodes": set(), "catnos": set(), "titles": set()}
    for name, part in (("dev", dev), ("test", test), ("test_nonlatin", nonlatin)):
        with open(out / f"queries_{name}.jsonl", "w") as f:
            for rec in part:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                keys["targets"].add(rec["target_discogs_id"])
                if (b := barcode_key(rec["barcode"])):
                    keys["barcodes"].add(b)
                for li in rec["labels"]:
                    if (c := catno_key(li.get("catno"))):
                        keys["catnos"].add(c)
                if (t := title_key(rec["title"])):
                    keys["titles"].add(t)
        stats[f"{name}_queries"] = len(part)
        for bucket, n in Counter(r["script"] for r in part).items():
            stats[f"{name}_script_{bucket}"] = n
    with open(out / "blocking_keys.json", "w") as f:
        json.dump({k: sorted(v) for k, v in keys.items()}, f)
    for k, v in keys.items():
        stats[f"keys_{k}"] = len(v)
    with open(out / "sample_stats.json", "w") as f:
        json.dump(dict(stats), f, indent=2, sort_keys=True)
    print(json.dumps(dict(stats), indent=2, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    main()
