"""Concept C measurement end to end on an invented catalogue."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
GENRES = ["Alpha", "Beta", "Gamma, Delta, & Epsilon"]
STYLES = [f"S{i}" for i in range(12)]


def invented_dump(n: int = 400) -> tuple[str, str]:
    rng = np.random.default_rng(7)
    rel, mst = ["<releases>"], ["<masters>"]
    for i in range(1, n + 1):
        g = rng.choice(len(GENRES), size=int(rng.integers(1, 3)), replace=False)
        s = rng.choice(len(STYLES), size=int(rng.integers(0, 3)), replace=False)
        master = int(rng.integers(1, 60)) if rng.random() < 0.7 else 0
        rel.append(
            f'<release id="{i}" status="Accepted"><artists><artist><id>{int(rng.integers(1, 80))}</id></artist></artists>'
            f'<labels><label id="{int(rng.integers(1, 30))}"/></labels>'
            "<genres>" + "".join(f"<genre>{GENRES[x].replace('&', '&amp;')}</genre>" for x in g) + "</genres>"
            "<styles>" + "".join(f"<style>{STYLES[x]}</style>" for x in s) + "</styles>"
            f"<released>{1960 + i % 60}</released>"
            + (f"<master_id>{master}</master_id>" if master else "")
            + "</release>"
        )
    for m in range(1, 60):
        rel_style = STYLES[m % len(STYLES)]
        mst.append(f'<master id="{m}"><artists><artist><id>{m}</id></artist></artists><genres><genre>Alpha</genre></genres><styles><style>{rel_style}</style></styles><year>{1960 + m}</year></master>')
    rel.append("</releases>")
    mst.append("</masters>")
    return "\n".join(rel), "\n".join(mst)


def test_measure_taste_end_to_end(tmp_path):
    rel_xml, mst_xml = invented_dump()
    py = sys.executable
    subprocess.run([py, str(SCRIPTS / "extract_dump.py"), "releases", str(tmp_path / "releases_x.npz")], input=rel_xml.encode(), check=True, capture_output=True)
    subprocess.run([py, str(SCRIPTS / "extract_dump.py"), "masters", str(tmp_path / "masters_x.npz")], input=mst_xml.encode(), check=True, capture_output=True)
    subprocess.run([py, str(SCRIPTS / "aggregate.py"), str(tmp_path / "releases_x.npz"), str(tmp_path / "masters_x.npz"), str(tmp_path / "aggregates_x.npz")], check=True, capture_output=True)
    out = tmp_path / "taste.json"
    subprocess.run(
        [py, str(SCRIPTS / "measure_taste.py"), str(tmp_path / "releases_x.npz"), str(tmp_path / "masters_x.npz"), str(tmp_path / "aggregates_x.npz"), str(out), "--sizes", "20", "--collectors", "5"],
        check=True, capture_output=True, cwd=SCRIPTS,
    )
    res = json.loads(out.read_text())
    assert res["fit_evaluations"] == 5 * 30
    assert res["genre_names_with_comma_or_and"] == 1
    assert res["fit"]["depth"]["entries_target_pct"].get("none") == 100.0
    assert res["items"]["held_items"] == 100


def test_fastrp_pipeline_on_invented_dump(tmp_path):
    rel_xml, mst_xml = invented_dump()
    py = sys.executable
    subprocess.run([py, str(SCRIPTS / "extract_dump.py"), "releases", str(tmp_path / "releases_x.npz")], input=rel_xml.encode(), check=True, capture_output=True)
    subprocess.run([py, str(SCRIPTS / "extract_dump.py"), "masters", str(tmp_path / "masters_x.npz")], input=mst_xml.encode(), check=True, capture_output=True)
    subprocess.run([py, str(SCRIPTS / "aggregate.py"), str(tmp_path / "releases_x.npz"), str(tmp_path / "masters_x.npz"), str(tmp_path / "aggregates_x.npz")], check=True, capture_output=True)
    for _ in range(2):
        subprocess.run([py, str(SCRIPTS / "fastrp.py"), str(tmp_path / "releases_x.npz"), str(tmp_path / "masters_x.npz"), str(tmp_path / "aggregates_x.npz"), str(tmp_path / f"vec{_}.npz")], check=True, capture_output=True)
    a = np.load(tmp_path / "vec0.npz")["style_vectors"]
    b = np.load(tmp_path / "vec1.npz")["style_vectors"]
    assert a.shape == (len(STYLES), 128)
    assert np.array_equal(a, b)  # same dump, same bytes
    assert (np.abs(a).sum(axis=1) > 0).all()
