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
GTIN would be its own vocabulary change and a further amendment to this record. Settled by the
[second 2026-09-25 amendment](#2026-09-25-upc-a-and-ean-13-are-one-gtin-at-lookup-no-alias-is-re-keyed)
below, at lookup time rather than as a vocabulary change.

### 2026-09-25: UPC-A and EAN-13 are one GTIN at lookup; no alias is re-keyed

The owner has decided that a 12-digit UPC-A barcode and the same digits with a leading zero,
its 13-digit EAN-13 form, are one GTIN and are treated as one barcode. This settles the
widening the amendment above left to a further amendment, and settles it at lookup time rather
than as a vocabulary change: stored `barcode` aliases keep the external id this record's
digits-only rule gave them.

**The rule.** GS1 defines GTIN-12, GTIN-13, and GTIN-14 as one number space. A shorter GTIN is
the same GTIN when it is right-aligned in a 14-digit field and filled with leading zeros
([GS1 General Specifications](https://www.gs1.org/standards/barcodes-epcrfid-id-keys/gs1-general-specifications),
section 3.3.2, the GTIN data structures, and the
[GS1 clarification of GTIN-14 creation](https://www.gs1.org/docs/barcodes/GSCN_21-258_GTIN14.pdf)).
The check digit is unchanged by that padding. The GS1 modulo-10 check digit (section 7.9.1)
weights digits from the right, starting with 3 for the digit beside the check digit, so a
leading zero contributes 0 at whatever weight it gets. `036000291452` and `0036000291452`
therefore carry the same check digit, 2. For barcode lookup this becomes:

1. Normalize the input with this record's `digits_only` rule, unchanged. It keeps the ASCII
   digits `0`-`9` only, as the Discogs producer, the shared Python runtime, and the reference
   mapper all do. Call the result `V`.
2. If `V` is 12 digits, or 13 digits, or 14 digits beginning with `0`, its GTIN key is `V`
   left-padded with zeros to 14 digits. Its equivalent values are the values of 12, 13, and 14
   digits that share that key:
   - a 12-digit `D` is equivalent to `0D` and `00D`;
   - a 13-digit `E` beginning with a non-zero digit is equivalent to `0E`;
   - a 13-digit `0D` is equivalent to `D` and `00D`, and a 14-digit value beginning with `0`
     is equivalent to the same value with its one or two leading zeros removed, as long as the
     result is 12 or 13 digits long.
3. Every other `V` is equivalent only to itself. That covers 8 digits (EAN-8 or UPC-E, which
   cannot be told apart, and UPC-E expands by an insertion rule, not by padding), 14 digits
   beginning with an indicator digit from `1` to `9` (GS1 uses the indicator for a different
   trade item, such as a case of the retail unit), and every other length.
4. The check digit is not validated. Stored aliases were never validated, padding cannot turn a
   valid GTIN into an invalid one or back, and rejecting an invalid value would make a
   stored-but-invalid alias unreachable.

**GTIN-14 is in scope, but only with indicator digit 0.** The owner's decision names 12 and 13
digits. The 14-digit form is included because the catalogs store it, measured below. The
`20260923` MusicBrainz dump holds 58,717 distinct 14-digit barcodes. 54,966 of them begin with
`00`, so they are GTIN-12s written in a 14-digit field, and 98.6% of all MusicBrainz 14-digit
values carry a valid check digit. 3,321 of the `00`-padded values also appear in MusicBrainz
as the bare 12-digit value. A person holding the sleeve types the 12 printed digits, and
without the 14-digit form those releases would never answer. Discogs is different. It holds
25,409 distinct 14-digit values, and only 20.4% of them are check-valid, so most are typing or
concatenation errors, which the rule leaves harmless: a value joins a GTIN's set only when its
digits are the same GTIN padded. A 14-digit value with a non-zero indicator is not the same
GTIN as anything shorter, so it stays exact.

**Lookup.** `GET /api/lookup/barcode/{value}` resolves the full set of equivalent values in one
read: current `provider_aliases` rows with provider `barcode`, kind `release`, and an
`external_id` in that set. `normalized` in the response stays the step-1 value. Then:

- **No row resolves:** `404`, as today.
- **All rows resolve to one native id:** the response is exactly today's response for that
  native id. Which stored form resolved it does not show.
- **Rows resolve to two or more native ids:** the lookup returns every one of them. It does not
  pick a winner, merge them, or hide any. Each entry carries its native id, the stored
  `external_id` that resolved it, and its releases as `releases_for_native_id` returns them
  today. Entries are ordered first by whether the stored value equals `V` (an exact match first),
  then by stored value length (shortest first), then by native id. The existing `gm_id` and
  `releases` fields name the first entry, so a single-item client keeps working. The full list is
  an additive field in `catalog-api`'s current API contract. Choosing the field's name is the
  implementing bead's job; its semantics are fixed here.

Current alias rows already point at the survivor of any native-id merge
([ADR 0009's amendment](0009-native-identity-and-provider-aliases.md#2026-09-25-superseded-catalog-items-and-native-id-merge),
section 4), so two entries are never one item seen twice through a supersession. The same
rule holds wherever a barcode is compared for identity: the `mcp-server` and `graph-explorer`
lookup surfaces call this endpoint, and any new reader that answers "which release carries
this barcode" applies these steps rather than an exact `external_id` match.

**What does not change.** No alias is re-keyed. The `digits_only` namespace rule, the
`taxonomy/identifiers/v1` vocabulary and its digest, and the three mappers (the Discogs
producer's, the shared Python runtime's, and the reference mapper) are unchanged, and no
conformance fixture moves. The loaders keep minting a `barcode` alias per exact digits-only
value through `common.identity.attach_aliases`, so a UPC-A form and an EAN-13 form of one GTIN
can still both be minted, to one native id or to two. The load-time conflict check stays an
exact `external_id` comparison. Equivalence is applied only when reading.

**The consequence, and why it is not a split signal.** The unique index gives each stored form
its own current row, so two forms of one GTIN can resolve to two different native items. The
lookup above answers that by returning both. The ADR 0014 section 8 re-attachment job does not
treat it as a split, and neither does anything else. Section 8 acts only on a catalog's
explicit link to another catalog's record. A barcode shared by two items is ordinary in this
catalog, not a sign of one item split in two: 294,299 distinct 12-digit barcodes each sit on more
than one Discogs release, because reissues and variants keep the barcode. A GTIN held in two
forms is the same evidence, spelled two ways. Inside the matcher it is already one key, under
ADR 0014 section 5, whose blocking key agrees with this rule on lengths 12 to 14, so it counts
as candidate evidence subject to section 4 and section 6, and nothing more.

**Measurement.** The counts are read-only aggregates, with no identifier committed
([script](../spikes/gm-design-ey3.1/README.md)). The Discogs side streamed the full
`discogs_20260901` releases dump: 19,417,067 releases, its SHA-256 matching the published
checksum, parsed with recovery off, and failing unless the stream ends in `</releases>`. The
MusicBrainz side read the `gm-design-1wd.1` compact snapshot of the `20260923` JSON dump, whose
5,797,718 releases the run checks against the stream's own count. Values are distinct
digits-only barcodes.

| | Discogs | MusicBrainz |
| --- | ---: | ---: |
| Releases with a barcode | 5,283,802 | 2,715,704 |
| 12-digit values | 1,769,071 | 1,250,405 |
| 13-digit values | 2,391,381 | 1,260,580 |
| of which begin with `0` | 194,660 | 97,635 |
| 14-digit values | 25,409 | 58,717 |
| of which begin with `00` | 3,121 | 54,966 |
| 8-digit values | 5,724 | 408 |
| GTINs held as both `D` and `0D` | 45,398 | 5,806 |
| of those, some release carries both forms | 34,499 | 0 |
| of those, the two forms sit only on different releases | 10,899 | 5,806 |

A MusicBrainz release carries one barcode, so its 5,806 GTINs held in both forms are always on
different releases. Across catalogs, 23,915 GTINs are held as `D` in MusicBrainz and as `0D` in
Discogs, and 20,937 the other way round. In 9,653 and 9,879 of those GTINs respectively, a
MusicBrainz release carrying one form already links to a Discogs release carrying the other.
For scale, 533,635 12-digit values and 580,253 13-digit values appear in the same form in both
catalogs. Over both catalogs together, since the alias table is shared, 71,380 of 5,553,143 in-scope GTINs (1.29%) are held in more than one form: 65,038 as 12 and 13 digits only, and 6,342 with a 14-digit form among them (4,495 as 12 and 14 digits, 1,229 as 13 and 14, and 618 in all three). These
are the GTINs whose stored aliases can resolve to more than one native item. How many actually
do depends on load order and on the links the loaders follow, so this is the upper bound
the lookup's multi-item answer serves.
