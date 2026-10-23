#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The draft strata payload and its aggregation rule, and its size per band.

    payload_model.py <db.duckdb> <out.json> [--sample 300] [--budgets 0,500,3/12/16,6/12/16]

A budget is either one number N (N per plane, the credit plane capped at 48) or
`credits/masters/releases`, the per-plane form S1 (gm-design-on0x) measured. 0 means
no aggregation.

`build_payload` is the rule a catalog-api strata route would apply after its Neo4j
read. It is pure, so the tests pin its invariants on synthetic input:

- every node and aggregate names a parent on the plane above (the hull nesting S1's
  cylinder property needs), and the credit plane has no parent;
- each plane holds at most its budget of entries, nodes plus aggregates;
- counts are conserved: the releases shown plus the releases inside aggregates equal
  the artist's release total, and the same holds for masters.

The driver measures payload bytes for a seeded sample of artists in each size band,
plus the ten largest artists, using the real title and name byte lengths from the
dumps. Strings are padded placeholders of those lengths, so no catalog text is read
into the payload and nothing but byte counts leaves the work directory.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import orjson

# A single-number budget N means N per plane, with the credit plane capped here.
CREDIT_PLANE_CAP = 48

Budget = int | tuple[int, int, int] | None


def plane_budgets(budget: Budget) -> tuple[int, int, int] | None:
    """(credits, masters, releases), or None for no aggregation."""
    if not budget:
        return None
    if isinstance(budget, int):
        return (min(budget, CREDIT_PLANE_CAP), budget, budget)
    credits, masters, releases = budget
    if not 1 <= credits <= masters or credits > releases:
        raise ValueError("a budget needs 1 <= credits <= masters and credits <= releases")
    return (credits, masters, releases)


def parse_budget(text: str) -> Budget:
    if "/" in text:
        c, m, r = (int(part) for part in text.split("/"))
        return (c, m, r)
    return int(text)
NO_YEAR = "unknown"


@dataclass(frozen=True, slots=True)
class Release:
    id: int
    master_id: int | None
    is_main: bool
    year: int | None
    title_bytes: int
    credit: tuple[int, ...]  # sorted BY artist ids: one Discogs artist credit
    state: str = "none"  # none | wanted | owned (collector state, signed-in only)


@dataclass(frozen=True, slots=True)
class Master:
    id: int
    year: int | None
    title_bytes: int


def _text(n: int) -> str:
    return "x" * n


def _decade(year: int | None) -> str:
    return NO_YEAR if year is None else f"{year // 10 * 10}s"


def _span(years: list[int | None]) -> tuple[int | None, int | None]:
    known = [y for y in years if y is not None]
    return (min(known), max(known)) if known else (None, None)


def _credit_id(credit: tuple[int, ...]) -> str:
    return "c:" + "+".join(str(a) for a in credit)


def build_payload(
    root_id: int,
    releases: list[Release],
    masters: dict[int, Master],
    name_bytes: dict[int, int],
    budget: Budget,
    *,
    signed_in: bool = False,
) -> dict[str, Any]:
    """Three planes for one artist root, each aggregated to its budget of entries.

    `budget=None` (or 0) means no aggregation: every credit, master, and release is a
    node. The rule, plane by plane:

    credits:  one node per distinct artist credit (the sorted BY set of a release), the
              root's own credit first, then by release count. Past the budget, the tail
              folds into one `other credits` aggregate.
    masters:  one node per master, parented to the credit of its main release (else
              its first release). Masterless releases get one `no master` aggregate per
              credit, because they still need a band. Past the budget, the masters
              with the fewest releases fold into per-credit, per-decade aggregates,
              keeping any master that holds collector state; then per-credit
              aggregates; and last, one aggregate per credit holding everything.
    releases: one node per release under a shown master or `no master` band. Past the
              budget, each master keeps its main release and any release with collector
              state, and the rest become one count aggregate per master; masterless
              releases fold into per-credit, per-decade aggregates. If that still does
              not fit, every master collapses to one count aggregate, and masterless
              releases to one aggregate per band when their decades do not fit.
    """
    budgets = plane_budgets(budget)
    limit = None if budgets is None else budgets[1]
    credit_limit = None if budgets is None else budgets[0]
    release_limit = None if budgets is None else budgets[2]

    # Credit plane.
    by_credit = Counter(r.credit for r in releases)
    root_credit = (root_id,)
    order = sorted(by_credit, key=lambda c: (c != root_credit, -by_credit[c], c))
    if root_credit not in by_credit:
        order.insert(0, root_credit)
    shown_credits = order if credit_limit is None or len(order) <= credit_limit else order[: credit_limit - 1]
    folded_credits = [c for c in order if c not in set(shown_credits)]
    other_id = "c:other"
    credit_parent = {c: _credit_id(c) for c in shown_credits} | {c: other_id for c in folded_credits}
    credit_nodes = [
        {"id": _credit_id(c), "artists": [{"id": a, "name": _text(name_bytes.get(a, 0))} for a in c], "releases": by_credit.get(c, 0)}
        for c in shown_credits
    ]
    credit_aggs = [{"id": other_id, "credits": len(folded_credits), "releases": sum(by_credit[c] for c in folded_credits)}] if folded_credits else []

    # Master plane.
    rel_by_master: dict[int, list[Release]] = defaultdict(list)
    masterless: list[Release] = []
    for r in releases:
        (rel_by_master[r.master_id] if r.master_id is not None else masterless).append(r)
    master_parent = {}
    for mid, rs in rel_by_master.items():
        anchor = next((r for r in rs if r.is_main), min(rs, key=lambda r: r.id))
        master_parent[mid] = credit_parent[anchor.credit]
    masterless_parents = sorted({credit_parent[r.credit] for r in masterless})
    stateful = {mid for mid, rs in rel_by_master.items() if any(r.state != "none" for r in rs)}
    master_order = sorted(rel_by_master, key=lambda m: (m not in stateful, -len(rel_by_master[m]), m))

    def by_decade(m: int) -> tuple[str, str]:
        return (master_parent[m], _decade(masters[m].year if m in masters else None))

    def by_band(m: int) -> tuple[str, str]:
        return (master_parent[m], "all")

    def plan(bucket_of) -> tuple[int, set[tuple[str, str]]]:
        """Show the first `keep` masters; fold the rest into buckets; fit the budget.

        The master plane holds the shown masters, the buckets, and one `no master` band
        per credit. The release plane must still fit when every shown master and every
        `no master` band is one count aggregate, so `keep` is bounded by both planes.
        """
        keep, rest = len(master_order), set()
        if limit is not None:
            room = limit - len(masterless_parents)
            release_room = release_limit - len(masterless_parents)
            while keep > 0 and (keep + len(rest) > room or keep > release_room):
                keep -= 1
                rest.add(bucket_of(master_order[keep]))
        return keep, rest

    # Fold by decade; if even that overflows, one bucket per credit band; if that
    # overflows too, each credit band becomes a single aggregate holding its masters
    # and its masterless releases. A band is at most one credit entry, so the last
    # level always fits.
    bucket_of = by_decade
    keep, rest = plan(bucket_of)
    if limit is not None and keep + len(rest) + len(masterless_parents) > limit:
        bucket_of = by_band
        keep, rest = plan(bucket_of)
    whole_bands = limit is not None and keep + len(rest) + len(masterless_parents) > limit
    if whole_bands:
        keep = 0
    shown_masters, folded_masters = master_order[:keep], master_order[keep:]
    master_nodes = []
    for mid in shown_masters:
        rs = rel_by_master[mid]
        y0, y1 = _span([r.year for r in rs])
        m = masters.get(mid, Master(mid, None, 0))
        node = {"id": f"m:{mid}", "parent": master_parent[mid], "title": _text(m.title_bytes), "year": m.year, "releases": len(rs), "y0": y0, "y1": y1}
        if signed_in:
            node["state"] = _rollup([r.state for r in rs])
        master_nodes.append(node)

    def master_agg(agg_id: str, parent: str, kind: str, mids: list[int], rs: list[Release], decade: str | None = None) -> dict[str, Any]:
        y0, y1 = _span([r.year for r in rs])
        agg = {"id": agg_id, "parent": parent, "kind": kind, "masters": len(mids), "releases": len(rs), "y0": y0, "y1": y1}
        if decade is not None:
            agg["decade"] = decade
        if signed_in:
            agg["states"] = dict(Counter(r.state for r in rs))
        return agg

    master_aggs = []
    buckets: dict[tuple[str, str], list[int]] = defaultdict(list)
    for mid in folded_masters:
        buckets[bucket_of(mid) if not whole_bands else by_band(mid)].append(mid)
    folded_releases = sum(len(rel_by_master[m]) for m in folded_masters)
    if whole_bands:
        bands = sorted({p for p, _ in buckets} | set(masterless_parents))
        for parent in bands:
            mids = buckets.get((parent, "all"), [])
            rs = [r for m in mids for r in rel_by_master[m]] + [r for r in masterless if credit_parent[r.credit] == parent]
            master_aggs.append(master_agg(f"ma:{parent}:all", parent, "band", mids, rs))
        folded_releases += len(masterless)
        masterless = []
    else:
        for parent in masterless_parents:
            rs = [r for r in masterless if credit_parent[r.credit] == parent]
            master_aggs.append(master_agg(f"nm:{parent}", parent, "no_master", [], rs))
        for (parent, decade), mids in sorted(buckets.items()):
            rs = [r for m in mids for r in rel_by_master[m]]
            master_aggs.append(master_agg(f"ma:{parent}:{decade}", parent, "masters", mids, rs, decade))

    # Release plane: only releases under a shown master or a `no master` band compete.
    candidates = [r for mid in shown_masters for r in rel_by_master[mid]] + masterless
    release_nodes: list[dict[str, Any]] = []
    release_aggs: list[dict[str, Any]] = []

    def release_node(r: Release) -> dict[str, Any]:
        parent = f"m:{r.master_id}" if r.master_id is not None else f"nm:{credit_parent[r.credit]}"
        node = {"id": f"r:{r.id}", "parent": parent, "title": _text(r.title_bytes), "year": r.year}
        if signed_in:
            node["state"] = r.state
            node["recorded_at"] = "2026-10-22T00:00:00Z" if r.state != "none" else None
        return node

    def count_agg(agg_id: str, parent: str, rs: list[Release]) -> dict[str, Any]:
        y0, y1 = _span([r.year for r in rs])
        agg = {"id": agg_id, "parent": parent, "releases": len(rs), "y0": y0, "y1": y1}
        if signed_in:
            agg["states"] = dict(Counter(r.state for r in rs))
        return agg

    def masterless_aggs(by_decade: bool = True) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str], list[Release]] = defaultdict(list)
        for r in masterless:
            groups[(f"nm:{credit_parent[r.credit]}", _decade(r.year) if by_decade else "all")].append(r)
        return [count_agg(f"ra:{p}:{d}", p, rs) for (p, d), rs in sorted(groups.items())]

    if release_limit is None or len(candidates) <= release_limit:
        release_nodes = [release_node(r) for r in candidates]
    else:
        # Step 1: per master, the main release and stateful releases stay.
        step_nodes, step_aggs = [], []
        for mid in shown_masters:
            rs = rel_by_master[mid]
            main = next((r for r in rs if r.is_main), None)
            keep_rs = [r for r in rs if r is main or r.state != "none"]
            kept = {id(r) for r in keep_rs}
            rest = [r for r in rs if id(r) not in kept]
            step_nodes += [release_node(r) for r in keep_rs]
            if rest:
                step_aggs.append(count_agg(f"ra:m:{mid}", f"m:{mid}", rest))
        step_aggs += masterless_aggs()
        if len(step_nodes) + len(step_aggs) <= release_limit:
            release_nodes, release_aggs = step_nodes, step_aggs
        else:
            # Step 2: every master is one count aggregate, and masterless releases fold
            # by decade, or into one aggregate per band if decades do not fit.
            release_aggs = [count_agg(f"ra:m:{mid}", f"m:{mid}", rel_by_master[mid]) for mid in shown_masters]
            tail = masterless_aggs()
            release_aggs += tail if len(release_aggs) + len(tail) <= release_limit else masterless_aggs(by_decade=False)

    # Releases under folded masters (and, at the last level, masterless releases) are
    # counted by their master-plane aggregate only.
    return {
        "root": {"type": "artist", "id": root_id, "name": _text(name_bytes.get(root_id, 0))},
        "budget": None if budgets is None else dict(zip(("credits", "masters", "releases"), budgets, strict=True)),
        "totals": {
            "credits": len(order),
            "masters": len(rel_by_master),
            "releases": len(releases),
            "masterless_releases": len(masterless),
            "releases_only_in_master_aggregates": folded_releases,
        },
        "planes": [
            {"level": 0, "kind": "credit", "nodes": credit_nodes, "aggregates": credit_aggs},
            {"level": 1, "kind": "master", "nodes": master_nodes, "aggregates": master_aggs},
            {"level": 2, "kind": "release", "nodes": release_nodes, "aggregates": release_aggs},
        ],
    }


def _rollup(states: list[str]) -> str:
    """The mockup's master rule: owned if any pressing is owned, else wanted, else none."""
    return "owned" if "owned" in states else "wanted" if "wanted" in states else "none"


def payload_bytes(payload: dict[str, Any]) -> int:
    return len(orjson.dumps(payload))


# ---------------------------------------------------------------------------
# Driver over the dump tables.
# ---------------------------------------------------------------------------


def _sample_key(artist_id: int) -> bytes:
    return hashlib.sha256(f"gm-design-1h2l:{artist_id}".encode()).digest()


def sample_artists(con, per_band: int) -> dict[str, list[int]]:
    from ladder_stats import BANDS, band_case

    con.execute("CREATE OR REPLACE TEMP TABLE ra_d AS SELECT DISTINCT release_id, artist_id FROM ra")
    rows = con.execute(f"SELECT artist_id, {band_case('n')} FROM (SELECT artist_id, count(*) AS n FROM ra_d GROUP BY 1)").fetchall()
    by_band: dict[str, list[int]] = defaultdict(list)
    for artist_id, band in rows:
        by_band[band].append(artist_id)
    sample = {label: sorted(by_band[label], key=_sample_key)[:per_band] for label, _, _ in BANDS}
    sample["largest10"] = [a for (a,) in con.execute("SELECT artist_id FROM ra_d GROUP BY 1 ORDER BY count(*) DESC, artist_id LIMIT 10").fetchall()]
    return sample


def load_artist(con, artist_id: int) -> tuple[list[Release], dict[int, Master], dict[int, int]]:
    rows = con.execute(
        """
        WITH mine AS (SELECT release_id FROM ra_d WHERE artist_id = ?)
        SELECT r.release_id, r.master_id, r.is_main, r.year, r.title_bytes,
               list(DISTINCT a.artist_id ORDER BY a.artist_id) AS credit
        FROM mine JOIN rel r USING (release_id) JOIN ra_d a USING (release_id)
        GROUP BY ALL
        """,
        [artist_id],
    ).fetchall()
    releases = [Release(rid, mid, bool(main), year, tb or 0, tuple(credit)) for rid, mid, main, year, tb, credit in rows]
    mids = sorted({r.master_id for r in releases if r.master_id is not None})
    masters: dict[int, Master] = {}
    if mids:
        con.execute("CREATE OR REPLACE TEMP TABLE want_m AS SELECT unnest(?::BIGINT[]) AS master_id", [mids])
        for mid, year, tb in con.execute("SELECT master_id, year, title_bytes FROM ms JOIN want_m USING (master_id)").fetchall():
            masters[mid] = Master(mid, year, tb or 0)
    artists = sorted({a for r in releases for a in r.credit})
    con.execute("CREATE OR REPLACE TEMP TABLE want_a AS SELECT unnest(?::BIGINT[]) AS artist_id", [artists])
    names = dict(con.execute("SELECT artist_id, max(name_bytes) FROM ra JOIN want_a USING (artist_id) GROUP BY 1").fetchall())
    return releases, masters, names


def _pct(values: list[int], q: float) -> int:
    """Nearest-rank percentile."""
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q * len(ordered))) - 1]


def main() -> None:
    from load_db import connect

    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("out")
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--budgets", default="0,500,3/12/16,6/12/16")
    ap.add_argument("--sample-out", help="write the band and artist id sample for latency.py (work directory only)")
    args = ap.parse_args()
    budgets = args.budgets.split(",")
    con = connect(args.db)
    sample = sample_artists(con, args.sample)
    if args.sample_out:
        with open(args.sample_out, "w") as handle:
            handle.writelines(f"{band}\t{artist_id}\n" for band, artists in sample.items() for artist_id in artists)
    result: dict[str, Any] = {"sample_per_band": args.sample, "budgets": budgets, "bands": {}}
    for band, artists in sample.items():
        sizes: dict[str, dict[str, list[int]]] = {str(b): {"anonymous": [], "signed_in": [], "entries": []} for b in budgets}
        for artist_id in artists:
            releases, masters, names = load_artist(con, artist_id)
            for b in budgets:
                anon = build_payload(artist_id, releases, masters, names, parse_budget(b))
                signed = build_payload(artist_id, releases, masters, names, parse_budget(b), signed_in=True)
                sizes[str(b)]["anonymous"].append(payload_bytes(anon))
                sizes[str(b)]["signed_in"].append(payload_bytes(signed))
                sizes[str(b)]["entries"].append(sum(len(p["nodes"]) + len(p["aggregates"]) for p in anon["planes"]))
        result["bands"][band] = {
            "artists": len(artists),
            "by_budget": {
                b: {k: {"p50": _pct(v, 0.5), "p95": _pct(v, 0.95), "max": max(v)} for k, v in s.items()} if artists else None
                for b, s in sizes.items()
            },
        }
        print(band, len(artists), file=sys.stderr, flush=True)
    with open(args.out, "wb") as handle:
        handle.write(orjson.dumps(result, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS) + b"\n")


if __name__ == "__main__":
    main()
