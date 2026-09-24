#!/usr/bin/env python3
"""Stream a MusicBrainz JSON dump (artist or label) and extract entities that
carry a Discogs URL relationship. Never writes the decompressed dump to disk:
curl and tar are piped directly into this process's stdin.

Usage:
    curl -sL <artist.tar.xz url> | tar -xJf - -O mbdump/artist \
        | python3 extract_mb_ground_truth.py artist > artists_linked.jsonl
"""
from __future__ import annotations

import json
import re
import sys

DISCOGS_RE = re.compile(r"discogs\.com/(?:[a-z]{2}/)?(artist|label)/(\d+)")


def extract_discogs_id(entity: dict, expected_kind: str) -> tuple[str, str] | None:
    for rel in entity.get("relations") or []:
        if rel.get("type") != "discogs":
            continue
        url = (rel.get("url") or {}).get("resource", "")
        m = DISCOGS_RE.search(url)
        if m and m.group(1) == expected_kind:
            return m.group(2), url
    return None


def main() -> None:
    kind = sys.argv[1]  # "artist" or "label"
    total = 0
    matched = 0
    out = sys.stdout
    for line in sys.stdin.buffer:
        total += 1
        line = line.strip()
        if not line:
            continue
        try:
            entity = json.loads(line)
        except json.JSONDecodeError:
            continue
        hit = extract_discogs_id(entity, kind)
        if hit is None:
            continue
        discogs_id, discogs_url = hit
        matched += 1
        record = {
            "mbid": entity.get("id"),
            "kind": kind,
            "name": entity.get("name"),
            "sort_name": entity.get("sort-name"),
            "disambiguation": entity.get("disambiguation") or "",
            "country": entity.get("country"),
            "area_name": (entity.get("area") or {}).get("name"),
            "aliases": [a.get("name") for a in (entity.get("aliases") or []) if a.get("name")],
            "life_span_begin": (entity.get("life-span") or {}).get("begin"),
            "discogs_id": discogs_id,
            "discogs_url": discogs_url,
        }
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
        if total % 200000 == 0:
            print(f"...scanned {total} {kind} entities, matched {matched}", file=sys.stderr)
    print(f"DONE kind={kind} total_scanned={total} matched_with_discogs={matched}", file=sys.stderr)


if __name__ == "__main__":
    main()
