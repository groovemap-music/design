"""Concept C: place a collection and a candidate's Fit evidence on the atlas.

``fit_entries`` re-states catalog-api ``api/fit.py`` (``cratefit_v0``) closely enough to
produce the same evidence entries per component, uncapped and capped at the route's three.
It is a copy of the rules for measurement, not an import: repositories never import each
other. Media families are not in the compact arrays, so Redundancy's two same-master cases
(same family 1.0, other family 0.6) are reported as one ``duplicate`` kind; the atlas
mapping is identical for both.

``atlas_target`` says where an entry can be drawn on the B atlas (planes L0 genre,
L1 style, L2 master, L3 the collector's releases):

- ``position``: a genre or style node, or a release whose master is on L2;
- ``edge``: a Bridge between genre hulls whose genre list parses unambiguously;
- ``ambiguous``: a Bridge whose rendered genre list cannot be split back into genres;
- ``none``: an artist or label (no atlas plane carries them), or a title-only duplicate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

WEIGHTS = {"artist": 0.35, "label": 0.25, "genre": 0.25, "style": 0.15}
DEPTH_SATURATION = 5
EVIDENCE_LIMIT = 3


@dataclass
class Release:
    rid: int
    master: int
    artists: tuple[int, ...]
    labels: tuple[int, ...]
    genres: tuple[str, ...]
    styles: tuple[str, ...]
    title: str = ""


@dataclass
class Collection:
    releases: list[Release]
    release_ids: set[int] = field(default_factory=set)
    master_ids: set[int] = field(default_factory=set)
    counts: dict[str, dict] = field(default_factory=dict)
    genre_artists: dict[str, set] = field(default_factory=dict)
    genre_labels: dict[str, set] = field(default_factory=dict)
    genre_styles: dict[str, set] = field(default_factory=dict)
    held_titles: set[tuple[int, str]] = field(default_factory=set)

    @classmethod
    def fold(cls, releases: list[Release]) -> "Collection":
        c = cls(releases)
        c.counts = {d: {} for d in WEIGHTS}
        for r in releases:
            c.release_ids.add(r.rid)
            if r.master:
                c.master_ids.add(r.master)
            for d, values in (("artist", r.artists), ("label", r.labels), ("genre", r.genres), ("style", r.styles)):
                for v in dict.fromkeys(values):
                    c.counts[d][v] = c.counts[d].get(v, 0) + 1
            for g in dict.fromkeys(r.genres):
                c.genre_artists.setdefault(g, set()).update(r.artists)
                c.genre_labels.setdefault(g, set()).update(r.labels)
                c.genre_styles.setdefault(g, set()).update(r.styles)
            if r.title:
                for a in r.artists:
                    c.held_titles.add((a, r.title.casefold().strip()))
        return c


def _facets(r: Release) -> dict[str, tuple]:
    return {"artist": r.artists, "label": r.labels, "genre": r.genres, "style": r.styles}


def fit_entries(c: Collection, cand: Release, siblings_held: list[int] | None = None) -> dict[str, dict]:
    """Per component: score, all entries, and the capped entries the route returns."""
    facets = _facets(cand)
    out: dict[str, dict] = {}

    weighted = total = 0.0
    shared = []
    for d, w in WEIGHTS.items():
        if not facets[d]:
            continue
        held = c.counts[d]
        matches = [v for v in facets[d] if v in held]
        weighted += w * len(matches) / len(facets[d])
        total += w
        shared += [(held[v], d, v) for v in matches]
    shared.sort(key=lambda e: (-e[0], e[1], str(e[2])))
    out["affinity"] = {"score": weighted / total if total else 0.0, "entries": [{"dimension": d, "entity": v, "kind": "shared"} for n, d, v in shared if n]}

    pool = new = 0
    unheld = []
    for d in WEIGHTS:
        if not facets[d]:
            continue
        pool += len(facets[d])
        unheld += [(d, v) for v in facets[d] if v not in c.counts[d]]
    unheld.sort(key=lambda e: (e[0], str(e[1])))
    new = len(unheld)
    out["novelty"] = {"score": new / pool if pool else 0.0, "entries": [{"dimension": d, "entity": v, "kind": "unheld"} for d, v in unheld]}

    depth = 0.0
    threads = []
    for d in ("label", "artist"):
        for v in facets[d]:
            n = c.counts[d].get(v, 0)
            if n > 0:
                depth = max(depth, min(1.0, n / DEPTH_SATURATION))
                threads.append((n, d, v))
    threads.sort(key=lambda e: (-e[0], e[1], str(e[2])))
    out["depth"] = {"score": depth, "entries": [{"dimension": d, "entity": v, "kind": "thread"} for n, d, v in threads]}

    cg, cs = set(cand.genres), set(cand.styles)
    touched = [g for g in sorted(c.counts["genre"]) if g in cg or (cs & c.genre_styles.get(g, set()))]
    picked, hoods = [], []
    for g in touched:
        hood = {("a", x) for x in c.genre_artists.get(g, ())} | {("l", x) for x in c.genre_labels.get(g, ())}
        if any(hood & h for h in hoods):
            continue
        picked.append(g)
        hoods.append(hood)
    bridge = min(1.0, float(max(0, len(picked) - 1)))
    entries = []
    if bridge > 0:
        named = ", ".join(picked[:-1]) + f" and {picked[-1]}"
        entries = [{"dimension": "genre", "entity": named, "kind": "bridge", "genres": picked}, {"dimension": "bridge", "entity": "v0 heuristic", "kind": "heuristic"}]
    out["bridge"] = {"score": bridge, "entries": entries}

    held_sib = [s for s in (siblings_held or []) if s in c.release_ids]
    if cand.rid in c.release_ids:
        red = {"score": 1.0, "entries": [{"dimension": "release", "entity": cand.rid, "kind": "duplicate", "release_id": cand.rid}]}
    elif held_sib:
        red = {"score": 1.0, "entries": [{"dimension": "release", "entity": min(held_sib), "kind": "duplicate", "release_id": min(held_sib)}]}
    else:
        red = {"score": 0.0, "entries": []}
        title = cand.title.casefold().strip()
        if title:
            for a in cand.artists:
                if (a, title) in c.held_titles:
                    red = {"score": 0.3, "entries": [{"dimension": "release", "entity": cand.title, "kind": "duplicate_title"}]}
                    break
    out["redundancy"] = red
    for comp in out.values():
        comp["capped"] = comp["entries"][:EVIDENCE_LIMIT]
    return out


def split_bridge(named: str, genres: list[str]) -> list[list[str]]:
    """Every way the rendered ``"A, B and C"`` string splits back into known genres.

    The route renders ``", ".join(picked[:-1]) + " and " + picked[-1]``. A genre whose
    own name contains ", " or " and " can make that string split more than one way.
    """
    known = sorted(set(genres))
    results: list[list[str]] = []

    def heads(rest: str) -> list[list[str]]:
        out = []
        for g in known:
            if rest == g:
                out.append([g])
            elif rest.startswith(g + ", "):
                out += [[g] + tail for tail in heads(rest[len(g) + 2 :])]
        return out

    for last in known:
        suffix = " and " + last
        if named.endswith(suffix):
            results += [h + [last] for h in heads(named[: -len(suffix)])]
    return results


def atlas_target(entry: dict, master_of: dict[int, int] | None = None, genres: list[str] | None = None) -> str:
    kind, dim = entry["kind"], entry["dimension"]
    if kind == "heuristic":
        return "label"  # the caveat sentence, not a fact to draw
    if dim in ("genre", "style") and kind in ("shared", "unheld"):
        return "position"
    if kind == "bridge":
        splits = split_bridge(entry["entity"], genres or [])
        return "edge" if len(splits) == 1 else "ambiguous"
    if kind == "duplicate":
        rid = entry.get("release_id")
        return "position" if master_of is not None and master_of.get(rid, 0) > 0 else "none"
    return "none"


def synthetic_collection(rng: np.random.Generator, pool: list[Release], by_style: dict[str, list[int]], seeds: list[str], size: int, focus: float = 0.8) -> list[Release]:
    """A synthetic collector: ``focus`` of the items from the seed styles, the rest uniform."""
    picks: set[int] = set()
    seed_pool = [i for s in seeds for i in by_style.get(s, [])]
    while len(picks) < size:
        if seed_pool and rng.random() < focus:
            picks.add(int(seed_pool[rng.integers(len(seed_pool))]))
        else:
            picks.add(int(rng.integers(len(pool))))
    return [pool[i] for i in sorted(picks)]
