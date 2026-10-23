#!/usr/bin/env python3
"""Stream a Discogs releases or masters XML dump from stdin into compact arrays.

Only the fields this spike measures are kept, as integer arrays in one ``.npz`` per
dump and kind, plus a ``vocab.json`` of the genre and style names seen:

- ``id``: the entity id (int64), used only to join releases to masters inside the cache;
- ``year``: release year from ``<released>`` (releases) or ``<year>`` (masters), 0 if absent
  or outside 1860..2030;
- ``master``: a release's ``<master_id>`` (0 if none); masters store 0;
- ``genre_mask``: one bit per genre index (Discogs has 15 genres; 32 bits is checked);
- ``style_ptr`` / ``style_idx``: CSR list of style indices;
- ``artist_ptr`` / ``artist_ids``: CSR list of the main ``<artists>`` ids (never
  ``extraartists``), the ``by_artist`` relation the FastRP graph reads;
- ``label_ptr`` / ``label_ids``: CSR list of label ids (releases only).

The dump is never written to disk. ``recover=True`` closes a truncated document on its
own, so the raw bytes must end in the closing root tag or the run fails.

Usage:
    gzip -dc discogs_20261001_masters.xml.gz | python extract_dump.py masters OUT.npz
    curl -sL <releases url> | gzip -dc | python extract_dump.py releases OUT.npz
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from array import array
from pathlib import Path

import numpy as np
from lxml import etree


class TailReader:
    """File-like wrapper that counts bytes and keeps the last few, so the caller can
    check that the stream really ended at the closing root tag."""

    def __init__(self, raw):
        self.raw, self.total, self.tail = raw, 0, b""

    def read(self, n: int = -1) -> bytes:
        chunk = self.raw.read(n)
        self.total += len(chunk)
        if chunk:
            self.tail = (self.tail + chunk)[-64:]
        return chunk


def parse_year(text: str | None) -> int:
    if not text or len(text) < 4 or not text[:4].isdigit():
        return 0
    year = int(text[:4])
    return year if 1860 <= year <= 2030 else 0


def parse_int(text: str | None) -> int:
    text = (text or "").strip()
    return int(text) if text.isdigit() else 0


class Vocab:
    def __init__(self, names: list[str] | None = None):
        self.names: list[str] = list(names or [])
        self.index = {n: i for i, n in enumerate(self.names)}

    def get(self, name: str) -> int:
        i = self.index.get(name)
        if i is None:
            i = self.index[name] = len(self.names)
            self.names.append(name)
        return i


class Columns:
    def __init__(self):
        self.id = array("q")
        self.year = array("h")
        self.master = array("q")
        self.genre_mask = array("I")
        self.style_ptr, self.style_idx = array("q", [0]), array("H")
        self.artist_ptr, self.artist_ids = array("q", [0]), array("q")
        self.label_ptr, self.label_ids = array("q", [0]), array("q")

    def save(self, path: Path) -> None:
        # Compressed: the shared spike disk is tight (a raw releases npz is ~1.3 GB).
        np.savez_compressed(
            path,
            **{k: np.frombuffer(v, dtype=v.typecode) for k, v in vars(self).items()},
        )


def record(el, kind: str, cols: Columns, genres: Vocab, styles: Vocab) -> None:
    cols.id.append(parse_int(el.get("id")))
    if kind == "releases":
        cols.year.append(parse_year(el.findtext("released")))
        cols.master.append(parse_int(el.findtext("master_id")))
        cols.label_ids.extend(
            v for v in (parse_int(lb.get("id")) for lb in el.findall("labels/label")) if v
        )
    else:
        cols.year.append(parse_year(el.findtext("year")))
        cols.master.append(0)
    cols.label_ptr.append(len(cols.label_ids))
    mask = 0
    for g in el.findall("genres/genre"):
        if g.text:
            bit = genres.get(g.text)
            if bit >= 32:
                raise SystemExit("more than 32 genres; widen genre_mask")
            mask |= 1 << bit
    cols.genre_mask.append(mask)
    seen = set()
    for s in el.findall("styles/style"):
        if s.text and s.text not in seen:
            seen.add(s.text)
            cols.style_idx.append(styles.get(s.text))
    cols.style_ptr.append(len(cols.style_idx))
    cols.artist_ids.extend(
        v for v in (parse_int(a.findtext("id")) for a in el.findall("artists/artist")) if v
    )
    cols.artist_ptr.append(len(cols.artist_ids))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["releases", "masters"])
    ap.add_argument("out", type=Path)
    ap.add_argument("--max-scan", type=int, default=0, help="0 = whole dump")
    args = ap.parse_args()
    tag = args.kind[:-1]
    genres, styles, cols = Vocab(), Vocab(), Columns()
    stats = {"scanned": 0, "status": {}}
    started = time.time()
    source = TailReader(sys.stdin.buffer)
    context = etree.iterparse(source, events=("end",), tag=tag, recover=True, huge_tree=True)
    for _, el in context:
        parent = el.getparent()
        if parent is None or parent.tag != args.kind:
            continue
        stats["scanned"] += 1
        status = el.get("status") or ""
        stats["status"][status] = stats["status"].get(status, 0) + 1
        record(el, args.kind, cols, genres, styles)
        el.clear()
        while el.getprevious() is not None:
            del parent[0]
        if stats["scanned"] % 1_000_000 == 0:
            rate = stats["scanned"] / (time.time() - started)
            print(f"...{stats['scanned']} {rate:.0f} rec/s", file=sys.stderr, flush=True)
        if args.max_scan and stats["scanned"] >= args.max_scan:
            break
    if not args.max_scan:
        source.read(-1)
    stats["seconds"] = round(time.time() - started)
    stats["bytes"] = source.total
    stats["complete"] = bool(args.max_scan) or source.tail.rstrip().endswith(f"</{args.kind}>".encode())
    print(f"DONE {json.dumps(stats)}", file=sys.stderr)
    if not stats["complete"]:
        sys.exit(f"stream ended before </{args.kind}>: the arrays are truncated")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    part = args.out.with_suffix(".part.npz")
    cols.save(part)
    part.rename(args.out)
    args.out.with_suffix(".vocab.json").write_text(
        json.dumps({"genres": genres.names, "styles": styles.names, "stats": stats}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
