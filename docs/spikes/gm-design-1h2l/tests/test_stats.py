# SPDX-License-Identifier: MIT
"""Hand-checked numbers over the synthetic dumps (tests/fixtures)."""
import duckdb
import pytest

from discogs_rules import role_fragments, year_of
from ladder_stats import FRAGMENTS_SQL, ladder_stats
from mb_attach import mb_attach


@pytest.fixture()
def con(fixture_db):
    connection = duckdb.connect(str(fixture_db))
    yield connection
    connection.close()


def test_year_rule():
    assert year_of("1971-03-00", 2027) == 1971
    assert year_of("0400-01-01", 2027) is None
    assert year_of("2028", 2027) is None
    assert year_of("", 2027) is None
    assert year_of("19xx", 2027) is None


def test_role_fragments_python_and_sql_agree(con):
    raw = "Producer, Mixed By [Assistant, Night]"
    assert role_fragments(raw) == ["Producer", "Mixed By"]
    sql = sorted(f for (f,) in con.execute(f"SELECT fragment FROM ({FRAGMENTS_SQL})").fetchall())
    assert sql == sorted(role_fragments(raw) + role_fragments("Bass"))


def test_ladder_stats(con):
    s = ladder_stats(con)
    assert s["releases"]["total"] == 4
    assert s["releases"]["no_master"] == 1
    assert s["releases"]["no_master_share"] == 0.25
    assert s["releases"]["no_year"] == 2  # an out-of-range year and an empty one
    assert s["releases"]["no_master_and_no_year"] == 1
    assert s["years"] == {"masters_with_no_year": 1, "releases_with_a_master_and_no_year": 1, "of_which_the_master_has_a_year": 0,
                          "masterless_releases_with_no_year": 1, "releases_with_no_year_even_after_master_fallback": 2}
    pa = s["per_artist"]
    assert pa["artists"] == 3
    assert pa["releases_per_artist"]["p50"] == 1 and pa["releases_per_artist"]["max"] == 3
    assert pa["no_master_share_per_artist"]["max"] == pytest.approx(0.3333)
    assert pa["no_master_share_per_artist"]["p50"] == 0
    assert [b["artists"] for b in s["bands"]] == [3, 0, 0, 0, 0]
    pm = s["per_master"]
    assert pm["masters_in_dump"] == 2 and pm["masters_with_a_release"] == 2
    assert pm["releases_per_master"]["max"] == 2
    fan = pm["credit_fan_out"]
    assert fan["by_artists_per_master"]["max"] == 2
    assert fan["masters_with_more_than_one_by_artist"] == 1
    assert fan["masters_with_more_than_one_master_artist"] == 1
    assert fan["credited_people_per_master"]["max"] == 2  # the track-level credit is not read
    assert fan["masters_with_no_credited_people"] == 1
    assert fan["raw_roles_per_master"]["max"] == 2
    assert fan["roles_per_master"]["max"] == 3
    assert s["credits"] == {"credited_on_rows": 2, "distinct_people": 2, "distinct_raw_roles": 2,
                            "distinct_roles": 3, "releases_with_credits": 1}
    assert s["largest_artists"][0] == {"rank": 1, "releases": 3, "masters": 1, "no_master_share": 0.3333, "no_year": 1}


def test_mb_attach(con):
    m = mb_attach(con)
    assert m["mb_releases"] == 14
    assert m["linked_to_discogs_release"] == 7
    assert m["linked_to_more_than_one_discogs_release"] == 1
    assert m["linked_but_release_missing_from_discogs_dump"] == 1
    assert m["mb_only_releases"] == 7
    assert m["mb_only_by_path"] == {
        "native_id": 1,
        "native_id_master_missing_from_dump": 1,
        "none": 2,
        "release_group_ambiguous": 1,
        "release_group_one_master": 1,
        "release_group_siblings_masterless": 1,
    }
    assert m["mb_only_attached_to_a_master"] == 2
    assert m["mb_only_with_a_release_level_master_link"] == 1
    assert m["release_groups"] == 9 and m["release_groups_with_master_link"] == 3
    assert m["release_group_master_missing_from_discogs_dump"] == 1
    assert m["group_master_vs_sibling_masters"] == {"agree": 1, "disagree": 1}


def test_payload_driver_end_to_end(fixture_db, tmp_path):
    import subprocess
    import sys

    import orjson

    from conftest import SCRIPTS

    out, sample = tmp_path / "payload.json", tmp_path / "sample.tsv"
    subprocess.run(
        [sys.executable, "payload_model.py", str(fixture_db), str(out), "--sample", "5", "--budgets", "0,48,3/12/16", "--sample-out", str(sample)],
        cwd=SCRIPTS, check=True, capture_output=True,
    )
    result = orjson.loads(out.read_bytes())
    assert result["bands"]["1-9"]["artists"] == 3
    assert result["bands"]["largest10"]["artists"] == 3
    assert result["bands"]["10-99"]["by_budget"]["0"] is None
    sizes = result["bands"]["1-9"]["by_budget"]["0"]
    assert 0 < sizes["anonymous"]["p50"] <= sizes["signed_in"]["p50"]
    assert result["bands"]["1-9"]["by_budget"]["3/12/16"]["entries"]["max"] <= 3 + 12 + 16
    assert len(sample.read_text().splitlines()) == 6
