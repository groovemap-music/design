# SPDX-License-Identifier: MIT
"""The full-export extractor on an invented, tiny `mbdump` tarball in PostgreSQL COPY format."""

import io
import tarfile

import numpy as np

from extract_mb_history import core, derived


def tarball(members: dict[str, str]) -> io.BytesIO:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, text in members.items():
            data = text.encode()
            info = tarfile.TarInfo(f"mbdump/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    buffer.seek(0)
    return buffer


GID = "00000000-0000-4000-9000-0000000000{:02x}"


def test_core_keeps_discogs_release_links_only(tmp_path):
    members = {
        # id, parent, child_order, gid, entity_type0, entity_type1, name, ...
        "link_type": "76\t\\N\t0\tx\trelease\turl\tdiscogs\n77\t\\N\t0\ty\trelease\turl\tamazon asin\n",
        # id, link_type, ...
        "link": "500\t76\n501\t77\n",
        # id, gid, url, edits_pending, last_updated
        "url": ("1\tu1\thttps://www.discogs.com/release/900001-Some-Title\t0\t2020-01-01 00:00:00+00\n"
                "2\tu2\thttps://www.discogs.com/master/900002\t0\t2020-01-01 00:00:00+00\n"
                "3\tu3\thttps://www.amazon.com/dp/X\t0\t2020-01-01 00:00:00+00\n"),
        # id, link, entity0, entity1, edits_pending, last_updated, link_order, ...
        "l_release_url": ("10\t500\t7\t1\t0\t2026-03-10 12:00:00.5+00\t0\t\t\n"
                          "11\t500\t8\t2\t0\t2026-03-11 12:00:00+00\t0\t\t\n"
                          "12\t501\t7\t3\t0\t2026-03-12 12:00:00+00\t0\t\t\n"),
        # id, gid, name, artist_credit, release_group, ...
        "release": f"7\t{GID.format(7)}\tA\t1\t70\n8\t{GID.format(8)}\tB\t1\t70\n",
        "release_group": f"70\t{GID.format(0x70)}\tG\n",
    }
    out = tmp_path / "core.npz"
    core(tarball(members), str(out))
    arrays = np.load(out)
    assert arrays["discogs_id"].tolist() == [900001]  # the master URL and the Amazon link are dropped
    assert arrays["mbid"].tolist() == [GID.format(7)]
    assert arrays["group_mbid"].tolist() == [GID.format(0x70)]
    assert arrays["last_updated"].tolist() == [1773144000]


def test_derived_reads_date_added_and_null(tmp_path):
    out = tmp_path / "derived.npz"
    derived(tarball({"release_meta": "7\t2026-03-01 00:00:00+00\t\\N\t\\N\tf\n8\t\\N\t\\N\t\\N\tf\n"}), str(out))
    arrays = np.load(out)
    assert arrays["release_id"].tolist() == [7, 8]
    assert arrays["date_added"].tolist() == [1772323200, 0]
