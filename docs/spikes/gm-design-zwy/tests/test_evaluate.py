"""Hard-negative classes and the metric arithmetic, on the synthetic fixture."""
import json
from pathlib import Path

from evaluate import classify, evaluate_run
from matching import view_of

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "synthetic_editions.json").read_text())


def _views():
    return {v.key: v for v in (view_of(r) for r in FIXTURE["pool"])}


def test_hard_negative_classes():
    views = _views()
    t = views["discogs:release:900001"]
    assert classify(t, t) == set()
    assert classify(views["discogs:release:900003"], t) == {"shared_barcode", "sibling_same_format"}
    assert classify(views["discogs:release:900002"], t) == {"sibling_diff_format"}
    assert classify(views["discogs:release:900004"], t) == {"near_identical_title", "namesake_artist"}
    assert classify(views["discogs:master:800001"], t) == {"release_vs_master"}
    assert classify(views["discogs:release:900005"], t) == set()


def _row(q, rank, top, scores, n):
    return {"q": q, "target": "900001", "n_candidates": n, "target_rank": rank,
            "target_score": scores[rank - 1] if rank else None, "top": top, "scores": scores}


def test_evaluate_run_separates_coverage_from_ranking_and_counts_review_load():
    views = _views()
    rows = [
        # target ranked 2nd behind the reused-barcode pressing
        _row("q1", 2, [["discogs:release:900003", 15, 0], ["discogs:release:900001", 14, 0]], [15, 14], 2),
        # target ranked 1st
        _row("q2", 1, [["discogs:release:900001", 16, 0], ["discogs:release:900002", 7, 0]], [16, 7], 2),
        # target not in the candidate set; the master is
        _row("q3", None, [["discogs:master:800001", 9, 0]], [9], 1),
        # nothing surfaced
        _row("q4", None, [], [], 0),
    ]
    meta = {q: {"script": "latin", "has_barcode": True, "has_catno": True} for q in ("q1", "q2", "q3", "q4")}
    present = {"q1": {"shared_barcode": 1}}
    res = evaluate_run(rows, views, present, [8, 15], meta)
    assert res["coverage_pct"] == 50.0
    assert res["recall@1_pct"] == 25.0 and res["recall@5_pct"] == 50.0
    assert res["mrr"] == round((0.5 + 1.0) / 4, 4)
    assert res["zero_candidate_queries"] == 1
    r8 = res["review"]["8"]
    assert r8["confusion"] == {"top_is_correct": 1, "correct_in_queue_not_top": 1,
                               "only_wrong_candidates": 1, "empty_queue": 1}
    assert r8["false_positives_per_query"] == round(2 / 4, 3)
    r15 = res["review"]["15"]
    assert r15["confusion"]["only_wrong_candidates"] == 1  # q1: only the wrong pressing clears 15
    hn = res["hard_negatives"]
    assert hn["shared_barcode"]["queries_with_class_in_pool"] == 1
    assert hn["shared_barcode"]["outranks_target"] == 1 and hn["shared_barcode"]["is_rank1"] == 1
    assert hn["sibling_diff_format"]["outranks_target"] == 0
    assert hn["release_vs_master"]["is_rank1"] == 1
