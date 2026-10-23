"""Extractor and fold over the invented XML fixtures."""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import aggregate

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"


def extract(kind: str, xml: str, out: Path) -> None:
    subprocess.run([sys.executable, str(SCRIPTS / "extract_dump.py"), kind, str(out)], input=xml.encode(), check=True, capture_output=True)


@pytest.fixture
def folded(tmp_path):
    extract("releases", (HERE / "fixtures/releases.xml").read_text(), tmp_path / "r.npz")
    extract("masters", (HERE / "fixtures/masters.xml").read_text(), tmp_path / "m.npz")
    rel, rv = aggregate.load(tmp_path / "r.npz")
    mst, mv = aggregate.load(tmp_path / "m.npz")
    return aggregate.fold(rel, rv, mst, mv), rel


def test_extract_keeps_only_main_artists_and_dedupes_styles(folded):
    _, rel = folded
    assert rel["artist_ids"].tolist() == [101, 102]  # track and extra artists, and id 0, dropped
    assert np.diff(rel["style_ptr"]).tolist() == [2, 1, 0]
    assert rel["year"].tolist() == [1991, 0, 2005]
    assert rel["master"].tolist() == [31, 0, 0]


def test_truncated_stream_fails(tmp_path):
    xml = (HERE / "fixtures/releases.xml").read_text().replace("</releases>", "")
    proc = subprocess.run([sys.executable, str(SCRIPTS / "extract_dump.py"), "releases", str(tmp_path / "x.npz")], input=xml.encode(), capture_output=True)
    assert proc.returncode != 0
    assert not (tmp_path / "x.npz").exists()


def test_fold_counts(folded):
    out, _ = folded
    styles, genres = list(out["_styles"]), list(out["_genres"])
    assert styles == ["Alpha One", "Shared"] and genres == ["Alpha", "Beta"]
    sg = out["style_genre_rel"]
    assert sg[0].tolist() == [1, 1]  # Alpha One on release 11 (Alpha + Beta)
    assert sg[1].tolist() == [1, 2]  # Shared on 11 (Alpha + Beta) and 12 (Beta)
    assert out["cotag"].tolist() == [[1, 1], [1, 2]]
    # part_of: release 12 is single-genre Beta with Shared; master 31 is single-genre Alpha with Alpha One.
    assert out["partof"].tolist() == [[1, 0], [0, 1]]
    assert out["first_year_style"].tolist() == [1991, 1991]
    assert out["style_year_mst"][0, 1990 - aggregate.YEAR0] == 1
    assert out["counts"].tolist() == [3, 1, 2, 2, 0, 1, 1, 3]
