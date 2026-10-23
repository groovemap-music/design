#!/usr/bin/env python3
"""Concept C measurements: synthetic collectors over one dump's releases.

Each synthetic collector draws ``focus`` of their items from one to three seed styles
(weighted by style size) and the rest uniformly. Candidates are drawn in three bands per
collector: in-taste (a seed style), adjacent (a seed's strongest co-tagged style), and
random. No real user data is read. The collections, candidates, and ids stay in memory;
only aggregate shares are written.

Usage:
    python measure_taste.py releases_<dump>.npz masters_<dump>.npz aggregates_<dump>.npz OUT.json
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np

import layout
import taste
from aggregate import load_aggregates

SIZES = (50, 300, 2000)
COLLECTORS_PER_SIZE = 40
CANDIDATES_PER_BAND = 10
LANDMARKS_PER_STYLE = 25
SEED = 4804


class Catalog:
    def __init__(self, rel: dict, rel_vocab: dict):
        self.rel = rel
        self.genres = rel_vocab["genres"]
        self.styles = rel_vocab["styles"]
        n = len(rel["id"])
        rec = np.repeat(np.arange(n), np.diff(rel["style_ptr"]))
        order = np.argsort(rel["style_idx"], kind="stable")
        self.by_style_idx = rec[order]
        bounds = np.searchsorted(rel["style_idx"][order], np.arange(len(self.styles) + 1))
        self.by_style_bounds = bounds
        self.n = n

    def style_members(self, s: int) -> np.ndarray:
        return self.by_style_idx[self.by_style_bounds[s] : self.by_style_bounds[s + 1]]

    def release(self, i: int) -> taste.Release:
        r = self.rel
        sp, ap, lp = r["style_ptr"], r["artist_ptr"], r["label_ptr"]
        mask = int(r["genre_mask"][i])
        return taste.Release(
            rid=int(r["id"][i]),
            master=int(r["master"][i]),
            artists=tuple(int(x) for x in r["artist_ids"][ap[i] : ap[i + 1]]),
            labels=tuple(int(x) for x in r["label_ids"][lp[i] : lp[i + 1]]),
            genres=tuple(g for b, g in enumerate(self.genres) if mask >> b & 1),
            styles=tuple(self.styles[x] for x in r["style_idx"][sp[i] : sp[i + 1]]),
        )


def landmark_masters(mst: dict, rel: dict) -> set[int]:
    """Top masters per style (the master's own styles) by number of releases."""
    ids, counts = np.unique(rel["master"][rel["master"] > 0], return_counts=True)
    size = dict(zip(ids.tolist(), counts.tolist()))
    rec = np.repeat(np.arange(len(mst["id"])), np.diff(mst["style_ptr"]))
    by_style: dict[int, list[tuple[int, int]]] = {}
    for i, s in zip(rec.tolist(), mst["style_idx"].tolist()):
        mid = int(mst["id"][i])
        by_style.setdefault(s, []).append((size.get(mid, 0), mid))
    out: set[int] = set()
    for lst in by_style.values():
        lst.sort(reverse=True)
        out.update(m for _, m in lst[:LANDMARKS_PER_STYLE])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("releases", type=Path)
    ap.add_argument("masters", type=Path)
    ap.add_argument("aggregates", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    ap.add_argument("--collectors", type=int, default=COLLECTORS_PER_SIZE)
    args = ap.parse_args()
    started = time.time()
    rel = dict(np.load(args.releases))
    rel_vocab = json.loads(args.releases.with_suffix(".vocab.json").read_text())
    mst = dict(np.load(args.masters))
    agg = load_aggregates(args.aggregates)
    cat = Catalog(rel, rel_vocab)
    landmarks = landmark_masters(mst, rel)
    share = layout.shares(agg["style_genre_rel"], agg["style_rel"])
    dom = {agg["styles"][i]: int(share[i].argmax()) for i in range(len(agg["styles"]))}
    sizes = np.array([len(cat.style_members(s)) for s in range(len(cat.styles))], dtype=float)
    cot = agg["cotag"].astype(float).copy()
    np.fill_diagonal(cot, 0)
    agg_index = {n: i for i, n in enumerate(agg["styles"])}
    rng = np.random.default_rng(SEED)

    items = Counter()
    fit = {c: Counter() for c in ("affinity", "novelty", "bridge", "depth", "redundancy")}
    affinity_mass = []
    evaluations = 0
    for size in args.sizes:
        for _ in range(args.collectors):
            k = int(rng.integers(1, 4))
            seeds = list(rng.choice(len(cat.styles), size=k, replace=False, p=sizes / sizes.sum()))
            picks: set[int] = set()
            seed_pool = np.concatenate([cat.style_members(s) for s in seeds])
            while len(picks) < size:
                if rng.random() < 0.8:
                    picks.add(int(seed_pool[rng.integers(len(seed_pool))]))
                else:
                    picks.add(int(rng.integers(cat.n)))
            held = [cat.release(i) for i in sorted(picks)]
            coll = taste.Collection.fold(held)
            master_of = {r.rid: r.master for r in held}
            held_by_master: dict[int, list[int]] = {}
            for r in held:
                if r.master:
                    held_by_master.setdefault(r.master, []).append(r.rid)
            # Item projection.
            for r in held:
                items["items"] += 1
                items["with_style"] += bool(r.styles)
                items["genre_only"] += (not r.styles) and bool(r.genres)
                items["no_genre"] += not r.genres
                items["with_master"] += r.master > 0
                items["landmark_master"] += r.master in landmarks
                hosts = {dom[s] for s in r.styles if s in dom}
                items["multi_hull"] += len(hosts) >= 2
                items["style_landings"] += len(r.styles)
            # Candidates.
            adjacent = []
            for s in seeds:
                name = cat.styles[s]
                if name in agg_index:
                    nb = int(np.argmax(cot[agg_index[name]]))
                    adjacent.append(cat.styles.index(agg["styles"][nb]) if agg["styles"][nb] in cat.styles else s)
            bands = {
                "in_taste": seed_pool,
                "adjacent": np.concatenate([cat.style_members(s) for s in adjacent]) if adjacent else seed_pool,
                "random": None,
            }
            for band, pool in bands.items():
                for _ in range(CANDIDATES_PER_BAND):
                    i = int(pool[rng.integers(len(pool))]) if pool is not None else int(rng.integers(cat.n))
                    cand = cat.release(i)
                    sib = held_by_master.get(cand.master, []) if cand.master else []
                    out = taste.fit_entries(coll, cand, siblings_held=sib)
                    evaluations += 1
                    mo = dict(master_of)
                    mo[cand.rid] = cand.master
                    for comp, body in out.items():
                        f = fit[comp]
                        f["evaluations"] += 1
                        scored = body["score"] > 0
                        f["scored"] += scored
                        tgt_all = [taste.atlas_target(e, mo, cat.genres) for e in body["entries"]]
                        tgt_cap = [taste.atlas_target(e, mo, cat.genres) for e in body["capped"]]
                        for t in tgt_all:
                            f[f"entries_{t}"] += 1
                        drawable_cap = any(t in ("position", "edge") for t in tgt_cap)
                        drawable_all = any(t in ("position", "edge") for t in tgt_all)
                        if scored:
                            f["scored_drawable_capped"] += drawable_cap
                            f["scored_drawable_uncapped"] += drawable_all
                            f["scored_nothing_drawable"] += not drawable_all
                            f["scored_drawable_lost_to_cap"] += drawable_all and not drawable_cap
                            f["scored_ambiguous"] += "ambiguous" in tgt_all
                    # Affinity mass from the dimensions the atlas carries.
                    facets = {"artist": cand.artists, "label": cand.labels, "genre": cand.genres, "style": cand.styles}
                    num = den = drawn = 0.0
                    for d, w in taste.WEIGHTS.items():
                        if not facets[d]:
                            continue
                        held_d = coll.counts[d]
                        part = w * sum(1 for v in facets[d] if v in held_d) / len(facets[d])
                        num += part
                        den += w
                        if d in ("genre", "style"):
                            drawn += part
                    if num > 0:
                        affinity_mass.append(drawn / num)

    def pct(a, b):
        return round(100 * a / b, 2) if b else None

    res = {
        "collectors": len(args.sizes) * args.collectors,
        "sizes": args.sizes,
        "fit_evaluations": evaluations,
        "landmarks_per_style": LANDMARKS_PER_STYLE,
        "landmark_masters": len(landmarks),
        "items": {
            "held_items": items["items"],
            "with_style_pct": pct(items["with_style"], items["items"]),
            "genre_only_pct": pct(items["genre_only"], items["items"]),
            "no_genre_pct": pct(items["no_genre"], items["items"]),
            "with_master_pct": pct(items["with_master"], items["items"]),
            "master_is_landmark_pct": pct(items["landmark_master"], items["items"]),
            "styles_span_2plus_hulls_pct": pct(items["multi_hull"], items["items"]),
            "mean_style_landings": round(items["style_landings"] / max(1, items["with_style"]), 2),
        },
        "fit": {},
        "affinity_mass_on_atlas_dims": {
            "median": round(float(np.median(affinity_mass)), 3) if affinity_mass else None,
            "mean": round(float(np.mean(affinity_mass)), 3) if affinity_mass else None,
        },
        "genre_names_with_comma_or_and": sum(1 for g in cat.genres if ", " in g or " and " in g),
        "seconds": round(time.time() - started, 1),
    }
    for comp, f in fit.items():
        total_entries = sum(v for k, v in f.items() if k.startswith("entries_"))
        res["fit"][comp] = {
            "scored_pct": pct(f["scored"], f["evaluations"]),
            "entries": total_entries,
            "entries_target_pct": {k[8:]: pct(v, total_entries) for k, v in sorted(f.items()) if k.startswith("entries_")},
            "scored_with_drawable_capped_pct": pct(f["scored_drawable_capped"], f["scored"]),
            "scored_with_drawable_uncapped_pct": pct(f["scored_drawable_uncapped"], f["scored"]),
            "scored_nothing_drawable_pct": pct(f["scored_nothing_drawable"], f["scored"]),
            "scored_drawable_lost_to_cap_pct": pct(f["scored_drawable_lost_to_cap"], f["scored"]),
            "scored_ambiguous_pct": pct(f["scored_ambiguous"], f["scored"]),
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps({"evaluations": evaluations, "seconds": res["seconds"]}))


if __name__ == "__main__":
    main()
