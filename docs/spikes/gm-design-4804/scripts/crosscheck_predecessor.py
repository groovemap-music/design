#!/usr/bin/env python3
"""Cross-check this harness's genre x decade release counts against the predecessor's
stored ``insights.genre_trends`` snapshot (the same Cypher catalog-api runs today).

Input CSV (kept in the cache, never committed): genre,decade,release_count,computed_on,
as written by ``predecessor_costs.sh --genre-trends``. Output: aggregate agreement only.

Usage:
    python crosscheck_predecessor.py aggregates_<dump>.npz predecessor_genre_trends.csv OUT.json
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from aggregate import YEAR0, load_aggregates


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("aggregates", type=Path)
    ap.add_argument("csv", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    agg = load_aggregates(args.aggregates)
    mine: dict[tuple[str, int], int] = {}
    years = np.arange(agg["genre_year_rel"].shape[1]) + YEAR0
    for gi, g in enumerate(agg["genres"]):
        for y, n in zip(years, agg["genre_year_rel"][gi]):
            if n:
                key = (g, int(y) // 10 * 10)
                mine[key] = mine.get(key, 0) + int(n)
    theirs: dict[tuple[str, int], int] = {}
    computed = set()
    with args.csv.open() as f:
        for genre, decade, count, day in csv.reader(f):
            theirs[(genre, int(decade))] = int(count)
            computed.add(day)
    known = set(agg["genres"])
    shared = sorted(set(mine) & set(theirs))
    rel = np.array([theirs[k] / mine[k] - 1 for k in shared])
    big = np.array([mine[k] >= 10000 for k in shared])
    out = {
        "predecessor_snapshot_days": sorted(computed),
        "cells_harness": len(mine),
        "cells_predecessor": len(theirs),
        "cells_shared": len(shared),
        "predecessor_cells_with_unknown_genre": sum(1 for g, _ in theirs if g not in known),
        "total_harness": int(sum(mine.values())),
        "total_predecessor_known_genres": int(sum(v for (g, _), v in theirs.items() if g in known)),
        "relative_diff_median": round(float(np.median(rel)), 4),
        "relative_diff_abs_p90_cells_ge_10k": round(float(np.percentile(np.abs(rel[big]), 90)), 4),
    }
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out))


if __name__ == "__main__":
    main()
