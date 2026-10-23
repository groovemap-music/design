#!/usr/bin/env python3
"""Concept B measurements over two consecutive dumps' aggregates.

Writes one JSON of aggregate numbers (no names, no ids): multi-parent rates, placement
rules, lifecycle stability, layout stability, and cost inputs.

Usage:
    python measure_atlas.py AGG_EARLY.npz AGG_LATE.npz OUT.json \
        [--vectors VEC_EARLY.npz VEC_LATE.npz]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

import layout
import lifecycle
from aggregate import COUNT_NAMES, YEAR0, load_aggregates

THRESHOLDS = (0.05, 0.10, 0.20, 0.30)
HEADLINE_SHARE = 0.20
HEADLINE_YEAR = 2025
TIMELINE_FROM = 1950


def align(a: dict, b: dict) -> tuple[dict, dict, list[str]]:
    """Restrict both dumps to the styles and genres they share, in one order."""
    styles = sorted(set(a["styles"]) & set(b["styles"]))
    genres = sorted(set(a["genres"]) & set(b["genres"]))

    def pick(d: dict) -> dict:
        si = np.array([d["styles"].index(s) for s in styles])
        gi = np.array([d["genres"].index(g) for g in genres])
        out = {k: v for k, v in d.items() if k not in ("styles", "genres")}
        for k in ("style_genre_rel", "partof"):
            out[k] = d[k][np.ix_(si, gi)]
        out["cotag"] = d["cotag"][np.ix_(si, si)]
        for k in ("style_rel", "style_year_rel", "style_year_mst", "first_year_style"):
            out[k] = d[k][si]
        for k in ("genre_year_rel", "first_year_genre"):
            out[k] = d[k][gi]
        out["genres"], out["styles"] = genres, styles
        return out

    return pick(a), pick(b), styles


def pct(x: float) -> float:
    return round(100 * x, 2)


def multi_parent(d: dict) -> dict:
    share = layout.shares(d["style_genre_rel"], d["style_rel"])
    live = d["style_rel"] > 0
    w = d["style_rel"].astype(float)
    po = d["partof"][live].sum(axis=1)
    top = np.sort(share[live], axis=1)[:, ::-1]
    p20 = layout.parents(share, HEADLINE_SHARE)[live]
    multi = p20.sum(axis=1) >= 2
    return {
        "styles_with_releases": int(live.sum()),
        "partof_rule": {
            "styles_with_2plus_parents_pct": pct((po >= 2).mean()),
            "release_weighted_pct": pct(w[live][po >= 2].sum() / w[live].sum()),
            "parent_count_hist": {str(k): int((np.minimum(po, 5) == k).sum()) for k in range(0, 6)},
            "mean_parents": round(float(po.mean()), 2),
        },
        "share_rule": {
            f"{t:.2f}": {
                "styles_pct": pct(layout.multi_parent_rate(share[live], t)),
                "release_weighted_pct": pct(layout.multi_parent_rate(share[live], t, w[live])),
                "secondary_parent_pairs": int(layout.parents(share[live], t).sum() - live.sum()),
            }
            for t in THRESHOLDS
        },
        "dominant_share": {
            "median": round(float(np.median(top[:, 0])), 3),
            "p10": round(float(np.percentile(top[:, 0], 10)), 3),
        },
        "multi_parent_split_at_headline": {
            "mean_top1": round(float(top[multi, 0].mean()), 3) if multi.any() else None,
            "mean_top2": round(float(top[multi, 1].mean()), 3) if multi.any() else None,
            "with_3plus_parents": int((p20.sum(axis=1) >= 3).sum()),
        },
    }


def lifecycle_block(a: dict, b: dict, key: str) -> dict:
    hy = HEADLINE_YEAR - YEAR0
    t0 = TIMELINE_FROM - YEAR0
    rule = lifecycle.Rule()
    sa = lifecycle.stages(a[key][:, : hy + 1], rule)
    sb = lifecycle.stages(b[key][:, : hy + 1], rule)
    timeline = np.zeros_like(sa, dtype=bool)
    timeline[:, t0:] = True
    out = {
        "stage_hist_headline_late": lifecycle.stage_histogram(sb[:, hy]),
        "dump_flip_headline_pct": pct(lifecycle.flip_share(sa[:, [hy]], sb[:, [hy]])),
        "dump_flip_headline_styles": int(((sa[:, hy] != sb[:, hy]) & ((sa[:, hy] > 0) | (sb[:, hy] > 0))).sum()),
        "dump_flip_prev_year_pct": pct(lifecycle.flip_share(sa[:, [hy - 1]], sb[:, [hy - 1]])),
        "dump_flip_timeline_pct": pct(lifecycle.flip_share(sa, sb, timeline)),
        "headline_year_count_growth_pct": pct(b[key][:, hy].sum() / max(1, a[key][:, hy].sum()) - 1),
        # Catalog entry lags release: how much each recent year grew in one month.
        "count_growth_by_year_pct": {
            str(y): pct(b[key][:, y - YEAR0].sum() / max(1, a[key][:, y - YEAR0].sum()) - 1) for y in range(2019, HEADLINE_YEAR + 1)
        },
        "tagged_count_by_year_late": {str(y): int(b[key][:, y - YEAR0].sum()) for y in range(2019, HEADLINE_YEAR + 1)},
        "stage_hist_by_year_late": {str(y): lifecycle.stage_histogram(sb[:, y - YEAR0]) for y in (1990, 2000, 2010, 2015, 2020, 2024)},
        "perturbation_headline_pct": {},
        "perturbation_timeline_pct": {},
    }
    for scale in (0.9, 1.1):
        for name, r in rule.perturbed(scale):
            sp = lifecycle.stages(b[key][:, : hy + 1], r)
            tag = f"{name}x{scale}"
            out["perturbation_headline_pct"][tag] = pct(lifecycle.flip_share(sb[:, [hy]], sp[:, [hy]]))
            out["perturbation_timeline_pct"][tag] = pct(lifecycle.flip_share(sb, sp, timeline))
    out["max_perturbation_headline_pct"] = max(out["perturbation_headline_pct"].values())
    out["max_perturbation_timeline_pct"] = max(out["perturbation_timeline_pct"].values())
    return out


def emergence_block(a: dict, b: dict) -> dict:
    rule = lifecycle.Rule()
    hy = HEADLINE_YEAR - YEAR0

    def y0(d):
        cum = np.cumsum(d["style_year_rel"][:, : hy + 1], axis=1)
        e = cum >= rule.emerge_total
        return np.where(e.any(axis=1), e.argmax(axis=1) + YEAR0, 0)

    def gy0(d):
        cum = np.cumsum(d["genre_year_rel"][:, : hy + 1], axis=1)
        e = cum >= rule.emerge_total
        return np.where(e.any(axis=1), e.argmax(axis=1) + YEAR0, 0)

    fa, fb = a["first_year_style"], b["first_year_style"]
    ya, yb = y0(a), y0(b)
    both = (fb > 0) & (yb > 0)
    gyb = gy0(b)
    gfb = b["first_year_genre"]
    par = b["partof"].astype(bool)
    dom = layout.shares(b["style_genre_rel"], b["style_rel"]).argmax(axis=1)
    live = b["style_rel"] > 0
    viol_dom = int(((yb > 0) & live & (yb < gyb[dom])).sum())
    viol_rule = viol_first = 0
    for s in range(len(yb)):
        ps = np.flatnonzero(par[s])
        if not len(ps):
            continue
        if yb[s] and yb[s] < gyb[ps].max():
            viol_rule += 1
        if fb[s] and fb[s] < gfb[ps].max():
            viol_first += 1
    return {
        "first_year_changed_between_dumps": int((fa != fb).sum()),
        "emergence_year_changed_between_dumps": int((ya != yb).sum()),
        "first_year_more_than_10y_before_emergence_pct": pct(((yb - fb) > 10)[both].mean()),
        "first_year_minus_emergence_median_years": float(np.median((yb - fb)[both])),
        "partof_parent_after_child_rule_y0": viol_rule,
        "partof_parent_after_child_first_year": viol_first,
        "dominant_parent_after_child_rule_y0": viol_dom,
        "styles_with_partof_parent": int((par.sum(axis=1) > 0).sum()),
    }


def geo_block(a: dict, b: dict) -> dict:
    out = {}
    hy = HEADLINE_YEAR - YEAR0
    rule = lifecycle.Rule()

    def emerge(d):
        cum = np.cumsum(d["style_year_rel"][:, : hy + 1], axis=1)
        e = cum >= rule.emerge_total
        return np.where(e.any(axis=1), e.argmax(axis=1) + YEAR0, HEADLINE_YEAR + 1)

    sh_a = layout.shares(a["style_genre_rel"], a["style_rel"])
    sh_b = layout.shares(b["style_genre_rel"], b["style_rel"])
    order_a = layout.ring_order(layout.genre_affinity(sh_a))
    order_b = layout.ring_order(layout.genre_affinity(sh_b))
    out["ring_order_changed"] = order_a != order_b
    par_b = layout.parents(sh_b, HEADLINE_SHARE)
    edges_b = layout.cotag_edges(b["cotag"])
    out["cotag_edges"] = int(len(edges_b))
    prof_a = layout.hellinger_profiles(a["cotag"])
    prof_b = layout.hellinger_profiles(b["cotag"])
    variants = [(r, r, None, None) for r in ("dominant", "ghost", "border")]
    variants += [(f"{r}_cotag_inner", r, prof_a, prof_b) for r in ("dominant", "ghost")]
    for name, rule_name, pa, pb in variants:
        da, meta_a = layout.geography(sh_a, emerge(a), HEADLINE_SHARE, rule_name, order=order_a, profiles=pa)
        db, meta = layout.geography(sh_b, emerge(b), HEADLINE_SHARE, rule_name, order=order_a, profiles=pb, inner_ref=meta_a["inner"] if pa is not None else None)
        m = layout.intrusions(db, par_b)
        m["sector_width_max_deg"] = round(float(np.degrees(meta["width"].max())), 1)
        segs = layout.place_edges(db, edges_b)
        m["edge_crossings"] = layout.crossings(segs)
        m["edges_through_foreign_hull"] = layout.edges_through_foreign_hulls(db, [tuple(e) for e in edges_b], segs, par_b)
        m.update(layout.intra_hull_crossings(db, edges_b))
        prim_a = {int(s): xy for s, xy, g in zip(da.style, da.xy, da.ghost) if not g}
        prim_b = {int(s): xy for s, xy, g in zip(db.style, db.xy, db.ghost) if not g}
        common = sorted(set(prim_a) & set(prim_b))
        xa = np.array([prim_a[s] for s in common])
        xb = np.array([prim_b[s] for s in common])
        m["stability"] = {**{k: round(v, 3) for k, v in layout.displacement(xa, xb).items()}, "knn10_jaccard": round(layout.knn_overlap(xa, xb), 3)}
        host_a = {int(s): int(h) for s, h, g in zip(da.style, da.host, da.ghost) if not g}
        host_b = {int(s): int(h) for s, h, g in zip(db.style, db.host, db.ghost) if not g}
        m["stability"]["host_changed"] = int(sum(host_a[s] != host_b[s] for s in common))
        out[name] = m
    # The ring recomputed from the late dump instead of pinned: what an unpinned monthly
    # recompute would show.
    da, _ = layout.geography(sh_a, emerge(a), HEADLINE_SHARE, "ghost", order=order_a)
    db, _ = layout.geography(sh_b, emerge(b), HEADLINE_SHARE, "ghost", order=order_b)
    prim_a = {int(s): xy for s, xy, g in zip(da.style, da.xy, da.ghost) if not g}
    prim_b = {int(s): xy for s, xy, g in zip(db.style, db.xy, db.ghost) if not g}
    common = sorted(set(prim_a) & set(prim_b))
    out["ghost_unpinned_ring_stability"] = {
        k: round(v, 3) for k, v in layout.displacement(np.array([prim_a[s] for s in common]), np.array([prim_b[s] for s in common])).items()
    }
    return out


def free_block(name: str, xa: np.ndarray, xb: np.ndarray, b: dict) -> dict:
    sh_b = layout.shares(b["style_genre_rel"], b["style_rel"])
    par_b = layout.parents(sh_b, HEADLINE_SHARE)
    live = sh_b.sum(axis=1) > 0
    xb_al = xb.copy()
    xb_al[live] = layout.procrustes(xa[live], xb[live])
    drawn = layout.free_drawn(xb_al, sh_b)
    m = layout.intrusions(drawn, par_b)
    edges_b = layout.cotag_edges(b["cotag"])
    segs = layout.place_edges(drawn, edges_b)
    m["edge_crossings"] = layout.crossings(segs)
    m["edges_through_foreign_hull"] = layout.edges_through_foreign_hulls(drawn, [tuple(e) for e in edges_b], segs, par_b)
    m.update(layout.intra_hull_crossings(drawn, edges_b))
    m["stability"] = {
        **{k: round(v, 3) for k, v in layout.displacement(xa[live], xb_al[live]).items()},
        "knn10_jaccard": round(layout.knn_overlap(xa[live], xb_al[live]), 3),
    }
    m["source"] = name
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("early", type=Path)
    ap.add_argument("late", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--vectors", nargs=2, type=Path)
    args = ap.parse_args()
    started = time.time()
    a_raw, b_raw = load_aggregates(args.early), load_aggregates(args.late)
    a, b, styles = align(a_raw, b_raw)
    res: dict = {
        "dumps": [args.early.stem.split("_")[-1], args.late.stem.split("_")[-1]],
        "population": {
            "early": dict(zip(COUNT_NAMES, a_raw["counts"].tolist())),
            "late": dict(zip(COUNT_NAMES, b_raw["counts"].tolist())),
            "styles_early": len(a_raw["styles"]),
            "styles_late": len(b_raw["styles"]),
            "styles_common": len(styles),
            "genres_common": len(a["genres"]),
        },
        "headline_share": HEADLINE_SHARE,
        "headline_year": HEADLINE_YEAR,
        "multi_parent": {"early": multi_parent(a), "late": multi_parent(b)},
    }
    sh_a = layout.shares(a["style_genre_rel"], a["style_rel"])
    sh_b = layout.shares(b["style_genre_rel"], b["style_rel"])
    res["multi_parent"]["dominant_parent_changed"] = int((sh_a.argmax(axis=1) != sh_b.argmax(axis=1))[(a["style_rel"] > 0) & (b["style_rel"] > 0)].sum())
    res["multi_parent"]["parent_set_changed_at_headline"] = int(
        (layout.parents(sh_a, HEADLINE_SHARE) != layout.parents(sh_b, HEADLINE_SHARE)).any(axis=1).sum()
    )
    res["lifecycle"] = {
        "rule": lifecycle.Rule().__dict__,
        "release_year": lifecycle_block(a, b, "style_year_rel"),
        "master_year": lifecycle_block(a, b, "style_year_mst"),
        "emergence": emergence_block(a, b),
    }
    res["layout"] = {"geography": geo_block(a, b)}
    res["layout"]["cooccurrence"] = free_block(
        "cooccurrence", layout.classical_mds(layout.hellinger_profiles(a["cotag"])), layout.classical_mds(layout.hellinger_profiles(b["cotag"])), b
    )
    if args.vectors:
        va = dict(np.load(args.vectors[0]))["style_vectors"]
        vb = dict(np.load(args.vectors[1]))["style_vectors"]
        ia = [a_raw["styles"].index(s) for s in styles]
        ib = [b_raw["styles"].index(s) for s in styles]
        va, vb = va[ia], vb[ib]
        unit = lambda v: v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)  # noqa: E731
        cos = (unit(va) * unit(vb)).sum(axis=1)
        live = (np.abs(va).sum(axis=1) > 0) & (np.abs(vb).sum(axis=1) > 0)
        block = free_block("embedding", layout.classical_mds(unit(va)), layout.classical_mds(unit(vb)), b)
        block["vector_cosine_across_dumps"] = {"median": round(float(np.median(cos[live])), 4), "p05": round(float(np.percentile(cos[live], 5)), 4)}
        res["layout"]["embedding"] = block
    hy = HEADLINE_YEAR - YEAR0
    res["cost_inputs"] = {
        "release_style_tags_late": int(b_raw["counts"][COUNT_NAMES.index("release_style_tags")]),
        "style_year_cells_nonzero_late": int((b["style_year_rel"][:, : hy + 1] > 0).sum()),
        "lifecycle_table_rows": int(len(styles) * (HEADLINE_YEAR - YEAR0 + 1)),
        "measure_seconds": round(time.time() - started, 1),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")
    print(json.dumps({"lifecycle_flip": res["lifecycle"]["release_year"]["dump_flip_headline_pct"]}))


if __name__ == "__main__":
    main()
