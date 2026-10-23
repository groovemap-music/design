"""Atlas layouts, placement rules for multi-parent styles, and the geometry measures.

Three layout sources are compared on the same styles:

- ``geography``: genres on a ring in an order that keeps co-occurring genres adjacent,
  one sector per genre (width proportional to the square root of its member count), and
  each style inside its genre's sector. A style's angle within the sector is the rank of
  its lean toward the clockwise versus the counter-clockwise neighbour genre; its radius
  is the rank of its emergence year. Ranks, not raw values, so a month of edits moves a
  style only when it swaps rank with a neighbour.
- ``cooccurrence``: classical MDS of the Hellinger distance between styles' co-tag
  profiles. No genre input at all.
- ``embedding``: PCA of per-style vectors (ADR 0013 artist vectors aggregated upward,
  see ``fastrp.py``).

The two free layouts are aligned across dumps by an orthogonal Procrustes fit (rotation,
reflection, uniform scale, translation) before any displacement is measured, which is the
best case for them: production would have to do the same alignment to keep the map still.

Placement rules (a style with more than one parent at the stated share):

- ``dominant``: drawn once, under the parent with the largest share;
- ``ghost``: drawn under the dominant parent, plus a ghost copy inside every other parent's
  sector, and the ghost counts as a member of its host hull;
- ``border``: drawn once, on the boundary between its two largest parents when they are
  adjacent on the ring (both hulls include it); otherwise under the dominant parent.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import Delaunay, cKDTree


# ---------------------------------------------------------------- structure


def shares(style_genre: np.ndarray, style_total: np.ndarray) -> np.ndarray:
    """S x G share of a style's releases that also carry each genre."""
    total = np.maximum(style_total, 1)[:, None]
    return style_genre / total


def parents(share: np.ndarray, threshold: float) -> np.ndarray:
    """S x G boolean: genres holding at least ``threshold`` of the style's releases.

    The dominant genre is always a parent, so every style with any genre has one.
    """
    out = share >= threshold
    out[np.arange(len(share)), share.argmax(axis=1)] = True
    out[share.sum(axis=1) == 0] = False
    return out


def multi_parent_rate(share: np.ndarray, threshold: float, weights: np.ndarray | None = None) -> float:
    p = parents(share, threshold)
    has = p.any(axis=1)
    multi = p.sum(axis=1) >= 2
    if weights is None:
        return float(multi[has].mean()) if has.any() else 0.0
    return float(weights[multi].sum() / weights[has].sum())


# ---------------------------------------------------------------- genre ring


def genre_affinity(share: np.ndarray) -> np.ndarray:
    """G x G soft overlap: sum over styles of min(share_g, share_h)."""
    g = share.shape[1]
    w = np.zeros((g, g))
    for i in range(g):
        w[i] = np.minimum(share[:, [i]], share).sum(axis=0)
    np.fill_diagonal(w, 0.0)
    return w


def ring_order(w: np.ndarray) -> list[int]:
    """Exact maximum-weight Hamiltonian cycle (Held-Karp), canonical start and direction.

    Starts at genre 0 and runs toward the smaller-index neighbour, so equal inputs give
    identical orders and a reversed cycle is the same ring.
    """
    n = len(w)
    if n <= 2:
        return list(range(n))
    full = 1 << n
    dp = np.full((full, n), -np.inf)
    parent = np.full((full, n), -1, dtype=np.int64)
    dp[1, 0] = 0.0
    for mask in range(1, full, 2):  # every subset that contains genre 0
        row = dp[mask]
        if not np.isfinite(row).any():
            continue
        for last in np.flatnonzero(np.isfinite(row)):
            base = row[last]
            for nxt in range(1, n):
                bit = 1 << nxt
                if mask & bit:
                    continue
                value = base + w[last, nxt]
                m2 = mask | bit
                if value > dp[m2, nxt]:
                    dp[m2, nxt] = value
                    parent[m2, nxt] = last
    last_mask = full - 1
    closing = dp[last_mask] + w[:, 0]
    closing[0] = -np.inf
    last = int(np.argmax(closing))
    order = []
    mask = last_mask
    while last != -1:
        order.append(last)
        prev = int(parent[mask, last])
        mask ^= 1 << last
        last = prev
    order.reverse()  # starts at 0
    if order[1] > order[-1]:
        order = [order[0]] + order[1:][::-1]
    return order


# ---------------------------------------------------------------- geography layout


@dataclass
class Drawn:
    """Drawn nodes: one row per placed copy of a style."""

    xy: np.ndarray  # N x 2
    style: np.ndarray  # N, style index
    host: np.ndarray  # N, genre whose hull this copy belongs to
    ghost: np.ndarray  # N, bool
    also: np.ndarray  # N, second hull a border node belongs to, or -1


def _ranks(values: np.ndarray, tiebreak: np.ndarray) -> np.ndarray:
    order = np.lexsort((tiebreak, values))
    r = np.empty(len(values))
    r[order] = (np.arange(len(values)) + 0.5) / len(values)
    return r


def geography(
    share: np.ndarray,
    emerge_year: np.ndarray,
    threshold: float,
    rule: str = "dominant",
    order: list[int] | None = None,
    profiles: np.ndarray | None = None,
    inner_ref: dict | None = None,
) -> tuple[Drawn, dict]:
    """Ring-sector layout. ``order`` may be passed to pin the ring across dumps.

    With ``profiles`` (S x F, e.g. Hellinger co-tag profiles), a style's place inside its
    sector is the rank of its first two classical-MDS coordinates over the sector's
    members (geography + co-occurrence) instead of lean and emergence year. ``inner_ref``
    (the previous dump's ``meta["inner"]``) pins each sector's MDS frame: the new
    coordinates are Procrustes-aligned to the previous ones over the shared members
    before ranking, so an axis flip or rotation between dumps does not move the map.
    """
    s_count, g_count = share.shape
    live = share.sum(axis=1) > 0
    par = parents(share, threshold)
    dom = share.argmax(axis=1)
    if order is None:
        order = ring_order(genre_affinity(share))
    pos_in_ring = np.empty(g_count, dtype=np.int64)
    pos_in_ring[order] = np.arange(g_count)
    cw = {g: order[(pos_in_ring[g] + 1) % g_count] for g in range(g_count)}
    ccw = {g: order[(pos_in_ring[g] - 1) % g_count] for g in range(g_count)}

    # Members per sector, under the rule.
    entries: list[tuple[int, int, bool, int]] = []  # (style, host, ghost, also)
    for s in np.flatnonzero(live):
        d = int(dom[s])
        if rule == "dominant" or par[s].sum() == 1:
            entries.append((s, d, False, -1))
        elif rule == "ghost":
            entries.append((s, d, False, -1))
            for h in np.flatnonzero(par[s]):
                if h != d:
                    entries.append((s, int(h), True, -1))
        elif rule == "border":
            ranked = np.argsort(-share[s])
            second = int(ranked[1])
            if par[s, second] and second in (cw[d], ccw[d]):
                entries.append((s, d, False, second))
            else:
                entries.append((s, d, False, -1))
        else:
            raise ValueError(rule)

    counts = np.zeros(g_count)
    for _, host, _, _ in entries:
        counts[host] += 1
    width = np.sqrt(counts + 1)
    width = 2 * np.pi * width / width.sum()
    start = np.zeros(g_count)
    acc = 0.0
    for g in order:
        start[g] = acc
        acc += width[g]

    xy = np.zeros((len(entries), 2))
    style = np.array([e[0] for e in entries], dtype=np.int64)
    host = np.array([e[1] for e in entries], dtype=np.int64)
    ghost = np.array([e[2] for e in entries], dtype=bool)
    also = np.array([e[3] for e in entries], dtype=np.int64)
    inner_out: dict = {}
    for g in range(g_count):
        idx = np.flatnonzero(host == g)
        if not len(idx):
            continue
        st = style[idx]
        if profiles is not None and len(idx) >= 3:
            inner = classical_mds(profiles[st])
            if inner_ref is not None and g in inner_ref:
                ref_st, ref_xy = inner_ref[g]
                pos = {int(x): i for i, x in enumerate(ref_st)}
                common = [i for i, x in enumerate(st) if int(x) in pos]
                if len(common) >= 3:
                    ref = ref_xy[[pos[int(st[i])] for i in common]]
                    mr, mx = ref.mean(axis=0), inner[common].mean(axis=0)
                    uu, sv, vt = np.linalg.svd((inner[common] - mx).T @ (ref - mr))
                    inner = (inner - mx) @ (uu @ vt) * (sv.sum() / ((inner[common] - mx) ** 2).sum()) + mr
            inner_out[g] = (st.copy(), inner)
            u = _ranks(inner[:, 0], st)
            v = _ranks(inner[:, 1], st)
        else:
            lean = share[st, cw[g]] - share[st, ccw[g]]
            u = _ranks(lean, st)
            v = _ranks(emerge_year[st].astype(float), st)
        theta = start[g] + width[g] * (0.1 + 0.8 * u)
        # A border node sits on the sector edge it shares with its second parent.
        for k, i in enumerate(idx):
            if also[i] == cw[g]:
                theta[k] = start[g] + width[g]
            elif also[i] == ccw[g] and also[i] != -1:
                theta[k] = start[g]
        rho = 0.35 + 0.6 * v
        xy[idx, 0] = rho * np.cos(theta)
        xy[idx, 1] = rho * np.sin(theta)
    return Drawn(xy, style, host, ghost, also), {"order": order, "width": width, "inner": inner_out}


# ---------------------------------------------------------------- free layouts


def hellinger_profiles(cotag: np.ndarray) -> np.ndarray:
    rows = cotag.astype(float).copy()
    np.fill_diagonal(rows, 0.0)
    total = rows.sum(axis=1, keepdims=True)
    return np.sqrt(np.divide(rows, total, out=np.zeros_like(rows), where=total > 0))


def classical_mds(features: np.ndarray, dims: int = 2) -> np.ndarray:
    """Classical MDS on Euclidean distances between rows (= PCA of centred rows).

    The sign of each axis is fixed so its largest-magnitude loading is positive.
    """
    x = features - features.mean(axis=0)
    u, sv, vt = np.linalg.svd(x, full_matrices=False)
    out = u[:, :dims] * sv[:dims]
    for d in range(dims):
        j = np.argmax(np.abs(vt[d]))
        if vt[d, j] < 0:
            out[:, d] *= -1
    return out


def procrustes(ref: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Similarity transform of ``x`` that best matches ``ref`` (least squares)."""
    mr, mx = ref.mean(axis=0), x.mean(axis=0)
    a, b = ref - mr, x - mx
    u, sv, vt = np.linalg.svd(b.T @ a)
    rot = u @ vt
    scale = sv.sum() / (b**2).sum()
    return b @ rot * scale + mr


def free_drawn(xy: np.ndarray, share: np.ndarray) -> Drawn:
    live = np.flatnonzero(share.sum(axis=1) > 0)
    dom = share.argmax(axis=1)
    n = len(live)
    return Drawn(xy[live], live, dom[live], np.zeros(n, bool), np.full(n, -1))


# ---------------------------------------------------------------- measures


def hulls(drawn: Drawn, g_count: int) -> list[Delaunay | None]:
    out: list[Delaunay | None] = []
    for g in range(g_count):
        pts = drawn.xy[(drawn.host == g) | (drawn.also == g)]
        if len(pts) >= 3:
            try:
                out.append(Delaunay(pts))
                continue
            except Exception:  # collinear points have no area
                pass
        out.append(None)
    return out


def intrusions(drawn: Drawn, par: np.ndarray) -> dict:
    """Drawn nodes inside a hull of a genre the style is not a parent-member of, and
    (style, parent) pairs with no drawn copy inside that parent's hull."""
    g_count = par.shape[1]
    hs = hulls(drawn, g_count)
    inside = np.zeros((len(drawn.xy), g_count), dtype=bool)
    for g, h in enumerate(hs):
        if h is not None:
            inside[:, g] = h.find_simplex(drawn.xy) >= 0
        inside[(drawn.host == g) | (drawn.also == g), g] = True
    member = par[drawn.style]
    intr = inside & ~member
    nodes_intruding = int(intr.any(axis=1).sum())
    styles = np.unique(drawn.style)
    covered = np.zeros_like(par)
    for i, s in enumerate(drawn.style):
        covered[s] |= inside[i]
    missing = par[styles] & ~covered[styles]
    return {
        "drawn_nodes": int(len(drawn.xy)),
        "ghost_nodes": int(drawn.ghost.sum()),
        "intruding_nodes": nodes_intruding,
        "intrusion_pairs": int(intr.sum()),
        "omitted_parent_pairs": int(missing.sum()),
        "parent_pairs": int(par[styles].sum()),
    }


def cotag_edges(cotag: np.ndarray, k: int = 3, min_support: int = 50) -> np.ndarray:
    """Each style's top-k co-tagged styles by lift, with at least ``min_support`` releases."""
    c = cotag.astype(float)
    total = np.diag(c).copy()
    n = total.sum()
    with np.errstate(divide="ignore", invalid="ignore"):
        lift = c * n / np.outer(total, total)
    lift[~np.isfinite(lift)] = 0
    np.fill_diagonal(lift, 0)
    lift[c < min_support] = 0
    edges = set()
    for s in range(len(c)):
        nbrs = np.argsort(-lift[s], kind="stable")[:k]
        for t in nbrs:
            if lift[s, t] > 0:
                edges.add((min(s, int(t)), max(s, int(t))))
    return np.array(sorted(edges), dtype=np.int64).reshape(-1, 2)


def place_edges(drawn: Drawn, edges: np.ndarray, with_index: bool = False):
    """E x 2 x 2 segments, each edge between the closest pair of drawn copies.

    With ``with_index``, also the (i, j) drawn-node indices of each segment's ends.
    """
    copies: dict[int, list[int]] = {}
    for i, s in enumerate(drawn.style):
        copies.setdefault(int(s), []).append(i)
    segs, ends = [], []
    for a, b in edges:
        if a not in copies or b not in copies:
            continue
        best = None
        for i in copies[a]:
            for j in copies[b]:
                d = float(((drawn.xy[i] - drawn.xy[j]) ** 2).sum())
                if best is None or d < best[0]:
                    best = (d, i, j)
        segs.append((drawn.xy[best[1]], drawn.xy[best[2]]))
        ends.append((best[1], best[2]))
    out = np.array(segs).reshape(-1, 2, 2)
    if with_index:
        return out, np.array(ends, dtype=np.int64).reshape(-1, 2)
    return out


def intra_hull_crossings(drawn: Drawn, edges: np.ndarray) -> dict:
    """Edges whose two drawn ends share a hull, and the crossings among only those."""
    segs, ends = place_edges(drawn, edges, with_index=True)
    same = drawn.host[ends[:, 0]] == drawn.host[ends[:, 1]]
    return {"intra_hull_edges": int(same.sum()), "intra_hull_crossings": crossings(segs[same])}


def crossings(segs: np.ndarray) -> int:
    """Proper crossings between segments that share no endpoint."""
    if len(segs) < 2:
        return 0
    p, r = segs[:, 0], segs[:, 1] - segs[:, 0]
    n = len(segs)
    total = 0
    for i in range(n - 1):
        q, s = p[i + 1 :], r[i + 1 :]
        rxs = r[i, 0] * s[:, 1] - r[i, 1] * s[:, 0]
        qp = q - p[i]
        t = (qp[:, 0] * s[:, 1] - qp[:, 1] * s[:, 0]) / np.where(rxs == 0, np.nan, rxs)
        u = (qp[:, 0] * r[i, 1] - qp[:, 1] * r[i, 0]) / np.where(rxs == 0, np.nan, rxs)
        eps = 1e-9
        hit = (t > eps) & (t < 1 - eps) & (u > eps) & (u < 1 - eps)
        total += int(np.nansum(hit))
    return total


def edges_through_foreign_hulls(drawn: Drawn, segs_styles: list[tuple[int, int]], segs: np.ndarray, par: np.ndarray, samples: int = 9) -> int:
    """Edges whose interior passes through a hull neither endpoint style belongs to."""
    g_count = par.shape[1]
    hs = hulls(drawn, g_count)
    ts = np.linspace(0.1, 0.9, samples)
    n = 0
    for (a, b), seg in zip(segs_styles, segs):
        pts = seg[0][None, :] + ts[:, None] * (seg[1] - seg[0])[None, :]
        allowed = par[a] | par[b]
        for g, h in enumerate(hs):
            if h is None or allowed[g]:
                continue
            if (h.find_simplex(pts) >= 0).any():
                n += 1
                break
    return n


def nn_scale(xy: np.ndarray) -> float:
    d, _ = cKDTree(xy).query(xy, k=2)
    return float(np.median(d[:, 1]))


def displacement(ref: np.ndarray, x: np.ndarray) -> dict:
    """Displacement in units of the reference layout's median nearest-neighbour distance."""
    scale = nn_scale(ref)
    d = np.linalg.norm(ref - x, axis=1) / scale
    return {
        "median_nn": float(np.median(d)),
        "p95_nn": float(np.percentile(d, 95)),
        "max_nn": float(d.max()),
        "share_over_1nn": float((d > 1).mean()),
    }


def knn_overlap(a: np.ndarray, b: np.ndarray, k: int = 10) -> float:
    """Mean Jaccard of each node's k nearest neighbours in the two layouts."""
    _, ia = cKDTree(a).query(a, k=k + 1)
    _, ib = cKDTree(b).query(b, k=k + 1)
    j = []
    for x, y in zip(ia[:, 1:], ib[:, 1:]):
        sx, sy = set(x.tolist()), set(y.tolist())
        j.append(len(sx & sy) / len(sx | sy))
    return float(np.mean(j))
