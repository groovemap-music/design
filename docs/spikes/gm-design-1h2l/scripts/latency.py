#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""p50 and p95 of the candidate strata queries next to today's explore and expand.

    NEO4J_URI=bolt://... NEO4J_USER=... NEO4J_PASSWORD=... \
        latency.py <sample.tsv> <out.json> [--repeats 5] [--expected-releases N]

Runs against a full-catalog Neo4j in READ access mode and writes nothing to it. The
sample file (band, Discogs artist id per line) comes from `payload_model.py
--sample-out` and stays in the work directory. Each query runs once to warm up and
then `--repeats` times per artist; p50 and p95 are nearest-rank over every timed run in
the band, client-side wall clock from `run` to the last record consumed. The server's
own `result_available_after + result_consumed_after` is recorded beside it.

`--expected-releases` is the Discogs dump's release count. The output records the
instance's Release count next to it, so a reader can see whether the instance was a
full catalog; a run against a partial graph is labelled, never silently reported.

The credentials come from the environment only and are never written or logged.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from collections import defaultdict
from typing import Any

import orjson
from neo4j import READ_ACCESS, GraphDatabase, Query

# Today's Explore, copied from catalog-api api/queries/neo4j_queries.py
# (explore_artist, expand_artist_releases, count_artist_releases) so the comparison is
# like for like. Explore addresses artists by name.
EXPLORE_ARTIST = """
MATCH (a:Artist {name: $name})
CALL {
    WITH a
    OPTIONAL MATCH (a)-[:ALIAS_OF]->(alias:Artist)
    WITH a, collect(DISTINCT alias.id) AS alias_ids
    OPTIONAL MATCH (a)-[:MEMBER_OF]->(grp:Artist)
    WITH a, alias_ids, collect(DISTINCT grp.id) AS group_ids
    OPTIONAL MATCH (m:Artist)-[:MEMBER_OF]->(a)
    WITH alias_ids, group_ids, collect(DISTINCT m.id) AS member_ids
    UNWIND (alias_ids + group_ids + member_ids) AS related_id
    WITH DISTINCT related_id WHERE related_id IS NOT NULL
    RETURN count(related_id) AS alias_count
}
RETURN a.id AS id, a.name AS name,
       COUNT { MATCH (r:Release)-[:BY]->(a) RETURN DISTINCT r } AS release_count,
       COUNT { MATCH (r:Release)-[:BY]->(a), (r)-[:ON]->(l:Label) RETURN DISTINCT l } AS label_count,
       alias_count
"""

EXPAND_ARTIST_RELEASES = """
MATCH (r:Release)-[:BY]->(a:Artist {name: $name})
RETURN r.id AS id, r.title AS name, 'release' AS type,
       CASE WHEN r.year > 0 THEN r.year ELSE null END AS year
ORDER BY year IS NULL ASC, year DESC, id
SKIP $offset
LIMIT $limit
"""

COUNT_ARTIST_RELEASES = "MATCH (r:Release)-[:BY]->(a:Artist {name: $name}) RETURN count(DISTINCT r) AS total"

# Candidate strata route, query 1 of 2: the master and release planes in one pass.
# One row per master (and one row for masterless releases, m = null) with its release
# count, year span, and up to $per_master release rows carrying the caller's collector
# marks: the COLLECTED and WANTS edges the Discogs sync wrote, with the Discogs
# date_added they carry (the same edges /api/user/collection reads). The user is matched once, before the fan-out, so an anonymous call (no such
# User) costs one index probe. The route applies payload_model.build_payload's
# aggregation rule to these rows; $per_master bounds what crosses the wire for the
# largest masters.
STRATA_LADDER = """
MATCH (a:Artist {id: $id})
OPTIONAL MATCH (u:User {id: $user_id})
WITH a, u
MATCH (r:Release)-[:BY]->(a)
OPTIONAL MATCH (r)-[:DERIVED_FROM]->(m:Master)
OPTIONAL MATCH (u)-[c:COLLECTED|WANTS]->(r)
WITH m, r, [x IN collect(c) | {kind: type(x), date_added: x.date_added}] AS marks
ORDER BY r.year, r.id
WITH m, count(r) AS releases, min(r.year) AS y0, max(r.year) AS y1,
     collect({id: r.id, title: r.title, year: r.year, marks: marks})[..$per_master] AS sample
RETURN m.id AS master_id, m.title AS title, m.year AS year, releases, y0, y1, sample
"""

# Query 2 of 2: the credit plane. Joint credits (other artists on the same releases),
# then the alias and membership neighbours Explore already shows.
STRATA_CREDITS = """
MATCH (a:Artist {id: $id})
CALL {
    WITH a
    MATCH (a)<-[:BY]-(r:Release)-[:BY]->(o:Artist)
    WHERE o <> a
    WITH o, count(DISTINCT r) AS shared
    ORDER BY shared DESC, o.id
    LIMIT $credit_cap
    RETURN collect({id: o.id, name: o.name, shared: shared}) AS joint
}
CALL {
    WITH a
    OPTIONAL MATCH (a)-[rel:ALIAS_OF|MEMBER_OF]-(n:Artist)
    RETURN collect(DISTINCT {id: n.id, name: n.name, rel: type(rel)}) AS related
}
RETURN a.id AS id, a.name AS name, joint, related
"""

QUERIES = {
    "explore": (EXPLORE_ARTIST, "name"),
    "expand_releases": (EXPAND_ARTIST_RELEASES, "name"),
    "count_releases": (COUNT_ARTIST_RELEASES, "name"),
    "strata_ladder": (STRATA_LADDER, "id"),
    "strata_credits": (STRATA_CREDITS, "id"),
}

# A user id that no User node carries: the anonymous path. A signed-in measurement
# would need a real user's graph, which this harness does not touch.
ANONYMOUS = "00000000-0000-7000-8000-000000000000"


def params_for(name: str, artist_id: str, artist_name: str) -> dict[str, Any]:
    base = {"name": artist_name} if QUERIES[name][1] == "name" else {"id": artist_id}
    if name == "expand_releases":
        base |= {"limit": 50, "offset": 0}
    if name == "strata_ladder":
        base |= {"user_id": ANONYMOUS, "per_master": 50}
    if name == "strata_credits":
        base |= {"credit_cap": 48}
    return base


def timed(session, cypher: str, params: dict[str, Any], timeout: float) -> tuple[float, float, int, int]:
    started = time.perf_counter()
    result = session.run(Query(cypher, timeout=timeout), params)
    records = list(result)
    summary = result.consume()
    wall = (time.perf_counter() - started) * 1000
    server = (summary.result_available_after or 0) + (summary.result_consumed_after or 0)
    return wall, float(server), len(records), len(orjson.dumps([r.data() for r in records], default=str))


def nearest_rank(values: list[float], q: float) -> float:
    ordered = sorted(values)
    k = max(1, math.ceil(q * len(ordered)))
    return round(ordered[k - 1], 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample")
    ap.add_argument("out")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--expected-releases", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()
    sample: list[tuple[str, str]] = []
    with open(args.sample) as handle:
        for line in handle:
            band, artist_id = line.rstrip("\n").split("\t")
            sample.append((band, artist_id))

    driver = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    runs: dict[str, dict[str, list[tuple[float, float, int, int]]]] = defaultdict(lambda: defaultdict(list))
    failures: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    with driver.session(default_access_mode=READ_ACCESS) as session:
        version = session.run("CALL dbms.components() YIELD versions RETURN versions[0] AS v").single()["v"]
        releases_in_graph = session.run("MATCH (r:Release) RETURN count(r) AS n").single()["n"]
        for band, artist_id in sample:
            row = session.run("MATCH (a:Artist {id: $id}) RETURN a.name AS name", {"id": artist_id}).single()
            if row is None:
                failures[band]["artist_missing"] += 1
                continue
            for name, (cypher, _) in QUERIES.items():
                params = params_for(name, artist_id, row["name"])
                try:
                    timed(session, cypher, params, args.timeout)
                    for _ in range(args.repeats):
                        runs[band][name].append(timed(session, cypher, params, args.timeout))
                except Exception as exc:  # a timeout on the largest artists is a finding
                    failures[band][f"{name}:{type(exc).__name__}"] += 1
            print(band, "artist done", file=sys.stderr, flush=True)
    driver.close()

    result: dict[str, Any] = {
        "neo4j_version": version,
        "releases_in_graph": releases_in_graph,
        "releases_in_dump": args.expected_releases,
        "full_catalog": None if args.expected_releases is None else releases_in_graph >= 0.99 * args.expected_releases,
        "repeats": args.repeats,
        "bands": {},
    }
    for band, by_query in runs.items():
        result["bands"][band] = {
            name: {
                "runs": len(values),
                "p50_ms": nearest_rank([v[0] for v in values], 0.5),
                "p95_ms": nearest_rank([v[0] for v in values], 0.95),
                "server_p50_ms": nearest_rank([v[1] for v in values], 0.5),
                "server_p95_ms": nearest_rank([v[1] for v in values], 0.95),
                "rows_max": max(v[2] for v in values),
                "bytes_p50": nearest_rank([float(v[3]) for v in values], 0.5),
                "bytes_max": max(v[3] for v in values),
            }
            for name, values in by_query.items()
        }
        result["bands"][band]["failures"] = dict(failures.get(band, {}))
    with open(args.out, "wb") as handle:
        handle.write(orjson.dumps(result, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS) + b"\n")


if __name__ == "__main__":
    main()
