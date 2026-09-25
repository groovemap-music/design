#!/usr/bin/env python3
"""Run the gm-design-zwy deterministic baseline over one query set and write every
candidate with its score and ADR 0014 section 4 comparison vector.

This is zwy's ``run_method.py baseline`` with one change that matters: it records
candidates as an unordered set. zwy sorted equal scores by key, so its recall@1 rested
on id order; here nothing downstream can see an order among equal scores, and every
metric in ``evaluate.py`` is computed from score groups. The candidate list is written
sorted by key only so the file is byte-stable; ``evaluate.py`` never reads that order.

Usage:
    python3 run_baseline.py --queries queries_test.jsonl \
        --pool pool_releases.jsonl.gz pool_masters.jsonl.gz --out runs/baseline_test.jsonl.gz \
        --timing-out runs/baseline_test.timing.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import resource
import sys
import time

os.environ.setdefault("OMP_NUM_THREADS", "4")

from matching import BaselineConfig, BaselineIndex, comparison, score_of, view_of  # noqa: E402


def iter_jsonl(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        for line in f:
            yield json.loads(line)


def peak_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024


def candidates_for(q, index: BaselineIndex, cfg: BaselineConfig) -> tuple[list[list], dict]:
    """Every blocked candidate as [key, score, comparison vector], unordered."""
    ids, diag = index.block(q, cfg)
    out = []
    for i in ids:
        c = index.pool[i]
        vec = comparison(q, c, cfg.drop)
        out.append([c.key, score_of(vec), list(vec)])
    return out, diag


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True)
    ap.add_argument("--pool", required=True, nargs="+")
    ap.add_argument("--drop", default="", help="comma list of fields to ablate")
    ap.add_argument("--out", required=True)
    ap.add_argument("--timing-out", required=True)
    args = ap.parse_args()
    drop = frozenset(x for x in args.drop.split(",") if x)

    t0 = time.perf_counter()
    queries = []
    for r in iter_jsonl(args.queries):
        v = view_of(r)
        v.extra["target"] = r["target_discogs_id"]
        queries.append(v)
    pool = [view_of(r, keep_raw=False) for path in args.pool for r in iter_jsonl(path)]
    t_load = time.perf_counter() - t0
    t1 = time.perf_counter()
    index = BaselineIndex(pool)
    cfg = BaselineConfig(drop=drop)
    t_index = time.perf_counter() - t1
    t2 = time.perf_counter()
    with gzip.open(args.out, "wt") as f:
        for q in queries:
            cands, diag = candidates_for(q, index, cfg)
            cands.sort(key=lambda c: c[0])  # byte-stable file only; never read as a rank
            f.write(json.dumps({"q": q.native_id, "target": q.extra["target"], "candidates": cands,
                                "diag": diag}) + "\n")
    t_match = time.perf_counter() - t2
    timing = {
        "queries": len(queries),
        "pool": len(pool),
        "drop": sorted(drop),
        "load_seconds": round(t_load, 3),
        "index_seconds": round(t_index, 3),
        "match_seconds": round(t_match, 3),
        "peak_rss_mb": round(peak_rss_mb(), 1),
    }
    with open(args.timing_out, "w") as f:
        json.dump(timing, f, indent=2)
    print(json.dumps(timing), file=sys.stderr)


if __name__ == "__main__":
    main()
