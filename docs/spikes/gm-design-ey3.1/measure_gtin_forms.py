# SPDX-License-Identifier: MIT
"""Aggregate UPC-A / EAN-13 form counts in the Discogs and MusicBrainz release dumps.

Read-only and aggregate-only. The Discogs dump is streamed through ``gzip -dc`` into a
strict (non-recovering) parser, and the run fails unless gzip exits 0 and the document
closes. The MusicBrainz side reads the gm-design-1wd.1 compact snapshot, whose line count
must match the release count its stream log recorded.

    uv run --with lxml python measure_gtin_forms.py DISCOGS.xml.gz MB.jsonl.gz MB_COUNT

``GTIN_STATE=path.pkl`` keeps the parsed Discogs sets in a scratch pickle outside the
repository, so a change to the report does not re-stream the dump.
"""
from __future__ import annotations

import gzip
import json
import os
import pickle
import subprocess
import sys
from collections import Counter, defaultdict

from lxml import etree


def digits(value: str | None) -> str:
    """ADR 0011 barcode namespace rule: ASCII digits only, as every mapper applies it."""
    return "".join(c for c in (value or "") if "0" <= c <= "9")


def check_ok(d: str) -> bool:
    """GS1 mod-10: weights 3,1,3,... from the digit left of the check digit."""
    body, check = d[:-1], int(d[-1])
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


class Catalog:
    def __init__(self, name: str) -> None:
        self.name = name
        self.releases = 0
        self.with_barcode = 0
        self.occ_len = Counter()  # (release, value) occurrences by length
        self.values: dict[int, set[str]] = defaultdict(set)  # distinct values by length
        self.forms: dict[str, list] = {}  # 12-digit D or '0'+D (13) -> release keys
        self.same_release: set[str] = set()  # GTINs a single release carries in both forms

    def add(self, key, raw_values) -> None:
        self.releases += 1
        vals = {d for d in (digits(v) for v in raw_values) if d}
        if not vals:
            return
        self.with_barcode += 1
        for d in vals:
            self.occ_len[len(d)] += 1
            self.values[len(d)].add(d)
            if len(d) == 12 or (len(d) == 13 and d[0] == "0"):
                self.forms.setdefault(d, []).append(key)
        for d in vals:
            if len(d) == 12 and "0" + d in vals:
                self.same_release.add(d)

    def report(self) -> dict:
        lens = {n: len(s) for n, s in sorted(self.values.items())}
        v12, v13 = self.values.get(12, set()), self.values.get(13, set())
        v14 = self.values.get(14, set())
        both = {d for d in v12 if "0" + d in v13}
        disjoint = sum(1 for d in both if not set(self.forms[d]) & set(self.forms["0" + d]))
        multi12 = sum(1 for d in v12 if len(self.forms[d]) > 1)
        return {
            "releases": self.releases,
            "releases_with_barcode": self.with_barcode,
            "distinct_values_by_length": {
                "8": lens.get(8, 0), "12": lens.get(12, 0), "13": lens.get(13, 0),
                "14": lens.get(14, 0),
                "other": sum(c for n, c in lens.items() if n not in (8, 12, 13, 14)),
            },
            "occurrences_by_length": {k: self.occ_len.get(k, 0) for k in (12, 13, 14)},
            "distinct_13_leading_0": sum(1 for d in v13 if d[0] == "0"),
            "check_digit_valid": {
                str(n): sum(1 for d in self.values.get(n, ()) if check_ok(d))
                for n in (12, 13, 14)
            },
            "distinct_12_on_multiple_releases": multi12,
            "gtins_in_both_forms": len(both),
            "both_forms_on_one_release": len(both & self.same_release),
            "both_forms_disjoint_releases": disjoint,
            "fourteen_digit": {
                "leading_00": sum(1 for d in v14 if d.startswith("00")),
                "leading_0_only": sum(1 for d in v14 if d[0] == "0" and d[1] != "0"),
                "indicator_1_to_8": sum(1 for d in v14 if d[0] in "12345678"),
                "indicator_9": sum(1 for d in v14 if d[0] == "9"),
                "check_valid": sum(1 for d in v14 if check_ok(d)),
                "leading_00_and_rest_in_12": sum(1 for d in v14 if d.startswith("00") and d[2:] in v12),
                "leading_0_and_rest_in_13": sum(1 for d in v14 if d[0] == "0" and d[1:] in v13),
            },
        }


def read_discogs(path: str, cat: Catalog) -> None:
    proc = subprocess.Popen(["gzip", "-dc", path], stdout=subprocess.PIPE)
    closed = False
    for event, el in etree.iterparse(proc.stdout, events=("end",), recover=False, huge_tree=True):
        if el.tag == "release":
            rid = int(el.get("id"))
            vals = [
                i.get("value") for i in el.iterfind("identifiers/identifier")
                if (i.get("type") or "") == "Barcode"
            ]
            cat.add(rid, vals)
            el.clear()
            parent = el.getparent()
            while el.getprevious() is not None:
                del parent[0]
            if cat.releases % 1_000_000 == 0:
                print(f"discogs {cat.releases}", file=sys.stderr, flush=True)
        elif el.tag == "releases":
            closed = True
    if proc.wait() != 0:
        raise SystemExit(f"gzip exited {proc.returncode}: Discogs stream incomplete")
    if not closed:
        raise SystemExit("Discogs document never closed </releases>: stream incomplete")


def read_mb(path: str, expected: int, cat: Catalog, links: dict) -> None:
    with gzip.open(path, "rt") as fh:
        for n, line in enumerate(fh):
            rec = json.loads(line)
            links[n] = {int(x) for x in rec.get("discogs_release_ids") or []}
            cat.add(n, [rec.get("barcode")])
    if cat.releases != expected:
        raise SystemExit(f"MB snapshot has {cat.releases} releases, expected {expected}")


def cross(mb: Catalog, dc: Catalog, links: dict) -> dict:
    """GTINs one catalog stores as D and the other as '0'+D."""
    out = {}
    for label, a_len, b_fn in (
        ("mb_12_discogs_13", 12, lambda d: "0" + d),
        ("mb_13_discogs_12", 13, lambda d: d[1:] if d[0] == "0" else None),
    ):
        gtins = linked = 0
        for d in mb.values.get(a_len, ()):
            other = b_fn(d)
            if other is None or other not in dc.forms:
                continue
            gtins += 1
            dc_ids = set(dc.forms[other])
            if any(links[k] & dc_ids for k in mb.forms[d]):
                linked += 1
        out[label] = {"gtins": gtins, "mb_release_links_a_discogs_release_in_other_form": linked}
    same = mb.values.get(12, set()) & dc.values.get(12, set())
    same13 = mb.values.get(13, set()) & dc.values.get(13, set())
    out["same_form_12"] = len(same)
    out["same_form_13"] = len(same13)
    return out


def union(mb: Catalog, dc: Catalog) -> dict:
    """GTINs held in more than one form across both catalogs (the alias table is shared).

    In scope are 12 and 13 digits and 14 digits beginning with ``0``; the GTIN key is the
    value zero-padded to 14 digits (ADR 0011, second 2026-09-25 amendment).
    """
    forms: dict[str, set[str]] = {}
    for cat in (dc, mb):
        for n in (12, 13, 14):
            for v in cat.values.get(n, ()):
                if n < 14 or v[0] == "0":
                    forms.setdefault(v.zfill(14), set()).add(v)
    multi = [f for f in forms.values() if len(f) > 1]
    shapes = Counter("/".join(str(n) for n in sorted(len(v) for v in f)) for f in multi)
    return {"gtins_in_scope": len(forms), "gtins_in_2plus_forms": len(multi), "shapes": dict(shapes)}


def main() -> None:
    discogs_path, mb_path, mb_expected = sys.argv[1], sys.argv[2], int(sys.argv[3])
    mb, links = Catalog("musicbrainz"), {}
    read_mb(mb_path, mb_expected, mb, links)
    mb_report = mb.report()  # before the long Discogs pass, so a report bug fails fast
    print("musicbrainz done", file=sys.stderr, flush=True)
    state = os.environ.get("GTIN_STATE")  # optional scratch pickle, so a report fix never re-streams
    if state and os.path.exists(state):
        with open(state, "rb") as fh:
            dc = pickle.load(fh)
    else:
        dc = Catalog("discogs")
        read_discogs(discogs_path, dc)
        if state:
            with open(state, "wb") as fh:
                pickle.dump(dc, fh)
    print(json.dumps({
        "discogs": dc.report(),
        "musicbrainz": mb_report,
        "cross_catalog": cross(mb, dc, links),
        "union": union(mb, dc),
    }, indent=2))


if __name__ == "__main__":
    main()
