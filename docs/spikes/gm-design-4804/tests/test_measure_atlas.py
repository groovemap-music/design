"""The whole concept B measurement on invented aggregates for two 'dumps'."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

import aggregate

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def synthetic(seed: int, drift: float) -> dict:
    rng = np.random.default_rng(0)
    s_count, g_count = 40, 6
    base = rng.dirichlet(np.full(g_count, 0.3), size=s_count)
    noise = np.random.default_rng(seed).dirichlet(np.full(g_count, 1.0), size=s_count)
    share = (1 - drift) * base + drift * noise
    size = rng.integers(200, 5000, size=s_count)
    sg = np.round(share * size[:, None] * 1.2).astype(np.int64)
    years = np.zeros((s_count, aggregate.NY), dtype=np.int64)
    start = rng.integers(1950 - aggregate.YEAR0, 2010 - aggregate.YEAR0, size=s_count)
    for s in range(s_count):
        span = np.arange(aggregate.NY - start[s])
        curve = np.exp(-((span - 15) ** 2) / 200.0) + 0.2
        years[s, start[s]:] = np.round(size[s] / curve.sum() * curve * (1 + drift * np.random.default_rng(seed + s).random(len(span))))
    cot = rng.integers(0, 80, size=(s_count, s_count))
    cot = np.triu(cot, 1) + np.triu(cot, 1).T
    np.fill_diagonal(cot, size)
    first = np.where((years > 0).any(axis=1), (years > 0).argmax(axis=1) + aggregate.YEAR0, 0)
    gy = np.zeros((g_count, aggregate.NY), dtype=np.int64)
    for g in range(g_count):
        gy[g] = (years * share[:, [g]]).sum(axis=0).astype(np.int64)
    return {
        "style_genre_rel": sg,
        "style_rel": size,
        "style_year_rel": years,
        "style_year_mst": years // 3,
        "genre_year_rel": gy,
        "cotag": cot,
        "partof": (share > 0.15).astype(np.int8),
        "first_year_style": first,
        "first_year_genre": np.where((gy > 0).any(axis=1), (gy > 0).argmax(axis=1) + aggregate.YEAR0, 0),
        "counts": np.array([1000, 100, 900, 800, 10, 300, 500, int(size.sum())]),
        "_styles": np.array([f"style {i:02d}" for i in range(s_count)], dtype=object),
        "_genres": np.array([f"genre {i}" for i in range(g_count)], dtype=object),
    }


def test_measure_atlas_end_to_end(tmp_path):
    aggregate.save(synthetic(1, 0.0), tmp_path / "aggregates_early.npz")
    aggregate.save(synthetic(2, 0.02), tmp_path / "aggregates_late.npz")
    rng = np.random.default_rng(5)
    v = rng.normal(size=(40, 16)).astype(np.float32)
    np.savez(tmp_path / "va.npz", style_vectors=v)
    np.savez(tmp_path / "vb.npz", style_vectors=v + 0.01 * rng.normal(size=v.shape).astype(np.float32))
    out = tmp_path / "atlas.json"
    subprocess.run(
        [sys.executable, str(SCRIPTS / "measure_atlas.py"), str(tmp_path / "aggregates_early.npz"), str(tmp_path / "aggregates_late.npz"), str(out),
         "--vectors", str(tmp_path / "va.npz"), str(tmp_path / "vb.npz")],
        check=True, capture_output=True, cwd=SCRIPTS,
    )
    res = json.loads(out.read_text())
    assert res["population"]["styles_common"] == 40
    geo = res["layout"]["geography"]
    assert geo["ghost"]["omitted_parent_pairs"] == 0
    assert geo["dominant"]["ghost_nodes"] == 0
    assert res["layout"]["embedding"]["vector_cosine_across_dumps"]["median"] > 0.99
    assert 0 <= res["lifecycle"]["release_year"]["dump_flip_headline_pct"] <= 100
    text = out.read_text()
    assert "style 0" not in text  # no names in the committed shape
