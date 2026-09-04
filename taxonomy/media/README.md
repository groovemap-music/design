# Canonical media taxonomy

[`v1/media-taxonomy.json`](v1/media-taxonomy.json) is the provider-neutral media vocabulary that [ADR 0007](../../docs/adr/0007-canonical-media-taxonomy.md) makes authoritative for every GrooveMap service. It names the closed family set, every canonical medium, the closed value sets for medium attributes and release facts, and the mapping of every known Discogs format name and description and every known MusicBrainz medium format, status, packaging, and release-group type onto that vocabulary.

Two schemas accompany it:

- [`v1/media-taxonomy.schema.json`](v1/media-taxonomy.schema.json) validates the vocabulary document itself.
- [`v1/media-block.schema.json`](v1/media-block.schema.json) validates the canonical `media` block that producers attach to every releases event and that every release-shaped store carries.

[`v1/fixtures/`](v1/fixtures/discogs-7-inch-45-single.json) holds the conformance suite: each file holds a provider, a raw input in the shape the producer sees, and the exact expected block. `just taxonomy` validates both schemas, checks the vocabulary's internal consistency, and proves every fixture against the reference mapper in [`scripts/media-mapper.mjs`](../../scripts/media-mapper.mjs). Every vendored mapper must reproduce these outputs byte for byte after canonical JSON serialisation (sorted object keys, no insignificant whitespace).

## Identifiers

- Family ids are lowercase snake case: `vinyl`, `shellac`, `grooved_other`, `tape`, `optical`, `digital`, `video`, `other`.
- Medium ids are prefixed by their family: `vinyl_12`, `optical_cd`, `digital_file`. Every family has a `<family>_unspecified` medium for entries whose family is known but whose medium is not.
- Value ids for channels, codecs, variants, appearances, release kinds, traits, editions, packagings, containers, and flags are listed under `values` and are the only values a block may carry.

## Mapping rules

- A Discogs format name maps to a medium, to a family (resolved to a medium by a size descriptor, otherwise `<family>_unspecified`), to a container (`Box Set`), or to a flag (`All Media`). A Discogs description maps to exactly one target: a medium attribute (`size_inches`, `speed_rpm`, `channels`, `codec`, `variant`, `appearance`), a release fact (`release_kind`, `trait`, `edition`, `packaging`, `container`, `flag`), or `ignore` for descriptors that are known but carry no modelled meaning.
- A MusicBrainz medium format maps to a medium or a family the same way; `status` maps to an edition, `packaging` to a packaging, the release-group primary type to the release kind, and secondary types to traits.
- The first value wins for scalar release facts; list facts are sorted and de-duplicated; `items` keep source order; every raw value the vocabulary does not know is recorded under `unmapped` and never dropped.
- A format or medium entry must be a plain object; a `null`, an array, a string, or a number in that position is skipped entirely and never recorded under `unmapped` — it never named a format or medium in the first place.
- Every vocabulary lookup (formats, descriptions, status, packaging, primary/secondary types, and a family's size-resolution map) is an own-property lookup, never a bare bracket access. An upstream name that happens to match an inherited `Object.prototype` member — `constructor`, `toString`, `hasOwnProperty`, `__proto__` — must still land in `unmapped` rather than silently resolving to that inherited value.
- Every sorted list (`unmapped.formats`, `unmapped.descriptions`, `families`, `traits`, `edition`, `flags`, an item's `variants` and `appearance`) is ordered by Unicode code point, not by UTF-16 code unit — a distinction that only surfaces for astral characters (outside the Basic Multilingual Plane).
- Medium defaults (for example 78 RPM for shellac, 12 inches for a 12" medium) fill attributes that the source did not state.

## Vendoring rule

The vocabulary is vendored verbatim, byte for byte, into `discogs-ingestion`, `musicbrainz-ingestion`, and `python-libraries`. A vendored copy sits beside a source record naming the design commit and the SHA-256 of this file, and each repository's check gate fails when the copy's digest differs from that record. Compute the digest from the exact bytes of the file:

```console
shasum -a 256 taxonomy/media/v1/media-taxonomy.json
```

`just publication-readiness` prints the same digest as `media_taxonomy_sha256` next to the catalog digest, so consumers can pin a reviewed commit and its vocabulary together.

## Changing the vocabulary

Add or re-route values in `media-taxonomy.json`, keep mapping keys sorted, add a fixture for any new behaviour, and run `just check`. A new upstream format name is a vocabulary change followed by re-vendoring; it is never a code change in a consumer. Renaming or removing an id, or changing what a target means, is a breaking change and requires a new `taxonomy_version` directory.
