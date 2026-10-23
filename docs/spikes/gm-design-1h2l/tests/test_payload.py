# SPDX-License-Identifier: MIT
"""Invariants of the draft aggregation rule, over invented discographies."""
import random

import pytest

from payload_model import Master, Release, build_payload, payload_bytes, plane_budgets

ROOT = 1


def discography(seed: int, n_releases: int, n_masters: int, masterless: float, joint: float, owned: float = 0.0):
    rng = random.Random(seed)
    masters = {m: Master(m, rng.choice([None, *range(1950, 2026)]), rng.randint(3, 40)) for m in range(1000, 1000 + n_masters)}
    has_main = set()
    releases = []
    for rid in range(10_000, 10_000 + n_releases):
        mid = None if rng.random() < masterless or not masters else rng.choice(list(masters))
        is_main = mid is not None and mid not in has_main
        if is_main:
            has_main.add(mid)
        credit = (ROOT,) if rng.random() >= joint else tuple(sorted({ROOT, rng.randint(2, 60)}))
        state = "owned" if rng.random() < owned else "none"
        releases.append(Release(rid, mid, is_main, rng.choice([None, *range(1950, 2026)]), rng.randint(1, 60), credit, state))
    names = {a: rng.randint(2, 30) for a in range(1, 61)}
    return releases, masters, names


def check(payload, releases, budget):
    credits, masters, rels = payload["planes"]
    ids = [{e["id"] for e in plane["nodes"] + plane["aggregates"]} for plane in payload["planes"]]
    # Nesting: every entry below the credit plane names a parent on the plane above.
    for level in (1, 2):
        for entry in payload["planes"][level]["nodes"] + payload["planes"][level]["aggregates"]:
            assert entry["parent"] in ids[level - 1], entry
    # Budget per plane.
    if budget:
        for plane, limit in zip(payload["planes"], plane_budgets(budget), strict=True):
            assert len(plane["nodes"]) + len(plane["aggregates"]) <= limit
    # Conservation of releases across the three planes.
    assert sum(n["releases"] for n in credits["nodes"]) + sum(a["releases"] for a in credits["aggregates"]) == len(releases)
    assert sum(n["releases"] for n in masters["nodes"]) + sum(a["releases"] for a in masters["aggregates"]) == len(releases)
    shown = len(rels["nodes"]) + sum(a["releases"] for a in rels["aggregates"])
    assert shown + payload["totals"]["releases_only_in_master_aggregates"] == len(releases)
    # Conservation of masters.
    folded = sum(a["masters"] for a in masters["aggregates"])
    assert len(masters["nodes"]) + folded == payload["totals"]["masters"]


@pytest.mark.parametrize("budget", [0, 48, 200, 500, (3, 12, 16), (6, 12, 16), (1, 1, 1), (2, 5, 3)])
@pytest.mark.parametrize(
    ("n_releases", "n_masters", "masterless", "joint"),
    [(1, 0, 1.0, 0.0), (8, 3, 0.3, 0.2), (300, 60, 0.4, 0.1), (3000, 900, 0.5, 0.3), (6000, 2500, 0.2, 0.6)],
)
def test_rule_invariants(budget, n_releases, n_masters, masterless, joint):
    releases, masters, names = discography(n_releases + n_masters, n_releases, n_masters, masterless, joint)
    for signed_in in (False, True):
        payload = build_payload(ROOT, releases, masters, names, budget, signed_in=signed_in)
        check(payload, releases, budget)


def test_no_budget_shows_everything():
    releases, masters, names = discography(7, 400, 90, 0.3, 0.2)
    payload = build_payload(ROOT, releases, masters, names, None)
    assert len(payload["planes"][2]["nodes"]) == 400
    assert not payload["planes"][2]["aggregates"]
    assert len(payload["planes"][1]["nodes"]) == payload["totals"]["masters"]


def test_owned_releases_survive_aggregation():
    releases, masters, names = discography(11, 3000, 400, 0.1, 0.0, owned=0.01)
    payload = build_payload(ROOT, releases, masters, names, 500, signed_in=True)
    owned = {f"r:{r.id}" for r in releases if r.state == "owned" and r.master_id is not None}
    kept_masters = {n["id"] for n in payload["planes"][1]["nodes"]}
    # Masters holding state are never folded, and step 1 keeps their owned releases.
    assert all(f"m:{r.master_id}" in kept_masters for r in releases if r.state == "owned" and r.master_id is not None)
    shown = {n["id"] for n in payload["planes"][2]["nodes"]}
    if shown:
        assert owned <= shown


def test_signed_in_adds_state_fields_only():
    releases, masters, names = discography(3, 50, 10, 0.2, 0.1)
    anon = build_payload(ROOT, releases, masters, names, None)
    signed = build_payload(ROOT, releases, masters, names, None, signed_in=True)
    assert "state" not in anon["planes"][2]["nodes"][0]
    assert signed["planes"][2]["nodes"][0]["state"] == "none"
    assert payload_bytes(signed) > payload_bytes(anon)


def test_root_credit_is_first_even_when_only_joint():
    releases = [Release(1, None, False, 1999, 5, (ROOT, 2))]
    payload = build_payload(ROOT, releases, {}, {ROOT: 4, 2: 4}, 48)
    assert payload["planes"][0]["nodes"][0]["id"] == "c:1"
    check(payload, releases, 48)


@pytest.mark.parametrize(("budget", "kind"), [(500, "masters"), (100, "masters"), (48, "band")])
def test_each_folding_level_is_reached_and_fits(budget, kind):
    releases, masters, names = discography(5, 6000, 2500, 0.3, 0.9)
    payload = build_payload(ROOT, releases, masters, names, budget)
    kinds = {a["kind"] for a in payload["planes"][1]["aggregates"]}
    assert kind in kinds
    check(payload, releases, budget)


def test_s1_budget_keeps_root_and_folds_the_rest():
    releases, masters, names = discography(13, 2000, 600, 0.4, 0.5)
    payload = build_payload(ROOT, releases, masters, names, (3, 12, 16))
    credits, mplane, rplane = payload["planes"]
    assert credits["nodes"][0]["id"] == "c:1" and len(credits["nodes"]) == 2 and credits["aggregates"]
    assert len(mplane["nodes"]) + len(mplane["aggregates"]) <= 12
    assert len(rplane["nodes"]) + len(rplane["aggregates"]) <= 16
    assert payload["budget"] == {"credits": 3, "masters": 12, "releases": 16}


def test_budget_shape_is_validated():
    with pytest.raises(ValueError):
        plane_budgets((5, 3, 16))
