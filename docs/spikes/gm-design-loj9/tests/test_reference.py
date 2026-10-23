# SPDX-License-Identifier: MIT
"""The identity-history figures on the synthetic catalog (see `synthetic.py` for the story)."""

import pytest

import synthetic
from reference import identity_history, load, percentile_disc


@pytest.fixture(scope="module")
def result():
    return identity_history(load(synthetic.build()))


def test_source_volumes(result):
    aliases = result["provider_aliases"]
    assert (aliases["rows"], aliases["current"], aliases["closed"]) == (32, 29, 3)
    assert aliases["opened_per_month"] == {"2026-08": 24, "2026-09": 5, "2026-10": 3}
    assert aliases["closed_per_month"] == {"2026-09": 2, "2026-10": 1}
    assert aliases["by_source"] == {"catalog": 31, "user": 1}
    supersessions = result["catalog_item_supersessions"]
    assert supersessions["by_kind"] == {"release": 1, "master": 1}
    assert supersessions["opened_per_month"] == {"2026-09": 1, "2026-10": 1}
    assert (supersessions["open"], supersessions["closed"], supersessions["with_via"]) == (2, 0, 0)
    assert result["catalog_item_moves"]["rows"] == 0


def test_audit_counts_identity_runs_only(result):
    audit = result["admin_audit_log_identity"]
    assert audit["rows"] == 3
    assert "admin.login" not in audit["by_action"]
    assert (audit["apply_runs"], audit["apply_run_months"]) == (2, 2)
    assert audit["outcomes"]["release"] == {"reattached": 1, "guarded": 2, "failed": 0, "supersessions_opened": 1, "merged_with_dependents": 0}
    assert audit["outcomes"]["release_group"]["reattached"] == 1


def test_transitions_recorded_today(result):
    transitions = result["transitions"]
    assert transitions["linked_at_ingest"] == {"release": 4, "master": 2}
    assert transitions["superseded"] == {"catalog_reattachment/release": 1, "catalog_reattachment/master": 1}
    assert transitions["aliases_opened_by_supersession"] == {"musicbrainz": 2, "barcode": 1}
    assert transitions["aliases_closed_by_supersession"] == {"musicbrainz": 2, "barcode": 1}
    assert transitions["aliases_opened_after_mint_otherwise"] == {"musicbrainz": 6, "catalog_number": 1, "matrix": 2}
    assert transitions["non_catalog_aliases"] == {"user": 1}


def test_transitions_no_writer_can_produce_today_are_zero(result):
    transitions = result["transitions"]
    assert transitions["discogs_attached_after_musicbrainz"] == {}
    assert transitions["aliases_closed_otherwise"] == {}
    assert (transitions["supersessions_closed"], transitions["chain_compressed"]) == (0, 0)
    assert not any(key.startswith("edition_promotion/") for key in transitions["superseded"])


def test_ledger_shape(result):
    ledger = result["ledger"]
    assert ledger["editions"] == 10
    assert ledger["editions_with_events"] == 6
    assert ledger["editions_repaired"] == 1
    assert ledger["editions_events_multi_month"] == 1
    assert ledger["editions_by_work_count"] == {"0": 0, "1": 8, "2+": 2}
    assert ledger["works"] == 5
    assert ledger["works_with_2plus_evented_editions"] == 3
    assert ledger["works_with_2plus_evented_editions_multi_month"] == 1
    assert ledger["works_with_2plus_repaired_editions"] == 0
    assert ledger["evented_editions_per_work"] == {"p50": 2, "p90": 3, "p99": 3, "max": 3}
    assert (ledger["split_now"], ledger["unresolved_now"]) == (1, 1)


def test_counters_see_writers_that_do_not_exist_yet():
    result = identity_history(load(synthetic.with_writers_that_do_not_exist_yet()))
    transitions = result["transitions"]
    assert transitions["superseded"]["edition_promotion/release"] == 1
    assert (transitions["supersessions_closed"], transitions["chain_compressed"]) == (1, 1)
    assert result["catalog_item_moves"]["by_table"] == {"owned_copies": 1}
    ledger = result["ledger"]
    # The reverted promotion touched two editions; the open compressed row folds X9 into E8.
    assert ledger["editions_repaired"] == 4
    assert ledger["editions"] == 9


def test_percentile_disc_matches_postgresql():
    assert percentile_disc([], 0.5) is None
    assert percentile_disc([5], 0.99) == 5
    assert percentile_disc([1, 2, 3, 4], 0.5) == 2
    assert percentile_disc(list(range(1, 11)), 0.9) == 9
    assert percentile_disc(list(range(1, 101)), 0.99) == 99
