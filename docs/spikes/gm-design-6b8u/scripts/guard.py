#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The aggregate-only guard, copied from gm-design-loj9's `scripts/measure.py` (merged at 3fdb051)."""

from __future__ import annotations

import re
from typing import Any


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_BARE_ID = re.compile(r"^\d{5,}$")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+")


def assert_aggregate_only(value: Any, path: str = "$") -> None:
    """Refuse any string or key that looks like an id, an external id, or an address.

    Counts are numbers and months and days are `YYYY-MM[-DD]`, so a UUID, a run of five or
    more digits held as a string, or an email address can only be a leak.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            assert_aggregate_only(key, f"{path}.<key>")
            assert_aggregate_only(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_aggregate_only(item, f"{path}[{index}]")
    elif isinstance(value, str) and (_UUID.search(value) or _BARE_ID.match(value) or _EMAIL.search(value)):
        raise ValueError(f"{path} looks like an identifier, not an aggregate")
