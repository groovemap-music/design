// SPDX-License-Identifier: MIT

import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, extname, relative, resolve, sep } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { validateTaxonomy } from "./media-mapper.mjs";
import {
  extractLinks,
  findExposureIssues,
  sorted,
  validateActionReference,
  validateCanonicalCatalog,
  validateCatalogContract,
  validateCompanyFixtureSet,
  validateCompanyRoleVocabulary,
  validateEventEnvelopeContract,
  validateEventFixtureSet,
  validateEventVocabulary,
  validateFixtureSet,
  validateIdentifierFixtureSet,
  validateIdentifierVocabulary,
  validateIdentityVocabulary,
  validateOrganizationVerification,
  validateRepowiseDefectRisk,
  validateSharedDeliveryRollout,
  validateTargetedDefectAudit,
  validateTelemetryDecision,
} from "./validation-policy.mjs";
import { ROOT, sha256 } from "./tooling.mjs";
export {
  extractLinks,
  findExposureIssues,
  validateActionReference,
  validateCanonicalCatalog,
  validateCatalogContract,
  validateEventEnvelopeContract,
  validateEventFixtureSet,
  validateEventVocabulary,
  validateFixtureSet,
  validateIdentityVocabulary,
  validateOrganizationVerification,
  validateRepowiseDefectRisk,
  validateSharedDeliveryRollout,
  validateTargetedDefectAudit,
  validateTelemetryDecision,
} from "./validation-policy.mjs";

const AUTOMATION_REVISION = "833cb464507678c38ab78bd4718ce697399463e9";
const MIT_SHA256 = "9572d39cdc09c0b2cd792a14fef5dcc4ed1b955d9b1ea2a3d0c058221fa5f391";
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
  "docs/adr/0009-native-identity-and-provider-aliases.md",
  "docs/adr/0010-first-party-events-consent-and-deletion.md",
  "docs/adr/0011-catalog-identifiers-and-manufacturing-credits.md",
  "docs/audits/organization-wide-verification-2026-09-13.md",
  "docs/programs/catalog-identifiers.md",
  "docs/audits/repowise-defect-risk-2026-09-14.md",
  "docs/audits/shared-delivery-rollout-2026-09-14.md",
  "docs/audits/targeted-defect-audit-2026-09-14.md",
  "docs/programs/media-taxonomy.md",
  "docs/programs/native-identity-and-events.md",
  "fixtures/catalog-valid.json",
  "scripts/build.mjs",
  "scripts/audit-catalog-fixtures.py",
  "scripts/audit-disposable-mutations.py",
  "scripts/audit-real-database-mutations.py",
  "scripts/check-governance.mjs",
  "scripts/check-recipes.mjs",
  "scripts/check-recipes.test.mjs",
  "scripts/check-secrets.sh",
  "scripts/media-mapper.mjs",
  "scripts/publication-readiness.mjs",
  "scripts/tooling.mjs",
  "scripts/validate.mjs",
  "scripts/validate.test.mjs",
  "scripts/validation-policy.mjs",
  "taxonomy/company-roles/README.md",
  "taxonomy/company-roles/v1/company-block.schema.json",
  "taxonomy/company-roles/v1/company-roles.json",
  "taxonomy/company-roles/v1/company-roles.schema.json",
  "taxonomy/company-roles/v1/fixtures/discogs-company-catalogue-number.json",
  "taxonomy/company-roles/v1/fixtures/discogs-distribution-and-marketing.json",
  "taxonomy/company-roles/v1/fixtures/discogs-issuing-label-excluded.json",
  "taxonomy/company-roles/v1/fixtures/discogs-malformed-entries.json",
  "taxonomy/company-roles/v1/fixtures/discogs-manufacturing-and-print.json",
  "taxonomy/company-roles/v1/fixtures/discogs-no-companies.json",
  "taxonomy/company-roles/v1/fixtures/discogs-pressing-and-transfer-master.json",
  "taxonomy/company-roles/v1/fixtures/discogs-recording-facilities.json",
  "taxonomy/company-roles/v1/fixtures/discogs-rights-holders.json",
  "taxonomy/company-roles/v1/fixtures/discogs-unmapped-role.json",
  "taxonomy/events/README.md",
  "taxonomy/events/v1/event-envelope.schema.json",
  "taxonomy/events/v1/event-types.json",
  "taxonomy/events/v1/event-types.schema.json",
  "taxonomy/events/v1/fixtures/event-account-erasure-requested.json",
  "taxonomy/events/v1/fixtures/event-account-export-requested.json",
  "taxonomy/events/v1/fixtures/event-collection-item-added.json",
  "taxonomy/events/v1/fixtures/event-collection-item-removed.json",
  "taxonomy/events/v1/fixtures/event-collection-item-updated.json",
  "taxonomy/events/v1/fixtures/event-consent-granted.json",
  "taxonomy/events/v1/fixtures/event-consent-revoked.json",
  "taxonomy/events/v1/fixtures/event-recommendation-dismissed.json",
  "taxonomy/events/v1/fixtures/event-recommendation-hidden.json",
  "taxonomy/events/v1/fixtures/event-recommendation-opened.json",
  "taxonomy/events/v1/fixtures/event-recommendation-saved.json",
  "taxonomy/events/v1/fixtures/event-recommendation-shown.json",
  "taxonomy/events/v1/fixtures/event-search-query.json",
  "taxonomy/events/v1/fixtures/event-search-result-impression.json",
  "taxonomy/events/v1/fixtures/event-wantlist-item-added.json",
  "taxonomy/events/v1/fixtures/event-wantlist-item-removed.json",
  "taxonomy/events/v1/fixtures/impression-recommendation-shown.json",
  "taxonomy/events/v1/fixtures/impression-search-result.json",
  "taxonomy/events/v1/fixtures/invalid-event-missing-consent-purposes.json",
  "taxonomy/events/v1/fixtures/invalid-event-unknown-type.json",
  "taxonomy/events/v1/fixtures/invalid-impression-missing-candidate-set-id.json",
  "taxonomy/events/v1/fixtures/invalid-impression-missing-policy-id.json",
  "taxonomy/events/v1/impression.schema.json",
  "taxonomy/identifiers/README.md",
  "taxonomy/identifiers/v1/fixtures/discogs-absent-catalogue-number.json",
  "taxonomy/identifiers/v1/fixtures/discogs-asin-and-isrc.json",
  "taxonomy/identifiers/v1/fixtures/discogs-barcode-and-catalogue-number.json",
  "taxonomy/identifiers/v1/fixtures/discogs-duplicate-alias-values.json",
  "taxonomy/identifiers/v1/fixtures/discogs-label-code-and-rights-society.json",
  "taxonomy/identifiers/v1/fixtures/discogs-malformed-entries.json",
  "taxonomy/identifiers/v1/fixtures/discogs-mapped-to-other.json",
  "taxonomy/identifiers/v1/fixtures/discogs-matrix-runout-inscriptions.json",
  "taxonomy/identifiers/v1/fixtures/discogs-no-identifiers.json",
  "taxonomy/identifiers/v1/fixtures/discogs-unmapped-type.json",
  "taxonomy/identifiers/v1/identifier-block.schema.json",
  "taxonomy/identifiers/v1/identifier-types.json",
  "taxonomy/identifiers/v1/identifier-types.schema.json",
  "taxonomy/identity/README.md",
  "taxonomy/identity/v1/identity-vocabulary.json",
  "taxonomy/identity/v1/identity-vocabulary.schema.json",
  "taxonomy/media/README.md",
  "taxonomy/media/v1/media-block.schema.json",
  "taxonomy/media/v1/media-taxonomy.json",
  "taxonomy/media/v1/media-taxonomy.schema.json",
  "verification/organization-wide-v1.json",
  "verification/repowise-defect-risk-v1.json",
  "verification/shared-delivery-rollout-v1.json",
  "verification/targeted-defect-audit-protocol-v1.json",
  "verification/targeted-defect-audit-v1.json",
];

export function trackedFiles(root = ROOT) {
  const result = spawnSync("git", ["ls-files", "-z"], { cwd: root, encoding: "utf8" });
  requireCondition(result.status === 0, `git ls-files failed: ${result.stderr.trim()}`);
  return result.stdout.split("\0").filter(Boolean).map((path) => resolve(root, path));
}

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
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

function expectJsonSchemaFailure(arguments_, message) {
  const result = spawnSync("jsonschema", arguments_, { cwd: ROOT, encoding: "utf8" });
  requireCondition(!result.error, `unable to execute the pinned JSON Schema validator: ${result.error?.message}`);
  requireCondition(result.status !== 0, message);
}

function checkIdentity() {
  const base = resolve(ROOT, "taxonomy/identity/v1");
  const schemaPath = resolve(base, "identity-vocabulary.schema.json");
  const vocabularyPath = resolve(base, "identity-vocabulary.json");
  runJsonSchema(["metaschema", schemaPath], `${relative(ROOT, schemaPath)} is not a valid 2020-12 schema`);
  runJsonSchema(["validate", schemaPath, vocabularyPath, "--format-assertion"], "the identity vocabulary does not satisfy its schema");
  const vocabulary = JSON.parse(readFileSync(vocabularyPath, "utf8"));
  const errors = validateIdentityVocabulary(vocabulary);
  requireCondition(errors.length === 0, `identity vocabulary:\n- ${errors.join("\n- ")}`);
  console.log(
    `Verified the identity vocabulary and its schema: ${vocabulary.entity_kinds.length} entity kinds, ${vocabulary.providers.length} providers, ${vocabulary.sources.length} alias sources.`,
  );
}

function checkEvents() {
  const base = resolve(ROOT, "taxonomy/events/v1");
  const vocabularySchema = resolve(base, "event-types.schema.json");
  const envelopeSchema = resolve(base, "event-envelope.schema.json");
  const impressionSchema = resolve(base, "impression.schema.json");
  for (const schema of [vocabularySchema, envelopeSchema, impressionSchema]) {
    runJsonSchema(["metaschema", schema], `${relative(ROOT, schema)} is not a valid 2020-12 schema`);
  }
  const vocabularyPath = resolve(base, "event-types.json");
  runJsonSchema(["validate", vocabularySchema, vocabularyPath, "--format-assertion"], "the event-type vocabulary does not satisfy its schema");
  const vocabulary = JSON.parse(readFileSync(vocabularyPath, "utf8"));
  const vocabularyErrors = validateEventVocabulary(vocabulary);
  requireCondition(vocabularyErrors.length === 0, `event-type vocabulary:\n- ${vocabularyErrors.join("\n- ")}`);
  const contractErrors = validateEventEnvelopeContract(
    JSON.parse(readFileSync(envelopeSchema, "utf8")),
    JSON.parse(readFileSync(impressionSchema, "utf8")),
    vocabulary,
  );
  requireCondition(contractErrors.length === 0, `event envelope contract:\n- ${contractErrors.join("\n- ")}`);

  const fixtureDirectory = resolve(base, "fixtures");
  const fixtureFiles = sorted(readdirSync(fixtureDirectory).filter((name) => name.endsWith(".json")));
  requireCondition(fixtureFiles.length > 0, "event conformance fixtures are missing");
  const fixtures = fixtureFiles.map((file) => ({ file, ...JSON.parse(readFileSync(resolve(fixtureDirectory, file), "utf8")) }));
  const fixtureErrors = validateEventFixtureSet(vocabulary, fixtures);
  requireCondition(fixtureErrors.length === 0, `event fixtures:\n- ${fixtureErrors.join("\n- ")}`);

  const expectedDirectory = resolve(ROOT, ".build", "event-fixtures");
  rmSync(expectedDirectory, { recursive: true, force: true });
  mkdirSync(expectedDirectory, { recursive: true });
  const write = (name, value) => {
    const path = resolve(expectedDirectory, `${name}.json`);
    writeFileSync(path, `${JSON.stringify(value)}\n`, "utf8");
    return path;
  };
  const schemaFor = { event: envelopeSchema, impression: impressionSchema };
  const payloads = new Map();
  const accepted = { event: [], impression: [] };
  for (const fixture of fixtures) {
    const path = write(fixture.name, fixture.document);
    if (fixture.valid === false) {
      expectJsonSchemaFailure(
        ["validate", schemaFor[fixture.envelope], path, "--format-assertion"],
        `fixture ${fixture.name} must be rejected by the ${fixture.envelope} envelope but was accepted`,
      );
      continue;
    }
    accepted[fixture.envelope].push(path);
    if (fixture.envelope !== "event") continue;
    const type = vocabulary.event_types.find((entry) => entry.id === fixture.document.event_type);
    const group = payloads.get(type.payload_schema) ?? [];
    group.push(write(`${fixture.name}-payload`, fixture.document.payload));
    payloads.set(type.payload_schema, group);
  }
  for (const [envelope, paths] of Object.entries(accepted)) {
    runJsonSchema(["validate", schemaFor[envelope], ...paths, "--format-assertion"], `a fixture does not satisfy the ${envelope} envelope schema`);
  }
  for (const [reference, paths] of sorted([...payloads.keys()]).map((key) => [key, payloads.get(key)])) {
    const name = reference.slice("#/$defs/".length);
    const payloadSchema = write(`${name}.schema`, { $schema: "https://json-schema.org/draft/2020-12/schema", $ref: reference, $defs: vocabulary.$defs });
    runJsonSchema(["validate", payloadSchema, ...paths, "--format-assertion"], `a fixture payload does not satisfy ${reference}`);
  }
  rmSync(expectedDirectory, { recursive: true, force: true });
  console.log(
    `Verified the event-type vocabulary, both envelope schemas, and ${fixtures.length} conformance fixtures covering ${vocabulary.event_types.length} event types.`,
  );
}

function checkIdentifiers() {
  const base = resolve(ROOT, "taxonomy/identifiers/v1");
  const vocabularySchema = resolve(base, "identifier-types.schema.json");
  const blockSchema = resolve(base, "identifier-block.schema.json");
  const vocabularyPath = resolve(base, "identifier-types.json");
  for (const schema of [vocabularySchema, blockSchema]) {
    runJsonSchema(["metaschema", schema], `${relative(ROOT, schema)} is not a valid 2020-12 schema`);
  }
  runJsonSchema(["validate", vocabularySchema, vocabularyPath, "--format-assertion"], "the identifier vocabulary does not satisfy its schema");
  const vocabulary = JSON.parse(readFileSync(vocabularyPath, "utf8"));
  const errors = validateIdentifierVocabulary(vocabulary);
  requireCondition(errors.length === 0, `identifier vocabulary:\n- ${errors.join("\n- ")}`);
  const fixtures = readFixtures(resolve(base, "fixtures"), "identifier conformance fixtures are missing");
  const fixtureErrors = validateIdentifierFixtureSet(vocabulary, fixtures);
  requireCondition(fixtureErrors.length === 0, `identifier fixtures:\n- ${fixtureErrors.join("\n- ")}`);
  validateExpectedBlocks("identifier-fixtures", blockSchema, fixtures, "a fixture's expected identifiers block does not satisfy the block schema");
  console.log(
    `Verified the identifier vocabulary, its schemas, and ${fixtures.length} conformance fixtures covering ${vocabulary.identifier_types.length} types and ${vocabulary.alias_namespaces.length} alias namespaces.`,
  );
}

function checkCompanyRoles() {
  const base = resolve(ROOT, "taxonomy/company-roles/v1");
  const vocabularySchema = resolve(base, "company-roles.schema.json");
  const blockSchema = resolve(base, "company-block.schema.json");
  const vocabularyPath = resolve(base, "company-roles.json");
  for (const schema of [vocabularySchema, blockSchema]) {
    runJsonSchema(["metaschema", schema], `${relative(ROOT, schema)} is not a valid 2020-12 schema`);
  }
  runJsonSchema(["validate", vocabularySchema, vocabularyPath, "--format-assertion"], "the company-role vocabulary does not satisfy its schema");
  const vocabulary = JSON.parse(readFileSync(vocabularyPath, "utf8"));
  const errors = validateCompanyRoleVocabulary(vocabulary);
  requireCondition(errors.length === 0, `company-role vocabulary:\n- ${errors.join("\n- ")}`);
  const fixtures = readFixtures(resolve(base, "fixtures"), "company-role conformance fixtures are missing");
  const fixtureErrors = validateCompanyFixtureSet(vocabulary, fixtures);
  requireCondition(fixtureErrors.length === 0, `company-role fixtures:\n- ${fixtureErrors.join("\n- ")}`);
  validateExpectedBlocks("company-fixtures", blockSchema, fixtures, "a fixture's expected companies block does not satisfy the block schema");
  console.log(
    `Verified the company-role vocabulary, its schemas, and ${fixtures.length} conformance fixtures covering ${Object.keys(vocabulary.discogs.roles).length} raw roles across ${vocabulary.role_categories.length} categories.`,
  );
}

function readFixtures(directory, message) {
  const files = sorted(readdirSync(directory).filter((name) => name.endsWith(".json")));
  requireCondition(files.length > 0, message);
  return files.map((file) => ({ file, ...JSON.parse(readFileSync(resolve(directory, file), "utf8")) }));
}

function validateExpectedBlocks(name, blockSchema, fixtures, message) {
  const expectedDirectory = resolve(ROOT, ".build", name);
  rmSync(expectedDirectory, { recursive: true, force: true });
  mkdirSync(expectedDirectory, { recursive: true });
  const paths = fixtures.map((fixture) => {
    const path = resolve(expectedDirectory, `${fixture.name}.json`);
    writeFileSync(path, `${JSON.stringify(fixture.expected)}\n`, "utf8");
    return path;
  });
  runJsonSchema(["validate", blockSchema, ...paths, "--format-assertion"], message);
  rmSync(expectedDirectory, { recursive: true, force: true });
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
    const actual = sha256(readFileSync(resolve(ROOT, path)));
    requireCondition(actual === expected, `${path} differs from the reviewed infra-source output`);
  }
  console.log("Verified byte identity of 12 reviewed brand outputs.");
}

function checkLicense() {
  const licenseHash = sha256(readFileSync(resolve(ROOT, "LICENSE")));
  requireCondition(licenseHash === MIT_SHA256, "LICENSE must remain the unmodified approved MIT text");
  const notice = readFileSync(resolve(ROOT, "NOTICE"), "utf8");
  requireCondition(/MIT License/.test(notice) && /does not grant trademark rights/i.test(notice), "NOTICE must retain the copyright/trademark boundary");
  for (const path of ["Justfile", "scripts/build.mjs", "scripts/check-governance.mjs", "scripts/check-recipes.mjs", "scripts/check-recipes.test.mjs", "scripts/check-secrets.sh", "scripts/media-mapper.mjs", "scripts/publication-readiness.mjs", "scripts/tooling.mjs", "scripts/validate.mjs", "scripts/validate.test.mjs", "scripts/validation-policy.mjs"]) {
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
  checkPublicSafety();
  const decision = readFileSync(resolve(ROOT, "docs/adr/0006-opentelemetry-metrics.md"), "utf8");
  const decisionErrors = validateTelemetryDecision(decision);
  requireCondition(decisionErrors.length === 0, `telemetry decision contract:\n- ${decisionErrors.join("\n- ")}`);
  const verification = JSON.parse(readFileSync(resolve(ROOT, "verification/organization-wide-v1.json"), "utf8"));
  const repowise = JSON.parse(readFileSync(resolve(ROOT, "verification/repowise-defect-risk-v1.json"), "utf8"));
  const rollout = JSON.parse(readFileSync(resolve(ROOT, "verification/shared-delivery-rollout-v1.json"), "utf8"));
  const targetedProtocol = JSON.parse(readFileSync(resolve(ROOT, "verification/targeted-defect-audit-protocol-v1.json"), "utf8"));
  const targetedAudit = JSON.parse(readFileSync(resolve(ROOT, "verification/targeted-defect-audit-v1.json"), "utf8"));
  const catalog = JSON.parse(readFileSync(resolve(ROOT, "catalog/repositories.json"), "utf8"));
  const verificationErrors = validateOrganizationVerification(verification, catalog);
  const repowiseErrors = validateRepowiseDefectRisk(repowise);
  const rolloutErrors = validateSharedDeliveryRollout(rollout);
  const targetedAuditErrors = validateTargetedDefectAudit(targetedAudit, targetedProtocol);
  requireCondition(verificationErrors.length === 0, `organization verification contract:\n- ${verificationErrors.join("\n- ")}`);
  requireCondition(repowiseErrors.length === 0, `Repowise defect-risk contract:\n- ${repowiseErrors.join("\n- ")}`);
  requireCondition(rolloutErrors.length === 0, `shared-delivery rollout contract:\n- ${rolloutErrors.join("\n- ")}`);
  requireCondition(targetedAuditErrors.length === 0, `targeted defect audit contract:\n- ${targetedAuditErrors.join("\n- ")}`);
  requireCondition(
    targetedAudit.protocol.sha256 === sha256(readFileSync(resolve(ROOT, targetedAudit.protocol.path))),
    "the frozen targeted defect audit protocol changed after inspection began",
  );
  for (const record of targetedAudit.historical_records) {
    requireCondition(
      record.sha256 === sha256(readFileSync(resolve(ROOT, record.path))),
      `historical evidence changed after the targeted defect audit: ${record.path}`,
    );
  }
  for (const record of repowise.historical_records) {
    requireCondition(
      record.sha256 === sha256(readFileSync(resolve(ROOT, record.path))),
      `historical evidence changed after the Repowise audit: ${record.path}`,
    );
  }
  requireCondition(
    rollout.historical_baseline.machine_record.sha256 === sha256(readFileSync(resolve(ROOT, "verification/organization-wide-v1.json"))),
    "the 2026-09-13 machine-readable verification changed after the rollout audit",
  );
  requireCondition(
    rollout.historical_baseline.narrative.sha256 === sha256(readFileSync(resolve(ROOT, "docs/audits/organization-wide-verification-2026-09-13.md"))),
    "the 2026-09-13 narrative verification changed after the rollout audit",
  );
  console.log("Verified the amended telemetry decision contract.");
  console.log("Verified the versioned organization-wide verification matrix.");
  console.log("Verified the versioned Repowise defect-risk evidence.");
  console.log("Verified the versioned shared-delivery rollout attestation.");
  console.log("Verified the frozen protocol and versioned targeted defect audit.");
}

function run(mode) {
  const checks = {
    "--assets": checkAssets,
    "--catalog": checkCatalog,
    "--company-roles": checkCompanyRoles,
    "--dependencies": checkDependencies,
    "--events": checkEvents,
    "--identifiers": checkIdentifiers,
    "--identity": checkIdentity,
    "--license": checkLicense,
    "--links": checkLinks,
    "--policy": checkPolicy,
    "--taxonomy": checkTaxonomy,
  };
  requireCondition(mode in checks, `unknown validation mode: ${mode}`);
  checks[mode]();
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) run(process.argv[2] ?? "--policy");
