// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import test from "node:test";

import {
  extractLinks,
  findExposureIssues,
  validateActionReference,
  validateCatalog,
} from "./validate.mjs";

import schema from "../catalog/repositories.schema.json" with { type: "json" };
import fixture from "../fixtures/catalog-valid.json" with { type: "json" };

test("extractLinks returns local and remote Markdown targets", () => {
  assert.deepEqual(extractLinks("[local](docs/README.md) and ![remote](https://example.com/a.svg)"), [
    "docs/README.md",
    "https://example.com/a.svg",
  ]);
});

test("validateActionReference requires an immutable external revision", () => {
  assert.equal(validateActionReference("./.github/actions/local"), null);
  assert.equal(validateActionReference("owner/repo/action@0123456789abcdef0123456789abcdef01234567"), null);
  assert.match(validateActionReference("owner/repo/action@main"), /full commit/);
});

test("findExposureIssues detects private-boundary material without storing it", () => {
  assert.deepEqual(findExposureIssues(["discogs", "ography"].join("")), ["retired-project-name"]);
  assert.deepEqual(findExposureIssues(["/", "Users", "/operator/file"].join("")), ["host-local-path"]);
  assert.deepEqual(findExposureIssues("ordinary public design text"), []);
});

test("validateCatalog accepts the synthetic public fixture", () => {
  assert.deepEqual(validateCatalog(schema, fixture), []);
});

test("validateCatalog rejects fields outside the public allowlist", () => {
  const invalid = structuredClone(fixture);
  invalid.repositories[0].provider_id = 123;
  assert.match(validateCatalog(schema, invalid).join("\n"), /public field allowlist/);
});

test("validateCatalog rejects duplicate repository names", () => {
  const invalid = structuredClone(fixture);
  invalid.repositories.push(structuredClone(invalid.repositories[0]));
  assert.match(validateCatalog(schema, invalid).join("\n"), /duplicated/);
});
