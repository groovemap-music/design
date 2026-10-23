#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The draft `admin_identity_ledger_work` payload, built from history-only rows.

This is the shape the spike proposes for catalog-api's operations-console contract (see the
spike document, "Draft admin route"). It is built here from the same in-memory rows as
`reference.py`, so the tests can show that every field comes from `catalog_items`,
`provider_aliases`, `catalog_item_supersessions`, `catalog_item_moves`, `admin_audit_log`,
and the two catalogs' release rows, and that nothing needs the matching schema.

`build(catalog, work_id, as_of)` answers one work: its editions on the edition plane, each
edition's alias rows on the evidence plane, the items superseded into it, its identity
events, and its state at `as_of` (transaction time; `None` means now). Moves are counted
per supersession; no user id, owned-copy id, or artifact id is ever emitted.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from reference import Catalog, _Index, edition_instants, edition_works, load, ts


RULES = {
    "minted": "ADR 0009: minted at ingest through common.identity",
    "linked_at_ingest": "ADR 0014 Context: musicbrainz-sql-loader attaches to a Discogs item that already resolves",
    "reattached": "ADR 0014 section 8; ADR 0009 2026-09-25 amendment, sections 1 to 3",
    "promoted": "ADR 0014 section 3, gated by section 6",
    "reverted": "ADR 0009 2026-09-25 amendment, section 1 (reversal)",
    "evidence_attached": "ADR 0011 identifier aliases; attach_aliases never overwrites",
    "alias_closed": "no writer closes an alias outside a supersession today",
}

STATES = ("not_recorded", "discogs_only", "musicbrainz_only", "unresolved", "split", "linked")


class NotFoundError(LookupError):
    """The id is not a master-kind catalog item (the route answers 404)."""


def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.isoformat().replace("+00:00", "Z")


def _valid(alias: dict[str, Any], t: datetime | None) -> bool:
    if t is None:
        return alias["valid_to"] is None
    return alias["valid_from"] <= t and (alias["valid_to"] is None or alias["valid_to"] > t)


def _visible(at: datetime | None, as_of: datetime | None) -> bool:
    return at is not None and (as_of is None or at <= as_of)


class _Ledger:
    def __init__(self, cat: Catalog) -> None:
        self.cat = cat
        self.ix = _Index(cat)
        self.instants = edition_instants(cat, self.ix)
        self.pairs = edition_works(cat, self.ix)

    def holder(self, provider: str, kind: str, external_id: str, t: datetime | None) -> str | None:
        for a in self.cat.provider_aliases:
            if (a["provider"], a["entity_kind"], a["external_id"]) == (provider, kind, external_id) and _valid(a, t):
                return a["native_id"]
        return None

    def group(self, edition: str) -> list[str]:
        former = sorted({s["superseded_id"] for s in self.cat.catalog_item_supersessions if s["survivor_id"] == edition and s["valid_to"] is None})
        return [edition, *former]

    def musicbrainz_rows(self, group: list[str]) -> list[dict[str, Any]]:
        rows = []
        for row in self.cat.musicbrainz_releases:
            item = self.ix.current_alias.get(("musicbrainz", "release", row["mbid"]))
            if item is not None and self.ix.resolve(item) == group[0]:
                rows.append(row)
        return rows

    def discogs_rows(self, group: list[str]) -> list[dict[str, Any]]:
        rows = []
        for row in self.cat.discogs_releases:
            item = self.ix.current_alias.get(("discogs", "release", row["data_id"]))
            if item is not None and self.ix.resolve(item) == group[0]:
                rows.append(row)
        return rows

    def state(self, item: str, group: list[str], t: datetime | None, kind: str) -> str:
        held = {a["provider"] for a in self.cat.provider_aliases if a["native_id"] == item and a["entity_kind"] == kind and _valid(a, t)}
        if {"discogs", "musicbrainz"} <= held:
            return "linked"
        if kind == "release":
            for row in self.musicbrainz_rows(group):
                if row.get("discogs_release_id") is None:
                    continue
                discogs_item = self.holder("discogs", "release", str(row["discogs_release_id"]), t)
                musicbrainz_item = self.holder("musicbrainz", "release", row["mbid"], t)
                if musicbrainz_item is None:
                    continue
                if discogs_item is None:
                    return "unresolved"
                if discogs_item != musicbrainz_item:
                    return "split"
        if "discogs" in held:
            return "discogs_only"
        if "musicbrainz" in held or any(
            a["provider"] == "musicbrainz" and a["native_id"] in group and _valid(a, t) for a in self.cat.provider_aliases
        ):
            return "musicbrainz_only"
        return "not_recorded"

    def events(self, group: list[str], as_of: datetime | None) -> list[dict[str, Any]]:
        ix, events = self.ix, []
        for item in group:
            own = [a for a in self.cat.provider_aliases if a["native_id"] == item]
            events.append({"at": ix.mint[item], "type": "minted", "item": item,
                           "providers": sorted({a["provider"] for a in own if a["valid_from"] == ix.mint[item]})})
            discogs_at = min((a["valid_from"] for a in own if a["provider"] == "discogs"), default=None)
            later = sorted((a for a in own if a["valid_from"] > ix.mint[item] and not ix.opened_by_supersession(a)),
                           key=lambda a: a["valid_from"])
            linked = False
            for a in later:
                if a["provider"] == "musicbrainz" and discogs_at is not None and not linked:
                    linked = True
                    events.append({"at": a["valid_from"], "type": "linked_at_ingest", "item": item})
                else:
                    events.append({"at": a["valid_from"], "type": "evidence_attached", "provider": a["provider"], "source": a["source"]})
            for a in own:
                if a["valid_to"] is not None and not ix.closed_by_supersession(a):
                    events.append({"at": a["valid_to"], "type": "alias_closed", "provider": a["provider"]})
        for s in self.cat.catalog_item_supersessions:
            if s["survivor_id"] not in group and s["superseded_id"] not in group:
                continue
            moves = Counter(m["table_name"] for m in self.cat.catalog_item_moves if m["supersession_id"] == s["id"])
            kind = "reattached" if s["cause"] == "catalog_reattachment" else "promoted"
            events.append({"at": s["valid_from"], "type": kind, "superseded": s["superseded_id"], "survivor": s["survivor_id"],
                           "decision_ref": s["decision_ref"], "compressed": s["via_id"] is not None, "moves": dict(moves)})
            if s["valid_to"] is not None:
                events.append({"at": s["valid_to"], "type": "reverted", "superseded": s["superseded_id"], "survivor": s["survivor_id"]})
        visible = [e for e in events if _visible(e["at"], as_of)]
        visible.sort(key=lambda e: (e["at"], e["type"]))
        return [{**e, "at": _iso(e["at"]), "rule": RULES[e["type"]]} for e in visible]

    def evidence(self, group: list[str], as_of: datetime | None) -> list[dict[str, Any]]:
        ix, rows = self.ix, []
        for a in sorted(self.cat.provider_aliases, key=lambda a: (a["valid_from"], a["provider"], a["external_id"])):
            if a["native_id"] not in group or not _visible(a["valid_from"], as_of):
                continue
            closed = _visible(a["valid_to"], as_of)
            rows.append({
                "provider": a["provider"],
                "external_id": a["external_id"],
                "source": a["source"],
                "held_by": a["native_id"],
                "valid_from": _iso(a["valid_from"]),
                "valid_to": _iso(a["valid_to"]) if closed else None,
                "opened_by": "supersession" if ix.opened_by_supersession(a) else "mint" if a["valid_from"] == ix.mint[a["native_id"]] else "later",
                "closed_by": None if not closed else "supersession" if ix.closed_by_supersession(a) else "other",
            })
        return rows


def build(cat: Catalog, work_id: str, as_of: datetime | None = None, edition_limit: int = 200) -> dict[str, Any]:
    ledger = _Ledger(cat)
    ix = ledger.ix
    work = ix.resolve(work_id)
    if ix.kind.get(work) != "master":
        raise NotFoundError(work_id)
    works_of: dict[str, set[str]] = {}
    for edition, parent in ledger.pairs:
        works_of.setdefault(edition, set()).add(parent)
    editions = sorted((e for e, parents in works_of.items() if work in parents and e in ledger.instants),
                      key=lambda e: (min(ledger.instants[e]), e))
    if as_of is not None:
        editions = [e for e in editions if min(ledger.instants[e]) <= as_of]
    shown = editions[:edition_limit]

    payload_editions = []
    for edition in shown:
        group = ledger.group(edition)
        former = []
        for s in cat.catalog_item_supersessions:
            if s["survivor_id"] == edition and s["superseded_id"] in group and _visible(s["valid_from"], as_of):
                former.append({"gm_id": s["superseded_id"], "superseded_at": _iso(s["valid_from"]), "cause": s["cause"],
                               "decision_ref": s["decision_ref"]})
        payload_editions.append({
            "gm_id": edition,
            "state": ledger.state(edition, group, as_of, "release"),
            "works": sorted(works_of[edition]),
            "work_disagreement": len(works_of[edition]) > 1,
            "provider_rows": [{"provider": "discogs", "external_id": row["data_id"]} for row in ledger.discogs_rows(group)]
            + [{"provider": "musicbrainz", "external_id": row["mbid"],
                "names_discogs_release": None if row.get("discogs_release_id") is None else str(row["discogs_release_id"])}
               for row in ledger.musicbrainz_rows(group)],
            "former_items": former,
            "evidence": ledger.evidence(group, as_of),
            "events": ledger.events(group, as_of),
        })

    work_aliases = [a for a in cat.provider_aliases if a["native_id"] == work and _visible(a["valid_from"], as_of)]
    payload: dict[str, Any] = {
        "work": {
            "gm_id": work,
            "state": ledger.state(work, [work], as_of, "master"),
            "providers": [{"provider": a["provider"], "external_id": a["external_id"], "valid_from": _iso(a["valid_from"]),
                           "valid_to": _iso(a["valid_to"]) if _visible(a["valid_to"], as_of) else None}
                          for a in sorted(work_aliases, key=lambda a: (a["valid_from"], a["provider"]))],
        },
        "as_of": _iso(as_of),
        "editions": payload_editions,
        "edition_count": len(editions),
        "truncated": len(editions) > len(shown),
    }
    if work != work_id:
        payload["work"]["requested_id"] = work_id
    return payload


def main() -> None:
    """Write the example payload for one synthetic work: `payload.py <fixture.json> <work id> [as_of]`."""
    fixture = json.loads(Path(sys.argv[1]).read_text())
    as_of = ts(sys.argv[3]) if len(sys.argv) > 3 else None
    print(json.dumps(build(load(fixture), sys.argv[2], as_of), indent=2))


if __name__ == "__main__":
    main()
