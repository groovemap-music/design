#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""latency.py's queries, timed server-side through a read-only cypher-shell wrapper.

    GM_CYPHER_CMD="<read-only cypher-shell wrapper> 3000" \
        latency_shell.py <sample.tsv> <out.json> [--per-band 30] [--repeats 5]

For a Neo4j reachable only through a wrapper that runs cypher-shell in READ mode and
never hands out a password (the predecessor graph this spike measured). A process per
statement would time ssh and the JVM, so the script sends one session per band and
times each statement inside the server:

    WITH datetime.realtime() AS t0
    CALL () { <the query> }
    WITH t0, count(*) AS rows
    RETURN <band>, <query>, <run>, rows, <microseconds since t0>

(An artist missing from the graph yields no row, so `artists_measured` counts the
artists that answered.)

`datetime.realtime()` is read when evaluated, not fixed per statement, so the
difference is the server's execution time with every row produced. Result transfer to
a client is not included. Run 0 is the first run on that artist (cold for its plan and
its pages, unless an earlier artist touched them) and is reported apart from the
repeats. Ids are inlined as string literals, which Neo4j auto-parameterises, so the
plan cache behaves as it does for the route.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import shlex
import subprocess
import sys
from collections import defaultdict

import orjson

from latency import ANONYMOUS, QUERIES, params_for

ROW = re.compile(r'^"([^"]+)", "([^"]+)", (\d+), (\d+), (-?\d+)$')


def literal(value) -> str:
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return str(value)


def inline(cypher: str, params: dict) -> str:
    for key in sorted(params, key=len, reverse=True):
        cypher = cypher.replace("$" + key, literal(params[key]))
    return cypher


def statement(band: str, name: str, run: int, artist_id: str) -> str:
    cypher, key = QUERIES[name]
    params = params_for(name, artist_id, "")
    if key == "name":
        # Explore addresses artists by name: look it up first, outside the timed part.
        body = inline(cypher, {k: v for k, v in params.items() if k != "name"}).replace("$name", "root_name")
        return (
            f"MATCH (x:Artist {{id: {literal(artist_id)}}}) WITH x.name AS root_name LIMIT 1\n"
            f"WITH root_name, datetime.realtime() AS t0\nCALL (root_name) {{\n{body}\n}}\n"
            f"WITH t0, count(*) AS rows\n"
            f"RETURN {literal(band)}, {literal(name)}, {run}, rows, duration.inSeconds(t0, datetime.realtime()).microseconds;\n"
        )
    body = inline(cypher, params)
    return (
        f"WITH datetime.realtime() AS t0\nCALL () {{\n{body}\n}}\n"
        f"WITH t0, count(*) AS rows\n"
        f"RETURN {literal(band)}, {literal(name)}, {run}, rows, duration.inSeconds(t0, datetime.realtime()).microseconds;\n"
    )


def nearest_rank(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(1, math.ceil(q * len(ordered))) - 1], 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample")
    ap.add_argument("out")
    ap.add_argument("--per-band", type=int, default=30)
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()
    command = shlex.split(os.environ["GM_CYPHER_CMD"])
    by_band: dict[str, list[str]] = defaultdict(list)
    with open(args.sample) as handle:
        for line in handle:
            band, artist_id = line.rstrip("\n").split("\t")
            if len(by_band[band]) < args.per_band:
                by_band[band].append(artist_id)

    first: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    warm: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    rows_max: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for band, artists in by_band.items():
        script = []
        for artist_id in artists:
            for name in QUERIES:
                for run in range(args.repeats + 1):
                    script.append(statement(band, name, run, artist_id))
        done = subprocess.run(command, input="".join(script), capture_output=True, text=True, check=False)
        if done.returncode != 0:
            print(f"{band}: exit {done.returncode}\n{done.stderr[-2000:]}", file=sys.stderr)
            sys.exit(done.returncode)
        for line in done.stdout.splitlines():
            match = ROW.match(line.strip())
            if not match:
                continue
            row_band, name, run, rows, ms = match.groups()
            (first if run == "0" else warm)[row_band][name].append(int(ms) / 1000)
            rows_max[row_band][name] = max(rows_max[row_band][name], int(rows))
        print(band, len(artists), "artists done", file=sys.stderr, flush=True)

    result = {
        "timing": "server-side, datetime.realtime() around each statement; transfer excluded",
        "per_band": args.per_band,
        "repeats": args.repeats,
        "anonymous_user": ANONYMOUS,
        "bands": {
            band: {
                "artists": len(by_band[band]),
                # An artist absent from the graph returns no row at all, so it shows as
                # fewer first runs than artists.
                "artists_measured": len(first[band]["strata_credits"]),
                "queries": {
                    name: {
                        "runs": len(warm[band][name]),
                        "p50_ms": nearest_rank(warm[band][name], 0.5),
                        "p95_ms": nearest_rank(warm[band][name], 0.95),
                        "max_ms": round(max(warm[band][name]), 1),
                        "first_run_p50_ms": nearest_rank(first[band][name], 0.5),
                        "first_run_max_ms": round(max(first[band][name]), 1),
                        "rows_max": rows_max[band][name],
                    }
                    for name in QUERIES
                    if warm[band][name]
                },
            }
            for band in by_band
        },
    }
    with open(args.out, "wb") as handle:
        handle.write(orjson.dumps(result, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS) + b"\n")


if __name__ == "__main__":
    main()
