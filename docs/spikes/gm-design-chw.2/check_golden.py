# SPDX-License-Identifier: MIT
"""Sanity check: the ported baseline reproduces catalog-api's own output on the golden set.

catalog-api is used read-only: its existing virtualenv runs ``GoldenGraph.candidate_artists``
and ``compute_similar_artists`` for every golden artist, and this spike's port
(:class:`catalog.Heuristic`) must return the same ids in the same order with the same
similarity. The dense scorer must agree with the production path on every returned pair.

Usage: ``uv run python check_golden.py /path/to/catalog-api``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import scipy.sparse as sp

from catalog import Catalog, Heuristic

REFERENCE = r"""
import json
from api.evaluation.fixtures import load_golden_set
from api.evaluation.graph import GoldenGraph
from api.queries.recommend_queries import compute_similar_artists
golden = load_golden_set()
graph = GoldenGraph(golden)
out = {}
for artist_id in sorted(golden.artists):
    rows = compute_similar_artists(graph.artist_profile(artist_id), graph.candidate_artists(artist_id), limit=20)
    out[artist_id] = [[row["artist_id"], row["similarity"]] for row in rows]
print(json.dumps(out))
"""


def golden_catalog(catalog_api: Path) -> tuple[Catalog, np.ndarray]:
    data = json.loads((catalog_api / "tests/fixtures/golden/catalog.json").read_text())
    artists = sorted(a["id"] for a in data["artists"])
    names = {a["id"]: a["name"] for a in data["artists"]}
    labels = sorted(label["id"] for label in data["labels"])
    label_names = {label["id"]: label["name"] for label in data["labels"]}
    genres = sorted({g for r in data["releases"] for g in r["genres"]})
    styles = sorted({s for r in data["releases"] for s in r["styles"]})
    a_ix = {a: i for i, a in enumerate(artists)}
    l_ix = {x: i for i, x in enumerate(labels)}
    g_ix = {x: i for i, x in enumerate(genres)}
    s_ix = {x: i for i, x in enumerate(styles)}
    releases = data["releases"]

    def incidence(lists: list[list[int]], width: int) -> sp.csr_matrix:
        rows = [i for i, values in enumerate(lists) for _ in values]
        cols = [c for values in lists for c in values]
        return sp.csr_matrix((np.ones(len(cols), dtype=np.int8), (rows, cols)), shape=(len(lists), width))

    n = len(releases)
    empty = sp.csr_matrix((n, len(artists)), dtype=np.int8)
    cat = Catalog(
        by=incidence([[a_ix[a] for a in r["artist_ids"] if a in a_ix] for r in releases], len(artists)),
        credits=empty,
        track=empty,
        labels=incidence([[l_ix[r["label_id"]]] for r in releases], len(labels)),
        genres=incidence([[g_ix[g] for g in r["genres"]] for r in releases], len(genres)),
        styles=incidence([[s_ix[s] for s in r["styles"]] for r in releases], len(styles)),
        rel_date=np.array([r["year"] * 10000 for r in releases], dtype=np.int32),
        rel_fam=np.zeros(n, dtype=np.int16),
        rel_master=np.zeros(n, dtype=np.int32),
        rel_id=np.arange(n, dtype=np.int32),
        artist_ids=np.array(artists),
        label_ids=np.array(labels),
        genre_names=genres,
        style_names=styles,
        artist_names=[names[a] for a in artists],
        label_names=[label_names[x] for x in labels],
    )
    # The adapter breaks count ties by artist id string; the ids sort in index order.
    return cat, np.arange(len(artists))


def main() -> None:
    catalog_api = Path(sys.argv[1]).resolve()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    raw = subprocess.run(
        [str(catalog_api / ".venv/bin/python"), "-c", REFERENCE], cwd=catalog_api, env=env, check=True, capture_output=True, text=True
    ).stdout
    reference = json.loads(raw)

    cat, key = golden_catalog(catalog_api)
    heuristic = Heuristic(cat, key)
    ids = list(cat.artist_ids)
    mismatches = 0
    pairs = 0
    max_dense_gap = 0.0
    for i, artist_id in enumerate(ids):
        mine = [[ids[row["artist_id"]], row["similarity"]] for row in heuristic.similar(i)]
        if mine != reference[artist_id]:
            mismatches += 1
            print(f"MISMATCH {artist_id}: ref={reference[artist_id][:5]} mine={mine[:5]}")
        dense = heuristic.scores(np.array([i]))[0]
        for row in heuristic.similar(i):
            pairs += 1
            max_dense_gap = max(max_dense_gap, abs(float(dense[row["artist_id"]]) - row["similarity"]))
    result = {
        "golden_artists": len(ids),
        "artists_with_results": sum(1 for v in reference.values() if v),
        "ranked_pairs": sum(len(v) for v in reference.values()),
        "mismatched_artists": mismatches,
        "dense_vs_production_max_abs_gap": round(max_dense_gap, 6),
        "dense_pairs_checked": pairs,
    }
    print(json.dumps(result, indent=2))
    sys.exit(1 if mismatches or max_dense_gap > 1e-4 else 0)


if __name__ == "__main__":
    main()
