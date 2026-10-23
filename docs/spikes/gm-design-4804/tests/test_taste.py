"""Fit evidence and its atlas mapping on an invented collection."""
import taste
from taste import Collection, Release


GENRES = ["Alpha", "Beta", "Gamma, Delta, & Epsilon", "Gamma"]


def held():
    return [
        Release(1, 10, (100,), (500,), ("Alpha",), ("A1",), "One"),
        Release(2, 11, (100,), (500,), ("Alpha",), ("A1", "A2"), "Two"),
        Release(3, 12, (101,), (501,), ("Beta",), ("B1",), "Three"),
    ]


def test_components_and_mapping():
    c = Collection.fold(held())
    cand = Release(9, 11, (100, 102), (502,), ("Alpha", "Beta"), ("A1", "B1", "N1"), "Nine")
    out = taste.fit_entries(c, cand, siblings_held=[2])
    assert out["redundancy"]["score"] == 1.0
    assert out["bridge"]["score"] == 1.0 and out["bridge"]["entries"][0]["genres"] == ["Alpha", "Beta"]
    assert out["depth"]["entries"][0] == {"dimension": "artist", "entity": 100, "kind": "thread"}
    master_of = {2: 11}
    targets = {k: [taste.atlas_target(e, master_of, GENRES) for e in v["entries"]] for k, v in out.items()}
    assert targets["depth"] == ["none"]
    assert targets["bridge"] == ["edge", "label"]
    assert targets["redundancy"] == ["position"]
    assert set(targets["affinity"]) == {"position", "none"}
    assert all(len(v["capped"]) <= 3 for v in out.values())


def test_bridge_string_with_comma_genre_is_ambiguous():
    named = "Alpha, Gamma, Delta, & Epsilon and Beta"
    assert taste.split_bridge(named, GENRES) == [["Alpha", "Gamma, Delta, & Epsilon", "Beta"]]
    # Two different picked lists render to the same string once a genre name embeds ", ".
    g2 = ["X", "Y", "X, Y", "Z"]
    assert len(taste.split_bridge("X, Y and Z", g2)) == 2
    assert taste.atlas_target({"dimension": "genre", "entity": "X, Y and Z", "kind": "bridge"}, {}, g2) == "ambiguous"


def test_title_duplicate_has_no_position():
    c = Collection.fold(held())
    cand = Release(20, 0, (100,), (599,), ("Alpha",), ("A1",), "one ")
    red = taste.fit_entries(c, cand)["redundancy"]
    assert red["score"] == 0.3
    assert taste.atlas_target(red["entries"][0], {}, GENRES) == "none"
