#!/usr/bin/env python3
"""Evaluate every finished run and write the committed aggregate results.

Loads the pool once, evaluates each run group against its query set, and gathers
the timing records plus the peak RSS that ``/usr/bin/time -l`` printed for each run
process. The outputs contain counts, rates, and timings only: no ids, names,
barcodes, or catalogue numbers.

Usage: python3 collect_results.py <work dir> <results dir>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from evaluate import evaluate_runs, load_jsonl, load_pool, query_context

GROUPS = {
    "eval_full_10k": ("queries_test.jsonl", [
        "baseline_10k", "semrerank_10k", "baseline_kindblind_10k", "semrerank_kindblind_10k", "semrerank_raw_10k",
    ]),
    "eval_bounded_1k": ("queries_test.jsonl", ["baseline_b1k", "semrerank_b1k", "native_b1k", "exhaustive_b1k"]),
    "eval_ablation_10k": ("queries_test.jsonl", [
        f"{m}_drop_{d}_10k" for d in ("barcode", "catno", "title", "artist", "descriptors", "barcode+catno", "title+artist")
        for m in ("baseline", "semrerank")
    ]),
    "eval_ablation_exhaustive_b1k": ("queries_test.jsonl", [
        f"exhaustive_drop_{d}_b1k" for d in ("barcode", "catno", "title", "artist", "descriptors", "barcode+catno",
                                             "title+artist")
    ]),
    "eval_dev": ("queries_dev.jsonl", ["baseline_dev", "semrerank_dev"]),
    "eval_nonlatin": ("queries_test_nonlatin.jsonl", ["baseline_nonlatin", "semrerank_nonlatin"]),
}
THRESHOLDS = {
    "baseline": [4, 6, 8, 10, 12, 14],
    "semantica": [0.6, 0.7, 0.8, 0.9, 0.95, 1.0],
    "exhaustive": [0.5, 0.6, 0.7, 0.8, 0.9],
}
MAXRSS = re.compile(r"(\d+)\s+maximum resident set size")


def thresholds_for(name: str) -> list[float]:
    if name.startswith("baseline"):
        return THRESHOLDS["baseline"]
    if name.startswith("exhaustive"):
        return THRESHOLDS["exhaustive"]
    return THRESHOLDS["semantica"]


def main() -> None:
    work, results = Path(sys.argv[1]), Path(sys.argv[2])
    runs_dir, data = work / "runs", work / "data"
    results.mkdir(parents=True, exist_ok=True)

    timing = {}
    for t in sorted(runs_dir.glob("*.timing.json")):
        name = t.name.removesuffix(".timing.json")
        rec = json.loads(t.read_text())
        log = runs_dir / f"{name}.log"
        if log.exists() and (m := MAXRSS.search(log.read_text())):
            rec["time_l_max_rss_mb"] = round(int(m.group(1)) / (1024 * 1024), 1)
        timing[name] = rec
    (results / "timing.json").write_text(json.dumps(timing, indent=1) + "\n")

    pool = load_pool([str(data / "pool_releases.jsonl.gz"), str(data / "pool_masters.jsonl.gz")])
    qctx_cache = {}
    for group, (qfile, names) in GROUPS.items():
        present = [n for n in names if (runs_dir / f"{n}.jsonl.gz").exists() and n in timing]
        if not present:
            continue
        if qfile not in qctx_cache:
            qctx_cache[qfile] = query_context(str(data / qfile), pool)
        runs = {n: load_jsonl(str(runs_dir / f"{n}.jsonl.gz")) for n in present}
        out = evaluate_runs(pool, qctx_cache[qfile], runs, {n: thresholds_for(n) for n in present})
        out["query_file"] = qfile
        (results / f"{group}.json").write_text(json.dumps(out, indent=1) + "\n")
        print(f"{group}: {', '.join(present)}", file=sys.stderr)

    stats = json.loads((data / "sample_stats.json").read_text())
    (results / "sample_stats.json").write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
