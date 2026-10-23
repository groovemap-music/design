#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compact one MusicBrainz JSON dump member, read from stdin, into a TSV for the replay.

    release        -> mbid, discogs_release_id, release_group_mbid
    release-group  -> mbid, discogs_master_id
    artist         -> mbid, discogs_artist_id
    label          -> mbid, discogs_label_id

An empty cell means no link. The output goes to the work directory outside the
repository, and the dump itself is never written to disk.

The Discogs id is the one `musicbrainz-ingestion` extracts (`src/musicbrainz/jsonl_parser.rs`
at `6c6c284`). `extract_url_rels` (lines 58-60) keeps relations whose `target-type` is
`url`. `find_discogs_id` (lines 216-228) takes the first `type == "discogs"` relation whose
resource `extract_discogs_id` (lines 45-51) accepts. That function strips the prefix
`https://www.discogs.com/<entity>/`, keeps the text before the first `-`, and parses it as
an `i64`. The entity is `artist` (line 242), `label` (line 288), `release` (line 328), or
`master` for a release group (line 379). `release_group_mbid` is `release-group.id` (line
331). Copied, not imported.
"""

from __future__ import annotations

import argparse
import gzip
import re
import sys

import orjson


ENTITY = {"release": "release", "release-group": "master", "artist": "artist", "label": "label"}

# Rust's `str::parse::<i64>`: an optional `+`, then one or more ASCII digits, in range.
_I64 = re.compile(r"\+?[0-9]+")
_I64_MAX = 2**63 - 1


def extract_discogs_id(url: str, entity: str) -> int | None:
    prefix = f"https://www.discogs.com/{entity}/"
    if not url.startswith(prefix):
        return None
    head = url[len(prefix):].split("-", 1)[0]
    if not _I64.fullmatch(head):
        return None
    value = int(head)
    return value if value <= _I64_MAX else None


def find_discogs_id(record: dict, entity: str) -> int | None:
    for rel in record.get("relations") or ():
        if rel.get("target-type") != "url" or rel.get("type") != "discogs":
            continue
        resource = (rel.get("url") or {}).get("resource")
        if not isinstance(resource, str):
            continue
        found = extract_discogs_id(resource, entity)
        if found is not None:
            return found
    return None


def row(kind: str, record: dict) -> str:
    discogs = find_discogs_id(record, ENTITY[kind])
    cells = [record.get("id") or "", "" if discogs is None else str(discogs)]
    if kind == "release":
        cells.append((record.get("release-group") or {}).get("id") or "")
    return "\t".join(cells)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=sorted(ENTITY))
    parser.add_argument("out")
    args = parser.parse_args()
    rows = linked = 0
    with gzip.open(args.out, "wt", compresslevel=3) as out:
        for line in sys.stdin.buffer:
            if not line.strip():
                continue
            text = row(args.kind, orjson.loads(line))
            rows += 1
            linked += text.split("\t")[1] != ""
            out.write(text + "\n")
    print(f"{args.kind}: {rows} rows, {linked} linked", file=sys.stderr)
    if rows == 0:
        sys.exit("no records read")


if __name__ == "__main__":
    main()
