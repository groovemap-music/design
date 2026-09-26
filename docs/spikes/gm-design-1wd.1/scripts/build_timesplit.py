#!/usr/bin/env python3
"""Join two MusicBrainz snapshots into the time-split holdout, split it into dev and
test, and emit the blocking keys the Discogs pass keeps records for.

A release is **newly linked** when the earlier snapshot shows it with no Discogs
release relation and the later snapshot shows it with one. The query is the *earlier*
record, which is what a matcher would have seen while the release was unlinked; the
later record's Discogs relation is the held-out label. The later record is kept
alongside only to measure what editors changed while adding the link.

Exclusions, all counted:

- the release gained more than one Discogs release relation (no single correct
  edition);
- the release is absent from the earlier snapshot (created between the dumps, so it
  was never an unlinked release a matcher could have served).

A release that had only a Discogs *master* link in the earlier snapshot is kept, since
it had no release relation and a master link names the work, not the edition; it is
counted.

Every query is used; there is no sampling. Dev and test are split by a hash of the
MBID, so the split is stable across reruns and independent of dump order.

Usage:
    python3 build_timesplit.py mb_20260919-001001.jsonl.gz mb_20260923-001002.jsonl.gz \
        --dev-mod 5 --out-dir data/
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import orjson

from normalize import barcode_key, catno_key, script_bucket, title_key


def iter_snapshot(path: str):
    with gzip.open(path, "rb") as f:
        for line in f:
            yield orjson.loads(line)


def is_dev(mbid: str, dev_mod: int) -> bool:
    return int(hashlib.sha256(mbid.encode()).hexdigest(), 16) % dev_mod == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("early")
    ap.add_argument("late")
    ap.add_argument("--dev-mod", type=int, default=5, help="1 in N queries goes to dev")
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()
    out = Path(args.out_dir)
    stats: Counter[str] = Counter()

    # Pass 1, later snapshot: every MBID, and the label of every linked release.
    late_ids: set[bytes] = set()
    late_linked: dict[str, list[str]] = {}
    for rec in iter_snapshot(args.late):
        late_ids.add(bytes.fromhex(rec["native_id"].replace("-", "")))
        stats["late_releases"] += 1
        if rec["discogs_release_ids"]:
            late_linked[rec["native_id"]] = rec["discogs_release_ids"]
            stats["late_linked"] += 1
    print(f"late pass: {dict(stats)}", file=sys.stderr, flush=True)

    # Pass 2, earlier snapshot: the unlinked population and the newly linked queries.
    queries: dict[str, dict] = {}
    for rec in iter_snapshot(args.early):
        mbid = rec["native_id"]
        stats["early_releases"] += 1
        label = late_linked.pop(mbid, None)
        if rec["discogs_release_ids"]:
            stats["early_linked"] += 1
            if label is None:
                stats["early_linked_lost_link_or_deleted"] += 1
            continue
        stats["early_unlinked"] += 1
        if rec["discogs_master_links"]:
            stats["early_unlinked_with_master_link"] += 1
        if bytes.fromhex(mbid.replace("-", "")) not in late_ids:
            stats["early_unlinked_absent_from_late"] += 1
            continue
        if label is None:
            continue
        stats["early_unlinked_gained_link"] += 1
        if len(label) > 1:
            stats["excluded_multi_link"] += 1
            continue
        rec["target_discogs_id"] = label[0]
        rec["script"] = script_bucket(rec["title"])
        rec["split"] = "dev" if is_dev(mbid, args.dev_mod) else "test"
        if rec["discogs_master_links"]:
            stats["newly_linked_had_master_link"] += 1
        queries[mbid] = rec
    # Whatever is left was linked in the later snapshot but absent from the earlier one.
    stats["excluded_new_release_linked"] = len(late_linked)
    del late_linked, late_ids
    stats["newly_linked_eligible"] = len(queries)
    print(f"early pass: {dict(stats)}", file=sys.stderr, flush=True)

    # Pass 3, later snapshot again: the later record of each query, for the edit census.
    with gzip.open(out / "later_records.jsonl.gz", "wb") as f:
        for rec in iter_snapshot(args.late):
            if rec["native_id"] in queries:
                f.write(orjson.dumps(rec) + b"\n")

    fanin = Counter(q["target_discogs_id"] for q in queries.values())
    stats["targets_linked_from_multiple_queries"] = sum(1 for c in fanin.values() if c > 1)
    keys = {"targets": set(), "barcodes": set(), "catnos": set(), "titles": set()}
    for split in ("dev", "test"):
        part = [q for q in queries.values() if q["split"] == split]
        part.sort(key=lambda q: hashlib.sha256(q["native_id"].encode()).hexdigest())
        with open(out / f"queries_{split}.jsonl", "w") as f:
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
        stats[f"{split}_queries"] = len(part)
        for bucket, n in Counter(r["script"] for r in part).items():
            stats[f"{split}_script_{bucket}"] = n
    with open(out / "blocking_keys.json", "w") as f:
        json.dump({k: sorted(v) for k, v in keys.items()}, f)
    for k, v in keys.items():
        stats[f"keys_{k}"] = len(v)
    with open(out / "sample_stats.json", "w") as f:
        json.dump(dict(stats), f, indent=2, sort_keys=True)
    print(json.dumps(dict(stats), indent=2, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    main()
