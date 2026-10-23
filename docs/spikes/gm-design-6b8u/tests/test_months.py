# SPDX-License-Identifier: MIT
"""The proxy's calendar, its validation, and the monthly model, on invented releases only."""

from datetime import UTC, datetime

import numpy as np
import pytest

import months
from months import T_A, T_B, dump_instants, g2, model, next_dump, next_run, validate


def ts(*parts: int) -> int:
    return int(datetime(*parts, tzinfo=UTC).timestamp())


def mbid(n: int) -> str:
    return f"00000000-0000-4000-9000-{n:012x}"


def test_dumps_fall_on_wednesday_and_saturday_at_ten_past_midnight():
    dumps = dump_instants(datetime(2026, 10, 12, tzinfo=UTC), datetime(2026, 10, 25, tzinfo=UTC))
    assert [datetime.fromtimestamp(int(d), UTC).strftime("%a %d %H:%M:%S") for d in dumps] == [
        "Wed 14 00:10:01", "Sat 17 00:10:01", "Wed 21 00:10:01", "Sat 24 00:10:01"]
    assert T_A in dumps and T_B in dumps
    # A release added one second after a dump is first carried by the next one.
    assert next_dump(dumps, np.asarray([T_A + 1]))[0] == T_B
    assert next_dump(dumps, np.asarray([T_A]))[0] == T_B


def test_runs_are_on_the_first_of_the_next_month():
    assert next_run(ts(2026, 10, 21, 0, 10, 1)) == ts(2026, 11, 1)
    assert next_run(ts(2026, 12, 31, 23, 0)) == ts(2027, 1, 1)


def test_validation_counts_both_directions_of_error():
    json_a = {mbid(1): (0, ""), mbid(2): (0, ""), mbid(3): (900003, ""), mbid(4): (0, ""), mbid(5): (0, "")}
    json_b = {mbid(1): (900001, ""), mbid(2): (900002, ""), mbid(3): (900003, ""), mbid(4): (900004, ""), mbid(5): (0, ""),
              mbid(6): (900006, "")}
    history = {
        mbid(1): (T_A + 3600, ts(2020, 1, 1), 900001, ""),  # added in the window: both agree
        mbid(2): (T_B + 3600, ts(2020, 1, 1), 900002, ""),  # added in the window, edited after it: a miss
        mbid(3): (T_A + 7200, ts(2020, 1, 1), 900003, ""),  # an older link edited in the window: a false hit
        mbid(4): (T_A + 60, T_A + 30, 900004, ""),          # date_added says it is newer than dump A: a miss
        mbid(6): (T_A + 90, T_A + 60, 900006, ""),          # new and linked: the secondary check
    }
    result = validate(history, json_a, json_b)
    assert (result["exact_link_added"], result["proxy_link_added"], result["both"]) == (3, 2, 1)
    assert (result["precision"], result["recall"]) == (0.5, 0.3333)
    assert not result["passes"]
    assert result["false_negatives"] == {"link_dated_after_window (edited later)": 1, "created_after_dump_a_per_date_added": 1}
    assert result["false_positives"] == {"linked_in_dump_a (an older link edited in the window)": 1}
    assert result["secondary_new_and_linked"] == {"exact": 1, "proxy": 2, "both": 1}


@pytest.fixture
def history():
    return {
        # Existed and linked before the first load: linked at ingest in month 0.
        mbid(1): (ts(2024, 5, 1), ts(2024, 1, 1), 900001, "g1"),
        # Existed before the first load, linked in March 2026: re-attached at the April run.
        mbid(2): (ts(2026, 3, 10), ts(2024, 1, 1), 900002, "g1"),
        # Added in June 2026 with its link: linked at ingest in June.
        mbid(3): (ts(2026, 6, 2, 10), ts(2026, 6, 2, 9), 900003, "g1"),
        # Added in May 2026 unlinked, linked in August: minted in May, re-attached at the September run.
        mbid(4): (ts(2026, 8, 20), ts(2026, 5, 5), 900004, "g2"),
        # Linked after the October run: pending.
        mbid(5): (ts(2026, 10, 15), ts(2024, 1, 1), 900005, "g2"),
        # Added after the last dump read: not loaded.
        mbid(6): (ts(2026, 10, 22), ts(2026, 10, 22), 900006, "g2"),
    }


def test_model_assigns_each_release_its_months(history):
    events, reattached, at_ingest, pending = model(history, {})
    assert dict(at_ingest) == {"2025-10": 1, "2026-06": 1}
    assert dict(reattached) == {"2026-04": 1, "2026-09": 1}
    assert pending == 1
    assert dict(events[900004]) == {"reattached": {"2026-09"}, "musicbrainz_item_minted": {"2026-05"}}
    assert 900006 not in events


def test_g2_counts_works_whose_editions_change_in_two_months(history):
    events, _, _, _ = model(history, {})
    parents = {900001: {("m", 1)}, 900002: {("m", 1)}, 900003: {("m", 1)}, 900004: {("m", 2)}}
    lower = g2(events, parents, include_mint=False)
    assert lower["works_with_2plus_evented_editions"] == 1
    assert lower["works_with_2plus_evented_editions_multi_month"] == 1
    assert g2(events, parents, include_mint=False, after_first_load=True)["works_with_2plus_evented_editions_multi_month"] == 1
    # One edition alone never counts, whatever its months.
    assert g2(events, {900004: {("m", 2)}}, include_mint=True)["works_with_2plus_evented_editions"] == 0


def test_bar_is_the_pre_registered_one():
    assert months.BAR == {"precision": 0.90, "recall": 0.90, "G2": 1000, "G3": 1000}
