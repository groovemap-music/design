# ADR 0007: Canonical media taxonomy and media-neutral product core

- Status: Accepted

## Context

GrooveMap describes release formats as a bag of Discogs strings. The Discogs producer emits
each release's raw `formats` list (a format name, a quantity, optional free text, and a
nested list of descriptions), the Discogs graph enricher flattens the names into one
`formats` list property on the release node, and the loaders store the raw objects inside
JSONB. Medium, size, speed, channel configuration, release type, edition, and packaging all
travel in the same descriptions list with no type tag, so every consumer that needs one of
them re-derives it differently. MusicBrainz mediums are never read from the dump: the
MusicBrainz release parser keeps a whitelist of fields that omits `media`, so the medium
format, position, and track count of every MusicBrainz release are lost before publication.

Neither store has a media entity. Neo4j has no Medium node, no index, and no constraint on
the `formats` property, while Genre and Style are first-class nodes with relationships.
PostgreSQL has no media column or index, and the user collection and wantlist tables store
formats in two different shapes (an array of raw objects versus one scalar name). Product
logic inherited the same bias: the rarity index applies a pressing-scarcity signal to every
medium, its format table mixes families with descriptors on one scale, gap analysis is framed
as missing pressings, and the time-travel endpoints are documented under a vinyl name.

GrooveMap intends to cover every kind of media that Discogs and MusicBrainz carry: grooved
discs, tape, optical discs, digital files, video, and legacy media. A vinyl-specific service
may exist later, but it must be an extension of a media-neutral core, not the shape of the
core itself. Without a recorded decision, fifteen repositories would each invent a
vocabulary, a storage shape, and a scoring rule, and the vinyl bias would survive as fifteen
inconsistent copies.

## Decision

### Canonical media block

Every `releases` event gains an additive top-level `media` object. The raw provider fields
(`formats` for Discogs; the raw medium list for MusicBrainz) are unchanged and remain the
provenance record. The block has this shape:

| Field | Type | Meaning |
| --- | --- | --- |
| `taxonomy_version` | string | The vocabulary version that produced the block (`"1"`). |
| `items` | array | One entry per source medium entry, in source order. |
| `items[].family` | string | A family id from the closed set below. |
| `items[].medium` | string | A medium id from the vocabulary; `<family>_unspecified` when the family is known but the medium is not. |
| `items[].qty` | integer | Units of this medium (Discogs `qty`; `1` per MusicBrainz medium). |
| `items[].size_inches` | number or null | Disc or tape width where derivable. |
| `items[].speed_rpm` | number or null | Rotational speed where derivable. |
| `items[].channels` | string or null | `mono`, `stereo`, `quadraphonic`, `multichannel`, or `ambisonic`. |
| `items[].codec` | string or null | Digital encoding where derivable. |
| `items[].variants` | array of string | Medium refinements such as `shm_cd`, `hdcd`, `hybrid_layer`; sorted, unique. |
| `items[].appearance` | array of string | Cosmetic traits such as `picture_disc`, `coloured`, `etched`; sorted, unique. |
| `items[].position` | integer or null | MusicBrainz medium position. |
| `items[].track_count` | integer or null | MusicBrainz medium track count. |
| `items[].source` | object | `provider`, `name`, `descriptions` (flat list), and `text` as received. |
| `families` | array of string | Sorted, unique family ids across `items`. |
| `release_kind` | string or null | `album`, `single`, `ep`, `broadcast`, or `other`. |
| `traits` | array of string | Release traits such as `compilation`, `live`, `soundtrack`, `remix`; sorted, unique. |
| `edition` | array of string | Edition facts such as `reissue`, `remastered`, `limited`, `promo`, `test_pressing`, `unofficial`; sorted, unique. |
| `packaging` | string or null | Packaging id from the vocabulary. |
| `container` | string or null | `box_set` when the release is a multi-format set. |
| `flags` | array of string | Release-level markers that are not media, such as `all_media`; sorted, unique. |
| `unmapped` | object | `formats` and `descriptions`: sorted, unique raw values the vocabulary did not recognise. |

Families are a closed set in version 1: `vinyl`, `shellac`, `grooved_other` (acetate, lathe
cut, flexi disc, cylinder, and other grooved media), `tape`, `optical`, `digital`, `video`,
and `other`. Families carry two boolean facts that product logic may key on: `physical` and
`grooved`.

The vocabulary decides routing. A Discogs description or a MusicBrainz value maps to exactly
one target: a medium attribute (`size_inches`, `speed_rpm`, `channels`, `codec`, `variant`,
`appearance`), a release fact (`release_kind`, `trait`, `edition`, `packaging`, `container`,
`flag`), or `ignore`. Descriptors such as Album, Single, EP, Compilation, Reissue, Remastered,
Limited Edition, and Promo therefore never become a medium. Discogs `Box Set` and
`All Media` are release-level facts, not media. Discogs `Hybrid` resolves to the SACD medium
with the `hybrid_layer` variant. MusicBrainz `Digital Media` and Discogs `File` are the same
digital medium; MusicBrainz `Other` maps to the `other` family, never to digital. Every raw
value the vocabulary does not know is preserved in `unmapped` and never dropped, so coverage
is measurable and a new upstream value is a vocabulary change, not a code change.

Ordering is deterministic so independent implementations produce byte-identical output:
`items` follow source order; every list that is not `items` or `source.descriptions` is
sorted and de-duplicated; every field is present, with `null` or an empty list when unknown.

### Producer-boundary computation and contract compatibility

Each producer computes the block once, where it already normalises records. The Discogs
producer attaches `media` after record normalisation and before it recomputes the content
hash, so the hash covers the block. The MusicBrainz producer starts keeping the raw medium
list (format, position, title, and track count; never tracks or disc ids) and computes the
block in its parser, which is that producer's normalisation boundary. The change is additive
inside the `groovemap.catalog-events` v1 contract: the data envelope already admits
source-specific additive fields, and no exchange, queue, or consumer name changes. Consumers
that receive an event without `media` (a producer that predates this decision) derive a
best-effort block from the raw names through the shared Python helper, so no store is ever
half-populated.

### Vocabulary home and vendoring

The vocabulary is one JSON document owned by this repository at
`taxonomy/media/v1/media-taxonomy.json`, with a JSON Schema for the vocabulary, a JSON
Schema for the canonical block, and a conformance fixture set of input and expected-output
pairs. `just check` validates all three and proves the fixtures against a reference mapper
kept beside the validator. The publication handoff prints the vocabulary's SHA-256 alongside
the catalog digest.

ADR 0005 rules out a third shared Rust crate and a third contract repository, so the
vocabulary is vendored verbatim, byte for byte, into `discogs-ingestion`,
`musicbrainz-ingestion`, and `python-libraries`. Each vendored copy carries a source record
naming the design commit and SHA-256, and each repository's check gate fails when the copy
drifts from that record. Each Rust producer carries its own mapper; Python services share one
mapper through the runtime library, which the catalog API also needs for the live Discogs
collection and wantlist synchronisation that never passes through an event. Every mapper must
pass the same conformance fixtures.

### Storage

Neo4j gains `Medium` nodes (unique `id`, plus `family` and `label`) and `MediaFamily` nodes
(unique `name`), with `(:Medium)-[:IN_FAMILY]->(:MediaFamily)` and
`(:Release)-[:ISSUED_ON {qty, source}]->(:Medium)`. The release node also carries a
`media_families` list property for cheap filtering. This mirrors the Genre and Style pattern
that consumers already query. The MusicBrainz enricher adds `ISSUED_ON` edges tagged
`source: musicbrainz` to releases it matches, so a release known to both catalogs shows both
catalogs' media and the API can reconcile disagreements. The rule that the MusicBrainz
enricher creates no release without a Discogs identifier is unchanged.

PostgreSQL gains an indexed `media` JSONB column on every release-shaped table (the Discogs
releases table, the MusicBrainz releases table, user collections, and user wantlists), with
GIN indexes on the families list, and additive columns on the precomputed rarity table. The
wantlist and collection tables converge on the same canonical column. Every change is
additive inside persistence contract v1: expand only, no renames, no type changes.

### Media-neutral core and per-family extensions

Product logic is a core that reasons about every medium the same way, plus extension modules
keyed by family. Rarity keeps label catalog size, temporal scarcity, graph isolation, and
collection prevalence as core signals and replaces the descriptor-keyed format table with a
`medium_rarity` signal keyed by canonical medium id. Pressing scarcity moves into a grooved
extension that contributes only for `vinyl`, `shellac`, and `grooved_other`. Weights are
renormalised over the signals present so every score stays on the same 0 to 100 scale; the
breakdown reports which family signals contributed. Gap analysis, label DNA, search,
natural-language queries, and the agent tools accept a `media` filter that takes family or
medium ids. The `formats` request parameters and response keys survive as deprecated aliases
for one minor version, mapped through the shared helper, and are then removed.

This extension seam is the boundary a future vinyl-specific service would own. Generic to the
core and never moved: the vocabulary, the canonical block, the storage shape, the media
filter, medium rarity, and every non-grooved family. Specific to grooved media and therefore
candidates for such a service: pressing scarcity and its sibling counting, pressing plant,
matrix and runout, lacquer and stamper lineage, colour and appearance evidence, and any
signal that reasons about a physical pressing rather than a release.

### Rollout order

The program is delivered one molecule per repository, in five waves, each pinning the
vocabulary digest and the upstream contract commits it consumes:

1. `discogs-ingestion`, `musicbrainz-ingestion`, `python-libraries`, and `database-schema`
   in parallel.
2. `discogs-graph-enricher`, `discogs-sql-loader`, `musicbrainz-sql-loader`,
   `musicbrainz-graph-enricher`, and `operations-toolkit`.
3. `catalog-api` and `analytics-engine`.
4. `graph-explorer`, `mcp-server`, `operations-console`, and the public site.
5. `deployment`, including the per-source extractor image cutover that ADR 0005 prescribes
   and an end-to-end assertion that the block reaches both stores.

## Consequences

Every service reads one vocabulary and one block shape, so a medium filter, a rarity score,
or a badge means the same thing in the graph, the relational store, the API, the explorer,
and an AI client. New upstream format names surface as measurable `unmapped` values and as a
warning in the producer's data-quality report, and adding them is a vocabulary change that
flows through vendoring rather than a code change in fifteen repositories. Three mappers exist
by design (two Rust, one Python), which is the cost ADR 0005 accepted; the shared conformance
fixtures are what keep them identical. Consumers see two format representations during the
deprecation window, and the raw provider fields remain forever as provenance. The grooved
extension is the only place vinyl-specific reasoning is allowed to live, which is what makes a
later vinyl service a clean split rather than a fork.

## Appendix: mapping rules for the ambiguous cases

The vocabulary is authoritative; these rules explain the choices it encodes.

- **Box Set** (Discogs format name): not a medium. Sets `container: box_set` and adds no item.
  The set's real media arrive as sibling format entries and are mapped normally.
- **All Media** (Discogs format name): not a medium. Adds the `all_media` flag and no item.
- **Hybrid** (Discogs format name): a hybrid SACD. Maps to the SACD medium in the optical
  family with the `hybrid_layer` variant.
- **Vinyl as a MusicBrainz parent**: the family is known and the medium is not, so the item
  maps to `vinyl_unspecified`; the sized children (`7" Vinyl`, `10" Vinyl`, `12" Vinyl`) map
  to a medium. The `CD` and `Cassette` parents are not ambiguous and map straight to the
  `optical_cd` and `tape_cassette` media, with their children adding variants.
- **Digital Media** (MusicBrainz) and **File** (Discogs): the same digital medium. Codec is
  derivable from Discogs descriptions only.
- **Other** (MusicBrainz): `other` family, `other_unspecified` medium. Never digital.
- **LP, 7", 10", 12"**: size only. `LP` sets `size_inches` to 12 and does not set the release
  kind; `Album` does.
- **Album, Single, EP, Maxi-Single, Mini-Album**: release kind. **Compilation, Mixtape,
  Sampler, Mixed** and the MusicBrainz secondary types: traits.
- **Reissue, Remastered, Repress, Limited Edition, Numbered, Promo, Test Pressing, White
  Label, Advance, Unofficial Release** and the MusicBrainz statuses other than Official:
  edition.
- **Mono, Stereo, Quadraphonic, Multichannel, Ambisonic**: channels. MusicBrainz has no
  channel field, so channels are null for MusicBrainz-only mediums.
- **Picture Disc, Shape, Etched, Coloured, Clear, Marbled, Splatter** and the Discogs free
  `text` field: appearance on the item; the text is kept verbatim in `source.text`.
- **Unknown values**: kept in `unmapped.formats` or `unmapped.descriptions`. A release whose
  only format is unknown has no items and an empty families list.
