# SPDX-License-Identifier: MIT
"""Only aggregates may reach results/: the guard refuses ids, and the measurement emits none."""

import json
from pathlib import Path

import pytest

import synthetic
from measure import assert_aggregate_only
from reference import identity_history, load

RESULTS = Path(__file__).resolve().parent.parent / "results"


@pytest.mark.parametrize("leak", [synthetic.native(1), {"900001": 3}, ["someone@example.invalid"], {"by": {synthetic.mbid(2): 1}}])
def test_guard_refuses_identifiers(leak):
    with pytest.raises(ValueError):
        assert_aggregate_only({"x": leak})


def test_guard_accepts_counts_months_and_days():
    assert_aggregate_only({"rows": 19418504, "per_month": {"2026-09": 3}, "first": "2026-09-02", "by_provider_kind": {"discogs/release": 2}})


def test_identity_history_emits_no_identifier():
    for fixture in (synthetic.build(), synthetic.with_writers_that_do_not_exist_yet()):
        assert_aggregate_only(identity_history(load(fixture)))


def test_committed_measurements_are_aggregate_only():
    measured = [path for path in RESULTS.glob("*.json") if not path.name.startswith("example_")]
    assert measured
    for path in measured:
        assert_aggregate_only(json.loads(path.read_text()))
