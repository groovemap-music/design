# SPDX-License-Identifier: MIT
"""Rules the graph applies to a Discogs release, restated for the spike.

- `year_of`: `python-libraries/src/common/data_normalizer.py` `_parse_year_int` derives
  `Release.year` from `released` (first four characters), and drops it outside
  [1860, current year + 1]. The bound is pinned to the dump's year + 1 here so a re-run
  next year reproduces the same numbers.
- `role_fragments`: `CREDITED_ON.role` holds the raw Discogs role string, which can
  carry several roles. The spike counts both the raw strings (what the graph stores) and
  the bare roles inside them.
"""
from __future__ import annotations

import re

MIN_RELEASE_YEAR = 1860


def year_of(value: str | None, max_year: int) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        year = int(text[:4])
    except ValueError:
        return None
    return year if MIN_RELEASE_YEAR <= year <= max_year else None


_QUALIFIER = re.compile(r"\s*\[[^\]]*\]")


def role_fragments(raw_role: str) -> list[str]:
    """Split a raw role ("Mixed By [Assistant], Producer") into bare roles.

    Discogs separates roles with commas and qualifies them in square brackets, and a
    qualifier can itself contain commas, so brackets are removed before splitting.
    """
    bare = _QUALIFIER.sub("", raw_role)
    return [part.strip() for part in bare.split(",") if part.strip()]
