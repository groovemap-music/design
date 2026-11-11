# mb-tag-genre

The reviewed MusicBrainz tag to Discogs genre and style lookup decided in [ADR 0020](../../docs/adr/0020-mb-tag-genre-lookup.md). This directory holds the lookup's frozen target tree; the tag rows are separate work.

## Discogs genre tree (v1)

[`v1/discogs-genre-tree.json`](v1/discogs-genre-tree.json) is the genre to style tree that tags map onto. It is built from the **releases plus masters** of one named Discogs dump, and records that dump's date, the SHA-256 of each input file, and the rule. [`v1/discogs-genre-tree.schema.json`](v1/discogs-genre-tree.schema.json) validates it, and `just taxonomy` runs the schema, the structural checks in `scripts/genre-tree.mjs`, and a sample fixture ([`v1/fixtures/discogs-genre-tree-sample.json`](v1/fixtures/discogs-genre-tree-sample.json), synthetic).

**Rule.** A style's parents are the genres carried by at least 0.20 of the style's records, counted across masters and releases. The dominant parent is always kept, and junk genres (`1`) are dropped. This is the share rule `insights.style_parents` applies in analytics-engine. A style with several parents appears under each genre. Every genre has at most 255 children, the TypeSafe Choice limit, and a test asserts it.

**Counts.** Each child carries `records` (the style's records) and `genre_records` (records with both the genre and the style), so the share is `genre_records / records` and can be checked from the file.

### Regenerate

The generator is `scripts/discogs-genre-tree.py` (Python standard library only). It reads the two dump files as gzip streams, hashes the compressed bytes as they stream, and writes only the tree. It makes no network calls and no model calls itself; the inputs are paths, and a path may be a pipe. The releases dump is over 10 GB compressed, so do not save it. Stream it:

```console
python3 -I scripts/discogs-genre-tree.py --dump-date 20261101 \
  --masters <(curl -fsS 'https://data.discogs.com/?download=data%2F2026%2Fdiscogs_20261101_masters.xml.gz') \
  --releases <(curl -fsS 'https://data.discogs.com/?download=data%2F2026%2Fdiscogs_20261101_releases.xml.gz') \
  --out taxonomy/mb-tag-genre/v1/discogs-genre-tree.json
```

The same dump regenerates the same bytes: there are no timestamps, and every list is sorted. Compare each recorded `sha256` with the dump's `discogs_20261101_CHECKSUM.txt`. A different dump date is a new tree version (ADR 0020, *Versioning*).
