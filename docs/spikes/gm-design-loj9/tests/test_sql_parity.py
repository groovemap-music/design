# SPDX-License-Identifier: MIT
"""sql/identity_history.sql and scripts/reference.py agree on the synthetic fixture.

Needs a scratch PostgreSQL 18 server, so it is skipped unless LEDGER_PARITY_PSQL is set to a
psql invocation for a role that may create databases, without a database argument, for
example `docker exec -i ledger-parity psql -U postgres` (see the README). It creates a
database, loads `sql/schema_subset.sql` and the fixture, runs the measurement through
`scripts/run_sql.sh` exactly as a real run does, and drops the database.
"""

import json
import os
import shlex
import subprocess
import uuid
from pathlib import Path

import pytest

import synthetic
from reference import identity_history, load

HARNESS = Path(__file__).resolve().parent.parent
PSQL = os.environ.get("LEDGER_PARITY_PSQL")

pytestmark = pytest.mark.skipif(not PSQL, reason="LEDGER_PARITY_PSQL is not set")


def _insert(table: str, rows: list[dict]) -> str:
    if not rows:
        return ""
    columns = ", ".join(rows[0])
    return f"INSERT INTO {table} ({columns}) SELECT {columns} FROM jsonb_populate_recordset(NULL::{table}, $fixture${json.dumps(rows)}$fixture$);\n"


def load_sql(fixture: dict) -> str:
    sql = (HARNESS / "sql/schema_subset.sql").read_text()
    for table in ("catalog_items", "provider_aliases", "catalog_item_supersessions", "catalog_item_moves", "admin_audit_log"):
        rows = fixture[table]
        if table == "catalog_item_supersessions":
            # Rows that name another row by via_id go in after it.
            rows = sorted(rows, key=lambda row: row["via_id"] is not None)
        sql += _insert(table, rows)
    sql += _insert("releases", [{"data_id": r["data_id"], "data": {"master_id": r["master_id"]}} for r in fixture["discogs_releases"]])
    sql += _insert("musicbrainz.releases", fixture["musicbrainz_releases"])
    return sql


def psql(*args: str, stdin: str | None = None) -> str:
    command = [*shlex.split(PSQL), "-X", "-q", "-v", "ON_ERROR_STOP=1", *args]
    return subprocess.run(command, input=stdin, check=True, capture_output=True, text=True).stdout


@pytest.mark.parametrize("variant", ["build", "with_writers_that_do_not_exist_yet"])
def test_sql_equals_reference(variant):
    fixture = getattr(synthetic, variant)()
    database = f"ledger_parity_{uuid.uuid4().hex[:8]}"
    psql("-c", f"CREATE DATABASE {database}")
    try:
        psql("-d", database, stdin=load_sql(fixture))
        env = {**os.environ, "PSQL": PSQL, "DATABASE": database, "STATEMENT_TIMEOUT": "60s"}
        output = subprocess.run([str(HARNESS / "scripts/run_sql.sh"), str(HARNESS / "sql/identity_history.sql")],
                                check=True, capture_output=True, text=True, env=env).stdout
        assert json.loads(output) == identity_history(load(fixture))
    finally:
        psql("-c", f"DROP DATABASE {database}")
