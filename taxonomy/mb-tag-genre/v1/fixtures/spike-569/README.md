# spike-569 regression fixture

Recorded, not synthetic: these files replay the spike that ADR 0020 rests on, so a test can prove the ported generator reproduces the spike's cascade figures. They come from `spikes/tag-mapping` in `musicbrainz-graph-enricher` at commit `ee3efa8a764d180b73ea2dec85fa3d4af08d72d1` (bead `gm-musicbrainz-graph-enricher-569`). All inputs are public: MusicBrainz tag names (CC0) and Discogs genre and style names (CC0).

| File | Provenance |
| --- | --- |
| `discogs-genre-tree-spike.json` | The spike's masters-only tree (`data/discogs_tree_20261101.json` with the pair counts of `data/discogs_pairs_20261101.json`) in the v1 tree layout. Children keep the spike's order, because option order is part of every capture key. It is not a valid v1 tree and is used only here. |
| `vocabulary.json` | The 200 tags of the spike's labelled sample (`data/sample.json`, seed 569) with their uses. It is a sample, not a whole dump, so its `sha256` is null; the spike recorded the dump hash only as `7547e470…5dc63`. |
| `captures/*.jsonl` | The spike's Jev (`jev-1.14.0`) and Claude (`claude-opus-5-5`, effort medium) answers for the 157 tags the string match does not settle, re-keyed by node and stored sparsely (zero probabilities dropped). The cache keys are the spike's. |
| `labels.tsv` | The spike's answer key, drafted by `claude-opus-5-5` and reviewed row by row by the operator on 2026-11-10. Copied verbatim. |
| `sample.json` | The spike's sample with strata, copied verbatim, for the per-stratum estimates. |
| `spike-summary-cascade.json` | The `cascade` section of the spike's `results/summary.json`: the figures the test must reproduce. |
| `mb-tag-genre.json`, `review-queue.json` | Generator output from a replay of the files above. A test rebuilds them byte for byte with the network blocked. |

Regenerate the outputs (no network, no model calls):

```console
python3 -I scripts/mb-tag-genre.py propose \
  --vocab taxonomy/mb-tag-genre/v1/fixtures/spike-569/vocabulary.json \
  --tree taxonomy/mb-tag-genre/v1/fixtures/spike-569/discogs-genre-tree-spike.json \
  --captures taxonomy/mb-tag-genre/v1/fixtures/spike-569/captures \
  --out-lookup taxonomy/mb-tag-genre/v1/fixtures/spike-569/mb-tag-genre.json \
  --out-queue taxonomy/mb-tag-genre/v1/fixtures/spike-569/review-queue.json
```
