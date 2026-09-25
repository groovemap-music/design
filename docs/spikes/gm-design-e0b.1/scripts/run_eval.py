#!/usr/bin/env python3
"""Core evaluation for one entity kind, at realistic candidate-pool scale.

Differs from gm-design-chw.3's run_eval.py in HOW retrieval is computed, not
in WHAT is measured, because chw.3's approach (store embeddings in pgvector,
one exact flat-scan SQL query per method per query row) does not scale from a
20k-row pool to a >=1M / all-labels pool on a 2-CPU/8GB Docker VM: per-query
latency scales ~linearly with pool size on an unindexed scan, which would
turn a few-thousand-query eval into many hours.

Instead:
  - pg_trgm: Postgres still does the work, but via a GiST trgm_ops index
    (`ORDER BY name <-> query LIMIT k`, index-accelerated KNN), not a
    sequential scan -- the DB never holds embeddings, only (kind, discogs_id,
    name), so its footprint stays small regardless of dense pool size.
  - dense (e5-small, bge-m3): embeddings never touch Postgres. Candidates and
    queries are encoded once, held as in-process numpy arrays, and scored
    with batched matrix multiplication (BLAS-backed, exact cosine similarity
    since embeddings are L2-normalized) -- one method's candidate matrix at a
    time, freed before the next, to bound peak RAM on the host running this.

RRF fusion is computed exactly as in chw.3: rank-based reciprocal fusion,
k=60, over each method's own top-K list.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
import torch  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

NUM_THREADS = int(os.environ.get("SPIKE_NUM_THREADS", "6"))
torch.set_num_threads(NUM_THREADS)

DSN = os.environ.get("SPIKE_DSN", "host=127.0.0.1 port=15433 dbname=identity_spike user=postgres password=spike")
RRF_K = 60
TOPK = 50


def load_jsonl(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        cur.execute("SET maintenance_work_mem = '1GB'")
        cur.execute("DROP TABLE IF EXISTS candidates")
        cur.execute(
            """
            CREATE TABLE candidates (
                id BIGSERIAL PRIMARY KEY,
                discogs_id TEXT NOT NULL,
                name TEXT NOT NULL
            )
            """
        )
    conn.commit()


def load_candidates_trgm(conn: psycopg.Connection, candidates_path: str) -> int:
    n = 0
    skipped = 0
    with conn.cursor() as cur:
        with cur.copy("COPY candidates (discogs_id, name) FROM STDIN") as copy:
            with open(candidates_path) as f:
                for line in f:
                    rec = json.loads(line)
                    if not rec.get("discogs_id"):
                        # A handful of dump records are malformed (missing id); the pool build
                        # keeps them as inert rows rather than dropping silently pre-COPY, so
                        # filter here where it's visible and counted.
                        skipped += 1
                        continue
                    copy.write_row((rec["discogs_id"], rec.get("name") or ""))
                    n += 1
    if skipped:
        print(f"[trgm] skipped {skipped} malformed candidate row(s) with no discogs_id", file=sys.stderr)
    conn.commit()
    with conn.cursor() as cur:
        t0 = time.monotonic()
        cur.execute("CREATE INDEX candidates_name_trgm ON candidates USING gist (name gist_trgm_ops)")
        conn.commit()
        index_seconds = time.monotonic() - t0
        cur.execute("ANALYZE candidates")
        conn.commit()
    print(f"[trgm] loaded {n} candidates, GiST trgm index built in {index_seconds:.1f}s", file=sys.stderr)
    return n


def trgm_ranks(conn: psycopg.Connection, queries: list[dict]) -> tuple[list[list[str]], float]:
    out = []
    t0 = time.monotonic()
    with conn.cursor() as cur:
        for i, q in enumerate(queries):
            cur.execute(
                "SELECT discogs_id FROM candidates ORDER BY name <-> %s LIMIT %s",
                (q["query_name"], TOPK),
            )
            out.append([r[0] for r in cur.fetchall()])
            if (i + 1) % 1000 == 0:
                print(f"[trgm] scored {i + 1}/{len(queries)}", file=sys.stderr)
    return out, time.monotonic() - t0


def embed_texts(model: SentenceTransformer, texts: list[str], prefix: str, batch_size: int) -> tuple[np.ndarray, float]:
    prefixed = [f"{prefix}{t}" if prefix else t for t in texts]
    t0 = time.monotonic()
    vecs = model.encode(
        prefixed,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype(np.float32)
    return vecs, time.monotonic() - t0


def dense_ranks(
    cand_ids: list[str], cand_vecs: np.ndarray, query_vecs: np.ndarray, query_batch: int = 200
) -> list[list[str]]:
    """Exact cosine top-K via batched matmul (embeddings are L2-normalized)."""
    out: list[list[str]] = []
    n = query_vecs.shape[0]
    cand_ids_arr = np.array(cand_ids)
    for start in range(0, n, query_batch):
        batch = query_vecs[start : start + query_batch]
        sims = batch @ cand_vecs.T  # (batch, n_candidates)
        k = min(TOPK, sims.shape[1])
        part = np.argpartition(-sims, k - 1, axis=1)[:, :k]
        for row_i in range(sims.shape[0]):
            idx = part[row_i]
            order = idx[np.argsort(-sims[row_i, idx])]
            out.append(cand_ids_arr[order].tolist())
    return out


def rrf_fuse(rank_a: dict[str, int], rank_b: dict[str, int], k: int = RRF_K) -> list[str]:
    ids = set(rank_a) | set(rank_b)
    scored = []
    for cid in ids:
        score = 0.0
        if cid in rank_a:
            score += 1.0 / (k + rank_a[cid])
        if cid in rank_b:
            score += 1.0 / (k + rank_b[cid])
        scored.append((score, cid))
    scored.sort(key=lambda x: -x[0])
    return [cid for _, cid in scored]


def rank_of(ranked_ids: list[str], target: str) -> int | None:
    try:
        return ranked_ids.index(target) + 1
    except ValueError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind")
    ap.add_argument("candidates_path")
    ap.add_argument("queries_path")
    ap.add_argument("out_metrics")
    args = ap.parse_args()

    queries = load_jsonl(args.queries_path)
    print(f"[{args.kind}] {len(queries)} queries; candidates file: {args.candidates_path}", file=sys.stderr)

    throughput: dict = {"num_threads": NUM_THREADS}

    # --- pg_trgm (Postgres, GiST-indexed KNN) ---
    conn = psycopg.connect(DSN, autocommit=False)
    ensure_schema(conn)
    n_candidates = load_candidates_trgm(conn, args.candidates_path)
    throughput["n_candidates"] = n_candidates
    trgm_lists, trgm_seconds = trgm_ranks(conn, queries)
    throughput["trgm_query_seconds"] = trgm_seconds
    throughput["trgm_queries_per_sec"] = len(queries) / trgm_seconds if trgm_seconds else None
    conn.close()

    trgm_ranked = {q["mbid"]: {cid: r + 1 for r, cid in enumerate(lst)} for q, lst in zip(queries, trgm_lists)}

    dense_ranked: dict[str, dict[str, dict[str, int]]] = {}  # method -> mbid -> rank map
    for method, model_name, prefix, batch_size in (
        ("e5", "intfloat/multilingual-e5-small", "query: ", 512),
        ("bge", "BAAI/bge-m3", "", 128),
    ):
        print(f"[{args.kind}] loading {model_name}...", file=sys.stderr)
        model = SentenceTransformer(model_name, device="cpu")

        cand_ids: list[str] = []
        cand_names: list[str] = []
        with open(args.candidates_path) as f:
            for line in f:
                rec = json.loads(line)
                if not rec.get("discogs_id"):
                    continue
                cand_ids.append(rec["discogs_id"])
                cand_names.append(rec.get("name") or "")

        cand_prefix = "passage: " if method == "e5" else ""
        cand_vecs, cand_seconds = embed_texts(model, cand_names, cand_prefix, batch_size)
        throughput[f"{method}_candidate_embed_seconds"] = cand_seconds
        throughput[f"{method}_candidate_throughput_per_sec"] = len(cand_names) / cand_seconds if cand_seconds else None
        print(f"[{args.kind}] {method} candidates embedded: {len(cand_names)} in {cand_seconds:.1f}s", file=sys.stderr)

        query_names = [q["query_name"] for q in queries]
        q_vecs, q_seconds = embed_texts(model, query_names, prefix, batch_size)
        throughput[f"{method}_query_embed_seconds"] = q_seconds

        t0 = time.monotonic()
        ranked_lists = dense_ranks(cand_ids, cand_vecs, q_vecs)
        throughput[f"{method}_score_seconds"] = time.monotonic() - t0

        dense_ranked[method] = {
            q["mbid"]: {cid: r + 1 for r, cid in enumerate(lst)} for q, lst in zip(queries, ranked_lists)
        }

        del cand_vecs, q_vecs, model
        gc.collect()

    results = []
    for q in queries:
        mbid = q["mbid"]
        t_rank = trgm_ranked.get(mbid, {})
        e5_rank = dense_ranked["e5"].get(mbid, {})
        bge_rank = dense_ranked["bge"].get(mbid, {})
        fused_e5 = rrf_fuse(t_rank, e5_rank)
        fused_bge = rrf_fuse(t_rank, bge_rank)
        target = q["correct_discogs_id"]

        def rank_in_map(m: dict[str, int]) -> int | None:
            return m.get(target)

        results.append(
            {
                **{k: q[k] for k in ("mbid", "kind", "script", "match_class", "name_frequency")},
                "rank_trgm": rank_in_map(t_rank),
                "rank_e5": rank_in_map(e5_rank),
                "rank_bge": rank_in_map(bge_rank),
                "rank_rrf_e5": rank_of(fused_e5, target),
                "rank_rrf_bge": rank_of(fused_bge, target),
            }
        )

    with open(args.out_metrics, "w") as f:
        json.dump({"throughput": throughput, "results": results}, f)
    print(f"[{args.kind}] wrote {args.out_metrics}: {json.dumps(throughput, indent=2)}", file=sys.stderr)


if __name__ == "__main__":
    main()
