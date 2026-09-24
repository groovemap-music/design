# SPDX-License-Identifier: MIT
"""Score similar-artist retrieval under the time split, heuristics-2026-09 vs graph embeddings.

Task. For a query artist, rank other artists; score the ranking against the artists the
query actually worked with after the cut. This is the harness's time-split protocol moved
from "collector -> later acquisitions" (which needs private collection data a Discogs dump
does not carry) to "artist -> later collaborators", which the dump does carry:

* **relevant(A)**: artists B != A that appear on a post-cut release on which A is a main
  artist, as a co-main artist, a kept-role credit, or a track artist; restricted to the
  retrievable catalog (artists with at least one pre-cut main-artist release in the subset,
  i.e. an ``Artist`` node the endpoint could return).
* **novel(A)**: relevant(A) minus every artist A already shared a pre-cut release with; the
  rankings are filtered of the same pre-cut neighbours before cutting at k.
* **queries**: seed artists with >= MIN_ARTIST_RELEASES pre-cut main-artist releases and a
  non-empty relevant set, split by a fixed hash into dev (30%, used for every
  hyperparameter and fusion-weight choice) and test (70%, the reported numbers).

Metrics are the catalog-api primitives (``baseline_port``), macro-averaged over queries,
at k = 10 and 20 (the endpoint returns at most 20, so the harness's k = 25 is not usable).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

THREADS = int(os.environ.get("SPIKE_THREADS", "6"))
os.environ.setdefault("OMP_NUM_THREADS", str(THREADS))

import numpy as np  # noqa: E402
import scipy.sparse as sp  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

import baseline_port as bp  # noqa: E402
from build_subset import unit_hash  # noqa: E402
from catalog import Heuristic, load_subset  # noqa: E402

K = 20
FAMILIES = ["vinyl", "shellac", "grooved_other", "tape", "optical", "digital", "video", "other"]
DEGREE_BUCKETS = [("3-5", 6), ("6-15", 16), ("16-50", 51), ("51+", 1 << 30)]
ALPHAS = [round(x * 0.1, 1) for x in range(1, 10)]
DEV_SHARE = 0.3


def dominant_family(cat, artists: np.ndarray) -> list[str]:
    by_t = cat.by.T.tocsr()
    bits = np.stack([((cat.rel_fam >> i) & 1).astype(np.int32) for i in range(len(FAMILIES))], axis=1)
    counts = by_t[artists] @ bits
    out = []
    for row in np.asarray(counts):
        out.append(FAMILIES[int(np.argmax(row))] if row.max() > 0 else "none")
    return out


def ranking_block(rankings: list[list[int]], relevant: list[set[int]]) -> dict[str, float]:
    block = {}
    for k in (10, 20):
        block[f"precision_at_{k}"] = bp._mean([bp.precision_at_k(r, rel, k) for r, rel in zip(rankings, relevant, strict=True)])
        block[f"recall_at_{k}"] = bp._mean([bp.recall_at_k(r, rel, k) for r, rel in zip(rankings, relevant, strict=True)])
    block["hit_rate_at_20"] = bp._mean([1.0 if bp.hits_at_k(r, rel, 20) else 0.0 for r, rel in zip(rankings, relevant, strict=True)])
    return block


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("subset", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--emb", action="append", default=[], help="name=path.npy[,path_seed2.npy]")
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--max-queries", type=int, default=0)
    args = parser.parse_args()
    t0 = time.time()

    full, pre_mask, seeds = load_subset(args.subset)
    pre = full.restrict(pre_mask)
    post = full.restrict(~pre_mask)
    n = full.n_artists
    key = full.artist_ids.astype(np.int64)
    heur = Heuristic(pre, key)
    universe = heur.release_count > 0

    def binary(m: sp.spmatrix) -> sp.csr_matrix:
        m = m.tocsr()
        m.data[:] = 1
        return m

    post_any = binary(post.by + post.credits + post.track)
    gt = binary(post.by.T.astype(np.int32) @ post_any.astype(np.int32))
    pre_any = binary(pre.by + pre.credits + pre.track)
    pre_links = binary(pre_any.T.astype(np.int32) @ pre_any.astype(np.int32))

    queries = seeds[heur.release_count[seeds] >= bp.MIN_ARTIST_RELEASES]
    relevant, novel, known = {}, {}, {}
    gt_pairs_total = gt_pairs_in_universe = 0
    for a in queries:
        row = gt.indices[gt.indptr[a] : gt.indptr[a + 1]]
        row = row[row != a]
        gt_pairs_total += len(row)
        row = row[universe[row]]
        gt_pairs_in_universe += len(row)
        if len(row) == 0:
            continue
        relevant[a] = set(row.tolist())
        kn = pre_links.indices[pre_links.indptr[a] : pre_links.indptr[a + 1]]
        known[a] = set(kn.tolist()) - {a}
        novel[a] = relevant[a] - known[a]
    qs = np.array(sorted(relevant), dtype=np.int64)
    if args.max_queries:
        qs = qs[: args.max_queries]
    dev = unit_hash(full.artist_ids[qs], salt=7) < DEV_SHARE
    families = dominant_family(pre, qs)
    print(f"{len(qs)} queries ({dev.sum()} dev), {time.time() - t0:.0f}s", flush=True)

    embs: dict[str, list[np.ndarray]] = {}
    for spec in args.emb:
        name, paths = spec.split("=", 1)
        mats = []
        for path in paths.split(","):
            # Only retrievable-catalog rows are ever scored (queries are among them).
            e = np.load(path, mmap_mode="r")[np.flatnonzero(universe)].astype(np.float32)
            e /= np.maximum(np.linalg.norm(e, axis=1, keepdims=True), 1e-12)
            mats.append(e)
        embs[name] = mats

    import torch

    torch.set_num_threads(THREADS)
    u_idx = np.flatnonzero(universe)
    pos = np.full(n, -1, dtype=np.int64)
    pos[u_idx] = np.arange(len(u_idx))
    # Deterministic tie-break: lower Discogs id first. 1e-13 per rank stays far below any
    # score difference the heuristic can express (it rounds to 1e-4).
    tiebreak = np.argsort(np.argsort(key[u_idx])).astype(np.float64) * 1e-13
    extra = 300

    def rank_block(s_u: np.ndarray, batch: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        s = s_u.astype(np.float64) - tiebreak[None, :]
        p = pos[batch]
        rows = np.flatnonzero(p >= 0)
        s[rows, p[rows]] = -np.inf
        kk = min(K + extra, s.shape[1])
        top = torch.topk(torch.from_numpy(s), kk, dim=1).indices.numpy()
        plain = u_idx[top[:, :K]]
        nov = np.full((len(batch), K), -1, dtype=np.int64)
        for i, a in enumerate(batch):
            kn = known[int(a)]
            picked = [x for x in u_idx[top[i]].tolist() if x not in kn][:K]
            if len(picked) < K:
                row = s[i].copy()
                kn_pos = pos[list(kn)] if kn else np.array([], dtype=np.int64)
                row[kn_pos[kn_pos >= 0]] = -np.inf
                picked = u_idx[np.argsort(-row, kind="stable")[:K]].tolist()
            nov[i, : len(picked)] = picked
        return plain, nov

    rankings: dict[str, np.ndarray] = {}
    novel_rankings: dict[str, np.ndarray] = {}
    stability: dict[str, list[tuple[float, float]]] = {name: [] for name, m in embs.items() if len(m) > 1}

    def put(name: str, rows: np.ndarray, block: tuple[np.ndarray, np.ndarray]) -> None:
        for store, value in zip((rankings, novel_rankings), block, strict=True):
            if name not in store:
                store[name] = np.full((len(qs), K), -1, dtype=np.int64)
            store[name][rows] = value

    # The production path: candidate generation + weighted cosine, at most 20 results.
    prod = np.full((len(qs), K), -1, dtype=np.int64)
    for i, a in enumerate(qs):
        result = heur.similar(int(a))
        prod[i, : len(result)] = [row["artist_id"] for row in result]
    print(f"heuristic production path done, {time.time() - t0:.0f}s", flush=True)

    split_idx = {"dev": np.flatnonzero(dev), "test": np.flatnonzero(~dev)}
    rel_list = [relevant[a] for a in qs]
    nov_list = [novel[a] for a in qs]
    selected_alpha: dict[str, float] = {}
    dev_alpha_scores: dict[str, dict[float, float]] = {}
    emb_u = embs

    for phase in ("dev", "test"):
        idx_all = split_idx[phase]
        for start in range(0, len(idx_all), args.batch):
            rows = idx_all[start : start + args.batch]
            batch = qs[rows]
            h = heur.scores(batch)[:, u_idx]
            put("heuristic_all_artists", rows, rank_block(h, batch))
            for name, mats in embs.items():
                s = emb_u[name][0][pos[batch]] @ emb_u[name][0].T
                put(name, rows, rank_block(s, batch))
                for alpha in (ALPHAS if phase == "dev" else [selected_alpha[name]]):
                    put(f"fused[{name}]@{alpha}", rows, rank_block(alpha * s + (1 - alpha) * h, batch))
                if len(mats) > 1 and phase == "test":
                    s2 = emb_u[name][1][pos[batch]] @ emb_u[name][1].T
                    t1, _ = rank_block(s, batch)
                    t2, _ = rank_block(s2, batch)
                    for i in range(len(batch)):
                        a10, b10 = set(t1[i, :10].tolist()), set(t2[i, :10].tolist())
                        # Rank correlation of the two runs' scores over the whole retrievable
                        # catalog (the harness's rank_stability, per query). scipy's spearmanr
                        # is the same average-rank Pearson as bp.spearman, fast enough for
                        # 10^5 items; it is sampled on the first 300 test queries.
                        rho = float(spearmanr(s[i], s2[i]).statistic) if len(stability[name]) < 300 else float("nan")
                        stability[name].append((len(a10 & b10) / len(a10 | b10), rho))
            if (start // args.batch) % 20 == 0:
                print(f"{phase} batch {start}/{len(idx_all)} {time.time() - t0:.0f}s", flush=True)
        if phase == "dev":
            # Pick each fusion weight on dev only; test sees only the chosen weight.
            for name in embs:
                scores = {}
                for alpha in ALPHAS:
                    mat = rankings[f"fused[{name}]@{alpha}"]
                    scores[alpha] = bp._mean([bp.recall_at_k([x for x in mat[i].tolist() if x >= 0], rel_list[i], 10) for i in idx_all])
                dev_alpha_scores[name] = scores
                selected_alpha[name] = max(ALPHAS, key=lambda alpha: (scores[alpha], -alpha))

    rankings["heuristic"] = prod
    # Production path under the novel view: drop known neighbours from its (<= 20) list.
    novel_rankings["heuristic"] = np.array(
        [([x for x in row.tolist() if x >= 0 and x not in known[int(a)]] + [-1] * K)[:K] for a, row in zip(qs, prod, strict=True)]
    )

    def as_lists(mat: np.ndarray, idx: np.ndarray) -> list[list[int]]:
        return [[x for x in mat[i].tolist() if x >= 0] for i in idx]

    catalog_size = int(universe.sum())
    art_family = dict(zip(np.flatnonzero(universe).tolist(), dominant_family(pre, np.flatnonzero(universe)), strict=True))

    def evaluate(name: str, idx: np.ndarray) -> dict:
        r = as_lists(rankings[name], idx)
        rel = [rel_list[i] for i in idx]
        nov_idx = [i for i in idx if nov_list[i]]
        res = {"queries": len(idx), "overall": ranking_block(r, rel)}
        res["novel"] = {"queries": len(nov_idx), **ranking_block(as_lists(novel_rankings[name], np.array(nov_idx)), [nov_list[i] for i in nov_idx])}
        res["coverage"] = {"catalog_artists": catalog_size, "catalogue_coverage": bp.catalogue_coverage(r, catalog_size)}
        fam = {}
        total_recommended = sum(len(x) for x in r)
        for family in [*FAMILIES, "none"]:
            members = [j for j, i in enumerate(idx) if families[i] == family]
            if not members:
                continue
            block = ranking_block([r[j] for j in members], [rel[j] for j in members])
            recommended = sum(1 for x in r for y in x if art_family.get(y) == family)
            fam[family] = {"queries": len(members), "recall_at_10": block["recall_at_10"], "recall_at_20": block["recall_at_20"],
                           "recommended_share": recommended / total_recommended if total_recommended else 0.0}
        res["by_query_family"] = fam
        deg = {}
        counts = heur.release_count[qs[idx]]
        lower = 3
        for label, upper in DEGREE_BUCKETS:
            members = [j for j in range(len(idx)) if lower <= counts[j] < upper]
            lower = upper
            if members:
                deg[label] = {"queries": len(members), **ranking_block([r[j] for j in members], [rel[j] for j in members])}
        res["by_query_release_count"] = deg
        return res

    results = {"split": {}, "fusion_selection": {}, "stability": {}}
    names = sorted(rankings)
    for split, idx in split_idx.items():
        present = [name for name in names if (rankings[name][idx] >= 0).any()]
        results["split"][split] = {name: evaluate(name, idx) for name in present}
    for name in embs:
        results["fusion_selection"][name] = {"alpha": selected_alpha[name], "dev_recall_at_10_by_alpha": dev_alpha_scores[name]}

    # Paired bootstraps of recall@10 on test, against the production heuristic and against
    # the same weights scored over every artist; both the all-collaborator and novel views.
    rng = np.random.default_rng(0)
    test = split_idx["test"]
    test_novel = np.array([i for i in test if nov_list[i]])

    def per_query(name: str, idx: np.ndarray, novel_view: bool) -> np.ndarray:
        mat = novel_rankings[name] if novel_view else rankings[name]
        rel = nov_list if novel_view else rel_list
        return np.array([bp.recall_at_k(x, rel[i], 10) for x, i in zip(as_lists(mat, idx), idx, strict=True)])

    boots = {False: rng.integers(0, len(test), size=(1000, len(test))), True: rng.integers(0, len(test_novel), size=(1000, len(test_novel)))}
    results["bootstrap_test"] = {}
    for view, idx in ((False, test), (True, test_novel)):
        refs = {ref: per_query(ref, idx, view) for ref in ("heuristic", "heuristic_all_artists")}
        for name in results["split"]["test"]:
            other = per_query(name, idx, view)
            entry = {"recall_at_10": float(other.mean())}
            for ref, base in refs.items():
                gain = other[boots[view]].mean(axis=1) / base[boots[view]].mean(axis=1) - 1.0
                entry[f"vs_{ref}"] = {
                    "reference_recall_at_10": float(base.mean()),
                    "relative_gain": float(other.mean() / base.mean() - 1.0),
                    "relative_gain_ci95": [float(np.percentile(gain, 2.5)), float(np.percentile(gain, 97.5))],
                }
            results["bootstrap_test"].setdefault("novel" if view else "all", {})[name] = entry

    # The "best embedding or fused method" is chosen on dev recall@10, never on test.
    candidates = [name for name in results["split"]["dev"] if name not in {"heuristic", "heuristic_all_artists"}
                  and (not name.startswith("fused[") or name == f"fused[{name[6:name.index(']')]}]@{selected_alpha[name[6:name.index(']')]]}")]
    best = max(candidates, key=lambda name: results["split"]["dev"][name]["overall"]["recall_at_10"])
    gate = {"selected_on_dev": best, "dev_recall_at_10": results["split"]["dev"][best]["overall"]["recall_at_10"], "families": {}}
    for ref in ("heuristic", "heuristic_all_artists"):
        fams = {}
        for family, block in results["split"]["test"][best]["by_query_family"].items():
            base_block = results["split"]["test"][ref]["by_query_family"][family]
            fams[family] = {"queries": block["queries"], "best_recall_at_10": block["recall_at_10"],
                            "reference_recall_at_10": base_block["recall_at_10"],
                            "delta_points": 100.0 * (block["recall_at_10"] - base_block["recall_at_10"])}
        gate["families"][ref] = fams
        gain = results["bootstrap_test"]["all"][best][f"vs_{ref}"]
        gate[f"vs_{ref}"] = {
            "relative_gain": gain["relative_gain"],
            "relative_gain_ci95": gain["relative_gain_ci95"],
            "meets_10pct": gain["relative_gain"] >= 0.10,
            "worst_family_delta_points": min(f["delta_points"] for f in fams.values()),
            "no_family_regresses_over_2_points": min(f["delta_points"] for f in fams.values()) >= -2.0,
        }
    results["gate"] = gate

    for name, pairs in stability.items():
        rhos = [p[1] for p in pairs if p[1] == p[1]]
        results["stability"][name] = {"queries": len(pairs), "mean_jaccard_at_10": bp._mean([p[0] for p in pairs]),
                                      "spearman_queries": len(rhos), "mean_spearman_full_catalog": bp._mean(rhos)}
    # The production heuristic is deterministic: a second run must match exactly.
    again = [[row["artist_id"] for row in heur.similar(int(a))] for a in qs[:500]]
    results["stability"]["heuristic"] = {"queries": len(again), "identical": all(
        again[i] == [x for x in prod[i].tolist() if x >= 0] for i in range(len(again)))}

    results["ground_truth"] = {
        "query_artists_eligible": int(len(queries)),
        "query_artists_with_relevant": int(len(qs)),
        "gt_pairs_total": int(gt_pairs_total),
        "gt_pairs_in_retrievable_catalog": int(gt_pairs_in_universe),
        "mean_relevant_per_query": float(np.mean([len(x) for x in rel_list])),
        "median_relevant_per_query": float(np.median([len(x) for x in rel_list])),
        "queries_with_novel": int(sum(1 for x in nov_list if x)),
        "retrievable_catalog_artists": catalog_size,
        "query_family_counts": {f: families.count(f) for f in sorted(set(families))},
    }
    results["eval_wall_s"] = round(time.time() - t0, 1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=1, sort_keys=True))
    print(f"done {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
