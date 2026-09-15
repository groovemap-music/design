#!/usr/bin/env python3
"""Validate producer catalog fixtures in a matching Python consumer environment."""

from __future__ import annotations

import argparse
import copy
import importlib.metadata
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


sys.dont_write_bytecode = True


def require_rejection(validator: Draft202012Validator, document: dict[str, Any], name: str) -> str:
    try:
        validator.validate(document)
    except ValidationError:
        return name
    raise AssertionError(f"mutation survived contract validation: {name}")


def load_binding(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("catalog_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("catalog contract binding could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract_root", type=Path)
    parser.add_argument("expected_source", choices=("discogs", "musicbrainz"))
    args = parser.parse_args()

    schema = json.loads((args.contract_root / "schemas/event.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    binding = load_binding(args.contract_root / "bindings/python/catalog_contract.py")
    if binding.CONTRACT_NAME != "groovemap.catalog-events" or binding.CONTRACT_VERSION != 1:
        raise AssertionError("Python binding contract identity drifted")
    if binding.SOURCE != args.expected_source:
        raise AssertionError("Python binding source identity drifted")

    fixtures = []
    for path in sorted((args.contract_root / "fixtures").glob("*.json")):
        document = json.loads(path.read_text())
        validator.validate(document)
        fixtures.append((path.name, document))
    if not fixtures:
        raise AssertionError("producer contract has no fixtures")

    data_fixture = next(document for _, document in fixtures if document.get("type") == "data")
    identity_mutant = copy.deepcopy(data_fixture)
    identity_mutant["id"] = 7
    extraction_fixture = next(document for _, document in fixtures if document.get("type") == "extraction_complete")
    started_at_mutant = copy.deepcopy(extraction_fixture)
    started_at_mutant["started_at"] = "not-a-date-time"

    result = {
        "contract": binding.CONTRACT_NAME,
        "contract_version": binding.CONTRACT_VERSION,
        "source": binding.SOURCE,
        "validator": f"jsonschema {importlib.metadata.version('jsonschema')}",
        "fixtures_validated": len(fixtures),
        "fixture_names": [name for name, _ in fixtures],
        "mutations_killed": [
            require_rejection(validator, identity_mutant, "integer-for-string-identity"),
            require_rejection(validator, started_at_mutant, "malformed-started-at"),
        ],
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
