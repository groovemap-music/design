# SPDX-License-Identifier: MIT
"""The Discogs cross-reference rule musicbrainz-ingestion applies, restated in Python.

`musicbrainz-ingestion/src/musicbrainz/jsonl_parser.rs` (`find_discogs_id`,
`extract_discogs_id`) takes the first `type == "discogs"` URL relation whose resource
parses as `https://www.discogs.com/<entity>/<id>` or `.../<id>-<slug>`. That value is
what lands in `musicbrainz.releases.discogs_release_id` and
`musicbrainz.release_groups.discogs_master_id`, so the spike counts with the same rule
rather than a looser regex. Copied, not imported: no GrooveMap repository imports
another's source.
"""
from __future__ import annotations

from typing import Any


def extract_discogs_id(url: str, entity: str) -> int | None:
    prefix = f"https://www.discogs.com/{entity}/"
    if not url.startswith(prefix):
        return None
    head = url[len(prefix):].split("-", 1)[0]
    # Rust's i64::parse accepts a leading '+' and rejects everything else that is not a
    # digit; isdigit() is the same set for the URLs MusicBrainz stores.
    if not head.isdigit():
        return None
    return int(head)


def find_discogs_id(record: dict[str, Any], entity: str) -> int | None:
    """First Discogs id of `entity` among the record's discogs-type URL relations."""
    for rel in record.get("relations") or ():
        if rel.get("target-type") != "url" or rel.get("type") != "discogs":
            continue
        resource = (rel.get("url") or {}).get("resource") or ""
        found = extract_discogs_id(resource, entity)
        if found is not None:
            return found
    return None


def count_discogs_links(record: dict[str, Any], entity: str) -> int:
    """How many distinct Discogs ids of `entity` the record links (ingestion keeps one)."""
    ids = set()
    for rel in record.get("relations") or ():
        if rel.get("target-type") != "url" or rel.get("type") != "discogs":
            continue
        found = extract_discogs_id((rel.get("url") or {}).get("resource") or "", entity)
        if found is not None:
            ids.add(found)
    return len(ids)
