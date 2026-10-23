# SPDX-License-Identifier: MIT
from mb_links import count_discogs_links, extract_discogs_id, find_discogs_id


def rel(url, kind="discogs"):
    return {"target-type": "url", "type": kind, "url": {"resource": url}}


def test_extract_matches_the_ingestion_rule():
    assert extract_discogs_id("https://www.discogs.com/release/42", "release") == 42
    assert extract_discogs_id("https://www.discogs.com/release/42-Some-Title", "release") == 42
    assert extract_discogs_id("https://www.discogs.com/master/42", "release") is None
    assert extract_discogs_id("http://www.discogs.com/release/42", "release") is None
    assert extract_discogs_id("https://www.discogs.com/release/abc", "release") is None


def test_first_parsable_discogs_relation_wins():
    record = {"relations": [
        rel("https://www.discogs.com/release/7", kind="other databases"),
        rel("https://www.discogs.com/master/9"),
        rel("https://www.discogs.com/release/5"),
        rel("https://www.discogs.com/release/6"),
    ]}
    assert find_discogs_id(record, "release") == 5
    assert find_discogs_id(record, "master") == 9
    assert count_discogs_links(record, "release") == 2


def test_no_relations():
    assert find_discogs_id({}, "release") is None
    assert count_discogs_links({"relations": None}, "master") == 0
