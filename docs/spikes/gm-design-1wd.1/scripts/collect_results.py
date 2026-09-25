#!/usr/bin/env python3
"""Evaluate the dev and test runs once, choose the review threshold on dev, and write
the committed aggregate results.

The threshold rule is zwy's, applied to this population's dev split: the lowest
integer score whose mean review queue on dev is at most 3 candidates per query. It is
then applied to test unchanged. Outputs hold counts, rates, and timings only: no ids,
names, barcodes, or catalogue numbers.

Usage: python3 collect_results.py <work dir> <results dir>
"""
from __future__ import annotations

import json
import math
import random
import statistics
import sys
from pathlib import Path

from evaluate import (
    edit_census,
    expected_hit,
    target_position,
    evaluate_runs,
    field_agreement,
    load_jsonl,
    load_pool,
    query_context,
)

THRESHOLDS = [float(t) for t in range(4, 19)]
QUEUE_BAR = 3.0


def choose_threshold(dev: dict) -> float | None:
    for t in THRESHOLDS:
        if dev["review"][str(t)]["queue_per_query"]["mean"] <= QUEUE_BAR:
            return t
    return None


def wilson(k: float, n: int, z: float = 1.96) -> list[float] | None:
    """95% Wilson interval for a rate, in percent."""
    if not n:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(100 * (mid - half), 1), round(100 * (mid + half), 1)]


def intervals(rows: list[dict], threshold: float | None, reps: int = 2000, seed: int = 20260925) -> dict:
    """95% intervals on the reachable queries: Wilson for per-query rates, and a
    percentile bootstrap over queries for the queue mean and queue precision (queue
    members are clustered by query, so a Wilson interval on members would be too
    narrow). The bootstrap resamples queries with a seeded RNG, never by id."""
    n = len(rows)
    pos = [target_position(r) for r in rows]
    out = {
        "n": n,
        "coverage": wilson(sum(1 for p in pos if p), n),
        "unique_top_recall@1": wilson(sum(1 for p in pos if p == (0, 1)), n),
        "expected_recall@1": wilson(sum(expected_hit(p, 1) for p in pos), n),
        "expected_recall@10": wilson(sum(expected_hit(p, 10) for p in pos), n),
    }
    if threshold is None or not n:
        return out
    per = []
    for r in rows:
        inq = [c for c in r["candidates"] if c[1] >= threshold]
        per.append((len(inq), int(any(c[0] == f"discogs:release:{r['target']}" for c in inq))))
    rng = random.Random(seed)
    means, precs = [], []
    for _ in range(reps):
        sample = [per[rng.randrange(n)] for _ in range(n)]
        size = sum(s for s, _ in sample)
        means.append(size / n)
        if size:
            precs.append(100 * sum(h for _, h in sample) / size)

    def ci(xs: list[float]) -> list[float]:
        xs = sorted(xs)
        return [round(xs[int(0.025 * len(xs))], 2), round(xs[int(0.975 * len(xs)) - 1], 2)]

    out["queue_mean"] = ci(means)
    out["queue_precision"] = ci(precs)
    out["queue_mean_point"] = round(statistics.fmean(s for s, _ in per), 2)
    return out


def main() -> None:
    work, results = Path(sys.argv[1]), Path(sys.argv[2])
    runs_dir, data = work / "runs", work / "data"
    results.mkdir(parents=True, exist_ok=True)
    pool = load_pool([str(data / "pool_releases.jsonl.gz"), str(data / "pool_masters.jsonl.gz")])
    out = {}
    for split in ("dev", "test"):
        qrecs = load_jsonl(str(data / f"queries_{split}.jsonl"))
        qctx = query_context(qrecs, pool)
        runs = {f"baseline_{split}": load_jsonl(str(runs_dir / f"baseline_{split}.jsonl.gz"))}
        res = evaluate_runs(pool, qctx, runs, THRESHOLDS)
        res["field_agreement"] = field_agreement(qctx["qviews"], qctx["targets"], pool["views"])
        res["edit_census"] = edit_census(qrecs, str(data / "later_records.jsonl.gz"))
        res["timing"] = json.loads((runs_dir / f"baseline_{split}.timing.json").read_text())
        out[split] = res
    t = choose_threshold(out["dev"]["runs"]["baseline_dev"])
    for split in ("dev", "test"):
        rows = load_jsonl(str(runs_dir / f"baseline_{split}.jsonl.gz"))
        reachable = [r for r in rows if f"discogs:release:{r['target']}" in pool["views"]]
        out[split]["intervals_reachable"] = intervals(reachable, t)
        out[split]["chosen_threshold"] = t
        out[split]["threshold_rule"] = f"lowest integer score with dev mean queue <= {QUEUE_BAR}"
        (results / f"eval_{split}.json").write_text(json.dumps(out[split], indent=1) + "\n")
    stats = json.loads((data / "sample_stats.json").read_text())
    (results / "sample_stats.json").write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print(f"chosen threshold on dev: {t}", file=sys.stderr)


if __name__ == "__main__":
    main()
