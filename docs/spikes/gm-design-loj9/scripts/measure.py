#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Measure one catalog database, read-only, and write aggregate JSON to `results/`.

    PSQL='<psql invocation>' DATABASE=<name> LABEL='<what this database is>' \
        uv run python scripts/measure.py results/

Runs `sql/probe.sql` first. `sql/identity_history.sql` runs only when every table it reads
exists; otherwise its result file records `"status": "DEFER"` and the probe that decided
it. `sql/link_structure.sql` runs whenever both catalogs' release tables exist. Each file is
checked by :func:`assert_aggregate_only` before it is written, so a figure that looks like
a native or provider id fails the run instead of reaching the repository.

The label is free text such as "predecessor catalog". Never put a host name, user name, or
connection string in it: it is committed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SQL = HERE.parent / "sql"

IDENTITY_TABLES = ("catalog_items", "provider_aliases", "catalog_item_supersessions", "catalog_item_moves", "admin_audit_log", "releases", "musicbrainz.releases")
LINK_TABLES = ("releases", "masters", "musicbrainz.releases", "musicbrainz.release_groups")

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


def run_sql(name: str) -> dict[str, Any]:
    output = subprocess.run([str(HERE / "run_sql.sh"), str(SQL / name)], check=True, capture_output=True, text=True).stdout
    return json.loads(output)


def write(out_dir: Path, name: str, result: dict[str, Any]) -> None:
    assert_aggregate_only(result)
    (out_dir / name).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(f"wrote {out_dir / name}")


def main() -> None:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else HERE.parent / "results")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = {"measured_on": datetime.now(UTC).strftime("%Y-%m-%d"), "database": os.environ.get("LABEL", "unlabelled")}

    probe = run_sql("probe.sql")
    write(out_dir, "probe.json", {**stamp, **probe})
    tables = probe["tables"]

    missing = [table for table in IDENTITY_TABLES if not tables.get(table)]
    if missing:
        write(out_dir, "identity_history.json", {**stamp, "status": "DEFER", "missing_tables": missing})
    else:
        write(out_dir, "identity_history.json", {**stamp, "status": "MEASURED", **run_sql("identity_history.sql")})

    if all(tables.get(table) for table in LINK_TABLES):
        write(out_dir, "link_structure.json", {**stamp, **run_sql("link_structure.sql")})


if __name__ == "__main__":
    main()
