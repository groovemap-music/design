#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The identity-history measurement of `sql/identity_history.sql`, in plain Python.

The SQL is what runs against a catalog. This module is the same computation over rows held
in memory, so the definitions can be read and tested without a database, and
`tests/test_sql_parity.py` holds the two equal on the synthetic fixture.

Rows use database-schema's column names. Timestamps are timezone-aware datetimes, and every
month and day is taken in UTC. The output carries counts, months, and days only: no native
id, external id, user id, admin id, or audit target.

**Instants.** An edition is a release-kind native item as resolved today (one hop through
an open `catalog_item_supersessions` row). Its instants are the distinct transaction times
at which anything was recorded about it or about an item superseded into it: every alias's
`valid_from` and `valid_to`, every supersession's `valid_from` and `valid_to`, and every
move's `moved_at`. Its first instant is when it was minted. Each further instant is one
**identity event**, so an edition "has events" when it has two or more instants.

**Alias classes.** A re-attachment closes aliases on the superseded item and re-inserts
them on the survivor, and stamps the supersession, in one transaction, so all three share
one `now()`. An alias opened on an item at the instant a supersession into that item opened
(or, for a revert, at the instant a supersession out of it closed) was moved by that
supersession. The same rule, mirrored, classifies closes. Anything else opened after the
item's first instant was attached later by a loader or another writer.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from typing import Any


PERCENTILES = (0.5, 0.9, 0.99)

# The two actions an applying re-attachment run ends as (catalog-api `api/reattach.py` and
# `api/reattach_trigger.py`). Started and failed rows are not finished runs.
APPLY_ACTIONS = ("identity.reattach.apply", "identity.reattach.auto")

# Per-kind fields of a run's `details.outcomes` (catalog-api `KindTally.as_dict`).
OUTCOME_FIELDS = ("reattached", "guarded", "failed", "supersessions_opened", "merged_with_dependents")


def ts(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without a time zone: {value}")
    return parsed.astimezone(UTC)


def month(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m")


def day(t: datetime | None) -> str | None:
    return None if t is None else t.astimezone(UTC).strftime("%Y-%m-%d")


def percentile_disc(values: list[int], p: float) -> int | None:
    """PostgreSQL's `percentile_disc`: the first value whose cumulative share reaches p."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(math.ceil(Fraction(str(p)) * len(ordered)) - 1, 0)
    return ordered[index]


def distribution(values: list[int]) -> dict[str, int | None]:
    result: dict[str, int | None] = {f"p{round(p * 100)}": percentile_disc(values, p) for p in PERCENTILES}
    result["max"] = max(values) if values else None
    return result


def per_month(times: list[datetime]) -> dict[str, int]:
    return dict(Counter(month(t) for t in times))


def nonzero(counter: Counter[str]) -> dict[str, int]:
    return {key: count for key, count in counter.items() if count}


@dataclass(frozen=True)
class Catalog:
    """The rows the measurement reads, with timestamps parsed."""

    catalog_items: list[dict[str, Any]]
    provider_aliases: list[dict[str, Any]]
    catalog_item_supersessions: list[dict[str, Any]]
    catalog_item_moves: list[dict[str, Any]]
    admin_audit_log: list[dict[str, Any]]
    discogs_releases: list[dict[str, Any]]
    musicbrainz_releases: list[dict[str, Any]]


_TIMESTAMPS = {
    "catalog_items": ("created_at",),
    "provider_aliases": ("valid_from", "valid_to"),
    "catalog_item_supersessions": ("valid_from", "valid_to"),
    "catalog_item_moves": ("moved_at",),
    "admin_audit_log": ("created_at",),
    "discogs_releases": (),
    "musicbrainz_releases": (),
}


def load(fixture: dict[str, list[dict[str, Any]]]) -> Catalog:
    tables = {}
    for table, columns in _TIMESTAMPS.items():
        tables[table] = [{**row, **{column: ts(row.get(column)) for column in columns}} for row in fixture.get(table, [])]
    return Catalog(**tables)


class _Index:
    """Lookups shared by every section."""

    def __init__(self, cat: Catalog) -> None:
        self.kind = {item["id"]: item["kind"] for item in cat.catalog_items}
        self.survivor = {s["superseded_id"]: s["survivor_id"] for s in cat.catalog_item_supersessions if s["valid_to"] is None}
        self.current_alias = {
            (a["provider"], a["entity_kind"], a["external_id"]): a["native_id"] for a in cat.provider_aliases if a["valid_to"] is None
        }
        self.opened_instants: set[tuple[str, datetime]] = set()
        self.closed_instants: set[tuple[str, datetime]] = set()
        for s in cat.catalog_item_supersessions:
            self.opened_instants.add((s["survivor_id"], s["valid_from"]))
            self.closed_instants.add((s["superseded_id"], s["valid_from"]))
            if s["valid_to"] is not None:
                self.opened_instants.add((s["superseded_id"], s["valid_to"]))
                self.closed_instants.add((s["survivor_id"], s["valid_to"]))
        self.mint: dict[str, datetime] = {}
        for a in cat.provider_aliases:
            first = self.mint.get(a["native_id"])
            if first is None or a["valid_from"] < first:
                self.mint[a["native_id"]] = a["valid_from"]

    def resolve(self, item_id: str) -> str:
        return self.survivor.get(item_id, item_id)

    def opened_by_supersession(self, alias: dict[str, Any]) -> bool:
        return (alias["native_id"], alias["valid_from"]) in self.opened_instants

    def closed_by_supersession(self, alias: dict[str, Any]) -> bool:
        return alias["valid_to"] is not None and (alias["native_id"], alias["valid_to"]) in self.closed_instants


def _aliases(cat: Catalog) -> dict[str, Any]:
    rows = cat.provider_aliases
    opened = [a["valid_from"] for a in rows]
    closed = [a["valid_to"] for a in rows if a["valid_to"] is not None]
    return {
        "rows": len(rows),
        "current": sum(a["valid_to"] is None for a in rows),
        "closed": len(closed),
        "first_opened": day(min(opened, default=None)),
        "last_opened": day(max(opened, default=None)),
        "first_closed": day(min(closed, default=None)),
        "last_closed": day(max(closed, default=None)),
        "opened_days": len({day(t) for t in opened}),
        "by_provider_kind": dict(Counter(f"{a['provider']}/{a['entity_kind']}" for a in rows)),
        "by_source": dict(Counter(a["source"] for a in rows)),
        "opened_per_month": per_month(opened),
        "closed_per_month": per_month(closed),
    }


def _supersessions(cat: Catalog, ix: _Index) -> dict[str, Any]:
    rows = cat.catalog_item_supersessions
    opened = [s["valid_from"] for s in rows]
    closed = [s["valid_to"] for s in rows if s["valid_to"] is not None]
    return {
        "rows": len(rows),
        "open": sum(s["valid_to"] is None for s in rows),
        "closed": len(closed),
        "with_via": sum(s["via_id"] is not None for s in rows),
        "decision_refs": len({s["decision_ref"] for s in rows}),
        "by_cause": dict(Counter(s["cause"] for s in rows)),
        "by_kind": dict(Counter(ix.kind[s["superseded_id"]] for s in rows)),
        "first_opened": day(min(opened, default=None)),
        "last_opened": day(max(opened, default=None)),
        "opened_per_month": per_month(opened),
        "closed_per_month": per_month(closed),
    }


def _moves(cat: Catalog) -> dict[str, Any]:
    rows = cat.catalog_item_moves
    moved = [m["moved_at"] for m in rows]
    return {
        "rows": len(rows),
        "by_table": dict(Counter(m["table_name"] for m in rows)),
        "supersessions_with_moves": len({m["supersession_id"] for m in rows}),
        "first_moved": day(min(moved, default=None)),
        "last_moved": day(max(moved, default=None)),
        "moved_per_month": per_month(moved),
    }


def _audit(cat: Catalog) -> dict[str, Any]:
    rows = [r for r in cat.admin_audit_log if r["action"].startswith("identity.")]
    applied = [r for r in rows if r["action"] in APPLY_ACTIONS]
    outcomes: dict[str, dict[str, int]] = {}
    for run in applied:
        for kind, tally in ((run.get("details") or {}).get("outcomes") or {}).items():
            sums = outcomes.setdefault(kind, dict.fromkeys(OUTCOME_FIELDS, 0))
            for field in OUTCOME_FIELDS:
                sums[field] += int(tally.get(field) or 0)
    created = [r["created_at"] for r in rows]
    return {
        "rows": len(rows),
        "by_action": dict(Counter(r["action"] for r in rows)),
        "per_month": per_month(created),
        "first": day(min(created, default=None)),
        "last": day(max(created, default=None)),
        "apply_runs": len(applied),
        "apply_run_months": len({month(r["created_at"]) for r in applied}),
        "outcomes": outcomes,
    }


def _items(cat: Catalog) -> dict[str, Any]:
    created = [i["created_at"] for i in cat.catalog_items]
    return {
        "rows": len(cat.catalog_items),
        "by_kind": dict(Counter(i["kind"] for i in cat.catalog_items)),
        "created_per_month": per_month(created),
        "first_created": day(min(created, default=None)),
        "last_created": day(max(created, default=None)),
    }


def _transitions(cat: Catalog, ix: _Index) -> dict[str, Any]:
    opened_by: Counter[str] = Counter()
    closed_by: Counter[str] = Counter()
    closed_other: Counter[str] = Counter()
    opened_later: Counter[str] = Counter()
    discogs_first: dict[str, datetime] = {}
    musicbrainz_first: dict[str, datetime] = {}
    for a in cat.provider_aliases:
        moved_in = ix.opened_by_supersession(a)
        if moved_in:
            opened_by[a["provider"]] += 1
        elif a["valid_from"] > ix.mint[a["native_id"]]:
            opened_later[a["provider"]] += 1
        if a["valid_to"] is not None:
            (closed_by if ix.closed_by_supersession(a) else closed_other)[a["provider"]] += 1
        item = a["native_id"]
        if a["provider"] == "discogs" and (item not in discogs_first or a["valid_from"] < discogs_first[item]):
            discogs_first[item] = a["valid_from"]
        if a["provider"] == "musicbrainz" and not moved_in and (item not in musicbrainz_first or a["valid_from"] < musicbrainz_first[item]):
            musicbrainz_first[item] = a["valid_from"]
    linked: Counter[str] = Counter()
    reversed_order: Counter[str] = Counter()
    for item, discogs_at in discogs_first.items():
        musicbrainz_at = musicbrainz_first.get(item)
        if musicbrainz_at is None:
            continue
        if musicbrainz_at > discogs_at:
            linked[ix.kind[item]] += 1
        elif discogs_at > musicbrainz_at:
            reversed_order[ix.kind[item]] += 1
    rows = cat.catalog_item_supersessions
    return {
        "linked_at_ingest": nonzero(linked),
        "discogs_attached_after_musicbrainz": nonzero(reversed_order),
        "superseded": dict(Counter(f"{s['cause']}/{ix.kind[s['superseded_id']]}" for s in rows)),
        "supersessions_closed": sum(s["valid_to"] is not None for s in rows),
        "chain_compressed": sum(s["via_id"] is not None for s in rows),
        "aliases_opened_by_supersession": nonzero(opened_by),
        "aliases_closed_by_supersession": nonzero(closed_by),
        "aliases_closed_otherwise": nonzero(closed_other),
        "aliases_opened_after_mint_otherwise": nonzero(opened_later),
        "non_catalog_aliases": nonzero(Counter(a["source"] for a in cat.provider_aliases if a["source"] != "catalog")),
    }


def edition_instants(cat: Catalog, ix: _Index) -> dict[str, set[datetime]]:
    """Every edition's instants (see the module docstring)."""
    instants: dict[str, set[datetime]] = defaultdict(set)
    for a in cat.provider_aliases:
        if ix.kind.get(a["native_id"]) != "release":
            continue
        edition = ix.resolve(a["native_id"])
        instants[edition].add(a["valid_from"])
        if a["valid_to"] is not None:
            instants[edition].add(a["valid_to"])
    for s in cat.catalog_item_supersessions:
        if ix.kind[s["superseded_id"]] != "release":
            continue
        for item in (s["superseded_id"], s["survivor_id"]):
            instants[ix.resolve(item)].add(s["valid_from"])
            if s["valid_to"] is not None:
                instants[ix.resolve(item)].add(s["valid_to"])
    for m in cat.catalog_item_moves:
        for item in (m["from_item_id"], m["to_item_id"]):
            if ix.kind[item] == "release":
                instants[ix.resolve(item)].add(m["moved_at"])
    return instants


def edition_works(cat: Catalog, ix: _Index) -> set[tuple[str, str]]:
    """(edition, work) pairs: each catalog's own release row names its master or release group."""
    pairs: set[tuple[str, str]] = set()
    for row in cat.discogs_releases:
        edition = ix.current_alias.get(("discogs", "release", row["data_id"]))
        master = row.get("master_id")
        work = None if master is None else ix.current_alias.get(("discogs", "master", master.strip()))
        if edition is not None and work is not None:
            pairs.add((ix.resolve(edition), ix.resolve(work)))
    for row in cat.musicbrainz_releases:
        edition = ix.current_alias.get(("musicbrainz", "release", row["mbid"]))
        group = row.get("release_group_mbid")
        work = None if group is None else ix.current_alias.get(("musicbrainz", "master", group))
        if edition is not None and work is not None:
            pairs.add((ix.resolve(edition), ix.resolve(work)))
    return pairs


def _ledger(cat: Catalog, ix: _Index) -> dict[str, Any]:
    instants = edition_instants(cat, ix)
    # The months an edition's events fall in: every instant after its first (the mint).
    months = {edition: {month(t) for t in times if t != min(times)} for edition, times in instants.items()}
    repaired = set()
    for s in cat.catalog_item_supersessions:
        if ix.kind[s["superseded_id"]] == "release":
            repaired.update(ix.resolve(item) for item in (s["superseded_id"], s["survivor_id"]))
    evented = {edition for edition, times in instants.items() if len(times) >= 2}

    pairs = {(edition, work) for edition, work in edition_works(cat, ix) if edition in instants}
    works_of: Counter[str] = Counter(edition for edition, _ in pairs)
    by_work_count = Counter("0" if works_of[e] == 0 else "1" if works_of[e] == 1 else "2+" for e in instants)
    editions_of: dict[str, set[str]] = defaultdict(set)
    for edition, work in pairs:
        editions_of[work].add(edition)
    per_work_evented = {work: len(editions & evented) for work, editions in editions_of.items()}
    multi_month = 0
    for work, editions in editions_of.items():
        if per_work_evented[work] >= 2 and len(set().union(*(months[e] for e in editions & evented))) >= 2:
            multi_month += 1

    split = unresolved = 0
    for row in cat.musicbrainz_releases:
        if row.get("discogs_release_id") is None:
            continue
        musicbrainz_item = ix.current_alias.get(("musicbrainz", "release", row["mbid"]))
        discogs_item = ix.current_alias.get(("discogs", "release", str(row["discogs_release_id"])))
        if discogs_item is None:
            unresolved += 1
        elif musicbrainz_item is not None and musicbrainz_item != discogs_item:
            split += 1

    return {
        "editions": len(instants),
        "editions_with_events": len(evented),
        "editions_repaired": len(repaired & set(instants)),
        "editions_events_multi_month": sum(len(m) >= 2 for m in months.values()),
        "editions_by_work_count": {key: by_work_count.get(key, 0) for key in ("0", "1", "2+")},
        "works": len(editions_of),
        "works_with_2plus_evented_editions": sum(n >= 2 for n in per_work_evented.values()),
        "works_with_2plus_evented_editions_multi_month": multi_month,
        "works_with_2plus_repaired_editions": sum(len(editions & repaired) >= 2 for editions in editions_of.values()),
        "evented_editions_per_work": distribution([n for n in per_work_evented.values() if n >= 1]),
        "split_now": split,
        "unresolved_now": unresolved,
    }


def identity_history(cat: Catalog) -> dict[str, Any]:
    ix = _Index(cat)
    return {
        "provider_aliases": _aliases(cat),
        "catalog_item_supersessions": _supersessions(cat, ix),
        "catalog_item_moves": _moves(cat),
        "admin_audit_log_identity": _audit(cat),
        "catalog_items": _items(cat),
        "transitions": _transitions(cat, ix),
        "ledger": _ledger(cat, ix),
    }
