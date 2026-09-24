# SPDX-License-Identifier: MIT
"""Pass 1: stream the Discogs releases dump into compact integer arrays.

The gzip is decompressed as a stream and never written to disk. The main process cuts the
stream into whole ``<release>`` chunks; a small worker pool parses each chunk with lxml and
returns only integer ids and short vocab strings. Nothing textual (titles, names, notes)
leaves the workers.

Output (one directory, ``.npy`` files, uncompressed, outside the repository):

* ``rel_id``, ``rel_date`` (yyyymmdd, 0 if no usable year; month/day 0 when unknown),
  ``rel_master``, ``rel_fam`` (bitmask over ``common.media.family_ids()``)
* CSR lists ``<name>_ptr`` / ``<name>_val`` for ``artists`` (release main artists, the
  ``BY`` edge), ``credits`` (release and track extraartists with a kept role category),
  ``trackartists``, ``labels``, ``genres``, ``styles`` (vocab ids)
* ``vocab.json`` for genres and styles
"""

from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

import numpy as np

# Placeholder artists that are not artists: Various, Unknown Artist, No Artist, Traditional.
PLACEHOLDER_ARTISTS = frozenset({194, 355, 118760, 151641})

# Credit categories (common.credit_roles) that say something about musical similarity.
# Mastering, design, and management credits are dropped: a cutting engineer or sleeve
# photographer links releases by vendor, not by sound.
KEPT_CREDIT_CATEGORIES = frozenset({"production", "engineering", "session", "other"})

CHUNK_BYTES = 16 << 20


def _date(text: str | None) -> int:
    if not text:
        return 0
    parts = text.strip().split("-")
    try:
        year = int(parts[0])
    except ValueError:
        return 0
    if not 1860 <= year <= 2026:
        return 0
    month = day = 0
    try:
        if len(parts) > 1:
            month = int(parts[1])
        if len(parts) > 2:
            day = int(parts[2])
    except ValueError:
        month = day = 0
    if not 0 <= month <= 12:
        month = 0
    if not 0 <= day <= 31:
        day = 0
    return year * 10000 + month * 100 + day


def _ids(elements, role_ok=None) -> list[int]:
    out = []
    for artist in elements:
        raw = artist.findtext("id")
        if not raw:
            continue
        try:
            aid = int(raw)
        except ValueError:
            continue
        if aid in PLACEHOLDER_ARTISTS or aid <= 0:
            continue
        if role_ok is not None and not role_ok(artist.findtext("role") or ""):
            continue
        out.append(aid)
    return out


def _worker_init() -> None:
    global _FAMILY_BITS, _map, _families_of, _categorize
    from common.credit_roles import categorize_role
    from common.media import families_of, family_ids, map_discogs_formats

    _FAMILY_BITS = {family: 1 << index for index, family in enumerate(family_ids())}
    _map, _families_of, _categorize = map_discogs_formats, families_of, categorize_role


def _role_ok(role: str) -> bool:
    # A role string can hold several comma-separated roles; keep the credit if any kept
    # category appears among them.
    return any(_categorize(part) in KEPT_CREDIT_CATEGORIES for part in role.split(",") if part.strip())


def _parse_chunk(chunk: bytes) -> dict:
    from lxml import etree

    root = etree.fromstring(b"<r>" + chunk + b"</r>", parser=etree.XMLParser(huge_tree=True, recover=True))
    rows = []
    for rel in root.iterchildren("release"):
        try:
            rid = int(rel.get("id"))
        except (TypeError, ValueError):
            continue
        artists = _ids(rel.iterfind("artists/artist"))
        credits = _ids(rel.iterfind("extraartists/artist"), _role_ok)
        credits += _ids(rel.iterfind("tracklist/track/extraartists/artist"), _role_ok)
        credits += _ids(rel.iterfind("tracklist/track/sub_tracks/track/extraartists/artist"), _role_ok)
        track_artists = _ids(rel.iterfind("tracklist/track/artists/artist"))
        labels = []
        for label in rel.iterfind("labels/label"):
            try:
                labels.append(int(label.get("id")))
            except (TypeError, ValueError):
                pass
        formats = []
        for fmt in rel.iterfind("formats/format"):
            formats.append(
                {
                    "name": fmt.get("name"),
                    "qty": fmt.get("qty"),
                    "text": fmt.get("text"),
                    "descriptions": [d.text for d in fmt.iterfind("descriptions/description") if d.text],
                }
            )
        fam = 0
        for family in _families_of(_map(formats)):
            fam |= _FAMILY_BITS.get(family, 0)
        master = rel.findtext("master_id")
        rows.append(
            (
                rid,
                _date(rel.findtext("released")),
                int(master) if master and master.isdigit() else 0,
                fam,
                sorted(set(artists)),
                sorted(set(credits) - set(artists)),
                sorted(set(track_artists) - set(artists)),
                sorted(set(labels)),
                sorted({g.text for g in rel.iterfind("genres/genre") if g.text}),
                sorted({s.text for s in rel.iterfind("styles/style") if s.text}),
            )
        )
    return rows


def _chunks(path: Path):
    tail = b""
    with gzip.open(path, "rb") as stream:
        first = True
        while True:
            block = stream.read(CHUNK_BYTES)
            if not block:
                break
            data = tail + block
            if first:
                data = data[data.index(b"<release ") :]
                first = False
            cut = data.rfind(b"</release>")
            if cut < 0:
                tail = data
                continue
            cut += len(b"</release>")
            yield data[:cut]
            tail = data[cut:]
    rest = tail.replace(b"</releases>", b"").strip()
    if rest:
        yield rest


LISTS = ("artists", "credits", "trackartists", "labels", "genres", "styles")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dump", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--limit-chunks", type=int, default=0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    vocab = {"genres": {}, "styles": {}}
    scalars = {"rel_id": [], "rel_date": [], "rel_master": [], "rel_fam": []}
    lists = {name: ([], []) for name in LISTS}  # (lengths, values) per chunk
    started = time.time()
    count = 0
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers, initializer=_worker_init) as pool:
        source = _chunks(args.dump)
        if args.limit_chunks:
            source = (c for i, c in zip(range(args.limit_chunks), source))
        for rows in pool.imap(_parse_chunk, source, chunksize=1):
            n = len(rows)
            count += n
            scalars["rel_id"].append(np.fromiter((r[0] for r in rows), np.int32, n))
            scalars["rel_date"].append(np.fromiter((r[1] for r in rows), np.int32, n))
            scalars["rel_master"].append(np.fromiter((r[2] for r in rows), np.int32, n))
            scalars["rel_fam"].append(np.fromiter((r[3] for r in rows), np.int16, n))
            for offset, name in enumerate(LISTS, start=4):
                if name in vocab:
                    table = vocab[name]
                    values = [table.setdefault(v, len(table)) for r in rows for v in r[offset]]
                    dtype = np.int16
                else:
                    values = [v for r in rows for v in r[offset]]
                    dtype = np.int32
                lists[name][0].append(np.fromiter((len(r[offset]) for r in rows), np.int32, n))
                lists[name][1].append(np.asarray(values, dtype=dtype))
            if len(scalars["rel_id"]) % 50 == 0:
                rate = count / (time.time() - started)
                print(f"{count:,} releases, {rate:,.0f}/s", file=sys.stderr, flush=True)

    for name, parts in scalars.items():
        np.save(args.out / f"{name}.npy", np.concatenate(parts))
    for name, (lengths, values) in lists.items():
        ptr = np.zeros(count + 1, dtype=np.int64)
        np.cumsum(np.concatenate(lengths), out=ptr[1:])
        np.save(args.out / f"{name}_ptr.npy", ptr)
        np.save(args.out / f"{name}_val.npy", np.concatenate(values))
    (args.out / "vocab.json").write_text(json.dumps({k: sorted(v, key=v.get) for k, v in vocab.items()}))
    elapsed = time.time() - started
    print(json.dumps({"releases": count, "seconds": round(elapsed, 1), "pid": os.getpid()}))


if __name__ == "__main__":
    main()
