"""Pin the Semantica 0.7.0 behaviours the report relies on. Skipped when semantica
is not installed (it lives only in the isolated spike venv)."""
import json
from pathlib import Path

import pytest

semantica = pytest.importorskip("semantica")
from semantica.deduplication import DuplicateDetector, SimilarityCalculator  # noqa: E402

from matching import semantica_entity, view_of  # noqa: E402

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "synthetic_editions.json").read_text())


def test_pinned_version():
    import importlib.metadata as md

    assert md.version("semantica") == "0.7.0"


def test_incremental_detect_excludes_type_mismatch_and_ranks_target():
    q = semantica_entity(view_of(FIXTURE["query"]))
    pool = [semantica_entity(view_of(r)) for r in FIXTURE["pool"]]
    det = DuplicateDetector()
    cands = det.incremental_detect([q], pool)
    ids = [c.entity2["id"] for c in cands]
    assert "discogs:master:800001" not in ids
    assert "discogs:release:900001" in ids
    assert "discogs:release:900005" not in ids


def test_property_similarity_is_fuzzy_on_identifiers():
    """A different barcode still earns most of the property credit: Semantica compares
    string properties with Jaro-Winkler, so identifiers are not an exact-match veto."""
    calc = SimilarityCalculator()
    a = {"name": "x", "properties": {"barcode": "0012345678905"}}
    b = {"name": "x", "properties": {"barcode": "0012345678912"}}
    assert calc.calculate_property_similarity(a, b) > 0.9
    c = {"name": "x", "properties": {}}
    assert calc.calculate_property_similarity(a, c) == 0.5  # missing = neutral, not a mismatch
