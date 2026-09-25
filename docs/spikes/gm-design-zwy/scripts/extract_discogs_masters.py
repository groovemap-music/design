#!/usr/bin/env python3
"""Stream the Discogs masters XML dump and keep masters that are release-vs-master hard
negatives for the sampled queries: the master of any pooled release, and any master
whose title shares a blocking key with a query. They enter the candidate pool with
``entity_kind='master'``, so a matcher that ignores entity kind can wrongly rank a
master above the correct release.

Usage:
    gzip -dc discogs_YYYYMMDD_masters.xml.gz \
        | python3 extract_discogs_masters.py blocking_keys.json pool_releases.jsonl.gz pool_masters.jsonl.gz
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys

from lxml import etree

from normalize import title_key


def text_of(el, tag: str) -> str | None:
    child = el.find(tag)
    return child.text if child is not None else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("blocking_keys")
    ap.add_argument("pool_releases")
    ap.add_argument("out")
    args = ap.parse_args()
    with open(args.blocking_keys) as f:
        titles = set(json.load(f)["titles"])
    wanted_masters: set[str] = set()
    with gzip.open(args.pool_releases, "rt") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("master_id") and set(rec["kept_reasons"]) - {"background"}:
                wanted_masters.add(rec["master_id"])

    stats = {"scanned": 0, "kept": 0, "master_of_pooled_release": 0, "title": 0}
    context = etree.iterparse(sys.stdin.buffer, events=("end",), tag="master", recover=True, huge_tree=True)
    with gzip.open(args.out, "wt", compresslevel=5) as out:
        for _, el in context:
            stats["scanned"] += 1
            mid = el.get("id")
            title = text_of(el, "title") or ""
            reasons = []
            if mid in wanted_masters:
                reasons.append("master_of_pooled_release")
            if title_key(title) in titles:
                reasons.append("title")
            if reasons:
                rec = {
                    "source": "discogs",
                    "entity_kind": "master",
                    "native_id": mid,
                    "title": title,
                    "artists": [
                        {"id": text_of(a, "id"), "name": text_of(a, "name"), "anv": text_of(a, "anv"),
                         "join": text_of(a, "join")}
                        for a in el.findall("artists/artist")
                    ],
                    "labels": [],
                    "formats": [],
                    "country": None,
                    "released": text_of(el, "year"),
                    "master_id": mid,
                    "main_release": text_of(el, "main_release"),
                    "barcodes": [],
                    "kept_reasons": reasons,
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stats["kept"] += 1
                for r in reasons:
                    stats[r] += 1
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
    stats["wanted_masters"] = len(wanted_masters)
    print(f"DONE {json.dumps(stats)}", file=sys.stderr)


if __name__ == "__main__":
    main()
