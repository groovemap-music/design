#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stream a decompressed Discogs XML dump from stdin into compact TSVs in OUT_DIR.

releases ->
    releases.tsv.gz         release_id, master_id ('' if none or the 0 sentinel), is_main, year ('' if
                            none), title_bytes, status
    release_artists.tsv.gz  release_id, artist_id, name_bytes  (release-level <artists>;
                            the graph's BY edges)
    release_credits.tsv.gz  release_id, name, role, artist_id  (release-level
                            <extraartists> with a name and a role; the graph's
                            Person-[:CREDITED_ON {role}]->Release edges)
masters ->
    masters.tsv.gz          master_id, main_release, year, title_bytes
    master_artists.tsv.gz   master_id, artist_id

Track-level artists and credits are not read: the graph projects only release-level
lists (discogs-ingestion `normalize_release`, discogs-graph-enricher `batch_projection`).
The parser runs without `recover`, so a truncated stream is an error rather than a
short, clean-looking result. Everything lands outside the repository.
"""
from __future__ import annotations

import argparse
import gzip
import os
import sys
import time

from lxml import etree

from discogs_rules import year_of


def _text(elem, tag: str) -> str:
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _clean(value: str) -> str:
    return value.replace("\t", " ").replace("\n", " ").replace("\r", " ")


def release_rows(elem, max_year: int):
    """(release row, artist rows, credit rows) for one <release> element."""
    rid = elem.get("id")
    master = elem.find("master_id")
    master_id = (master.text or "").strip() if master is not None else ""
    # Discogs writes `0` for "no master". GrooveMap's own rule (database-schema
    # `_usable_id`, discogs-sql-loader `_entity_id`) treats it as no entity.
    if master_id == "0":
        master_id = ""
    is_main = "1" if master is not None and master.get("is_main_release") == "true" else "0"
    year = year_of(_text(elem, "released"), max_year)
    title = _text(elem, "title")
    release = (rid, master_id, is_main, "" if year is None else str(year), str(len(title.encode())), elem.get("status") or "")
    artists = []
    container = elem.find("artists")
    if container is not None:
        for artist in container.findall("artist"):
            aid = _text(artist, "id")
            if aid:
                artists.append((rid, aid, str(len(_text(artist, "name").encode()))))
    credits = []
    container = elem.find("extraartists")
    if container is not None:
        for artist in container.findall("artist"):
            name, role = _text(artist, "name"), _text(artist, "role")
            if name and role:
                credits.append((rid, _clean(name), _clean(role), _text(artist, "id")))
    return release, artists, credits


def master_rows(elem, max_year: int):
    mid = elem.get("id")
    year = year_of(_text(elem, "year"), max_year)
    title = _text(elem, "title")
    master = (mid, _text(elem, "main_release"), "" if year is None else str(year), str(len(title.encode())))
    artists = []
    container = elem.find("artists")
    if container is not None:
        for artist in container.findall("artist"):
            aid = _text(artist, "id")
            if aid:
                artists.append((mid, aid))
    return master, artists


def _open(out_dir: str, name: str):
    return gzip.open(os.path.join(out_dir, name + ".part"), "wt", compresslevel=3, encoding="utf-8")


def _write(handle, rows) -> None:
    for row in rows:
        handle.write("\t".join(row) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["releases", "masters"])
    ap.add_argument("out_dir")
    ap.add_argument("--max-year", type=int, required=True, help="dump year + 1")
    args = ap.parse_args()
    names = (
        ["releases.tsv.gz", "release_artists.tsv.gz", "release_credits.tsv.gz"]
        if args.kind == "releases"
        else ["masters.tsv.gz", "master_artists.tsv.gz"]
    )
    tag = args.kind[:-1]
    handles = [_open(args.out_dir, name) for name in names]
    seen = 0
    started = time.time()
    for _, elem in etree.iterparse(sys.stdin.buffer, events=("end",), tag=tag, huge_tree=True):
        if args.kind == "releases":
            release, artists, credits = release_rows(elem, args.max_year)
            _write(handles[0], [release])
            _write(handles[1], artists)
            _write(handles[2], credits)
        else:
            master, artists = master_rows(elem, args.max_year)
            _write(handles[0], [master])
            _write(handles[1], artists)
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
        seen += 1
        if seen % 500000 == 0:
            print(f"...{seen} {seen / (time.time() - started):.0f} rec/s", file=sys.stderr, flush=True)
    for handle in handles:
        handle.close()
    for name in names:
        os.replace(os.path.join(args.out_dir, name + ".part"), os.path.join(args.out_dir, name))
    print(f"DONE {args.kind} {seen} seconds={time.time() - started:.0f}", file=sys.stderr)


if __name__ == "__main__":
    main()
