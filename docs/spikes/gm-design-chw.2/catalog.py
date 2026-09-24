# SPDX-License-Identifier: MIT
"""An in-memory release graph and the heuristics-2026-09 similar-artist baseline over it.

A :class:`Catalog` holds releases as rows of sparse incidence matrices (release x artist for
the ``BY`` edge, credits, and track artists; release x label, genre, style), all with local
0-based column indices. :class:`Heuristic` replays ``GET /api/recommend/similar/artist/{id}``
exactly as catalog-api's evaluation adapter does (``api/evaluation/graph.py``
``candidate_artists`` + ``compute_similar_artists``), and additionally exposes the same
weighted cosine as a dense scorer over every artist, for fusion and for separating the
weights from the candidate generator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import scipy.sparse as sp

import baseline_port as bp


@dataclass
class Catalog:
    """Releases as sparse incidence matrices. Every matrix has one row per release."""

    by: sp.csr_matrix  # release x artist (main artists, the BY edge)
    credits: sp.csr_matrix  # release x artist (kept extraartist roles)
    track: sp.csr_matrix  # release x artist (track-level artists)
    labels: sp.csr_matrix  # release x label
    genres: sp.csr_matrix  # release x genre
    styles: sp.csr_matrix  # release x style
    rel_date: np.ndarray
    rel_fam: np.ndarray
    rel_master: np.ndarray
    rel_id: np.ndarray
    artist_ids: np.ndarray  # external id per artist column
    label_ids: np.ndarray
    genre_names: list[str]
    style_names: list[str]
    artist_names: list[str] | None = None  # golden set only
    label_names: list[str] | None = None  # golden set only

    @property
    def n_artists(self) -> int:
        return self.by.shape[1]

    def restrict(self, mask: np.ndarray) -> Catalog:
        """The same catalog with only the releases where ``mask`` is true."""
        rows = np.flatnonzero(mask)
        pick = lambda m: m[rows]  # noqa: E731
        return Catalog(
            pick(self.by), pick(self.credits), pick(self.track), pick(self.labels), pick(self.genres), pick(self.styles),
            self.rel_date[rows], self.rel_fam[rows], self.rel_master[rows], self.rel_id[rows],
            self.artist_ids, self.label_ids, self.genre_names, self.style_names, self.artist_names, self.label_names,
        )


def load_subset(src: Path) -> tuple[Catalog, np.ndarray, np.ndarray]:
    """Load a ``build_subset.py`` directory.

    Returns the catalog (all subset releases, pre- and post-cut), the pre-cut release mask,
    and the local indices of the seed artists.
    """
    arr = {p.stem: np.load(p) for p in src.glob("*.npy")}
    vocab = json.loads((src / "vocab.json").read_text())
    n = len(arr["rel_id"])
    artist_ids = np.unique(np.concatenate([arr[f"{x}_val"] for x in ("artists", "credits", "trackartists")]))
    label_ids = np.unique(arr["labels_val"])

    def incidence(name: str, ids: np.ndarray | None, width: int) -> sp.csr_matrix:
        ptr, val = arr[f"{name}_ptr"], arr[f"{name}_val"]
        cols = np.searchsorted(ids, val) if ids is not None else val.astype(np.int64)
        m = sp.csr_matrix((np.ones(len(cols), dtype=np.int8), cols, ptr), shape=(n, width))
        m.sum_duplicates()
        m.data[:] = 1
        return m

    cat = Catalog(
        by=incidence("artists", artist_ids, len(artist_ids)),
        credits=incidence("credits", artist_ids, len(artist_ids)),
        track=incidence("trackartists", artist_ids, len(artist_ids)),
        labels=incidence("labels", label_ids, len(label_ids)),
        genres=incidence("genres", None, len(vocab["genres"])),
        styles=incidence("styles", None, len(vocab["styles"])),
        rel_date=arr["rel_date"],
        rel_fam=arr["rel_fam"],
        rel_master=arr["rel_master"],
        rel_id=arr["rel_id"],
        artist_ids=artist_ids,
        label_ids=label_ids,
        genre_names=vocab["genres"],
        style_names=vocab["styles"],
    )
    seeds = arr["seed_artists"]
    seeds = np.searchsorted(artist_ids, seeds[np.isin(seeds, artist_ids)])
    return cat, arr["rel_pre"].astype(bool), seeds


def _row_normalize(m: sp.csr_matrix) -> sp.csr_matrix:
    m = m.astype(np.float32).tocsr()
    norms = np.sqrt(np.asarray(m.multiply(m).sum(axis=1)).ravel())
    norms[norms == 0] = 1.0
    return (sp.diags((1.0 / norms).astype(np.float32)) @ m).tocsr()


class Heuristic:
    """heuristics-2026-09 similar-artist scoring over a catalog (normally the pre-cut one)."""

    def __init__(self, catalog: Catalog, artist_sort_key: np.ndarray) -> None:
        self.cat = catalog
        by_t = catalog.by.T.tocsr().astype(np.int64)
        # count(DISTINCT r) per artist and facet: the incidence matrices are binary.
        self.dims = {
            "genre": (by_t @ catalog.genres).tocsr(),
            "style": (by_t @ catalog.styles).tocsr(),
            "label": (by_t @ catalog.labels).tocsr(),
        }
        collab = (by_t @ catalog.by).tolil()
        collab.setdiag(0)
        self.dims["collaborator"] = collab.tocsr()
        self.dims["collaborator"].eliminate_zeros()
        self.release_count = np.asarray(catalog.by.sum(axis=0)).ravel()
        self.key = artist_sort_key  # deterministic tiebreak, standing in for Cypher's unspecified order
        self._facet_names = {
            "genre": catalog.genre_names,
            "style": catalog.style_names,
            "label": catalog.label_names if catalog.label_names is not None else [str(x) for x in catalog.label_ids],
            "collaborator": catalog.artist_names if catalog.artist_names is not None else [str(x) for x in catalog.artist_ids],
        }
        # Per-genre artist rankings by release count, for the candidate expansion.
        genre_csc = self.dims["genre"].tocsc()
        self._genre_top: list[tuple[np.ndarray, np.ndarray]] = []
        for g in range(genre_csc.shape[1]):
            start, end = genre_csc.indptr[g], genre_csc.indptr[g + 1]
            artists = genre_csc.indices[start:end]
            counts = genre_csc.data[start:end]
            order = np.lexsort((self.key[artists], -counts))[: bp.PER_GENRE_CANDIDATE_LIMIT + 1]
            self._genre_top.append((artists[order], counts[order]))
        self._normalized = {dim: _row_normalize(m) for dim, m in self.dims.items()}

    # ── the production path ────────────────────────────────────────

    def _counted(self, dim: str, artist: int) -> list[dict[str, Any]]:
        m = self.dims[dim]
        start, end = m.indptr[artist], m.indptr[artist + 1]
        names = self._facet_names[dim]
        rows = [{"name": names[c], "count": int(v)} for c, v in zip(m.indices[start:end], m.data[start:end], strict=True) if v > 0]
        rows.sort(key=lambda item: (-item["count"], item["name"]))
        return rows

    def profile(self, artist: int) -> dict[str, Any]:
        return {
            "genres": self._counted("genre", artist),
            "styles": self._counted("style", artist),
            "labels": self._counted("label", artist),
            "collaborators": self._counted("collaborator", artist),
        }

    def candidate_artists(self, artist: int, profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Mirror of catalog-api ``GoldenGraph.candidate_artists`` (see its docstring)."""
        profile = profile or self.profile(artist)
        genre_index = {name: i for i, name in enumerate(self.cat.genre_names)}
        top_genres = [genre_index[entry["name"]] for entry in profile["genres"][: bp.TOP_GENRES]]
        shared: dict[int, int] = {}
        for g in top_genres:
            artists, counts = self._genre_top[g]
            keep = artists != artist
            for other, count in zip(artists[keep][: bp.PER_GENRE_CANDIDATE_LIMIT], counts[keep][: bp.PER_GENRE_CANDIDATE_LIMIT], strict=True):
                shared[int(other)] = shared.get(int(other), 0) + int(count)
        ranked = sorted(
            ((other, count) for other, count in shared.items() if count >= bp.MIN_ARTIST_RELEASES),
            key=lambda item: (-item[1], self.key[item[0]]),
        )[: bp.CANDIDATE_LIMIT]
        profiled = ranked[: bp.PROFILED_CANDIDATES]
        names = self._facet_names["collaborator"]
        return [{"artist_id": other, "artist_name": names[other], "release_count": count, **self.profile(other)} for other, count in profiled]

    def similar(self, artist: int, limit: int = bp.SIMILAR_ARTIST_LIMIT) -> list[dict[str, Any]]:
        """The production similar-artist list: candidate generation, then weighted cosine."""
        profile = self.profile(artist)
        return bp.compute_similar_artists(profile, self.candidate_artists(artist, profile), limit=limit)

    # ── the same weights, scored densely ──────────────────────────

    def scores(self, artists: np.ndarray) -> np.ndarray:
        """Weighted cosine of each query artist against every artist, as a dense block."""
        out = np.zeros((self.cat.n_artists, len(artists)), dtype=np.float32)
        for dim, weight in bp._WEIGHTS.items():
            xn = self._normalized[dim]
            q = xn[artists].T
            # Collaborator vectors live in artist space and are very sparse; the facet
            # dimensions are small enough to densify the query side.
            block = (xn @ q).toarray() if dim == "collaborator" else xn @ q.toarray()
            out += weight * block
        return out.T
