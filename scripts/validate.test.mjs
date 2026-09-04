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
  trackedFiles,
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

test("catalog schema retains the exact public field boundary", () => {
  assert.deepEqual(validateCatalogContract(schema), []);
});

test("canonical catalog contains the exact sorted 21-repository set and source-owned ingestion relationships", () => {
  assert.deepEqual(validateCanonicalCatalog(catalog), []);
  assert.equal(catalog.repositories.length, 21);
  assert.equal(catalog.repositories.some((repository) => repository.name === "catalog-ingestion"), false);
  for (const producer of ["discogs-ingestion", "musicbrainz-ingestion"]) {
    assert.ok(catalog.repositories.some((repository) => repository.name === producer));
  }
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

import { validateFixtureSet } from "./validate.mjs";
import { flattenDescriptions, mapDiscogsFormats, mapMusicBrainzRelease, validateTaxonomy } from "./media-mapper.mjs";
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

test("publication handoff carries the media taxonomy digest", () => {
  const script = readFileSync(resolve(root, "scripts/publication-readiness.mjs"), "utf8");
  assert.match(script, /media_taxonomy_sha256: createHash\("sha256"\)/);
  assert.match(script, /media_taxonomy_version: taxonomy\.taxonomy_version/);
});
