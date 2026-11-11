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

## Drift check

The lookup goes stale as MusicBrainz tags and the Discogs tree change. `scripts/mb-tag-drift.mjs` compares the committed lookup with a newer vocabulary, a newer tree, or both. It reads local files only: no network, no model calls, and it never runs the generator. `just tag-drift` fills in the committed lookup and tree.

**When a new dump or tree is adopted**, build the newer inputs with the commands above (`vocab` for a MusicBrainz dump, `discogs-genre-tree.py` for a Discogs dump) into a scratch directory, not over `v1/`, then run:

```console
just tag-drift --new-vocab /tmp/drift/mb-tag-vocabulary.json --new-tree /tmp/drift/discogs-genre-tree.json \
  --out /tmp/drift/report.json --out-review /tmp/drift/review-work.json
```

Either `--new-vocab` or `--new-tree` alone works. The JSON report goes to `--out` (stdout without it) and a short summary to stderr. It lists:

- `new_tags`: tags at or above the lookup's `min_uses` that the lookup does not have, most-used first.
- `fell_below_scope` and `vanished`: lookup tags that the newer vocabulary lists under `min_uses` (only possible when it was built with a lower `--min-uses`), or does not list at all.
- `broken_paths`: every `result`, Jev or Claude path of a lookup row that the newer tree no longer has, with the genres a moved style now sits under (`candidates`). `tree_changes` (needs `--tree`, the old tree) lists genres and pairs added or removed.
- `use_changes`: a summary only (tags up, down, unchanged and the total delta).

**Exit status:** 0 when no path is broken (new, dropped and recounted tags are review work, not failure), 1 when any path is broken, 2 for bad usage or an unreadable or invalid input.

**Drift becomes review work.** `--out-review` writes `propose` (the new tags, with uses) and `reverify` (rows whose path broke, or reviewed rows whose tag left scope, with the candidate replacements). To act on it, run `propose` on the newer vocabulary and tree: it carries reviewed rows whose proposals are unchanged, replays committed captures and makes no call, and `estimate` counts the misses and prices a `--live` run (operator only). The new rows arrive as `pending` queue rows for the review loop below. Nothing in the drift check writes the lookup or the queue.

**CI.** `just check` runs on every pull request and every push to `main` (`.github/workflows/ci.yml`, no path filter). It runs the structural part through `just taxonomy` (`scripts/validate.mjs --taxonomy`): the lookup against its own tree, the schemas, and the review-state invariants. It also runs the drift script's tests (`just test`) on small synthetic fixtures. The dump-based part is the command above, run by hand when a dump is adopted, because dumps are too large for CI.

**Patch v1 or cut v2.** Patch v1 (a reviewed row corrected, a few new tags proposed and reviewed, `propose` rerun on the same tree) only while the tree and the vocabulary's dump stay the same. Cut `v2` when any of these holds:

- the drift check exits 1: a newer tree changed paths a row already names, and the tree is frozen from a named dump;
- the tree dump changes at all, even with no broken path, because the lookup records which tree it was reviewed against;
- the MusicBrainz dump changes and new tags exceed about 10% of the lookup's tags (`new_tags` over `counts.tags`), or `min_uses` changes;
- the model pins change.

A smaller tag-only change on the same tree and dump can stay in v1 as a patch. `v1` stays in place for consumers that pin it.

## Review loop (v1)

The operator reviews the 4,415 pending rows in a local page, [`review/index.html`](review/index.html), and a script merges the result into the lookup. Nothing here calls a network or a model. A model-proposed genre reaches the lookup only with a named reviewer.

1. **Open the page.** `just tag-review` serves it at `http://127.0.0.1:8765/index.html` (localhost only, Ctrl-C stops it). Opening `review/index.html` straight from disk (`file://`) works too. The page has no CDN, font or request of any kind (its Content-Security-Policy forbids them). It loads [`review/data.js`](review/data.js), which holds the queue, the Discogs tree and the lookup's SHA-256, and [`review/core.js`](review/core.js).
2. **Type your name** in the Reviewer box. It is recorded on every decision.
3. **Review one row at a time.** The page shows the tag, its uses, both proposals with full tree paths (Claude's answer is the default, Jev's when Claude gave none), Jev's top three paths, and progress: decided of 4,415 with counts by decision.

   | Key | Action |
   | --- | --- |
   | `Enter` or `a` | accept the default |
   | `o` | accept the other model's answer |
   | `n` | NONE, leave the tag unmapped |
   | `p` or `/` | pick another path: fuzzy search over every genre and style, `Up`/`Down`, `Enter` to pick, `Esc` to cancel |
   | `1` `2` `3` | pick one of Jev's top three |
   | `s` | skip; skipped rows come back after the open ones |
   | `u` / `Ctrl+Z`, `y` | undo, redo (every action, as many as you like) |
   | `[` `]` | previous or next row without deciding |
   | `e`, `i`, `?` | export, import, help |

4. **Progress is saved in the browser** (`localStorage`) after every action, so you can stop and resume. It is keyed on the queue version, the MusicBrainz dump and the tree date, which a merge does not change, and each decision is keyed by tag and bound to a hash of the row you were shown (bucket and both proposals). A cleared browser loses it, so press `e` now and then: the page counts the decisions not yet exported and turns the count amber at 200. The export is a JSON progress file; `i` imports one (a later decision for a tag wins), which also moves progress between browsers. The page refuses a file for another queue, dump or tree, and ignores rows whose hash no longer matches.
5. **Merge.** `just tag-review-merge ~/Downloads/mb-tag-genre-review-<dump>-<time>.json` runs `scripts/mb-tag-review.mjs merge`. For each exported row it writes `result`, `review_state: reviewed`, `reviewer`, `decision` and `reviewed_at`, then rewrites [`v1/mb-tag-genre.json`](v1/mb-tag-genre.json), [`v1/review-queue.json`](v1/review-queue.json) (the rows still pending) and `review/data.js`. The merge checks **each row**, not the file:
   - a row is applied when its tag is still pending and its row hash matches the lookup's,
   - a row for a tag already reviewed with the same result is a no-op, so merging the same export twice changes nothing,
   - a row for a tag already reviewed with a different result, a row whose hash differs (the proposals changed since you decided), a tag that is not a queue row, a repeated tag, a missing reviewer or timestamp, a pick that is not a genre or style path in the tree, or a decision whose result does not follow from it, is **rejected**. By default any rejected row fails the whole merge, lists every conflict and writes nothing. `just tag-review-merge <file> --skip-rejected` applies the other rows and prints the rejected ones,
   - an export for a different `queue_version`, MusicBrainz dump or tree date is always refused,
   - the merged files are validated with the same checks as `just taxonomy` before anything is written,
   - the result is deterministic: the same lookup and export give the same bytes, whatever the row order.
6. **Reload and commit.** Reload the page after a merge. Rows now in the lookup show as done and count as decided, your unmerged decisions are kept, and the counts stay out of 4,415. Commit the three regenerated files. Because decisions survive merges, you can export, keep reviewing, and merge that earlier export later: the later decisions are still in the page and still merge.

Partial review is valid. While `publishable` is `false`, the validator accepts pending rows and reviewed rows together, so the lookup stays committable after every session. The merge sets `publishable: true` only when the queue is empty and the lookup was built from a whole, checksummed dump. From then on `just taxonomy` rejects any model-proposed genre row that lacks a reviewer, and any pending row (`unreviewed model rows never ship`, ADR 0020).

`just tag-review-build` rebuilds `review/data.js` from the lookup, and a test fails when the committed file differs.

**Regression fixture.** [`v1/fixtures/spike-569/`](v1/fixtures/spike-569/README.md) replays the spike's recorded answers for its 200-tag labelled sample. `scripts/mb-tag-genre.test.mjs` checks that the replay reproduces the spike's cascade figures (43 string matches, 40 agreements at 97.5%, 80 both-NONE, 37 disagreements where Claude is right 86.5% of the time), and that a capture miss or a foreign model fails the run.
