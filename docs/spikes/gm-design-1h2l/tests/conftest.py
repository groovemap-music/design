# SPDX-License-Identifier: MIT
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture(scope="session")
def fixture_db(tmp_path_factory):
    """The synthetic dumps run through the same extract and load steps as the real ones."""
    out = tmp_path_factory.mktemp("discogs")
    for kind in ("releases", "masters"):
        with open(FIXTURES / f"synthetic_{kind}.xml", "rb") as stdin:
            subprocess.run(
                [sys.executable, "extract_discogs.py", kind, str(out), "--max-year", "2027"],
                cwd=SCRIPTS, stdin=stdin, check=True, capture_output=True,
            )
    db = out / "spike.duckdb"
    subprocess.run(
        [sys.executable, "load_db.py", str(out), str(FIXTURES / "synthetic_mb_release.tsv"),
         str(FIXTURES / "synthetic_mb_release_group.tsv"), str(db)],
        cwd=SCRIPTS, check=True, capture_output=True,
    )
    return db
