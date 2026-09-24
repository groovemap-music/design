# SPDX-License-Identifier: MIT
"""Train graph embeddings on the pre-cut graph: FastRP (local) and Node2Vec (PyG).

The graph is homogeneous and undirected. Node blocks, in order: artists, releases, labels,
genres, styles, masters. Edges run release-artist (main, and optionally credit and track
artist), release-label, release-genre, release-style, release-master. Only artist rows are
saved; they are the only rows similar-artist retrieval scores.

Every run records wall time, process CPU time, and peak RSS next to the embedding. The
embedding itself lands in the work directory outside the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import time
from pathlib import Path

THREADS = int(os.environ.get("SPIKE_THREADS", "6"))
os.environ.setdefault("OMP_NUM_THREADS", str(THREADS))
os.environ.setdefault("MKL_NUM_THREADS", str(THREADS))
os.environ.setdefault("OPENBLAS_NUM_THREADS", str(THREADS))

import numpy as np  # noqa: E402
import scipy.sparse as sp  # noqa: E402

from catalog import Catalog, load_subset  # noqa: E402


def cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def peak_rss_gb() -> float:
    # macOS reports ru_maxrss in bytes.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9


def build_adjacency(cat: Catalog, *, credits: bool, track: bool, genres: bool, styles: bool, masters: bool) -> tuple[sp.csr_matrix, int]:
    """Symmetric binary adjacency over all node blocks; returns (A, number of artist nodes)."""
    n_a, n_r = cat.n_artists, cat.by.shape[0]
    rel_artist = cat.by.copy().astype(np.float32)
    if credits:
        rel_artist = rel_artist + cat.credits.astype(np.float32)
    if track:
        rel_artist = rel_artist + cat.track.astype(np.float32)
    blocks = [rel_artist, cat.labels.astype(np.float32)]
    if genres:
        blocks.append(cat.genres.astype(np.float32))
    if styles:
        blocks.append(cat.styles.astype(np.float32))
    if masters:
        present = cat.rel_master > 0
        uniq, inv = np.unique(cat.rel_master[present], return_inverse=True)
        rows = np.flatnonzero(present)
        blocks.append(sp.csr_matrix((np.ones(len(rows), np.float32), (rows, inv)), shape=(n_r, len(uniq))))
    # B: release x (artists | labels | genres | styles | masters)
    b = sp.hstack(blocks).tocsr()
    b.data[:] = 1.0
    n_other = b.shape[1]
    # Node order: artists, releases, then the non-artist blocks of B.
    n = n_other + n_r
    b_art = b[:, :n_a]
    b_rest = b[:, n_a:]
    r_off = n_a
    o_off = n_a + n_r
    coo_a = b_art.tocoo()
    coo_o = b_rest.tocoo()
    rows = np.concatenate([coo_a.row + r_off, coo_o.row + r_off])
    cols = np.concatenate([coo_a.col, coo_o.col + o_off])
    a = sp.csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(n, n))
    del b, b_art, b_rest, coo_a, coo_o, rows, cols
    a = (a + a.T).tocsr()
    a.data[:] = 1.0
    return a, n_a


def fastrp(a: sp.csr_matrix, dim: int, weights: list[float], beta: float, seed: int) -> np.ndarray:
    """FastRP (Chen et al., 2019): very sparse random projection of powers of D^-1 A."""
    n = a.shape[0]
    rng = np.random.default_rng(seed)
    deg = np.asarray(a.sum(axis=1)).ravel().astype(np.float64)
    deg[deg == 0] = 1.0
    p = (sp.diags((1.0 / deg).astype(np.float32)) @ a).tocsr()
    # Very sparse projection, s = 3: +-sqrt(3) with probability 1/6 each, else 0.
    # Drawn in row chunks so the float64 intermediates stay small.
    r = np.empty((n, dim), dtype=np.float32)
    values = np.array([-np.sqrt(3), 0.0, np.sqrt(3)], dtype=np.float32)
    for start in range(0, n, 1 << 18):
        u = rng.random((min(1 << 18, n - start), dim), dtype=np.float32)
        r[start : start + len(u)] = values[(u >= 1 / 6).astype(np.int8) + (u >= 5 / 6).astype(np.int8)]
    if beta != 0.0:
        r *= (deg ** beta).astype(np.float32)[:, None]
    out = np.zeros((n, dim), dtype=np.float32)
    current = r
    del r
    step = 1 << 18
    for w in weights:
        current = p @ current
        if w:
            # Row-normalize and accumulate in chunks so no full-size temporary is allocated.
            for start in range(0, n, step):
                block = current[start : start + step]
                norms = np.linalg.norm(block, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                out[start : start + step] += (w / norms) * block
    return out


def node2vec(a: sp.csr_matrix, dim: int, *, p: float, q: float, walk_length: int, context: int, walks_per_node: int,
             epochs: int, batch: int, lr: float, seed: int, log) -> np.ndarray:
    import torch
    from torch_geometric.nn import Node2Vec

    torch.set_num_threads(THREADS)
    torch.manual_seed(seed)
    coo = a.tocoo()
    edge_index = torch.from_numpy(np.vstack([coo.row, coo.col]).astype(np.int64))
    model = Node2Vec(edge_index, embedding_dim=dim, walk_length=walk_length, context_size=context,
                     walks_per_node=walks_per_node, p=p, q=q, num_negative_samples=1, num_nodes=a.shape[0], sparse=True)
    if p != 1.0 or q != 1.0:
        # pyg-lib's walker is uniform-only; torch-cluster implements the biased second-order walk.
        import torch_cluster  # noqa: F401

        model.random_walk_fn = torch.ops.torch_cluster.random_walk
    optimizer = torch.optim.SparseAdam(list(model.parameters()), lr=lr)
    loader = model.loader(batch_size=batch, shuffle=True, num_workers=0)
    for epoch in range(epochs):
        model.train()
        total, steps, started = 0.0, 0, time.time()
        for pos_rw, neg_rw in loader:
            optimizer.zero_grad()
            loss = model.loss(pos_rw, neg_rw)
            loss.backward()
            optimizer.step()
            total += loss.item()
            steps += 1
            if steps % 500 == 0:
                log(f"epoch {epoch} step {steps}/{len(loader)} loss {total / steps:.4f} {time.time() - started:.0f}s")
        log(f"epoch {epoch} done loss {total / max(steps, 1):.4f} {time.time() - started:.0f}s")
    return model.embedding.weight.detach().numpy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("subset", type=Path)
    parser.add_argument("out", type=Path, help="output .npy for artist embeddings; a .json sidecar holds the run record")
    parser.add_argument("--method", choices=["fastrp", "node2vec"], required=True)
    parser.add_argument("--dim", type=int, default=128)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--no-credits", action="store_true")
    parser.add_argument("--no-track", action="store_true")
    parser.add_argument("--no-genres", action="store_true")
    parser.add_argument("--no-styles", action="store_true")
    parser.add_argument("--no-masters", action="store_true")
    parser.add_argument("--weights", default="0,1,1,1")
    parser.add_argument("--beta", type=float, default=0.0)
    parser.add_argument("--p", type=float, default=1.0)
    parser.add_argument("--q", type=float, default=1.0)
    parser.add_argument("--walk-length", type=int, default=20)
    parser.add_argument("--context", type=int, default=10)
    parser.add_argument("--walks-per-node", type=int, default=10)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--lr", type=float, default=0.01)
    args = parser.parse_args()

    started_wall, started_cpu = time.time(), cpu_seconds()

    def log(msg: str) -> None:
        print(f"[{time.time() - started_wall:7.0f}s rss {peak_rss_gb():.2f}GB] {msg}", flush=True)

    full, pre, _seeds = load_subset(args.subset)
    cat = full.restrict(pre)
    a, n_art = build_adjacency(cat, credits=not args.no_credits, track=not args.no_track, genres=not args.no_genres,
                               styles=not args.no_styles, masters=not args.no_masters)
    graph = {"nodes": int(a.shape[0]), "undirected_edges": int(a.nnz // 2), "artist_nodes": int(n_art)}
    log(f"graph {graph}")
    load_wall = time.time() - started_wall
    train_wall0, train_cpu0 = time.time(), cpu_seconds()
    if args.method == "fastrp":
        emb = fastrp(a, args.dim, [float(x) for x in args.weights.split(",")], args.beta, args.seed)
    else:
        emb = node2vec(a, args.dim, p=args.p, q=args.q, walk_length=args.walk_length, context=args.context,
                       walks_per_node=args.walks_per_node, epochs=args.epochs, batch=args.batch, lr=args.lr,
                       seed=args.seed, log=log)
    record = {
        "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "graph": graph,
        "load_wall_s": round(load_wall, 1),
        "train_wall_s": round(time.time() - train_wall0, 1),
        "train_cpu_s": round(cpu_seconds() - train_cpu0, 1),
        "peak_rss_gb": round(peak_rss_gb(), 2),
        "threads": THREADS,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.out, emb[:n_art].astype(np.float32))
    args.out.with_suffix(".json").write_text(json.dumps(record, indent=2))
    log(json.dumps(record))


if __name__ == "__main__":
    main()
