#!/usr/bin/env python3
"""Stream the MusicBrainz release JSON dump from stdin and keep releases that carry a
Discogs URL relation, as compact query records.

The dump is never written to disk: curl, xz and tar are piped into this process and
it stops after ``--max-scan`` dump lines (a dump-order prefix; see the report for the
bias this introduces). The Discogs relation is the held-out label; everything else in
the record is what a matcher is allowed to see.

Usage:
    curl -s <json-dumps/.../release.tar.xz> | xz -dc | tar -xf - -O mbdump/release \
        | python3 extract_mb_releases.py --max-scan 600000 > mb_linked.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys

DISCOGS_URL = re.compile(r"discogs\.com/(release|master|artist|label)/(\d+)")


def compact(d: dict) -> dict:
    releases, masters, others = [], [], []
    for rel in d.get("relations") or []:
        if rel.get("type") != "discogs":
            continue
        m = DISCOGS_URL.search((rel.get("url") or {}).get("resource") or "")
        if not m:
            others.append((rel.get("url") or {}).get("resource"))
        elif m.group(1) == "release":
            releases.append(m.group(2))
        elif m.group(1) == "master":
            masters.append(m.group(2))
        else:
            others.append(m.group(0))
    credit = d.get("artist-credit") or []
    rg = d.get("release-group") or {}
    return {
        "source": "musicbrainz",
        "entity_kind": "release",
        "native_id": d["id"],
        "title": d.get("title") or "",
        "artists": [c.get("name") or (c.get("artist") or {}).get("name") or "" for c in credit],
        "artist_ids": [(c.get("artist") or {}).get("id") for c in credit],
        "artist_display": "".join((c.get("name") or "") + (c.get("joinphrase") or "") for c in credit),
        "barcode": d.get("barcode") or None,
        "labels": [
            {
                "name": (li.get("label") or {}).get("name"),
                "catno": li.get("catalog-number"),
                "mbid": (li.get("label") or {}).get("id"),
            }
            for li in d.get("label-info") or []
        ],
        "date": d.get("date") or None,
        "country": d.get("country") or None,
        "formats": [m.get("format") for m in d.get("media") or []],
        "status": d.get("status"),
        "release_group": {"id": rg.get("id"), "primary_type": rg.get("primary-type")},
        "discogs_release_ids": sorted(set(releases)),
        "discogs_master_links": sorted(set(masters)),
        "discogs_other_links": others,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-scan", type=int, required=True)
    args = ap.parse_args()
    stats = {"scanned": 0, "with_discogs_relation": 0, "release_links": 0, "multi_release_links": 0,
             "master_links_on_release": 0, "barcode_present": 0, "catno_present": 0}
    out = sys.stdout
    for line in sys.stdin:
        stats["scanned"] += 1
        if stats["scanned"] > args.max_scan:
            stats["scanned"] -= 1
            break
        if "discogs.com/" not in line:
            continue
        rec = compact(json.loads(line))
        if not (rec["discogs_release_ids"] or rec["discogs_master_links"] or rec["discogs_other_links"]):
            continue
        stats["with_discogs_relation"] += 1
        if rec["discogs_release_ids"]:
            stats["release_links"] += 1
        if len(rec["discogs_release_ids"]) > 1:
            stats["multi_release_links"] += 1
        if rec["discogs_master_links"]:
            stats["master_links_on_release"] += 1
        if rec["barcode"]:
            stats["barcode_present"] += 1
        if any(li.get("catno") for li in rec["labels"]):
            stats["catno_present"] += 1
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if stats["scanned"] % 100000 == 0:
            print(f"...{stats}", file=sys.stderr)
    print(f"DONE {json.dumps(stats)}", file=sys.stderr)


if __name__ == "__main__":
    main()
