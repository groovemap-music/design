#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compact one decompressed Discogs XML dump, read from stdin, into a TSV for the replay.

    releases -> release_id, master_id ('' if none)
    masters  -> master_id
    artists  -> artist_id
    labels   -> label_id

These are the entities `discogs-sql-loader` mints a native item for, because its batch
writer resolves (lookup-or-create) a `discogs` alias for every message it receives
(`tableinator/batch_writer.py` at `e594106`, lines 76-82). The extractor publishes every
record of the dump except the ones its skip rules drop (`discogs-ingestion` at `ac08d5e`,
`src/discogs/mod.rs` lines 658-662). Those rules are in `extraction-rules.yaml`, lines
11-19: an artist or label whose `profile` contains "DO NOT USE", case-insensitively
(`src/discogs/rules.rs`, `should_skip_record`, lines 361-372). The record id is the `id`
attribute, or failing that the `<id>` child (`src/discogs/parser.rs`, line 308). A
release's master is the text of `<master_id>`, the value the loader reads as
`data ->> 'master_id'`.

The parser runs without `recover`, so a truncated stream is an error, not a short result.
The output goes to the work directory outside the repository.
"""

from __future__ import annotations

import argparse
import gzip
import sys

from lxml import etree


TAG = {"releases": "release", "masters": "master", "artists": "artist", "labels": "label"}
SKIP_PROFILE = {"artists": "do not use", "labels": "do not use"}


def record_id(elem) -> str:
    value = elem.get("id")
    if value is None:
        child = elem.find("id")
        value = child.text if child is not None else None
    return (value or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=sorted(TAG))
    parser.add_argument("out")
    args = parser.parse_args()
    tag, skip = TAG[args.kind], SKIP_PROFILE.get(args.kind)
    rows = skipped = 0
    with gzip.open(args.out, "wt", compresslevel=3) as out:
        for _, elem in etree.iterparse(sys.stdin.buffer, events=("end",), tag=tag, huge_tree=True):
            if elem.getparent() is not None and elem.getparent().getparent() is not None:
                continue  # a nested element of the same name, not a record
            if skip is not None:
                profile = elem.find("profile")
                if profile is not None and skip in "".join(profile.itertext()).lower():
                    skipped += 1
                    elem.clear()
                    continue
            cells = [record_id(elem)]
            if args.kind == "releases":
                master = elem.find("master_id")
                cells.append((master.text or "").strip() if master is not None else "")
            out.write("\t".join(cells) + "\n")
            rows += 1
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]
    print(f"{args.kind}: {rows} rows, {skipped} skipped", file=sys.stderr)
    if rows == 0:
        sys.exit("no records read")


if __name__ == "__main__":
    main()
