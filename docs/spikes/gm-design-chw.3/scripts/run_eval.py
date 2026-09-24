#!/usr/bin/env python3
"""Core evaluation: load a candidate pool + query set for one entity kind
into Postgres (pg_trgm + pgvector, exact search, no ANN index), embed both
sides with multilingual-e5-small and bge-m3, and measure recall@1/10/50 for
pg_trgm alone, each dense model alone, and RRF(trgm, dense) fusion -- overall
and sliced by script / match-class / name-frequency.

Threads are capped at 4 (torch + tokenizers) per the spike's resource budget;
Postgres runs against a locally built PG19+pgvector container exposed at
127.0.0.1:15433.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import psycopg  # noqa: E402
import torch  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

torch.set_num_threads(4)

DSN = "host=127.0.0.1 port=15433 dbname=identity_spike user=postgres password=spike"
RRF_K = 60


def load_jsonl(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("DROP TABLE IF EXISTS candidates")
        cur.execute(
            """
            CREATE TABLE candidates (
                id BIGSERIAL PRIMARY KEY,
                kind TEXT NOT NULL,
                discogs_id TEXT NOT NULL,
                name TEXT NOT NULL,
                emb_e5 vector(384),
                emb_bge vector(1024)
            )
            """
        )
    conn.commit()


def embed_texts(model: SentenceTransformer, texts: list[str], prefix: str, batch_size: int) -> tuple[list[list[float]], float]:
    prefixed = [f"{prefix}{t}" if prefix else t for t in texts]
    t0 = time.monotonic()
    vecs = model.encode(
        prefixed,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    elapsed = time.monotonic() - t0
    return vecs.tolist(), elapsed


def load_candidates(conn: psycopg.Connection, kind: str, candidates: list[dict], e5, bge) -> dict:
    names = [c["name"] for c in candidates]
    e5_vecs, e5_time = embed_texts(e5, names, "passage: ", batch_size=256)
    bge_vecs, bge_time = embed_texts(bge, names, "", batch_size=64)

    with conn.cursor() as cur:
        with cur.copy(
            "COPY candidates (kind, discogs_id, name, emb_e5, emb_bge) FROM STDIN"
        ) as copy:
            for c, ev, bv in zip(candidates, e5_vecs, bge_vecs):
                copy.write_row((kind, c["discogs_id"], c["name"], str(ev), str(bv)))
    conn.commit()
    return {
        "n_candidates": len(candidates),
        "e5_embed_seconds": e5_time,
        "e5_throughput_per_sec": len(names) / e5_time if e5_time else None,
        "bge_embed_seconds": bge_time,
        "bge_throughput_per_sec": len(names) / bge_time if bge_time else None,
    }


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
    ap.add_argument("--topk", type=int, default=50)
    args = ap.parse_args()

    candidates = load_jsonl(args.candidates_path)
    queries = load_jsonl(args.queries_path)
    print(f"[{args.kind}] loading {len(candidates)} candidates, {len(queries)} queries", file=sys.stderr)

    print("loading models...", file=sys.stderr)
    e5 = SentenceTransformer("intfloat/multilingual-e5-small", device="cpu")
    bge = SentenceTransformer("BAAI/bge-m3", device="cpu")

    conn = psycopg.connect(DSN, autocommit=False)
    ensure_schema(conn)

    throughput = load_candidates(conn, args.kind, candidates, e5, bge)
    print(f"[{args.kind}] candidate embedding done: {throughput}", file=sys.stderr)

    query_names = [q["query_name"] for q in queries]
    q_e5_vecs, q_e5_time = embed_texts(e5, query_names, "query: ", batch_size=256)
    q_bge_vecs, q_bge_time = embed_texts(bge, query_names, "", batch_size=64)
    throughput["query_e5_embed_seconds"] = q_e5_time
    throughput["query_bge_embed_seconds"] = q_bge_time

    results = []
    t0 = time.monotonic()
    with conn.cursor() as cur:
        for i, q in enumerate(queries):
            name = q["query_name"]
            cur.execute(
                "SELECT discogs_id FROM candidates WHERE kind = %s "
                "ORDER BY similarity(name, %s) DESC LIMIT %s",
                (args.kind, name, args.topk),
            )
            trgm_ids = [r[0] for r in cur.fetchall()]

            cur.execute(
                "SELECT discogs_id FROM candidates WHERE kind = %s "
                "ORDER BY emb_e5 <=> %s LIMIT %s",
                (args.kind, str(q_e5_vecs[i]), args.topk),
            )
            e5_ids = [r[0] for r in cur.fetchall()]

            cur.execute(
                "SELECT discogs_id FROM candidates WHERE kind = %s "
                "ORDER BY emb_bge <=> %s LIMIT %s",
                (args.kind, str(q_bge_vecs[i]), args.topk),
            )
            bge_ids = [r[0] for r in cur.fetchall()]

            trgm_rank = {cid: r + 1 for r, cid in enumerate(trgm_ids)}
            e5_rank = {cid: r + 1 for r, cid in enumerate(e5_ids)}
            bge_rank = {cid: r + 1 for r, cid in enumerate(bge_ids)}

            fused_e5 = rrf_fuse(trgm_rank, e5_rank)
            fused_bge = rrf_fuse(trgm_rank, bge_rank)

            target = q["correct_discogs_id"]
            results.append(
                {
                    **{k: q[k] for k in ("mbid", "kind", "script", "match_class", "name_frequency")},
                    "rank_trgm": rank_of(trgm_ids, target),
                    "rank_e5": rank_of(e5_ids, target),
                    "rank_bge": rank_of(bge_ids, target),
                    "rank_rrf_e5": rank_of(fused_e5, target),
                    "rank_rrf_bge": rank_of(fused_bge, target),
                }
            )
            if (i + 1) % 1000 == 0:
                print(f"[{args.kind}] scored {i + 1}/{len(queries)} queries", file=sys.stderr)
    throughput["query_scoring_seconds"] = time.monotonic() - t0

    conn.close()

    with open(args.out_metrics, "w") as f:
        json.dump({"throughput": throughput, "results": results}, f)
    print(f"[{args.kind}] wrote {args.out_metrics}", file=sys.stderr)


if __name__ == "__main__":
    main()
