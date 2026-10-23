# SPDX-License-Identifier: MIT
"""Only aggregates reach results/: the guard refuses ids, and the committed files pass it."""

import json
from pathlib import Path

import pytest

from guard import assert_aggregate_only

RESULTS = Path(__file__).resolve().parent.parent / "results"


@pytest.mark.parametrize("leak", ["00000000-0000-4000-8000-000000000001", {"900001": 3}, ["someone@example.invalid"]])
def test_guard_refuses_identifiers(leak):
    with pytest.raises(ValueError):
        assert_aggregate_only({"x": leak})


def test_committed_results_are_aggregate_only():
    files = list(RESULTS.glob("*.json"))
    assert files
    for path in files:
        assert_aggregate_only(json.loads(path.read_text()))
