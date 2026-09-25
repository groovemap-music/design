# Spike: Semantica for cross-catalog release-edition matching

Status: NO-GO for a Semantica component. Keep deterministic matching and make the
ownership decision below before any matcher is built.  
Evidence date: 2026-09-24  
Spike: `gm-design-zwy`  
Harness: [gm-design-zwy/](gm-design-zwy/README.md)  
Related: `gm-design-chw.3` (name embeddings), `gm-design-e0b.1` (non-Latin identity, running in parallel)

## Question

Can Semantica generate better candidates for matching Discogs and MusicBrainz catalog
identities than a simple deterministic baseline? The focus is release editions. The
improvement has to be large enough to justify a narrowly scoped GrooveMap dependency or
an adaptation of Semantica's rules.

Four things must all hold for a GO: a measured improvement over the baseline, an
acceptable manual-review load, verified compatibility and dependency cost, and an
ownership proposal consistent with ADRs 0005, 0009, 0011, and 0012. Semantica may only
propose candidates. It never asserts an identity, never calls `EntityMerger`, and never
touches `provider_aliases`.

## Method

### Upstream facts, re-verified on 2026-09-24

| Fact | Bead text (2026-09-21) | Verified | Source |
| --- | --- | --- | --- |
| Latest release | v0.6.8 | **v0.7.0**, published 2026-09-22 on both PyPI and GitHub. v0.6.8 is from 2026-09-05. | PyPI JSON API, GitHub releases API |
| License | not stated | MIT (`pyproject.toml` `license = { text = "MIT" }`, GitHub SPDX `MIT`) | GitHub, PyPI |
| Python support | `<3.14` | `>=3.10,<3.14` for 0.7.0. v0.6.8 declared `>=3.8`. | PyPI metadata for each version |
| Dedup API | `DuplicateDetector` / `SimilarityCalculator` | Matches the documented API. It was read from the installed 0.7.0 source (`semantica/deduplication/`, 4,634 lines) and pinned by `tests/test_semantica_api.py`. | context7 `/semantica-agi/semantica`, deduplication reference |

The spike pins **`semantica==0.7.0`** (the latest release) in a uv-managed **CPython
3.13.13** environment. It is locked by the harness `uv.lock` and lives at
`~/.cache/groovemap-spikes/gm-design-zwy/.venv`, outside the repository and outside every
service. No GrooveMap service acquired the dependency. No graph store, agent memory,
REST or MCP server, GraphRAG pipeline, LLM provider, or embedding model was installed or
started. Only `semantica.deduplication` was imported.

What the installed code actually does. This matters more than the docs:

- `SimilarityCalculator.calculate_similarity` combines three parts. The first is
  Jaro-Winkler on `name` only, after `lower().strip()`, weighted 0.6. The second is
  property similarity, weighted 0.2: a string property is scored by Jaro-Winkler, a
  property missing on either side scores a neutral 0.5, and unequal non-strings score
  0.5. The third is relationship Jaccard, weighted 0.2. When the name score is below
  0.3 and the name weight is above 0.5, the result short-circuits to the name part alone.
- `DuplicateDetector` turns a similarity into a *confidence*. It adds +0.1 for an exact
  name, +0.05 for each exactly equal property, and +0.05 for an equal `type`, then caps
  at 1.0. A `type` mismatch is excluded structurally. The defaults are similarity ≥ 0.7
  and confidence ≥ 0.6.
- `incremental_detect(new, existing)` compares every pair. `detect_duplicates` and
  `batch_calculate_similarity` block within one mixed list (`legacy` = first character
  of the name; `blocking_v2` = token prefixes, optionally plus Soundex). Blocking emits
  every within-block pair, including pairs from the same source.

### Matching unit and data model

The matching unit is **one MusicBrainz release → one Discogs release**. Every record,
on both sides, keeps `source`, native id, `entity_kind`, and its master or release-group
link (`matching.View`). Discogs masters are in the candidate pool as
`entity_kind='master'`, so a release-vs-master confusion can be measured instead of
assumed away. A score is a ranking signal. Nothing in the harness writes an alias or an
assertion.

### Ground truth: held-out MusicBrainz → Discogs release relations

This follows the construction used by chw.3 and e0b.1 and named in ADR 0013's "Shared
ground truth" follow-up, applied here to releases:

1. **MusicBrainz side.** The `json-dumps/20260923-001002/release.tar.xz` dump (22 GB) was
   streamed as `curl | xz -dc | tar -O` into `extract_mb_releases.py`, stopping after a
   **600,000-line dump-order prefix**. Nothing was written to disk except the compact
   linked records. Of those releases, 319,302 (53.2%) carry a Discogs relation, and every
   one of them points at a `/release/` URL. None points at a master. 2,743 releases link
   to more than one Discogs release. They have no single correct edition, so they were
   counted and excluded, leaving 316,559 eligible queries. 1,158 Discogs releases are the
   target of more than one MusicBrainz release.
2. **Sampling.** `sample_queries.py` draws a stratified sample proportional to the
   title's script bucket: latin 311,035, non-Latin 4,133, and unknown 1,391 in the
   population. It splits the sample by MBID hash into **test = 10,000** (9,820 latin,
   135 non-Latin, 45 unknown) and **dev = 2,000**. Because 135 is thin, a disjoint
   **extra non-Latin slice of 1,000** was drawn and scored separately.
3. **Discogs side.** The whole `discogs_20260901_releases.xml.gz` was streamed from
   `data.discogs.com` into `lxml.etree.iterparse`, never to disk: 19,417,067 releases in
   1,303 s. The pass kept every held-out target (12,958 of 12,998; the other 40 are
   absent from the dump), every release sharing a barcode, catalogue-number, or title key
   with any query, and a deterministic 1% background sample. That makes 1,129,406
   releases. Because every key-sharing release **in the full corpus** is kept, blocking
   coverage and review burden reflect the full 19.4M corpus, not a toy pool.
4. **Masters.** The masters dump in the shared cache (read-only) contributed 136,603
   masters: the master of every keyed release, plus title-key matches. The full pool is
   **1,266,009** records.

The label is the held-out relation. A matcher sees only the MusicBrainz side's title,
artist credit, barcode, labels and catalogue numbers, date, country, and media formats.
No user collection data was used anywhere.

**The test queries are not a random sample of the catalog, and this matters:**

- The dump-order prefix skews old and physical. Release years have p10/p50/p90 of
  1986/2000/2007, 74.5% are CD, 21.9% vinyl, 2.0% digital, and 96.1% are "Official".
- The pairs are ones people already linked, and MusicBrainz data is often entered from
  Discogs. Among queries whose target exists, the fields agree unusually often: barcode
  equal 5,513 of 6,018 (91.6%), catalogue-number key equal 8,643 of 9,346 (92.5%), title
  key equal 8,542 of 9,967 (85.7%), year equal 9,049 of 9,627 (94.0%), and country equal
  8,855 of 9,885 (89.6%). The unlinked population is the one a matcher would actually
  serve, and it will be harder. **Every absolute number below is an optimistic upper
  bound.** The comparison between methods is the finding.

### The deterministic baseline

The baseline uses GrooveMap normalization (`normalize.py`) and keyed blocking with an
additive rule score (`matching.py`):

- **Blocks.** Three keys, and a query takes the union of their blocks. **Barcode**:
  ADR 0011 digits only, plus a spike extension that widens a 12-digit UPC-A to EAN-13.
  **Catalogue number**: the ADR 0011 upper-case and whitespace-collapse rule, plus a
  spike extension that also drops punctuation and spaces. **(title key, artist key)**:
  NFKD fold, casefold, punctuation removed, and the Discogs ` (N)` disambiguator
  stripped. A key shared by more than 2,000 candidates is a stop-key. It fired on 4
  queries. Blocking is entity-kind aware, so a release query never blocks a master.
- **Score.** Barcode equal +8. Label and catalogue number equal +4, or catalogue number
  alone +2. Title key equal +3, or title token Jaccard ≥ 0.5 +1. Artist overlap +3.
  "Descriptors": year equal +1, format family equal +1, and country equal +1, where
  MusicBrainz ISO codes are mapped to Discogs names. The weights are hand-set to encode
  identifier strength and were not fitted to the test split. Ties break by id order,
  which is arbitrary.

The domain exclusions are deliberate and matter:

- **No matrix or runout.** MusicBrainz release JSON carries none, even though matrix
  evidence is the strongest pressing evidence ADR 0011 makes queryable.
- **No tracklists or durations.** They are a heavier signal and out of this spike's
  scope.
- **No Discogs `notes`.**

### Semantica configurations

Each Semantica entity carries: `name` = the release title, normalized with the same
folding the baseline uses; `properties` = artist, barcode, catalogue number, label,
year, format family, and country; `relationships` = the artist and label keys; and
`type` = the entity kind. `--raw` passes the unnormalized source strings instead, and
`--kind-blind` drops `type`.

| Run | What it measures |
| --- | --- |
| `semantica_rerank` | Semantica's scoring on the baseline's blocked candidates. Candidates are ranked by `DuplicateDetector` confidence, then similarity. Coverage equals the baseline's by construction, so this isolates **ranking**. |
| `semantica_native` | `DuplicateDetector.incremental_detect` per query over a bounded pool, with default thresholds: Semantica's own candidate set and ranking, as shipped. |
| `semantica_exhaustive` | `SimilarityCalculator` on every (query, pool) pair with no threshold: Semantica's ranking with its cut-off removed. |
| `semantica_blocking` | Semantica's own blocking strategies over queries plus pool: coverage and pair volume only. |

The pure-Python scan cannot run over 1.27M records. Native, exhaustive, and blocking
therefore run on the **first 1,000 test queries against a bounded pool of 22,154
records** (19,815 releases and 2,339 masters). That pool holds every record any
baseline rule blocks for those queries (kind-blind), their targets, and those records'
masters. It is denser in hard negatives than a random pool, and the cap of 20,000 left
no room for background records. The baseline and rerank run on the same bounded pool
too, for a like-for-like row.

Each configuration ran as its own process under `/usr/bin/time -l`, with BLAS and
OpenMP capped at 4 threads (Semantica is single-threaded here). The host is shared
10-core, 32 GB. Metrics come from `evaluate.py`. The committed `results/*.json` files
hold counts and rates only.

## Evidence

### Baseline vs Semantica

**Full keyed pool, 10,000 test queries.** 33 targets are absent from the dump, so no
method can exceed 99.67% coverage.

| | Coverage | R@1 | R@5 | R@10 | MRR | Candidates/query (mean / median / p95) | Match time, 10k queries | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| Baseline | 97.33% | **77.14%** | **95.34%** | **96.81%** | **0.8529** | 21.8 / 5 / 83 | 0.7 s + 5.1 s index | 3,453 MB* |
| Semantica rerank | 97.33% | 71.00% | 92.77% | 95.32% | 0.8064 | 21.8 / 5 / 83 | 14.5 s + 5.2 s index | 3,829 MB* |
| Semantica rerank, raw strings | 97.33% | 71.21% | 92.77% | 95.20% | 0.8078 | 21.8 / 5 / 83 | 9.8 s + 4.5 s index | 4,378 MB* |
| Delta, rerank − baseline | 0.00 | **−6.14 pt** | −2.57 pt | −1.49 pt | −0.0465 | | | |

\* The full-pool peak is dominated by holding 1.27M pool records in memory (about
2.9 GB after load). It measures the harness, not the matcher. The bounded runs below
isolate the matchers' own memory.

**Bounded pool (22,154 records), first 1,000 test queries.** 4 targets are absent, so
the ceiling is 99.6%.

| | Coverage | R@1 | R@5 | R@10 | MRR | Candidates/query (mean / median / p95) | Match time, 1k queries | Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| Baseline | 97.7% | **78.1%** | **96.3%** | **97.3%** | **0.8617** | 19.8 / 5 / 82 | 0.07 s | 94 MB |
| Semantica rerank | 97.7% | 71.2% | 93.6% | 95.9% | 0.8084 | 19.8 / 5 / 82 | 0.77 s | 121 MB |
| Semantica native (defaults) | 97.6% | 71.3% | 93.5% | 95.8% | 0.8085 | 15.0 / 4 / 64 | **967 s** | 116 MB |
| Semantica exhaustive (no threshold) | 99.6%† | 72.0% | 94.6% | 97.1% | 0.8173 | 19,815 (every release) | **933 s** | 138 MB |

† Exhaustive scores the whole pool, so its "coverage" is only the targets present in the
pool. That is not a candidate-generation result.

Both Semantica scan modes run at about **23,000 pairs/s** (0.93 to 0.97 s per query
against 22k records). The keyed pool has 1.27M records, which extrapolates to roughly
55 s per query, or about 6.4 core-days for 10,000 queries. That figure is an
extrapolation and was not measured. Matched against the full 19.4M corpus it would be
about 15× larger again. Semantica's own blocking is the alternative, measured on the
same 1,000 queries plus the bounded pool:

| Semantica blocking | Coverage | Total pairs | Cross-source pairs | Cross-source pairs per query |
| --- | ---: | ---: | ---: | ---: |
| `legacy` (first character) | 96.4% | 15,795,260 | 1,258,203 | 1,258 |
| `blocking_v2` | 98.7% | 16,339,815 | 1,010,091 | 1,010 |
| `blocking_v2` + Soundex | 98.7% | 35,764,192 | 2,266,434 | 2,266 |
| Baseline keyed blocking (same pool) | 97.7% | — | 19,800 | 19.8 |

`blocking_v2` finds 1.0 pt more targets than the baseline's keys on this pool, which is
the only coverage win in the spike. It gets there by scoring about 51× as many
cross-source pairs, and 94% of the pairs it generates are within-source pairs, mostly
Discogs to Discogs, that a cross-catalog matcher has no use for. At the measured rate, scoring those 16.3M pairs
takes about 710 s for 1,000 queries on a 22k pool. The pair count grows with the square
of the pool.

### Review burden

A threshold is usable, for this spike, if the mean review queue is **at most 3
candidates per query**. The threshold was chosen on the **dev** split and then applied
to test.

- Baseline: `score ≥ 10` gives a dev mean of 2.91.
- Semantica: **no confidence threshold reaches it.** Confidence saturates at the 1.0
  cap, so even `confidence ≥ 1.0` leaves a dev mean of 12.83.

Confusion and review table on test, 10,000 queries:

| Operating point | Queue mean / median / p95 | False positives/query | Queue precision | Top is correct | Correct in queue, not top | Only wrong candidates | Empty queue |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline `score ≥ 10` | 2.54 / 1 / 8 | 1.65 | 35.2% | 7,180 | 1,745 | 172 | 903 |
| Baseline `score ≥ 8` | 5.87 / 2 / 22 | 4.91 | 16.5% | 7,689 | 1,970 | 110 | 231 |
| Semantica rerank `conf ≥ 1.0` (strictest) | 11.49 / 3 / 46 | 10.53 | 8.3% | 7,001 | 2,571 | 119 | 309 |
| Semantica rerank `conf ≥ 0.7` (default) | 15.21 / 4 / 61 | 14.24 | 6.4% | 7,089 | 2,620 | 98 | 193 |
| Semantica native (default thresholds), bounded 1k | 14.43 / 4 / 64 | 13.45 | 6.8% | 713 | 263 | 8 | 16 |
| Semantica exhaustive `similarity ≥ 0.9`, bounded 1k | 5.36 / 1 / 19 | 4.67 | 13.0% | 528 | 168 | 46 | 258 |

**Ties.** Ties limit auto-acceptance for every method, and the tie behavior is itself
evidence. Under the baseline, the top score is tied on 2,363 of 10,000 queries, and on
1,359 of them the target is in the tie but lost the id-order tie-break. Counting only
queries where the target is the unique top, baseline recall@1 is 69.40%, and the target
is in the top-scoring group for 90.73% of queries. Semantica's confidence ties at the
top on **7,208 of 10,000** queries because of the 1.0 cap. Only the secondary similarity
separates those candidates.

### Hard negatives, by class

The method-independent census counts, for each query, the pool records around the
target that share its barcode, master, or title key. The per-method columns count a
class member ranked **above** the target, and a class member at rank 1. Test set, full
pool, 10,000 queries:

| Class | Queries with class in pool | Baseline: outranks target / rank 1 | Semantica rerank: outranks target / rank 1 |
| --- | ---: | --- | --- |
| Reused or shared barcode (another release with the target's barcode) | 2,438 | 983 / 955 | 1,026 / 848 |
| Same master, same format family (another pressing) | 6,324 | 1,991 / 1,968 | 2,423 / 2,280 |
| Same master, different format family | 5,181 | **94 / 56** | **606 / 297** |
| Near-identical title, different master | 4,375 | **38 / 21** | **132 / 61** |
| Release vs master (kind-aware runs) | 8,188 | 0 / 0 (blocked) | 0 / 0 (type gate) |
| Release vs master (kind-blind runs) | 8,188 | **41 / 7** | **232 / 156** |
| Namesake artist (same name, different Discogs artist id, in the neighbourhood) | 46 (thin) | 2 / 2 | 3 / 2 |

What the classes show:

- **Same-master pressings dominate, and that is the edition problem itself.** Neither
  method separates two pressings that share barcode, label, catalogue number, title, and
  artist. Only year, country, and format separate them, and often nothing does.
- **Semantica is much worse where fuzzy similarity rewards the wrong thing.**
  Different-format siblings reach rank 1 5.3× as often (297 vs 56), and different-master
  near-title releases 2.9× as often (61 vs 21). The cause is that it scores a different
  barcode or catalogue number by Jaro-Winkler rather than as a mismatch
  (`tests/test_semantica_api.py` pins this), and treats a missing field as a neutral 0.5.
- **Entity kind is load-bearing.** When the kind is withheld, Semantica ranks a Discogs
  master first on 156 queries against the baseline's 7. With `type` set, its structural
  type gate excludes masters completely, which is correct behavior worth keeping in any
  design.

The bounded 1k runs repeat the pattern (native: different-format siblings at rank 1 26
vs baseline 2, near-title 10 vs 1). So does the non-Latin slice (below).

### Slices

| Slice (test, full pool) | n | Baseline R@1 / R@10 | Semantica rerank R@1 / R@10 |
| --- | ---: | --- | --- |
| Barcode on query | 6,071 | 80.56% / 98.90% | 73.09% / 97.05% |
| No barcode on query | 3,929 | 71.85% / 93.59% | 67.78% / 92.64% |
| Catalogue number on query | 9,469 | 78.15% / 98.09% | 71.82% / 96.56% |
| No catalogue number on query | 531 | 59.13% / 74.01% | 56.31% / 73.26% |
| Extra non-Latin slice (separate 1,000) | 1,000 | 81.80% / 96.70% | 78.30% / 96.20% |
| Dev split | 2,000 | 76.70% / 97.00% | 70.85% / 95.75% |

The baseline misses 267 of 10,000 targets outright. 33 are absent from the dump. 210
share no identifier and differ in title key: translated titles, added subtitles, and
"Bande Originale Du Film …"-style titles. 20 differ in artist key only. 4 are lost to
stop-keys. Of the misses with a title-key mismatch, only 1 is a non-Latin title.

### Field ablation

A dropped field is removed from blocking and scoring (baseline) or from the entity
encoding (Semantica). The table shows R@1 / coverage, with the delta against the
full-field run in brackets.

| Dropped | Baseline, 10k | Semantica rerank, 10k | Semantica exhaustive, bounded 1k (R@1) |
| --- | --- | --- | --- |
| none | 77.14% / 97.33% | 71.00% / 97.33% | 72.0% |
| barcode | 73.48% (−3.66) / 96.43% (−0.90) | 68.28% (−2.72) | 69.6% (−2.4) |
| catalogue number and label | 70.25% (−6.89) / 91.07% (−6.26) | 66.94% (−4.06) | 72.2% (+0.2) |
| title | 72.72% (−4.42) / 90.83% (−6.50) | 72.36% (**+1.36**) | **0.0%** (name short-circuit) |
| artist | 77.07% (−0.07) / 97.50% (+0.17); candidates 21.8 → 73.2 per query | 71.62% (+0.62) | 72.6% (+0.6) |
| descriptors (year, format, country) | 69.91% (**−7.23**) / 97.33% | 64.93% (−6.07) | 66.2% (−5.8) |
| barcode + catalogue number | 54.64% (**−22.50**) / 82.83% (**−14.50**) | 54.24% | 65.1% (−6.9) |
| title + artist | 72.71% (−4.43) / 90.83% (−6.50) | 72.31% | 0.0% |

The ablation headline:

- **Identifiers carry candidate generation.** Without barcode and catalogue number,
  baseline coverage falls 14.5 pt and recall@1 falls 22.5 pt.
- **Descriptors are the only thing that separates pressings,** worth 5.8 to 7.2 pt of
  recall@1 in every method.
- **Semantica's fuzzy scoring actively hurts.** With the title removed, rerank ranking
  falls back to "count the exactly equal properties", and recall@1 *rises* to 72.36%
  from 71.00%. Removing catalogue numbers helps exhaustive slightly. In scan mode
  Semantica cannot work at all without a title, because the name short-circuit zeroes
  every score.

### Candidate-pair examples

These three illustrate the failure modes. Scores are shown without ids.

1. **Fuzzy identifiers outrank a shared barcode** (native, target at rank 4). The query
   and target share a barcode and year for a various-artists 2002 festival album. The
   target title is shorter ("Live From Bonnaroo 2002"). Semantica's rank 1 is a *video*
   release with the query's exact title and a different barcode that differs in its last
   six digits. Both reach confidence 1.0, and the video wins on similarity (0.83).
2. **An exact catalogue-number match is dropped by the threshold** (native, target not
   in the candidate set). The query is a 1973 Belgian soundtrack LP. The target shares
   its catalogue number exactly, but the Discogs title is the long bilingual
   "Bande Originale Du Film … = Mon Nom Est Personne". The name similarity sinks the
   target below 0.7. Semantica's top candidate is a different release with the short
   title and a catalogue number two characters away, scored by Jaro-Winkler as a near
   match. The baseline finds the target through the catalogue-number block.
3. **A master outranks its release** (kind-blind rerank). For a 2006 Italian CD album,
   the Discogs master (same title, artist, and year, with no identifiers, so its fields
   score neutral 0.5) ties the release at confidence 1.0 and wins on similarity. The baseline ranks
   it below the release, because the release also matches on catalogue number, format,
   and country.

### Compatibility and dependency cost

- **Python.** 0.7.0 declares `<3.14`, and GrooveMap services run 3.14. uv ignores
  requires-python upper bounds, so it installed 0.7.0 into a throwaway 3.14.5 venv. The
  dedup module imported there, and this harness's tests (including the Semantica API
  pins) passed. This is *not* supported upstream, and pip would refuse the install.
  Anything shipped would inherit the pin, or would have to be vendored.
- **Weight.** The installed environment has 49 distributions totalling **410 MB**
  (pyarrow 127 MB, scipy 70 MB, grpcio 41 MB, pandas 39 MB, scikit-learn 30 MB, numpy
  21 MB). The code actually used, `semantica.deduplication`, is 4,634 lines of pure
  Python importing only `math`, `dataclasses`, and `typing`. Importing it loads no
  numpy, pandas, scipy, scikit-learn, pyarrow, grpc, rdflib, networkx, or pydantic
  (checked via `sys.modules`: 139 modules, 25 MB RSS). Semantica core pulls in no torch
  or sentence-transformers. Those arrive only with the `models-huggingface` and
  `embeddings-local` extras, which were not installed.
- **Licenses.** `scripts/license_check.py` runs the inventory through catalog-api's own
  `check_dependency_licenses` policy, read-only (`results/licenses.json`). Semantica is
  MIT. No dependency is GPL or AGPL, and none carries non-OSI model terms. Two are MPL:
  `certifi` 2026.7.22 (MPL-2.0) and `tqdm` 4.70.1 (MPL-2.0 AND MIT). The policy passes
  on forbidden licenses, but anything shipped would need `THIRD_PARTY_NOTICES` entries
  for both. The rest is MIT, BSD, Apache-2.0, 0BSD, PSF-2.0, and MIT-CMU. A cross-check
  with `pip-licenses` 5.5.5 gave the same families.
- **Throughput.** Covered above: about 23k pairs/s, pure Python, single core. Without
  blocking it does not scale past bounded pools. With its own blocking, 94% of the pairs
  scored are wasted.

### Missing evidence and failure modes, stated plainly

- **No unlinked-population measurement.** Every pair was already linked, so field
  agreement is inflated (91.6% barcode equality where present). Real candidate
  generation for the 47% of this prefix with no Discogs link was not measured and cannot
  be scored without new labels.
- **Dump-order prefix bias.** 600,000 of MusicBrainz's releases, skewed pre-2008 and
  toward CD. Digital releases are 2% of queries.
- **The native and exhaustive Semantica numbers are 1,000 queries on a 22k bounded pool.**
  The 10k and full-pool figures for those modes are extrapolations and were not run.
  The rerank mode covers 10,000 queries.
- **Semantica was tested only in its deterministic modes.** The embedding component
  (`embedding_weight`, which needs a model), LLM-backed modules, and custom
  `MethodRegistry` strategies were not evaluated. chw.3 already measured name embeddings
  (+0.4 to +0.5 pt recall@10) in the same catalog. Semantica's weights were not tuned;
  its defaults were used. A weight search on dev could close part of the gap. It cannot
  remove the Jaro-Winkler-on-identifiers behavior or the confidence cap.
- **The baseline's weights are hand-set,** and its recall@1 leans on arbitrary tie
  order: it is 69.40% counting only unique tops.
- **No matrix or runout evidence.** MusicBrainz has none in its release JSON, so the
  signal ADR 0011 names as strongest for pressings was unavailable. Tracklists and
  durations were also not used.
- **Artist and label identity was not evaluated.** Edition ground truth was plentiful
  (316,559 eligible pairs), so no fallback was needed, and chw.3 and e0b.1 already cover
  artist and label names. Artist and label identity semantics differ from edition
  semantics: a namesake is a different entity, while a sibling pressing is the same work
  in a different edition. The two verdicts should not be combined.
- **The namesake-artist class is thin** (46 queries) and should not be read as a rate.
- **Timing ran on a shared host** (other resident workloads, with 5.8 GB of swap in
  use). Single-core CPU-bound rates are stable, but wall times carry that noise.

## Verdict

**NO-GO** for a Semantica component, whether as a pinned dependency in an isolated job
or as an adaptation of its scoring rules.

| GO requirement | Result | Met? |
| --- | --- | --- |
| Measured improvement over the baseline | Ranking is worse in every configuration and slice. On 10k: R@1 −6.14 pt, R@5 −2.57 pt, R@10 −1.49 pt, MRR −0.047. Coverage: equal in rerank; −0.1 pt (1 query) in native. `blocking_v2` finds +1.0 pt more targets at 51× the cross-source pairs. **Near misses, flagged:** exhaustive R@10 is 97.1% vs 97.3% (−0.2 pt, 2 of 1,000 queries), and non-Latin R@10 is 96.2% vs 96.7%. | No |
| Acceptable manual-review load | No confidence threshold gets below 11.49 candidates/query (target 3). The baseline reaches 2.54 at `score ≥ 10`. | No |
| Verified compatibility and dependency cost | MIT, no GPL or AGPL, 2 MPL notices needed. The declared `<3.14` conflicts with GrooveMap's 3.14; it runs there only unsupported. It brings 410 MB and 49 packages to use 4.6k lines of stdlib-only code. At 23k pairs/s it does not scale without blocking. | Partly (licenses yes, Python and cost no) |
| Ownership proposal | Proposed below for deterministic matching. There is nothing to own for Semantica. | n/a |

The three follow-ons compared:

- **(a) A pinned Semantica component in an isolated job.** Rejected. It ranks worse,
  gives no usable threshold, pins Python below the platform version, and brings 410 MB
  of dependencies for code it does not use.
- **(b) A native reimplementation of Semantica's rules.** Rejected. The rules that
  distinguish it from the baseline (Jaro-Winkler on identifiers, neutral 0.5 for missing
  fields, the capped additive confidence) are exactly what the evidence shows hurting.
  The one idea worth keeping is the structural entity-kind gate, which the baseline
  already has as kind-aware blocking.
- **(c) Deterministic matching only.** Recommended. Keyed blocking on ADR 0011
  identifiers plus title and artist, and a rule score with descriptors. It is the best
  method measured here on every axis, and it needs no dependency.

## Recommendation

1. **Decline the Semantica dependency.** Do not add it to any service, job, or shared
   library. Revisit only if upstream ships 3.14 support *and* a later release is shown to
   beat this harness's baseline. The harness can be re-run against a new pin in about an
   hour.
2. **The next decision is ownership and architecture, and it needs an ADR, not an
   implementation bead.** The question is where deterministic cross-catalog edition
   candidates are produced and where they wait for review. The constraints:
   - **ADR 0005.** Each producer owns its own source, so neither `discogs-ingestion` nor
     `musicbrainz-ingestion` should own a matcher that reads both.
   - **ADR 0009.** A heuristic's output is `source='inference'` and never auto-promotes
     to `source='catalog'`. Since 1,359 of 10,000 test queries have the correct edition
     tied with a wrong pressing, inferred edition candidates belong in a review queue, not
     directly in `provider_aliases`.
   - **ADR 0011.** Barcode and catalogue-number aliases already resolve through
     `provider_aliases`, and it explicitly defers what a matcher does with them.
   - **ADR 0012.** The property graph is where a candidate edge would be queryable.

   A reasonable default to put to that ADR is: an offline batch job in
   `analytics-engine` (it already owns offline features under ADR 0013's roadmap, and
   ADR 0013's amendment gives it a least-privilege read role on the catalog graph) that reads both sources'
   loaded releases and writes `source='inference'` candidates into its own schema. A
   human or deterministic promotion step in `catalog-api` then decides what, if
   anything, reaches `provider_aliases`. The ADR must also settle the domain rule the
   data here cannot: **what an edition match means when two Discogs pressings are
   indistinguishable on every field MusicBrainz carries.**
3. **Before any matcher is built, measure on the population it would serve.** Label a
   small sample of *unlinked* MusicBrainz releases by hand, or use relations added after
   this dump as a time-split holdout, and re-run this harness. Every number here is an
   upper bound from already-linked, often copied data.
4. **If deterministic matching proceeds, the evidence says where the value is:**
   identifiers for coverage, descriptors (year, format family, and country, with an
   explicit ISO-to-Discogs country map) for pressing separation, kind-aware blocking, a
   stop-key limit, and a review threshold near `score ≥ 10` (2.5 candidates per query on
   this sample). Recalibrate that threshold on unlinked data. Do not ship the UPC and
   compact catalogue-number extensions silently. They go beyond the ADR 0011 rules and
   would need an ADR amendment.
5. **Relationship to gm-design-chw.3 and gm-design-e0b.1.** Those spikes evaluate
   artist and label name retrieval. This one evaluates release editions. Read the
   verdicts separately. The shared ground-truth construction (held-out MusicBrainz →
   Discogs relations, stratified by script) transferred cleanly to releases.

No production data was touched, no alias was merged, no user collection data was used,
and no implementation bead was filed or dispatched.

## Sources

- Semantica: [GitHub](https://github.com/semantica-agi/semantica),
  [deduplication reference](https://github.com/semantica-agi/semantica/blob/main/docs/reference/deduplication.md),
  [PyPI](https://pypi.org/project/semantica/0.7.0/), [v0.7.0 release](https://github.com/semantica-agi/semantica/releases/tag/v0.7.0)
- MusicBrainz JSON dumps: [data.metabrainz.org json-dumps](https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/)
  (`20260923-001002`)
- Discogs data dumps: [data.discogs.com](https://data.discogs.com/) (`discogs_20260901_releases.xml.gz`,
  `discogs_20260901_masters.xml.gz`)
- ADRs: [0005](../adr/0005-source-owned-catalog-ingestion.md), [0009](../adr/0009-native-identity-and-provider-aliases.md),
  [0011](../adr/0011-catalog-identifiers-and-manufacturing-credits.md),
  [0012](../adr/0012-postgresql-property-graph-migration.md), [0013](../adr/0013-pgvector-catalog-embeddings.md)
- Prior spike: [gm-design-chw.3](gm-design-chw.3-identity-name-embeddings.md)
- Harness and aggregate results: [gm-design-zwy/](gm-design-zwy/README.md)
