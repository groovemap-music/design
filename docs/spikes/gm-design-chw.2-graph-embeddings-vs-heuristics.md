# Graph embeddings vs the heuristics-2026-09 baseline spike

Status: GO on the acceptance gate as written, recommending FastRP and not Node2Vec. Read
the caveats before acting on it.  
Evidence date: 2026-09-24  
Spike: `gm-design-chw.2`  
Epic: `gm-design-chw`  
Decision: `gm-design-chw.4`

## Question

The question is whether learned graph embeddings over the artist, release, label, and
credit graph retrieve similar artists better than the frozen heuristic weights behind
`GET /api/recommend/similar/artist/{id}`, and by enough to justify an embedding pipeline in
`analytics-engine` (ROADMAP model step 1). Those weights are `heuristics-2026-09` in
catalog-api `api/queries/recommend_queries.py`.

The acceptance gate is a proposal that the maintainer may lower. It reads: GO if the best
embedding or fused method improves recall@10 over the baseline by at least 10% relative,
with no media family regressing by more than 2 points.

## Method

### Data and sampling

- **Source.** The Discogs monthly releases dump `discogs_20260901_releases.xml.gz` (sha256
  `7dd4b9b6…9ac0`, 11 GB gzipped, 19,417,067 releases), downloaded once into the shared
  spike cache. It was stream-parsed with 5 lxml workers and never decompressed to disk.
  The pass took 876 s wall and 3,240 s CPU, and produced 1.8 GB of integer arrays (ids,
  dates, media-family bits, and genre and style vocab ids). Titles, names, and notes never
  left the parser.
- **Graph edges.** Release to main artist (the `BY` edge), release to label, release to
  genre and style, and release to master. Release to credited artist is also included,
  keeping the `production`, `engineering`, `session`, and `other` categories of
  `common.credit_roles`. Mastering, design, and management credits link releases by
  vendor, not by sound, so they are dropped. Track artists are included as well. The
  placeholder artists Various, Unknown Artist, No Artist, and Traditional are removed.
- **Media families.** Media families come from `common.media.map_discogs_formats` in
  groovemap-runtime `6e84fe9a`, the same vocabulary the harness resolves.
- **Sampling.** Seeds are artist-seeded ego networks. The eligible artists are those with
  at least `MIN_ARTIST_RELEASES` = 3 pre-cut main-artist releases (769,668 artists). A
  fixed splitmix64 hash of the Discogs artist id selects 10% of them: 77,538 seed artists.
  The subset holds every pre- and post-cut release on which a seed is a main artist, so
  each seed has its full profile and its full post-cut neighborhood. Selection reads only
  pre-cut data. The result is 1,417,486 releases: 1,348,067 pre-cut, which is 9.7% of all
  pre-cut releases, and 69,419 post-cut. They reference 1,092,879 artists and 157,845
  labels. The training graph has 2,850,614 nodes and 15,069,600 undirected edges.
- **Rejected alternatives.** A 1-hop expansion that also pulled in neighbors' pre-cut
  discographies grew the subset to 6.7M releases, even at a 5% seed rate. Prolific
  credited engineers and session players drive that growth, and it would not fit the RAM
  budget. A 5% sample was run as a pipeline check, but it left only 3,044 queries.

### Time split

The cut is catalog-api `SPLIT_CUT` = 2023-01-01, enforced by building the graph and not
by filtering results:

| Bucket | Rule | Releases |
| --- | --- | ---: |
| Pre-cut (trains every method) | release date before 2023-01-01 **and** release id below 25,802,761 | 13,845,524 |
| Post-cut (ground truth only) | release date on or after 2023-01-01 | 994,823 |
| Dropped, no usable date | no year from 1860 to 2026 | 2,584,617 |
| Dropped, catalogued after the cut | old date, but release id at or above 25,802,761 | 1,992,103 |

The id condition approximates the catalog as it stood on the cut date. A 1975 pressing
catalogued in 2024 is not something a 2023 model could have seen. The threshold is the 5th
percentile of ids among releases dated 2023-01-16 to 2023-01-31, so it errs toward
excluding late-catalogued releases.

### Ground truth

The harness scores "collector, then later acquisitions". A Discogs dump carries no
collections, so the same protocol was moved to "artist, then the artists they work with
after the cut". This is a proxy. It was fixed before any method was scored:

- **relevant(A).** Every artist B other than A who appears on a post-cut release where A
  is a main artist, as a co-main artist, a kept-role credit, or a track artist. B must also
  be retrievable, meaning B has a pre-cut main-artist release in the subset. That makes B an
  `Artist` node the endpoint could return: 220,699 artists. 37,839 of the 154,365 post-cut
  pairs are retrievable. The rest are artists with no pre-cut main release, such as new
  artists or credit-only producers and players.
- **novel(A).** relevant(A) minus everyone A already shared a pre-cut release with. Every
  ranking is filtered of those pre-cut neighbors before it is cut at k. This view measures
  discovery instead of re-finding past collaborators.
- **Queries.** Seeds with a non-empty relevant set: 6,730 artists, with a median of 2
  relevant artists and a mean of 5.6. A fixed hash splits them 30/70 into **dev** (2,009)
  and **test** (4,721). Every hyperparameter, every fusion weight, and the choice of
  "best method" were made on dev. Every number reported below is from test. 2,939 test
  queries have a non-empty novel set.

### Methods

- **heuristics-2026-09, production path.** A port of catalog-api
  `GoldenGraph.candidate_artists` plus `compute_similar_artists`. It expands the query's top
  5 genres, keeps the 500 artists per genre with the most releases, keeps candidates that
  share at least 3 releases, takes the top 200, profiles 50, ranks by weighted cosine, and
  returns 20. On the committed 120-release golden set, the port reproduces catalog-api's own
  output exactly for all 36 artists, in ids, order, and similarity
  (`results/golden_check.json`, catalog-api `15f70c71`). The harness adapter also skips
  Cypher's 100,000-release per-genre scan cap. That favors the baseline.
- **Same weights over all artists (reference).** The identical 0.35/0.25/0.25/0.15 weighted
  cosine, scored against every retrievable artist with no candidate generator. It is not
  the served baseline. It separates what the weights can do from what the candidate
  generator throws away.
- **FastRP (local, about 40 lines of numpy and scipy).** A very sparse random projection,
  s = 3, of powers of D⁻¹A, row-normalized per power and summed. The grid was 64 and 128
  dimensions; iteration weights `0,1,1,1`, `0,0,1,1`, and `0,1,1,1,1`; degree
  normalization β of 0 and −0.5; and ablations without genre nodes and without credit or
  track edges.
- **Node2Vec (PyTorch Geometric 2.8, SparseAdam, lr 0.01, walk 20, context 10, 10 walks
  per node, 1 negative).** Runs were 128 dimensions with p = q = 1 on the full graph; 128
  dimensions without genre and style hub nodes at p = q = 1 and at p = 1, q = 0.5; 64
  dimensions without hubs; and a 2-epoch 128-dimension run without hubs. pyg-lib's walker
  only samples uniformly, so the q = 0.5 run swaps in `torch_cluster.random_walk`.
- **Fusion.** α · cosine(embedding) + (1 − α) · heuristic weighted cosine, over all
  retrievable artists. α ∈ {0.1, …, 0.9} is chosen per embedding on dev recall@10.
- **Scoring.** Exact cosine kNN by brute force over all 220,699 retrievable artists, with
  no ANN. Ties go to the lower Discogs id.

Metrics are the catalog-api primitives: `precision_at_k`, `recall_at_k`, `hits_at_k`,
`catalogue_coverage`, and `spearman`, copied read-only into `baseline_port.py`. They are
macro-averaged over queries at k = 10 and 20. The endpoint returns at most 20 results, so
the harness's k = 25 cannot be used. The per-family breakdown assigns each query artist to
its dominant media family over its pre-cut releases. The harness code is in
[the spike harness](gm-design-chw.2/README.md), and the aggregate outputs are in
`gm-design-chw.2/results/`.

### Environment and limits

Python 3.14.5 had wheels for everything except torch-cluster 1.6.3, which has no macOS
wheel and was built from source against torch 2.14. The host is an Apple Silicon machine
with 10 cores and 32 GB of RAM, shared with the concurrent pgvector footprint benchmark.
Every process capped itself at 6 threads (`OMP_NUM_THREADS`, `torch.set_num_threads`). Two
Node2Vec runs in parallel reached about 14 GB combined, so the second was stopped each
time and the runs were serialized to stay under the 12 GB peak. The cache footprint was 11
GB for the dump, 1.8 GB for the parse, 0.1 GB for the subset, 7.6 GB for embeddings, and
0.8 GB for the virtualenv. The peak was about 21 GB with the shared dump counted, 1 GB
over the 20 GB budget, and 10.3 GB without it. Everything except the shared dump was
deleted afterward.

## Evidence

### Headline metrics (test, 4,721 queries)

| Method | P@10 | R@10 | P@20 | R@20 | Hit@20 | Coverage | Novel R@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **heuristics-2026-09 (production path)** | 0.0094 | **0.0092** | 0.0069 | 0.0117 | 0.0640 | 0.0023 | 0.0079 |
| Same weights, all artists | 0.0566 | 0.1799 | 0.0359 | 0.2066 | 0.3963 | 0.2627 | **0.0311** |
| FastRP 128, weights 0,1,1,1,1 | 0.1069 | 0.3135 | 0.0662 | 0.3458 | 0.5757 | 0.2842 | 0.0099 |
| **Fused FastRP 128 (0,1,1,1,1), α = 0.9 (best on dev)** | 0.1078 | **0.3173** | 0.0666 | 0.3496 | 0.5791 | 0.2811 | 0.0134 |
| FastRP 128, weights 0,1,1,1 | 0.1034 | 0.3050 | 0.0637 | 0.3354 | 0.5624 | 0.2508 | 0.0141 |
| FastRP 128, weights 0,0,1,1 | 0.1055 | 0.3110 | 0.0642 | 0.3367 | 0.5662 | 0.2709 | 0.0096 |
| FastRP 128, β = −0.5 | 0.0868 | 0.2665 | 0.0490 | 0.2819 | 0.4921 | 0.3440 | 0.0023 |
| FastRP 128, no genre nodes | 0.1027 | 0.3069 | 0.0629 | 0.3384 | 0.5624 | 0.2966 | 0.0127 |
| FastRP 128, no credit or track edges | 0.0670 | 0.2061 | 0.0403 | 0.2243 | 0.4317 | 0.2511 | 0.0105 |
| FastRP 64, weights 0,1,1,1,1 | 0.0909 | 0.2693 | 0.0544 | 0.2904 | 0.5052 | 0.2968 | 0.0057 |
| FastRP 64, weights 0,1,1,1 | 0.0888 | 0.2647 | 0.0535 | 0.2890 | 0.5077 | 0.2663 | 0.0059 |
| Node2Vec 128, with genre and style hubs | 0.0186 | 0.0345 | 0.0139 | 0.0449 | 0.1457 | 0.1618 | 0.0049 |
| Node2Vec 128, no hubs, p = q = 1 | 0.0436 | 0.1050 | 0.0303 | 0.1339 | 0.2993 | 0.2222 | 0.0129 |
| Node2Vec 128, no hubs, q = 0.5 | 0.0436 | 0.1038 | 0.0299 | 0.1323 | 0.3014 | 0.2222 | 0.0107 |
| Node2Vec 128, no hubs, 2 epochs | 0.0651 | 0.1914 | 0.0441 | 0.2349 | 0.4397 | 0.1982 | 0.0233 |
| Node2Vec 64, no hubs | 0.0580 | 0.1586 | 0.0383 | 0.1946 | 0.3895 | 0.2359 | 0.0142 |
| Fused Node2Vec 128, 2 epochs, α = 0.7 | 0.0783 | 0.2446 | 0.0518 | 0.2934 | 0.5209 | 0.1964 | **0.0368** |
| Fused Node2Vec 128, q = 0.5, α = 0.4 | 0.0718 | 0.2176 | 0.0460 | 0.2544 | 0.4762 | 0.2182 | 0.0355 |

Coverage is the share of the 220,699 retrievable artists that appear in at least one test
query's top 20. Every fused variant, with its dev-selected α, is in `results/eval.json`.

### Gate check

The best method was selected on dev recall@10: fused FastRP 128 with weights `0,1,1,1,1`
and α = 0.9, at 0.3231 on dev. The confidence intervals below come from a paired 1,000-draw
bootstrap over test queries.

| Criterion (proposed threshold) | Measured against heuristics-2026-09 | Result |
| --- | --- | --- |
| Relative recall@10 gain ≥ +10% | 0.0092 → 0.3173: **+3,362%** (95% CI +2,753% to +4,196%) | Met by a wide margin |
| No media family regresses > 2 points | Worst family delta is **+0.0 points** (video, n = 1, both 0). Every other family gains 26.9 to 50.0 points. | Met |

The same check against the stronger all-artist reference, which is not the gate's
baseline, gives +76.4% relative (95% CI +69.4% to +83.6%). The worst family delta there is
+0.0 points (video, n = 1). The smallest real gain is shellac at +1.1 points, on only 9
queries.

Per-family recall@10 on test, by the query artist's dominant family:

| Family | Queries | Production heuristic | Same weights, all artists | Fused FastRP (best) | FastRP 128 | Node2Vec 2 epochs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| vinyl | 1,545 | 0.0086 | 0.1722 | 0.3435 | 0.3411 | 0.2159 |
| optical | 1,781 | 0.0141 | 0.1420 | 0.2829 | 0.2808 | 0.1886 |
| digital | 1,223 | 0.0031 | 0.2372 | 0.3308 | 0.3226 | 0.1648 |
| tape | 158 | 0.0074 | 0.2290 | 0.3383 | 0.3363 | 0.1894 |
| shellac | 9 | 0.0000 | 0.3435 | 0.3545 | 0.3545 | 0.1963 |
| grooved_other | 4 | 0.0000 | 0.2500 | 0.5000 | 0.5000 | 0.2500 |
| video | 1 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

Shellac, grooved_other, and video hold 14 queries between them, and their numbers are
noise. Tape, at 158 queries, is the smallest family that can be read. Node2Vec's 2-epoch
run *does* regress on digital against the all-artist reference, by −7.2 points. It is not
the selected method, but it would fail the family rule against that reference.

Where the recommendations land: the production heuristic sends 60.9% of its slots to
vinyl-dominant artists, against 32.7% of the queries. Its candidate pool is the most
prolific artists per genre. Fused FastRP sends 35.3% to vinyl, 33.0% to optical, 25.0% to
digital, and 4.9% to tape, which is close to the query mix.

### The novel-collaborator view: flagged

Most of the embedding gain comes from ranking an artist's *past* collaborators highly and
seeing them recur. On pairs with no pre-cut link (2,939 test queries):

| Method | Novel R@10 | vs production heuristic | vs same weights, all artists |
| --- | ---: | --- | --- |
| Production heuristic | 0.0079 | — | — |
| Same weights, all artists | 0.0311 | +293% (CI +187% to +463%) | — |
| Fused FastRP (gate winner) | 0.0134 | +69% (CI +18% to +147%) | **−57% (CI −68% to −45%)** |
| FastRP 128 alone | 0.0099 | +24% (CI −15% to +85%) | −68% |
| Fused Node2Vec, 2 epochs | 0.0368 | +364% | +18% (CI −0% to +39%) |

The gate winner still clears +10% against the production path on this view. It loses
clearly to the same weights scored over every artist. Only fused Node2Vec improves
discovery at all, and its lower CI bound touches zero. On this proxy, none of the methods
discovers new collaborators well: the best novel recall@10 is under 4%.

### Stability

The harness rule is "a model that does not reproduce its own ranking cannot be compared".

| Method | Second run | Top-10 Jaccard | Spearman over the whole catalog (300 queries) | R@10, seed 0 / seed 1 |
| --- | --- | ---: | ---: | --- |
| heuristics-2026-09 | identical rerun, 500 queries | identical lists | identical lists | — |
| FastRP 128 (0,1,1,1,1) | new projection seed | 0.281 | 0.351 | 0.3135 / 0.3151 |
| FastRP 128 (0,1,1,1) | new projection seed | 0.257 | 0.515 | 0.3050 / 0.3025 |
| Node2Vec 128, no hubs | new training seed | 0.097 | 0.484 | 0.1050 / 0.1060 |

FastRP is deterministic for a fixed seed. Node2Vec's fixed-seed determinism was not
verified beyond identical loss traces. Recall is stable across seeds, within 0.003. The
top-10 lists are not: a new FastRP projection replaces about 72% of an artist's top 10,
and a new Node2Vec seed replaces about 90%. The measured quality survives a reseed, but
the user-visible lists would churn at every retrain unless the projection is pinned. See
the recommendation below.

### Cost on this host (6 threads, 10-core Apple Silicon, 32 GB)

| Method | Train wall | Train CPU | Peak RSS |
| --- | ---: | ---: | ---: |
| FastRP 128 (0,1,1,1,1) | 16 s | 16 s | 6.6 GB |
| FastRP 64 | 8 to 11 s | 8 to 11 s | 4.3 GB |
| Node2Vec 128, 1 epoch, full graph | 3,399 s | 6,218 s | 7.4 GB |
| Node2Vec 128, 1 epoch, no hubs (3 threads) | 2,568 to 2,719 s | 4,643 to 4,701 s | 7.5 to 9.5 GB |
| Node2Vec 128, 2 epochs, no hubs | 4,397 s | 10,378 s | 8.7 GB |
| Node2Vec 64, 1 epoch, no hubs (3 threads) | 1,719 s | 2,819 s | 5.9 GB |
| Evaluation (15 embeddings, all fusions) | 639 s | — | 5.9 GB |

Node2Vec averages about 1.8 cores even with 6 threads, because walk sampling and the
Python training loop serialize it.

**Full-catalog extrapolation (estimated, not run).** The whole dump is 32.8M nodes and at
most 222M edges, 11.5× the nodes and 14.7× the edges of this subset.

- **FastRP.** Cost is linear in edges × dimensions: about 4 minutes of compute at 128
  dimensions. The in-RAM form needs 3 × N × 128 × 4 B ≈ 50 GB, so it must run
  column-blocked. Dimensions are independent apart from the per-power row norms, which a
  two-pass scheme handles. At 16 columns per block that is about 10 GB and roughly 10
  minutes.
- **Node2Vec.** About 10 hours per epoch, or 20 hours for the 2 epochs it needs. Parameters
  plus SparseAdam state alone come to about 50 GB at 128 dimensions. It does not fit a
  32 GB homelab host without sharding or dropping to about 64 dimensions and a smaller
  graph.

### Refreshing after a monthly dump load

- **FastRP** has no training state. It is a fixed linear operator applied to the new
  graph, so a monthly refresh is a full recompute in minutes, not an incremental update.
  Pin the projection by deriving each node's row of R from a hash of its provider id, not
  from a global RNG stream. Then an artist whose neighborhood did not change keeps
  (numerically) the same vector across dumps, and top-k churn is limited to artists whose
  graph actually changed. The subset measurements used a global RNG, so pinned-projection
  churn is **not** measured here. Store vectors with a `model_versions` row per dump, and
  let spike 1 (`gm-design-chw.1`) cost the index rebuild.
- **Node2Vec** needs a full retrain per dump. Warm-starting from the previous vectors is
  possible but unvalidated. Retrains rotate the space, and about 90% of top-10 lists change
  across seeds, so every monthly refresh would reshuffle the similar-artist lists as well
  as costing the time and RAM above.

### Licenses

Recorded with `license_check.py` and checked by catalog-api's own
`scripts/check_dependency_licenses.py` (`results/licenses.json`). No GPL or AGPL package
appears in the harness environment.

| Library | Version | License | Needed for the recommendation? |
| --- | --- | --- | --- |
| numpy | 2.5.3 | BSD-3-Clause (plus 0BSD, MIT, Zlib, CC0 parts) | Yes (FastRP) |
| scipy | 1.18.1 | BSD | Yes (FastRP) |
| torch | 2.14.0 | Apache-2.0 AND BSD-2/3-Clause AND BSL-1.0 AND MIT (compound, all permissive) | No (Node2Vec only) |
| torch-geometric | 2.8.0.post1 | MIT | No |
| pyg-lib | 0.9.0+pt214 | MIT | No |
| torch-cluster | 1.6.3 | MIT | No |
| lxml | 6.1.3 | BSD-3-Clause | Harness only |
| groovemap-runtime | 0.1.0 | MIT (first party) | Harness only |

Three transitive packages are MPL-2.0: certifi, orjson, and tqdm. The policy allows MPL but
requires a `THIRD_PARTY_NOTICES.md` entry. catalog-api already ships orjson. No model
weights are involved: FastRP is deterministic code, and Node2Vec trains from scratch.

## Verdict

**GO**, on the gate as written. The dev-selected best method, fused FastRP 128 at
α = 0.9, raises recall@10 over heuristics-2026-09 from 0.0092 to 0.3173. That is +3,362%
against a +10% threshold. No media family regresses (worst delta +0.0 points against a
−2 point limit). There is no near-miss on either criterion.

The margin is not what it appears, and three qualifications carry into the decision:

1. **Most of the gap is the baseline's candidate generator, not its weights.** The same
   weights scored over every artist reach 0.1799. Against that, fused FastRP is +76% (CI
   +69% to +84%). That is still well over the gate, with no family regression.
2. **The gain is recurrence, not discovery.** On novel collaborators the gate winner
   (0.0134) is 57% *worse* than the all-artist heuristic (0.0311). Nothing tested exceeds
   0.037.
3. **The ground truth is a proxy.** "Later collaborators" stands in for "items a collector
   later wanted", which the dump cannot provide. This is the harness's time-split protocol
   on a different relation, not the harness's task.

Node2Vec is **NO-GO** as the method. Its best test recall@10 is 0.1914 (2 epochs, no hubs),
below the all-artist heuristic on digital and tape. It costs 73 minutes and 8.7 GB
on a 2.85M-node subset, and it cannot train the full catalog in 32 GB.

## Recommendation

1. **Fix the production candidate generator regardless of the ADR.** Keeping only the 500
   most prolific artists per genre costs the served endpoint most of its recall:
   0.0092 against 0.1799 for the same weights. Scoring every artist is one sparse matrix
   product over the facet vectors, which the harness ran across 220,699 artists, and it
   can be precomputed offline. This needs no embedding pipeline and deserves its own bead.
2. **Use FastRP if the embedding pipeline goes ahead, not Node2Vec or PyG.** FastRP is
   about 40 lines of numpy and scipy (BSD), deterministic, recomputed monthly in minutes,
   and needs no GPU, torch, or model weights. Start with 128 dimensions, iteration weights
   `0,1,1,1,1`, β = 0, and credit and track edges included. Removing them costs 10 points of
   recall@10. Fuse with the heuristic at α ≈ 0.9 only if the stronger novel number
   matters. The fused gain on the headline metric is small, at +0.4 points.
3. **Before product use, pin and measure churn.** Derive projection rows from node-id
   hashes, then measure month-over-month top-10 Jaccard across two real dumps. Across
   random seeds it is 0.28 today. Raising dimensions or averaging projections are the
   levers if churn stays high.
4. **Do not claim discovery.** If "similar" is meant to surface artists a listener does
   not already associate, this spike does not show that embeddings help. Measure it on
   first-party co-collection events (ADR 0010) once they exist, before investing past
   FastRP.
5. **For the vector-search decision (`gm-design-chw.4`)**, the retrieval unit is about
   9.4M artist vectors at full scale, of which only those with a main-artist release are
   servable. At 128 dimensions that is about 4.8 GB as `vector` and 2.4 GB as `halfvec`.
   Exact kNN was used here, so ANN recall loss is not in these numbers.
