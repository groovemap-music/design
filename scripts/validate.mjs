// SPDX-License-Identifier: MIT

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, extname, relative, resolve, sep } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { mapFixtureInput, validateTaxonomy } from "./media-mapper.mjs";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const AUTOMATION_REVISION = "833cb464507678c38ab78bd4718ce697399463e9";
const MIT_SHA256 = "9572d39cdc09c0b2cd792a14fef5dcc4ed1b955d9b1ea2a3d0c058221fa5f391";
const REQUIRED_REPOSITORY_FIELDS = [
  "commercial_license_available",
  "description",
  "destination_visibility",
  "homepage",
  "languages",
  "license",
  "name",
  "publication_status",
  "relationships",
  "release_units",
  "responsibilities",
  "topics",
  "url",
];
const EXPECTED_REPOSITORIES = [
  ".github",
  "analytics-engine",
  "automation",
  "catalog-api",
  "database-schema",
  "deployment",
  "design",
  "discogs-graph-enricher",
  "discogs-ingestion",
  "discogs-sql-loader",
  "graph-explorer",
  "groovemap-music.github.io",
  "infra",
  "mcp-server",
  "musicbrainz-graph-enricher",
  "musicbrainz-ingestion",
  "musicbrainz-sql-loader",
  "operations-console",
  "operations-toolkit",
  "planning-archive",
  "python-libraries",
];
const REQUIRED_FILES = [
  ".github/dependabot.yml",
  ".github/workflows/ci.yml",
  ".gitignore",
  ".mise.toml",
  "AGENTS.md",
  "CONTRIBUTING.md",
  "Justfile",
  "LICENSE",
  "NOTICE",
  "PUBLICATION.md",
  "README.md",
  "TRADEMARKS.md",
  "brand/README.md",
  "brand/assets.sha256",
  "brand/render.mjs",
  "brand/tokens.json",
  "catalog/README.md",
  "catalog/repositories.json",
  "catalog/repositories.schema.json",
  "docs/README.md",
  "docs/adr/0001-repository-ownership-boundary.md",
  "docs/adr/0002-shared-automation-boundary.md",
  "docs/adr/0003-agpl-commercial-licensing.md",
  "docs/adr/0004-beadhive-compatible-branch-policy.md",
  "docs/adr/0005-source-owned-catalog-ingestion.md",
  "docs/adr/0006-opentelemetry-metrics.md",
  "docs/adr/0007-canonical-media-taxonomy.md",
  "docs/adr/0008-victoriametrics-tracing-runtime-alerting.md",
  "docs/programs/media-taxonomy.md",
  "fixtures/catalog-valid.json",
  "scripts/build.mjs",
  "scripts/check-governance.mjs",
  "scripts/check-secrets.sh",
  "scripts/media-mapper.mjs",
  "scripts/publication-readiness.mjs",
  "scripts/validate.mjs",
  "scripts/validate.test.mjs",
  "taxonomy/media/README.md",
  "taxonomy/media/v1/media-block.schema.json",
  "taxonomy/media/v1/media-taxonomy.json",
  "taxonomy/media/v1/media-taxonomy.schema.json",
];
const EXPOSURE_PATTERNS = [
  ["retired-project-name", new RegExp(["discogs", "ography"].join(""), "i")],
  ["host-local-path", /(?:\/Users\/|\/var\/folders\/|[A-Z]:\\Users\\)/],
  ["private-ip-url", /https?:\/\/(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/],
  ["private-hostname", /https?:\/\/[^\s)>]*(?:\.internal|\.corp|\.lan|\.local)(?::\d+)?/i],
  ["private-key", new RegExp(["-----BEGIN", "(?:[A-Z ]+ )?PRIVATE", "KEY-----"].join(" "))],
  ["github-token", /\b(?:ghp|github_pat)_[A-Za-z0-9_]{12,}\b/],
  ["private-planning-path", /(?:\.planning\/|docs\/superpowers\/)/i],
  ["encrypted-operations", /(?:sops\.yaml|age1[ac-hj-np-z02-9]{20,})/i],
];

export function trackedFiles(root = ROOT) {
  const result = spawnSync("git", ["ls-files", "-z"], { cwd: root, encoding: "utf8" });
  requireCondition(result.status === 0, `git ls-files failed: ${result.stderr.trim()}`);
  return result.stdout.split("\0").filter(Boolean).map((path) => resolve(root, path));
}

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

function sorted(values) {
  return [...values].sort((left, right) => left.localeCompare(right));
}

function sameValues(left, right) {
  return JSON.stringify(sorted(left)) === JSON.stringify(sorted(right));
}

export function extractLinks(markdown) {
  return [...markdown.matchAll(/!?\[[^\]]*\]\(([^)\s]+)(?:\s+["'][^"']*["'])?\)/g)].map((match) => match[1]);
}

export function validateActionReference(reference) {
  if (reference.startsWith("./")) return null;
  return /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_./-]+)?@[a-f0-9]{40}$/.test(reference)
    ? null
    : `external action reference is not pinned to a full commit: ${reference}`;
}

export function findExposureIssues(content) {
  return EXPOSURE_PATTERNS.filter(([, pattern]) => pattern.test(content)).map(([name]) => name);
}

export function validateCatalogContract(schema) {
  const errors = [];
  const repositorySchema = schema?.$defs?.repository;
  const schemaFields = Object.keys(repositorySchema?.properties ?? {});
  if (schema.$schema !== "https://json-schema.org/draft/2020-12/schema") errors.push("schema must use JSON Schema 2020-12");
  if (schema["x-license"] !== "MIT") errors.push("schema must declare MIT license metadata");
  if (schema.additionalProperties !== false || repositorySchema?.additionalProperties !== false) {
    errors.push("catalog and repository objects must reject undeclared fields");
  }
  if (!sameValues(schemaFields, REQUIRED_REPOSITORY_FIELDS)) errors.push("schema field allowlist differs from the public catalog contract");
  if (!sameValues(repositorySchema?.required ?? [], REQUIRED_REPOSITORY_FIELDS)) errors.push("every public repository field must be explicit");
  return errors;
}

export function validateCanonicalCatalog(catalog) {
  const errors = [];
  const repositories = catalog?.repositories ?? [];
  const names = repositories.map((repository) => repository.name);
  if (!sameValues(names, EXPECTED_REPOSITORIES)) errors.push(`catalog must contain the exact ${EXPECTED_REPOSITORIES.length}-repository organization set`);
  if (JSON.stringify(names) !== JSON.stringify(sorted(names))) errors.push("catalog repositories must be sorted by name");
  if (new Set(names).size !== names.length) errors.push("catalog repository names must be unique");
  for (const repository of repositories) {
    const relationshipTargets = repository.relationships.map((relationship) => relationship.repository);
    if (relationshipTargets.some((target) => !EXPECTED_REPOSITORIES.includes(target))) {
      errors.push(`${repository.name} has a relationship to an unknown repository`);
    }
    if (new Set(relationshipTargets.map((target, index) => `${target}:${repository.relationships[index].kind}`)).size !== repository.relationships.length) {
      errors.push(`${repository.name} has a duplicate relationship`);
    }
  }

  const relationshipsFor = (name) => repositories.find((repository) => repository.name === name)?.relationships ?? [];
  const hasRelationship = (name, target, kind) =>
    relationshipsFor(name).some((relationship) => relationship.repository === target && relationship.kind === kind);
  const sourceConsumers = {
    "discogs-ingestion": ["discogs-graph-enricher", "discogs-sql-loader"],
    "musicbrainz-ingestion": ["musicbrainz-graph-enricher", "musicbrainz-sql-loader"],
  };
  for (const [producer, consumers] of Object.entries(sourceConsumers)) {
    for (const consumer of consumers) {
      if (!hasRelationship(producer, consumer, "publishes-events-to")) errors.push(`${producer} must publish events to ${consumer}`);
      if (!hasRelationship(consumer, producer, "consumes-events-from")) errors.push(`${consumer} must consume events from ${producer}`);
    }
  }
  for (const [consumer, otherProducer] of [
    ["discogs-graph-enricher", "musicbrainz-ingestion"],
    ["discogs-sql-loader", "musicbrainz-ingestion"],
    ["musicbrainz-graph-enricher", "discogs-ingestion"],
    ["musicbrainz-sql-loader", "discogs-ingestion"],
  ]) {
    if (hasRelationship(consumer, otherProducer, "consumes-events-from")) errors.push(`${consumer} must not consume events from ${otherProducer}`);
  }
  for (const composer of ["catalog-api", "operations-console", "operations-toolkit"]) {
    for (const producer of Object.keys(sourceConsumers)) {
      if (!hasRelationship(composer, producer, "composes-contract-from")) errors.push(`${composer} must compose the contract from ${producer}`);
    }
  }
  return errors;
}

function checkRequiredFiles() {
  for (const path of REQUIRED_FILES) requireCondition(existsSync(resolve(ROOT, path)), `required file is missing: ${path}`);
}

function checkLinks() {
  for (const path of trackedFiles().filter((item) => extname(item) === ".md")) {
    for (const rawLink of extractLinks(readFileSync(path, "utf8"))) {
      const link = rawLink.replace(/^<|>$/g, "");
      if (/^(?:https?:|mailto:)/.test(link) || link.startsWith("#")) continue;
      const targetPart = decodeURIComponent(link.split("#", 1)[0]);
      if (!targetPart) continue;
      const target = resolve(dirname(path), targetPart);
      requireCondition(target === ROOT || target.startsWith(`${ROOT}${sep}`), `${relative(ROOT, path)}: link escapes the repository: ${link}`);
      const exists = existsSync(target) && (statSync(target).isFile() || existsSync(resolve(target, "README.md")));
      requireCondition(exists, `${relative(ROOT, path)}: broken local link: ${link}`);
    }
  }
  console.log("Verified local Markdown links.");
}

function checkCatalog() {
  const schemaPath = resolve(ROOT, "catalog/repositories.schema.json");
  const schema = JSON.parse(readFileSync(schemaPath, "utf8"));
  const errors = validateCatalogContract(schema);
  requireCondition(errors.length === 0, `catalog schema contract:\n- ${errors.join("\n- ")}`);

  const instances = [resolve(ROOT, "fixtures/catalog-valid.json")];
  const catalogPath = resolve(ROOT, "catalog/repositories.json");
  requireCondition(existsSync(catalogPath), "canonical repository catalog is missing");
  const catalog = JSON.parse(readFileSync(catalogPath, "utf8"));
  const catalogErrors = validateCanonicalCatalog(catalog);
  requireCondition(catalogErrors.length === 0, `canonical catalog contract:\n- ${catalogErrors.join("\n- ")}`);
  instances.push(catalogPath);
  for (const arguments_ of [["metaschema", schemaPath], ["validate", schemaPath, ...instances, "--format-assertion"]]) {
    const result = spawnSync("jsonschema", arguments_, { cwd: ROOT, encoding: "utf8" });
    requireCondition(!result.error, `unable to execute the pinned JSON Schema validator: ${result.error?.message}`);
    requireCondition(result.status === 0, `JSON Schema validation failed:\n${result.stdout}${result.stderr}`);
  }
  console.log(`Verified the 2020-12 public catalog schema against ${instances.length} catalog document(s).`);
}

export function validateFixtureSet(taxonomy, fixtures) {
  const errors = [];
  const names = new Set();
  for (const fixture of fixtures) {
    for (const field of ["name", "provider", "description", "input", "expected"]) {
      if (!(field in fixture)) errors.push(`fixture ${fixture.name ?? "?"} is missing ${field}`);
    }
    if (names.has(fixture.name)) errors.push(`duplicate fixture name ${fixture.name}`);
    names.add(fixture.name);
    let actual;
    try {
      actual = mapFixtureInput(taxonomy, fixture);
    } catch (error) {
      errors.push(`fixture ${fixture.name}: ${error.message}`);
      continue;
    }
    if (JSON.stringify(actual) !== JSON.stringify(fixture.expected)) errors.push(`fixture ${fixture.name} expected output differs from the reference mapper`);
  }
  for (const required of ["discogs-7-inch-45-single", "discogs-2xlp-gatefold-reissue", "discogs-hybrid-sacd", "discogs-box-set-cd-and-vinyl", "discogs-file-flac", "discogs-unknown-format", "musicbrainz-12-inch-vinyl", "musicbrainz-digital-media", "musicbrainz-other-medium"]) {
    if (!names.has(required)) errors.push(`required conformance fixture is missing: ${required}`);
  }
  return errors;
}

function runJsonSchema(arguments_, message) {
  const result = spawnSync("jsonschema", arguments_, { cwd: ROOT, encoding: "utf8" });
  requireCondition(!result.error, `unable to execute the pinned JSON Schema validator: ${result.error?.message}`);
  requireCondition(result.status === 0, `${message}:\n${result.stdout}${result.stderr}`);
}

function checkTaxonomy() {
  const base = resolve(ROOT, "taxonomy/media/v1");
  const taxonomySchema = resolve(base, "media-taxonomy.schema.json");
  const blockSchema = resolve(base, "media-block.schema.json");
  const taxonomyPath = resolve(base, "media-taxonomy.json");
  for (const schema of [taxonomySchema, blockSchema]) runJsonSchema(["metaschema", schema], `${relative(ROOT, schema)} is not a valid 2020-12 schema`);
  runJsonSchema(["validate", taxonomySchema, taxonomyPath, "--format-assertion"], "media taxonomy does not satisfy its schema");
  const taxonomy = JSON.parse(readFileSync(taxonomyPath, "utf8"));
  const errors = validateTaxonomy(taxonomy);
  requireCondition(errors.length === 0, `media taxonomy structure:\n- ${errors.join("\n- ")}`);
  const fixturePaths = sorted(readdirSync(resolve(base, "fixtures")).filter((name) => name.endsWith(".json"))).map((name) => resolve(base, "fixtures", name));
  requireCondition(fixturePaths.length > 0, "media taxonomy conformance fixtures are missing");
  const fixtures = fixturePaths.map((path) => JSON.parse(readFileSync(path, "utf8")));
  const fixtureErrors = validateFixtureSet(taxonomy, fixtures);
  requireCondition(fixtureErrors.length === 0, `media taxonomy fixtures:\n- ${fixtureErrors.join("\n- ")}`);
  const expectedDirectory = resolve(ROOT, ".build", "media-fixtures");
  rmSync(expectedDirectory, { recursive: true, force: true });
  mkdirSync(expectedDirectory, { recursive: true });
  const expectedPaths = fixtures.map((fixture) => {
    const path = resolve(expectedDirectory, `${fixture.name}.json`);
    writeFileSync(path, `${JSON.stringify(fixture.expected)}\n`, "utf8");
    return path;
  });
  runJsonSchema(["validate", blockSchema, ...expectedPaths, "--format-assertion"], "a fixture's expected media block does not satisfy the media block schema");
  rmSync(expectedDirectory, { recursive: true, force: true });
  console.log(`Verified the media taxonomy, its schemas, and ${fixtures.length} conformance fixtures against the reference mapper.`);
}

function checkWorkflow() {
  const workflowPath = resolve(ROOT, ".github/workflows/ci.yml");
  const workflow = readFileSync(workflowPath, "utf8");
  const callers = [...workflow.matchAll(/uses:\s+(\S+)/g)].map((match) => match[1]);
  requireCondition(callers.length === 1, "CI must contain exactly one external reusable-workflow reference");
  for (const caller of callers) requireCondition(validateActionReference(caller) === null, validateActionReference(caller));
  requireCondition(
    callers[0] === `groovemap-music/automation/.github/workflows/reusable-ci.yml@${AUTOMATION_REVISION}`,
    "CI must pin the approved automation revision",
  );
  for (const marker of [
    "pull_request:",
    "branches: [main]",
    "language: mixed",
    "setup-command: just setup",
    "check-command: just check",
    "coverage-command: just coverage",
    "audit-command: just audit",
    "license-command: just license-check",
    "secret-scan-command: just secret-scan",
    "package-command: just build",
    "install-command: just install-check",
    "coverage-files: coverage/lcov.info",
  ]) requireCondition(workflow.includes(marker), `CI contract marker is missing: ${marker}`);
  for (const forbidden of ["github.actor", "dependabot[bot]", "pull_request_target", "secrets: inherit", "if:"]) {
    requireCondition(!workflow.toLowerCase().includes(forbidden.toLowerCase()), `CI must not contain an actor-specific or broad-credential path: ${forbidden}`);
  }
  const jobs = workflow.split("jobs:\n", 2)[1] ?? "";
  requireCondition((jobs.match(/^  [a-zA-Z0-9_-]+:\s*$/gm) ?? []).length === 1, "CI must expose one caller job on every pull request");

  const dependabot = readFileSync(resolve(ROOT, ".github/dependabot.yml"), "utf8");
  for (const marker of ["package-ecosystem: github-actions", "labels: [dependencies, github-actions]", "interval: weekly"]) {
    requireCondition(dependabot.includes(marker), `Dependabot contract marker is missing: ${marker}`);
  }
  console.log("Verified immutable CI and identical Dependabot pull-request coverage.");
}

function checkAssets() {
  const entries = readFileSync(resolve(ROOT, "brand/assets.sha256"), "utf8").trim().split("\n");
  requireCondition(entries.length === 12, "brand checksum manifest must cover exactly 12 outputs");
  const seen = new Set();
  for (const entry of entries) {
    const match = entry.match(/^([a-f0-9]{64})  (brand\/assets\/[a-z0-9.-]+)$/);
    requireCondition(match, `invalid brand checksum entry: ${entry}`);
    const [, expected, path] = match;
    requireCondition(!seen.has(path), `duplicate brand checksum path: ${path}`);
    seen.add(path);
    const actual = createHash("sha256").update(readFileSync(resolve(ROOT, path))).digest("hex");
    requireCondition(actual === expected, `${path} differs from the reviewed infra-source output`);
  }
  console.log("Verified byte identity of 12 reviewed brand outputs.");
}

function checkLicense() {
  const licenseHash = createHash("sha256").update(readFileSync(resolve(ROOT, "LICENSE"))).digest("hex");
  requireCondition(licenseHash === MIT_SHA256, "LICENSE must remain the unmodified approved MIT text");
  const notice = readFileSync(resolve(ROOT, "NOTICE"), "utf8");
  requireCondition(/MIT License/.test(notice) && /does not grant trademark rights/i.test(notice), "NOTICE must retain the copyright/trademark boundary");
  for (const path of ["Justfile", "scripts/build.mjs", "scripts/check-governance.mjs", "scripts/check-secrets.sh", "scripts/media-mapper.mjs", "scripts/publication-readiness.mjs", "scripts/validate.mjs", "scripts/validate.test.mjs"]) {
    requireCondition(readFileSync(resolve(ROOT, path), "utf8").includes("SPDX-License-Identifier: MIT"), `${path} is missing MIT license metadata`);
  }
  console.log("Verified MIT license metadata and the separate trademark boundary.");
}

function checkDependencies() {
  const mise = readFileSync(resolve(ROOT, ".mise.toml"), "utf8");
  for (const marker of ['gitleaks = "8.30.1"', 'jsonschema = "16.8.0"', 'just = "1.57.0"', 'node = "24.20.0"', 'trufflehog = "3.97.1"']) {
    requireCondition(mise.includes(marker), `tool pin is missing: ${marker}`);
  }
  for (const path of ["package.json", "package-lock.json", "pyproject.toml", "uv.lock", "Cargo.toml", "Cargo.lock"]) {
    requireCondition(!existsSync(resolve(ROOT, path)), `unexpected dependency manifest requires an audit policy: ${path}`);
  }
  console.log("Verified the exact zero-dependency tool boundary.");
}

function checkPublicSafety() {
  for (const path of trackedFiles()) {
    const content = readFileSync(path, "utf8");
    const issues = findExposureIssues(content);
    requireCondition(issues.length === 0, `${relative(ROOT, path)} contains prohibited public-boundary material: ${issues.join(", ")}`);
  }
  console.log("Verified the repository's public-content boundary.");
}

function checkPolicy() {
  checkRequiredFiles();
  checkWorkflow();
  checkAssets();
  checkPublicSafety();
}

function run(mode) {
  const checks = {
    "--assets": checkAssets,
    "--catalog": checkCatalog,
    "--dependencies": checkDependencies,
    "--license": checkLicense,
    "--links": checkLinks,
    "--policy": checkPolicy,
    "--taxonomy": checkTaxonomy,
  };
  requireCondition(mode in checks, `unknown validation mode: ${mode}`);
  checks[mode]();
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) run(process.argv[2] ?? "--policy");
