// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  extractLinks,
  findExposureIssues,
  validateActionReference,
  validateCanonicalCatalog,
  validateCatalogContract,
} from "./validate.mjs";

import schema from "../catalog/repositories.schema.json" with { type: "json" };
import fixture from "../fixtures/catalog-valid.json" with { type: "json" };
import catalog from "../catalog/repositories.json" with { type: "json" };

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const schemaPath = resolve(root, "catalog/repositories.schema.json");

function validateInstance(instance) {
  const directory = mkdtempSync(join(tmpdir(), "groovemap-catalog-test-"));
  const instancePath = join(directory, "instance.json");
  writeFileSync(instancePath, `${JSON.stringify(instance)}\n`, "utf8");
  try {
    return spawnSync("jsonschema", ["validate", schemaPath, instancePath, "--format-assertion"], {
      cwd: root,
      encoding: "utf8",
    });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

function mutate(mutator) {
  const instance = structuredClone(fixture);
  mutator(instance, instance.repositories[0]);
  return instance;
}

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

test("publication handoff implementation is local and non-mutating", () => {
  const script = readFileSync(resolve(root, "scripts/publication-readiness.mjs"), "utf8");
  assert.match(script, /publication_action_performed: false/);
  assert.match(script, /git\("status", "--porcelain"/);
  for (const forbidden of ["gh ", "tofu ", "git push", "visibility", "fetch(", "https.request"]) {
    assert.equal(script.includes(forbidden), false, `publication handoff contains forbidden operation: ${forbidden}`);
  }
});

test("catalog schema retains the exact public field boundary", () => {
  assert.deepEqual(validateCatalogContract(schema), []);
});

test("canonical catalog contains the exact sorted 20-repository set", () => {
  assert.deepEqual(validateCanonicalCatalog(catalog), []);
  assert.equal(catalog.repositories.length, 20);
});

test("catalog schema rejects private operational metadata fields", async (t) => {
  for (const field of [
    "branch_rule_id",
    "has_issues",
    "provider_id",
    "secret_repositories",
    "source_paths",
    "team_permission",
  ]) {
    await t.test(field, () => {
      const result = validateInstance(mutate((_catalog, repository) => { repository[field] = "excluded"; }));
      assert.equal(result.error, undefined);
      assert.equal(result.status, 2, `${field} unexpectedly passed:\n${result.stdout}${result.stderr}`);
    });
  }
});

test("standards validator accepts the complete synthetic fixture", () => {
  const result = validateInstance(fixture);
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0, `${result.stdout}${result.stderr}`);
});

test("standards validator rejects every declared catalog constraint", async (t) => {
  const cases = [
    ["top-level type", () => []],
    ["top-level additionalProperties", () => mutate((catalog) => { catalog.provider_id = 1; })],
    ["schema_version const", () => mutate((catalog) => { catalog.schema_version = 2; })],
    ["repositories type", () => mutate((catalog) => { catalog.repositories = {}; })],
    ["repositories uniqueItems", () => mutate((catalog, repository) => { catalog.repositories.push(structuredClone(repository)); })],
    ["repository type", () => mutate((catalog) => { catalog.repositories = [null]; })],
    ["repository additionalProperties", () => mutate((_catalog, repository) => { repository.provider_id = 1; })],
    ["name type", () => mutate((_catalog, repository) => { repository.name = 1; })],
    ["name pattern", () => mutate((_catalog, repository) => { repository.name = "Invalid_Name"; })],
    ["url type", () => mutate((_catalog, repository) => { repository.url = 1; })],
    ["url format", () => mutate((_catalog, repository) => { repository.url = "not a URL"; })],
    ["description type", () => mutate((_catalog, repository) => { repository.description = 1; })],
    ["description minLength", () => mutate((_catalog, repository) => { repository.description = ""; })],
    ["responsibilities minItems", () => mutate((_catalog, repository) => { repository.responsibilities = []; })],
    ["responsibilities uniqueItems", () => mutate((_catalog, repository) => { repository.responsibilities = ["one", "one"]; })],
    ["responsibilities item type", () => mutate((_catalog, repository) => { repository.responsibilities = [1]; })],
    ["responsibilities item minLength", () => mutate((_catalog, repository) => { repository.responsibilities = [""]; })],
    ["relationships uniqueItems", () => mutate((_catalog, repository) => { repository.relationships.push(structuredClone(repository.relationships[0])); })],
    ["relationship item type", () => mutate((_catalog, repository) => { repository.relationships = [null]; })],
    ["relationship additionalProperties", () => mutate((_catalog, repository) => { repository.relationships[0].provider_id = 1; })],
    ["relationship repository type", () => mutate((_catalog, repository) => { repository.relationships[0].repository = 1; })],
    ["relationship repository pattern", () => mutate((_catalog, repository) => { repository.relationships[0].repository = "Invalid_Name"; })],
    ["relationship kind type", () => mutate((_catalog, repository) => { repository.relationships[0].kind = 1; })],
    ["relationship kind minLength", () => mutate((_catalog, repository) => { repository.relationships[0].kind = ""; })],
    ["homepage type", () => mutate((_catalog, repository) => { repository.homepage = 1; })],
    ["homepage format", () => mutate((_catalog, repository) => { repository.homepage = "not a URL"; })],
    ["languages uniqueItems", () => mutate((_catalog, repository) => { repository.languages = ["JavaScript", "JavaScript"]; })],
    ["languages item type", () => mutate((_catalog, repository) => { repository.languages = [1]; })],
    ["languages item minLength", () => mutate((_catalog, repository) => { repository.languages = [""]; })],
    ["topics uniqueItems", () => mutate((_catalog, repository) => { repository.topics = ["design", "design"]; })],
    ["topics item type", () => mutate((_catalog, repository) => { repository.topics = [1]; })],
    ["topics item pattern", () => mutate((_catalog, repository) => { repository.topics = ["Invalid_Topic"]; })],
    ["license type", () => mutate((_catalog, repository) => { repository.license = 1; })],
    ["license minLength", () => mutate((_catalog, repository) => { repository.license = ""; })],
    ["commercial_license_available type", () => mutate((_catalog, repository) => { repository.commercial_license_available = "false"; })],
    ["release_units uniqueItems", () => mutate((_catalog, repository) => { repository.release_units = ["source", "source"]; })],
    ["release_units item type", () => mutate((_catalog, repository) => { repository.release_units = [1]; })],
    ["release_units item minLength", () => mutate((_catalog, repository) => { repository.release_units = [""]; })],
    ["destination_visibility enum", () => mutate((_catalog, repository) => { repository.destination_visibility = "internal"; })],
    ["publication_status enum", () => mutate((_catalog, repository) => { repository.publication_status = "unknown"; })],
  ];
  for (const field of ["schema_version", "repositories"]) {
    cases.push([`top-level required ${field}`, () => mutate((catalog) => { delete catalog[field]; })]);
  }
  for (const field of ["responsibilities", "relationships", "languages", "topics", "release_units"]) {
    cases.push([`${field} type`, () => mutate((_catalog, repository) => { repository[field] = {}; })]);
  }
  for (const field of schema.$defs.repository.required) {
    cases.push([`repository required ${field}`, () => mutate((_catalog, repository) => { delete repository[field]; })]);
  }
  for (const field of ["repository", "kind"]) {
    cases.push([`relationship required ${field}`, () => mutate((_catalog, repository) => { delete repository.relationships[0][field]; })]);
  }
  for (const [description, createInvalid] of cases) {
    await t.test(description, () => {
      const result = validateInstance(createInvalid());
      assert.equal(result.error, undefined);
      assert.equal(result.status, 2, `${description} unexpectedly passed:\n${result.stdout}${result.stderr}`);
    });
  }
});
