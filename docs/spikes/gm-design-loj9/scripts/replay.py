#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Replay two load cycles of GrooveMap's identity jobs over real dumps, and count what they write.

GrooveMap has never been deployed, so no catalog holds identity history. This script
predicts the history from real data. It replays the identity rules the loaders and
catalog-api's section 8 job apply, cited below, over two consecutive dumps of each catalog,
and counts what each step would write. Every count is a **prediction from real dumps**, not
a measurement of a catalog.

The modelled deployment follows the runbook's order (`deployment/docs/maintenance.md`,
"Post-import identity maintenance": Discogs finishes before MusicBrainz starts, then the
re-attachment runs):

| Instant | Month | Step |
| --- | --- | --- |
| t1 | 1 | Discogs dump A loaded |
| t2 | 1 | MusicBrainz dump A loaded |
| t3 | 1 | re-attachment run R1 |
| t4 | 2 | Discogs dump B loaded |
| t5 | 2 | MusicBrainz dump B loaded |
| t6 | 2 | re-attachment run R2 |

Each step is one instant here. A real load spreads its writes over many transactions, but
they all fall in the same month, so event months are unaffected. Event *counts* per
edition can only be undercounted where two writes to one edition share a step.

Rules replayed, with the code each comes from:

- **Discogs mint.** Every record of a Discogs dump mints an item under its `discogs` alias
  (`discogs-sql-loader` `tableinator/batch_writer.py`, lines 76-82,
  `resolve_aliases` lookup-or-create). A record that is already aliased mints nothing. A
  record missing from a later dump closes nothing, because no code closes a `discogs`
  alias. Skip rules are applied in `extract_discogs.py`.
- **MusicBrainz attach or mint.** `_native_id` (`musicbrainz-sql-loader`
  `brainztableinator/_record_processing.py`, lines 279-304) attaches the row's
  `musicbrainz` alias to the Discogs item when the row names a Discogs id that already
  resolves, and otherwise mints the row its own item. `attach_aliases` never overwrites
  (`python-libraries` `src/common/identity.py`, line 325, `ON CONFLICT DO NOTHING` at line
  93). So a row already aliased keeps its item on every later load, whatever it now names.
  Rows missing from dump B stay in the table with their dump A values. The loader upserts
  and never deletes entity rows (`brainztableinator/_reconciliation.py` deletes only
  relationship and external-link rows).
- **Re-attachment population** (`catalog-api` `api/reattach.py`, `_LINKED` and
  `_CANDIDATE`, lines 166-192). A row is a candidate when it names a Discogs id with a
  current alias (item D) and its `musicbrainz` alias resolves to another item M. The
  `gm_item_id`-only "stale" case comes from a loader race, which this replay does not
  model.
- **Guards** (`_GUARDS`, lines 216-224). `shared_native_id` holds when M has a current
  alias that is neither an identifier nor this row's `musicbrainz` alias. M holds a
  `discogs` alias exactly when M is a Discogs item, that is, when the row attached at
  ingest and later named another Discogs id. An item minted for a row holds only that
  row's alias and identifiers. `non_catalog_alias` cannot hold, because every writer uses
  `source = 'catalog'`.
- **Re-attach and merge** (`reattach_item`, lines 480-553, and `api/catalog_merge.py`
  `merge_items`). An eligible row's aliases close on M and reopen on D at one instant, and
  one supersession M → D opens. `merge_items` refuses a merge only when the kinds differ,
  the survivor is superseded, or M already resolves elsewhere. None of those can happen
  here, because survivors are Discogs items and nothing supersedes one. No dependents
  exist in a fresh deployment, so nothing moves.
- **Kinds** (`KINDS`, lines 141-146): release → Discogs releases, release group → Discogs
  masters, artist, and label.

Identifier aliases (barcode, catalogue number) are not replayed. They open and close at
the same instant as the `musicbrainz` or `discogs` alias they travel with, so they change
no edition's instants. Counting them would mean replaying ADR 0011's normalization of both
catalogs' identifiers.
"""

from __future__ import annotations

import gzip
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from reference import distribution


KINDS = {"release": "releases", "release-group": "masters", "artist": "artists", "label": "labels"}
MONTH = {1: "month 1", 2: "month 1", 3: "month 1", 4: "month 2", 5: "month 2", 6: "month 2"}

# Row outcomes after R2.
LINKED, GUARDED, REATTACHED, UNRESOLVED, MUSICBRAINZ_ONLY = "linked", "guarded", "reattached", "unresolved", "musicbrainz_only"


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def read_mb(path: Path, kind: str) -> dict[str, tuple[int, str | None]]:
    """mbid -> (discogs id or 0, release group mbid or None) from `extract_mb.py` output."""
    rows: dict[str, tuple[int, str | None]] = {}
    with gzip.open(path, "rt") as handle:
        for line in handle:
            cells = line.rstrip("\n").split("\t")
            rows[cells[0]] = (int(cells[1]) if cells[1] else 0, (cells[2] or None) if kind == "release" else None)
    return rows


def read_discogs(path: Path, kind: str) -> tuple[np.ndarray, np.ndarray | None]:
    """Sorted unique ids, and for releases the master id aligned to them (0 for none).

    Reads `extract_discogs.py` output, or a `.npz` holding `id` and `master` arrays
    (gm-design-4804's `releases_<date>.npz`, from the same dump).
    """
    ids: list[int] = []
    masters: list[int] = []
    if path.suffix == ".npz":
        # gm-design-4804's releases_<date>.npz: `id` and `master` (0 for none) per release.
        with np.load(path) as arrays:
            ids, masters = arrays["id"].tolist(), arrays["master"].tolist()
    else:
        ids, masters = _read_tsv(path, kind)
    id_array = np.asarray(ids, dtype=np.int64)
    order = np.argsort(id_array, kind="stable")
    id_array = id_array[order]
    keep = np.ones(len(id_array), dtype=bool)
    keep[1:] = id_array[1:] != id_array[:-1]
    if kind != "releases":
        return id_array[keep], None
    return id_array[keep], np.asarray(masters, dtype=np.int64)[order][keep]


def _read_tsv(path: Path, kind: str) -> tuple[list[int], list[int]]:
    ids: list[int] = []
    masters: list[int] = []
    with gzip.open(path, "rt") as handle:
        for line in handle:
            cells = line.rstrip("\n").split("\t")
            ids.append(int(cells[0]))
            if kind == "releases":
                master = cells[1].strip() if len(cells) > 1 else ""
                masters.append(int(master) if master.isdigit() else 0)
    return ids, masters


# ---------------------------------------------------------------------------
# One kind's replay
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Row:
    """One MusicBrainz row's path through the two cycles. `item` is ('d', discogs id) or ('x', mbid)."""

    initial: tuple[str, Any]
    phase: int  # 2 or 5: the MusicBrainz load that first aliased it
    current: int  # the Discogs id the table row names after load B (0 for none)
    outcome: str = ""
    cause: str = ""  # for a re-attachment: discogs_arrived, link_added, or link_changed
    final: tuple[str, Any] = ("", None)
    group: str | None = None


@dataclass
class KindReplay:
    rows: dict[str, Row] = field(default_factory=dict)
    counts: dict[str, Any] = field(default_factory=dict)


def _present(named: set[int], ids: np.ndarray) -> set[int]:
    if not named:
        return set()
    probe = np.fromiter(named, dtype=np.int64, count=len(named))
    return set(probe[np.isin(probe, ids, assume_unique=True)].tolist())


def replay_kind(mb_a: dict, mb_b: dict, discogs_a: np.ndarray, discogs_b: np.ndarray) -> KindReplay:
    named = {did for did, _ in mb_a.values() if did} | {did for did, _ in mb_b.values() if did}
    in_a = _present(named, discogs_a)
    loaded_b = in_a | _present(named, discogs_b)
    result = KindReplay()
    linked_at_ingest = Counter()
    minted = Counter()
    r1 = Counter()

    # t2: MusicBrainz A against Discogs A.
    for mbid, (did, group) in mb_a.items():
        if did and did in in_a:
            row = Row(("d", did), 2, did)
            linked_at_ingest[2] += 1
        else:
            row = Row(("x", mbid), 2, did)
            minted[2] += 1
        row.group = group
        result.rows[mbid] = row
    # t3: R1 over the same state. A row whose Discogs id resolves attached to it at t2, so
    # this is zero after a staged first load; it is computed, not assumed.
    for row in result.rows.values():
        if row.current and row.current in in_a and row.initial != ("d", row.current):
            r1["guarded" if row.initial[0] == "d" else "reattached"] += 1
    # t5: MusicBrainz B against Discogs A and B. Existing rows keep their alias.
    for mbid, (did, group) in mb_b.items():
        row = result.rows.get(mbid)
        if row is None:
            if did and did in loaded_b:
                row = Row(("d", did), 5, did)
                linked_at_ingest[5] += 1
            else:
                row = Row(("x", mbid), 5, did)
                minted[5] += 1
            result.rows[mbid] = row
        row.current, row.group = did, group
    # t6: R2.
    outcomes = Counter()
    causes = Counter()
    for mbid, row in result.rows.items():
        did = row.current
        if not did:
            row.outcome, row.final = (LINKED if row.initial[0] == "d" else MUSICBRAINZ_ONLY), row.initial
        elif did not in loaded_b:
            row.outcome, row.final = UNRESOLVED, row.initial
        elif row.initial == ("d", did):
            row.outcome, row.final = LINKED, row.initial
        elif row.initial[0] == "d":
            row.outcome, row.final = GUARDED, row.initial
        else:
            original = mb_a.get(mbid, (0, None))[0] if row.phase == 2 else 0
            row.cause = "link_added" if not original else "discogs_arrived" if original == did else "link_changed"
            row.outcome, row.final = REATTACHED, ("d", did)
            causes[row.cause] += 1
        outcomes[row.outcome] += 1

    result.counts = {
        "musicbrainz_rows": {"dump_a": len(mb_a), "dump_b": len(mb_b), "table_after_b": len(result.rows),
                             "new_in_b": len(result.rows) - len(mb_a), "missing_from_b": sum(1 for m in mb_a if m not in mb_b)},
        "musicbrainz_linked": {"dump_a": sum(1 for d, _ in mb_a.values() if d), "dump_b": sum(1 for d, _ in mb_b.values() if d)},
        "discogs_records": {"dump_a": int(len(discogs_a)), "dump_b": int(len(discogs_b)),
                            "new_in_b": int((~np.isin(discogs_b, discogs_a, assume_unique=True)).sum()),
                            "missing_from_b": int((~np.isin(discogs_a, discogs_b, assume_unique=True)).sum())},
        "linked_at_ingest": {"t2": linked_at_ingest[2], "t5": linked_at_ingest[5]},
        "musicbrainz_items_minted": {"t2": minted[2], "t5": minted[5]},
        "r1": {"reattached": r1["reattached"], "guarded": r1["guarded"]},
        "r2": {"reattached": outcomes[REATTACHED], "guarded_shared_native_id": outcomes[GUARDED],
               "unresolved": outcomes[UNRESOLVED], "linked": outcomes[LINKED], "musicbrainz_only": outcomes[MUSICBRAINZ_ONLY],
               "reattached_by_cause": dict(causes)},
    }
    return result


def alias_windows(kind_counts: dict[str, Any]) -> dict[str, Any]:
    """`provider_aliases` rows each step opens and closes (the `discogs` and `musicbrainz` aliases only)."""
    d, linked, minted, r2 = kind_counts["discogs_records"], kind_counts["linked_at_ingest"], kind_counts["musicbrainz_items_minted"], kind_counts["r2"]
    return {
        "opened": {"t1": d["dump_a"], "t2": linked["t2"] + minted["t2"], "t3": kind_counts["r1"]["reattached"],
                   "t4": d["new_in_b"], "t5": linked["t5"] + minted["t5"], "t6": r2["reattached"]},
        "closed": {"t3": kind_counts["r1"]["reattached"], "t6": r2["reattached"]},
    }


# ---------------------------------------------------------------------------
# The release ledger
# ---------------------------------------------------------------------------


def _months(instants: set[int]) -> set[str]:
    first = min(instants)
    return {MONTH[t] for t in instants if t != first}


def ledger(releases: KindReplay, groups: KindReplay, rel_a: np.ndarray, rel_b: np.ndarray,
           masters_of_a: np.ndarray, masters_of_b: np.ndarray, masters_a: np.ndarray, masters_b: np.ndarray) -> dict[str, Any]:
    """The `ledger` section of `reference.identity_history`, from the replayed state.

    An edition is ('d', discogs release id) or ('x', mbid) as resolved after R2. Its
    instants are its mint, each MusicBrainz attach at ingest, and for each item superseded
    into it that item's mint and the supersession. Work parents come from the Discogs
    release's master and each MusicBrainz row's release group, resolved the same way.
    """
    # Discogs release table after load B: dump B's rows, plus dump A's rows missing from B.
    only_a = ~np.isin(rel_a, rel_b, assume_unique=True)
    rel_ids = np.concatenate([rel_b, rel_a[only_a]])
    rel_masters = np.concatenate([masters_of_b, masters_of_a[only_a]])
    order = np.argsort(rel_ids)
    rel_ids, rel_masters = rel_ids[order], rel_masters[order]
    loaded_masters = np.union1d(masters_a, masters_b)
    master_ok = np.isin(rel_masters, loaded_masters)

    def work_of_group(mbid: str | None) -> tuple[str, Any] | None:
        row = groups.rows.get(mbid) if mbid else None
        if row is None:
            return None
        return ("m", row.final[1]) if row.final[0] == "d" else ("g", row.final[1])

    instants: dict[tuple[str, Any], set[int]] = defaultdict(set)
    parents: dict[tuple[str, Any], set[tuple[str, Any]]] = defaultdict(set)
    repaired: set[tuple[str, Any]] = set()
    touched_d = {row.final[1] for row in releases.rows.values() if row.final[0] == "d"}
    probe = np.fromiter(touched_d, dtype=np.int64, count=len(touched_d))
    in_rel_a = set(probe[np.isin(probe, rel_a, assume_unique=True)].tolist())
    for row in releases.rows.values():
        edition = row.final
        if edition[0] == "d":
            instants[edition].add(1 if edition[1] in in_rel_a else 4)
        # The load that first aliased the row: an attach at ingest, or its own item's mint.
        instants[edition].add(row.phase)
        if row.outcome == REATTACHED:
            instants[edition].add(6)
            repaired.add(edition)
        work = work_of_group(row.group)
        if work is not None:
            parents[edition].add(work)
    # Discogs parents of touched editions.
    index = np.searchsorted(rel_ids, probe)
    for did, i in zip(probe.tolist(), index.tolist(), strict=True):
        if i < len(rel_ids) and rel_ids[i] == did and master_ok[i]:
            parents[("d", did)].add(("m", int(rel_masters[i])))

    # Untouched Discogs editions: one instant, no events, at most the Discogs parent.
    untouched = ~np.isin(rel_ids, probe, assume_unique=True)
    untouched_with_master = untouched & master_ok
    works: set[tuple[str, Any]] = {("m", int(m)) for m in np.unique(rel_masters[untouched_with_master]).tolist()}

    evented = {e for e, times in instants.items() if len(times) >= 2}
    months = {e: _months(times) for e, times in instants.items() if e in evented}
    editions_of: dict[tuple[str, Any], set[tuple[str, Any]]] = defaultdict(set)
    by_work_count = Counter()
    for edition in instants:
        mine = parents.get(edition, set())
        works |= mine
        by_work_count["0" if not mine else "1" if len(mine) == 1 else "2+"] += 1
        if edition in evented or edition in repaired:
            for work in mine:
                editions_of[work].add(edition)
    by_work_count["1"] += int(untouched_with_master.sum())
    by_work_count["0"] += int((untouched & ~master_ok).sum())

    per_work = {w: len(e & evented) for w, e in editions_of.items()}
    multi_month = sum(1 for w, e in editions_of.items() if per_work[w] >= 2 and len(set().union(*(months[x] for x in e & evented))) >= 2)
    split_now = sum(1 for row in releases.rows.values() if row.outcome == GUARDED)
    unresolved_now = sum(1 for row in releases.rows.values() if row.outcome == UNRESOLVED)
    return {
        "editions": len(instants) + int(untouched.sum()),
        "editions_with_events": len(evented),
        "editions_repaired": len(repaired),
        "editions_events_multi_month": sum(1 for m in months.values() if len(m) >= 2),
        "editions_by_work_count": {key: by_work_count.get(key, 0) for key in ("0", "1", "2+")},
        "works": len(works),
        "works_with_2plus_evented_editions": sum(1 for n in per_work.values() if n >= 2),
        "works_with_2plus_evented_editions_multi_month": multi_month,
        "works_with_2plus_repaired_editions": sum(1 for e in editions_of.values() if len(e & repaired) >= 2),
        "evented_editions_per_work": distribution([n for n in per_work.values() if n >= 1]),
        "split_now": split_now,
        "unresolved_now": unresolved_now,
        "edition_event_types": event_types(releases),
    }


def event_types(releases: KindReplay) -> dict[str, dict[str, int]]:
    """Release events per modelled month, by type: the state mix the ledger would color."""
    mix: dict[str, Counter] = {"month 1": Counter(), "month 2": Counter()}
    for row in releases.rows.values():
        month = MONTH[row.phase]
        mix[month]["linked_at_ingest" if row.initial[0] == "d" else "musicbrainz_item_minted"] += 1
        if row.outcome == REATTACHED:
            mix["month 2"]["reattached"] += 1
    return {month: dict(counter) for month, counter in mix.items()}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run(data: Path, mb_dumps: tuple[str, str], discogs_dumps: tuple[str, str], releases_b: Path | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "prediction": "replayed from real dumps; not measured on a catalog",
        "musicbrainz_dumps": [f"json-dumps/{dump}" for dump in mb_dumps],
        "discogs_dumps": [f"discogs_{dump}" for dump in discogs_dumps],
        "kinds": {},
    }
    replays: dict[str, KindReplay] = {}
    discogs: dict[str, tuple] = {}
    for kind, discogs_kind in KINDS.items():
        a_ids, a_masters = read_discogs(data / f"discogs_{discogs_kind}_{discogs_dumps[0]}.tsv.gz", discogs_kind)
        b_path = releases_b if (discogs_kind == "releases" and releases_b) else data / f"discogs_{discogs_kind}_{discogs_dumps[1]}.tsv.gz"
        b_ids, b_masters = read_discogs(b_path, discogs_kind)
        discogs[discogs_kind] = (a_ids, a_masters, b_ids, b_masters)
        mb_a = read_mb(data / f"mb_{kind}_{mb_dumps[0]}.tsv.gz", kind)
        mb_b = read_mb(data / f"mb_{kind}_{mb_dumps[1]}.tsv.gz", kind)
        replay = replay_kind(mb_a, mb_b, a_ids, b_ids)
        del mb_a, mb_b
        out["kinds"][kind] = {**replay.counts, "alias_windows": alias_windows(replay.counts)}
        print(f"{kind}: {json.dumps(replay.counts['r2'])}", file=sys.stderr)
        if kind in ("release", "release-group"):
            replays[kind] = replay
        else:
            del replay
    rel_a, mas_of_a, rel_b, mas_of_b = discogs["releases"]
    out["ledger"] = ledger(replays["release"], replays["release-group"], rel_a, rel_b, mas_of_a, mas_of_b,
                           discogs["masters"][0], discogs["masters"][2])
    runs = {f"r{n}": {kind: out["kinds"][kind][f"r{n}"]["reattached"] for kind in KINDS} for n in (1, 2)}
    out["supersessions_per_run"] = runs
    return out


def main() -> None:
    import argparse

    from measure import assert_aggregate_only

    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--mb", nargs=2, required=True, metavar=("A", "B"))
    parser.add_argument("--discogs", nargs=2, required=True, metavar=("A", "B"))
    parser.add_argument("--releases-b", type=Path, help="dump B releases compacted elsewhere (.npz with id and master)")
    args = parser.parse_args()
    result = run(args.data, tuple(args.mb), tuple(args.discogs), args.releases_b)
    assert_aggregate_only(result)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
