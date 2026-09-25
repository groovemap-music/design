"""Baseline blocking and scoring on the synthetic fixture: zwy's scores are unchanged,
and the score is a function of the ADR 0014 section 4 comparison vector alone."""
import json
from pathlib import Path

from matching import BaselineConfig, BaselineIndex, baseline_score, comparison, score_of, view_of

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "synthetic_editions.json").read_text())


def _setup():
    q = view_of(FIXTURE["query"])
    pool = [view_of(r) for r in FIXTURE["pool"]]
    return q, pool


def test_blocking_is_kind_aware_and_keyed():
    q, pool = _setup()
    index = BaselineIndex(pool)
    ids, _ = index.block(q, BaselineConfig())
    keys = {pool[i].key for i in ids}
    assert "discogs:release:900001" in keys
    assert "discogs:release:900005" not in keys
    assert "discogs:master:800001" not in keys


def test_scores_match_gm_design_zwy():
    q, pool = _setup()
    scores = {v.native_id: baseline_score(q, v) for v in pool if v.entity_kind == "release"}
    # barcode 8 + label/catno 4 + title 3 + artist 3 + year, format, country 3
    assert scores["900001"] == 21
    assert scores["900003"] == scores["900001"] - 2
    assert scores["900001"] > scores["900002"] > scores["900005"]
    assert baseline_score(q, pool[2], frozenset({"descriptors"})) == baseline_score(q, pool[0], frozenset({"descriptors"}))


def test_equal_scores_do_not_imply_equal_comparisons():
    # A barcode match alone (8) and catno+title+... can reach one score with different
    # evidence; section 4 ambiguity is about the evidence, not the number.
    a = (1, 0, 0, 0, 0, 0, 0)
    b = (0, 1, 2, 1, 0, 0, 0)  # 2 + 3 + 3
    assert score_of(a) == score_of(b) == 8
    assert a != b


def test_comparison_vector_levels():
    q, pool = _setup()
    assert comparison(q, pool[0]) == (1, 2, 2, 1, 1, 1, 1)
    assert comparison(q, pool[0], frozenset({"barcode", "descriptors"})) == (0, 2, 2, 1, 0, 0, 0)


def test_master_id_zero_means_no_master():
    rec = dict(FIXTURE["pool"][4], master_id="0")
    assert view_of(rec).master_id is None
