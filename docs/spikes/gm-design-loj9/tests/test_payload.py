# SPDX-License-Identifier: MIT
"""The draft ledger payload: history-only fields, states over transaction time, no user data."""

import json
from pathlib import Path

import pytest

import synthetic
from payload import RULES, STATES, NotFoundError, build
from reference import load, ts


@pytest.fixture(scope="module")
def catalog():
    return load(synthetic.build())


def edition(payload, gm_id):
    return next(e for e in payload["editions"] if e["gm_id"] == gm_id)


def test_work_lists_editions_from_both_catalogs_rows(catalog):
    payload = build(catalog, synthetic.W1)
    assert [e["gm_id"] for e in payload["editions"]] == [synthetic.E1, synthetic.E2, synthetic.E4, synthetic.E3, synthetic.E5]
    assert payload["work"]["state"] == "linked"
    assert edition(payload, synthetic.E5)["state"] == "musicbrainz_only"
    assert edition(payload, synthetic.E4)["state"] == "discogs_only"


def test_reattached_edition_walks_unresolved_split_linked(catalog):
    states = [edition(build(catalog, synthetic.W1, ts(t)), synthetic.E3)["state"]
              for t in ("2026-08-05T00:00:00+00:00", "2026-09-01T12:00:00+00:00", "2026-09-03T00:00:00+00:00")]
    assert states == ["unresolved", "split", "linked"]


def test_reattachment_is_one_event_citing_its_audit_entry(catalog):
    e3 = edition(build(catalog, synthetic.W1), synthetic.E3)
    reattached = [e for e in e3["events"] if e["type"] == "reattached"]
    assert len(reattached) == 1
    assert reattached[0]["decision_ref"] == synthetic.RUN1
    assert reattached[0]["moves"] == {}
    assert e3["former_items"] == [{"gm_id": synthetic.X3, "superseded_at": "2026-09-02T10:00:01Z", "cause": "catalog_reattachment",
                                   "decision_ref": synthetic.RUN1}]
    moved = [row for row in e3["evidence"] if row["opened_by"] == "supersession"]
    assert {row["provider"] for row in moved} == {"musicbrainz", "barcode"}


def test_as_of_hides_what_was_not_yet_recorded(catalog):
    early = build(catalog, synthetic.W1, ts("2026-08-02T00:00:00+00:00"))
    assert [e["gm_id"] for e in early["editions"]] == [synthetic.E1, synthetic.E2, synthetic.E4]
    for row in early["editions"][0]["evidence"]:
        assert row["valid_from"] <= "2026-08-02"
    assert all(event["at"] <= "2026-08-02" for e in early["editions"] for event in e["events"])


def test_work_disagreement_is_flagged(catalog):
    payload = build(catalog, synthetic.W2)
    assert all(e["work_disagreement"] for e in payload["editions"])
    assert all(sorted(e["works"]) == sorted([synthetic.W2, synthetic.G2]) for e in payload["editions"])


def test_superseded_work_id_answers_as_the_survivor(catalog):
    payload = build(catalog, synthetic.G5X)
    assert payload["work"]["gm_id"] == synthetic.W5
    assert payload["work"]["requested_id"] == synthetic.G5X
    with pytest.raises(NotFoundError):
        build(catalog, synthetic.E1)


def test_vocabularies_are_closed(catalog):
    for work in (synthetic.W1, synthetic.W2, synthetic.W3):
        for e in build(catalog, work)["editions"]:
            assert e["state"] in STATES
            assert all(event["type"] in RULES and event["rule"] == RULES[event["type"]] for event in e["events"])


def test_no_user_or_row_id_is_emitted():
    fixture = synthetic.with_writers_that_do_not_exist_yet()
    text = json.dumps(build(load(fixture), synthetic.W1))
    for move in fixture["catalog_item_moves"]:
        assert move["user_id"] not in text and move["row_id"] not in text and move["id"] not in text
    assert synthetic.ADMIN not in text


def test_committed_fixture_matches_the_builder():
    committed = json.loads((Path(__file__).parent / "fixtures/synthetic_catalog.json").read_text())
    committed.pop("_comment")
    assert committed == synthetic.build()
