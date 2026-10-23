"""Layout, placement rules, and geometry measures on invented structures."""
import numpy as np

import layout


def toy_share():
    # 4 genres; styles 0-2 pure g0, 3-5 pure g1, 6-8 pure g2, 9-11 pure g3,
    # style 12 splits g0/g1 (adjacent on the ring), style 13 splits g0/g2.
    s = np.zeros((14, 4))
    for i in range(12):
        s[i, i // 3] = 1.0
    s[12, [0, 1]] = [0.6, 0.4]
    s[13, [0, 2]] = [0.55, 0.45]
    return s


def test_parents_and_multi_parent_rate():
    s = toy_share()
    assert layout.parents(s, 0.3).sum(axis=1).tolist() == [1] * 12 + [2, 2]
    assert layout.multi_parent_rate(s, 0.3) == 2 / 14
    assert layout.multi_parent_rate(s, 0.5) == 0.0


def test_ring_order_is_exact_and_canonical():
    w = np.zeros((5, 5))
    for a, b in [(0, 3), (3, 1), (1, 4), (4, 2), (2, 0)]:
        w[a, b] = w[b, a] = 10
    w[0, 1] = w[1, 0] = 1
    assert layout.ring_order(w) == [0, 2, 4, 1, 3]
    # The same ring read from any start or direction canonicalises to one order.
    perm = [3, 0, 4, 1, 2]
    wp = w[np.ix_(perm, perm)]
    back = [perm[i] for i in layout.ring_order(wp)]
    i0 = back.index(0)
    rotated = back[i0:] + back[:i0]
    assert rotated in ([0, 2, 4, 1, 3], [0, 3, 1, 4, 2])


def test_geography_dominant_has_no_intrusions_but_omits_secondary_parents():
    s = toy_share()
    years = np.arange(14)
    drawn, meta = layout.geography(s, years, 0.3, "dominant", order=[0, 1, 2, 3])
    m = layout.intrusions(drawn, layout.parents(s, 0.3))
    assert m["intruding_nodes"] == 0
    assert m["omitted_parent_pairs"] == 2


def test_geography_ghost_covers_every_parent():
    s = toy_share()
    drawn, _ = layout.geography(s, np.arange(14), 0.3, "ghost", order=[0, 1, 2, 3])
    m = layout.intrusions(drawn, layout.parents(s, 0.3))
    assert m["ghost_nodes"] == 2 and m["omitted_parent_pairs"] == 0 and m["intruding_nodes"] == 0


def test_geography_border_only_covers_adjacent_parents():
    s = toy_share()
    drawn, _ = layout.geography(s, np.arange(14), 0.3, "border", order=[0, 1, 2, 3])
    m = layout.intrusions(drawn, layout.parents(s, 0.3))
    assert m["omitted_parent_pairs"] == 1  # style 13's g2 is not adjacent to g0


def test_intrusion_detected_in_free_layout():
    s = np.zeros((7, 2))
    s[:4, 0] = 1
    s[4:, 1] = 1
    xy = np.array([[0, 0], [2, 0], [0, 2], [2, 2], [1, 1], [8, 1.2], [8, 0.8]], dtype=float)
    m = layout.intrusions(layout.free_drawn(xy, s), layout.parents(s, 0.3))
    assert m["intruding_nodes"] == 1  # style 4 (g1) sits inside g0's square


def test_crossings():
    segs = np.array([[[0, 0], [1, 1]], [[0, 1], [1, 0]], [[2, 2], [3, 3]], [[1, 1], [2, 0]]], dtype=float)
    assert layout.crossings(segs) == 1  # shared endpoints are not crossings


def test_procrustes_recovers_rotation_and_scale():
    rng = np.random.default_rng(0)
    a = rng.normal(size=(50, 2))
    th = 0.7
    rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    b = 3 * a @ rot + 5
    assert np.allclose(layout.procrustes(a, b), a, atol=1e-9)
    d = layout.displacement(a, layout.procrustes(a, b))
    assert d["max_nn"] < 1e-6


def test_knn_overlap_identity():
    a = np.random.default_rng(1).normal(size=(30, 2))
    assert layout.knn_overlap(a, a, k=5) == 1.0


def test_cotag_edges_respect_support():
    c = np.array([[100, 60, 5], [60, 100, 0], [5, 0, 10]])
    e = layout.cotag_edges(c, k=2, min_support=50)
    assert e.tolist() == [[0, 1]]


def test_ring_order_matches_brute_force():
    import itertools

    rng = np.random.default_rng(3)
    w = rng.random((7, 7))
    w = w + w.T
    np.fill_diagonal(w, 0)

    def score(o):
        return sum(w[o[i], o[(i + 1) % len(o)]] for i in range(len(o)))

    best = max(score([0, *p]) for p in itertools.permutations(range(1, 7)))
    assert abs(score(layout.ring_order(w)) - best) < 1e-9


def test_intra_hull_crossings_counts_only_same_host_edges():
    s = np.zeros((4, 2))
    s[:2, 0] = 1
    s[2:, 1] = 1
    xy = np.array([[0, 0], [1, 1], [0, 1], [1, 0]], dtype=float)
    drawn = layout.free_drawn(xy, s)
    edges = np.array([[0, 1], [2, 3], [0, 2]])
    m = layout.intra_hull_crossings(drawn, edges)
    assert m == {"intra_hull_edges": 2, "intra_hull_crossings": 1}


def test_inner_ref_pins_the_sector_frame():
    rng = np.random.default_rng(2)
    s = np.zeros((30, 2))
    s[:15, 0] = 1
    s[15:, 1] = 1
    prof = rng.random((30, 6))
    a, meta = layout.geography(s, np.arange(30), 0.3, "dominant", order=[0, 1], profiles=prof)
    # The same data, re-run against its own frame, lands on the same positions.
    b, _ = layout.geography(s, np.arange(30), 0.3, "dominant", order=[0, 1], profiles=prof, inner_ref=meta["inner"])
    assert np.allclose(a.xy, b.xy)
