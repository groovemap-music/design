#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Proxy 2's binding validation on the out-of-sample window (pre-registered at 8f7a5ed).

    python oos.py <dir with mb_release_20261021-001001.tsv.gz and mb_release_20261024-001001.tsv.gz> \\
        <dir with mbhist_core_20261024-*.npz and mbhist_derived_20261024-*.npz> results/oos_validation.json

The window is 2026-10-21 00:10:01 to 2026-10-24 00:10:01 UTC. Neither proxy has seen it.
The bar is unchanged: precision >= 0.90 and recall >= 0.90.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from guard import assert_aggregate_only
from months import link_history, read_json_releases, validate


T_A = int(datetime(2026, 10, 21, 0, 10, 1, tzinfo=UTC).timestamp())
T_B = int(datetime(2026, 10, 24, 0, 10, 1, tzinfo=UTC).timestamp())


def main() -> None:
    json_dir, hist_dir, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    core = next(hist_dir.glob("mbhist_core_20261024-*.npz"))
    derived = next(hist_dir.glob("mbhist_derived_20261024-*.npz"))
    history = link_history(core, derived, proxy=2)
    result = {"proxy_2_out_of_sample": validate(history, read_json_releases(json_dir / "mb_release_20261021-001001.tsv.gz"),
                                                read_json_releases(json_dir / "mb_release_20261024-001001.tsv.gz"), T_A, T_B)}
    assert_aggregate_only(result)
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
