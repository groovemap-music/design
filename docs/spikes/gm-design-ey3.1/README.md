# Measurement for gm-design-ey3.1: UPC-A and EAN-13 forms of one GTIN

This is throwaway code behind the measurement in
[ADR 0011's second 2026-09-25 amendment](../../adr/0011-catalog-identifiers-and-manufacturing-credits.md#2026-09-25-upc-a-and-ean-13-are-one-gtin-at-lookup-no-alias-is-re-keyed).
It is not a product package, and no GrooveMap service depends on it. It prints aggregate counts
only. No id, barcode, or other catalog value is committed, and the numbers live in the ADR.

| Input | How it is read |
| --- | --- |
| `discogs_20260901_releases.xml.gz` (19,417,067 releases) | Streamed through `gzip -dc` into `lxml.etree.iterparse` with `recover=False`. The run fails unless gzip exits 0 and the document closes with `</releases>`, so a truncated stream cannot parse silently. The cached copy's SHA-256 matches the published Discogs `CHECKSUM` |
| `mb_20260923-001002.jsonl.gz` from `~/.cache/groovemap-spikes/gm-design-1wd.1/data/` | The [gm-design-1wd.1](../gm-design-1wd.1/README.md) compact snapshot of the `20260923` MusicBrainz JSON dump. The run fails unless it holds exactly the 5,797,718 releases its stream log recorded |

Barcodes are normalized with ADR 0011's `digits_only` rule, which keeps ASCII digits only, as
the three mappers do. Python's `str.isdigit` would also keep characters such as `₇`, which
really do occur in Discogs barcode values.

```sh
W=~/.cache/groovemap-spikes
uv run --with lxml python measure_gtin_forms.py \
  $W/dumps/discogs_20260901_releases.xml.gz \
  $W/gm-design-1wd.1/data/mb_20260923-001002.jsonl.gz 5797718
```

The full Discogs pass takes about an hour on one core.
