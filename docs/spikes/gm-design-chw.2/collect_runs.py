# SPDX-License-Identifier: MIT
"""Gather the embed.py run records and the subset statistics into results/, paths stripped.

Usage: ``uv run python collect_runs.py ~/.cache/groovemap-spikes/graphemb/work``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    work = Path(sys.argv[1]).expanduser()
    out = Path(__file__).parent / "results"
    runs = {}
    for record in sorted((work / "emb").glob("*.json")):
        data = json.loads(record.read_text())
        data["args"] = {k: v for k, v in data["args"].items() if k not in {"subset", "out"}}
        runs[record.stem] = data
    (out / "runs.json").write_text(json.dumps(runs, indent=1, sort_keys=True) + "\n")
    (out / "subset.json").write_text((work / "s10" / "subset.json").read_text() + "\n")
    print(f"{len(runs)} runs")


if __name__ == "__main__":
    main()
