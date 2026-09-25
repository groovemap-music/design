"""Baseline blocking/scoring and the Semantica encoding, on the synthetic fixture."""
import json
from pathlib import Path

from matching import BaselineConfig, BaselineIndex, baseline_score, semantica_entity, view_of

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "synthetic_editions.json").read_text())


def _setup():
    q = view_of(FIXTURE["query"])
    pool = [view_of(r) for r in FIXTURE["pool"]]
    return q, pool


def test_views_keep_provenance_and_kind():
    q, pool = _setup()
    assert q.key == "musicbrainz:release:00000000-0000-4000-8000-000000000001"
    assert q.release_group == "00000000-0000-4000-8000-0000000000b1"
    assert pool[0].key == "discogs:release:900001" and pool[0].master_id == "800001"
    assert pool[-1].key == "discogs:master:800001" and pool[-1].entity_kind == "master"
    assert q.barcodes == pool[0].barcodes == {"0012345678905"}
    assert ("imaginary records", "IMG101") in q.label_catnos & pool[0].label_catnos


def test_blocking_is_kind_aware_and_keyed():
    q, pool = _setup()
    index = BaselineIndex(pool)
    ids, _ = index.block(q, BaselineConfig())
    keys = {pool[i].key for i in ids}
    assert "discogs:release:900001" in keys
    assert "discogs:release:900005" not in keys  # shares no key
    assert "discogs:master:800001" not in keys  # kind-aware
    blind, _ = index.block(q, BaselineConfig(kind_aware=False))
    assert "discogs:master:800001" in {pool[i].key for i in blind}


def test_ablation_removes_blocks():
    q, pool = _setup()
    index = BaselineIndex(pool)
    ids, _ = index.block(q, BaselineConfig(drop=frozenset({"barcode", "catno", "title", "artist"})))
    assert ids == set()
    ids, _ = index.block(q, BaselineConfig(drop=frozenset({"artist"})))
    # title-only block also reaches the namesake-artist release
    assert "discogs:release:900004" in {pool[i].key for i in ids}


def test_stop_key():
    q, pool = _setup()
    index = BaselineIndex(pool)
    ids, diag = index.block(q, BaselineConfig(max_block=1))
    assert diag["stop_keys"] >= 1


def test_baseline_score_prefers_target_but_cannot_split_reused_barcode_pressing():
    q, pool = _setup()
    scores = {v.native_id: baseline_score(q, v) for v in pool if v.entity_kind == "release"}
    assert scores["900001"] > scores["900002"] > scores["900005"]
    assert scores["900001"] > scores["900004"]
    # 900003 reuses the barcode and catno and differs only by year and country: the
    # descriptors are all that separate a reused-barcode pressing.
    assert scores["900003"] == scores["900001"] - 2
    assert baseline_score(q, pool[2], frozenset({"descriptors"})) == baseline_score(q, pool[0], frozenset({"descriptors"}))


def test_semantica_entity_encoding_and_ablation():
    q, _ = _setup()
    e = semantica_entity(q)
    assert e["id"] == q.key and e["type"] == "release"
    assert e["name"] == "northern lights remastered"
    assert e["properties"]["barcode"] == "0012345678905"
    assert {"artist": "the example quartet"} in e["relationships"]
    d = semantica_entity(q, drop=frozenset({"barcode", "title"}), with_type=False)
    assert "barcode" not in d["properties"] and d["name"] == "" and "type" not in d
    raw = semantica_entity(q, normalized=False)
    assert raw["name"] == "Northern Lights (Remastered)"
    assert raw["properties"]["barcode"] == "012345678905"


def test_master_id_zero_means_no_master():
    rec = dict(FIXTURE["pool"][4], master_id="0")
    assert view_of(rec).master_id is None
