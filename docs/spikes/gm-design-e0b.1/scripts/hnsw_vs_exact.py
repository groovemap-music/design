#!/usr/bin/env python3
"""Small side-check: how much of a ceiling is run_eval.py's exact-cosine dense
retrieval relative to what pgvector's HNSW index (the shape ADR 0013 actually
adopts: halfvec, m=16, ef_construction=64, cosine) would retrieve in
production? Deliberately kept small (one subsample, one kind) -- this is a
sanity check on the exact-cosine caveat, not a full re-run.

Usage: hnsw_vs_exact.py <candidates.jsonl> <queries.jsonl> --n-candidates 50000 --n-queries 300
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
import torch  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

torch.set_num_threads(6)

DSN = os.environ.get("SPIKE_DSN_VEC", "host=127.0.0.1 port=15434 dbname=identity_spike user=postgres password=spike")


def load_jsonl(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


def embed(model, texts, prefix, batch_size):
    prefixed = [f"{prefix}{t}" if prefix else t for t in texts]
    return model.encode(prefixed, batch_size=batch_size, show_progress_bar=False, normalize_embeddings=True, convert_to_numpy=True).astype(np.float32)


def exact_top10(cand_vecs: np.ndarray, q_vecs: np.ndarray) -> list[list[int]]:
    sims = q_vecs @ cand_vecs.T
    idx = np.argsort(-sims, axis=1)[:, :10]
    return idx.tolist()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates_path")
    ap.add_argument("queries_path")
    ap.add_argument("--n-candidates", type=int, default=50000)
    ap.add_argument("--n-queries", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20260924)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    all_candidates = load_jsonl(args.candidates_path)
    all_queries = load_jsonl(args.queries_path)
    rng.shuffle(all_queries)
    queries = all_queries[: args.n_queries]
    target_ids = {q["correct_discogs_id"] for q in queries}

    targets = [c for c in all_candidates if c["discogs_id"] in target_ids]
    rest = [c for c in all_candidates if c["discogs_id"] not in target_ids]
    rng.shuffle(rest)
    n_rest = max(0, args.n_candidates - len(targets))
    candidates = targets + rest[:n_rest]
    print(f"subsample: {len(candidates)} candidates ({len(targets)} targets), {len(queries)} queries", file=sys.stderr)

    for method, model_name, prefix in (("e5", "intfloat/multilingual-e5-small", "query: "), ("bge", "BAAI/bge-m3", "")):
        model = SentenceTransformer(model_name, device="cpu")
        cand_names = [c.get("name") or "" for c in candidates]
        cand_prefix = "passage: " if method == "e5" else ""
        cand_vecs = embed(model, cand_names, cand_prefix, 256)
        q_names = [q["query_name"] for q in queries]
        q_vecs = embed(model, q_names, prefix, 256)

        exact_idx = exact_top10(cand_vecs, q_vecs)
        cand_ids = [c["discogs_id"] for c in candidates]

        dim = cand_vecs.shape[1]
        conn = psycopg.connect(DSN, autocommit=False)
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("DROP TABLE IF EXISTS hnsw_check")
            cur.execute(f"CREATE TABLE hnsw_check (id BIGSERIAL PRIMARY KEY, discogs_id TEXT, emb halfvec({dim}))")
            with cur.copy("COPY hnsw_check (discogs_id, emb) FROM STDIN") as copy:
                for cid, v in zip(cand_ids, cand_vecs):
                    copy.write_row((cid, str(v.tolist())))
            cur.execute("SET maintenance_work_mem = '512MB'")
            cur.execute(
                f"CREATE INDEX ON hnsw_check USING hnsw (emb halfvec_cosine_ops) WITH (m=16, ef_construction=64)"
            )
        conn.commit()

        for ef_search in (40, 100):
            with conn.cursor() as cur:
                cur.execute(f"SET hnsw.ef_search = {ef_search}")
                hits = 0
                total = 0
                for i, q in enumerate(queries):
                    cur.execute(
                        "SELECT discogs_id FROM hnsw_check ORDER BY emb <=> %s LIMIT 10",
                        (str(q_vecs[i].tolist()),),
                    )
                    ann_ids = {r[0] for r in cur.fetchall()}
                    exact_ids = {cand_ids[j] for j in exact_idx[i]}
                    hits += len(ann_ids & exact_ids)
                    total += len(exact_ids)
                print(f"[{method}] ef_search={ef_search}: ANN-vs-exact top-10 overlap recall = {hits/total:.4f} ({hits}/{total})", file=sys.stderr)
        conn.close()
        del cand_vecs, q_vecs, model


if __name__ == "__main__":
    main()
