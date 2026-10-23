#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Load the compact TSVs into one DuckDB file in the work directory.

    load_db.py <discogs_dir> <mb_release.tsv.gz> <mb_release_group.tsv.gz> <out.duckdb>

Every later script reads this file, so the dumps are parsed once. Missing MusicBrainz
inputs are allowed (pass '-'): the Discogs tables load on their own.
"""
from __future__ import annotations

import os
import sys

import duckdb

TABLES = {
    "rel": ("releases.tsv.gz", {"release_id": "BIGINT", "master_id": "BIGINT", "is_main": "INTEGER", "year": "INTEGER", "title_bytes": "INTEGER", "status": "VARCHAR"}),
    "ra": ("release_artists.tsv.gz", {"release_id": "BIGINT", "artist_id": "BIGINT", "name_bytes": "INTEGER"}),
    "rc": ("release_credits.tsv.gz", {"release_id": "BIGINT", "name": "VARCHAR", "role": "VARCHAR", "artist_id": "BIGINT"}),
    "ms": ("masters.tsv.gz", {"master_id": "BIGINT", "main_release": "BIGINT", "year": "INTEGER", "title_bytes": "INTEGER"}),
    "ma": ("master_artists.tsv.gz", {"master_id": "BIGINT", "artist_id": "BIGINT"}),
}
MB = {
    "mbr": {"rg_mbid": "VARCHAR", "discogs_release_id": "BIGINT", "n_release_links": "INTEGER", "discogs_master_id": "BIGINT"},
    "mbg": {"rg_mbid": "VARCHAR", "discogs_master_id": "BIGINT", "n_master_links": "INTEGER"},
}


def read_tsv(path: str, columns: dict[str, str]) -> str:
    cols = ", ".join(f"'{k}': '{v}'" for k, v in columns.items())
    return f"read_csv('{path}', delim='\t', header=false, quote='', escape='', columns={{{cols}}})"


def connect(path: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(path)
    con.execute("SET threads = 4")
    con.execute("SET memory_limit = '12GB'")
    con.execute("SET max_temp_directory_size = '1GB'")
    con.execute("SET preserve_insertion_order = false")
    con.execute(f"SET temp_directory = '{os.path.dirname(os.path.abspath(path))}/duckdb_tmp'")
    return con


def main() -> None:
    discogs_dir, mb_release, mb_group, out = sys.argv[1:5]
    con = connect(out)
    for table, (name, columns) in TABLES.items():
        path = os.path.join(discogs_dir, name)
        if os.path.exists(path):
            con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM {read_tsv(path, columns)}")
            if table == "rel":
                # The Discogs `0` master sentinel means no master (extract_discogs.py drops it
                # too; this keeps extracts made before that rule correct).
                con.execute("UPDATE rel SET master_id = NULL WHERE master_id = 0")
            print(table, con.execute(f"SELECT count(*) FROM {table}").fetchone()[0], file=sys.stderr)
    for table, path in (("mbr", mb_release), ("mbg", mb_group)):
        if path != "-":
            con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM {read_tsv(path, MB[table])}")
            print(table, con.execute(f"SELECT count(*) FROM {table}").fetchone()[0], file=sys.stderr)
    con.close()


if __name__ == "__main__":
    main()
