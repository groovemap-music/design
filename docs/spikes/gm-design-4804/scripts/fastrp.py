#!/usr/bin/env python3
"""Reconstruct ADR 0013-style artist vectors from one dump and aggregate them to styles.

This is a reconstruction, not the production vectors (those live in
``public.artist_embeddings``, which this spike cannot reach). It follows the documented
production configuration in analytics-engine ``docs/embeddings.md``: 128 dimensions,
iteration weights 0,1,1,1,1, beta 0, self term 0.05 x the vertex's own normalized
projection row, a very sparse Achlioptas projection (s = 3) whose row is a function of the
vertex key alone, and two passes over column blocks. The edge set is the subset the
compact arrays carry: ``by_artist``, ``on_label``, ``derived_from``, ``in_genre``,
``in_style``, ``master_by_artist``, ``master_in_genre``, ``master_in_style``. It omits
edges-v3's credited and track-level artist relations.

Because the projection row is keyed, two dumps' vectors are directly comparable: a style
vector's cosine across dumps needs no alignment.

Style vector = mean of the unit artist vectors of every main artist on a release carrying
the style, weighted by how many such releases the artist has.

Usage:
    python fastrp.py releases_<dump>.npz masters_<dump>.npz aggregates_<dump>.npz OUT.npz
"""
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path

import numpy as np
from scipy import sparse

DIM = 128
WEIGHTS = (0.0, 1.0, 1.0, 1.0, 1.0)
SELF_WEIGHT = 0.05
SEED = 20260924
BLOCK = 4
KIND = {"release": 1, "master": 2, "artist": 3, "label": 4, "genre": 5, "style": 6}
MASK64 = np.uint64(0xFFFFFFFFFFFFFFFF)


def splitmix64(x: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):
        z = (x + np.uint64(0x9E3779B97F4A7C15)) & MASK64
        z = ((z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)) & MASK64
        z = ((z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)) & MASK64
        return z ^ (z >> np.uint64(31))


def name_key(name: str) -> int:
    return int.from_bytes(hashlib.blake2b(name.encode(), digest_size=5).digest(), "big")


def node_keys(kind: str, ids: np.ndarray) -> np.ndarray:
    return (np.uint64(KIND[kind]) << np.uint64(56)) | ids.astype(np.uint64)


def projection_block(keys: np.ndarray, columns: range) -> np.ndarray:
    """Achlioptas s=3 rows keyed by vertex: +sqrt3 / -sqrt3 with p 1/6 each, else 0."""
    out = np.zeros((len(keys), len(columns)), dtype=np.float32)
    base = splitmix64(keys ^ np.uint64(SEED))
    for j, col in enumerate(columns):
        h = splitmix64(base ^ splitmix64(np.full(1, col, dtype=np.uint64)))
        r = (h % np.uint64(6)).astype(np.int8)
        out[r == 0, j] = np.sqrt(3.0)
        out[r == 1, j] = -np.sqrt(3.0)
    return out


def build_graph(rel: dict, mst: dict, styles: list[str], genres: list[str], rel_vocab: dict, mst_vocab: dict):
    # A genre and a style can share a name (Reggae is both), so the kind bits matter.
    s_key = node_keys("style", np.array([name_key(n) for n in styles], dtype=np.uint64))
    g_key = node_keys("genre", np.array([name_key(n) for n in genres], dtype=np.uint64))
    s_idx = {n: i for i, n in enumerate(styles)}
    g_idx = {n: i for i, n in enumerate(genres)}

    def csr_pairs(ptr: np.ndarray, vals: np.ndarray, owner_keys: np.ndarray):
        rec = np.repeat(np.arange(len(ptr) - 1), np.diff(ptr))
        return owner_keys[rec], vals

    def genre_pairs(mask: np.ndarray, vocab_genres: list[str], owner_keys: np.ndarray):
        src, dst = [], []
        for bit, name in enumerate(vocab_genres):
            sel = ((mask >> np.uint32(bit)) & 1).astype(bool)
            src.append(owner_keys[sel])
            dst.append(np.full(int(sel.sum()), g_key[g_idx[name]], dtype=np.uint64))
        return np.concatenate(src), np.concatenate(dst)

    r_keys = node_keys("release", rel["id"])
    m_keys = node_keys("master", mst["id"])
    src, dst = [], []
    a, b = csr_pairs(rel["artist_ptr"], node_keys("artist", rel["artist_ids"]), r_keys)
    src.append(a); dst.append(b)
    a, b = csr_pairs(rel["label_ptr"], node_keys("label", rel["label_ids"]), r_keys)
    src.append(a); dst.append(b)
    has_master = rel["master"] > 0
    src.append(r_keys[has_master]); dst.append(node_keys("master", rel["master"][has_master]))
    local = np.array([s_key[s_idx[n]] for n in rel_vocab["styles"]], dtype=np.uint64)
    a, b = csr_pairs(rel["style_ptr"], local[rel["style_idx"]], r_keys)
    src.append(a); dst.append(b)
    a, b = genre_pairs(rel["genre_mask"], rel_vocab["genres"], r_keys)
    src.append(a); dst.append(b)
    a, b = csr_pairs(mst["artist_ptr"], node_keys("artist", mst["artist_ids"]), m_keys)
    src.append(a); dst.append(b)
    local = np.array([s_key[s_idx[n]] for n in mst_vocab["styles"]], dtype=np.uint64)
    a, b = csr_pairs(mst["style_ptr"], local[mst["style_idx"]], m_keys)
    src.append(a); dst.append(b)
    a, b = genre_pairs(mst["genre_mask"], mst_vocab["genres"], m_keys)
    src.append(a); dst.append(b)
    src = np.concatenate(src)
    dst = np.concatenate(dst)
    return src, dst, s_key, g_key


def adjacency(src: np.ndarray, dst: np.ndarray):
    keys = np.unique(np.concatenate([src, dst]))
    si = np.searchsorted(keys, src).astype(np.int32)
    di = np.searchsorted(keys, dst).astype(np.int32)
    del src, dst
    keep = si != di
    si, di = si[keep], di[keep]
    n = len(keys)
    rows = np.concatenate([si, di])
    cols = np.concatenate([di, si])
    del si, di
    a = sparse.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(n, n))
    del rows, cols
    a.sum_duplicates()
    # Parallel edges collapse; then D^-1 A in place (row i scaled by 1 / degree).
    deg = np.diff(a.indptr).astype(np.float32)
    inv = np.divide(1.0, deg, out=np.zeros_like(deg), where=deg > 0)
    a.data[:] = np.repeat(inv, np.diff(a.indptr))
    return keys, a


def fastrp(keys: np.ndarray, m, rows: np.ndarray) -> np.ndarray:
    """Two passes over column blocks; returns float32 vectors for ``rows`` only."""
    n = len(keys)
    powers = len(WEIGHTS)
    sq = np.zeros((n, powers + 1), dtype=np.float64)  # last column: projection itself
    for start in range(0, DIM, BLOCK):
        x = projection_block(keys, range(start, min(DIM, start + BLOCK)))
        sq[:, powers] += (x.astype(np.float64) ** 2).sum(axis=1)
        for p in range(powers):
            x = m @ x
            sq[:, p] += (x.astype(np.float64) ** 2).sum(axis=1)
    scale = np.where(sq > 0, 1.0 / np.sqrt(np.maximum(sq, 1e-300)), 0.0)[rows]
    out = np.zeros((len(rows), DIM), dtype=np.float32)
    for start in range(0, DIM, BLOCK):
        cols = slice(start, min(DIM, start + BLOCK))
        x = projection_block(keys, range(cols.start, cols.stop))
        acc = SELF_WEIGHT * x[rows] * scale[:, [powers]]
        for p in range(powers):
            x = m @ x
            if WEIGHTS[p]:
                acc += WEIGHTS[p] * x[rows] * scale[:, [p]]
        out[:, cols] = acc
    return out


def style_vectors(rel: dict, rel_vocab: dict, styles: list[str], artist_keys: np.ndarray, artist_vecs: np.ndarray) -> np.ndarray:
    s_idx = {n: i for i, n in enumerate(styles)}
    local = np.array([s_idx[n] for n in rel_vocab["styles"]], dtype=np.int64)
    n_rel = len(rel["id"])
    rec = np.repeat(np.arange(n_rel), np.diff(rel["style_ptr"]))
    m_rs = sparse.csr_matrix((np.ones(len(rec), np.float32), (rec, local[rel["style_idx"]])), shape=(n_rel, len(styles)))
    rec_a = np.repeat(np.arange(n_rel), np.diff(rel["artist_ptr"]))
    a_keys = node_keys("artist", rel["artist_ids"])
    pos = np.searchsorted(artist_keys, a_keys)
    pos = np.minimum(pos, len(artist_keys) - 1)
    ok = artist_keys[pos] == a_keys
    m_ra = sparse.csr_matrix((np.ones(int(ok.sum()), np.float32), (rec_a[ok], pos[ok])), shape=(n_rel, len(artist_keys)))
    w = (m_rs.T @ m_ra).tocsr()
    unit = artist_vecs / np.maximum(np.linalg.norm(artist_vecs, axis=1, keepdims=True), 1e-12)
    total = np.asarray(w.sum(axis=1)).ravel()
    vec = (w @ unit) / np.maximum(total, 1)[:, None]
    return vec.astype(np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("releases", type=Path)
    ap.add_argument("masters", type=Path)
    ap.add_argument("aggregates", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    t0 = time.time()
    rel = dict(np.load(args.releases))
    mst = dict(np.load(args.masters))
    rel_vocab = json.loads(args.releases.with_suffix(".vocab.json").read_text())
    mst_vocab = json.loads(args.masters.with_suffix(".vocab.json").read_text())
    names = json.loads(args.aggregates.with_suffix(".names.json").read_text())
    src, dst, _, _ = build_graph(rel, mst, names["styles"], names["genres"], rel_vocab, mst_vocab)
    n_edges = len(src)
    keys, m = adjacency(src, dst)
    del src, dst
    t1 = time.time()
    kinds = (keys >> np.uint64(56)).astype(np.int64)
    artist_rows = np.flatnonzero(kinds == KIND["artist"])
    vecs = fastrp(keys, m, artist_rows)
    t2 = time.time()
    svec = style_vectors(rel, rel_vocab, names["styles"], keys[artist_rows], vecs)
    t3 = time.time()
    np.savez(args.out, style_vectors=svec)
    stats = {
        "nodes": int(len(keys)),
        "edge_rows": int(n_edges),
        "nnz": int(m.nnz),
        "artists": int(len(artist_rows)),
        "zero_artist_vectors": int((np.abs(vecs).sum(axis=1) == 0).sum()),
        "graph_seconds": round(t1 - t0, 1),
        "fastrp_seconds": round(t2 - t1, 1),
        "style_seconds": round(t3 - t2, 1),
        "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**30, 2),
    }
    args.out.with_suffix(".stats.json").write_text(json.dumps(stats))
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
