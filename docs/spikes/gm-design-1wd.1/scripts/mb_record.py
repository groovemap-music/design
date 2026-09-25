"""The compact MusicBrainz release record, copied from gm-design-zwy's
``extract_mb_releases.compact`` so the matcher sees exactly the fields it saw there.

The Discogs relations are the label; every other field is what a matcher may use.
"""
from __future__ import annotations

import re

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
