#!/usr/bin/env python3
"""Check every installed dependency of this harness against catalog-api's license policy.

Adapted from gm-design-chw.2's ``license_check.py``. The inventory is read from this
virtualenv's distribution metadata and handed, as the pip-licenses JSON shape, to
catalog-api's own ``scripts.check_dependency_licenses`` in catalog-api's virtualenv
(read-only), so the policy code is the policy, not a copy of it. It also records the
installed size of each distribution, as dependency-cost evidence.

Usage: ``uv run python scripts/license_check.py /path/to/catalog-api results/licenses.json``
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from importlib.metadata import distributions
from pathlib import Path

POLICY = r"""
import json, sys
from scripts.check_dependency_licenses import license_families, validate_inventory
payload = json.load(sys.stdin)
report = [{**p, "families": sorted(license_families(p["License"]))} for p in payload["packages"]]
try:
    validate_inventory(payload["packages"], payload["locked"], "")
    verdict = "pass"
except ValueError as error:
    verdict = f"fail: {error}"
forbidden = [p["Name"] for p in report if set(p["families"]) & {"GPL", "AGPL"}]
reciprocal = [p["Name"] for p in report if set(p["families"]) & {"LGPL", "MPL"}]
print(json.dumps({"verdict_with_empty_notices": verdict, "forbidden_gpl_agpl": forbidden,
                  "reciprocal_needing_notice": reciprocal, "packages": report}))
"""


def license_of(meta) -> str:
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    raw = (meta.get("License") or "").strip()
    if classifiers:
        return " AND ".join(classifiers)
    return raw.splitlines()[0] if raw else "UNKNOWN"


def installed_bytes(dist) -> int:
    total = 0
    for f in dist.files or []:
        try:
            total += Path(dist.locate_file(f)).stat().st_size
        except OSError:
            pass
    return total


def main() -> None:
    catalog_api, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    dists = list(distributions())
    sizes = {d.metadata["Name"]: installed_bytes(d) for d in dists}
    packages = sorted(
        ({"Name": d.metadata["Name"], "Version": d.version, "License": license_of(d.metadata)} for d in dists),
        key=lambda p: p["Name"].lower(),
    )
    lock = tomllib.loads((Path(__file__).resolve().parent.parent / "uv.lock").read_text())
    locked = {p["name"]: p["version"] for p in lock["package"] if "version" in p}
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [str(catalog_api / ".venv/bin/python"), "-c", POLICY],
        cwd=catalog_api, env=env, input=json.dumps({"packages": packages, "locked": locked}),
        check=True, capture_output=True, text=True,
    )
    report = json.loads(result.stdout)
    for p in report["packages"]:
        p["installed_mb"] = round(sizes.get(p["Name"], 0) / 1e6, 1)
    report["python"] = sys.version.split()[0]
    report["installed_total_mb"] = round(sum(sizes.values()) / 1e6, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n")
    print("forbidden:", report["forbidden_gpl_agpl"], "reciprocal:", report["reciprocal_needing_notice"],
          "total MB:", report["installed_total_mb"])
    for p in report["packages"]:
        if p["families"] or p["License"] == "UNKNOWN":
            print(p)


if __name__ == "__main__":
    main()
