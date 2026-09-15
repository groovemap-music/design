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

const IDENTITY_ENTITY_KINDS = ["release", "master", "artist", "label", "artifact", "owned_copy", "collection_snapshot", "observation"];
const IDENTITY_NATIVE_TABLES = {
  release: "catalog_items",
  master: "catalog_items",
  artist: "catalog_items",
  label: "catalog_items",
  artifact: "artifacts",
  owned_copy: "owned_copies",
  collection_snapshot: "collection_snapshots",
  observation: "observations",
};
const IDENTITY_USER_CREATABLE = new Set(["artifact", "owned_copy", "collection_snapshot", "observation"]);
const IDENTITY_PROVIDERS = ["discogs", "musicbrainz", "wikidata", "barcode", "catalog_number", "isrc", "matrix"];
const IDENTITY_SOURCES = ["catalog", "user", "inference"];
const ALIAS_COLUMNS = ["provider", "external_id", "entity_kind", "native_id", "valid_from", "valid_to", "confidence", "source", "asserted_at"];
const ALIAS_UNIQUE_ON = ["provider", "entity_kind", "external_id"];

const EVENT_TYPES_V1 = [
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
];
const EVENT_NOUNS_OF_RECORD = ["query", "result_impression"];
const CONSENT_PURPOSES = ["product_analytics", "model_training"];
const EVENT_ENVELOPE_COLUMNS = [
  "event_id",
  "event_type",
  "schema_version",
  "subject_id",
  "session_id",
  "occurred_at",
  "recorded_at",
  "producer",
  "consent_purposes",
  "model_version",
  "feature_version",
  "idempotency_key",
  "payload",
];
const IMPRESSION_COLUMNS = [
  "impression_id",
  "subject_id",
  "surface",
  "policy_id",
  "candidate_set_id",
  "position",
  "item_id",
  "score",
  "propensity",
  "request_id",
  "occurred_at",
];
const REQUIRED_EVENT_REJECTIONS = [
  "unknown-event-type",
  "missing-consent-purposes",
  "impression-missing-policy-id",
  "impression-missing-candidate-set-id",
];

function sameSequence(actual, expected) {
  return JSON.stringify(actual ?? null) === JSON.stringify(expected);
}

export function validateIdentityVocabulary(vocabulary) {
  const errors = [];
  if (vocabulary?.vocabulary_version !== "1") errors.push("the identity vocabulary must declare vocabulary_version 1");
  if (vocabulary?.license !== "MIT") errors.push("the identity vocabulary must declare MIT license metadata");
  if (vocabulary?.native_id_format !== "uuid_v7") errors.push("native identifiers must be UUID version 7");

  const kinds = vocabulary?.entity_kinds ?? [];
  if (!sameSequence(kinds.map((kind) => kind.id), IDENTITY_ENTITY_KINDS)) {
    errors.push("entity kinds must be the closed ADR 0009 set in declaration order");
  }
  for (const kind of kinds) {
    const table = IDENTITY_NATIVE_TABLES[kind.id];
    if (table === undefined) continue;
    if (kind.native_table !== table) errors.push(`entity kind ${kind.id} must live in ${table}`);
    if (kind.user_creatable !== IDENTITY_USER_CREATABLE.has(kind.id)) {
      errors.push(`entity kind ${kind.id} misstates whether a user can create it`);
    }
  }

  const providers = vocabulary?.providers ?? [];
  if (!sameSequence(providers.map((provider) => provider.id), IDENTITY_PROVIDERS)) {
    errors.push("providers must be the closed ADR 0009 set in declaration order");
  }
  for (const provider of providers) {
    if (!["catalog", "identifier"].includes(provider.kind)) errors.push(`provider ${provider.id} must be a catalog or an identifier namespace`);
  }
  if (!sameSequence((vocabulary?.sources ?? []).map((source) => source.id), IDENTITY_SOURCES)) {
    errors.push("alias sources must be the closed catalog, user, and inference set in declaration order");
  }

  const aliases = vocabulary?.provider_aliases ?? {};
  if (!sameSequence(aliases.columns, ALIAS_COLUMNS)) errors.push("the alias table must declare every ADR 0009 column in order");
  if (!sameSequence(aliases.unique_on, ALIAS_UNIQUE_ON)) errors.push("alias uniqueness must be on (provider, entity_kind, external_id)");
  if (aliases.unique_scope !== "currently_valid_row") errors.push("alias uniqueness must apply to the currently valid row");
  for (const column of aliases.required ?? []) {
    if (!(aliases.columns ?? []).includes(column)) errors.push(`alias requires an undeclared column: ${column}`);
  }
  if ((aliases.required ?? []).includes("valid_to")) errors.push("an open alias interval must leave valid_to unset");
  return errors;
}

export function validateEventVocabulary(vocabulary) {
  const errors = [];
  if (vocabulary?.vocabulary_version !== "1") errors.push("the event-type vocabulary must declare vocabulary_version 1");
  if (vocabulary?.license !== "MIT") errors.push("the event-type vocabulary must declare MIT license metadata");
  if (!sameSequence(vocabulary?.consent_purposes, CONSENT_PURPOSES)) errors.push("consent purposes must be product_analytics and model_training");

  const rule = vocabulary?.naming_rule ?? {};
  if (rule.form !== "<surface>.<past-tense verb>") errors.push("the naming rule must remain <surface>.<past-tense verb>");
  if (rule.regular_past_tense_suffix !== "ed") errors.push("the regular past-tense suffix must remain ed");
  if (!sameSequence(rule.nouns_of_record, EVENT_NOUNS_OF_RECORD)) {
    errors.push("the two version 1 nouns of record are closed and cannot grow: query and result_impression");
  }

  const surfaces = (vocabulary?.surfaces ?? []).map((surface) => surface.id);
  const types = vocabulary?.event_types ?? [];
  if (!sameSequence(types.map((type) => type.id), EVENT_TYPES_V1)) {
    errors.push("event types must be the closed ADR 0010 version 1 set in declaration order");
  }
  const irregular = new Set(rule.irregular_past_tense ?? []);
  const nouns = new Set(rule.nouns_of_record ?? []);
  const usedIrregular = new Set();
  const definitions = vocabulary?.$defs ?? {};
  for (const type of types) {
    if (type.id !== `${type.surface}.${type.verb}`) errors.push(`event type ${type.id} must be <surface>.<verb>`);
    if (!surfaces.includes(type.surface)) errors.push(`event type ${type.id} names an undeclared surface: ${type.surface}`);
    const head = String(type.verb ?? "").split("_").pop();
    if (nouns.has(type.verb)) {
      // A version 1 carry-over that names the record rather than the act.
    } else if (irregular.has(head)) {
      usedIrregular.add(head);
    } else if (!head.endsWith("ed")) {
      errors.push(`event type ${type.id} does not name something that happened in the past tense`);
    }
    const reference = String(type.payload_schema ?? "");
    const name = reference.startsWith("#/$defs/") ? reference.slice("#/$defs/".length) : "";
    if (!Object.hasOwn(definitions, name)) errors.push(`event type ${type.id} names a payload schema that is not defined: ${reference}`);
    if (!Number.isInteger(type.schema_version) || type.schema_version < 1) errors.push(`event type ${type.id} must carry a payload schema version`);
  }
  for (const word of irregular) {
    if (!usedIrregular.has(word)) errors.push(`the naming rule declares an unused irregular past tense: ${word}`);
  }
  for (const surface of surfaces) {
    if (!types.some((type) => type.surface === surface)) errors.push(`surface ${surface} carries no event type`);
  }
  return errors;
}

export function validateEventEnvelopeContract(envelope, impression, vocabulary) {
  const errors = [];
  for (const [name, schema, columns] of [["event envelope", envelope, EVENT_ENVELOPE_COLUMNS], ["impression", impression, IMPRESSION_COLUMNS]]) {
    if (schema?.$schema !== "https://json-schema.org/draft/2020-12/schema") errors.push(`the ${name} schema must use JSON Schema 2020-12`);
    if (schema?.["x-license"] !== "MIT") errors.push(`the ${name} schema must declare MIT license metadata`);
    if (schema?.additionalProperties !== false) errors.push(`the ${name} schema must reject undeclared columns`);
    if (!sameValues(Object.keys(schema?.properties ?? {}), columns)) errors.push(`the ${name} schema must declare every ADR 0010 column`);
    if (!sameValues(schema?.required ?? [], columns)) errors.push(`every ${name} column must be present on the wire`);
  }
  const declaredTypes = envelope?.$defs?.eventTypeId?.enum;
  if (!sameSequence(declaredTypes, (vocabulary?.event_types ?? []).map((type) => type.id))) {
    errors.push("the event envelope's event_type enumeration has drifted from the vocabulary");
  }
  if (!sameValues(envelope?.properties?.consent_purposes?.items?.enum ?? [], vocabulary?.consent_purposes ?? [])) {
    errors.push("the event envelope's consent purposes have drifted from the vocabulary");
  }
  if (!sameValues(impression?.$defs?.surfaceId?.enum ?? [], (vocabulary?.surfaces ?? []).map((surface) => surface.id))) {
    errors.push("the impression surface enumeration has drifted from the vocabulary");
  }
  return errors;
}

export function validateEventFixtureSet(vocabulary, fixtures) {
  const errors = [];
  const names = new Set();
  const covered = new Set();
  const rejections = new Set();
  const valid = { event: 0, impression: 0 };
  const invalid = { event: 0, impression: 0 };
  const types = new Map((vocabulary?.event_types ?? []).map((type) => [type.id, type]));

  for (const fixture of fixtures) {
    for (const field of ["name", "envelope", "valid", "description", "document"]) {
      if (!(field in fixture)) errors.push(`fixture ${fixture.name ?? "?"} is missing ${field}`);
    }
    if (names.has(fixture.name)) errors.push(`duplicate fixture name ${fixture.name}`);
    names.add(fixture.name);
    if (fixture.file !== undefined && fixture.file !== `${fixture.name}.json`) errors.push(`fixture ${fixture.name} does not match its file name`);
    if (!["event", "impression"].includes(fixture.envelope)) {
      errors.push(`fixture ${fixture.name} names an unknown envelope: ${fixture.envelope}`);
      continue;
    }
    if (fixture.valid === false) {
      invalid[fixture.envelope] += 1;
      if (typeof fixture.rejection !== "string" || fixture.rejection === "") errors.push(`invalid fixture ${fixture.name} must name what rejects it`);
      else rejections.add(fixture.rejection);
      continue;
    }
    valid[fixture.envelope] += 1;
    if ("rejection" in fixture) errors.push(`valid fixture ${fixture.name} must not name a rejection`);
    if (fixture.envelope !== "event") continue;
    const type = types.get(fixture.document?.event_type);
    if (type === undefined) {
      errors.push(`valid fixture ${fixture.name} carries an event type outside the vocabulary`);
      continue;
    }
    covered.add(type.id);
    if (fixture.document.schema_version !== type.schema_version) errors.push(`fixture ${fixture.name} disagrees with the payload schema version of ${type.id}`);
  }

  for (const envelope of ["event", "impression"]) {
    if (valid[envelope] === 0) errors.push(`the ${envelope} envelope has no valid example`);
    if (invalid[envelope] === 0) errors.push(`the ${envelope} envelope has no invalid example`);
  }
  for (const type of types.keys()) {
    if (!covered.has(type)) errors.push(`event type has no valid fixture: ${type}`);
  }
  for (const rejection of REQUIRED_EVENT_REJECTIONS) {
    if (!rejections.has(rejection)) errors.push(`required rejection fixture is missing: ${rejection}`);
  }
  return errors;
}

// ---------------------------------------------------------------------------
// ADR 0011: catalog identifiers and manufacturing credits.
//
// The two mappers below are the reference implementation the conformance
// fixtures are proved against. Every vendored mapper (the Rust Discogs
// producer, the shared Python runtime) must reproduce these blocks byte for
// byte after canonical JSON serialisation.
// ---------------------------------------------------------------------------

const IDENTIFIER_TYPES_V1 = ["barcode", "matrix_runout", "label_code", "rights_society", "asin", "other", "catalog_number"];
const IDENTIFIER_ALIAS_NAMESPACES = [
  ["barcode", "barcode"],
  ["catalog_number", "catalog_number"],
  ["matrix", "matrix_runout"],
];
const IDENTIFIER_NORMALIZATIONS = ["digits_only", "upper_collapse_space", "collapse_space"];
const REQUIRED_IDENTIFIER_FIXTURES = [
  "discogs-barcode-and-catalogue-number",
  "discogs-matrix-runout-inscriptions",
  "discogs-label-code-and-rights-society",
  "discogs-mapped-to-other",
  "discogs-unmapped-type",
  "discogs-no-identifiers",
  "discogs-malformed-entries",
  "discogs-duplicate-alias-values",
];
const COMPANY_ROLE_CATEGORIES = [
  "manufacturing",
  "mastering",
  "lacquer",
  "pressing",
  "distribution",
  "marketing",
  "rights",
  "recording_facility",
  "other",
];
const REQUIRED_COMPANY_FIXTURES = [
  "discogs-pressing-and-transfer-master",
  "discogs-rights-holders",
  "discogs-distribution-and-marketing",
  "discogs-recording-facilities",
  "discogs-manufacturing-and-print",
  "discogs-unmapped-role",
  "discogs-no-companies",
  "discogs-malformed-entries",
];
const ALIAS_KEY_SEPARATOR = " ";

function compareByCodePoint(left, right) {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    const difference = leftPoints[index].codePointAt(0) - rightPoints[index].codePointAt(0);
    if (difference !== 0) return difference;
  }
  return leftPoints.length - rightPoints.length;
}

function sortedUniqueByCodePoint(values) {
  return [...new Set(values)].sort(compareByCodePoint);
}

function isSortedByCodePoint(values) {
  return JSON.stringify(values) === JSON.stringify([...values].sort(compareByCodePoint));
}

// An upstream name we do not control must never resolve to an inherited
// Object.prototype member, or a genuinely unknown Discogs string would be
// treated as mapped instead of landing in `unmapped`.
function ownGet(map, key) {
  return Object.hasOwn(map ?? {}, key) ? map[key] : undefined;
}

function isPlainEntry(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function trimmedString(value) {
  return typeof value === "string" ? value.trim() : "";
}

export function normalizeIdentifierValue(normalization, value) {
  if (normalization === "digits_only") return [...value].filter((character) => character >= "0" && character <= "9").join("");
  const collapsed = value.trim().replace(/\s+/g, " ");
  return normalization === "upper_collapse_space" ? collapsed.toUpperCase() : collapsed;
}

export function mapIdentifierBlock(vocabulary, input) {
  const items = [];
  const unmapped = [];
  const types = vocabulary?.discogs?.types ?? {};
  const absentCatalogNumber = vocabulary?.discogs?.absent_catalog_number ?? "none";

  for (const entry of Array.isArray(input?.identifiers) ? input.identifiers : []) {
    if (!isPlainEntry(entry)) continue;
    const rawType = trimmedString(entry.type);
    const value = trimmedString(entry.value);
    if (rawType === "" || value === "") continue;
    const mapped = ownGet(types, rawType);
    if (mapped === undefined) unmapped.push(rawType);
    const description = trimmedString(entry.description);
    items.push({
      type: mapped ?? vocabulary.unmapped_type,
      value,
      description: description === "" ? null : description,
      source: { provider: "discogs", type: rawType, field: "identifiers" },
    });
  }

  for (const entry of Array.isArray(input?.labels) ? input.labels : []) {
    if (!isPlainEntry(entry)) continue;
    const catalogNumber = trimmedString(entry.catno);
    if (catalogNumber === "" || catalogNumber.toLowerCase() === absentCatalogNumber) continue;
    items.push({
      type: "catalog_number",
      value: catalogNumber,
      description: null,
      source: { provider: "discogs", type: null, field: "labels[].catno" },
    });
  }

  const namespaces = new Map((vocabulary?.alias_namespaces ?? []).map((namespace) => [namespace.type, namespace]));
  const aliases = new Map();
  for (const item of items) {
    const namespace = namespaces.get(item.type);
    if (namespace === undefined) continue;
    const externalId = normalizeIdentifierValue(namespace.normalization, item.value);
    if (externalId === "") continue;
    aliases.set(`${namespace.provider}${ALIAS_KEY_SEPARATOR}${externalId}`, { provider: namespace.provider, external_id: externalId });
  }

  return {
    identifiers_version: vocabulary.vocabulary_version,
    items,
    types: sortedUniqueByCodePoint(items.map((item) => item.type)),
    aliases: [...aliases.keys()].sort(compareByCodePoint).map((key) => aliases.get(key)),
    unmapped: { types: sortedUniqueByCodePoint(unmapped) },
  };
}

export function mapCompanyBlock(vocabulary, input) {
  const items = [];
  const unmapped = [];
  const roles = vocabulary?.discogs?.roles ?? {};

  for (const entry of Array.isArray(input?.companies) ? input.companies : []) {
    if (!isPlainEntry(entry)) continue;
    const name = trimmedString(entry.name);
    const role = trimmedString(entry.entity_type_name);
    if (name === "" || role === "") continue;
    const category = ownGet(roles, role);
    if (category === undefined) unmapped.push(role);
    const catalogNumber = trimmedString(entry.catno);
    const entityType = trimmedString(entry.entity_type) || (Number.isInteger(entry.entity_type) ? String(entry.entity_type) : "");
    items.push({
      name,
      discogs_id: Number.isInteger(entry.id) && entry.id > 0 ? entry.id : null,
      role,
      role_category: category ?? vocabulary.unmapped_category,
      catno: catalogNumber === "" ? null : catalogNumber,
      source: { provider: "discogs", entity_type: /^[0-9]+$/.test(entityType) ? entityType : null },
    });
  }

  return {
    companies_version: vocabulary.vocabulary_version,
    items,
    role_categories: sortedUniqueByCodePoint(items.map((item) => item.role_category)),
    unmapped: { roles: sortedUniqueByCodePoint(unmapped) },
  };
}

export function validateIdentifierVocabulary(vocabulary) {
  const errors = [];
  if (vocabulary?.vocabulary_version !== "1") errors.push("the identifier vocabulary must declare vocabulary_version 1");
  if (vocabulary?.license !== "MIT") errors.push("the identifier vocabulary must declare MIT license metadata");
  if (vocabulary?.unmapped_type !== "other") errors.push("an unrecognised identifier type must fall to other");

  const declared = vocabulary?.identifier_types ?? [];
  if (!sameSequence(declared.map((type) => type.id), IDENTIFIER_TYPES_V1)) {
    errors.push("identifier types must be the closed ADR 0011 set in declaration order");
  }
  const aliasTypes = declared.filter((type) => type.alias_provider !== null).map((type) => type.id);
  if (!sameValues(aliasTypes, IDENTIFIER_ALIAS_NAMESPACES.map(([, type]) => type))) {
    errors.push("exactly barcode, catalog_number, and matrix_runout may mint provider aliases");
  }

  const namespaces = vocabulary?.alias_namespaces ?? [];
  if (!sameSequence(namespaces.map((namespace) => [namespace.provider, namespace.type]), IDENTIFIER_ALIAS_NAMESPACES)) {
    errors.push("the alias namespaces must be the closed ADR 0009 providers in declaration order");
  }
  const normalizations = new Set((vocabulary?.normalizations ?? []).map((normalization) => normalization.id));
  if (!sameValues([...normalizations], IDENTIFIER_NORMALIZATIONS)) errors.push("the declared normalizations must be the closed ADR 0011 set");
  for (const namespace of namespaces) {
    const type = declared.find((entry) => entry.id === namespace.type);
    if (type?.alias_provider !== namespace.provider) errors.push(`alias namespace ${namespace.provider} disagrees with the type that declares it`);
    if (!normalizations.has(namespace.normalization)) errors.push(`alias namespace ${namespace.provider} names an undeclared normalization`);
    if (namespace.alias_source !== "catalog") errors.push(`alias namespace ${namespace.provider} must mint catalog-sourced aliases`);
  }

  const mapping = vocabulary?.discogs?.types ?? {};
  const keys = Object.keys(mapping);
  if (!isSortedByCodePoint(keys)) errors.push("the raw Discogs identifier type strings must be sorted");
  const targets = new Set();
  for (const key of keys) {
    const target = mapping[key];
    if (!IDENTIFIER_TYPES_V1.includes(target)) errors.push(`raw identifier type ${key} maps to an undeclared type: ${target}`);
    if (target === "catalog_number") errors.push("no raw identifier type maps to catalog_number: it is lifted from the label entries");
    targets.add(target);
  }
  for (const type of IDENTIFIER_TYPES_V1) {
    if (type === "catalog_number" || targets.has(type)) continue;
    errors.push(`identifier type carries no raw Discogs string: ${type}`);
  }
  return errors;
}

export function validateCompanyRoleVocabulary(vocabulary) {
  const errors = [];
  if (vocabulary?.vocabulary_version !== "1") errors.push("the company-role vocabulary must declare vocabulary_version 1");
  if (vocabulary?.license !== "MIT") errors.push("the company-role vocabulary must declare MIT license metadata");
  if (vocabulary?.unmapped_category !== "other") errors.push("an unrecognised company role must fall to other");
  if (!sameSequence((vocabulary?.role_categories ?? []).map((category) => category.id), COMPANY_ROLE_CATEGORIES)) {
    errors.push("role categories must be the closed ADR 0011 set in declaration order");
  }
  if (vocabulary?.discogs?.excluded_field !== "labels") {
    errors.push("the vocabulary must record that the issuing-label relation is not a company credit");
  }

  const mapping = vocabulary?.discogs?.roles ?? {};
  const keys = Object.keys(mapping);
  if (!isSortedByCodePoint(keys)) errors.push("the raw Discogs company role strings must be sorted");
  const targets = new Set();
  for (const key of keys) {
    const target = mapping[key];
    if (!COMPANY_ROLE_CATEGORIES.includes(target)) errors.push(`raw company role ${key} maps to an undeclared category: ${target}`);
    targets.add(target);
  }
  for (const category of COMPANY_ROLE_CATEGORIES) {
    if (!targets.has(category)) errors.push(`role category carries no raw Discogs role: ${category}`);
  }
  if (Object.hasOwn(mapping, "Label")) errors.push("the issuing label is not a company credit and must not be mapped as one");
  return errors;
}

function validateBlockFixtureSet(fixtures, map, required, subject) {
  const errors = [];
  const names = new Set();
  for (const fixture of fixtures) {
    for (const field of ["name", "provider", "description", "input", "expected"]) {
      if (!(field in fixture)) errors.push(`fixture ${fixture.name ?? "?"} is missing ${field}`);
    }
    if (names.has(fixture.name)) errors.push(`duplicate fixture name ${fixture.name}`);
    names.add(fixture.name);
    if (fixture.file !== undefined && fixture.file !== `${fixture.name}.json`) errors.push(`fixture ${fixture.name} does not match its file name`);
    if (fixture.provider !== "discogs") errors.push(`fixture ${fixture.name} names a provider outside version 1: ${fixture.provider}`);
    let actual;
    try {
      actual = map(fixture.input);
    } catch (error) {
      errors.push(`fixture ${fixture.name}: ${error.message}`);
      continue;
    }
    if (JSON.stringify(actual) !== JSON.stringify(fixture.expected)) {
      errors.push(`fixture ${fixture.name} expected ${subject} differs from the reference mapper`);
    }
  }
  for (const name of required) {
    if (!names.has(name)) errors.push(`required conformance fixture is missing: ${name}`);
  }
  return errors;
}

export function validateIdentifierFixtureSet(vocabulary, fixtures) {
  const errors = validateBlockFixtureSet(
    fixtures,
    (input) => mapIdentifierBlock(vocabulary, input),
    REQUIRED_IDENTIFIER_FIXTURES,
    "identifiers block",
  );
  if (!fixtures.some((fixture) => (fixture.expected?.unmapped?.types ?? []).length > 0)) {
    errors.push("no fixture proves that an unrecognised raw identifier type is preserved");
  }
  const minted = new Set(fixtures.flatMap((fixture) => (fixture.expected?.aliases ?? []).map((alias) => alias.provider)));
  for (const [provider] of IDENTIFIER_ALIAS_NAMESPACES) {
    if (!minted.has(provider)) errors.push(`no fixture mints an alias in the ${provider} namespace`);
  }
  return errors;
}

export function validateCompanyFixtureSet(vocabulary, fixtures) {
  const errors = validateBlockFixtureSet(
    fixtures,
    (input) => mapCompanyBlock(vocabulary, input),
    REQUIRED_COMPANY_FIXTURES,
    "companies block",
  );
  if (!fixtures.some((fixture) => (fixture.expected?.unmapped?.roles ?? []).length > 0)) {
    errors.push("no fixture proves that an unrecognised raw company role is preserved");
  }
  const covered = new Set(fixtures.flatMap((fixture) => fixture.expected?.role_categories ?? []));
  for (const category of COMPANY_ROLE_CATEGORIES) {
    if (!covered.has(category)) errors.push(`role category has no conformance fixture: ${category}`);
  }
  return errors;
}
