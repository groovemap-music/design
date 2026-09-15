#!/usr/bin/env python3
"""Run the frozen audit's source mutants in disposable Git archives."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Mutation:
    name: str
    repository: str
    revision: str
    source_path: str
    before: str
    after: str
    test_args: tuple[str, ...]
    python_path: str


REVISIONS = {
    "python-libraries": "24704f5fd48d3ef4fff29398585e9924e225b0c5",
    "catalog-api": "7e6f21f01cd645f552cdf7ac54ccdecdfb2554df",
    "musicbrainz-graph-enricher": "fa8ad811d8989f1bf87dcffdfe24ecb8a15deb93",
    "discogs-sql-loader": "0f7b5d6ed679cf7233fe6118ab407391928a71c9",
}


def materialize(repository: Path, revision: str, destination: Path) -> None:
    archive = destination.parent / f"{destination.name}.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), revision],
        cwd=repository,
        check=True,
    )
    destination.mkdir()
    with tarfile.open(archive) as source:
        source.extractall(destination, filter="data")


def mutate_once(path: Path, before: str, after: str) -> None:
    source = path.read_text()
    if source.count(before) != 1:
        raise AssertionError(f"mutation anchor count is {source.count(before)}, expected 1: {path.name}")
    path.write_text(source.replace(before, after))


def main() -> None:
    parser = argparse.ArgumentParser()
    for repository in REVISIONS:
        parser.add_argument(f"--{repository}", required=True, type=Path)
    args = parser.parse_args()
    roots = {name: getattr(args, name.replace("-", "_")) for name in REVISIONS}

    mutations = (
        Mutation(
            "reject-settlement-requeues",
            "python-libraries",
            REVISIONS["python-libraries"],
            "src/common/delivery.py",
            "await delivery.nack(requeue=False)",
            "await delivery.nack(requeue=True)",
            ("tests/test_delivery.py",),
            "src",
        ),
        Mutation(
            "nlq-skips-shared-revocation-state",
            "catalog-api",
            REVISIONS["catalog-api"],
            "api/routers/nlq.py",
            "payload = await validate_token(token, _jwt_secret, _redis)",
            "payload = await validate_token(token, _jwt_secret, None)",
            ("tests/test_nlq_token_revocation.py",),
            ".",
        ),
        Mutation(
            "integer-discogs-artist-id-not-normalized",
            "musicbrainz-graph-enricher",
            REVISIONS["musicbrainz-graph-enricher"],
            "brainzgraphinator/_projections.py",
            "    discogs_id = str(discogs_id)\n    result = await tx.run(\n        \"MATCH (a:Artist {id: $discogs_id}) \"",
            "    result = await tx.run(\n        \"MATCH (a:Artist {id: $discogs_id}) \"",
            ("tests/test_brainzgraphinator.py", "-k", "test_enrich_artist_coerces_discogs_id_to_string"),
            ".",
        ),
        Mutation(
            "purge-veto-excludes-exact-boundary",
            "discogs-sql-loader",
            REVISIONS["discogs-sql-loader"],
            "tableinator/record_persistence.py",
            "if delete_fraction >= self.purge_max_delete_fraction:",
            "if delete_fraction > self.purge_max_delete_fraction:",
            ("tests/test_tableinator.py", "-k", "test_vetoes_at_fraction_boundary"),
            ".",
        ),
    )

    results = []
    with tempfile.TemporaryDirectory(prefix="groovemap-targeted-audit-") as directory:
        temporary_root = Path(directory)
        for index, mutation in enumerate(mutations):
            repository = roots[mutation.repository]
            destination = temporary_root / f"probe-{index}"
            materialize(repository, mutation.revision, destination)
            mutate_once(destination / mutation.source_path, mutation.before, mutation.after)
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(destination / mutation.python_path)
            command = [str(repository / ".venv/bin/python"), "-m", "pytest", "-q", *mutation.test_args]
            completed = subprocess.run(command, cwd=destination, env=environment, capture_output=True, text=True, check=False)
            if completed.returncode == 0:
                raise AssertionError(f"mutation survived: {mutation.name}")
            output = f"{completed.stdout}\n{completed.stderr}"
            if "failed" not in output.lower():
                raise AssertionError(f"mutation did not produce a test failure: {mutation.name}")
            results.append(
                {
                    "name": mutation.name,
                    "repository": mutation.repository,
                    "revision": mutation.revision,
                    "source_path": mutation.source_path,
                    "test_command": "python -m pytest -q " + " ".join(mutation.test_args),
                    "mutant_exit_code": completed.returncode,
                    "verdict": "killed",
                }
            )
    print(json.dumps({"mutations": results, "survivors": 0}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
