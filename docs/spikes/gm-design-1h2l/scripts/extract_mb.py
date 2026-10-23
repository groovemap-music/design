#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stream one MusicBrainz JSON dump member from stdin into a compact TSV.

    release        -> rg_mbid, discogs_release_id, n_release_links, discogs_master_id
    release-group  -> rg_mbid, discogs_master_id, n_master_links

Ids are written only to the work directory outside the repository. Empty string means
no link. The dump itself is never written to disk.

Usage:
    curl -s .../release.tar.xz | xz -dc | tar -xf - -O mbdump/release \
        | python extract_mb.py release out.tsv.gz
"""
from __future__ import annotations

import argparse
import gzip
import sys
import time

import orjson

from mb_links import count_discogs_links, find_discogs_id


def _cell(value: int | None) -> str:
    return "" if value is None else str(value)


def release_row(record: dict) -> str:
    rg = (record.get("release-group") or {}).get("id") or ""
    return "\t".join(
        (
            rg,
            _cell(find_discogs_id(record, "release")),
            str(count_discogs_links(record, "release")),
            _cell(find_discogs_id(record, "master")),
        )
    )


def release_group_row(record: dict) -> str:
    return "\t".join(
        (
            record.get("id") or "",
            _cell(find_discogs_id(record, "master")),
            str(count_discogs_links(record, "master")),
        )
    )


ROW = {"release": release_row, "release-group": release_group_row}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=sorted(ROW))
    ap.add_argument("out")
    args = ap.parse_args()
    row = ROW[args.kind]
    scanned = errors = 0
    started = time.time()
    with gzip.open(args.out, "wt", compresslevel=3, encoding="utf-8") as out:
        for line in sys.stdin.buffer:
            try:
                record = orjson.loads(line)
            except orjson.JSONDecodeError:
                errors += 1
                continue
            out.write(row(record) + "\n")
            scanned += 1
            if scanned % 500000 == 0:
                print(f"...{scanned} {scanned / (time.time() - started):.0f} rec/s", file=sys.stderr, flush=True)
    print(f"DONE {args.kind} scanned={scanned} parse_errors={errors} seconds={time.time() - started:.0f}", file=sys.stderr)
    if errors:
        sys.exit(2)


if __name__ == "__main__":
    main()
