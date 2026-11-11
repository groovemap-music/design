#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Regenerate taxonomy/mb-tag-genre/v1/discogs-genre-tree.json from one named Discogs dump.

The tree is built from the masters and releases files of the same dump. Each file is read as a
stream (the gzip is decompressed in memory, never written to disk) and its SHA-256 is computed over
the compressed bytes while it streams. There is no network access in this script and no model call:
the inputs are paths, and a path may be a pipe such as ``<(curl -fsS URL)``.

Rule (ADR 0020, the same rule as analytics-engine insights.style_parents): a style's parents are
the genres carried by at least SHARE of the style's records. The dominant parent is always kept.
Junk genres are dropped. Output is deterministic: no timestamps, sorted keys and lists.

Usage:
    scripts/discogs-genre-tree.py --dump-date 20261101 \\
        --masters discogs_20261101_masters.xml.gz --releases <(curl -fsS .../discogs_20261101_releases.xml.gz) \\
        --out taxonomy/mb-tag-genre/v1/discogs-genre-tree.json
"""

import argparse
import gzip
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

SHARE_NUMERATOR = 1
SHARE_DENOMINATOR = 5  # share >= 0.20, compared in integers so there is no float drift
JUNK_GENRES = ("1",)
MAX_CHILDREN = 255
RECORD_TAGS = {"masters": "master", "releases": "release"}


class HashingReader:
    """File-like wrapper that hashes the raw (compressed) bytes as they are read."""

    def __init__(self, raw):
        self.raw = raw
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        chunk = self.raw.read(size)
        self.digest.update(chunk)
        return chunk


def count_stream(path, record_tag, junk=JUNK_GENRES):
    """Stream one gzip XML dump; return (sha256, records, genre, style and pair counters)."""
    genre_records, style_records, pairs = Counter(), Counter(), Counter()
    records = 0
    with open(path, "rb") as raw:
        hashed = HashingReader(raw)
        with gzip.GzipFile(fileobj=hashed) as xml:
            root = None
            for event, elem in ET.iterparse(xml, events=("start", "end")):  # noqa: S314 (public dump, own pipeline)
                if root is None:
                    root = elem  # first start event is the document root
                if event != "end" or elem.tag != record_tag:
                    continue
                records += 1
                genres = sorted({g.text for g in elem.iterfind("genres/genre") if g.text and g.text not in junk})
                styles = sorted({s.text for s in elem.iterfind("styles/style") if s.text})
                genre_records.update(genres)
                style_records.update(styles)
                for genre in genres:
                    for style in styles:
                        pairs[genre, style] += 1
                elem.clear()
                root.clear()  # drop the emptied record from the root so memory stays flat
        # drain so the hash covers trailing bytes past the gzip member
        while hashed.read(1 << 20):
            pass
    return hashed.digest.hexdigest(), records, genre_records, style_records, pairs


def build_tree(dump_date, inputs, genre_records, style_records, pairs, junk=JUNK_GENRES):
    by_style = defaultdict(dict)
    for (genre, style), n in pairs.items():
        by_style[style][genre] = n
    children = defaultdict(list)
    multi_parent = 0
    for style, per_genre in by_style.items():
        total = style_records[style]
        parents = sorted(
            genre for genre, n in per_genre.items() if n * SHARE_DENOMINATOR >= total * SHARE_NUMERATOR
        ) or [max(sorted(per_genre), key=per_genre.__getitem__)]
        multi_parent += len(parents) > 1
        for genre in parents:
            children[genre].append({"style": style, "records": total, "genre_records": per_genre[genre]})
    genres = []
    for genre in sorted(children):
        ordered = sorted(children[genre], key=lambda c: (-c["records"], c["style"]))
        genres.append({"genre": genre, "records": genre_records[genre], "children": ordered})
    return {
        "tree_version": "1",
        "license": "MIT",
        "source": {
            "name": "Discogs monthly data dump",
            "url": "https://data.discogs.com/",
            "license": "CC0-1.0",
            "dump_date": dump_date,
            "inputs": inputs,
        },
        "rule": {
            "description": (
                "A style's parents are the genres carried by at least share_threshold of the style's records "
                "(masters plus releases). The dominant parent is always kept. Junk genres are dropped."
            ),
            "share_threshold": "0.20",
            "dominant_parent_always_kept": True,
            "dropped_genres": list(junk),
            "max_children_per_genre": MAX_CHILDREN,
        },
        "counts": {
            "genres": len(genres),
            "styles": len(by_style),
            "pairs": sum(len(g["children"]) for g in genres),
            "styles_with_2plus_parents": multi_parent,
            "max_children": max((len(g["children"]) for g in genres), default=0),
        },
        "genres": genres,
    }


def render(tree):
    return json.dumps(tree, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dump-date", required=True, help="Discogs dump date, YYYYMMDD")
    parser.add_argument("--masters", required=True, help="path to discogs_<date>_masters.xml.gz (may be a pipe)")
    parser.add_argument("--releases", required=True, help="path to discogs_<date>_releases.xml.gz (may be a pipe)")
    parser.add_argument("--out", required=True, help="output tree JSON")
    args = parser.parse_args(argv)

    genre_records, style_records, pairs = Counter(), Counter(), Counter()
    inputs = []
    for kind in ("masters", "releases"):
        sha, records, g, s, p = count_stream(getattr(args, kind), RECORD_TAGS[kind])
        genre_records.update(g)
        style_records.update(s)
        pairs.update(p)
        inputs.append({"file": f"discogs_{args.dump_date}_{kind}.xml.gz", "kind": kind, "records": records, "sha256": sha})
        print(f"{kind}: {records} records, sha256 {sha}", file=sys.stderr)
    tree = build_tree(args.dump_date, inputs, genre_records, style_records, pairs)
    Path(args.out).write_text(render(tree), encoding="utf-8")
    print(json.dumps(tree["counts"], indent=1), file=sys.stderr)


if __name__ == "__main__":
    main()
