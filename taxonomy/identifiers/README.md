# Catalog identifier vocabulary

[`v1/identifier-types.json`](v1/identifier-types.json) is the closed identifier vocabulary that [ADR 0011](../../docs/adr/0011-catalog-identifiers-and-manufacturing-credits.md) makes authoritative for the `identifiers` block every Discogs releases event carries. It names the seven canonical types, the raw Discogs type strings each type maps from, the three alias namespaces that mint `provider_aliases` rows under [ADR 0009](../../docs/adr/0009-native-identity-and-provider-aliases.md), and the normalization each namespace applies before a value becomes an `external_id`.

Two schemas accompany it:

- [`v1/identifier-types.schema.json`](v1/identifier-types.schema.json) validates the vocabulary document itself.
- [`v1/identifier-block.schema.json`](v1/identifier-block.schema.json) validates the canonical `identifiers` block that producers attach to every releases event and that every release-shaped store carries.

[`v1/fixtures/`](v1/fixtures/discogs-barcode-and-catalogue-number.json) holds the conformance suite: each file holds a provider, a raw input in the shape the producer sees, and the exact expected block. `just identifiers` validates both schemas as JSON Schema 2020-12 documents, checks the vocabulary's closed sets and mapping rules, proves every fixture against the reference mapper in [`scripts/validation-policy.mjs`](../../scripts/validation-policy.mjs), and proves every expected block against the block schema. Every vendored mapper must reproduce these outputs byte for byte after canonical JSON serialisation (sorted object keys, no insignificant whitespace).

## Identifiers

- Canonical type ids are lowercase snake case: `barcode`, `matrix_runout`, `label_code`, `rights_society`, `asin`, `other`, and `catalog_number`.
- The first six are the targets the raw Discogs `identifiers` strings map onto. `catalog_number` has no raw identifier string behind it: it is lifted from the catalogue number the release's label entries carry, so every namespace that mints an alias has an entry in one list.
- Three types are alias namespaces and declare the ADR 0009 provider they mint into: `barcode` mints `barcode`, `catalog_number` mints `catalog_number`, and `matrix_runout` mints `matrix`. `label_code`, `rights_society`, `asin`, and `other` mint nothing and are stored in the block only.
- Every alias is minted with `source: catalog`, because the value came from the provider's own record.

## Mapping rules

- An entry in the raw `identifiers` list must be a plain object carrying a non-empty `type` and a non-empty `value` after trimming. A `null`, an array, a bare string or number, a missing type, or an empty value is skipped entirely and never recorded under `unmapped` — it never named an identifier.
- A raw type the vocabulary knows maps to its canonical type. A raw type it does not know maps to `other` **and** is recorded under `unmapped.types`. A raw type it knows and deliberately routes to `other` — `ISRC`, `Price Code`, `SPARS Code`, `Mastering SID Code`, `Mould SID Code`, `Pressing Plant ID` — is not recorded there, because it is mapped rather than unrecognised. The raw string survives under the item's `source.type` either way, so nothing is dropped and coverage stays measurable.
- A label entry contributes a `catalog_number` item when its `catno` is non-empty after trimming and is not the absent marker `none`, compared without case. Its `source.type` is `null` and its `source.field` is `labels[].catno`.
- Every vocabulary lookup is an own-property lookup, never a bare bracket access. An upstream type that happens to match an inherited `Object.prototype` member — `constructor`, `toString`, `hasOwnProperty`, `__proto__` — must still land in `unmapped` rather than silently resolving to that inherited value.
- Aliases are derived from the items: each item whose type is an alias namespace yields one `{provider, external_id}` pair, normalised by that namespace's rule, and an empty result yields none. Pairs are de-duplicated, so the same barcode written two ways is one alias and two items.
- Normalization is exactly three rules. `digits_only` keeps the ASCII digits in order; `upper_collapse_space` trims, collapses each run of whitespace to one space, and upper-cases; `collapse_space` trims and collapses whitespace but preserves case, because the characters stamped into a run-out groove are the evidence.
- `items` keep source order, with the label-derived entries after the identifier-derived ones. `types`, `aliases`, and `unmapped.types` are sorted and de-duplicated by Unicode code point, not by UTF-16 code unit — a distinction that only surfaces for astral characters. Every field is present, with `null` when unknown.

## Documentation consulted

The canonical type ids and the alias namespaces are this organization's own design, recorded in ADR 0011. The raw Discogs strings they map from are not: they are the strings Discogs itself emits.

They were taken from Discogs' published release API reference — the `identifiers` array of the release resource at `https://api.discogs.com/releases/{release_id}`, which the [Discogs data dumps documentation](https://data.discogs.com/) names as the specification the monthly XML dumps are formatted against. The endpoint was read directly on **2026-09-14** over a sample of 246 release resources, and the union of the `type` values it returned is the twelve strings this vocabulary maps:

`ASIN`, `Barcode`, `ISRC`, `Label Code`, `Mastering SID Code`, `Matrix / Runout`, `Mould SID Code`, `Other`, `Pressing Plant ID`, `Price Code`, `Rights Society`, `SPARS Code`.

A sample is evidence, not an enumeration: Discogs publishes no closed list of identifier types, and a rarer string certainly exists. That is precisely why an unrecognised type is preserved under `unmapped.types` and surfaced in the producer's data-quality report rather than dropped — adding it later is a vocabulary change followed by re-vendoring, never a code change in a consumer.

## Vendoring rule

The vocabulary is vendored verbatim, byte for byte, into every repository that computes or reads the identifiers block, beginning with `discogs-ingestion` and `python-libraries`. A vendored copy sits beside a source record naming the design commit and the SHA-256 of this file, and each repository's check gate fails when the copy drifts from that record. Compute the digest from the exact bytes of the file:

```console
shasum -a 256 taxonomy/identifiers/v1/identifier-types.json
```

`just publication-readiness` prints the same digest as `identifier_types_sha256` next to the catalog, media, identity, event, and company-role digests, so consumers can pin a reviewed commit and its vocabularies together.

## Current promotion record

The canonical v1 bytes have SHA-256
`2df8a691173f779b2d2076f31e8abd01d160e51f4f371de99f1f8e1cb12f26a5`.
No consumer has vendored the vocabulary yet; the first source records are written in wave 1 of
the rollout order ADR 0011 records. Consumer source records are promotion provenance; each
consumer remains responsible for reviewing and validating its vendored copy.

## Changing the vocabulary

Add or re-route a raw Discogs string in `identifier-types.json`, keep the mapping keys sorted, add a fixture for any new behaviour, and run `just check`. A new upstream type string is a vocabulary change followed by re-vendoring; it is never a code change in a consumer. Adding a canonical type, changing which types mint aliases, or changing a normalization rule is a breaking change: an alias `external_id` computed under an old rule is already stored, so it requires a new `vocabulary_version` directory and its own decision about the rows already minted.
