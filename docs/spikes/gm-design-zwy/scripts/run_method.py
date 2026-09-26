#!/usr/bin/env python3
"""Run one candidate-generation method over a query batch and write its rankings.

Methods:
    baseline              keyed blocking + additive rule score (matching.py)
    semantica_rerank      the baseline's blocked candidates, scored by Semantica's
                          SimilarityCalculator and ranked by DuplicateDetector confidence
    semantica_native      DuplicateDetector.incremental_detect per query over the pool,
                          default thresholds: Semantica's own candidate set and ranking
    semantica_exhaustive  SimilarityCalculator over every (query, pool) pair, no
                          threshold: Semantica's ranking without its cut-off
    semantica_blocking    Semantica's own blocking strategies (legacy, blocking_v2,
                          blocking_v2+phonetic) over queries+pool: coverage and pair volume
                          only, no scoring

``--bounded-pool N --save-pool FILE`` materializes that pool once, so the scan methods
and their memory are measured on the bounded pool alone. ``--bounded-pool N`` replaces the full pool with a deterministic per-batch pool of at
most N records: every record any baseline rule (kind-blind) blocks for the batch, every
target and pooled master, then background records by id order. Methods that scan the
pool (native, exhaustive) are only affordable on such a pool; running the baseline with
the same flag gives the like-for-like comparison.

Every run writes rankings (gzip JSONL) and a timing record with ru_maxrss.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import resource
import sys
import time
from collections import Counter

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")

from matching import BaselineConfig, BaselineIndex, baseline_score, semantica_entity, view_of  # noqa: E402

TOP = 50
SCORE_CAP = 500


def iter_jsonl(path: str):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        for line in f:
            yield json.loads(line)


def load_jsonl(path: str) -> list[dict]:
    return list(iter_jsonl(path))


def peak_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024


def bounded_pool(queries, pool, cap: int) -> list:
    index = BaselineIndex(pool)
    cfg = BaselineConfig(kind_aware=False)
    keep: set[int] = set()
    targets = {q.extra["target"] for q in queries}
    for q in queries:
        ids, _ = index.block(q, cfg)
        keep |= ids
    for i, v in enumerate(pool):
        if v.native_id in targets and v.entity_kind == "release":
            keep.add(i)
    masters = {pool[i].master_id for i in keep if pool[i].master_id}
    for i, v in enumerate(pool):
        if v.entity_kind == "master" and v.native_id in masters:
            keep.add(i)
    if len(keep) < cap:
        background = sorted(
            (i for i, v in enumerate(pool) if i not in keep and "background" in v.extra.get("reasons", ())),
            key=lambda i: int(pool[i].native_id),
        )
        keep.update(background[: cap - len(keep)])
    return [pool[i] for i in sorted(keep)]


def rank_record(q, scored: list[tuple[float, float, str]], n_candidates: int, diag: dict | None = None) -> dict:
    """scored: (primary, secondary, key) — sorted descending by (primary, secondary),
    ties broken by key so the ranking is deterministic."""
    scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
    target_key = f"discogs:release:{q.extra['target']}"
    rank = next((i + 1 for i, t in enumerate(scored) if t[2] == target_key), None)
    rec = {
        "q": q.native_id,
        "target": q.extra["target"],
        "n_candidates": n_candidates,
        "target_rank": rank,
        "target_score": scored[rank - 1][0] if rank else None,
        "top": [[t[2], round(t[0], 4), round(t[1], 4)] for t in scored[:TOP]],
        "scores": [round(t[0], 4) for t in scored[:SCORE_CAP]],
    }
    if diag:
        rec["diag"] = diag
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("method")
    ap.add_argument("--queries", required=True)
    ap.add_argument("--pool", required=True, nargs="+")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--bounded-pool", type=int, default=0)
    ap.add_argument("--drop", default="", help="comma list of fields to ablate")
    ap.add_argument("--kind-blind", action="store_true")
    ap.add_argument("--raw", action="store_true", help="Semantica gets raw strings, not GrooveMap-normalized")
    ap.add_argument("--save-pool", help="write the (bounded) pool's source records here and exit")
    ap.add_argument("--out")
    ap.add_argument("--timing-out")
    args = ap.parse_args()
    drop = frozenset(x for x in args.drop.split(",") if x)

    t0 = time.perf_counter()
    qrecs = load_jsonl(args.queries)
    qrecs = qrecs[args.offset : args.offset + args.limit] if args.limit else qrecs[args.offset :]
    queries = []
    for r in qrecs:
        v = view_of(r)
        v.extra["target"] = r["target_discogs_id"]
        queries.append(v)
    pool = []
    for path in args.pool:
        for r in iter_jsonl(path):
            v = view_of(r, keep_raw=args.raw)
            v.extra["reasons"] = tuple(r.get("kept_reasons") or ())
            pool.append(v)
    t_load = time.perf_counter() - t0
    if args.bounded_pool:
        pool = bounded_pool(queries, pool, args.bounded_pool)
    t_pool = time.perf_counter() - t0 - t_load
    if args.save_pool:
        keep = {v.key for v in pool}
        with gzip.open(args.save_pool, "wt") as f:
            for path in args.pool:
                for r in iter_jsonl(path):
                    if f"{r['source']}:{r['entity_kind']}:{r['native_id']}" in keep:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"saved {len(keep)} pool records to {args.save_pool}", file=sys.stderr)
        return
    rss_after_load = peak_rss_mb()

    t1 = time.perf_counter()
    records: list[dict] = []
    extra_timing: dict = {}
    if args.method in ("baseline", "semantica_rerank"):
        index = BaselineIndex(pool)
        cfg = BaselineConfig(drop=drop, kind_aware=not args.kind_blind)
        extra_timing["index_seconds"] = round(time.perf_counter() - t1, 3)
        if args.method == "semantica_rerank":
            from semantica.deduplication import DuplicateDetector

            det = DuplicateDetector()
            det.progress_tracker.enabled = False
            calc = det.similarity_calculator
            pool_ents: dict[int, dict] = {}
        for q in queries:
            ids, diag = index.block(q, cfg)
            if args.method == "baseline":
                scored = [(baseline_score(q, pool[i], drop), 0.0, pool[i].key) for i in ids]
            else:
                qe = semantica_entity(q, drop, normalized=not args.raw, with_type=not args.kind_blind)
                scored = []
                for i in ids:
                    pe = pool_ents.get(i)
                    if pe is None:
                        pe = pool_ents[i] = semantica_entity(pool[i], drop, normalized=not args.raw,
                                                             with_type=not args.kind_blind)
                    sim = calc.calculate_similarity(qe, pe, track=False).score
                    cand = det._create_duplicate_candidate(qe, pe, sim)
                    if "type_mismatch" in cand.reasons:
                        continue
                    scored.append((cand.confidence, sim, pool[i].key))
            records.append(rank_record(q, scored, len(scored), diag))
    elif args.method in ("semantica_native", "semantica_exhaustive"):
        from semantica.deduplication import DuplicateDetector

        det = DuplicateDetector()
        det.progress_tracker.enabled = False
        calc = det.similarity_calculator
        pool_ents = [semantica_entity(v, drop, normalized=not args.raw, with_type=not args.kind_blind) for v in pool]
        by_id = {pe["id"]: pe for pe in pool_ents}
        extra_timing["encode_seconds"] = round(time.perf_counter() - t1, 3)
        for n, q in enumerate(queries):
            qe = semantica_entity(q, drop, normalized=not args.raw, with_type=not args.kind_blind)
            if args.method == "semantica_native":
                cands = det.incremental_detect([qe], pool_ents)
                scored = [(c.confidence, c.similarity_score, c.entity2["id"]) for c in cands]
                records.append(rank_record(q, scored, len(scored)))
            else:
                scored = []
                above = Counter()
                for pe in pool_ents:
                    if pe.get("type") and qe.get("type") and pe["type"] != qe["type"]:
                        continue
                    s = calc.calculate_similarity(qe, pe, track=False).score
                    for t in (0.5, 0.6, 0.7, 0.8, 0.9):
                        if s >= t:
                            above[t] += 1
                    scored.append((s, 0.0, pe["id"]))
                rec = rank_record(q, scored, len(scored))
                # Detector confidence for the head of the ranking only (it adds boosts
                # for exact name, equal properties, and equal type on top of similarity).
                rec["top"] = [
                    [key, sim, round(det._create_duplicate_candidate(qe, by_id[key], sim).confidence, 4)]
                    for key, sim, _ in rec["top"]
                ]
                rec["above"] = {str(k): v for k, v in above.items()}
                records.append(rec)
            if (n + 1) % 50 == 0:
                el = time.perf_counter() - t1
                print(f"...{n + 1}/{len(queries)} queries {el:.0f}s", file=sys.stderr, flush=True)
    elif args.method == "semantica_blocking":
        from semantica.deduplication import SimilarityCalculator

        calc = SimilarityCalculator()
        ents = [semantica_entity(v, drop, normalized=not args.raw) for v in queries] + \
               [semantica_entity(v, drop, normalized=not args.raw) for v in pool]
        processed = []
        for e in ents:
            p = dict(e)
            p["_lower_name"] = (p.get("name") or "").lower().strip()
            processed.append(p)
        nq = len(queries)
        pos = {e["id"]: i for i, e in enumerate(ents)}
        summary = {}
        for label, opts in (
            ("legacy", {"candidate_strategy": "legacy"}),
            ("blocking_v2", {"candidate_strategy": "blocking_v2"}),
            ("blocking_v2_phonetic", {"candidate_strategy": "blocking_v2", "enable_phonetic_blocking": True}),
        ):
            ts = time.perf_counter()
            blocks = calc._build_block_indexes(processed, opts)
            member: dict[int, set[str]] = {}
            total_pairs = cross_pairs = 0
            for k, idx in blocks.items():
                n_all = len(idx)
                n_q = sum(1 for i in idx if i < nq)
                total_pairs += n_all * (n_all - 1) // 2
                cross_pairs += n_q * (n_all - n_q)
                for i in idx:
                    member.setdefault(i, set()).add(k)
            covered = 0
            for qi, q in enumerate(queries):
                ti = pos.get(f"discogs:release:{q.extra['target']}")
                if ti is not None and member.get(qi, set()) & member.get(ti, set()):
                    covered += 1
            summary[label] = {
                "blocks": len(blocks),
                "total_pairs": total_pairs,
                "cross_source_pairs": cross_pairs,
                "coverage": covered / len(queries),
                "seconds": round(time.perf_counter() - ts, 3),
            }
        extra_timing["blocking"] = summary
    else:
        raise SystemExit(f"unknown method {args.method}")
    t_match = time.perf_counter() - t1

    with gzip.open(args.out, "wt") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    timing = {
        "method": args.method,
        "queries": len(queries),
        "pool": len(pool),
        "pool_kinds": dict(Counter(v.entity_kind for v in pool)),
        "bounded_pool": args.bounded_pool,
        "drop": sorted(drop),
        "kind_blind": args.kind_blind,
        "raw": args.raw,
        "load_seconds": round(t_load, 3),
        "pool_build_seconds": round(t_pool, 3),
        "match_seconds": round(t_match, 3),
        "match_ms_per_query": round(1000 * t_match / max(1, len(queries)), 3),
        "rss_after_load_mb": round(rss_after_load, 1),
        "peak_rss_mb": round(peak_rss_mb(), 1),
        **extra_timing,
    }
    with open(args.timing_out, "w") as f:
        json.dump(timing, f, indent=2)
    print(json.dumps(timing), file=sys.stderr)


if __name__ == "__main__":
    main()
