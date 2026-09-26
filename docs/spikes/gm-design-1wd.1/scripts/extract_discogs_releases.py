#!/usr/bin/env python3
"""Stream the Discogs releases XML dump from stdin and keep the bounded candidate pool.

A release is kept when any of these holds, and the reasons are recorded on it:

- ``target``: its id is the held-out Discogs side of a sampled MusicBrainz query;
- ``barcode`` / ``catno`` / ``title``: it shares a blocking key with any sampled query
  (so every Discogs release in the *full* corpus that a keyed blocker could surface is
  in the pool, and blocking coverage and review burden reflect the full corpus);
- ``background``: a deterministic 1-in-``--background-mod`` sample by id, used as
  unkeyed distractors for methods that scan rather than block.

The dump is never written to disk: curl and gunzip pipe into ``lxml.etree.iterparse``,
which clears each element as it is read. Output is gzip JSONL.

Usage:
    curl -sL <discogs_YYYYMMDD_releases.xml.gz url> | gzip -dc \
        | python3 extract_discogs_releases.py blocking_keys.json pool_releases.jsonl.gz
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time

from lxml import etree

from normalize import barcode_key, catno_key, title_key


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


def text_of(el, tag: str) -> str | None:
    child = el.find(tag)
    return child.text if child is not None else None


def compact(el) -> dict:
    master = el.find("master_id")
    return {
        "source": "discogs",
        "entity_kind": "release",
        "native_id": el.get("id"),
        "status": el.get("status"),
        "title": text_of(el, "title") or "",
        "artists": [
            {"id": text_of(a, "id"), "name": text_of(a, "name"), "anv": text_of(a, "anv"), "join": text_of(a, "join")}
            for a in el.findall("artists/artist")
        ],
        "labels": [
            {"id": lb.get("id"), "name": lb.get("name"), "catno": lb.get("catno")}
            for lb in el.findall("labels/label")
        ],
        "formats": [
            {
                "name": fm.get("name"),
                "qty": fm.get("qty"),
                "descriptions": [d.text for d in fm.findall("descriptions/description") if d.text],
            }
            for fm in el.findall("formats/format")
        ],
        "country": text_of(el, "country"),
        "released": text_of(el, "released"),
        "master_id": master.text if master is not None else None,
        "is_main_release": master is not None and master.get("is_main_release") == "true",
        "barcodes": [
            i.get("value")
            for i in el.findall("identifiers/identifier")
            if (i.get("type") or "").casefold() == "barcode" and i.get("value")
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("blocking_keys")
    ap.add_argument("out")
    # 0 disables the background sample; gm-design-1wd.1 runs only the keyed baseline,
    # which never reaches an unkeyed record.
    ap.add_argument("--background-mod", type=int, default=100)
    ap.add_argument("--max-scan", type=int, default=0, help="0 = whole dump")
    args = ap.parse_args()
    with open(args.blocking_keys) as f:
        raw = json.load(f)
    targets, barcodes = set(raw["targets"]), set(raw["barcodes"])
    catnos, titles = set(raw["catnos"]), set(raw["titles"])

    stats = {"scanned": 0, "kept": 0, "target": 0, "barcode": 0, "catno": 0, "title": 0, "background": 0}
    started = time.time()
    # recover=True closes an unterminated document on its own, so a dropped download
    # would otherwise parse as a silently short pool. The raw bytes must end in </releases>.
    source = TailReader(sys.stdin.buffer)
    context = etree.iterparse(source, events=("end",), tag="release", recover=True, huge_tree=True)
    with gzip.open(args.out, "wt", compresslevel=5) as out:
        for _, el in context:
            if el.getparent() is None or el.getparent().tag != "releases":
                continue
            stats["scanned"] += 1
            rec = compact(el)
            reasons = []
            rid = rec["native_id"]
            if rid in targets:
                reasons.append("target")
            if any(barcode_key(b) in barcodes for b in rec["barcodes"]):
                reasons.append("barcode")
            if any(catno_key(lb["catno"]) in catnos for lb in rec["labels"]):
                reasons.append("catno")
            if title_key(rec["title"]) in titles:
                reasons.append("title")
            if args.background_mod and rid and rid.isdigit() and int(rid) % args.background_mod == 0:
                reasons.append("background")
            if reasons:
                rec["kept_reasons"] = reasons
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stats["kept"] += 1
                for r in reasons:
                    stats[r] += 1
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
            if stats["scanned"] % 500000 == 0:
                rate = stats["scanned"] / (time.time() - started)
                print(f"...{json.dumps(stats)} {rate:.0f} rec/s", file=sys.stderr, flush=True)
            if args.max_scan and stats["scanned"] >= args.max_scan:
                break
    stats["targets_wanted"] = len(targets)
    stats["seconds"] = round(time.time() - started)
    if not args.max_scan:
        source.read(-1)
    stats["bytes"] = source.total
    stats["complete"] = bool(args.max_scan) or source.tail.rstrip().endswith(b"</releases>")
    print(f"DONE {json.dumps(stats)}", file=sys.stderr)
    if not stats["complete"]:
        sys.exit("stream ended before </releases>: the pool is truncated")


if __name__ == "__main__":
    main()
