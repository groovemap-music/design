# Spike: name-embedding candidate recall for MusicBrainz-Discogs identity

- Bead: gm-design-chw.3 (child of epic gm-design-chw, "Spike vector search in PostgreSQL 19 with pgvector")
- Related: gm-design-zwy ("Evaluate Semantica for cross-catalog identity matching") — still OPEN/unclaimed as of
  this run, so there was no labelled-pairs set or deterministic baseline to reuse yet (see Recommendation).

## Question

Does multilingual name-embedding retrieval, alone or fused with `pg_trgm`, surface the correct Discogs entity
for a MusicBrainz entity more often than `pg_trgm` alone — enough to justify an embedding-based candidate
generator writing `source='inference'` rows to `provider_aliases` (ADR 0009)?

## Method

### Ground truth

Today linking is exact-ID only via MusicBrainz URL relationships
(`musicbrainz-ingestion/src/musicbrainz/jsonl_parser.rs`); unlinked MusicBrainz entities never reach the
graph. Those existing MusicBrainz → Discogs URL relations are free, real-world ground truth: hold out the
link and ask each retrieval method to find the Discogs entity from the MusicBrainz name alone.

1. Streamed the MusicBrainz JSON dumps (`json-dumps/20260923-001002/{artist,label}.tar.xz`, PG19-generation
   snapshot) directly from `curl` into `tar -xJf - -O mbdump/<kind>` — the decompressed dump is never written
   to disk, only piped line-by-line into a filter that keeps entities carrying a `relations[].type == "discogs"`
   URL and records `(mbid, name, sort-name, aliases, country, discogs_id)`.
2. Streamed the Discogs 2026-09-01 XML dumps (`data.discogs.com/?download=data/2026/discogs_20260901_{artists,labels}.xml.gz`;
   the S3 mirror in the original bead notes 403s, `data.discogs.com` does not) into `gunzip -c` and an
   `lxml.etree.iterparse` filter that keeps only records whose numeric id is in the MusicBrainz-side target
   set, clearing each element as it's read so memory stays bounded regardless of corpus size.
3. Joined the two sides on the Discogs id.

| | MB scanned | MB w/ Discogs relation | Discogs scanned | Discogs targets found |
|---|---:|---:|---:|---:|
| artist | 2,992,523 | 1,271,176 (42.5%) | 10,203,002 | 1,258,175 (99.0% of targets) |
| label | 350,637 | 164,278 (46.9%) | 2,729,516 | 162,911 (99.2% of targets) |

The ~1% of targets not found are almost certainly Discogs merges/deletions/renumbering since whatever
snapshot originally fed the MusicBrainz relation.

### Scoping the candidate pool (resource-budget decision)

The full Discogs corpus (~10M artists, ~2.7M labels) is out of budget to embed under the constraints below.
Instead, per kind, the candidate pool is capped at **20,000** entries: the correct Discogs target for every
sampled query, plus random distractors drawn from the rest of the matched MusicBrainz-linked population
(itself already hundreds of thousands of real, previously-linked names, not synthetic). The query set is a
**5,000**-query sample, stratified by script (see below) proportional to the full linked population.

This is an explicit limitation, not a hidden one: recall measured against a 20,000-row pool of real but
already-linked names is an **optimistic upper bound** relative to what a production candidate generator
would see against the full ~10M/2.7M corpus, where far more near-duplicate distractors exist. A production
rollout would need blocking (e.g. phonetic key, first-letter, country) or an ANN index to make full-corpus
retrieval affordable — deliberately out of scope here, since the design calls for exact search so recall
reflects the method, not index approximation.

Both the 20,000-candidate cap and the 5,000-query sample are well inside the "50k–200k linked entities" scale
suggested for this spike; the reduction from the full 1.27M/163k matched population to 20k/5k was made to fit
the embedding-throughput budget below in the time available, and is called out per the "flag near-misses,
don't round them away" instruction where it affects slice sample sizes (the non-Latin slices in particular
are thin: n=198 for artists, n=54 for labels — flagged throughout, not smoothed over).

### Methods compared

- **pg_trgm** (baseline): `ORDER BY similarity(name, query) DESC LIMIT 50`, plain sequential scan — no GIN/GiST
  index, so there is no `%`-operator similarity-threshold cutoff that could silently drop a weak but correct
  match before it's ranked.
- **multilingual-e5-small** (MIT) and **bge-m3** (MIT), both local, CPU-only, via `sentence-transformers`.
  e5 uses the model's documented `"query: "` / `"passage: "` asymmetric prefixes; bge-m3 uses no prefix
  (not required for its dense head). Embeddings stored in `pgvector` (`vector(384)` / `vector(1024)`),
  retrieved with `ORDER BY embedding <=> query LIMIT 50` — no HNSW/IVFFlat index, i.e. exact flat-scan
  cosine search, per the design's "no ANN index" directive.
- **RRF(trgm, e5)** and **RRF(trgm, bge)**: Reciprocal Rank Fusion, `score = Σ 1/(60 + rank)` over each
  method's top-50 list (`k=60`, the standard RRF constant), re-ranked descending. "The fused method" in the
  acceptance criteria is read as the better of these two per kind, reported individually below.
- bge-m3's sparse/lexical output was **not** evaluated — out of scope for the time budget; noted as a gap.

### Infrastructure

- `postgres@sha256:b8e68149dff78f8c379e7d8d6b3dd3c3cff74c9d4dad83118ed11b9d4e9ba3e9` (postgres:19beta3-alpine)
  + pgvector 0.8.6 built from source per the proven recipe handed down from the sibling footprint spike
  (`gm-design-chw.1`); `pg_trgm` from contrib. Container `gm-spike-identity-pg`, port 15433, dropped at the
  end of this run.
- Docker/colima VM: 2 CPUs, ~8GB RAM (confirmed via `docker info` / `colima list`) — unchanged, per instruction.
- Embedding inference ran in a host Python 3.14 process (`uv`-managed venv), **not** inside the DB container,
  with `torch.set_num_threads(4)` and `OMP_NUM_THREADS=4` to respect the 4-thread cap and leave headroom for
  the concurrently running graph-embedding spike on the same host.
- No product-derived data or embeddings are committed; only this report, the throwaway scripts under
  `docs/spikes/gm-design-chw.3/scripts/`, and aggregate metrics. All raw dump downloads and intermediate
  JSONL ground-truth files were deleted after the sampled candidate/query sets were built; disk footprint
  peaked at ~4.7GB (mostly the two MIT-licensed model caches) against a ~10GB budget flagged mid-run by the
  dispatcher, confirmed via `df -h` before/after each large step.

### Licenses (checked against `catalog-api/tests/test_dependency_license_policy.py`: no GPL/AGPL, no non-OSI
model terms)

| Package | Version | License |
|---|---|---|
| intfloat/multilingual-e5-small (model) | — | MIT |
| BAAI/bge-m3 (model) | — | MIT |
| torch | 2.14.0 | BSD-3-Clause / Apache-2.0 / MIT / BSL-1.0 mix (bundled components) |
| transformers | 5.17.0 | Apache-2.0 |
| sentence-transformers | 6.1.0 | Apache-2.0 |
| huggingface-hub | 1.32.0 | Apache-2.0 |
| numpy | 2.5.3 | BSD-3-Clause (+ permissive bundled components) |
| lxml | 6.1.3 | BSD-3-Clause |
| psycopg / psycopg-binary | 3.3.6 | LGPL-3.0-only (reciprocal; harness-only, not shipped) |
| tqdm | 4.70.1 | MPL-2.0 AND MIT (reciprocal; harness-only, not shipped) |
| pgvector | 0.8.6 | PostgreSQL License |

Nothing here is GPL/AGPL or carries non-OSI model terms. `psycopg` and `tqdm` are reciprocal-licensed but
compliant; they're throwaway-harness dependencies, not proposed as shipped `catalog-api`/loader dependencies,
so the locked-notice requirement in the policy test doesn't apply to this spike's own tooling. If a future
implementation bead actually ships `psycopg` in a service, that notice obligation carries over — `catalog-api`
already depends on it today per the same test file, so nothing new there.

## Evidence

Recall@1/10/50, overall and sliced by script, name/target match class, and name-frequency collision, for
both entity kinds. "diacritic_or_case_only" = the MusicBrainz name and the correct Discogs name differ only
by diacritics/case after NFKD-fold; "other_mismatch" = they differ beyond that (real transliteration, alias,
or spelling divergence); "common" name-frequency = the correct target's normalized name (Discogs
disambiguation suffixes like " (2)" stripped first) collides with another name in the sampled pool.

### Artists

**overall** (n=5000)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 96.5% | 97.6% | 97.7% |
| e5-small | 93.6% | 97.7% | 98.4% |
| bge-m3 | 93.9% | 97.8% | 98.3% |
| RRF(trgm,e5) | 95.5% | 97.9% | 98.5% |
| RRF(trgm,bge) | 95.4% | 97.9% | 98.4% |

**script=latin** (n=4797)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 98.1% | 99.2% | 99.4% |
| e5-small | 94.8% | 99.0% | 99.4% |
| bge-m3 | 95.1% | 99.0% | 99.3% |
| RRF(trgm,e5) | 97.0% | 99.2% | 99.5% |
| RRF(trgm,bge) | 97.0% | 99.2% | 99.5% |

**script=non_latin** (n=198, small — interpret with caution)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 57.1% | 57.1% | 57.6% |
| e5-small | 62.6% | 66.7% | 74.2% |
| bge-m3 | 65.7% | 69.2% | 73.2% |
| RRF(trgm,e5) | 58.1% | 64.6% | 72.2% |
| RRF(trgm,bge) | 58.6% | 66.7% | 71.7% |

**match_class=diacritic_or_case_only** (n=267)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 100.0% | 100.0% | 100.0% |
| e5-small | 98.9% | 100.0% | 100.0% |
| bge-m3 | 98.9% | 100.0% | 100.0% |
| RRF(trgm,e5) | 100.0% | 100.0% | 100.0% |
| RRF(trgm,bge) | 100.0% | 100.0% | 100.0% |

**match_class=exact** (n=3686)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 100.0% | 100.0% | 100.0% |
| e5-small | 100.0% | 100.0% | 100.0% |
| bge-m3 | 100.0% | 100.0% | 100.0% |
| RRF(trgm,e5) | 100.0% | 100.0% | 100.0% |
| RRF(trgm,bge) | 100.0% | 100.0% | 100.0% |

**match_class=other_mismatch** (n=1047)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 83.2% | 88.3% | 89.0% |
| e5-small | 69.6% | 89.1% | 92.4% |
| bge-m3 | 71.2% | 89.5% | 91.7% |
| RRF(trgm,e5) | 78.4% | 89.8% | 92.6% |
| RRF(trgm,bge) | 78.3% | 90.1% | 92.2% |

**name_frequency=common** (n=53, small)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 41.5% | 98.1% | 98.1% |
| e5-small | 35.8% | 94.3% | 98.1% |
| bge-m3 | 39.6% | 96.2% | 96.2% |
| RRF(trgm,e5) | 41.5% | 98.1% | 98.1% |
| RRF(trgm,bge) | 43.4% | 96.2% | 98.1% |

**name_frequency=rare** (n=4947)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 97.0% | 97.6% | 97.7% |
| e5-small | 94.2% | 97.8% | 98.4% |
| bge-m3 | 94.5% | 97.8% | 98.3% |
| RRF(trgm,e5) | 96.0% | 97.9% | 98.5% |
| RRF(trgm,bge) | 96.0% | 97.9% | 98.4% |

### Labels

**overall** (n=5000)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 96.2% | 98.4% | 98.7% |
| e5-small | 91.9% | 98.0% | 99.1% |
| bge-m3 | 92.5% | 98.4% | 99.3% |
| RRF(trgm,e5) | 94.0% | 98.8% | 99.2% |
| RRF(trgm,bge) | 94.4% | 99.0% | 99.4% |

**script=latin** (n=4943)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 96.5% | 98.8% | 99.1% |
| e5-small | 92.1% | 98.2% | 99.3% |
| bge-m3 | 92.7% | 98.6% | 99.4% |
| RRF(trgm,e5) | 94.4% | 99.0% | 99.5% |
| RRF(trgm,bge) | 94.6% | 99.2% | 99.6% |

**script=non_latin** (n=54, small — interpret with caution)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 61.1% | 61.1% | 63.0% |
| e5-small | 72.2% | 77.8% | 79.6% |
| bge-m3 | 75.9% | 77.8% | 85.2% |
| RRF(trgm,e5) | 64.8% | 77.8% | 77.8% |
| RRF(trgm,bge) | 70.4% | 77.8% | 79.6% |

**match_class=diacritic_or_case_only** (n=310)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 100.0% | 100.0% | 100.0% |
| e5-small | 98.4% | 99.7% | 100.0% |
| bge-m3 | 97.7% | 100.0% | 100.0% |
| RRF(trgm,e5) | 99.7% | 100.0% | 100.0% |
| RRF(trgm,bge) | 99.7% | 100.0% | 100.0% |

**match_class=exact** (n=3745)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 99.9% | 100.0% | 100.0% |
| e5-small | 100.0% | 100.0% | 100.0% |
| bge-m3 | 100.0% | 100.0% | 100.0% |
| RRF(trgm,e5) | 99.9% | 100.0% | 100.0% |
| RRF(trgm,bge) | 99.9% | 100.0% | 100.0% |

**match_class=other_mismatch** (n=945)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 80.1% | 91.6% | 93.0% |
| e5-small | 57.5% | 89.3% | 95.0% |
| bge-m3 | 61.0% | 91.4% | 96.1% |
| RRF(trgm,e5) | 68.8% | 93.5% | 96.0% |
| RRF(trgm,bge) | 70.5% | 94.5% | 96.6% |

**name_frequency=common** (n=111)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 49.5% | 96.4% | 97.3% |
| e5-small | 31.5% | 86.5% | 98.2% |
| bge-m3 | 30.6% | 85.6% | 94.6% |
| RRF(trgm,e5) | 45.0% | 95.5% | 97.3% |
| RRF(trgm,bge) | 39.6% | 96.4% | 97.3% |

**name_frequency=rare** (n=4889)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 97.2% | 98.5% | 98.7% |
| e5-small | 93.2% | 98.2% | 99.1% |
| bge-m3 | 93.9% | 98.7% | 99.4% |
| RRF(trgm,e5) | 95.2% | 98.9% | 99.3% |
| RRF(trgm,bge) | 95.6% | 99.0% | 99.4% |

(`script=unknown` buckets, n=5 artists / n=3 labels — names with no alphabetic characters at all — are
omitted here as statistically meaningless; both were 100% recall across every method, already visible in the
per-kind evidence tables' raw run output if this spike is re-run with `scripts/analyze_results.py`.)

### Throughput (host CPU, 4 threads)

| | e5-small | bge-m3 |
|---|---|---|
| artist candidates (20,000) | 1,458 texts/sec | 183 texts/sec |
| label candidates (20,000) | 936 texts/sec | 129 texts/sec |
| query scoring (5,000 queries × 3 SQL lookups against a 20k-row exact scan) | ~4.4 queries/sec combined (≈260ms/query for trgm+e5+bge) | |

### The GO/NO-GO arithmetic, stated precisely (per acceptance: fused recall@10 − trgm recall@10 ≥ 5pt on
artists or labels)

| kind | trgm@10 | best fused@10 | delta |
|---|---|---|---|
| artist (overall, n=5000) | 97.56% | 97.92% (RRF-bge) | **+0.36pt** |
| label (overall, n=5000) | 98.42% | 98.96% (RRF-bge) | **+0.54pt** |

Both are far below the 5-point bar — this is not a near-miss at the aggregate level, it's a clear miss, driven
by a ceiling effect: ~75-80% of queries per kind are `exact` or `diacritic_or_case_only` matches where
`pg_trgm` already sits at 100% recall@10, so there is no headroom left for any method to improve on there.

The one segment that *does* clear the bar decisively is **non-Latin script names**:

| kind (non-Latin slice) | n | trgm@10 | best fused@10 | delta |
|---|---|---|---|---|
| artist | 198 | 57.07% | 66.67% (RRF-bge) | **+9.60pt** |
| label | 54 | 61.11% | 77.78% (RRF-e5/bge, tied) | **+16.67pt** |

Flagged, not rounded away: these are real, decisive deltas exceeding the threshold, but on samples an order
of magnitude smaller than the overall query set (198 and 54 vs 5000), because non-Latin names are a small
fraction (≈4% of linked artists, ≈1% of linked labels) of the natural MusicBrainz↔Discogs link population.

## Verdict

**NO-GO**, per the acceptance criterion as written (fused recall@10 vs. `pg_trgm` recall@10, aggregate,
per kind): the fused method improves recall@10 by 0.36 points on artists and 0.54 points on labels, both
well under the 5-point bar. A general-purpose, always-on embedding candidate generator sitting under
`provider_aliases` is not justified by this evidence — `pg_trgm` alone, which needs no model, no pgvector
storage, and no embedding-inference dependency, already gets recall@10 into the high 90s for the bulk of
real MusicBrainz↔Discogs name pairs, because most of them are exact or near-exact string matches.

The one place the evidence says the opposite is the non-Latin-script segment, where fusion clears the bar
by a wide margin on both entity kinds (+9.6pt artists, +16.7pt labels) — see Recommendation for how to act on
that without contradicting the aggregate NO-GO.

Two further findings shape the recommendation below:

- **Dense embeddings alone are worse than `pg_trgm` at recall@1 in every slice tested** (e.g. artists overall:
  trgm 96.5% vs. e5-small 93.6% / bge-m3 93.9%). Fusion recovers most but not all of this gap. Embeddings
  should never replace trigram matching as a standalone method; at best they supplement it.
- **The largest single failure mode is genuine name ambiguity, not a matching-method weakness.** In the
  `name_frequency=common` slice (the correct target's name collides with another candidate in the pool, after
  stripping Discogs' own "(2)"-style disambiguation suffixes), recall@1 collapses to 30-50% for *every*
  method — trigram and dense alike — while recall@10 stays high. No name-string method, however good, can
  resolve which of two same-named artists/labels is correct from the name alone; that needs a downstream
  signal (release/discography overlap, active-year overlap, country) that is out of scope for a name-only
  candidate generator.

## Recommendation

1. **Do not build a general-purpose embedding candidate generator now.** The aggregate recall gain over the
   existing (free, dependency-free, already-exact) `pg_trgm` baseline is under one point for both artists and
   labels — not worth the pgvector storage, the two ~500MB–2GB model downloads, and the CPU-bound embedding
   inference cost this spike measured.
2. **The non-Latin-script segment is worth a follow-up, not an implementation bead yet.** A decisive
   double-digit recall@10 gain on both entity kinds, but on samples of 198 and 54 — re-run this same harness
   (`docs/spikes/gm-design-chw.3/scripts/`) with a *non-Latin-only* stratified sample sized in the low
   thousands (achievable by drawing more MB-linked entities specifically from the non-Latin bucket, which
   this run under-sampled proportionally) before deciding whether a **narrowly scoped** candidate generator —
   triggered only when a script-detection heuristic flags non-Latin content on either side of a prospective
   match, or as a fallback tier when `pg_trgm`'s top hit is weak — clears the bar on a properly powered sample.
3. **If a scoped generator like that is later built**, it would write to `provider_aliases` exactly as ADR
   0009 already specifies for any heuristic: `provider='discogs'`, `entity_kind='artist'|'label'`,
   `source='inference'`, `confidence` derived from the RRF/cosine score, `asserted_at=now()`. It would never
   auto-promote to `source='catalog'` — that stays a human-reviewed or deterministic-loader decision, exactly
   the same non-promotion boundary gm-design-zwy's Semantica evaluation draws for release-edition candidates.
   Given the common-name-collision failure mode above, any such generator's output belongs behind a
   confidence floor and/or human review queue, not a direct write path — rank-1 precision from name alone is
   not trustworthy when a genuine namesake exists.
4. **Relationship to gm-design-zwy**: that spike was still OPEN and unclaimed as of this run, so there was no
   labelled-pairs set or deterministic baseline yet to share in either direction. This spike's ground-truth
   construction method — hold out a real MusicBrainz→Discogs URL relation, recover the Discogs side by id,
   stratify by script — is a real (non-synthetic), reusable pattern if gm-design-zwy wants labelled
   artist/label pairs; note its primary scope is release-edition matching, a different entity kind and a
   harder identity problem (barcodes, pressings, matrix numbers) than the name-only artist/label matching
   evaluated here, so the two verdicts should be read independently rather than combined.
5. **Releases/editions remain out of scope** here, per the epic design (ADR 0011 territory).

## Appendix: reproducing this spike

Scripts live under `docs/spikes/gm-design-chw.3/scripts/` (throwaway harness code, not product code):

- `extract_mb_ground_truth.py` — streams a MusicBrainz JSON dump, keeps entities with a Discogs URL relation.
- `extract_discogs_targets.py` — streams a Discogs XML dump, keeps records matching a target-id set.
- `build_dataset.py` — joins the two sides, builds the stratified query sample and candidate pool.
- `patch_name_frequency.py` — fixes the name-frequency collision axis to key off the *correct target's*
  normalized name (with Discogs "(2)"-style disambiguation suffixes stripped) rather than the MusicBrainz
  query name; used once, in place, on already-computed results (see git history of this bead's worktree).
- `run_eval.py` — loads pg_trgm/pgvector, embeds both sides, scores recall@1/10/50 per method.
- `analyze_results.py` — slices results and prints the GO/NO-GO arithmetic.
- `Dockerfile` — the PG19beta3-alpine + pgvector 0.8.6 image recipe (inherited from the sibling footprint
  spike, gm-design-chw.1).

No provider-derived data, embeddings, or model weights are committed; the downloaded dumps were never
written to disk (streamed straight from `curl`/`gunzip`/`tar` into the extraction scripts), and the
sampled JSONL datasets, HF model cache, Python venv, and eval logs under `data/`/`work/`/`.venv/` were all
deleted from the working tree before submission.
