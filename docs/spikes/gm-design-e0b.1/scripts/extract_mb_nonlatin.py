#!/usr/bin/env python3
"""Stream a MusicBrainz JSON dump (artist or label) once and, in the same
pass: (a) tally script buckets and Discogs-link status for every entity, so
the "how many unlinked non-Latin MB entities exist" figure the epic asks for
comes from a real full scan, not an estimate; and (b) emit ground-truth JSONL
rows only for entities that are BOTH non-Latin-script AND already linked to
Discogs (the query population this spike scores against).

Never writes the decompressed dump to disk: curl and tar are piped directly
into this process's stdin (matches gm-design-chw.3's method).

Usage:
    curl -sL <artist.tar.xz url> | tar -xJf - -O mbdump/artist \
        | python3 extract_mb_nonlatin.py artist linked_nonlatin_artists.jsonl > summary_artist.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

from script_util import script_of

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
    out_path = sys.argv[2]

    total = 0
    script_counts: Counter[str] = Counter()
    script_linked_counts: Counter[str] = Counter()
    total_linked = 0
    kept = 0

    with open(out_path, "w") as out:
        for line in sys.stdin.buffer:
            total += 1
            line = line.strip()
            if not line:
                continue
            try:
                entity = json.loads(line)
            except json.JSONDecodeError:
                continue

            name = entity.get("name") or ""
            script = script_of(name)
            script_counts[script] += 1

            hit = extract_discogs_id(entity, kind)
            is_linked = hit is not None
            if is_linked:
                total_linked += 1
                script_linked_counts[script] += 1

            if is_linked and script not in ("latin", "unknown"):
                discogs_id, discogs_url = hit
                kept += 1
                record = {
                    "mbid": entity.get("id"),
                    "kind": kind,
                    "name": name,
                    "sort_name": entity.get("sort-name"),
                    "disambiguation": entity.get("disambiguation") or "",
                    "country": entity.get("country"),
                    "area_name": (entity.get("area") or {}).get("name"),
                    "aliases": [a.get("name") for a in (entity.get("aliases") or []) if a.get("name")],
                    "life_span_begin": (entity.get("life-span") or {}).get("begin"),
                    "discogs_id": discogs_id,
                    "discogs_url": discogs_url,
                    "script": script,
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")

            if total % 200000 == 0:
                print(f"...scanned {total} {kind} entities, linked={total_linked}, kept_nonlatin_linked={kept}", file=sys.stderr)

    non_latin_total = sum(v for k, v in script_counts.items() if k not in ("latin", "unknown"))
    non_latin_linked = sum(v for k, v in script_linked_counts.items() if k not in ("latin", "unknown"))
    summary = {
        "kind": kind,
        "total_scanned": total,
        "total_linked_to_discogs": total_linked,
        "script_counts": dict(script_counts),
        "script_linked_counts": dict(script_linked_counts),
        "non_latin_total": non_latin_total,
        "non_latin_linked": non_latin_linked,
        "non_latin_unlinked": non_latin_total - non_latin_linked,
        "kept_query_candidates": kept,
    }
    print(json.dumps(summary, indent=2))
    print(f"DONE kind={kind} {summary}", file=sys.stderr)


if __name__ == "__main__":
    main()
