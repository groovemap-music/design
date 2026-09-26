# ADR 0011: Catalog identifiers, manufacturing credits, and release country

- Status: Accepted; amended 2026-09-25

## Context

Three catalog facts that exact-edition work depends on are present in the sources GrooveMap
already ingests and absent from everything downstream of ingestion.

The first is the Discogs release identifier. A release carries an `identifiers` list of
`{type, value, description}` entries whose type is a raw Discogs string — `Barcode`,
`Matrix / Runout`, `Label Code`, `Rights Society`, `ASIN`, `Other`, and a tail of narrower
strings such as `Mastering SID Code` and `Price Code`. The Discogs XML parser is a generic
element-to-JSON converter, so the list arrives intact inside the raw record without anyone
having written a rule for it, and `normalize.rs` never touches it. Nothing after that reads
it: no normalization, no index, no projection, no alias. Barcode lookup — the one gesture a
person with a record in their hand can perform — is impossible against a catalog that holds
every barcode it was given.

The second is the company credit. The same parser delivers the release's `companies` list,
each entry carrying a name, a Discogs label id, an optional catalogue number, a numeric
`entity_type`, and the `entity_type_name` string that names the relationship: `Pressed By`,
`Manufactured By`, `Lacquer Cut At`, `Mastered At`, `Recorded At`, `Mixed At`,
`Distributed By`, `Marketed By`, `Published By`, `Copyright (c)`,
`Phonographic Copyright (p)`, and more. That is the pressing-plant and mastering-chain
evidence two of the collector lenses are built on, and it rides uncleaned in the raw record
exactly like the identifiers do.

The third is release country. MusicBrainz ingestion keeps a field whitelist on the release
parser: `barcode` is on it, and `country`, the release-event list, and the catalogue numbers
inside `label-info` are not, so all three are dropped before publication. On the Discogs
side, country survives into PostgreSQL and is indexed there — `releases.data->>'country'`
already carries an index — but the Neo4j `Release` node has no `country` property at all,
so the graph cannot answer a question the relational store answers cheaply.

The precedents for the shapes this record needs already exist. The Discogs graph enricher
writes `(:Person)-[:CREDITED_ON {role}]->(:Release)` against a vendored set of credit-role
categories, which is the pattern for a credited party with a typed role, and
[ADR 0007](0007-canonical-media-taxonomy.md) established
`(:Release)-[:ISSUED_ON {qty, source}]->(:Medium)`, which is the pattern for a release-level
edge that records which catalog asserted it.
[ADR 0009](0009-native-identity-and-provider-aliases.md) went further still: its closed
provider vocabulary already reserves `barcode`, `catalog_number`, `isrc`, and `matrix` as
alias namespaces alongside `discogs` and `musicbrainz`. Those rows are reserved and unminted.
Nothing in the system writes one, because nothing has decided where the values come from.

One narrower shape is already in production and must not be confused with any of this.
`catalog-api`'s live per-user Discogs synchronisation writes a `catalog_number` property onto
the `Release` node it touches, taken from the catalogue number that user's collection row
carried. It is a per-collection assertion about one user's copy, written on a per-user code
path, and it is not the catalog-wide identifier record this decision creates.

Without a record, four producers and consumers would each invent an identifier shape, a
company role list, and a country projection, and barcode lookup would stay impossible.

## Decision

### Additive `identifiers` and `companies` blocks on every Discogs releases event

Every Discogs `releases` event gains two additive top-level objects, computed at the
normalization boundary before the content hash is recomputed, exactly as ADR 0007 attaches
the `media` block. The raw `identifiers` and `companies` lists are unchanged and remain the
provenance record.

The `identifiers` block has this shape:

| Field | Type | Meaning |
| --- | --- | --- |
| `identifiers_version` | string | The vocabulary version that produced the block (`"1"`). |
| `items` | array | One entry per source identifier, in source order. |
| `items[].type` | string | A canonical type id from the identifier vocabulary. |
| `items[].value` | string | The identifier value as received, trimmed. |
| `items[].description` | string or null | The free-text qualifier Discogs carries beside the value. |
| `items[].source` | object | `provider`, the raw `type` string as received, and the `field` it came from. |
| `types` | array of string | Sorted, unique canonical type ids across `items`. |
| `aliases` | array | Sorted, unique `{provider, external_id}` pairs the alias namespaces yield. |
| `unmapped` | object | `types`: sorted, unique raw type strings the vocabulary did not recognise. |

Canonical types are a closed set in version 1: `barcode`, `matrix_runout`, `label_code`,
`rights_society`, `asin`, `other`, and `catalog_number`. The first six are the targets the
raw Discogs `identifiers` strings map onto. `catalog_number` has no raw identifier string
behind it: it is lifted from the catalogue number the release's label entries carry, so that
every namespace that mints an alias has an entry in one list and the loaders read one list
rather than two. A raw type the vocabulary does not know becomes `other` and is additionally
recorded in `unmapped.types`; a raw type the vocabulary knows and deliberately routes to
`other` — `ISRC`, `Price Code`, `SPARS Code`, the two SID codes, `Pressing Plant ID` — is not,
because it is mapped, not unrecognised. The raw string survives under `source.type` either
way, so nothing is ever dropped and coverage stays measurable.

The `companies` block has this shape:

| Field | Type | Meaning |
| --- | --- | --- |
| `companies_version` | string | The vocabulary version that produced the block (`"1"`). |
| `items` | array | One entry per source company, in source order. |
| `items[].name` | string | The company name as received, trimmed. |
| `items[].discogs_id` | integer or null | The Discogs label id of the company. |
| `items[].role` | string | The raw Discogs `entity_type_name`, preserved verbatim. |
| `items[].role_category` | string | A category id from the company-role vocabulary. |
| `items[].catno` | string or null | The catalogue number the company entry carried. |
| `items[].source` | object | `provider` and the numeric `entity_type` as received. |
| `role_categories` | array of string | Sorted, unique category ids across `items`. |
| `unmapped` | object | `roles`: sorted, unique raw role strings the vocabulary did not recognise. |

Role categories are a closed set in version 1: `manufacturing`, `mastering`, `lacquer`,
`pressing`, `distribution`, `marketing`, `rights`, `recording_facility`, and `other`.
`lacquer` covers the fabrication of the physical transfer master in any medium — lacquer
cutting, glass mastering, and stamper plating — while `mastering` is the audio mastering step;
separating them is what keeps a vinyl cutting room and a mastering house from collapsing into
one signal. An unrecognised role becomes `other` and is recorded in `unmapped.roles`.

Ordering is deterministic so independent implementations produce byte-identical output:
`items` follow source order; `types`, `role_categories`, `aliases`, and both `unmapped` lists
are sorted and de-duplicated; every field is present, with `null` when unknown. Entries that
are not plain objects are skipped entirely and contribute nothing, not even an unmapped value,
following the rule ADR 0007 set for malformed format entries. Unmapped types and roles are
surfaced in the producer's data-quality report, so a new upstream string is a vocabulary
change rather than a code change.

### MusicBrainz country, release events, and catalogue numbers

The MusicBrainz release whitelist gains three additive fields: `country`, the release-event
list (date and area per event), and the catalogue numbers carried inside `label-info`. This is
a whitelist change in the parser and nothing else; `barcode` already passes and keeps passing.

MusicBrainz manufacturing relations stay where they are. They arrive in the generic relations
bag, they are modelled differently from Discogs company credits, and reconciling the two
vocabularies is not attempted here.

### Vocabulary homes, vendoring, and which types mint aliases

Two vocabularies are published in this repository, each as a vocabulary document, a JSON
Schema for that document, a JSON Schema for the block it produces, a conformance fixture set,
and a README carrying the digest:

- `taxonomy/identifiers/v1` owns the canonical identifier types, the raw Discogs type strings
  each maps from, and the alias namespaces.
- `taxonomy/company-roles/v1` owns the role categories and the raw Discogs
  `entity_type_name` strings each maps from.

ADR 0005 rules out a third shared crate and a third contract repository, so both are vendored
verbatim, byte for byte, into `discogs-ingestion` and `python-libraries`. Each vendored copy
carries a source record naming the design commit and the SHA-256, and each repository's check
gate fails when the copy drifts from that record. `just check` validates both vocabularies,
both schemas, and every fixture here, and `just publication-readiness` prints both digests
beside the catalog, media, identity, and event digests.

Three of the seven canonical identifier types are alias namespaces, and they mint
`provider_aliases` rows against the release's native id under ADR 0009: `barcode` from the
`barcode` type, `catalog_number` from the `catalog_number` type, and `matrix` from the
`matrix_runout` type. Each namespace declares the normalization applied before the value
becomes an `external_id`: barcodes keep their digits only, catalogue numbers are upper-cased
with internal whitespace collapsed, and matrix inscriptions keep their case with whitespace
collapsed, because a matrix inscription's characters are the evidence. Every minted row
carries `source: catalog`, since the value came from the provider's own record.

`label_code`, `rights_society`, `asin`, and `other` are stored in the block only. They mint
nothing, and the ADR 0009 provider vocabulary is not widened to admit them: a namespace
belongs there when something resolves an entity through it, and nothing resolves a release by
its rights society. `isrc` remains reserved and unminted by this record — the Discogs `ISRC`
identifier string is a release-level annotation, while the ADR 0009 `isrc` namespace names a
recording, and minting one from the other would assert an identity that is not the same
identity.

### Storage

PostgreSQL gains no column. The two blocks ride inside the existing `data` JSONB on the
releases tables, with GIN indexes on `data->'identifiers'` and `data->'companies'` so a
containment query is answerable. Barcode and catalogue-number lookup does not use those
indexes: it resolves through `provider_aliases`, which already has the uniqueness rule that
makes a lookup exact, so the identifier indexes serve analytical containment queries and the
alias table serves lookup. Every change is additive inside persistence contract v1.

Neo4j gains `(:Company {id, name})` with a uniqueness constraint on `id`, and
`(:Release)-[:CREDITED_TO {role, role_category, source}]->(:Company)`. The edge follows the
two precedents exactly: the typed `role` property from `(:Person)-[:CREDITED_ON]->(:Release)`,
and the `source` property from `(:Release)-[:ISSUED_ON {qty, source}]->(:Medium)`, so a
credit a second catalog asserts is distinguishable from a Discogs one without a second edge
type. Edges are written prune-then-merge, so a company removed upstream disappears rather than
accumulating.

`Release.country` is added as an additive property with a range index, written by the Discogs
graph enricher from the release's country and by the MusicBrainz graph enricher as
`mb_country` on releases it matches. The rule that the MusicBrainz enricher creates no release
without a Discogs identifier is unchanged.

The existing per-user `Release.catalog_number` property written by `catalog-api`'s live
synchronisation is left exactly as it is. It is documented as a per-collection assertion about
one user's copy, distinct from the catalog-wide `catalog_number` entries in the identifiers
block and from the `catalog_number` aliases those entries mint. The two are not reconciled and
neither overwrites the other.

### Lookup, country facet, and release detail

`catalog-api` gains `GET /api/lookup/{provider}/{value}` for the `barcode` and
`catalog_number` providers. It normalises the value with the namespace's declared rule,
resolves it through `provider_aliases`, and returns the release with both its native and its
provider identifiers, or a not-found result. Only namespaces that mint rows are addressable,
so an unsupported provider is rejected rather than silently returning nothing.

Release search gains a `country` facet, and the release detail response gains the
`identifiers` and `companies` blocks as additive fields. `graph-explorer` and `mcp-server`
promote the consumer contracts and surface barcode and catalogue-number lookup in search, the
company credits on the release view, and a lookup tool.

### Wave order

The program is delivered one molecule per repository, each pinning both vocabulary digests and
the upstream contract commits it consumes:

0. `design`: this record and the two vocabularies.
1. `discogs-ingestion`, `musicbrainz-ingestion`, `python-libraries`, and `database-schema` in
   parallel.
2. `discogs-sql-loader` (mint `barcode` and `catalog_number` aliases per batch through
   `common.identity`, and backfill the rows whose content hash did not change),
   `musicbrainz-sql-loader` (attach barcode aliases to the release's native id),
   `discogs-graph-enricher` (`Company` nodes, `CREDITED_TO` edges, `Release.country`), and
   `musicbrainz-graph-enricher` (`mb_country`).
3. `catalog-api`: the lookup endpoint, the country facet, the two blocks on release detail,
   and the consumer contracts.
4. `graph-explorer` and `mcp-server`.
5. `deployment`: a smoke assertion that a barcode resolves to a release after ingestion.

## Consequences

A person holding a record can find it. Barcode and catalogue-number lookup resolve through the
same alias table that ADR 0009 built and left empty, so the namespaces it reserved stop being
a promise. Pressing plant, lacquer cutting room, and mastering house become queryable in the
graph with the same edge grammar that already carries person credits and media, which is what
the exact-edition and manufacturing-chain lenses need. Release country stops being a fact only
one store knows.

The cost is two more vocabularies to vendor and keep in step, and three mappers that must
agree — the Discogs producer's, the shared Python runtime's, and the reference mapper the
conformance fixtures are proved against. That is the same cost ADR 0007 accepted for media,
and the fixtures are again what keeps the implementations identical rather than merely
similar.

The per-user `Release.catalog_number` property is now one of two things in the graph named
after a catalogue number. They are deliberately not merged: one is what a user's own collection
row said, the other is what the catalog says about the release. Documenting the difference is
the whole mitigation, and a consumer that treats them as interchangeable will be wrong about
whose assertion it is reading.

Deferred to their own records:

- **MusicBrainz manufacturing relations.** They stay in the generic relations bag. Mapping
  them onto the same role categories means reconciling two relationship vocabularies, and that
  is a decision about equivalence, not about storage.
- **Places on releases.** Both catalogs can name where something happened, and a pressing plant
  or a studio is arguably a place with a location rather than a company with a name. This
  record models the credit, not the geography behind it.
- **ISRC minting.** The namespace stays reserved. Minting it needs a recording entity to hang
  it on, which ADR 0009 explicitly left undecided.
- **Identifier-driven edition matching.** A shared matrix inscription or barcode across two
  releases is strong evidence they are the same pressing. This record makes that evidence
  available and queryable; what a matcher does with it is not settled here. Settled by
  [ADR 0014](0014-cross-catalog-edition-candidates.md); see the 2026-09-25 amendment below.

## Amendments

### 2026-09-25: Edition matching decided; alias normalization unchanged

[ADR 0014](0014-cross-catalog-edition-candidates.md) settles the edition-matching deferral
above, on the evidence of the
[Semantica identity-matching spike](../spikes/gm-design-zwy-semantica-identity-matching.md).
That spike compared barcodes and catalogue numbers under two keys wider than this record's:
a 12-digit UPC-A barcode also as its 13-digit EAN-13 form with a leading zero, and a
catalogue number also as a compact key with punctuation and spaces removed.

ADR 0014 adopts both only as blocking and comparison keys inside its matcher and declines
them as alias normalization. The namespace rules in "Vocabulary homes, vendoring, and which
types mint aliases" above are unchanged: a `barcode` alias keeps its digits only, and a
`catalog_number` alias is upper-cased with internal whitespace collapsed. No minted alias changes
its external id, the identifier vocabulary does not change, and the lookup endpoint's
normalization stays as decided here. A future widening of the barcode rule to treat UPC-A and EAN-13 as one
GTIN would be its own vocabulary change and a further amendment to this record.
