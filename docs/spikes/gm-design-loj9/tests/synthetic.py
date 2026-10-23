# SPDX-License-Identifier: MIT
"""An invented catalog that walks every identity path the code allows today.

No Discogs or MusicBrainz data: ids, identifiers, and times are made up. Native ids are
`00000000-0000-4000-8000-…`, Discogs ids are `9000xx`, MusicBrainz ids are
`00000000-0000-4000-9000-…`, and identifiers say `synthetic`.

The story, in transaction time (each loader message and each re-attached item is its own
transaction, so each gets its own instant):

- 2026-08-01, Discogs load 1: masters 900101, 900102, 900103; releases 900001, 900002,
  900004 (master 900101), 900005, 900006 (master 900102). Each mints an item.
- 2026-08-03, MusicBrainz load 1, after Discogs as the runbook requires:
  - release group g1 names master 900101 and attaches to its item; g3 names 900103 and
    attaches; g2 and g4 name no master and mint their own items; g5 names master 900105,
    which is not loaded yet, so it mints its own item;
  - r1 names 900001 and attaches, with a catalogue number Discogs did not claim;
  - r3 names 900003, which is not loaded yet, so it mints its own item and wins a barcode;
  - r5 names no Discogs release; r6 and r7 name 900005 and 900006 and attach;
  - r8 names 900008 (not loaded yet) and mints its own item; an hour later a person adds a
    matrix alias to it (`source = 'user'`), which will guard it;
  - r9 names 900009, which never arrives.
- 2026-09-01, Discogs load 2: releases 900003 (master 900101) and 900008 (master 900103).
- 2026-09-02, re-attachment run 1: r3's item is superseded into 900003's, its MusicBrainz
  alias and barcode move; r8's item is guarded and left split.
- 2026-09-10, MusicBrainz load 2: r2 names 900002 and attaches.
- 2026-10-01, Discogs load 3: master 900105.
- 2026-10-05, a MusicBrainz reload attaches a matrix inscription r1 now carries.
- 2026-10-02, re-attachment run 2: g5's item is superseded into 900105's.

Nothing promotes, reverts, compresses a chain, or moves a dependent: no writer for any of
those exists today. Tests add them as variants.
"""

from __future__ import annotations

import copy
from typing import Any


def native(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012x}"


def mbid(n: int) -> str:
    return f"00000000-0000-4000-9000-{n:012x}"


D1 = "2026-08-01T02:00:00+00:00"
D2 = "2026-09-01T02:00:00+00:00"
D3 = "2026-10-01T02:00:00+00:00"
RUN1, RUN2 = native(0xA001), native(0xA002)
R1 = "2026-09-02T10:00:00+00:00"
R2 = "2026-10-02T10:00:00+00:00"
ADMIN = native(0xF001)


def at(base: str, seconds: int) -> str:
    """`base` plus a few seconds, as each message's own transaction instant."""
    hour, minute = base[11:13], base[14:16]
    return f"{base[:11]}{hour}:{minute}:{seconds:02d}+00:00"


def mb_load(seconds: int) -> str:
    return at("2026-08-03T05:00:00+00:00", seconds)


# Native items.
W1, W2, W3 = native(0x101), native(0x102), native(0x103)
G2, G4, G5X, W5 = native(0x202), native(0x204), native(0x205), native(0x105)
E1, E2, E4, E6, E7 = native(0x1), native(0x2), native(0x4), native(0x6), native(0x7)
X3, E3, E5, X8, E8, X9 = native(0x13), native(0x3), native(0x5), native(0x18), native(0x8), native(0x19)
S3, S5 = native(0x5003), native(0x5005)


def build() -> dict[str, list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    serial = iter(range(0x10000, 0x20000))

    def item(item_id: str, kind: str, created_at: str) -> None:
        items.append({"id": item_id, "kind": kind, "created_at": created_at})

    def alias(provider: str, kind: str, external_id: str, native_id: str, valid_from: str, valid_to: str | None = None, source: str = "catalog") -> None:
        aliases.append(
            {
                "id": native(next(serial)),
                "provider": provider,
                "entity_kind": kind,
                "external_id": external_id,
                "native_id": native_id,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "source": source,
            }
        )

    # Discogs load 1.
    for item_id, external in ((W1, "900101"), (W2, "900102"), (W3, "900103")):
        item(item_id, "master", D1)
        alias("discogs", "master", external, item_id, D1)
    for item_id, external, barcode in ((E1, "900001", "synthetic-barcode-1"), (E2, "900002", None), (E4, "900004", None), (E6, "900005", None), (E7, "900006", None)):
        item(item_id, "release", D1)
        alias("discogs", "release", external, item_id, D1)
        if barcode:
            alias("barcode", "release", barcode, item_id, D1)

    # MusicBrainz load 1.
    alias("musicbrainz", "master", mbid(0xB1), W1, mb_load(1))
    alias("musicbrainz", "master", mbid(0xB3), W3, mb_load(2))
    for item_id, group, seconds in ((G2, 0xB2, 3), (G4, 0xB4, 4), (G5X, 0xB5, 5)):
        item(item_id, "master", mb_load(seconds))
        alias("musicbrainz", "master", mbid(group), item_id, mb_load(seconds))
    alias("musicbrainz", "release", mbid(0x1), E1, mb_load(10))
    alias("catalog_number", "release", "synthetic-catno-1", E1, mb_load(10))
    item(X3, "release", mb_load(11))
    alias("musicbrainz", "release", mbid(0x3), X3, mb_load(11), valid_to=R1)
    alias("barcode", "release", "synthetic-barcode-3", X3, mb_load(11), valid_to=R1)
    item(E5, "release", mb_load(12))
    alias("musicbrainz", "release", mbid(0x5), E5, mb_load(12))
    alias("musicbrainz", "release", mbid(0x6), E6, mb_load(13))
    alias("musicbrainz", "release", mbid(0x7), E7, mb_load(14))
    item(X8, "release", mb_load(15))
    alias("musicbrainz", "release", mbid(0x8), X8, mb_load(15))
    alias("matrix", "release", "synthetic-matrix-8", X8, "2026-08-03T06:00:15+00:00", source="user")
    item(X9, "release", mb_load(16))
    alias("musicbrainz", "release", mbid(0x9), X9, mb_load(16))

    # Discogs load 2. The Discogs loader loses r3's barcode to the split item, so 900003
    # carries only its Discogs alias.
    item(E3, "release", D2)
    alias("discogs", "release", "900003", E3, D2)
    item(E8, "release", D2)
    alias("discogs", "release", "900008", E8, D2)

    # Re-attachment run 1: r3's aliases move in one transaction.
    r3 = at(R1, 1)
    aliases[[a["external_id"] for a in aliases].index(mbid(0x3))]["valid_to"] = r3
    aliases[[a["external_id"] for a in aliases].index("synthetic-barcode-3")]["valid_to"] = r3
    alias("musicbrainz", "release", mbid(0x3), E3, r3)
    alias("barcode", "release", "synthetic-barcode-3", E3, r3)

    # MusicBrainz load 2.
    alias("musicbrainz", "release", mbid(0x2), E2, "2026-09-10T05:00:00+00:00")

    # A MusicBrainz reload in October attaches a matrix inscription r1 now carries.
    alias("matrix", "release", "synthetic-matrix-1", E1, "2026-10-05T05:00:00+00:00")

    # Discogs load 3 and re-attachment run 2.
    item(W5, "master", D3)
    alias("discogs", "master", "900105", W5, D3)
    g5 = at(R2, 1)
    aliases[[a["external_id"] for a in aliases].index(mbid(0xB5))]["valid_to"] = g5
    alias("musicbrainz", "master", mbid(0xB5), W5, g5)

    supersessions = [
        {"id": S3, "superseded_id": X3, "survivor_id": E3, "cause": "catalog_reattachment", "decision_ref": RUN1, "valid_from": r3, "valid_to": None, "via_id": None},
        {"id": S5, "superseded_id": G5X, "survivor_id": W5, "cause": "catalog_reattachment", "decision_ref": RUN2, "valid_from": g5, "valid_to": None, "via_id": None},
    ]

    def outcomes(release: dict[str, int], release_group: dict[str, int]) -> dict[str, Any]:
        empty = {"reattached": 0, "guarded": 0, "unchanged": 0, "failed": 0, "supersessions_opened": 0, "merged_with_dependents": 0}
        return {"release": {**empty, **release}, "release_group": {**empty, **release_group}, "artist": empty, "label": empty}

    audit = [
        {"id": RUN1, "admin_id": ADMIN, "action": "identity.reattach.auto", "target": "discogs:20260901", "created_at": R1,
         "details": {"job_id": RUN1, "apply": True, "outcomes": outcomes({"reattached": 1, "guarded": 1, "supersessions_opened": 1}, {})}},
        {"id": native(0xA011), "admin_id": ADMIN, "action": "identity.project.trigger", "target": None, "created_at": "2026-09-02T11:00:00+00:00",
         "details": {"job_id": native(0xA012)}},
        {"id": RUN2, "admin_id": ADMIN, "action": "identity.reattach.auto", "target": "discogs:20261001", "created_at": R2,
         "details": {"job_id": RUN2, "apply": True, "outcomes": outcomes({"guarded": 1, "unchanged": 1}, {"reattached": 1, "supersessions_opened": 1})}},
        {"id": native(0xA021), "admin_id": ADMIN, "action": "admin.login", "target": "someone@example.invalid", "created_at": R2, "details": {"success": True}},
    ]

    discogs_releases = [
        {"data_id": "900001", "master_id": "900101"},
        {"data_id": "900002", "master_id": "900101"},
        {"data_id": "900003", "master_id": " 900101 "},
        {"data_id": "900004", "master_id": "900101"},
        {"data_id": "900005", "master_id": "900102"},
        {"data_id": "900006", "master_id": "900102"},
        {"data_id": "900008", "master_id": "900103"},
    ]
    musicbrainz_releases = [
        {"mbid": mbid(0x1), "release_group_mbid": mbid(0xB1), "discogs_release_id": 900001},
        {"mbid": mbid(0x2), "release_group_mbid": mbid(0xB1), "discogs_release_id": 900002},
        {"mbid": mbid(0x3), "release_group_mbid": mbid(0xB1), "discogs_release_id": 900003},
        {"mbid": mbid(0x5), "release_group_mbid": mbid(0xB1), "discogs_release_id": None},
        {"mbid": mbid(0x6), "release_group_mbid": mbid(0xB2), "discogs_release_id": 900005},
        {"mbid": mbid(0x7), "release_group_mbid": mbid(0xB2), "discogs_release_id": 900006},
        {"mbid": mbid(0x8), "release_group_mbid": mbid(0xB3), "discogs_release_id": 900008},
        {"mbid": mbid(0x9), "release_group_mbid": mbid(0xB4), "discogs_release_id": 900009},
    ]

    return {
        "catalog_items": items,
        "provider_aliases": aliases,
        "catalog_item_supersessions": supersessions,
        "catalog_item_moves": [],
        "admin_audit_log": audit,
        "discogs_releases": discogs_releases,
        "musicbrainz_releases": musicbrainz_releases,
    }


def with_writers_that_do_not_exist_yet() -> dict[str, list[dict[str, Any]]]:
    """The base story plus a promotion, its revert, a chain, and a ledgered move.

    None of these can be written today (no promotion path, no caller of
    `revert_supersession`, survivors always hold a Discogs alias, and no writer creates a
    dependent on a MusicBrainz-side item). They are here so the counters are proven to see
    them when they do arrive.
    """
    fixture = copy.deepcopy(build())
    promoted, chained = native(0x5101), native(0x5102)
    # E5 (MusicBrainz-only) promoted into E4 in November, reverted in December.
    fixture["catalog_item_supersessions"].append(
        {"id": promoted, "superseded_id": E5, "survivor_id": E4, "cause": "edition_promotion", "decision_ref": native(0xD001),
         "valid_from": "2026-11-05T09:00:00+00:00", "valid_to": "2026-12-05T09:00:00+00:00", "via_id": None}
    )
    fixture["catalog_item_moves"].append(
        {"id": native(0x6001), "supersession_id": promoted, "table_name": "owned_copies", "row_id": native(0x7001),
         "from_item_id": E5, "to_item_id": E4, "user_id": native(0xE001), "moved_at": "2026-11-05T09:00:00+00:00"}
    )
    # A compressed row: X9 recorded as superseded into E8 via the promotion row.
    fixture["catalog_item_supersessions"].append(
        {"id": chained, "superseded_id": X9, "survivor_id": E8, "cause": "catalog_reattachment", "decision_ref": RUN2,
         "valid_from": "2026-11-06T09:00:00+00:00", "valid_to": None, "via_id": promoted}
    )
    return fixture


if __name__ == "__main__":
    import json

    print(json.dumps({"_comment": "Invented rows only; regenerate with `uv run python tests/synthetic.py`.", **build()}, indent=1))
