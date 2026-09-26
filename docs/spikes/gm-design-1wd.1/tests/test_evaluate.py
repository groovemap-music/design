"""Tie-aware metrics, the ADR 0014 section 4 ambiguity rule, and the ban on id or
insertion-order tie-breaks, on invented candidate sets."""
import json
import random
from pathlib import Path

from evaluate import evaluate_run, expected_hit, groups_of, target_position
from matching import comparison, score_of, view_of

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "synthetic_editions.json").read_text())
META = {"script": "latin", "barcode_on_query": "yes", "catno_on_query": "yes", "format": "cd", "decade": "2000s"}


def _views():
    return {v.key: v for v in (view_of(r) for r in FIXTURE["pool"])}


def _row(q, target, cands):
    return {"q": q, "target": target, "candidates": [[k, score_of(tuple(v)), list(v)] for k, v in cands]}


def _eval(rows, views=None):
    views = views if views is not None else _views()
    meta = {r["q"]: META for r in rows}
    return evaluate_run(rows, views, {}, {}, [8, 15], meta)


def _strip_diagnostics(res):
    return {k: v for k, v in res.items() if not k.startswith("diagnostic")}


TOP = (1, 2, 2, 1, 1, 1, 1)  # 21
SIB = (1, 2, 2, 1, 0, 1, 0)  # 19


def test_positions_are_order_free():
    row = _row("q1", "900001", [("discogs:release:900003", TOP), ("discogs:release:900001", TOP),
                                ("discogs:release:900002", SIB)])
    assert target_position(row) == (0, 2)
    assert expected_hit((0, 2), 1) == 0.5 and expected_hit((0, 2), 2) == 1.0
    assert expected_hit((3, 4), 5) == 0.5 and expected_hit(None, 10) == 0.0


def test_unique_top_expected_and_guaranteed_recall():
    rows = [
        _row("q1", "900001", [("discogs:release:900001", TOP), ("discogs:release:900002", SIB)]),
        _row("q2", "900001", [("discogs:release:900003", TOP), ("discogs:release:900001", TOP)]),
        _row("q3", "900001", [("discogs:release:900002", SIB)]),
        _row("q4", "900001", []),
    ]
    res = _eval(rows)["all"]
    assert res["coverage_pct"] == 50.0
    assert res["unique_top_recall@1_pct"] == 25.0
    assert res["expected_recall@1_pct"] == 37.5  # 1 + 0.5 over 4
    assert res["guaranteed_recall@1_pct"] == 25.0
    assert res["top_group_recall_pct"] == 50.0
    assert res["expected_recall@5_pct"] == 50.0


def test_no_tie_is_broken_by_id_or_insertion_order():
    """ADR 0014 section 4: on linked data the target is the lowest id in most tie
    groups, so an id tie-break would inflate recall. Every metric must be identical
    whether the target has the lowest or the highest id in its tie, and whatever order
    the candidates arrive in."""
    views = _views()
    low = _row("q1", "900001", [("discogs:release:900001", TOP), ("discogs:release:900003", TOP),
                                ("discogs:release:900002", SIB)])
    # The same evidence with the target holding the higher id of the tie.
    views_hi = dict(views)
    views_hi["discogs:release:999999"] = views["discogs:release:900001"]
    high = _row("q1", "999999", [("discogs:release:999999", TOP), ("discogs:release:900003", TOP),
                                 ("discogs:release:900002", SIB)])
    base = _strip_diagnostics(_eval([low], views))
    assert _strip_diagnostics(_eval([high], views_hi)) == base
    rng = random.Random(7)
    for _ in range(20):
        shuffled = dict(low, candidates=rng.sample(low["candidates"], len(low["candidates"])))
        assert _strip_diagnostics(_eval([shuffled], views)) == base
    assert base["all"]["expected_recall@1_pct"] == 50.0
    assert base["all"]["unique_top_recall@1_pct"] == 0.0
    # The diagnostic sees the difference, which is what it is for.
    assert _eval([low], views)["diagnostic_lowest_id_in_tie_groups"]["target_is_lowest_id"] == 1
    assert _eval([high], views_hi)["diagnostic_lowest_id_in_tie_groups"]["target_is_lowest_id"] == 0


def test_ambiguity_is_field_equality_not_score_equality():
    views = _views()
    same_evidence = [["discogs:release:900001", 21.0, list(TOP)], ["discogs:release:900003", 21.0, list(TOP)]]
    assert len(groups_of(same_evidence, None, views, strict=False)) == 1
    a, b = (1, 0, 0, 0, 0, 0, 0), (0, 1, 2, 1, 0, 0, 0)
    same_score = [["discogs:release:900001", 8.0, list(a)], ["discogs:release:900003", 8.0, list(b)]]
    assert len(groups_of(same_score, None, views, strict=False)) == 2
    res = _eval([_row("q1", "900001", [("discogs:release:900001", a), ("discogs:release:900003", b)])])
    assert res["tied_top_queries"] == 1
    assert res["ambiguity"]["comparison_vector"]["leading_group_ambiguous"] == 0


def test_strict_ambiguity_also_needs_equal_values():
    views = _views()
    q = view_of(FIXTURE["query"])
    t, sib = views["discogs:release:900001"], views["discogs:release:900003"]
    # Equal vectors against a query that carries no country or year: loose says one group.
    vec = comparison(q, t, frozenset({"descriptors"}))
    cands = [[t.key, 18.0, list(vec)], [sib.key, 18.0, list(vec)]]
    assert len(groups_of(cands, q, views, strict=False)) == 1
    # Strict compares the values of every field the query carries; the two differ on
    # year and country, which the query carries, so they are separable.
    assert len(groups_of(cands, q, views, strict=True)) == 2


def test_review_queue_counts_members_and_groups():
    rows = [_row("q1", "900001", [("discogs:release:900001", TOP), ("discogs:release:900003", TOP),
                                  ("discogs:release:900002", SIB), ("discogs:release:900004", (0, 0, 2, 1, 0, 0, 0))])]
    r8 = _eval(rows)["review"]["8"]
    assert r8["queue_per_query"]["mean"] == 3  # 21, 21, 19 clear 8; 6 does not
    assert r8["queue_groups_per_query"]["mean"] == 2
    assert r8["precision_of_queue_pct"] == round(100 / 3, 2)
    assert r8["confusion"]["correct_in_tied_top"] == 1
