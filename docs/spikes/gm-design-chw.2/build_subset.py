# SPDX-License-Identifier: MIT
"""Pass 2: cut the full-dump arrays at the time split and sample an artist-seeded subset.

Time split (catalog-api ``SPLIT_CUT`` = 2023-01-01):

* **pre-cut** releases: a usable release date before the cut *and* a release id below the
  id Discogs was assigning at the cut. The second condition approximates the catalog as it
  stood on the cut date, so an old record catalogued in 2024 is not training data.
* **post-cut** releases: a release date on or after the cut. Used only to build ground truth.
* Everything else (no usable date, or old but catalogued after the cut) is dropped.

Sampling: seed artists are drawn by a fixed integer hash of the Discogs artist id from the
artists with at least ``MIN_ARTIST_RELEASES`` pre-cut main-artist releases. The subset holds
every pre- and post-cut release on which a seed is a main artist, so a seed's full profile
and its full post-cut neighbourhood are present. With ``--expand``, the pre-cut main-artist
releases of every artist that shares a *pre-cut* release with a seed are added too, so those
neighbours get their full pre-cut profiles. Expansion reads only pre-cut data, so it cannot
leak which artists turn up later.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

CUT = 20230101
MIN_ARTIST_RELEASES = 3
LISTS = ("artists", "credits", "trackartists", "labels", "genres", "styles")


def splitmix64(x: np.ndarray) -> np.ndarray:
    z = x.astype(np.uint64) + np.uint64(0x9E3779B97F4A7C15)
    z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return z ^ (z >> np.uint64(31))


def unit_hash(ids: np.ndarray, salt: int = 0) -> np.ndarray:
    """A deterministic uniform [0, 1) value per id."""
    return (splitmix64(ids.astype(np.uint64) ^ np.uint64(salt)) >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def load(src: Path) -> dict[str, np.ndarray]:
    arrays = {name: np.load(src / f"{name}.npy") for name in ("rel_id", "rel_date", "rel_master", "rel_fam")}
    for name in LISTS:
        arrays[f"{name}_ptr"] = np.load(src / f"{name}_ptr.npy")
        arrays[f"{name}_val"] = np.load(src / f"{name}_val.npy")
    return arrays


def row_of(ptr: np.ndarray) -> np.ndarray:
    """The owning release row of every value in a CSR list."""
    return np.repeat(np.arange(len(ptr) - 1, dtype=np.int64), np.diff(ptr))


def id_at_cut(rel_id: np.ndarray, rel_date: np.ndarray) -> int:
    """Estimate the release id Discogs was assigning on the cut date.

    Releases with a full date in 2023-01-16..2023-01-31 were, for the most part, catalogued on
    or shortly after that date; the 5th percentile of their ids is taken as the id at the cut,
    which errs toward excluding late-catalogued releases rather than admitting them.
    """
    window = (rel_date >= 20230116) & (rel_date <= 20230131)
    return int(np.percentile(rel_id[window], 5))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("src", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--rate", type=float, required=True, help="seed sampling rate over eligible artists")
    parser.add_argument("--expand", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    a = load(args.src)
    rel_id, rel_date = a["rel_id"], a["rel_date"]
    n = len(rel_id)
    cut_id = id_at_cut(rel_id, rel_date)
    pre = (rel_date > 0) & (rel_date < CUT) & (rel_id < cut_id)
    post = rel_date >= CUT
    stats = {
        "dump_releases": int(n),
        "id_at_cut": cut_id,
        "pre_cut_releases": int(pre.sum()),
        "post_cut_releases": int(post.sum()),
        "dropped_no_date": int((rel_date == 0).sum()),
        "dropped_catalogued_after_cut": int(((rel_date > 0) & (rel_date < CUT) & (rel_id >= cut_id)).sum()),
    }

    by_rows = row_of(a["artists_ptr"])
    by_vals = a["artists_val"]
    pre_by = pre[by_rows]
    counts = np.bincount(by_vals[pre_by], minlength=int(by_vals.max()) + 1)
    eligible = np.flatnonzero(counts >= MIN_ARTIST_RELEASES)
    seeds = eligible[unit_hash(eligible) < args.rate]
    is_seed = np.zeros(len(counts), dtype=bool)
    is_seed[seeds] = True
    stats |= {"eligible_artists": int(len(eligible)), "seed_rate": args.rate, "seed_artists": int(len(seeds))}

    seed_release = np.zeros(n, dtype=bool)
    seed_release[by_rows[is_seed[by_vals]]] = True
    keep = seed_release & (pre | post)

    if args.expand:
        neighbours = np.zeros(len(counts) if len(counts) > 0 else 1, dtype=bool)
        seed_pre = seed_release & pre
        for name in ("artists", "credits", "trackartists"):
            vals = a[f"{name}_val"]
            rows = row_of(a[f"{name}_ptr"])
            hit = vals[seed_pre[rows]]
            hit = hit[hit < len(neighbours)]
            neighbours[hit] = True
        neighbours &= ~is_seed
        expand = np.zeros(n, dtype=bool)
        expand[by_rows[neighbours[by_vals] & pre_by]] = True
        keep |= expand
        stats["expanded_neighbour_artists"] = int(neighbours.sum())

    stats |= {
        "subset_releases": int(keep.sum()),
        "subset_pre_cut_releases": int((keep & pre).sum()),
        "subset_post_cut_releases": int((keep & post).sum()),
    }

    rows = np.flatnonzero(keep)
    out: dict[str, np.ndarray] = {
        "rel_id": rel_id[rows],
        "rel_date": rel_date[rows],
        "rel_master": a["rel_master"][rows],
        "rel_fam": a["rel_fam"][rows],
        "rel_pre": pre[rows],
    }
    for name in LISTS:
        ptr, val = a[f"{name}_ptr"], a[f"{name}_val"]
        lengths = np.diff(ptr)[rows]
        new_ptr = np.zeros(len(rows) + 1, dtype=np.int64)
        np.cumsum(lengths, out=new_ptr[1:])
        out[f"{name}_ptr"] = new_ptr
        out[f"{name}_val"] = val[keep[row_of(ptr)]]
    out["seed_artists"] = seeds.astype(np.int32)
    stats["subset_artist_refs"] = int(len(np.unique(np.concatenate([out[f"{x}_val"] for x in ("artists", "credits", "trackartists")]))))
    stats["subset_labels"] = int(len(np.unique(out["labels_val"])))
    print(json.dumps(stats, indent=2))
    if args.dry_run:
        return
    args.out.mkdir(parents=True, exist_ok=True)
    for name, value in out.items():
        np.save(args.out / f"{name}.npy", value)
    (args.out / "vocab.json").write_text((args.src / "vocab.json").read_text())
    (args.out / "subset.json").write_text(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
