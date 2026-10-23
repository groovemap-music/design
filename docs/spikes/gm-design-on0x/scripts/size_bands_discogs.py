#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Size bands for the strata fixtures, from gm-design-1h2l's Discogs 20261001 database.

    uv run --no-project --with duckdb==2.0.0 python -I scripts/size_bands_discogs.py \
        ~/.cache/groovemap-spikes/gm-design-1h2l/spike.duckdb > results/size_bands.json

The database is opened read-only. It is gm-design-1h2l's `load_db.py` output: `rel`
(release_id, master_id, year, ...), `ra` (release_id, artist_id: the release-level `BY`
edges), and `ms` (master_id, year, ...). The ladder is read the way gm-design-1h2l reads
the graph:

- an artist's releases are its `BY` releases;
- a release's master is its `master_id`. Discogs writes `0` for "no master" and GrooveMap
  treats it as no entity, so both NULL and 0 count as masterless;
- an artist's masters are the distinct masters of its releases;
- a release with no year takes its master's year; a release that still has none is
  undated.

An artist's size in nodes is 1 + masters + releases (on masters or not), and the bands
match the fixture scales: 50, 500, 5,000, and 20,000 nodes, split at the geometric
midpoints. Each band also reports `near`: the same shape over artists within a factor of
1.6 of the fixture scale, which is what the fixtures use. Every artist weighs the same: the releases-per-master
histogram is the mean of each artist's own bucket shares, and the masterless and
undated shares are per-artist means, so one placeholder-sized root cannot set the shape
of its band. Pooled counts are reported alongside. Output is aggregates only.
"""
from __future__ import annotations

import json
import sys

import duckdb

BANDS = [("b50", 1, 158), ("b500", 159, 1581), ("b5000", 1582, 10000), ("b20000", 10001, 1_000_000_000)]
# The fixture at each scale borrows its shape from artists near that scale (within a factor
# of 1.6), because a band's per-artist means are set by its smallest members: 71.5% of
# artists have no master at all, which says nothing about a 50-node discography.
SCALES = {"b50": 50, "b500": 500, "b5000": 5000, "b20000": 20000}
BUCKETS = [(1, 1), (2, 2), (3, 4), (5, 9), (10, 30), (31, 100), (101, 400), (401, 1000), (1001, 1_000_000_000)]


def main() -> None:
    con = duckdb.connect(sys.argv[1], read_only=True)
    con.execute("SET preserve_insertion_order = false")
    con.execute(
        """
        CREATE TEMP TABLE r AS
        SELECT rel.release_id,
               CASE WHEN rel.master_id IS NULL OR rel.master_id = 0 THEN NULL ELSE rel.master_id END AS master_id,
               rel.year AS raw_year,
               coalesce(rel.year, ms.year) AS year
        FROM rel LEFT JOIN ms ON ms.master_id = rel.master_id AND rel.master_id <> 0
        """
    )
    con.execute("CREATE TEMP TABLE ar AS SELECT DISTINCT a.artist_id, r.* FROM ra a JOIN r USING (release_id)")
    con.execute(
        """
        CREATE TEMP TABLE art AS
        SELECT artist_id,
               count(*) AS releases,
               count(*) FILTER (WHERE master_id IS NULL) AS masterless,
               count(*) FILTER (WHERE year IS NULL) AS undated,
               count(*) FILTER (WHERE raw_year IS NULL) AS undated_raw,
               count(DISTINCT master_id) AS masters
        FROM ar GROUP BY artist_id
        """
    )
    con.execute("ALTER TABLE art ADD COLUMN nodes BIGINT; UPDATE art SET nodes = 1 + masters + releases")
    band_case = " ".join(f"WHEN nodes BETWEEN {lo} AND {hi} THEN '{name}'" for name, lo, hi in BANDS)
    con.execute(f"ALTER TABLE art ADD COLUMN band VARCHAR; UPDATE art SET band = CASE {band_case} END")
    bucket_case = " ".join(f"WHEN n BETWEEN {lo} AND {hi} THEN {i}" for i, (lo, hi) in enumerate(BUCKETS))
    # Releases per master within each artist's own releases, then each artist's bucket shares.
    con.execute(
        f"""
        CREATE TEMP TABLE am AS
        SELECT artist_id, CASE {bucket_case} END AS bucket, count(*) AS masters
        FROM (SELECT artist_id, master_id, count(*) AS n FROM ar WHERE master_id IS NOT NULL GROUP BY 1, 2)
        GROUP BY 1, 2
        """
    )

    def shape(where: str, params: list) -> dict:
        row = con.execute(
            f"""
            SELECT count(*), avg(masterless::DOUBLE / releases), avg(undated::DOUBLE / releases),
                   count(*) FILTER (WHERE masters > 0)
            FROM art WHERE {where}
            """,
            params,
        ).fetchone()
        n, ml, ud, with_masters = row
        shares = dict(
            con.execute(
                f"SELECT bucket, sum(am.masters::DOUBLE / art.masters) / ? FROM am JOIN art USING (artist_id) WHERE {where} GROUP BY bucket",
                [with_masters or 1, *params],
            ).fetchall()
        )
        return {
            "credits": n,
            "masterless_share_per_artist": round(ml, 4),
            "undated_share_per_artist": round(ud, 4),
            "releases_per_master": [
                [BUCKETS[b][0], min(BUCKETS[b][1], 5000), round(shares[b] * 1_000_000)] for b in sorted(shares) if shares[b] > 0
            ],
        }

    out_bands = []
    for name, lo, hi in BANDS:
        row = con.execute(
            """
            SELECT count(*), sum(releases), sum(masterless), sum(undated), sum(undated_raw), sum(masters),
                   avg(masterless::DOUBLE / releases), avg(undated::DOUBLE / releases),
                   count(*) FILTER (WHERE masters > 0)
            FROM art WHERE band = ?
            """,
            [name],
        ).fetchone()
        credits, releases, masterless, undated, undated_raw, masters, ml_share, ud_share, with_masters = row
        shares = dict(
            con.execute(
                """
                SELECT bucket, sum(am.masters::DOUBLE / art.masters) / ?
                FROM am JOIN art USING (artist_id) WHERE art.band = ? GROUP BY bucket
                """,
                [with_masters or 1, name],
            ).fetchall()
        )
        pooled = dict(
            con.execute(
                "SELECT bucket, sum(am.masters) FROM am JOIN art USING (artist_id) WHERE art.band = ? GROUP BY bucket",
                [name],
            ).fetchall()
        )
        out_bands.append(
            {
                "name": name,
                "nodes": [lo, min(hi, 1_000_000)],
                "credits": credits,
                "releases_on_masters": int(releases - masterless),
                "masterless_releases": int(masterless),
                "undated_releases": int(undated),
                "undated_raw": int(undated_raw),
                "masters": int(masters),
                "masterless_share_per_artist": round(ml_share, 4),
                "undated_share_per_artist": round(ud_share, 4),
                # [lo, hi, weight]: weight is the per-artist mean share in parts per million.
                "releases_per_master": [
                    [BUCKETS[b][0], min(BUCKETS[b][1], 5000), round(shares[b] * 1_000_000)]
                    for b in sorted(shares) if shares[b] > 0
                ],
                "near": {"nodes": [round(SCALES[name] / 1.6), round(SCALES[name] * 1.6)], **shape("nodes BETWEEN ? AND ?", [round(SCALES[name] / 1.6), round(SCALES[name] * 1.6)])},
                "releases_per_master_pooled": [
                    [BUCKETS[b][0], min(BUCKETS[b][1], 5000), int(pooled[b])] for b in sorted(pooled)
                ],
            }
        )

    totals = con.execute(
        """
        SELECT count(*), count(*) FILTER (WHERE master_id IS NULL), count(*) FILTER (WHERE year IS NULL),
               count(*) FILTER (WHERE raw_year IS NULL)
        FROM r
        """
    ).fetchone()
    q = con.execute(
        "SELECT quantile_disc(nodes, [0.5, 0.9, 0.99, 0.999, 0.9999]), count(*) FROM art"
    ).fetchone()
    rpm = con.execute(
        """
        SELECT quantile_disc(n, [0.5, 0.9, 0.99, 0.999]), max(n)
        FROM (SELECT master_id, count(*) AS n FROM r WHERE master_id IS NOT NULL GROUP BY 1)
        """
    ).fetchone()
    largest = con.execute(
        "SELECT nodes, masters, releases, masterless, undated FROM art ORDER BY nodes DESC LIMIT 10"
    ).fetchall()
    json.dump(
        {
            "source": "Discogs 20261001 via gm-design-1h2l's spike.duckdb (load_db.py); query: scripts/size_bands_discogs.py",
            "releases": totals[0],
            "masterless_releases": totals[1],
            "undated_releases": totals[2],
            "undated_raw": totals[3],
            "credits_with_releases": q[1],
            "credit_nodes": dict(zip(["p50", "p90", "p99", "p999", "p9999"], q[0])),
            "releases_per_master": dict(zip(["p50", "p90", "p99", "p999"], rpm[0])) | {"max": rpm[1]},
            "largest_credits": [
                {"nodes": n, "masters": m, "releases": r, "masterless": ml, "undated": u} for n, m, r, ml, u in largest
            ],
            "bands": out_bands,
        },
        sys.stdout,
        indent=1,
    )
    print()


if __name__ == "__main__":
    main()
