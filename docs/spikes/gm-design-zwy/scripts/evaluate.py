#!/usr/bin/env python3
"""Score method rankings: candidate coverage, ranking quality, review burden, and the
per-class hard-negative breakdown.

Coverage (is the correct Discogs release anywhere in the method's candidate set) is
reported separately from ranking quality (recall@1/5/10 and MRR over all queries,
counting a missing target as rank infinity). Review burden is the queue a person
would see at a score threshold: candidates per query, and a confusion table of what
the queue contains.

Usage:
    python3 evaluate.py --queries queries_test.jsonl --pool pool_releases.jsonl.gz pool_masters.jsonl.gz \
        --run baseline=runs/baseline.jsonl.gz --thresholds baseline=6,8,10,12 --out metrics.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import statistics
from collections import Counter, defaultdict

from matching import View, view_of
from normalize import script_bucket

CLASSES = (
    "shared_barcode",
    "near_identical_title",
    "sibling_same_format",
    "sibling_diff_format",
    "release_vs_master",
    "namesake_artist",
)


def iter_jsonl(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        for line in f:
            yield json.loads(line)


def load_jsonl(path: str) -> list[dict]:
    return list(iter_jsonl(path))


def _artist_map(t: View) -> dict[str, set]:
    out: dict[str, set] = defaultdict(set)
    for name, aid in t.extra.get("artist_pairs", ()):
        out[name].add(aid)
    return out


def classify(c: View, t: View, t_artists: dict[str, set] | None = None) -> set[str]:
    """Hard-negative classes a non-target candidate falls in, relative to the target."""
    out: set[str] = set()
    if c.entity_kind == "master":
        out.add("release_vs_master")
        return out
    if c.native_id == t.native_id:
        return out
    if c.barcodes & t.barcodes:
        out.add("shared_barcode")
    same_master = bool(t.master_id) and c.master_id == t.master_id
    if same_master:
        if (c.formats & t.formats) or (not c.formats and not t.formats):
            out.add("sibling_same_format")
        else:
            out.add("sibling_diff_format")
    elif c.title and c.title == t.title:
        out.add("near_identical_title")
    t_ids = t_artists if t_artists is not None else _artist_map(t)
    for name, aid in c.extra.get("artist_pairs", ()):
        if name in t_ids and name != "various" and aid not in t_ids[name]:
            out.add("namesake_artist")
            break
    return out


def pct(x: float) -> float:
    return round(100.0 * x, 2)


def summarize(values: list[int]) -> dict:
    if not values:
        return {"mean": 0, "median": 0, "p95": 0, "max": 0}
    s = sorted(values)
    return {
        "mean": round(statistics.fmean(s), 2),
        "median": s[len(s) // 2],
        "p95": s[min(len(s) - 1, int(0.95 * len(s)))],
        "max": s[-1],
    }


def evaluate_run(rows: list[dict], views: dict[str, View], present: dict[str, dict[str, int]],
                 thresholds: list[float], qmeta: dict[str, dict]) -> dict:
    n = len(rows)
    ranks = [r["target_rank"] for r in rows]
    res: dict = {"n": n}
    res["coverage_pct"] = pct(sum(1 for x in ranks if x) / n)
    for k in (1, 5, 10):
        res[f"recall@{k}_pct"] = pct(sum(1 for x in ranks if x and x <= k) / n)
    res["mrr"] = round(sum(1.0 / x for x in ranks if x) / n, 4)
    res["candidates_per_query"] = summarize([r["n_candidates"] for r in rows])
    res["zero_candidate_queries"] = sum(1 for r in rows if r["n_candidates"] == 0)
    # Ties are broken by id order, which is arbitrary; count how much recall@1 rests on it.
    res["tied_top_queries"] = sum(1 for r in rows if len(r["top"]) > 1 and r["top"][0][1] == r["top"][1][1])
    res["target_tied_with_wrong_top"] = sum(
        1 for r in rows if r["target_rank"] and r["target_rank"] > 1 and r["target_score"] == r["top"][0][1]
    )

    review = {}
    for t in thresholds:
        queue, conf = [], Counter()
        for r in rows:
            q = sum(1 for s in r["scores"] if s >= t)
            queue.append(q)
            tp = r["target_score"] is not None and r["target_score"] >= t
            if tp and r["target_rank"] == 1:
                conf["top_is_correct"] += 1
            elif tp:
                conf["correct_in_queue_not_top"] += 1
            elif q > 0:
                conf["only_wrong_candidates"] += 1
            else:
                conf["empty_queue"] += 1
        fp = sum(queue) - conf["top_is_correct"] - conf["correct_in_queue_not_top"]
        nonempty = n - conf["empty_queue"]
        review[str(t)] = {
            "queue_per_query": summarize(queue),
            "false_positives_per_query": round(fp / n, 3),
            "precision_of_queue_pct": pct((sum(queue) - fp) / sum(queue)) if sum(queue) else None,
            "top1_precision_nonempty_pct": pct(conf["top_is_correct"] / nonempty) if nonempty else None,
            "confusion": {k: conf[k] for k in ("top_is_correct", "correct_in_queue_not_top",
                                                "only_wrong_candidates", "empty_queue")},
        }
    res["review"] = review

    hard = {}
    for cls in CLASSES:
        hard[cls] = {"queries_with_class_in_pool": 0, "queries_with_class_in_candidates": 0,
                     "outranks_target": 0, "is_rank1": 0}
    for r in rows:
        t = views.get(f"discogs:release:{r['target']}")
        pres = present.get(r["q"], {})
        for cls in CLASSES:
            if pres.get(cls):
                hard[cls]["queries_with_class_in_pool"] += 1
        if t is None:
            continue
        seen_in, above, rank1 = set(), set(), set()
        cutoff = r["target_rank"] or len(r["top"]) + 1
        for i, (key, *_s) in enumerate(r["top"]):
            c = views.get(key)
            if c is None:
                continue
            classes = classify(c, t)
            seen_in |= classes
            if i + 1 < cutoff:
                above |= classes
            if i == 0:
                rank1 |= classes
        for cls in seen_in:
            hard[cls]["queries_with_class_in_candidates"] += 1
        for cls in above:
            hard[cls]["outranks_target"] += 1
        for cls in rank1:
            hard[cls]["is_rank1"] += 1
    res["hard_negatives"] = hard

    slices = defaultdict(list)
    for r in rows:
        m = qmeta[r["q"]]
        slices[f"script={m['script']}"].append(r)
        slices[f"barcode_on_query={'yes' if m['has_barcode'] else 'no'}"].append(r)
        slices[f"catno_on_query={'yes' if m['has_catno'] else 'no'}"].append(r)
    res["slices"] = {
        name: {
            "n": len(rs),
            "coverage_pct": pct(sum(1 for r in rs if r["target_rank"]) / len(rs)),
            "recall@1_pct": pct(sum(1 for r in rs if r["target_rank"] == 1) / len(rs)),
            "recall@10_pct": pct(sum(1 for r in rs if r["target_rank"] and r["target_rank"] <= 10) / len(rs)),
            "mrr": round(sum(1.0 / r["target_rank"] for r in rs if r["target_rank"]) / len(rs), 4),
        }
        for name, rs in sorted(slices.items())
    }
    return res


def load_pool(pool_paths: list[str]) -> dict:
    views: dict[str, View] = {}
    idx = {"barcode": defaultdict(list), "master": defaultdict(list), "title": defaultdict(list)}
    for path in pool_paths:
        for rec in iter_jsonl(path):
            v = view_of(rec, keep_raw=False)
            views[v.key] = v
            for b in v.barcodes:
                idx["barcode"][b].append(v.key)
            if v.master_id:
                idx["master"][v.master_id].append(v.key)
            if v.title:
                idx["title"][v.title].append(v.key)
    return {"views": views, "idx": idx}


def query_context(queries_path: str, pool: dict) -> dict:
    """Per-query metadata and the method-independent hard-negative census: how many
    pool records of each class exist around each query's target."""
    views, idx = pool["views"], pool["idx"]
    qrecs = load_jsonl(queries_path)
    qmeta = {
        r["native_id"]: {
            "script": script_bucket(r["title"]),
            "has_barcode": bool(r.get("barcode")),
            "has_catno": any(li.get("catno") for li in r.get("labels") or []),
        }
        for r in qrecs
    }
    present: dict[str, dict[str, int]] = {}
    missing = set()
    for r in qrecs:
        t = views.get(f"discogs:release:{r['target_discogs_id']}")
        if t is None:
            missing.add(r["native_id"])
            continue
        # The census neighbourhood: records sharing the target's barcode, master, or
        # title key, plus masters. A namesake-artist release counts only when it is in
        # that neighbourhood, i.e. when it could plausibly be confused with the target.
        near = set()
        for b in t.barcodes:
            near.update(idx["barcode"][b])
        if t.master_id:
            near.update(idx["master"][t.master_id])
        near.update(idx["title"][t.title])
        t_artists = _artist_map(t)
        counts = Counter()
        for key in near:
            if key in views:
                for cls in classify(views[key], t, t_artists):
                    counts[cls] += 1
        present[r["native_id"]] = dict(counts)
    return {"qmeta": qmeta, "present": present, "missing": missing, "n": len(qrecs)}


def evaluate_runs(pool: dict, qctx: dict, runs: dict[str, list[dict]], thresholds: dict) -> dict:
    out = {"runs": {}}
    for name, rows in runs.items():
        sub = {r["q"] for r in rows}
        out["runs"][name] = evaluate_run(rows, pool["views"], qctx["present"], thresholds.get(name) or (
            [6, 8, 10, 12] if name.startswith("baseline") else [0.7, 0.8, 0.9, 0.95]), qctx["qmeta"])
        out["runs"][name]["target_missing_from_dump"] = len(sub & qctx["missing"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", required=True)
    ap.add_argument("--pool", nargs="+", required=True)
    ap.add_argument("--run", action="append", required=True, help="name=path")
    ap.add_argument("--thresholds", action="append", default=[], help="name=t1,t2 (default by method family)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    runs = {}
    for spec in args.run:
        name, path = spec.split("=", 1)
        runs[name] = load_jsonl(path)
    thr = {}
    for spec in args.thresholds:
        name, values = spec.split("=", 1)
        thr[name] = [float(x) for x in values.split(",")]
    pool = load_pool(args.pool)
    qctx = query_context(args.queries, pool)
    out = evaluate_runs(pool, qctx, runs, thr)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    for name, res in out["runs"].items():
        print(f"{name}: n={res['n']} cov={res['coverage_pct']} r@1={res['recall@1_pct']} "
              f"r@5={res['recall@5_pct']} r@10={res['recall@10_pct']} mrr={res['mrr']} "
              f"cands={res['candidates_per_query']}")


if __name__ == "__main__":
    main()
