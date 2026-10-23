#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate the full-export proxy, then evaluate gm-design-loj9's bar on real months.

    python months.py <loj9 data dir> <6b8u data dir> <discogs 20261001 releases .npz> results/months.json

The spike document pre-registered the method, and each function below names the part it
implements. In short:

- A release's link time L is the earliest `last_updated` over its current Discogs links.
  Its creation C is `release_meta.date_added`.
- It is first loaded at D(C), the first MusicBrainz dump instant after C. Dumps are on
  Wednesdays and Saturdays at 00:10:01 UTC.
- If L < D(C), it is linked at ingest. Otherwise it is re-attached at the first monthly
  run after D(L). Runs are on the 1st of the month at 00:00 UTC.

Only counts, months, and rates are written.
"""

from __future__ import annotations

import gzip
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from math import ceil
from pathlib import Path
from typing import Any

import numpy as np


T_A = int(datetime(2026, 10, 17, 0, 10, 1, tzinfo=UTC).timestamp())  # JSON dump 20261017-001001
T_B = int(datetime(2026, 10, 21, 0, 10, 1, tzinfo=UTC).timestamp())  # JSON dump 20261021-001001
FIRST_LOAD_MONTH = (2025, 10)  # Discogs 20251001, then the next MusicBrainz dump
LAST_RUN_MONTH = (2026, 10)
BAR = {"precision": 0.90, "recall": 0.90, "G2": 1000, "G3": 1000}


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def dump_instants(start: datetime, end: datetime) -> np.ndarray:
    """MusicBrainz dump instants (Wednesday and Saturday, 00:10:01 UTC) in [start, end]."""
    day = datetime(start.year, start.month, start.day, 0, 10, 1, tzinfo=UTC)
    out = []
    while day <= end:
        if day.weekday() in (2, 5) and day >= start:
            out.append(int(day.timestamp()))
        day += timedelta(days=1)
    return np.asarray(out, dtype=np.int64)


def next_dump(dumps: np.ndarray, t: np.ndarray) -> np.ndarray:
    """The first dump instant strictly after each t (the dump that first carries it)."""
    return dumps[np.searchsorted(dumps, t, side="right")]


def month_start(year: int, month: int) -> int:
    return int(datetime(year, month, 1, tzinfo=UTC).timestamp())


def month_of(t: int) -> str:
    return datetime.fromtimestamp(int(t), UTC).strftime("%Y-%m")


def next_run(t: int) -> int:
    """The first monthly run (the 1st, 00:00 UTC) strictly after t."""
    moment = datetime.fromtimestamp(int(t), UTC)
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    return month_start(year, month)


def percentile_disc(values: list[int], p: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(ceil(Fraction(str(p)) * len(ordered)) - 1, 0)]


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def read_json_releases(path: Path) -> dict[str, tuple[int, str]]:
    rows = {}
    with gzip.open(path, "rt") as handle:
        for line in handle:
            mbid, did, group = line.rstrip("\n").split("\t")
            rows[mbid] = (int(did) if did else 0, group)
    return rows


def read_json_groups(path: Path) -> dict[str, int]:
    rows = {}
    with gzip.open(path, "rt") as handle:
        for line in handle:
            mbid, did = line.rstrip("\n").split("\t")[:2]
            rows[mbid] = int(did) if did else 0
    return rows


def read_ids(path: Path) -> np.ndarray:
    with gzip.open(path, "rt") as handle:
        return np.unique(np.asarray([int(line.split("\t", 1)[0]) for line in handle], dtype=np.int64))


def creation_bound(row_ids: np.ndarray, all_row_ids: np.ndarray, all_updated: np.ndarray) -> np.ndarray:
    """Proxy 2's c(k): the minimum `last_updated` over release-URL rows with id >= k.

    A zero (unparsed) `last_updated` is ignored, so one bad row cannot pull every earlier
    row back to 1970.
    """
    order = np.argsort(all_row_ids)
    ids = all_row_ids[order]
    updated = np.where(all_updated[order] > 0, all_updated[order], np.iinfo(np.int64).max)
    suffix_min = np.minimum.accumulate(updated[::-1])[::-1]
    return suffix_min[np.searchsorted(ids, row_ids)]


def read_release_masters(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Release ids and their master ids (0 for none) from gm-design-loj9's `extract_discogs.py` output."""
    ids, masters = [], []
    with gzip.open(path, "rt") as handle:
        for line in handle:
            release, master = line.rstrip("\n").split("\t")
            ids.append(int(release))
            masters.append(int(master) if master.isdigit() else 0)
    return np.asarray(ids, dtype=np.int64), np.asarray(masters, dtype=np.int64)


def link_history(core: Path, derived: Path, proxy: int = 1) -> dict[str, tuple[int, int, int, str]]:
    """mbid -> (L, C, Discogs id of the earliest link, release group mbid), for linked releases.

    Proxy 1 dates a link by its `last_updated`. Proxy 2 dates it by `creation_bound`.
    """
    links = np.load(core)
    meta = np.load(derived)
    added = dict(zip(meta["release_id"].tolist(), meta["date_added"].tolist(), strict=True))
    dated = links["last_updated"] if proxy == 1 else creation_bound(links["row_id"], links["all_row_id"], links["all_last_updated"])
    out: dict[str, tuple[int, int, int, str]] = {}
    for rid, did, updated, mbid, group in zip(links["release_id"].tolist(), links["discogs_id"].tolist(),
                                               dated.tolist(), links["mbid"].tolist(),
                                               links["group_mbid"].tolist(), strict=True):
        current = out.get(mbid)
        if current is None or updated < current[0]:
            out[mbid] = (updated, added.get(rid, 0), did, group)
    return out


# ---------------------------------------------------------------------------
# Validation against the exact diff
# ---------------------------------------------------------------------------


def validate(history: dict, json_a: dict, json_b: dict, t_a: int = T_A, t_b: int = T_B) -> dict[str, Any]:
    exact = {m for m, (did, _) in json_b.items() if did and m in json_a and not json_a[m][0]}
    proxy = {m for m, (link, created, _, _) in history.items() if created <= t_a and t_a < link <= t_b}
    hit = exact & proxy
    false_pos = Counter()
    for m in proxy - exact:
        if m not in json_a:
            false_pos["absent_from_dump_a"] += 1
        elif json_a[m][0]:
            false_pos["linked_in_dump_a (an older link edited in the window)"] += 1
        elif m not in json_b or not json_b[m][0]:
            false_pos["unlinked_in_dump_b"] += 1
        else:
            false_pos["other"] += 1
    false_neg = Counter()
    for m in exact - proxy:
        link, created, _, _ = history.get(m, (None, None, None, None))
        if link is None:
            false_neg["no_discogs_link_in_full_export"] += 1
        elif created > t_a:
            false_neg["created_after_dump_a_per_date_added"] += 1
        elif link <= t_a:
            false_neg["link_dated_before_window"] += 1
        else:
            false_neg["link_dated_after_window (edited later)"] += 1
    precision = len(hit) / len(proxy) if proxy else 0.0
    recall = len(hit) / len(exact) if exact else 0.0
    # Secondary: releases new in dump B that carry a link, against the proxy's creation in W.
    new_linked = {m for m, (did, _) in json_b.items() if did and m not in json_a}
    proxy_new = {m for m, (link, created, _, _) in history.items() if t_a < created <= t_b and link <= t_b}
    return {
        "window": f"{datetime.fromtimestamp(t_a, UTC):%Y-%m-%d %H:%M:%S} to {datetime.fromtimestamp(t_b, UTC):%Y-%m-%d %H:%M:%S} UTC",
        "exact_link_added": len(exact),
        "proxy_link_added": len(proxy),
        "both": len(hit),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "bar": {"precision": BAR["precision"], "recall": BAR["recall"]},
        "passes": precision >= BAR["precision"] and recall >= BAR["recall"],
        "false_positives": dict(false_pos),
        "false_negatives": dict(false_neg),
        "secondary_new_and_linked": {"exact": len(new_linked), "proxy": len(proxy_new), "both": len(new_linked & proxy_new)},
    }


# ---------------------------------------------------------------------------
# The monthly model
# ---------------------------------------------------------------------------


def months_between(first: tuple[int, int], last: tuple[int, int]) -> list[str]:
    year, month = first
    out = []
    while (year, month) <= last:
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def model(history: dict, json_b: dict, targets: np.ndarray | None = None) -> tuple[dict[int, dict[str, set[str]]], Counter, Counter, int, Counter]:
    """Per edition (Discogs release id), its event months by kind; per month, re-attachments and links at ingest.

    With `targets` (sorted Discogs release ids of a dump), a row whose Discogs release is not
    in it neither attaches nor re-attaches: it stays `unresolved` (`_LINKED` in
    `api/reattach.py` needs a current Discogs alias). Those rows are counted per month instead.

    Returns (events, reattached per run month, linked at ingest per month, pending after the
    last run, unresolved per month).
    """
    first_load_start = month_start(*FIRST_LOAD_MONTH)
    dumps = dump_instants(datetime(2000, 1, 1, tzinfo=UTC), datetime(2027, 12, 31, tzinfo=UTC))
    first_load = int(next_dump(dumps, np.asarray([first_load_start]))[0])
    last_run = month_start(*LAST_RUN_MONTH)
    mbids = list(history)
    link = np.asarray([history[m][0] for m in mbids], dtype=np.int64)
    created = np.asarray([history[m][1] for m in mbids], dtype=np.int64)
    loaded = np.maximum(next_dump(dumps, created), first_load)
    linked_at = next_dump(dumps, link)
    events: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    reattached, at_ingest, unresolved = Counter(), Counter(), Counter()
    pending = 0
    known = None
    if targets is not None:
        editions = np.asarray([json_b.get(m, (0, ""))[0] or history[m][2] for m in mbids], dtype=np.int64)
        known = np.isin(editions, targets)
    for i, mbid in enumerate(mbids):
        if loaded[i] > T_B:
            continue  # first loaded after the last dump read
        edition = json_b.get(mbid, (0, ""))[0] or history[mbid][2]
        if known is not None and not known[i]:
            unresolved[month_of(max(loaded[i], linked_at[i]))] += 1
            continue
        if link[i] < loaded[i]:
            month = month_of(loaded[i])
            at_ingest[month] += 1
            events[edition]["linked_at_ingest"].add(month)
            continue
        run = next_run(int(linked_at[i]))
        if run > last_run:
            pending += 1
            continue
        reattached[month_of(run)] += 1
        events[edition]["reattached"].add(month_of(run))
        if loaded[i] > first_load:
            events[edition]["musicbrainz_item_minted"].add(month_of(loaded[i]))
    return events, reattached, at_ingest, pending, unresolved


def g2(events: dict, parents: dict[int, set], include_mint: bool, after_first_load: bool = False) -> dict[str, Any]:
    first = f"{FIRST_LOAD_MONTH[0]:04d}-{FIRST_LOAD_MONTH[1]:02d}"
    editions_of: dict[Any, list[set[str]]] = defaultdict(list)
    for edition, kinds in events.items():
        months = set(kinds["linked_at_ingest"]) | set(kinds["reattached"])
        if include_mint:
            months |= set(kinds["musicbrainz_item_minted"])
        if after_first_load:
            months.discard(first)
        if not months:
            continue
        for work in parents.get(edition, ()):
            editions_of[work].append(months)
    two = {w: e for w, e in editions_of.items() if len(e) >= 2}
    multi = sum(1 for e in two.values() if len(set().union(*e)) >= 2)
    counts = [len(e) for e in editions_of.values()]
    return {
        "works_with_evented_editions": len(editions_of),
        "works_with_2plus_evented_editions": len(two),
        "works_with_2plus_evented_editions_multi_month": multi,
        "evented_editions_per_work": {"p50": percentile_disc(counts, 0.5), "p90": percentile_disc(counts, 0.9),
                                       "p99": percentile_disc(counts, 0.99), "max": max(counts) if counts else None},
    }


def work_parents(events: dict, history: dict, json_b: dict, groups_b: dict, ids: np.ndarray, masters: np.ndarray,
                 masters_b: np.ndarray) -> dict[int, set]:
    """gm-design-loj9's work parents: the Discogs master, and each MusicBrainz row's release group."""
    order = np.argsort(ids)
    ids, masters = ids[order], masters[order]
    wanted = np.fromiter(events, dtype=np.int64, count=len(events))
    index = np.clip(np.searchsorted(ids, wanted), 0, len(ids) - 1)
    loaded_master = np.isin(masters[index], masters_b)
    parents: dict[int, set] = defaultdict(set)
    for did, i, ok in zip(wanted.tolist(), index.tolist(), loaded_master.tolist(), strict=True):
        if ids[i] == did and masters[i] and ok:
            parents[did].add(("m", int(masters[i])))
    master_ids = set(masters_b.tolist())
    for mbid, (_, _, did0, group0) in history.items():
        edition = json_b.get(mbid, (0, ""))[0] or did0
        if edition not in events:
            continue
        group = json_b.get(mbid, (0, group0))[1] or group0
        if not group:
            continue
        group_master = groups_b.get(group, 0)
        parents[edition].add(("m", group_master) if group_master in master_ids else ("g", group))
    return parents


def evaluate(history: dict, json_b: dict, groups_b: dict, releases_b: Path, masters_b: np.ndarray) -> dict[str, Any]:
    if releases_b.suffix == ".npz":
        with np.load(releases_b) as arrays:
            ids, masters = arrays["id"], arrays["master"]
    else:
        ids, masters = read_release_masters(releases_b)
    events, reattached, at_ingest, pending, unresolved = model(history, json_b, np.sort(ids))
    parents = work_parents(events, history, json_b, groups_b, ids, masters, masters_b)
    runs = months_between((FIRST_LOAD_MONTH[0], FIRST_LOAD_MONTH[1] + 1), LAST_RUN_MONTH)
    first = f"{FIRST_LOAD_MONTH[0]:04d}-{FIRST_LOAD_MONTH[1]:02d}"
    per_month = {m: {"reattached": reattached.get(m, 0), "linked_at_ingest": at_ingest.get(m, 0),
                     "unresolved_target_not_in_discogs_dump": unresolved.get(m, 0),
                     "G1_run_writes": reattached.get(m, 0) > 0} for m in runs}
    g3_total = sum(reattached.get(m, 0) for m in runs)
    lower = g2(events, parents, include_mint=False)
    with_mint = g2(events, parents, include_mint=True)
    return {
        "prediction": "modelled from the MusicBrainz full export 20261021; not recorded history",
        "first_load_month": first,
        "first_load_linked_at_ingest": at_ingest.get(first, 0),
        "per_month": per_month,
        "reattached_after_last_run": pending,
        "G1": {"months_with_a_writing_run": sum(1 for m in runs if reattached.get(m, 0)), "bar": 2},
        "G2_lower_bound": {**lower, "bar": BAR["G2"]},
        "G2_with_musicbrainz_mint_months": {**with_mint, "bar": BAR["G2"]},
        "G2_after_first_load_only": g2(events, parents, include_mint=False, after_first_load=True),
        "G3": {"release_reattachments_12_runs": g3_total, "bar": BAR["G3"]},
        "editions_with_events": len(events),
        "editions_by_work_parents": dict(Counter("0" if not parents.get(e) else "1" if len(parents[e]) == 1 else "2+" for e in events)),
    }


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from guard import assert_aggregate_only

    loj9, data, releases_b, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
    core, derived = data / "mbhist_core_20261021-002201.npz", data / "mbhist_derived_20261021-002201.npz"
    json_a = read_json_releases(loj9 / "mb_release_20261017-001001.tsv.gz")
    json_b = read_json_releases(loj9 / "mb_release_20261021-001001.tsv.gz")
    result: dict[str, Any] = {}

    # Proxy 1: pre-registered at 9e9440a. Its validation on this window is binding.
    history = link_history(core, derived, proxy=1)
    result["proxy_1"] = {"validation": validate(history, json_a, json_b)}
    if not result["proxy_1"]["validation"]["passes"]:
        result["proxy_1"]["months"] = "not evaluated: the proxy failed its validation bar"

    # Proxy 2: registered at 8f7a5ed, after proxy 1 failed. On this window its validation is
    # a diagnostic; the binding window is 20261021 -> 20261024. Its months are conditional on
    # passing that window.
    history = link_history(core, derived, proxy=2)
    groups_b = read_json_groups(loj9 / "mb_release-group_20261021-001001.tsv.gz")
    masters_b = read_ids(loj9 / "discogs_masters_20261001.tsv.gz")
    result["proxy_2"] = {
        "validation_in_sample_diagnostic": validate(history, json_a, json_b),
        "validation_out_of_sample": "pending: JSON 20261021 -> 20261024 against full export 20261024",
        "months_conditional_on_out_of_sample_validation": evaluate(history, json_b, groups_b, releases_b, masters_b),
    }
    for name in ("proxy_1", "proxy_2"):
        print(name, json.dumps(result[name], indent=1)[:1500], file=sys.stderr)
    assert_aggregate_only(result)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
