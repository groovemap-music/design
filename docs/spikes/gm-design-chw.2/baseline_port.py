# SPDX-License-Identifier: MIT
"""Read-only copies of the catalog-api pieces this spike scores against.

Copied verbatim (function bodies) from groovemap-music/catalog-api at
15f70c7137fa2dc0358184dbf61803734cc17015 so the spike runs without catalog-api's database
and web dependencies:

* ``api/evaluation/metrics.py``: ``precision_at_k``, ``recall_at_k``, ``hits_at_k``,
  ``catalogue_coverage``, ``_mean``, ``_average_ranks``, ``spearman``
* ``api/queries/similarity.py``: ``to_genre_vector``, ``cosine_similarity``
* ``api/queries/recommend_queries.py``: ``compute_similar_artists``, ``_WEIGHTS``,
  ``MIN_ARTIST_RELEASES``
* ``api/evaluation/graph.py``: the candidate-generation limits of ``candidate_artists``

``check_golden.py`` proves the copies still reproduce catalog-api's own output on the
committed golden set, so a drift in either direction fails the sanity check.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence
from typing import Any, Final

# ── api/queries/recommend_queries.py (heuristics-2026-09) ─────────────────────

MIN_ARTIST_RELEASES = 3

_WEIGHTS = {
    "genre": 0.35,
    "style": 0.25,
    "label": 0.25,
    "collaborator": 0.15,
}

# ── api/evaluation/graph.py candidate limits ─────────────────────────────────

TOP_GENRES: Final[int] = 5
PER_GENRE_CANDIDATE_LIMIT: Final[int] = 500
CANDIDATE_LIMIT: Final[int] = 200
PROFILED_CANDIDATES: Final[int] = 50
SIMILAR_ARTIST_LIMIT: Final[int] = 20


# ── api/queries/similarity.py ────────────────────────────────────────────────


def to_genre_vector(genres: list[dict[str, Any]]) -> dict[str, float]:
    """Convert genre list with counts to a normalized percentage vector."""
    total = sum(g["count"] for g in genres)
    if total == 0:
        return {}
    return {g["name"]: g["count"] / total for g in genres}


def cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Compute cosine similarity between two sparse vectors (dict-based)."""
    if not vec_a or not vec_b:
        return 0.0
    all_keys = set(vec_a) | set(vec_b)
    dot = sum(vec_a.get(k, 0.0) * vec_b.get(k, 0.0) for k in all_keys)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def compute_similar_artists(
    target_profile: dict[str, Any],
    candidates: list[dict[str, Any]],
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Rank candidate artists by weighted cosine similarity to the target."""
    target_vecs = {
        "genre": to_genre_vector(target_profile.get("genres", [])),
        "style": to_genre_vector(target_profile.get("styles", [])),
        "label": to_genre_vector(target_profile.get("labels", [])),
        "collaborator": to_genre_vector(target_profile.get("collaborators", [])),
    }

    if not any(target_vecs.values()):
        return []

    target_genre_names = set(target_vecs["genre"])
    target_label_names = set(target_vecs["label"])

    results = []
    for candidate in candidates:
        # Skip candidates with missing names (NULL in Neo4j)
        if not candidate.get("artist_name"):
            continue
        cand_vecs = {
            "genre": to_genre_vector(candidate.get("genres", [])),
            "style": to_genre_vector(candidate.get("styles", [])),
            "label": to_genre_vector(candidate.get("labels", [])),
            "collaborator": to_genre_vector(candidate.get("collaborators", [])),
        }

        breakdown = {}
        weighted_sum = 0.0
        for dim, weight in _WEIGHTS.items():
            sim = cosine_similarity(target_vecs[dim], cand_vecs[dim])
            breakdown[dim] = round(sim, 4)
            weighted_sum += sim * weight

        if weighted_sum <= 0.0:
            continue

        shared_genres = sorted(set(cand_vecs["genre"]) & target_genre_names)
        shared_labels = sorted(set(cand_vecs["label"]) & target_label_names)

        results.append(
            {
                "artist_id": candidate["artist_id"],
                "artist_name": candidate["artist_name"],
                "similarity": round(weighted_sum, 4),
                "breakdown": breakdown,
                "release_count": candidate.get("release_count", 0),
                "shared_genres": shared_genres,
                "shared_labels": shared_labels,
            }
        )

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]


# ── api/evaluation/metrics.py ────────────────────────────────────────────────


def precision_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float:
    if k <= 0:
        return 0.0
    relevant_set = set(relevant)
    return sum(1 for release_id in ranked[:k] if release_id in relevant_set) / k


def recall_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> float:
    relevant_set = set(relevant)
    if not relevant_set:
        return 0.0
    return sum(1 for release_id in ranked[:k] if release_id in relevant_set) / len(relevant_set)


def hits_at_k(ranked: Sequence[str], relevant: Collection[str], k: int) -> int:
    relevant_set = set(relevant)
    return sum(1 for release_id in ranked[:k] if release_id in relevant_set)


def catalogue_coverage(rankings: Collection[Sequence[str]], catalog_size: int) -> float:
    if catalog_size <= 0:
        return 0.0
    return len({release_id for ranking in rankings for release_id in ranking}) / catalog_size


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return math.fsum(values) / len(values)


def _average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        shared = (start + end) / 2 + 1
        for position in range(start, end + 1):
            ranks[order[position]] = shared
        start = end + 1
    return ranks


def spearman(first: Sequence[float], second: Sequence[float]) -> float:
    if len(first) != len(second):
        raise ValueError("spearman needs two sequences of the same length")
    if not first:
        return 0.0
    ranks_a = _average_ranks(first)
    ranks_b = _average_ranks(second)
    mean_a = _mean(ranks_a)
    mean_b = _mean(ranks_b)
    covariance = math.fsum((a - mean_a) * (b - mean_b) for a, b in zip(ranks_a, ranks_b, strict=True))
    variance_a = math.fsum((a - mean_a) ** 2 for a in ranks_a)
    variance_b = math.fsum((b - mean_b) ** 2 for b in ranks_b)
    if variance_a == 0.0 or variance_b == 0.0:
        return 1.0 if list(first) == list(second) else 0.0
    return max(-1.0, min(1.0, covariance / math.sqrt(variance_a * variance_b)))
