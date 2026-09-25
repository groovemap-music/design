"""The time-split join on invented snapshots: who counts as newly linked, what is
excluded, and that the query is the earlier record."""
import gzip
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _rec(n, title, discogs=(), masters=(), barcode=None):
    return {"source": "musicbrainz", "entity_kind": "release", "native_id": f"00000000-0000-4000-8000-{n:012d}",
            "title": title, "artists": ["Example Artist"], "artist_ids": [None], "artist_display": "Example Artist",
            "barcode": barcode, "labels": [{"name": "Imaginary Records", "catno": f"IMG {n}", "mbid": None}],
            "date": "2001", "country": "GB", "formats": ["CD"], "status": "Official",
            "release_group": {"id": None, "primary_type": "Album"}, "discogs_release_ids": list(discogs),
            "discogs_master_links": list(masters), "discogs_other_links": []}


def _write(path, recs):
    with gzip.open(path, "wt") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")


def test_timesplit_join(tmp_path):
    early = [
        _rec(1, "Already Linked", discogs=["900001"]),
        _rec(2, "Newly Linked"),
        _rec(3, "Stays Unlinked"),
        _rec(4, "Gains Two Links"),
        _rec(5, "Deleted Later"),
        _rec(6, "Master Only Before", masters=["800006"]),
    ]
    late = [
        _rec(1, "Already Linked", discogs=["900001"]),
        _rec(2, "Newly Linked (Edited)", discogs=["900002"], barcode="0012345678905"),
        _rec(3, "Stays Unlinked"),
        _rec(4, "Gains Two Links", discogs=["900004", "900044"]),
        _rec(6, "Master Only Before", discogs=["900006"], masters=["800006"]),
        _rec(7, "Created Between Dumps", discogs=["900007"]),
    ]
    _write(tmp_path / "early.jsonl.gz", early)
    _write(tmp_path / "late.jsonl.gz", late)
    subprocess.run([sys.executable, str(SCRIPTS / "build_timesplit.py"), str(tmp_path / "early.jsonl.gz"),
                    str(tmp_path / "late.jsonl.gz"), "--dev-mod", "1000000", "--out-dir", str(tmp_path)],
                   check=True, cwd=SCRIPTS, capture_output=True)
    stats = json.loads((tmp_path / "sample_stats.json").read_text())
    assert stats["early_unlinked"] == 5
    assert stats["early_unlinked_gained_link"] == 3
    assert stats["excluded_multi_link"] == 1
    assert stats["excluded_new_release_linked"] == 1
    assert stats["early_unlinked_absent_from_late"] == 1
    assert stats["newly_linked_eligible"] == 2
    assert stats["newly_linked_had_master_link"] == 1
    queries = [json.loads(line) for line in (tmp_path / "queries_test.jsonl").read_text().splitlines()]
    by_title = {q["title"]: q for q in queries}
    # The query is the earlier record: the edit made alongside the link is not visible.
    assert set(by_title) == {"Newly Linked", "Master Only Before"}
    assert by_title["Newly Linked"]["barcode"] is None
    assert by_title["Newly Linked"]["target_discogs_id"] == "900002"
    keys = json.loads((tmp_path / "blocking_keys.json").read_text())
    assert keys["targets"] == ["900002", "900006"]
    assert keys["barcodes"] == []
