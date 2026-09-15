// SPDX-License-Identifier: MIT

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
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
  validateFixtureSet,
  validateOrganizationVerification,
  validateTelemetryDecision,
} from "./validation-policy.mjs";
import { trackedFiles, validateCatalogContract as validateCatalogContractEntry } from "./validate.mjs";

import schema from "../catalog/repositories.schema.json" with { type: "json" };
import fixture from "../fixtures/catalog-valid.json" with { type: "json" };
import catalog from "../catalog/repositories.json" with { type: "json" };
import organizationVerification from "../verification/organization-wide-v1.json" with { type: "json" };

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

test("validation input is the tracked publishable source tree", () => {
  const files = trackedFiles();
  assert.ok(files.includes(resolve(root, "scripts/validate.mjs")));
  assert.equal(files.some((path) => path.includes("/.beads/")), false);
  assert.equal(files.some((path) => path.includes("/.build/")), false);
});

test("publication handoff implementation is local and non-mutating", () => {
  const script = readFileSync(resolve(root, "scripts/publication-readiness.mjs"), "utf8");
  assert.match(script, /publication_action_performed: false/);
  assert.match(script, /catalog_schema_version: catalog\.schema_version/);
  assert.match(script, /catalog_source_repositories: catalogSourceRepositories/);
  assert.match(script, /git\("status", "--porcelain"/);
  for (const forbidden of ["gh ", "tofu ", "git push", "visibility", "fetch(", "https.request"]) {
    assert.equal(script.includes(forbidden), false, `publication handoff contains forbidden operation: ${forbidden}`);
  }
});

test("repository policy leaves canonical asset verification to the brand capability", () => {
  const result = spawnSync(process.execPath, ["scripts/validate.mjs", "--policy"], {
    cwd: root,
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  assert.doesNotMatch(result.stdout, /byte identity/);
  assert.match(result.stdout, /immutable CI/);
  assert.match(result.stdout, /public-content boundary/);
});

test("catalog schema retains the exact public field boundary", () => {
  assert.deepEqual(validateCatalogContract(schema), []);
  assert.equal(validateCatalogContractEntry, validateCatalogContract);
});

test("canonical catalog contains the exact repository set and decided deployment ownership", () => {
  assert.deepEqual(validateCanonicalCatalog(catalog), []);
  assert.equal(catalog.repositories.length, 21);
  assert.equal(catalog.repositories.filter((repository) => repository.publication_status === "public").length, 19);
  assert.deepEqual(
    catalog.repositories.filter((repository) => repository.publication_status === "private").map((repository) => repository.name),
    ["infra", "planning-archive"],
  );
  assert.equal(catalog.repositories.some((repository) => repository.name === "catalog-ingestion"), false);
  for (const producer of ["discogs-ingestion", "musicbrainz-ingestion"]) {
    const repository = catalog.repositories.find((candidate) => candidate.name === producer);
    assert.ok(repository.relationships.some((relationship) => relationship.repository === "deployment" && relationship.kind === "deployed-by"));
  }
  const mcpServer = catalog.repositories.find((repository) => repository.name === "mcp-server");
  assert.match(mcpServer.description, /^Client-run /);
  assert.equal(mcpServer.relationships.some((relationship) => relationship.repository === "deployment"), false);
});

test("canonical catalog rejects stale publication state and cross-source producer coordination", () => {
  const stalePublication = structuredClone(catalog);
  stalePublication.repositories.find((repository) => repository.name === "design").publication_status = "preparing";
  assert.match(validateCanonicalCatalog(stalePublication).join("\n"), /design must record its current public publication state/);

  const coordinatedSources = structuredClone(catalog);
  coordinatedSources.repositories.find((repository) => repository.name === "musicbrainz-ingestion").relationships.push({
    repository: "discogs-ingestion",
    kind: "coordinates-after",
  });
  assert.match(validateCanonicalCatalog(coordinatedSources).join("\n"), /musicbrainz-ingestion must remain independent/);
});

test("organization verification pins the final repository and diagram evidence", () => {
  assert.deepEqual(validateOrganizationVerification(organizationVerification, catalog), []);

  const mutableRevision = structuredClone(organizationVerification);
  mutableRevision.repositories[0].revision = "main";
  assert.ok(validateOrganizationVerification(mutableRevision, catalog).some((error) => /full commit/.test(error)));

  const expandedPrivateEvidence = structuredClone(organizationVerification);
  expandedPrivateEvidence.repositories.find((repository) => repository.name === "infra").tree = "a".repeat(40);
  assert.ok(validateOrganizationVerification(expandedPrivateEvidence, catalog).some((error) => /private evidence must remain/.test(error)));

  const missingDiagram = structuredClone(organizationVerification);
  missingDiagram.diagram_audit.maintained_mermaid -= 1;
  assert.ok(validateOrganizationVerification(missingDiagram, catalog).some((error) => /94 \+ 6 Mermaid baseline/.test(error)));
});

test("canonical catalog rejects deployment ownership that contradicts the active topology", () => {
  const missingIngestionDeployment = structuredClone(catalog);
  const discogs = missingIngestionDeployment.repositories.find((repository) => repository.name === "discogs-ingestion");
  discogs.relationships = discogs.relationships.filter((relationship) => relationship.repository !== "deployment");
  assert.match(validateCanonicalCatalog(missingIngestionDeployment).join("\n"), /discogs-ingestion must be deployed by deployment/);

  const hostedMcp = structuredClone(catalog);
  const mcpServer = hostedMcp.repositories.find((repository) => repository.name === "mcp-server");
  mcpServer.description = mcpServer.description.replace(/^Client-run /, "Hosted ");
  mcpServer.relationships.push({ repository: "deployment", kind: "deployed-by" });
  const errors = validateCanonicalCatalog(hostedMcp).join("\n");
  assert.match(errors, /mcp-server must be described as client-run/);
  assert.match(errors, /mcp-server is client-run and must not be catalogued as deployed by deployment/);
});

test("telemetry ADR preserves the historical default and records the current runtime default", () => {
  const decision = readFileSync(resolve(root, "docs/adr/0006-opentelemetry-metrics.md"), "utf8");
  assert.deepEqual(validateTelemetryDecision(decision), []);
  assert.match(
    validateTelemetryDecision(decision.replace("`60000` ms", "`15000` ms")).join("\n"),
    /60000 ms as the current metric export interval default/,
  );
  assert.match(
    validateTelemetryDecision(decision.replace("OTEL_METRIC_EXPORT_INTERVAL (default 15000 ms)", "OTEL_METRIC_EXPORT_INTERVAL")).join("\n"),
    /preserve the original 15000 ms appendix text/,
  );
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

import { flattenDescriptions, mapDiscogsFormats, mapFixtureInput, mapMusicBrainzRelease, validateTaxonomy } from "./media-mapper.mjs";
import taxonomy from "../taxonomy/media/v1/media-taxonomy.json" with { type: "json" };

const fixtureDirectory = resolve(root, "taxonomy/media/v1/fixtures");
const fixtures = readdirSync(fixtureDirectory)
  .filter((name) => name.endsWith(".json"))
  .sort()
  .map((name) => JSON.parse(readFileSync(join(fixtureDirectory, name), "utf8")));

test("media taxonomy is internally consistent", () => {
  assert.deepEqual(validateTaxonomy(taxonomy), []);
  assert.deepEqual(taxonomy.families.map((family) => family.id), ["vinyl", "shellac", "grooved_other", "tape", "optical", "digital", "video", "other"]);
  for (const name of ["Vinyl", "Shellac", "CD", "Cassette", "File", "DVD", "Blu-ray", "Box Set", "All Media", "Hybrid"]) {
    assert.ok(name in taxonomy.discogs.formats, `Discogs format ${name} must be mapped`);
  }
  for (const name of ["Vinyl", "12\" Vinyl", "CD", "Cassette", "Digital Media", "Other", "SACD", "DVD-Video", "Shellac"]) {
    assert.ok(name in taxonomy.musicbrainz.formats, `MusicBrainz format ${name} must be mapped`);
  }
});

test("media taxonomy structural validator rejects broken references", () => {
  const broken = structuredClone(taxonomy);
  broken.media.push({ id: "vinyl_78", family: "cylinder", label: "x", defaults: {} });
  broken.discogs.formats.Zzz = { medium: "nope" };
  broken.discogs.descriptions.Zzz = { target: "edition", value: "not_an_edition" };
  broken.musicbrainz.status.Zzz = "not_an_edition";
  const errors = validateTaxonomy(broken);
  assert.ok(errors.some((error) => error.includes("unknown family cylinder")));
  assert.ok(errors.some((error) => error.includes("unknown medium nope")));
  assert.ok(errors.some((error) => error.includes("outside the edition set")));
  assert.ok(errors.some((error) => error.includes("unknown edition not_an_edition")));
});

test("flattenDescriptions accepts every producer and API shape", () => {
  assert.deepEqual(flattenDescriptions({ description: ["LP", "Album"] }), ["LP", "Album"]);
  assert.deepEqual(flattenDescriptions({ description: "Album" }), ["Album"]);
  assert.deepEqual(flattenDescriptions(["7\"", "45 RPM"]), ["7\"", "45 RPM"]);
  assert.deepEqual(flattenDescriptions(undefined), []);
  assert.deepEqual(flattenDescriptions({ other: 1 }), []);
});

test("Discogs mapping routes descriptors to media attributes and release facts", () => {
  const block = mapDiscogsFormats(taxonomy, [
    { name: "Vinyl", qty: "2", text: "Red", descriptions: { description: ["LP", "Album", "Reissue", "Gatefold", "Stereo", "Picture Disc", "Mystery"] } },
    { name: "Box Set", qty: "1", descriptions: { description: ["Limited Edition"] } },
    { name: "All Media", qty: "1" },
    { name: "Unknown Thing", qty: "1" },
  ]);
  assert.equal(block.items.length, 1);
  const [item] = block.items;
  assert.equal(item.medium, "vinyl_12");
  assert.equal(item.qty, 2);
  assert.equal(item.size_inches, 12);
  assert.equal(item.channels, "stereo");
  assert.deepEqual(item.appearance, ["picture_disc"]);
  assert.equal(item.source.text, "Red");
  assert.equal(block.release_kind, "album");
  assert.deepEqual(block.edition, ["limited", "reissue"]);
  assert.equal(block.packaging, "gatefold");
  assert.equal(block.container, "box_set");
  assert.deepEqual(block.flags, ["all_media"]);
  assert.deepEqual(block.families, ["vinyl"]);
  assert.deepEqual(block.unmapped, { formats: ["Unknown Thing"], descriptions: ["Mystery"] });
});

test("Discogs mapping resolves medium by size, applies medium defaults, and never maps release descriptors to media", () => {
  const seven = mapDiscogsFormats(taxonomy, [{ name: "Vinyl", qty: "1", descriptions: ["7\"", "45 RPM", "Single"] }]);
  assert.equal(seven.items[0].medium, "vinyl_7");
  assert.equal(seven.items[0].speed_rpm, 45);
  assert.equal(seven.release_kind, "single");
  const shellac = mapDiscogsFormats(taxonomy, [{ name: "Shellac", qty: "1", descriptions: ["10\""] }]);
  assert.equal(shellac.items[0].medium, "shellac_10");
  assert.equal(shellac.items[0].speed_rpm, 78);
  const bare = mapDiscogsFormats(taxonomy, [{ name: "Vinyl", qty: "1", descriptions: ["Album", "Compilation"] }]);
  assert.equal(bare.items[0].medium, "vinyl_unspecified");
  assert.deepEqual(bare.traits, ["compilation"]);
  const hybrid = mapDiscogsFormats(taxonomy, [{ name: "Hybrid", qty: "1", descriptions: ["SACD", "Album"] }]);
  assert.equal(hybrid.items[0].medium, "optical_sacd");
  assert.deepEqual(hybrid.items[0].variants, ["hybrid_layer"]);
  assert.deepEqual(hybrid.unmapped.descriptions, []);
  const file = mapDiscogsFormats(taxonomy, [{ name: "File", qty: "10", descriptions: ["FLAC", "320 kbps", "Album"] }]);
  assert.equal(file.items[0].medium, "digital_file");
  assert.equal(file.items[0].codec, "flac");
  assert.equal(file.families[0], "digital");
  assert.deepEqual(mapDiscogsFormats(taxonomy, undefined).items, []);
  assert.deepEqual(mapDiscogsFormats(taxonomy, [null, "Vinyl", 3]).items, []);
});

test("MusicBrainz mapping keeps mediums in position order and routes release facts", () => {
  const block = mapMusicBrainzRelease(taxonomy, {
    media: [
      { format: "12\" Vinyl", position: 1, title: "", track_count: 6 },
      { format: "Vinyl", position: 2, title: "", track_count: 5 },
      { format: "Digital Media", position: 3, title: "", track_count: 11 },
      { format: "Other", position: 4, title: "", track_count: 1 },
      { format: null, position: 5, title: "", track_count: 2 },
      { format: "Quantum Crystal", position: 6, title: "", track_count: 1 },
    ],
    status: "Bootleg",
    packaging: "Digipak",
    release_group: { primary_type: "Album", secondary_types: ["Live", "Compilation", "Unknown Type"] },
  });
  assert.deepEqual(block.items.map((item) => item.medium), ["vinyl_12", "vinyl_unspecified", "digital_file", "other_unspecified", "other_unspecified"]);
  assert.deepEqual(block.items.map((item) => item.position), [1, 2, 3, 4, 5]);
  assert.equal(block.items[0].size_inches, 12);
  assert.equal(block.items[0].channels, null);
  assert.deepEqual(block.families, ["digital", "other", "vinyl"]);
  assert.equal(block.release_kind, "album");
  assert.deepEqual(block.traits, ["compilation", "live"]);
  assert.deepEqual(block.edition, ["unofficial"]);
  assert.equal(block.packaging, "digipak");
  assert.deepEqual(block.unmapped, { formats: ["Quantum Crystal"], descriptions: ["Unknown Type"] });
  assert.equal(mapMusicBrainzRelease(taxonomy, { status: "Official" }).edition.length, 0);
});

test("conformance fixtures agree with the reference mapper and cover the required cases", () => {
  assert.deepEqual(validateFixtureSet(taxonomy, fixtures), []);
  assert.ok(fixtures.length >= 9);
  const drifted = structuredClone(fixtures);
  drifted[0].expected.families = ["other"];
  assert.ok(validateFixtureSet(taxonomy, drifted).some((error) => error.includes("differs from the reference mapper")));
  assert.ok(validateFixtureSet(taxonomy, fixtures.slice(0, 1)).some((error) => error.includes("required conformance fixture is missing")));
});

test("non-object format and medium entries are skipped without recording unmapped values", () => {
  const discogsFixture = fixtures.find((entry) => entry.name === "discogs-non-object-entries");
  const musicbrainzFixture = fixtures.find((entry) => entry.name === "musicbrainz-non-object-mediums");
  assert.deepEqual(mapFixtureInput(taxonomy, discogsFixture), discogsFixture.expected);
  assert.equal(discogsFixture.expected.items.length, 1);
  assert.equal(discogsFixture.expected.items[0].medium, "vinyl_12");
  assert.deepEqual(discogsFixture.expected.unmapped, { formats: [], descriptions: [] });
  assert.deepEqual(mapFixtureInput(taxonomy, musicbrainzFixture), musicbrainzFixture.expected);
  assert.equal(musicbrainzFixture.expected.items.length, 1);
  assert.equal(musicbrainzFixture.expected.items[0].medium, "vinyl_12");
  assert.deepEqual(musicbrainzFixture.expected.unmapped, { formats: [], descriptions: [] });
});

test("format and description names that collide with Object.prototype members land in unmapped", () => {
  const fixture = fixtures.find((entry) => entry.name === "discogs-prototype-key-names");
  assert.deepEqual(mapFixtureInput(taxonomy, fixture), fixture.expected);
  assert.deepEqual(fixture.expected.unmapped.formats, ["__proto__", "constructor"]);
  assert.deepEqual(fixture.expected.unmapped.descriptions, ["hasOwnProperty", "toString"]);
  assert.equal(fixture.expected.items.length, 1);
  assert.equal(fixture.expected.items[0].medium, "vinyl_12");
});

test("sortedUnique orders lists by Unicode code point, not UTF-16 code unit", () => {
  const block = mapDiscogsFormats(taxonomy, [{ name: "Vinyl", qty: "1", descriptions: ["￿", "\u{10000}"] }]);
  assert.deepEqual(block.unmapped.descriptions, ["￿", "\u{10000}"]);
});

test("publication handoff carries the media taxonomy digest", () => {
  const script = readFileSync(resolve(root, "scripts/publication-readiness.mjs"), "utf8");
  assert.match(script, /media_taxonomy_sha256: createHash\("sha256"\)/);
  assert.match(script, /media_taxonomy_version: taxonomy\.taxonomy_version/);
});

import {
  validateEventEnvelopeContract,
  validateEventFixtureSet,
  validateEventVocabulary,
  validateIdentityVocabulary,
} from "./validation-policy.mjs";
import identityVocabulary from "../taxonomy/identity/v1/identity-vocabulary.json" with { type: "json" };
import eventVocabulary from "../taxonomy/events/v1/event-types.json" with { type: "json" };
import eventEnvelopeSchema from "../taxonomy/events/v1/event-envelope.schema.json" with { type: "json" };
import impressionSchema from "../taxonomy/events/v1/impression.schema.json" with { type: "json" };

const eventFixtureDirectory = resolve(root, "taxonomy/events/v1/fixtures");
const eventFixtures = readdirSync(eventFixtureDirectory)
  .filter((name) => name.endsWith(".json"))
  .sort()
  .map((file) => ({ file, ...JSON.parse(readFileSync(join(eventFixtureDirectory, file), "utf8")) }));

function validateDocument(schemaPath, document) {
  const directory = mkdtempSync(join(tmpdir(), "groovemap-events-test-"));
  const documentPath = join(directory, "document.json");
  writeFileSync(documentPath, `${JSON.stringify(document)}\n`, "utf8");
  try {
    return spawnSync("jsonschema", ["validate", resolve(root, schemaPath), documentPath, "--format-assertion"], {
      cwd: root,
      encoding: "utf8",
    });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

test("identity vocabulary carries the closed ADR 0009 sets", () => {
  assert.deepEqual(validateIdentityVocabulary(identityVocabulary), []);
  assert.equal(identityVocabulary.native_id_format, "uuid_v7");
  assert.deepEqual(
    identityVocabulary.entity_kinds.map((kind) => kind.id),
    ["release", "master", "artist", "label", "artifact", "owned_copy", "collection_snapshot", "observation"],
  );
  assert.deepEqual(
    identityVocabulary.providers.map((provider) => provider.id),
    ["discogs", "musicbrainz", "wikidata", "barcode", "catalog_number", "isrc", "matrix"],
  );
  assert.deepEqual(identityVocabulary.sources.map((source) => source.id), ["catalog", "user", "inference"]);
  assert.deepEqual(identityVocabulary.provider_aliases.unique_on, ["provider", "entity_kind", "external_id"]);
  assert.equal(identityVocabulary.provider_aliases.unique_scope, "currently_valid_row");
});

test("identity vocabulary rejects a reopened closed set and a closed alias interval", () => {
  const extraProvider = structuredClone(identityVocabulary);
  extraProvider.providers.push({ id: "spotify", label: "Spotify", kind: "catalog", description: "Not a decided provider." });
  assert.match(validateIdentityVocabulary(extraProvider).join("\n"), /providers must be the closed ADR 0009 set/);

  const relocatedKind = structuredClone(identityVocabulary);
  relocatedKind.entity_kinds.find((kind) => kind.id === "owned_copy").native_table = "catalog_items";
  assert.match(validateIdentityVocabulary(relocatedKind).join("\n"), /owned_copy must live in owned_copies/);

  const providerMinted = structuredClone(identityVocabulary);
  providerMinted.entity_kinds.find((kind) => kind.id === "release").user_creatable = true;
  assert.match(validateIdentityVocabulary(providerMinted).join("\n"), /release misstates whether a user can create it/);

  const closedInterval = structuredClone(identityVocabulary);
  closedInterval.provider_aliases.required.push("valid_to");
  assert.match(validateIdentityVocabulary(closedInterval).join("\n"), /open alias interval must leave valid_to unset/);
});

test("event vocabulary carries the closed ADR 0010 version 1 types in order", () => {
  assert.deepEqual(validateEventVocabulary(eventVocabulary), []);
  assert.equal(eventVocabulary.event_types.length, 16);
  assert.deepEqual(
    eventVocabulary.event_types.map((type) => type.id),
    [
      "search.query",
      "search.result_impression",
      "recommendation.shown",
      "recommendation.opened",
      "recommendation.saved",
      "recommendation.dismissed",
      "recommendation.hidden",
      "collection.item_added",
      "collection.item_removed",
      "collection.item_updated",
      "wantlist.item_added",
      "wantlist.item_removed",
      "consent.granted",
      "consent.revoked",
      "account.export_requested",
      "account.erasure_requested",
    ],
  );
  assert.deepEqual(eventVocabulary.consent_purposes, ["product_analytics", "model_training"]);
  for (const type of eventVocabulary.event_types) {
    assert.equal(type.id, `${type.surface}.${type.verb}`);
    assert.ok(type.payload_schema.slice("#/$defs/".length) in eventVocabulary.$defs);
  }
});

test("event vocabulary enforces the past-tense naming rule and its closed exceptions", () => {
  const presentTense = structuredClone(eventVocabulary);
  presentTense.event_types.push({
    id: "collection.item_add",
    surface: "collection",
    verb: "item_add",
    schema_version: 1,
    description: "Present tense names an intention, not an occurrence.",
    payload_schema: "#/$defs/wantlist_item_change",
  });
  const presentTenseErrors = validateEventVocabulary(presentTense).join("\n");
  assert.match(presentTenseErrors, /collection\.item_add does not name something that happened/);

  const grownNouns = structuredClone(eventVocabulary);
  grownNouns.naming_rule.nouns_of_record.push("summary");
  assert.match(validateEventVocabulary(grownNouns).join("\n"), /nouns of record are closed and cannot grow/);

  const unusedIrregular = structuredClone(eventVocabulary);
  unusedIrregular.naming_rule.irregular_past_tense.push("sung");
  assert.match(validateEventVocabulary(unusedIrregular).join("\n"), /unused irregular past tense: sung/);

  const danglingPayload = structuredClone(eventVocabulary);
  danglingPayload.event_types[0].payload_schema = "#/$defs/absent";
  assert.match(validateEventVocabulary(danglingPayload).join("\n"), /payload schema that is not defined/);

  const undeclaredSurface = structuredClone(eventVocabulary);
  undeclaredSurface.event_types[0].surface = "browse";
  const undeclaredErrors = validateEventVocabulary(undeclaredSurface).join("\n");
  assert.match(undeclaredErrors, /undeclared surface: browse/);
});

test("both envelopes declare every ADR 0010 column and stay tied to the vocabulary", () => {
  assert.deepEqual(validateEventEnvelopeContract(eventEnvelopeSchema, impressionSchema, eventVocabulary), []);
  for (const column of ["consent_purposes", "idempotency_key", "occurred_at", "recorded_at", "model_version", "feature_version"]) {
    assert.ok(eventEnvelopeSchema.required.includes(column), `event envelope must require ${column}`);
  }
  for (const column of ["policy_id", "candidate_set_id", "position", "propensity"]) {
    assert.ok(impressionSchema.required.includes(column), `impression must require ${column}`);
  }

  const optionalConsent = structuredClone(eventEnvelopeSchema);
  optionalConsent.required = optionalConsent.required.filter((column) => column !== "consent_purposes");
  assert.match(
    validateEventEnvelopeContract(optionalConsent, impressionSchema, eventVocabulary).join("\n"),
    /every event envelope column must be present on the wire/,
  );

  const driftedEnum = structuredClone(eventEnvelopeSchema);
  driftedEnum.$defs.eventTypeId.enum = driftedEnum.$defs.eventTypeId.enum.slice(0, 15);
  assert.match(
    validateEventEnvelopeContract(driftedEnum, impressionSchema, eventVocabulary).join("\n"),
    /event_type enumeration has drifted from the vocabulary/,
  );
});

test("event fixtures cover every type, both envelopes, and the required rejections", () => {
  assert.deepEqual(validateEventFixtureSet(eventVocabulary, eventFixtures), []);
  const valid = eventFixtures.filter((entry) => entry.valid);
  assert.equal(new Set(valid.filter((entry) => entry.envelope === "event").map((entry) => entry.document.event_type)).size, 16);
  assert.ok(valid.some((entry) => entry.envelope === "impression"));

  const missingRejection = eventFixtures.filter((entry) => entry.rejection !== "unknown-event-type");
  assert.match(
    validateEventFixtureSet(eventVocabulary, missingRejection).join("\n"),
    /required rejection fixture is missing: unknown-event-type/,
  );

  const uncoveredType = eventFixtures.filter((entry) => entry.document?.event_type !== "consent.revoked");
  assert.match(validateEventFixtureSet(eventVocabulary, uncoveredType).join("\n"), /event type has no valid fixture: consent\.revoked/);
});

test("the envelopes reject an unknown type, a missing consent snapshot, and an unattributable impression", () => {
  const rejections = {
    "unknown-event-type": "taxonomy/events/v1/event-envelope.schema.json",
    "missing-consent-purposes": "taxonomy/events/v1/event-envelope.schema.json",
    "impression-missing-policy-id": "taxonomy/events/v1/impression.schema.json",
    "impression-missing-candidate-set-id": "taxonomy/events/v1/impression.schema.json",
  };
  for (const [rejection, schemaPath] of Object.entries(rejections)) {
    const fixture = eventFixtures.find((entry) => entry.rejection === rejection);
    assert.ok(fixture, `fixture for ${rejection} must exist`);
    const result = validateDocument(schemaPath, fixture.document);
    assert.equal(result.error, undefined);
    assert.equal(result.status, 2, `${rejection} unexpectedly passed:\n${result.stdout}${result.stderr}`);
  }
  const accepted = validateDocument("taxonomy/events/v1/event-envelope.schema.json", eventFixtures.find((entry) => entry.name === "event-search-query").document);
  assert.equal(accepted.status, 0, `${accepted.stdout}${accepted.stderr}`);
});

test("the identity and events capabilities run as standalone validation modes", () => {
  for (const [mode, marker] of [["--identity", /identity vocabulary/], ["--events", /event-type vocabulary/]]) {
    const result = spawnSync(process.execPath, ["scripts/validate.mjs", mode], { cwd: root, encoding: "utf8" });
    assert.equal(result.status, 0, `${result.stdout}${result.stderr}`);
    assert.match(result.stdout, marker);
  }
});

test("publication handoff carries the identity and event vocabulary digests", () => {
  const script = readFileSync(resolve(root, "scripts/publication-readiness.mjs"), "utf8");
  assert.match(script, /identity_vocabulary_sha256: createHash\("sha256"\)/);
  assert.match(script, /event_types_sha256: createHash\("sha256"\)/);
  assert.match(script, /event_type_count: eventTypes\.event_types\.length/);
});

import {
  mapCompanyBlock,
  mapIdentifierBlock,
  normalizeIdentifierValue,
  validateCompanyFixtureSet,
  validateCompanyRoleVocabulary,
  validateIdentifierFixtureSet,
  validateIdentifierVocabulary,
} from "./validation-policy.mjs";
import identifierVocabulary from "../taxonomy/identifiers/v1/identifier-types.json" with { type: "json" };
import companyRoleVocabulary from "../taxonomy/company-roles/v1/company-roles.json" with { type: "json" };

function loadFixtures(directory) {
  const base = resolve(root, directory);
  return readdirSync(base)
    .filter((name) => name.endsWith(".json"))
    .sort()
    .map((file) => ({ file, ...JSON.parse(readFileSync(join(base, file), "utf8")) }));
}

const identifierFixtures = loadFixtures("taxonomy/identifiers/v1/fixtures");
const companyFixtures = loadFixtures("taxonomy/company-roles/v1/fixtures");

test("identifier vocabulary carries the closed ADR 0011 types and alias namespaces", () => {
  assert.deepEqual(validateIdentifierVocabulary(identifierVocabulary), []);
  assert.deepEqual(
    identifierVocabulary.identifier_types.map((type) => type.id),
    ["barcode", "matrix_runout", "label_code", "rights_society", "asin", "other", "catalog_number"],
  );
  assert.deepEqual(
    identifierVocabulary.alias_namespaces.map((namespace) => [namespace.provider, namespace.type, namespace.normalization]),
    [
      ["barcode", "barcode", "digits_only"],
      ["catalog_number", "catalog_number", "upper_collapse_space"],
      ["matrix", "matrix_runout", "collapse_space"],
    ],
  );
  for (const namespace of identifierVocabulary.alias_namespaces) assert.equal(namespace.alias_source, "catalog");
  assert.equal(identifierVocabulary.discogs.catalog_number_field, "labels[].catno");
});

test("identifier vocabulary rejects a widened alias set and an unsorted raw mapping", () => {
  const widened = structuredClone(identifierVocabulary);
  widened.identifier_types.find((type) => type.id === "asin").alias_provider = "barcode";
  assert.match(validateIdentifierVocabulary(widened).join("\n"), /may mint provider aliases/);

  const unsorted = structuredClone(identifierVocabulary);
  unsorted.discogs.types = { Barcode: "barcode", ASIN: "asin", "Label Code": "label_code", "Matrix / Runout": "matrix_runout", "Rights Society": "rights_society", Other: "other" };
  assert.match(validateIdentifierVocabulary(unsorted).join("\n"), /must be sorted/);

  const minted = structuredClone(identifierVocabulary);
  minted.discogs.types["Catalogue Number"] = "catalog_number";
  assert.match(validateIdentifierVocabulary(minted).join("\n"), /lifted from the label entries/);
});

test("company-role vocabulary maps every closed category and excludes the issuing label", () => {
  assert.deepEqual(validateCompanyRoleVocabulary(companyRoleVocabulary), []);
  assert.deepEqual(
    companyRoleVocabulary.role_categories.map((category) => category.id),
    ["manufacturing", "mastering", "lacquer", "pressing", "distribution", "marketing", "rights", "recording_facility", "other"],
  );
  assert.equal(companyRoleVocabulary.discogs.roles["Pressed By"], "pressing");
  assert.equal(companyRoleVocabulary.discogs.roles["Lacquer Cut At"], "lacquer");
  assert.equal(companyRoleVocabulary.discogs.roles["Glass Mastered At"], "lacquer");
  assert.equal(companyRoleVocabulary.discogs.roles["Mastered At"], "mastering");
  assert.equal(companyRoleVocabulary.discogs.roles.Label, undefined);
});

test("company-role vocabulary rejects an undeclared category and a mapped issuing label", () => {
  const undeclared = structuredClone(companyRoleVocabulary);
  undeclared.discogs.roles["Pressed By"] = "plant";
  assert.match(validateCompanyRoleVocabulary(undeclared).join("\n"), /maps to an undeclared category/);

  const labelled = structuredClone(companyRoleVocabulary);
  labelled.discogs.roles.Label = "rights";
  assert.match(validateCompanyRoleVocabulary(labelled).join("\n"), /not a company credit/);
});

test("identifier normalization keeps digits, case, and whitespace exactly as each namespace declares", () => {
  assert.equal(normalizeIdentifierValue("digits_only", "5 012394-144777"), "5012394144777");
  assert.equal(normalizeIdentifierValue("upper_collapse_space", "  fac   73 "), "FAC 73");
  assert.equal(normalizeIdentifierValue("collapse_space", " PB 41447  A2 "), "PB 41447 A2");
});

test("the reference mappers preserve unknown upstream strings and skip malformed entries", () => {
  const identifiers = mapIdentifierBlock(identifierVocabulary, {
    identifiers: [
      null,
      "Barcode",
      { type: "constructor", value: "inherited" },
      { type: "Barcode", value: " 5012394144777 " },
      { type: "Barcode", value: "  " },
    ],
    labels: [{ catno: "none" }, { catno: "SP-1234" }],
  });
  assert.deepEqual(identifiers.unmapped.types, ["constructor"]);
  assert.deepEqual(identifiers.items.map((item) => item.type), ["other", "barcode", "catalog_number"]);
  assert.deepEqual(identifiers.aliases, [
    { provider: "barcode", external_id: "5012394144777" },
    { provider: "catalog_number", external_id: "SP-1234" },
  ]);

  const companies = mapCompanyBlock(companyRoleVocabulary, {
    companies: [
      null,
      { name: "Damont" },
      { name: "Sarm West", entity_type_name: "hasOwnProperty", entity_type: "99", id: 1 },
      { name: "Damont", entity_type_name: "Pressed By", entity_type: "plant", id: 0 },
    ],
  });
  assert.deepEqual(companies.unmapped.roles, ["hasOwnProperty"]);
  assert.deepEqual(companies.items.map((item) => item.role_category), ["other", "pressing"]);
  assert.deepEqual(companies.items.at(-1).source, { provider: "discogs", entity_type: null });
  assert.equal(companies.items.at(-1).discogs_id, null);
});

test("identifier and company fixtures agree with the reference mappers and cover the required cases", () => {
  assert.deepEqual(validateIdentifierFixtureSet(identifierVocabulary, identifierFixtures), []);
  assert.deepEqual(validateCompanyFixtureSet(companyRoleVocabulary, companyFixtures), []);
  assert.ok(identifierFixtures.length >= 8);
  assert.ok(companyFixtures.length >= 8);
  const drifted = identifierFixtures.map((fixture) => structuredClone(fixture));
  drifted[0].expected.aliases = [];
  assert.match(validateIdentifierFixtureSet(identifierVocabulary, drifted).join("\n"), /differs from the reference mapper/);
});

test("the identifier and company-role capabilities run as standalone validation modes", () => {
  for (const [mode, marker] of [["--identifiers", /identifier vocabulary/], ["--company-roles", /company-role vocabulary/]]) {
    const result = spawnSync(process.execPath, ["scripts/validate.mjs", mode], { cwd: root, encoding: "utf8" });
    assert.equal(result.status, 0, `${result.stdout}${result.stderr}`);
    assert.match(result.stdout, marker);
  }
});

test("publication handoff carries the identifier and company-role vocabulary digests", () => {
  const script = readFileSync(resolve(root, "scripts/publication-readiness.mjs"), "utf8");
  assert.match(script, /identifier_types_sha256: createHash\("sha256"\)/);
  assert.match(script, /company_roles_sha256: createHash\("sha256"\)/);
  assert.match(script, /identifier_type_count: identifierTypes\.identifier_types\.length/);
  assert.match(script, /company_role_category_count: companyRoles\.role_categories\.length/);
});
