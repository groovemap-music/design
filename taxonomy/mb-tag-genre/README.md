# mb-tag-genre

The reviewed MusicBrainz tag to Discogs genre and style lookup decided in [ADR 0020](../../docs/adr/0020-mb-tag-genre-lookup.md). This directory holds the lookup's frozen target tree, the tag vocabulary it covers, the generator's schemas, the model proposals for the named dump with their recorded captures and review queue, and a recorded regression fixture.

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

## Tag vocabulary (v1)

[`v1/mb-tag-vocabulary.json`](v1/mb-tag-vocabulary.json) lists the MusicBrainz tags with **20 or more uses** in one named full export, and records the export, the SHA-256 of its `mbdump-derived.tar.bz2` (checked against the export's `SHA256SUMS`), and per-table counts. A *use* is one (entity, tag) row with a positive vote count in `artist_tag`, `label_tag`, `release_tag` or `release_group_tag`. [`v1/mb-tag-vocabulary.schema.json`](v1/mb-tag-vocabulary.schema.json) validates it. The dump is about 530 MB; stream it, and the script keeps only per-tag counts:

```console
D=20261111-002335; U=https://data.metabrainz.org/pub/musicbrainz/data/fullexport/$D
python3 -I scripts/mb-tag-genre.py vocab --dump-name $D \
  --dump <(curl -fsS "$U/mbdump-derived.tar.bz2") --sha256sums <(curl -fsS "$U/SHA256SUMS") \
  --out taxonomy/mb-tag-genre/v1/mb-tag-vocabulary.json
```

## Lookup and review queue (v1)

`scripts/mb-tag-genre.py propose` runs the ADR 0020 cascade over the vocabulary and the tree:

1. **String match.** A tag whose normalized name is a Discogs genre or style name is accepted without review (`bucket: string`, `review_state: not_required`).
2. **Two model proposals** for every other tag: Jev beam K=3 (`jev-1.14.0`) and flat Claude (`claude-opus-5-5`, effort medium). The prompts and option order are the spike's.
3. **Both NONE:** recorded unmapped with both proposals (`agree_none`, `not_required`).
4. **Same genre or style, or a disagreement:** `pending`, with Claude's answer as the default (Jev's when Claude gave no valid answer). These rows, most-used first, are the review queue.

The lookup is validated by [`v1/mb-tag-genre.schema.json`](v1/mb-tag-genre.schema.json) and the queue by [`v1/mb-tag-genre-review-queue.schema.json`](v1/mb-tag-genre-review-queue.schema.json). `scripts/mb-tag-genre.mjs` adds the rules a schema cannot hold, and `just taxonomy` runs both. The generator always writes `publishable: false`. In a file marked publishable, the validator rejects any model-proposed genre row that has no named reviewer, and any pending row. A rerun keeps a reviewed row as long as both proposals are unchanged.

**Captures.** Every model answer is stored in `<captures>/<model>.jsonl`, keyed on the model, the tag and a digest of the question's options. By default `propose` replays captures only: it blocks the network, never imports either SDK, and exits with status 3 on the first capture miss. Status 4 means a capture or a response reported a model other than the pinned one. Only `--live` makes paid calls; it needs `TYPESAFE_API_KEY` and Anthropic credentials, and is run by the operator.

```console
# Count the misses and estimate what --live would spend. No calls.
python3 -I scripts/mb-tag-genre.py estimate --vocab taxonomy/mb-tag-genre/v1/mb-tag-vocabulary.json \
  --tree taxonomy/mb-tag-genre/v1/discogs-genre-tree.json --captures taxonomy/mb-tag-genre/v1/captures

# The paid run (operator only). --limit 20 first gives a cheap smoke run that writes captures only.
uv run --no-project --with typesafe-sdk --with anthropic python -I scripts/mb-tag-genre.py propose --live \
  --vocab taxonomy/mb-tag-genre/v1/mb-tag-vocabulary.json --tree taxonomy/mb-tag-genre/v1/discogs-genre-tree.json \
  --captures taxonomy/mb-tag-genre/v1/captures \
  --out-lookup taxonomy/mb-tag-genre/v1/mb-tag-genre.json --out-queue taxonomy/mb-tag-genre/v1/review-queue.json

# Anyone, afterwards: rebuild both files from the committed captures with zero network calls.
python3 -I scripts/mb-tag-genre.py propose --vocab ... --tree ... --captures ... --out-lookup ... --out-queue ...
```

**Proposals (v1).** [`v1/mb-tag-genre.json`](v1/mb-tag-genre.json) and [`v1/review-queue.json`](v1/review-queue.json) cover the 9,899 tags of the vocabulary above (export `20261111-002335`) against the v1 tree (`20261101`). The operator ran `--live` on 2026-11-11: a 20-tag smoke run, then the full run, 4,654 s wall time at 4 workers. `v1/captures/` holds every answer: 28,243 Jev requests and 8,978 Claude requests, all reporting the pinned models. Outcome: 921 string matches, 4,563 both-NONE, 2,410 agreements and 2,005 disagreements, so the review queue holds **4,415** rows and nothing is reviewed yet (`publishable: false`). A test replays the captures with the network and both SDKs unavailable and checks both files byte for byte.

Measured cost, from the token counts in the captures at list prices read 2026-11-01 (Jev $0.042 per million input tokens, output free; Claude Opus 5.5 $4 input, $5 cache write, $0.20 cache read and $20 output per million tokens):

| Model | Requests | Tokens | Cost |
| --- | ---: | --- | ---: |
| `jev-1.14.0` | 28,243 | 41.94M input (18.50M output, not billed) | $1.76 |
| `claude-opus-5-5` | 8,978 | 18,244 cache write (once), 163.78M cache read, 0.20M input, 0.56M output | $44.89 |
| **Total** | 37,221 | | **$46.65** |

The `estimate` step had predicted $45.11. Claude wrote 62.6 output tokens per tag against the spike's 53, which adds $1.72; Jev came in $0.13 under. The captures are model output over public CC0 tag names. They hold no credentials, and their `at` and `latency_s` fields are the only run telemetry.

**Regression fixture.** [`v1/fixtures/spike-569/`](v1/fixtures/spike-569/README.md) replays the spike's recorded answers for its 200-tag labelled sample. `scripts/mb-tag-genre.test.mjs` checks that the replay reproduces the spike's cascade figures (43 string matches, 40 agreements at 97.5%, 80 both-NONE, 37 disagreements where Claude is right 86.5% of the time), and that a capture miss or a foreign model fails the run.
