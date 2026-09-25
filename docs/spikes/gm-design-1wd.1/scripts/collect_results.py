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
import sys
from pathlib import Path

from evaluate import (
    edit_census,
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
        out[split]["chosen_threshold"] = t
        out[split]["threshold_rule"] = f"lowest integer score with dev mean queue <= {QUEUE_BAR}"
        (results / f"eval_{split}.json").write_text(json.dumps(out[split], indent=1) + "\n")
    stats = json.loads((data / "sample_stats.json").read_text())
    (results / "sample_stats.json").write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print(f"chosen threshold on dev: {t}", file=sys.stderr)


if __name__ == "__main__":
    main()
