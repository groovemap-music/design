#!/usr/bin/env python3
"""Stream one whole MusicBrainz release JSON dump from stdin and write one compact
record per release.

The time-split needs two snapshots of the same releases: the earlier dump says which
releases had no Discogs release relation, the later dump says which of them gained one,
and the earlier record is what a matcher would have seen while the release was still
unlinked. Unlike gm-design-zwy's ``extract_mb_releases.py`` (a dump-order prefix of
linked releases only), this reads the whole dump and keeps every release, linked or
not, so both populations can be counted.

The dump is never written to disk: curl, xz and tar pipe into this process, and only
the compact records (gzip JSONL, no tracklists) are kept, outside the repository.

Usage:
    curl -s <json-dumps/YYYYMMDD-HHMMSS/release.tar.xz> | xz -dc | tar -xf - -O mbdump/release \
        | python3 extract_mb_snapshot.py snapshot_YYYYMMDD.jsonl.gz
"""
from __future__ import annotations

import argparse
import gzip
import sys
import time

import orjson

from mb_record import compact


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--max-scan", type=int, default=0, help="0 = whole dump")
    args = ap.parse_args()
    stats = {"scanned": 0, "with_discogs_release_link": 0, "multi_discogs_release_link": 0,
             "discogs_master_link_only": 0, "parse_errors": 0}
    started = time.time()
    with gzip.open(args.out, "wb", compresslevel=3) as out:
        for line in sys.stdin.buffer:
            try:
                rec = compact(orjson.loads(line))
            except orjson.JSONDecodeError:
                stats["parse_errors"] += 1
                continue
            stats["scanned"] += 1
            if rec["discogs_release_ids"]:
                stats["with_discogs_release_link"] += 1
                if len(rec["discogs_release_ids"]) > 1:
                    stats["multi_discogs_release_link"] += 1
            elif rec["discogs_master_links"]:
                stats["discogs_master_link_only"] += 1
            out.write(orjson.dumps(rec) + b"\n")
            if stats["scanned"] % 250000 == 0:
                rate = stats["scanned"] / (time.time() - started)
                print(f"...{orjson.dumps(stats).decode()} {rate:.0f} rec/s", file=sys.stderr, flush=True)
            if args.max_scan and stats["scanned"] >= args.max_scan:
                break
    stats["seconds"] = round(time.time() - started)
    print(f"DONE {orjson.dumps(stats).decode()}", file=sys.stderr)


if __name__ == "__main__":
    main()
