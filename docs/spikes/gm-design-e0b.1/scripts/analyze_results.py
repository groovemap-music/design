#!/usr/bin/env python3
"""Turn run_eval.py's per-query rank JSON into recall@1/10/50 tables, overall
and sliced by script / match_class / name_frequency, for one or more entity
kinds, plus the GO/NO-GO check (fused recall@10 - trgm recall@10 >= 5 points).
"""
from __future__ import annotations

import json
import sys

METHODS = ["trgm", "e5", "bge", "rrf_e5", "rrf_bge"]
KS = (1, 10, 50)


def recall_at_k(rows: list[dict], method: str, k: int) -> float | None:
    if not rows:
        return None
    hits = sum(1 for r in rows if r[f"rank_{method}"] is not None and r[f"rank_{method}"] <= k)
    return hits / len(rows)


def table_for(rows: list[dict], label: str) -> dict:
    out = {"slice": label, "n": len(rows), "metrics": {}}
    for m in METHODS:
        out["metrics"][m] = {f"recall@{k}": recall_at_k(rows, m, k) for k in KS}
    return out


def slices(rows: list[dict]) -> list[dict]:
    tables = [table_for(rows, "overall")]
    for key in ("script", "match_class", "name_frequency"):
        values = sorted({r[key] for r in rows})
        for v in values:
            sub = [r for r in rows if r[key] == v]
            tables.append(table_for(sub, f"{key}={v}"))
    return tables


def main() -> None:
    all_rows = []
    for path in sys.argv[1:]:
        with open(path) as f:
            data = json.load(f)
        all_rows.extend(data["results"])

    by_kind: dict[str, list[dict]] = {}
    for r in all_rows:
        by_kind.setdefault(r["kind"], []).append(r)

    report = {"by_kind": {}}
    for kind, rows in by_kind.items():
        report["by_kind"][kind] = slices(rows)

    print(json.dumps(report, indent=2))

    print("\n=== GO/NO-GO check: fused recall@10 - trgm recall@10, per kind (best of rrf_e5/rrf_bge) ===", file=sys.stderr)
    go = False
    for kind, rows in by_kind.items():
        trgm10 = recall_at_k(rows, "trgm", 10) or 0.0
        rrf_e5_10 = recall_at_k(rows, "rrf_e5", 10) or 0.0
        rrf_bge_10 = recall_at_k(rows, "rrf_bge", 10) or 0.0
        best_fused = max(rrf_e5_10, rrf_bge_10)
        delta = (best_fused - trgm10) * 100
        flag = "GO-eligible" if delta >= 5.0 else "no"
        print(
            f"{kind}: trgm@10={trgm10:.4f} rrf_e5@10={rrf_e5_10:.4f} rrf_bge@10={rrf_bge_10:.4f} "
            f"best_fused@10={best_fused:.4f} delta_pts={delta:.2f} -> {flag}",
            file=sys.stderr,
        )
        if delta >= 5.0:
            go = True
    print(f"OVERALL VERDICT: {'GO' if go else 'NO-GO'}", file=sys.stderr)


if __name__ == "__main__":
    main()
