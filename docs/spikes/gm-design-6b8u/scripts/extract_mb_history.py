#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stream a MusicBrainz full export, read from stdin, into the history of its release→Discogs links.

    bzip2 -dc < mbdump.tar.bz2 | python extract_mb_history.py core   core.npz
    bzip2 -dc < mbdump-derived.tar.bz2 | python extract_mb_history.py derived derived.npz

The JSON dumps hold only current state, and only the two newest are kept, so they cannot
show months. The full export's PostgreSQL tables carry two timestamps that can:

- `l_release_url.last_updated`: when the release→URL relationship row last changed. For a
  Discogs link this is when the link was added, unless it was edited later (which moves the
  time forward) or removed (which drops the row).
- `release_meta.date_added`: when the release was added to MusicBrainz.

`core` keeps, for every relationship of the `discogs` release-URL type whose URL parses as
a Discogs release (the `musicbrainz-ingestion` rule, as in `extract_mb.py`), the release
id, the Discogs id, and `last_updated`. It also keeps the release's MBID and its release
group's MBID. `derived` keeps `release_meta.date_added` per release id. Tables arrive in
PostgreSQL `COPY` text format (tab-separated, `\\N` for NULL), with columns in the order of
MusicBrainz's `CreateTables.sql`. Only ids and timestamps are written, to the work
directory outside the repository.
"""

from __future__ import annotations

import sys
import tarfile
from datetime import UTC, datetime

import numpy as np

from extract_mb import extract_discogs_id


def _epoch(text: str) -> int:
    if text == "\\N":
        return 0
    moment = datetime.fromisoformat(text.replace(" ", "T", 1))
    return int((moment if moment.tzinfo else moment.replace(tzinfo=UTC)).timestamp())


def _rows(member_file):
    for raw in member_file:
        yield raw.decode("utf-8").rstrip("\n").split("\t")


def core(stream, out: str) -> None:
    link_type_id = None
    link_types: dict[int, int] = {}
    discogs_urls: dict[int, int] = {}
    l_release, l_url, l_link, l_time = [], [], [], []
    release_gid: dict[int, tuple[str, int]] = {}
    group_gid: dict[int, str] = {}
    with tarfile.open(fileobj=stream, mode="r|") as tar:
        for member in tar:
            name = member.name.rsplit("/", 1)[-1]
            if not member.isfile() or name not in {"link_type", "link", "url", "l_release_url", "release", "release_group"}:
                continue
            handle = tar.extractfile(member)
            if name == "link_type":
                # id, parent, child_order, gid, entity_type0, entity_type1, name, ...
                for cells in _rows(handle):
                    if cells[4] == "release" and cells[5] == "url" and cells[6] == "discogs":
                        link_type_id = int(cells[0])
            elif name == "link":
                # id, link_type, ...
                for cells in _rows(handle):
                    link_types[int(cells[0])] = int(cells[1])
            elif name == "url":
                # id, gid, url, edits_pending, last_updated
                for cells in _rows(handle):
                    found = extract_discogs_id(cells[2], "release")
                    if found is not None:
                        discogs_urls[int(cells[0])] = found
            elif name == "l_release_url":
                # id, link, entity0 (release), entity1 (url), edits_pending, last_updated, ...
                for cells in _rows(handle):
                    l_link.append(int(cells[1]))
                    l_release.append(int(cells[2]))
                    l_url.append(int(cells[3]))
                    l_time.append(_epoch(cells[5]))
            elif name == "release":
                # id, gid, name, artist_credit, release_group, ...
                for cells in _rows(handle):
                    release_gid[int(cells[0])] = (cells[1], int(cells[4]))
            elif name == "release_group":
                # id, gid, ...
                for cells in _rows(handle):
                    group_gid[int(cells[0])] = cells[1]
            print(f"{name} read", file=sys.stderr)
    if link_type_id is None:
        sys.exit("no discogs release-url link type")
    keep = [i for i in range(len(l_link)) if link_types.get(l_link[i]) == link_type_id and l_url[i] in discogs_urls]
    releases = [l_release[i] for i in keep]
    np.savez(
        out,
        release_id=np.asarray(releases, dtype=np.int64),
        discogs_id=np.asarray([discogs_urls[l_url[i]] for i in keep], dtype=np.int64),
        last_updated=np.asarray([l_time[i] for i in keep], dtype=np.int64),
        mbid=np.asarray([release_gid[r][0] for r in releases]),
        group_mbid=np.asarray([group_gid.get(release_gid[r][1], "") for r in releases]),
    )
    print(f"core: {len(keep)} discogs release links of {len(l_link)} release-url rows", file=sys.stderr)


def derived(stream, out: str) -> None:
    ids, added = [], []
    with tarfile.open(fileobj=stream, mode="r|") as tar:
        for member in tar:
            if member.isfile() and member.name.rsplit("/", 1)[-1] == "release_meta":
                # id, date_added, info_url, amazon_asin, ...
                for cells in _rows(tar.extractfile(member)):
                    ids.append(int(cells[0]))
                    added.append(_epoch(cells[1]))
    if not ids:
        sys.exit("no release_meta rows")
    np.savez(out, release_id=np.asarray(ids, dtype=np.int64), date_added=np.asarray(added, dtype=np.int64))
    print(f"derived: {len(ids)} release_meta rows", file=sys.stderr)


if __name__ == "__main__":
    {"core": core, "derived": derived}[sys.argv[1]](sys.stdin.buffer, sys.argv[2])
