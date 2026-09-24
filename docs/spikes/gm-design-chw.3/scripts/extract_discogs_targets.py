#!/usr/bin/env python3
"""Stream a Discogs XML dump (artists.xml.gz or labels.xml.gz) and pull out
only the records whose numeric id is in a ground-truth target set built from
the MusicBrainz side. Never writes the decompressed dump to disk: curl and
gunzip are piped directly into this process's stdin, and lxml.etree.iterparse
processes one <artist>/<label> element at a time, clearing each as it goes so
memory stays bounded regardless of corpus size (Discogs ships ~9M artists).

Usage:
    curl -sL <artists.xml.gz url> | gunzip -c \
        | python3 extract_discogs_targets.py artist targets.json > artists_matched.jsonl
"""
from __future__ import annotations

import json
import sys

from lxml import etree


def load_targets(path: str) -> set[str]:
    with open(path) as f:
        return set(json.load(f))


def text_of(el, tag: str) -> str | None:
    child = el.find(tag)
    return child.text if child is not None else None


def main() -> None:
    kind = sys.argv[1]  # "artist" or "label"
    targets_path = sys.argv[2]
    targets = load_targets(targets_path)
    found = 0
    scanned = 0
    context = etree.iterparse(sys.stdin.buffer, events=("end",), tag=kind, recover=True)
    out = sys.stdout
    for _, el in context:
        scanned += 1
        disc_id = text_of(el, "id")
        if disc_id in targets:
            found += 1
            record = {
                "discogs_id": disc_id,
                "kind": kind,
                "name": text_of(el, "name"),
                "realname": text_of(el, "realname") if kind == "artist" else None,
                "namevariations": [n.text for n in el.findall("namevariations/name") if n.text],
                "aliases": [n.text for n in el.findall("aliases/name") if n.text],
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
        # free memory: clear this element and drop earlier siblings
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]
        if scanned % 500000 == 0:
            print(f"...scanned {scanned} {kind} records, matched {found}/{len(targets)}", file=sys.stderr)
        if found == len(targets):
            print(f"all targets found early at scanned={scanned}", file=sys.stderr)
            break
    print(f"DONE kind={kind} scanned={scanned} matched={found} targets={len(targets)}", file=sys.stderr)


if __name__ == "__main__":
    main()
