// SPDX-License-Identifier: MIT

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

import { ROOT as root } from "./tooling.mjs";

function git(...arguments_) {
  const result = spawnSync("git", arguments_, { cwd: root, encoding: "utf8" });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`git ${arguments_.join(" ")} failed: ${result.stderr.trim()}`);
  return result.stdout.trim();
}

const status = git("status", "--porcelain", "--untracked-files=all");
if (status !== "") throw new Error("publication readiness requires a clean reviewed commit");

const catalogBytes = readFileSync(resolve(root, "catalog/repositories.json"));
const catalog = JSON.parse(catalogBytes.toString("utf8"));
if (catalog.schema_version !== 1 || catalog.repositories.length !== 21) {
  throw new Error("catalog identity changed after validation");
}
const catalogSourceRepositories = ["discogs-ingestion", "musicbrainz-ingestion"];
const catalogRepositoryNames = new Set(catalog.repositories.map((repository) => repository.name));
if (!catalogSourceRepositories.every((repository) => catalogRepositoryNames.has(repository)) || catalogRepositoryNames.has("catalog-ingestion")) {
  throw new Error("source-owned catalog ingestion identity changed after validation");
}

const taxonomyBytes = readFileSync(resolve(root, "taxonomy/media/v1/media-taxonomy.json"));
const taxonomy = JSON.parse(taxonomyBytes.toString("utf8"));
if (taxonomy.taxonomy_version !== "1") throw new Error("media taxonomy identity changed after validation");

const identityBytes = readFileSync(resolve(root, "taxonomy/identity/v1/identity-vocabulary.json"));
const identity = JSON.parse(identityBytes.toString("utf8"));
if (identity.vocabulary_version !== "1" || identity.native_id_format !== "uuid_v7") {
  throw new Error("identity vocabulary identity changed after validation");
}

const eventBytes = readFileSync(resolve(root, "taxonomy/events/v1/event-types.json"));
const eventTypes = JSON.parse(eventBytes.toString("utf8"));
if (eventTypes.vocabulary_version !== "1" || eventTypes.event_types.length !== 21) {
  throw new Error("event-type vocabulary identity changed after validation");
}

const identifierBytes = readFileSync(resolve(root, "taxonomy/identifiers/v1/identifier-types.json"));
const identifierTypes = JSON.parse(identifierBytes.toString("utf8"));
if (identifierTypes.vocabulary_version !== "1" || identifierTypes.identifier_types.length !== 7) {
  throw new Error("identifier vocabulary identity changed after validation");
}

const companyRoleBytes = readFileSync(resolve(root, "taxonomy/company-roles/v1/company-roles.json"));
const companyRoles = JSON.parse(companyRoleBytes.toString("utf8"));
if (companyRoles.vocabulary_version !== "1" || companyRoles.role_categories.length !== 9) {
  throw new Error("company-role vocabulary identity changed after validation");
}

const handoff = {
  schema_version: 1,
  design_commit: git("rev-parse", "HEAD"),
  catalog_path: "catalog/repositories.json",
  catalog_sha256: createHash("sha256").update(catalogBytes).digest("hex"),
  catalog_schema_version: catalog.schema_version,
  catalog_repository_count: catalog.repositories.length,
  catalog_source_repositories: catalogSourceRepositories,
  media_taxonomy_path: "taxonomy/media/v1/media-taxonomy.json",
  media_taxonomy_sha256: createHash("sha256").update(taxonomyBytes).digest("hex"),
  media_taxonomy_version: taxonomy.taxonomy_version,
  identity_vocabulary_path: "taxonomy/identity/v1/identity-vocabulary.json",
  identity_vocabulary_sha256: createHash("sha256").update(identityBytes).digest("hex"),
  identity_vocabulary_version: identity.vocabulary_version,
  event_types_path: "taxonomy/events/v1/event-types.json",
  event_types_sha256: createHash("sha256").update(eventBytes).digest("hex"),
  event_types_version: eventTypes.vocabulary_version,
  event_type_count: eventTypes.event_types.length,
  identifier_types_path: "taxonomy/identifiers/v1/identifier-types.json",
  identifier_types_sha256: createHash("sha256").update(identifierBytes).digest("hex"),
  identifier_types_version: identifierTypes.vocabulary_version,
  identifier_type_count: identifierTypes.identifier_types.length,
  company_roles_path: "taxonomy/company-roles/v1/company-roles.json",
  company_roles_sha256: createHash("sha256").update(companyRoleBytes).digest("hex"),
  company_roles_version: companyRoles.vocabulary_version,
  company_role_category_count: companyRoles.role_categories.length,
  publication_action_performed: false,
};

process.stdout.write(`${JSON.stringify(handoff, null, 2)}\n`);
