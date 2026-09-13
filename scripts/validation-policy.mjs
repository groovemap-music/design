// SPDX-License-Identifier: MIT

import { mapFixtureInput } from "./media-mapper.mjs";

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
const PRIVATE_REPOSITORIES = new Set(["infra", "planning-archive"]);
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

export function sorted(values) {
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

export function validateTelemetryDecision(markdown) {
  const errors = [];
  const historicalDefault = "OTEL_METRIC_EXPORT_INTERVAL (default 15000 ms)";
  const amendmentHeading = "## Amendment: current metric export interval default (2026-09-12)";
  const amendmentStart = markdown.indexOf(amendmentHeading);
  const appendixStart = markdown.indexOf("## Appendix: GrooveMap OpenTelemetry metrics conventions");
  if (!markdown.includes(historicalDefault)) errors.push("ADR 0006 must preserve the original 15000 ms appendix text");
  if (amendmentStart < 0) errors.push("ADR 0006 must identify the current metric export interval amendment");
  if (amendmentStart >= 0 && appendixStart >= 0 && amendmentStart > appendixStart) {
    errors.push("ADR 0006 must distinguish the current amendment from its historical appendix");
  }
  const amendment = amendmentStart >= 0 && appendixStart > amendmentStart
    ? markdown.slice(amendmentStart, appendixStart)
    : "";
  if (!amendment.includes("`OTEL_METRIC_EXPORT_INTERVAL` to `60000` ms")) {
    errors.push("ADR 0006 must record 60000 ms as the current metric export interval default");
  }
  if (!/unless an operator explicitly sets the environment\s+variable/.test(amendment)) {
    errors.push("ADR 0006 must preserve the operator override for OTEL_METRIC_EXPORT_INTERVAL");
  }
  return errors;
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
    const expectedPublicationState = PRIVATE_REPOSITORIES.has(repository.name) ? "private" : "public";
    if (repository.destination_visibility !== expectedPublicationState || repository.publication_status !== expectedPublicationState) {
      errors.push(`${repository.name} must record its current ${expectedPublicationState} publication state`);
    }
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
  for (const [producer, otherProducer] of [
    ["discogs-ingestion", "musicbrainz-ingestion"],
    ["musicbrainz-ingestion", "discogs-ingestion"],
  ]) {
    if (relationshipsFor(producer).some((relationship) => relationship.repository === otherProducer)) {
      errors.push(`${producer} must remain independent of ${otherProducer}`);
    }
  }
  for (const [producer, consumers] of Object.entries(sourceConsumers)) {
    if (!hasRelationship(producer, "deployment", "deployed-by")) errors.push(`${producer} must be deployed by deployment`);
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
  const mcpServer = repositories.find((repository) => repository.name === "mcp-server");
  if (typeof mcpServer?.description !== "string" || !mcpServer.description.startsWith("Client-run ")) {
    errors.push("mcp-server must be described as client-run");
  }
  if (hasRelationship("mcp-server", "deployment", "deployed-by")) {
    errors.push("mcp-server is client-run and must not be catalogued as deployed by deployment");
  }
  return errors;
}

export function validateOrganizationVerification(report, catalog) {
  const errors = [];
  const repositories = report?.repositories ?? [];
  const names = repositories.map((repository) => repository.name);
  const catalogNames = (catalog?.repositories ?? []).map((repository) => repository.name);
  if (report?.schema_version !== 1) errors.push("organization verification must use schema version 1");
  if (report?.reviewed_on !== "2026-09-13") errors.push("organization verification date must remain versioned");
  if (!/^[a-f0-9]{40}$/.test(report?.design_input_revision ?? "")) {
    errors.push("organization verification must retain a full Design input revision");
  }
  if (report?.final_design_validation !== "beadhive-tree-attestation") {
    errors.push("final Design validation must rely on the Beadhive tree attestation");
  }
  if (JSON.stringify(names) !== JSON.stringify(catalogNames)) {
    errors.push("organization verification repository order must match the canonical catalog");
  }
  for (const repository of repositories) {
    if (!/^[a-f0-9]{40}$/.test(repository.revision ?? "")) errors.push(`${repository.name}: reviewed revision must be a full commit`);
    if (repository.verdict !== "pass") errors.push(`${repository.name}: exact-tree verdict must be pass`);
    if (PRIVATE_REPOSITORIES.has(repository.name)) {
      if (JSON.stringify(Object.keys(repository).sort()) !== JSON.stringify(["name", "revision", "verdict"])) {
        errors.push(`${repository.name}: private evidence must remain identity, revision, and verdict only`);
      }
      continue;
    }
    if (!/^[a-f0-9]{40}$/.test(repository.tree ?? "")) {
      errors.push(`${repository.name}: public exact-tree evidence is missing`);
    }
    if (!Number.isInteger(repository.maintained_mermaid) || repository.maintained_mermaid < 0) {
      errors.push(`${repository.name}: maintained Mermaid count is invalid`);
    }
    if (!Array.isArray(repository.evidence_roots) || repository.evidence_roots.length === 0) {
      errors.push(`${repository.name}: evidence roots are missing`);
    }
  }
  const diagrams = report?.diagram_audit ?? {};
  const design = repositories.find((repository) => repository.name === "design");
  if (design?.revision !== report?.design_input_revision) {
    errors.push("organization verification Design row must match its reviewed input revision");
  }
  if (diagrams.renderer !== "@mermaid-js/mermaid-cli@11.12.0") {
    errors.push("organization verification must retain the pinned Mermaid renderer");
  }
  if (diagrams.browser !== "Chrome Headless Shell 152.0.7977.75") {
    errors.push("organization verification must retain the reviewed Chromium build");
  }
  if (diagrams.maintained_mermaid !== 94 || diagrams.excluded_historical_mermaid !== 6 || diagrams.total_mermaid !== 100) {
    errors.push("organization verification must retain the reconciled 94 + 6 Mermaid baseline");
  }
  if (diagrams.maintained_conceptual_ascii !== 0) {
    errors.push("organization verification must not retain maintained conceptual ASCII diagrams");
  }
  const publicMermaid = repositories
    .filter((repository) => !PRIVATE_REPOSITORIES.has(repository.name))
    .reduce((total, repository) => total + (repository.maintained_mermaid ?? 0), 0);
  if (publicMermaid !== 92) errors.push("public repository Mermaid counts differ from the reviewed matrix");
  return errors;
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
