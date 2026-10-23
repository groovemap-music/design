#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Which MusicBrainz-only releases can hang under a Discogs master on the ladder.

    mb_attach.py <db.duckdb> <out.json>

A MusicBrainz-only release has no `discogs_release_id` (the ingestion rule in
mb_links.py), so the graph has no node for it: musicbrainz-graph-enricher merges
MusicBrainz data onto the Discogs node its Discogs id names and skips the rest. It can
still reach a master two ways, tried in this order:

1. native id: its release group carries `discogs_master_id`. That is the alias the
   loaders mint into one native item for the group and the master (ADR 0009, ADR 0014
   section 8). `exists` checks the master is in the Discogs dump.
2. release group: no master link on the group, but sibling releases in the same group
   are linked to Discogs releases, and those releases derive from exactly one master.
   More than one master among the siblings is reported as ambiguous, not attached.

Everything else stays off the master plane. Output is counts only.
"""
from __future__ import annotations

import sys
from typing import Any

import orjson

from load_db import connect


def mb_attach(con) -> dict[str, Any]:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE sib AS
        SELECT m.rg_mbid,
               count(*) AS n_linked,
               count(DISTINCT r.master_id) AS n_masters,
               min(r.master_id) AS only_master,
               count(*) FILTER (WHERE r.release_id IS NULL) AS n_dangling
        FROM mbr m LEFT JOIN rel r ON r.release_id = m.discogs_release_id
        WHERE m.discogs_release_id IS NOT NULL
        GROUP BY m.rg_mbid
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE mbonly AS
        SELECT m.rg_mbid,
               m.discogs_master_id AS release_master_link,
               g.discogs_master_id AS group_master,
               g.discogs_master_id IN (SELECT master_id FROM ms) AS group_master_exists,
               coalesce(s.n_linked, 0) AS n_linked_siblings,
               coalesce(s.n_masters, 0) AS n_sibling_masters
        FROM mbr m
        LEFT JOIN mbg g USING (rg_mbid)
        LEFT JOIN sib s USING (rg_mbid)
        WHERE m.discogs_release_id IS NULL
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE mbonly_path AS
        SELECT *,
               CASE
                 WHEN group_master IS NOT NULL AND group_master_exists THEN 'native_id'
                 WHEN group_master IS NOT NULL THEN 'native_id_master_missing_from_dump'
                 WHEN n_sibling_masters = 1 THEN 'release_group_one_master'
                 WHEN n_sibling_masters > 1 THEN 'release_group_ambiguous'
                 WHEN n_linked_siblings > 0 THEN 'release_group_siblings_masterless'
                 ELSE 'none'
               END AS path
        FROM mbonly
        """
    )
    q = lambda sql: con.execute(sql).fetchone()  # noqa: E731
    total, linked = q("SELECT count(*), count(discogs_release_id) FROM mbr")
    multi = q("SELECT count(*) FROM mbr WHERE n_release_links > 1")[0]
    dangling = q("SELECT count(*) FROM mbr m WHERE discogs_release_id IS NOT NULL AND discogs_release_id NOT IN (SELECT release_id FROM rel)")[0]
    only = total - linked
    paths = dict(con.execute("SELECT path, count(*) FROM mbonly_path GROUP BY 1 ORDER BY 1").fetchall())
    attached = paths.get("native_id", 0) + paths.get("release_group_one_master", 0)
    groups, groups_linked = q("SELECT count(*), count(discogs_master_id) FROM mbg")
    groups_dangling = q("SELECT count(*) FROM mbg WHERE discogs_master_id IS NOT NULL AND discogs_master_id NOT IN (SELECT master_id FROM ms)")[0]
    # Does the group's master agree with the masters its linked releases derive from?
    agree, disagree = q(
        """
        SELECT count(*) FILTER (WHERE s.n_masters = 1 AND s.only_master = g.discogs_master_id),
               count(*) FILTER (WHERE NOT (s.n_masters = 1 AND s.only_master = g.discogs_master_id))
        FROM mbg g JOIN sib s USING (rg_mbid)
        WHERE g.discogs_master_id IS NOT NULL AND s.n_masters > 0
        """
    )
    release_level_master = q("SELECT count(*) FROM mbonly WHERE release_master_link IS NOT NULL")[0]
    return {
        "mb_releases": total,
        "linked_to_discogs_release": linked,
        "linked_share": round(linked / total, 4) if total else None,
        "linked_to_more_than_one_discogs_release": multi,
        "linked_but_release_missing_from_discogs_dump": dangling,
        "mb_only_releases": only,
        "mb_only_by_path": paths,
        "mb_only_attached_to_a_master": attached,
        "mb_only_attached_share": round(attached / only, 4) if only else None,
        "mb_only_with_a_release_level_master_link": release_level_master,
        "release_groups": groups,
        "release_groups_with_master_link": groups_linked,
        "release_group_master_missing_from_discogs_dump": groups_dangling,
        "group_master_vs_sibling_masters": {"agree": agree, "disagree": disagree},
    }


def main() -> None:
    db, out = sys.argv[1:3]
    con = connect(db)
    result = mb_attach(con)
    with open(out, "wb") as handle:
        handle.write(orjson.dumps(result, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS) + b"\n")


if __name__ == "__main__":
    main()
