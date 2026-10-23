#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""How the Discogs catalog fits concept A's credit -> master -> release ladder.

    ladder_stats.py <db.duckdb> <out.json>

Reads the tables load_db.py built and writes aggregates only: counts, shares, and
percentiles. No id, name, or title reaches the output. The ladder is read the way the
graph projects it: an artist's releases are its release-level `BY` edges, a release's
master is its `DERIVED_FROM` edge, and a master's credits are the union of its
releases' `BY` artists and release-level `CREDITED_ON` people.

Percentiles are nearest-rank (`quantile_disc`), so every reported value is one that
some artist or master actually has.
"""
from __future__ import annotations

import sys
from typing import Any

import orjson

from load_db import connect

# Size bands by an artist's release count. The latency and payload harnesses use the
# same bands so every table in the write-up lines up.
BANDS: list[tuple[str, int, int | None]] = [
    ("1-9", 1, 9),
    ("10-99", 10, 99),
    ("100-999", 100, 999),
    ("1000-9999", 1000, 9999),
    ("10000+", 10000, None),
]

# Same rule as discogs_rules.role_fragments: drop [qualifiers], split on commas, trim.
FRAGMENTS_SQL = r"""
    SELECT release_id, name, trim(fragment) AS fragment
    FROM (
        SELECT release_id, name,
               unnest(string_split(regexp_replace(role, '\s*\[[^\]]*\]', '', 'g'), ',')) AS fragment
        FROM rc
    )
    WHERE trim(fragment) <> ''
"""


def band_case(column: str) -> str:
    parts = []
    for label, low, high in BANDS:
        cond = f"{column} >= {low}" + (f" AND {column} <= {high}" if high is not None else "")
        parts.append(f"WHEN {cond} THEN '{label}'")
    return "CASE " + " ".join(parts) + " END"


def dist(con, source: str, column: str, where: str = "TRUE") -> dict[str, Any]:
    row = con.execute(
        f"""
        SELECT count(*), quantile_disc({column}, 0.5), quantile_disc({column}, 0.9),
               quantile_disc({column}, 0.95), quantile_disc({column}, 0.99), max({column}),
               avg({column})
        FROM {source} WHERE {where}
        """
    ).fetchone()
    n, p50, p90, p95, p99, mx, mean = row
    rnd = lambda v: None if v is None else (round(v, 4) if isinstance(v, float) else v)  # noqa: E731
    return {"n": n, "p50": rnd(p50), "p90": rnd(p90), "p95": rnd(p95), "p99": rnd(p99), "max": rnd(mx), "mean": rnd(mean)}


def _per_master_distinct(con, name: str, source: str, column: str) -> None:
    """count(DISTINCT column) per master as two plain GROUP BYs, which stay in memory."""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {name} AS
        SELECT master_id, count(*) AS n FROM (SELECT DISTINCT master_id, {column} FROM {source}) GROUP BY 1
        """
    )


def build_views(con) -> None:
    con.execute("CREATE OR REPLACE TEMP TABLE ra_d AS SELECT DISTINCT release_id, artist_id FROM ra")
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE art AS
        WITH per AS (
            SELECT a.artist_id,
                   count(*) AS n_rel,
                   count(*) FILTER (WHERE r.master_id IS NULL) AS n_noma,
                   count(*) FILTER (WHERE r.year IS NULL) AS n_noyear
            FROM ra_d a JOIN rel r USING (release_id)
            GROUP BY a.artist_id
        ), mas AS (
            SELECT artist_id, count(*) AS n_mas
            FROM (SELECT DISTINCT a.artist_id, r.master_id FROM ra_d a JOIN rel r USING (release_id) WHERE r.master_id IS NOT NULL)
            GROUP BY 1
        )
        SELECT per.artist_id, n_rel, coalesce(n_mas, 0) AS n_mas, n_noma, n_noyear, n_noma::DOUBLE / n_rel AS noma_share
        FROM per LEFT JOIN mas USING (artist_id)
        """
    )
    con.execute(f"ALTER TABLE art ADD COLUMN band VARCHAR; UPDATE art SET band = {band_case('n_rel')}")
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE cm AS
        SELECT r.master_id, c.release_id, c.name, c.role
        FROM rc c JOIN rel r USING (release_id) WHERE r.master_id IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE fm AS
        SELECT r.master_id, f.fragment
        FROM (""" + FRAGMENTS_SQL + """) f JOIN rel r USING (release_id) WHERE r.master_id IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE bm AS
        SELECT r.master_id, a.artist_id FROM rel r JOIN ra_d a USING (release_id) WHERE r.master_id IS NOT NULL
        """
    )
    _per_master_distinct(con, "m_by", "bm", "artist_id")
    _per_master_distinct(con, "m_people", "cm", "name")
    _per_master_distinct(con, "m_raw_roles", "cm", "role")
    _per_master_distinct(con, "m_edges", "cm", "release_id, name, role")
    _per_master_distinct(con, "m_roles", "fm", "fragment")
    _per_master_distinct(con, "m_own", "ma", "artist_id")
    con.execute("DROP TABLE cm; DROP TABLE fm; DROP TABLE bm")
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE mas AS
        WITH m AS (SELECT master_id, count(*) AS n_rel FROM rel WHERE master_id IS NOT NULL GROUP BY 1)
        SELECT m.master_id, m.n_rel,
               coalesce(b.n, 0) AS n_by,
               coalesce(o.n, 0) AS n_master_artists,
               coalesce(p.n, 0) AS n_people,
               coalesce(rr.n, 0) AS n_raw_roles,
               coalesce(f.n, 0) AS n_roles,
               coalesce(e.n, 0) AS n_credit_edges
        FROM m
        LEFT JOIN m_by b USING (master_id)
        LEFT JOIN m_own o USING (master_id)
        LEFT JOIN m_people p USING (master_id)
        LEFT JOIN m_raw_roles rr USING (master_id)
        LEFT JOIN m_roles f USING (master_id)
        LEFT JOIN m_edges e USING (master_id)
        """
    )


def ladder_stats(con) -> dict[str, Any]:
    build_views(con)
    q = lambda sql: con.execute(sql).fetchone()  # noqa: E731
    total, no_master, no_year, no_both = q(
        """
        SELECT count(*), count(*) FILTER (WHERE master_id IS NULL), count(*) FILTER (WHERE year IS NULL),
               count(*) FILTER (WHERE master_id IS NULL AND year IS NULL)
        FROM rel
        """
    )
    statuses = {status or "(none)": n for status, n in con.execute("SELECT status, count(*) FROM rel GROUP BY 1 ORDER BY 1").fetchall()}
    no_artist = q("SELECT count(*) FROM rel WHERE release_id NOT IN (SELECT release_id FROM ra_d)")[0]
    releases = {
        "total": total,
        "by_status": statuses,
        "no_master": no_master,
        "no_master_share": round(no_master / total, 4) if total else None,
        "no_year": no_year,
        "no_year_share": round(no_year / total, 4) if total else None,
        "no_master_and_no_year": no_both,
        "no_by_artist": no_artist,
    }

    per_artist = {
        "artists": q("SELECT count(*) FROM art")[0],
        "releases_per_artist": dist(con, "art", "n_rel"),
        "masters_per_artist": dist(con, "art", "n_mas"),
        "no_master_share_per_artist": dist(con, "art", "noma_share"),
        "artists_with_no_master_at_all": q("SELECT count(*) FROM art WHERE n_mas = 0")[0],
    }
    bands = []
    for label, _, _ in BANDS:
        where = f"band = '{label}'"
        n, rel_sum, noma_sum = q(f"SELECT count(*), sum(n_rel), sum(n_noma) FROM art WHERE {where}")
        bands.append(
            {
                "band": label,
                "artists": n,
                "releases": rel_sum,
                "pooled_no_master_share": round(noma_sum / rel_sum, 4) if rel_sum else None,
                "releases_per_artist": dist(con, "art", "n_rel", where),
                "masters_per_artist": dist(con, "art", "n_mas", where),
                "no_master_share_per_artist": dist(con, "art", "noma_share", where),
            }
        )
    largest = [
        {"rank": rank, "releases": n_rel, "masters": n_mas, "no_master_share": round(share, 4), "no_year": n_noyear}
        for rank, (n_rel, n_mas, share, n_noyear) in enumerate(
            con.execute("SELECT n_rel, n_mas, noma_share, n_noyear FROM art ORDER BY n_rel DESC, n_mas DESC LIMIT 10").fetchall(),
            start=1,
        )
    ]

    masters_in_dump = q("SELECT count(*) FROM ms")[0]
    referenced = q("SELECT count(*) FROM mas")[0]
    per_master = {
        "masters_in_dump": masters_in_dump,
        "masters_with_a_release": referenced,
        "masters_with_no_release_in_dump": q("SELECT count(*) FROM ms WHERE master_id NOT IN (SELECT master_id FROM mas)")[0],
        "release_master_ids_missing_from_masters_dump": q("SELECT count(*) FROM mas WHERE master_id NOT IN (SELECT master_id FROM ms)")[0],
        "releases_per_master": dist(con, "mas", "n_rel"),
        "credit_fan_out": {
            "by_artists_per_master": dist(con, "mas", "n_by"),
            "masters_with_more_than_one_by_artist": q("SELECT count(*) FROM mas WHERE n_by > 1")[0],
            "master_artists_per_master": dist(con, "mas", "n_master_artists"),
            "masters_with_more_than_one_master_artist": q("SELECT count(*) FROM mas WHERE n_master_artists > 1")[0],
            "credited_people_per_master": dist(con, "mas", "n_people"),
            "masters_with_no_credited_people": q("SELECT count(*) FROM mas WHERE n_people = 0")[0],
            "raw_roles_per_master": dist(con, "mas", "n_raw_roles"),
            "roles_per_master": dist(con, "mas", "n_roles"),
            "credited_on_edges_per_master": dist(con, "mas", "n_credit_edges"),
        },
    }
    credits = {
        "credited_on_rows": q("SELECT count(*) FROM rc")[0],
        "distinct_people": q("SELECT count(*) FROM (SELECT DISTINCT name FROM rc)")[0],
        "distinct_raw_roles": q("SELECT count(*) FROM (SELECT DISTINCT role FROM rc)")[0],
        "distinct_roles": q(f"SELECT count(*) FROM (SELECT DISTINCT fragment FROM ({FRAGMENTS_SQL}))")[0],
        "releases_with_credits": q("SELECT count(*) FROM (SELECT DISTINCT release_id FROM rc)")[0],
    }
    with_master, with_master_no_year, master_year_fallback = q(
        """
        SELECT count(*), count(*) FILTER (WHERE r.year IS NULL),
               count(*) FILTER (WHERE r.year IS NULL AND m.year IS NOT NULL)
        FROM rel r LEFT JOIN ms m USING (master_id) WHERE r.master_id IS NOT NULL
        """
    )
    years = {
        "masters_with_no_year": q("SELECT count(*) FROM ms WHERE year IS NULL")[0],
        "releases_with_a_master_and_no_year": with_master_no_year,
        "of_which_the_master_has_a_year": master_year_fallback,
        "masterless_releases_with_no_year": no_both,
        "releases_with_no_year_even_after_master_fallback": with_master_no_year - master_year_fallback + no_both,
    }
    return {
        "years": years,
        "releases": releases,
        "per_artist": per_artist,
        "bands": bands,
        "largest_artists": largest,
        "per_master": per_master,
        "credits": credits,
    }


def main() -> None:
    db, out = sys.argv[1:3]
    con = connect(db)
    result = ladder_stats(con)
    with open(out, "wb") as handle:
        handle.write(orjson.dumps(result, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS) + b"\n")


if __name__ == "__main__":
    main()
