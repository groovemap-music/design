"""Keyed projection and FastRP on an invented graph."""
import numpy as np

import fastrp


def test_projection_row_depends_only_on_key():
    keys = fastrp.node_keys("artist", np.array([5, 7, 9]))
    a = fastrp.projection_block(keys, range(0, 8))
    b = fastrp.projection_block(keys[[2, 0]], range(0, 8))
    assert np.array_equal(a[[2, 0]], b)
    block = fastrp.projection_block(fastrp.node_keys("label", np.arange(1, 6001)), range(4))
    assert np.isclose(np.abs(block), 0).sum() + np.isclose(np.abs(block), np.sqrt(3)).sum() == block.size
    assert abs(np.isclose(block, 0).mean() - 2 / 3) < 0.02  # s = 3: two thirds zero


def test_unrelated_component_leaves_vectors_unchanged():
    src = fastrp.node_keys("release", np.array([1, 1, 2]))
    dst = fastrp.node_keys("artist", np.array([10, 11, 10]))
    keys, m = fastrp.adjacency(src, dst)
    rows = np.flatnonzero((keys >> np.uint64(56)) == fastrp.KIND["artist"])
    v1 = fastrp.fastrp(keys, m, rows)
    src2 = np.concatenate([src, fastrp.node_keys("release", np.array([3]))])
    dst2 = np.concatenate([dst, fastrp.node_keys("artist", np.array([12]))])
    keys2, m2 = fastrp.adjacency(src2, dst2)
    rows2 = np.flatnonzero(np.isin(keys2, keys[rows]))
    v2 = fastrp.fastrp(keys2, m2, rows2)
    assert np.allclose(v1, v2)


def test_genre_and_style_with_same_name_stay_distinct():
    g = fastrp.node_keys("genre", np.array([fastrp.name_key("Reggae")], dtype=np.uint64))
    s = fastrp.node_keys("style", np.array([fastrp.name_key("Reggae")], dtype=np.uint64))
    assert g[0] != s[0]
