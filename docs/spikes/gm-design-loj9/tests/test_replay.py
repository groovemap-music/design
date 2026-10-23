# SPDX-License-Identifier: MIT
"""The two-cycle replay on invented dumps: each rule's outcome, and the ledger it implies.

Discogs ids are invented small integers and MusicBrainz ids are letters. The invented dumps:

- Discogs releases A: 1, 2 (master 100), 3 (master 101), 4 (no master). B adds 5 (master
  100) and 6 (master 102). Masters A: 100, 101; B adds 102.
- MusicBrainz releases A:
  - a names 1;
  - b names 5, not loaded yet;
  - c names nothing, then 3 in B;
  - d names 2, then 6 in B;
  - e names 7, which never arrives;
  - f names nothing;
  - g names 9, then 2 in B.
  B drops a, and adds h (names 6) and i (names nothing).
- Release groups A: g1 names 100, g2 nothing, g3 names 105 (never loaded). In B, g2 names
  102.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from reference import identity_history, load
from replay import GUARDED, LINKED, MUSICBRAINZ_ONLY, REATTACHED, UNRESOLVED, KindReplay, ledger, replay_kind

REL_A = np.array([1, 2, 3, 4], dtype=np.int64)
MAS_OF_A = np.array([100, 100, 101, 0], dtype=np.int64)
REL_B = np.array([1, 2, 3, 4, 5, 6], dtype=np.int64)
MAS_OF_B = np.array([100, 100, 101, 0, 100, 102], dtype=np.int64)
MASTERS_A = np.array([100, 101], dtype=np.int64)
MASTERS_B = np.array([100, 101, 102], dtype=np.int64)

MB_A = {"a": (1, "g1"), "b": (5, "g1"), "c": (0, "g2"), "d": (2, "g1"), "e": (7, "g3"), "f": (0, "g2"), "g": (9, "g1")}
MB_B = {"b": (5, "g1"), "c": (3, "g2"), "d": (6, "g1"), "e": (7, "g3"), "f": (0, "g2"), "g": (2, "g1"), "h": (6, "g2"), "i": (0, "g2")}
RG_A = {"g1": (100, None), "g2": (0, None), "g3": (105, None)}
RG_B = {"g1": (100, None), "g2": (102, None), "g3": (105, None)}


@pytest.fixture(scope="module")
def replays():
    return replay_kind(MB_A, MB_B, REL_A, REL_B), replay_kind(RG_A, RG_B, MASTERS_A, MASTERS_B)


def test_each_row_takes_the_path_the_code_gives_it(replays):
    releases, _ = replays
    outcome = {mbid: row.outcome for mbid, row in releases.rows.items()}
    assert outcome == {"a": LINKED, "b": REATTACHED, "c": REATTACHED, "d": GUARDED, "e": UNRESOLVED,
                       "f": MUSICBRAINZ_ONLY, "g": REATTACHED, "h": LINKED, "i": MUSICBRAINZ_ONLY}
    causes = {mbid: row.cause for mbid, row in releases.rows.items() if row.cause}
    assert causes == {"b": "discogs_arrived", "c": "link_added", "g": "link_changed"}
    # A row dropped from dump B stays in the table and keeps its alias.
    assert releases.rows["a"].final == ("d", 1)
    # A guarded row keeps the Discogs item it attached to at ingest.
    assert releases.rows["d"].final == ("d", 2)


def test_counts_per_step(replays):
    releases, groups = replays
    counts = releases.counts
    assert counts["linked_at_ingest"] == {"t2": 2, "t5": 1}
    assert counts["musicbrainz_items_minted"] == {"t2": 5, "t5": 1}
    assert counts["r1"] == {"reattached": 0, "guarded": 0}
    assert counts["r2"]["reattached"] == 3 and counts["r2"]["guarded_shared_native_id"] == 1
    assert counts["discogs_records"] == {"dump_a": 4, "dump_b": 6, "new_in_b": 2, "missing_from_b": 0}
    assert counts["musicbrainz_rows"]["missing_from_b"] == 1
    assert groups.counts["r2"]["reattached"] == 1 and groups.counts["r2"]["unresolved"] == 1


def test_ledger_by_hand(replays):
    result = ledger(*replays, REL_A, REL_B, MAS_OF_A, MAS_OF_B, MASTERS_A, MASTERS_B)
    assert result["editions"] == 9
    assert (result["editions_with_events"], result["editions_repaired"], result["editions_events_multi_month"]) == (5, 3, 2)
    assert result["editions_by_work_count"] == {"0": 1, "1": 7, "2+": 1}
    assert result["works"] == 4
    assert result["works_with_2plus_evented_editions"] == 2
    assert result["works_with_2plus_evented_editions_multi_month"] == 2
    assert result["works_with_2plus_repaired_editions"] == 1
    assert result["evented_editions_per_work"] == {"p50": 2, "p90": 3, "p99": 3, "max": 3}
    assert (result["split_now"], result["unresolved_now"]) == (1, 1)


T0 = datetime(2026, 9, 1, tzinfo=UTC)
INSTANT = {1: T0, 2: T0 + timedelta(days=1), 3: T0 + timedelta(days=2),
           4: T0 + timedelta(days=30), 5: T0 + timedelta(days=31), 6: T0 + timedelta(days=32)}


def materialize(releases: KindReplay, groups: KindReplay) -> dict:
    """The rows the replayed jobs would have written, as `reference.load` reads them."""
    items, aliases, supersessions = [], [], []
    serial = iter(range(1, 10**6))

    def uid() -> str:
        return f"00000000-0000-4000-8000-{next(serial):012x}"

    native: dict[tuple, str] = {}

    def item(key: tuple, kind: str, t: int) -> str:
        if key not in native:
            native[key] = uid()
            items.append({"id": native[key], "kind": kind, "created_at": INSTANT[t].isoformat()})
        return native[key]

    def alias(provider, kind, external, native_id, t_from, t_to=None):
        aliases.append({"id": uid(), "provider": provider, "entity_kind": kind, "external_id": external, "native_id": native_id,
                        "valid_from": INSTANT[t_from].isoformat(), "valid_to": INSTANT[t_to].isoformat() if t_to else None,
                        "source": "catalog"})

    for kind, ids_a, ids_b in (("release", REL_A, REL_B), ("master", MASTERS_A, MASTERS_B)):
        for did in sorted(set(ids_a.tolist()) | set(ids_b.tolist())):
            t = 1 if did in ids_a else 4
            alias("discogs", kind, str(did), item(("d", kind, did), kind, t), t)
    for kind, replay in (("release", releases), ("master", groups)):
        for mbid, row in replay.rows.items():
            first = item(("d", kind, row.initial[1]), kind, row.phase) if row.initial[0] == "d" else item(("x", kind, mbid), kind, row.phase)
            if row.outcome == REATTACHED:
                alias("musicbrainz", kind, mbid, first, row.phase, 6)
                survivor = native[("d", kind, row.final[1])]
                alias("musicbrainz", kind, mbid, survivor, 6)
                supersessions.append({"id": uid(), "superseded_id": first, "survivor_id": survivor, "cause": "catalog_reattachment",
                                      "decision_ref": uid(), "valid_from": INSTANT[6].isoformat(), "valid_to": None, "via_id": None})
            else:
                alias("musicbrainz", kind, mbid, first, row.phase)
    masters = dict(zip(REL_A.tolist(), MAS_OF_A.tolist(), strict=True)) | dict(zip(REL_B.tolist(), MAS_OF_B.tolist(), strict=True))
    return {
        "catalog_items": items, "provider_aliases": aliases, "catalog_item_supersessions": supersessions,
        "catalog_item_moves": [], "admin_audit_log": [],
        "discogs_releases": [{"data_id": str(r), "master_id": str(m) if m else None} for r, m in masters.items()],
        "musicbrainz_releases": [{"mbid": mbid, "release_group_mbid": row.group, "discogs_release_id": row.current or None}
                                 for mbid, row in releases.rows.items()],
    }


def test_replay_ledger_equals_the_reference_on_the_rows_it_implies(replays):
    expected = identity_history(load(materialize(*replays)))
    got = ledger(*replays, REL_A, REL_B, MAS_OF_A, MAS_OF_B, MASTERS_A, MASTERS_B)
    got.pop("edition_event_types")
    assert got == expected["ledger"]
    assert expected["transitions"]["superseded"] == {"catalog_reattachment/release": 3, "catalog_reattachment/master": 1}
