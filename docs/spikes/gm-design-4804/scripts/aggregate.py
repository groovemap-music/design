#!/usr/bin/env python3
"""Fold one dump's compact arrays into the aggregates every measurement reads.

Inputs are ``releases_<dump>.npz`` and ``masters_<dump>.npz`` from ``extract_dump.py``.
The output ``aggregates_<dump>.npz`` holds, over a fixed name order (styles and genres
sorted by name, so two dumps line up by index):

- ``style_genre_rel``: S x G releases carrying both the style and the genre;
- ``style_rel``: releases per style (a release with two genres counts once);
- ``style_year_rel`` / ``style_year_mst``: S x Y releases per style per release year, and
  masters per style per master year (Y covers YEAR0..YEAR1);
- ``genre_year_rel``: G x Y releases per genre per year;
- ``cotag``: S x S releases carrying both styles (diagonal = ``style_rel``);
- ``partof``: S x G 0/1, the product's ``graph.part_of`` rule: some release or master
  with exactly one genre carries the style and that genre;
- ``first_year_style`` / ``first_year_genre``: the earliest release year > 0, as
  graphinator sets ``first_year`` (0 when never dated);
- ``counts``: scalar population counts (releases, masters, dated, styled, ...).

These aggregates are derived from Discogs records and stay in the cache. Only numbers
computed from them are committed.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from scipy import sparse

YEAR0, YEAR1 = 1860, 2030
NY = YEAR1 - YEAR0 + 1


def load(path: Path) -> tuple[dict[str, np.ndarray], dict]:
    arrays = dict(np.load(path))
    vocab = json.loads(path.with_suffix(".vocab.json").read_text())
    return arrays, vocab


def genre_bits(mask: np.ndarray, n_genres: int) -> np.ndarray:
    """N x G boolean matrix from the per-record genre bitmask."""
    out = np.zeros((len(mask), n_genres), dtype=bool)
    for bit in range(n_genres):
        out[:, bit] = (mask >> np.uint32(bit)) & 1
    return out


def style_pairs(arr: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """(record index, local style index) for every style tag."""
    ptr = arr["style_ptr"]
    rec = np.repeat(np.arange(len(ptr) - 1), np.diff(ptr))
    return rec, arr["style_idx"].astype(np.int64)


def remap(local_names: list[str], global_index: dict[str, int]) -> np.ndarray:
    return np.array([global_index[n] for n in local_names], dtype=np.int64)


def fold(rel: dict, rel_vocab: dict, mst: dict, mst_vocab: dict) -> dict[str, np.ndarray]:
    styles = sorted(set(rel_vocab["styles"]) | set(mst_vocab["styles"]))
    genres = sorted(set(rel_vocab["genres"]) | set(mst_vocab["genres"]))
    s_index = {n: i for i, n in enumerate(styles)}
    g_index = {n: i for i, n in enumerate(genres)}
    S, G = len(styles), len(genres)
    out: dict[str, np.ndarray] = {}

    def per_kind(arr: dict, vocab: dict):
        n = len(arr["id"])
        local_g = genre_bits(arr["genre_mask"], len(vocab["genres"]))
        gmat = np.zeros((n, G), dtype=bool)
        gmat[:, remap(vocab["genres"], g_index)] = local_g
        rec, local_s = style_pairs(arr)
        s = remap(vocab["styles"], s_index)[local_s] if len(local_s) else local_s
        return n, gmat, rec, s

    n_rel, g_rel, rec_r, s_r = per_kind(rel, rel_vocab)
    n_mst, g_mst, rec_m, s_m = per_kind(mst, mst_vocab)
    year_r = rel["year"].astype(np.int64)
    year_m = mst["year"].astype(np.int64)

    # Release x style incidence; S x G and S x S fall out of sparse products.
    m_rs = sparse.csr_matrix((np.ones(len(s_r), dtype=np.int32), (rec_r, s_r)), shape=(n_rel, S))
    gr, gc = np.nonzero(g_rel)
    m_rg = sparse.csr_matrix((np.ones(len(gr), dtype=np.int32), (gr, gc)), shape=(n_rel, G))
    out["style_genre_rel"] = np.asarray((m_rs.T @ m_rg).todense(), dtype=np.int64)
    out["cotag"] = np.asarray((m_rs.T @ m_rs).todense(), dtype=np.int64)
    out["style_rel"] = np.bincount(s_r, minlength=S).astype(np.int64)

    def yearly(rec: np.ndarray, s: np.ndarray, years: np.ndarray) -> np.ndarray:
        y = years[rec]
        ok = y > 0
        flat = s[ok] * NY + (y[ok] - YEAR0)
        return np.bincount(flat, minlength=S * NY).reshape(S, NY).astype(np.int64)

    out["style_year_rel"] = yearly(rec_r, s_r, year_r)
    out["style_year_mst"] = yearly(rec_m, s_m, year_m)
    gy = np.zeros((G, NY), dtype=np.int64)
    dated = year_r > 0
    for g in range(G):
        sel = g_rel[:, g] & dated
        gy[g] = np.bincount(year_r[sel] - YEAR0, minlength=NY)
    out["genre_year_rel"] = gy

    # graph.part_of: documents (releases and masters) with exactly one genre.
    partof = np.zeros((S, G), dtype=np.int8)
    for gmat, rec, s in ((g_rel, rec_r, s_r), (g_mst, rec_m, s_m)):
        single = gmat.sum(axis=1) == 1
        only = gmat.argmax(axis=1)
        keep = single[rec]
        partof[s[keep], only[rec[keep]]] = 1
    out["partof"] = partof

    def first_year(rows: np.ndarray) -> np.ndarray:
        has = rows > 0
        first = np.where(has.any(axis=1), has.argmax(axis=1) + YEAR0, 0)
        return first.astype(np.int64)

    out["first_year_style"] = first_year(out["style_year_rel"])
    out["first_year_genre"] = first_year(gy)

    styled = np.diff(rel["style_ptr"]) > 0
    out["counts"] = np.array(
        [
            n_rel,
            n_mst,
            int(dated.sum()),
            int(styled.sum()),
            int((g_rel.sum(axis=1) == 0).sum()),
            int((g_rel.sum(axis=1) >= 2).sum()),
            int((rel["master"] > 0).sum()),
            len(s_r),
        ],
        dtype=np.int64,
    )
    out["_styles"] = np.array(styles, dtype=object)
    out["_genres"] = np.array(genres, dtype=object)
    return out


COUNT_NAMES = [
    "releases",
    "masters",
    "releases_dated",
    "releases_styled",
    "releases_no_genre",
    "releases_multi_genre",
    "releases_with_master",
    "release_style_tags",
]


def save(out: dict[str, np.ndarray], path: Path) -> None:
    names = {"styles": list(out["_styles"]), "genres": list(out["_genres"])}
    np.savez_compressed(path, **{k: v for k, v in out.items() if not k.startswith("_")})
    path.with_suffix(".names.json").write_text(json.dumps(names, ensure_ascii=False))


def load_aggregates(path: Path) -> dict:
    data = dict(np.load(path))
    data.update(json.loads(path.with_suffix(".names.json").read_text()))
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("releases", type=Path)
    ap.add_argument("masters", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    started = time.time()
    rel, rel_vocab = load(args.releases)
    mst, mst_vocab = load(args.masters)
    out = fold(rel, rel_vocab, mst, mst_vocab)
    save(out, args.out)
    print(json.dumps({"seconds": round(time.time() - started, 1), **dict(zip(COUNT_NAMES, out["counts"].tolist()))}))


if __name__ == "__main__":
    main()
