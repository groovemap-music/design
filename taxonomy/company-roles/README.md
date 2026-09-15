# Company-role vocabulary

[`v1/company-roles.json`](v1/company-roles.json) is the closed role vocabulary that [ADR 0011](../../docs/adr/0011-catalog-identifiers-and-manufacturing-credits.md) makes authoritative for the `companies` block every Discogs releases event carries and for the `(:Release)-[:CREDITED_TO]->(:Company)` edge the graph projects from it. It names the nine role categories and the raw Discogs company `entity_type_name` strings each category maps from.

Two schemas accompany it:

- [`v1/company-roles.schema.json`](v1/company-roles.schema.json) validates the vocabulary document itself.
- [`v1/company-block.schema.json`](v1/company-block.schema.json) validates the canonical `companies` block that producers attach to every releases event.

[`v1/fixtures/`](v1/fixtures/discogs-pressing-and-transfer-master.json) holds the conformance suite: each file holds a provider, a raw input in the shape the producer sees, and the exact expected block. `just company-roles` validates both schemas as JSON Schema 2020-12 documents, checks the vocabulary's closed set and mapping rules, proves every fixture against the reference mapper in [`scripts/validation-policy.mjs`](../../scripts/validation-policy.mjs), and proves every expected block against the block schema. Every vendored mapper must reproduce these outputs byte for byte after canonical JSON serialisation (sorted object keys, no insignificant whitespace).

## Identifiers

- Category ids are lowercase snake case: `manufacturing`, `mastering`, `lacquer`, `pressing`, `distribution`, `marketing`, `rights`, `recording_facility`, and `other`.
- `lacquer` and `mastering` are deliberately separate. `lacquer` is the fabrication of the physical transfer master in any medium — lacquer cutting, glass mastering, and stamper plating — while `mastering` is the audio mastering step. Collapsing them would make a vinyl cutting room and a mastering house the same signal, which is exactly the distinction the exact-edition work depends on.
- `pressing` is the plant that pressed the discs and nothing else. General manufacture, tape duplication, and print work are `manufacturing`.
- `rights` covers every commercial or legal relationship to the release: copyright, phonographic copyright, publishing, licensing in either direction, the record company of record, and the party a release was produced for.
- The item carries both the raw `role` string, preserved verbatim, and the mapped `role_category`. A consumer that needs the precise relationship reads `role`; a consumer that needs to reason across catalogs reads `role_category`.

## Mapping rules

- The block is computed from the release's `companies` list only. The issuing-label relation lives in the separate `labels` list, is not a company credit, and contributes nothing here; its catalogue number feeds the identifier vocabulary instead.
- An entry in `companies` must be a plain object carrying a non-empty `name` and a non-empty `entity_type_name` after trimming. A `null`, an array, a bare string or number, a missing name, or a missing role is skipped entirely and never recorded under `unmapped` — it never named a credit.
- A raw role the vocabulary knows maps to its category. A raw role it does not know maps to `other` **and** is recorded under `unmapped.roles`, so a new upstream relationship is measurable and is added by a vocabulary change rather than a code change.
- Every vocabulary lookup is an own-property lookup, never a bare bracket access, so an upstream role that happens to match an inherited `Object.prototype` member still lands in `unmapped`.
- `discogs_id` is the Discogs label id when it is a positive integer and `null` otherwise. `catno` is the company's own number — a plant job number, for instance — or `null` when absent. `source.entity_type` keeps Discogs' numeric code as a string when it is one, and is `null` otherwise, so a role Discogs sent without a code is still a credit.
- `items` keep source order. `role_categories` and `unmapped.roles` are sorted and de-duplicated by Unicode code point, not by UTF-16 code unit. Every field is present, with `null` when unknown.

## Documentation consulted

The nine role categories and the mapping of roles onto them are this organization's own design, recorded in ADR 0011. The raw Discogs strings they map from are not: they are the strings Discogs itself emits.

They were taken from Discogs' published release API reference — the `companies` array of the release resource at `https://api.discogs.com/releases/{release_id}`, where each entry carries a numeric `entity_type` and the `entity_type_name` string this vocabulary keys on, and which the [Discogs data dumps documentation](https://data.discogs.com/) names as the specification the monthly XML dumps are formatted against. The endpoint was read directly on **2026-09-14** over a sample of 246 release resources. The union of the `entity_type_name` values it returned, with the code Discogs paired with each, was:

| Code | Role | Code | Role |
| --- | --- | --- | --- |
| 4 | `Record Company` | 24 | `Engineered At` |
| 5 | `Licensed To` | 26 | `Produced At` |
| 6 | `Licensed From` | 27 | `Mixed At` |
| 7 | `Licensed Through` | 29 | `Mastered At` |
| 8 | `Marketed By` | 30 | `Lacquer Cut At` |
| 9 | `Distributed By` | 31 | `Glass Mastered At` |
| 10 | `Manufactured By` | 33 | `Designed At` |
| 11 | `Exported By` | 36 | `Edited At` |
| 13 | `Phonographic Copyright (p)` | 37 | `Produced For` |
| 14 | `Copyright (c)` | 39 | `Recorded By` |
| 16 | `Made By` | 43 | `Funded By` |
| 17 | `Pressed By` | 44 | `Plated At` |
| 19 | `Printed By` | | |
| 21 | `Published By` | | |
| 23 | `Recorded At` | | |

Code 1, `Label`, appears only in the release's `labels` list and is excluded for the reason given above.

Two further strings are mapped that the sample did not surface: `Duplicated By` and `Manufactured For`, both carried from the company roles the catalog-identifiers program enumerated, and both mapped to `manufacturing`. They are mapped rather than left out because a tape duplicator and a contract manufacturer are exactly the credits the manufacturing category exists for; the vocabulary records no numeric code for either, and the block's `source.entity_type` is whatever Discogs sends.

A sample is evidence, not an enumeration: the numeric codes above are visibly not contiguous, so roles this repository has not seen certainly exist. That is why an unrecognised role is preserved under `unmapped.roles` and surfaced in the producer's data-quality report rather than dropped.

## Vendoring rule

The vocabulary is vendored verbatim, byte for byte, into every repository that computes or reads the companies block, beginning with `discogs-ingestion` and `python-libraries`. A vendored copy sits beside a source record naming the design commit and the SHA-256 of this file, and each repository's check gate fails when the copy drifts from that record. Compute the digest from the exact bytes of the file:

```console
shasum -a 256 taxonomy/company-roles/v1/company-roles.json
```

`just publication-readiness` prints the same digest as `company_roles_sha256` next to the catalog, media, identity, event, and identifier digests, so consumers can pin a reviewed commit and its vocabularies together.

## Current promotion record

The canonical v1 bytes have SHA-256
`03ab8689ba14768dceffb756a71475c01797caea8d18ba9943cd5f69b3d705de`.
No consumer has vendored the vocabulary yet; the first source records are written in wave 1 of
the rollout order ADR 0011 records. Consumer source records are promotion provenance; each
consumer remains responsible for reviewing and validating its vendored copy.

## Changing the vocabulary

Add or re-route a raw Discogs role in `company-roles.json`, keep the mapping keys sorted, add a fixture for any new behaviour, and run `just check`. A new upstream role string is a vocabulary change followed by re-vendoring; it is never a code change in a consumer. Adding, renaming, or removing a category, or changing what a category means, is a breaking change and requires a new `vocabulary_version` directory, because a `role_category` already written onto a `CREDITED_TO` edge cannot be reinterpreted in place.
