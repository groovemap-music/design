# Spike: non-Latin candidate recall with a realistic candidate pool

- Bead: gm-design-e0b.1 (child of epic gm-design-e0b, "Spike non-Latin identity candidates
  against a realistic pool")
- Provenance: spike epic gm-design-chw, ADR 0013 ("Identity candidates: not adopted now, not
  disproven") and its follow-ups "Non-Latin identity evaluation" and "Shared ground truth". The
  identity spike (docs/spikes/gm-design-chw.3-*) found fusion adds +9.6pt (artists, n=198) and
  +16.7pt (labels, n=54) recall@10 on non-Latin names, but flagged that result as measured on
  thin samples, a 20,000-row candidate pool, and an already-linked (easy-skewed) population.
- Related: gm-design-zwy ("Evaluate Semantica for cross-catalog identity matching") -- the
  ground-truth construction method below was posted as a comment there so both evaluations can
  score the same kind of pairs.

## Question

At a realistic candidate-pool size (>=1M Discogs artists, all Discogs labels) and a properly
powered non-Latin-only query sample (low thousands per entity type, not a thin slice of a
mixed-script sample), does trigram+embedding fusion raise non-Latin recall@10 over `pg_trgm`
alone enough to justify an inferred-alias candidate generator for that slice?

## Method

### Ground truth

Same principle as gm-design-chw.3: existing MusicBrainz -> Discogs URL relations
(`relations[].type == "discogs"` in the MusicBrainz JSON dumps) are free, real-world linked
pairs. Hold out the link and ask each retrieval method to recover the Discogs entity from the
MusicBrainz name alone. Unlike chw.3, the query population here is restricted to non-Latin
script from the start (chw.3 sampled proportionally across all scripts, so non-Latin was a thin
~4%/~1% slice of a 5,000-query sample; this spike samples non-Latin entities directly).

1. `extract_mb_nonlatin.py` streams the MusicBrainz `artist`/`label` JSON dumps
   (`json-dumps/20260923-001002/{artist,label}.tar.xz` from data.metabrainz.org, decompressed
   only in a pipe -- `curl | tar -xJf - -O mbdump/<kind>` -- never written to disk) and in a
   single pass tallies, for every entity: its script bucket and whether it carries a Discogs
   relation. It emits ground-truth rows only for entities that are non-Latin **and** already
   linked -- the query population for this spike.
2. `extract_discogs_targets.py` (unchanged from chw.3) streams the Discogs 2026-09-01 XML dumps
   (`data.discogs.com/?download=data/2026/discogs_20260901_{artists,labels}.xml.gz` -- the S3
   mirror 403s, `data.discogs.com` does not) and recovers each target record by numeric id via
   `lxml.etree.iterparse`, clearing each element as it's read.
3. `extract_discogs_pool.py` (new) streams the same Discogs dumps again and builds the
   realistic-scale candidate pool: every query's correct target is always kept; every other
   record is kept via Bernoulli sampling at a fixed probability (artists) or with probability 1
   (labels -- "all labels" per the epic design). Single pass, O(1) memory.
4. `build_dataset.py` joins the MB and Discogs sides, computes `match_class` (exact /
   diacritic_or_case_only / other_mismatch, via NFKD-fold with Discogs' `" (2)"`-style
   disambiguator stripped first) and `name_frequency` (collision count keyed off the *correct
   target's* normalized name in the pool, not the MB query spelling -- chw.3 shipped that the
   other way round and fixed it post hoc via `patch_name_frequency.py`; this run computes it
   correctly from the start), and writes the final candidate pool and query set.

**Script classification**: chw.3 used a binary latin/non_latin split, adequate there because
non-Latin was one thin slice among many. Here the whole query population is non-Latin by
construction, so "sliced by script" (the acceptance criterion) needs a finer breakdown, or it
collapses to one row. `script_util.py` classifies by the dominant Unicode block among a name's
alphabetic characters: `cyrillic`, `han` (CJK ideographs, shared across zh/ja/ko), `japanese_kana`
(hiragana/katakana), `korean_hangul`, `hebrew`, `arabic`, `greek`, `devanagari`, `thai`,
`other_non_latin`, plus `latin`/`unknown` (excluded from the query population).

### Ground-truth population (this run, MusicBrainz 2026-09-23 dump x Discogs 2026-09-01 dump)

| | MB scanned | MB linked (any script) | MB non-Latin | MB non-Latin **linked** | MB non-Latin **unlinked** |
|---|---:|---:|---:|---:|---:|
| artist | 2,992,523 | 1,271,176 | 180,899 | 49,787 | **131,112** |
| label | 350,637 | 164,278 | 6,950 | 1,611 | **5,339** |

The unlinked-non-Latin counts are the real prize this spike is sizing: 131,112 non-Latin
MusicBrainz artists and 5,339 non-Latin MusicBrainz labels have no Discogs link today at all,
roughly 2.6x (artists) and 3.3x (labels) the number that are already linked.

### Scoping the candidate pool and query sample

Per the epic design, this run does **not** cap the candidate pool at 20,000 (chw.3's budget
compromise). Instead:

- **Artists**: every one of the 49,783 unique target ids, plus a Bernoulli sample (p=0.10354,
  seed 20260924) of the rest of the streamed Discogs artist dump (10,203,002 records scanned),
  for a realized pool of **1,098,846** candidates (target: >=1,000,000, met with margin).
- **Labels**: **every** Discogs label record (2,729,516 scanned, 2,415,477 after de-duplicating
  malformed/duplicate ids in the dump -- matches ADR 0013's independently-derived count of
  2,415,476 to within 1 row), per the epic design's "(all labels)".

Query sample: up to 5,000 non-Latin linked entities per kind (sampled down when more are
available), all of them when fewer are:

| kind | non-Latin linked available | usable (Discogs record recovered) | sampled |
|---|---:|---:|---:|
| artist | 49,787 | 48,714 | 5,000 |
| label | 1,611 | 1,592 | **1,592 (all available -- below the 5,000 cap, flagged)** |

The label query count (1,592) is thinner than "low thousands" would ideally support -- it is
every non-Latin, Discogs-linked MusicBrainz label that exists in the current dump, not a
sampling choice. This is the real size of that population, not a budget shortcut; flagged per
instruction rather than smoothed over.

### Methods compared

Same five methods as chw.3: `pg_trgm` baseline, `multilingual-e5-small` (MIT) and `bge-m3` (MIT)
dense retrieval, and RRF(trgm, e5) / RRF(trgm, bge) fusion (k=60, standard RRF constant, over
each method's own top-50 list). bge-m3's sparse/lexical output was again not evaluated (out of
scope for the time budget, same gap chw.3 flagged).

### Infrastructure -- and why retrieval is computed differently from chw.3

chw.3 stored both dense embeddings in `pgvector` and ran one exact flat-scan SQL query per
query row per method against a 20,000-row pool. That does not scale to this spike's pool sizes:
per-query latency on an unindexed scan grows ~linearly with pool size, so the same approach at
1.1M/2.4M rows would turn a few-thousand-query eval into many hours on the 2-CPU/8GB Docker VM
this spike runs against (unchanged, per instruction). Two changes:

- **`pg_trgm`**: still real Postgres, but via a **GiST `gist_trgm_ops` index**
  (`ORDER BY name <-> query LIMIT k`, index-accelerated KNN) instead of a sequential scan. The
  candidates table holds only `(discogs_id, name)` -- no embeddings -- so its footprint stays a
  few hundred MB regardless of dense-method pool size. This is a real deviation from chw.3's "no
  ANN index" directive for pg_trgm specifically: it was necessary for tractable runtime at this
  scale, and a GiST-indexed trigram search is what a production `pg_trgm` deployment would
  actually use, so it does not make the number less representative of a real system -- if
  anything, more.
- **Dense (e5-small, bge-m3)**: embeddings never touch Postgres. Candidates and queries are
  encoded once with `sentence-transformers`, held as in-process `numpy` arrays (L2-normalized,
  so dot product = cosine similarity), and scored with batched, BLAS-backed matrix
  multiplication -- one method's candidate matrix at a time, freed before the next, to bound
  peak host RAM. **This is computed as exact cosine top-k, not an ANN index** -- see the
  HNSW-vs-exact side-check below for how much of a ceiling that is relative to what pgvector's
  HNSW index (the shape ADR 0013 actually adopts) would retrieve in production.

RRF fusion is computed exactly as in chw.3: rank-based reciprocal fusion over each method's own
top-50 list, combining the (indexed) trgm ranks with the (exact) dense ranks.

Postgres: `postgres@sha256:b8e68149dff78f8c379e7d8d6b3dd3c3cff74c9d4dad83118ed11b9d4e9ba3e9`
(postgres:19beta3-alpine), unmodified -- `pg_trgm` ships in contrib, no custom pgvector build
needed this run since embeddings never enter the database. Container `gm-spike-e0b1-pg`, port
15433, dropped at the end of this run. Docker VM: 2 CPUs, ~8GB RAM, unchanged. Embedding
inference ran in a host Python 3.14 process (`uv`-managed venv, dependency versions identical to
chw.3's), not inside the DB container, with `torch.set_num_threads(6)` (raised from chw.3's 4,
since the host has 10 cores / 32GB and this spike ran without a concurrent sibling spike
contending for the same host process).

### Throughput (host CPU, 6 threads; Docker VM 2 CPU/~8GB unchanged for `pg_trgm`)

| | artists (1,098,846 candidates, 5,000 queries) | labels (2,415,476 candidates, 1,592 queries) |
|---|---|---|
| `pg_trgm` query scoring (GiST-indexed KNN) | 1,026.9s total, 4.87 queries/sec | 1,043.9s total, 1.53 queries/sec |
| GiST trgm index build | 21-22s | 89.2s |
| e5-small candidate embedding | 740.7s, 1,483.6 texts/sec | 1,918.4s, 1,259.1 texts/sec |
| bge-m3 candidate embedding | 5,612.2s (~93.5 min), 195.8 texts/sec | 14,542.7s (~4.04 hours), 166.1 texts/sec |
| e5-small dense scoring (batched matmul) | 40.6s | 56.3s |
| bge-m3 dense scoring (batched matmul) | 53.5s | 54.5s |

`bge-m3` candidate embedding dominates wall-clock time at this scale (~1.5 hours for the
artist pool, ~4 hours for the full label pool) -- the main reason chw.3's per-query
pgvector-exact-scan approach was replaced (see Infrastructure above): at these throughputs,
re-embedding is a one-time cost per pool, but re-scoring per query against an unindexed 1M+/2.4M
row table would not have been.

### Licenses (checked against `catalog-api/tests/test_dependency_license_policy.py`: no GPL/AGPL,
no non-OSI model terms) -- unchanged from chw.3, same dependency versions:

| Package | Version | License |
|---|---|---|
| intfloat/multilingual-e5-small (model) | -- | MIT |
| BAAI/bge-m3 (model) | -- | MIT |
| torch | 2.14.0 | BSD-3-Clause / Apache-2.0 / MIT / BSL-1.0 mix (bundled components) |
| transformers | 5.17.0 | Apache-2.0 |
| sentence-transformers | 6.1.0 | Apache-2.0 |
| huggingface-hub | 1.33.0 | Apache-2.0 |
| numpy | 2.5.3 | BSD-3-Clause (+ permissive bundled components) |
| lxml | 6.1.3 | BSD-3-Clause |
| psycopg / psycopg-binary | 3.3.6 | LGPL-3.0-only (reciprocal; harness-only, not shipped) |
| tqdm | 4.70.1 | MPL-2.0 AND MIT (reciprocal; harness-only, not shipped) |

Nothing here is GPL/AGPL or carries non-OSI model terms. `psycopg` and `tqdm` are
reciprocal-licensed but compliant; throwaway-harness dependencies only, not proposed for
`catalog-api`/loader. No `pgvector` dependency this run (see Infrastructure).

## Evidence

Recall@1/10/50, overall and sliced by script / match-class / name-frequency (`script` here is the
finer per-block classifier above, not the binary split; `match_class` and `name_frequency`
definitions are unchanged from chw.3). Every row's `n` is stated -- several script slices are
thin by nature of the real population (see the ground-truth table above), flagged rather than
smoothed over.

### Artists (n=5,000 non-Latin queries, 1,098,846-candidate pool)

**overall** (n=5000)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 53.2% | 54.4% | 54.5% |
| e5-small | 54.7% | 59.6% | 62.3% |
| bge-m3 | 55.4% | 60.2% | 62.9% |
| RRF(trgm,e5) | 53.3% | 57.2% | 62.0% |
| RRF(trgm,bge) | 53.3% | 58.4% | 62.2% |

**script=han** (n=1917 -- the largest slice, 38% of the artist sample; see diagnosis below)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 25.6% | 26.0% | 26.0% |
| e5-small | 25.8% | 26.3% | 26.6% |
| bge-m3 | 25.9% | 26.5% | 26.9% |
| RRF(trgm,e5) | 25.8% | 26.2% | 26.4% |
| RRF(trgm,bge) | 25.9% | 26.4% | 26.8% |

**script=cyrillic** (n=1358)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 84.9% | 87.6% | 87.8% |
| e5-small | 85.3% | 92.2% | 95.4% |
| bge-m3 | 86.7% | 94.7% | 97.1% |
| RRF(trgm,e5) | 84.2% | 90.1% | 95.9% |
| RRF(trgm,bge) | 84.2% | 91.8% | 97.3% |

**script=japanese_kana** (n=588)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 47.8% | 48.1% | 48.1% |
| e5-small | 53.1% | 62.4% | 68.4% |
| bge-m3 | 54.8% | 61.7% | 65.6% |
| RRF(trgm,e5) | 48.5% | 57.5% | 67.2% |
| RRF(trgm,bge) | 48.5% | 60.0% | 64.5% |

**script=hebrew** (n=583)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 55.9% | 57.3% | 57.3% |
| e5-small | 60.4% | 72.2% | 78.7% |
| bge-m3 | 60.7% | 69.5% | 79.2% |
| RRF(trgm,e5) | 56.3% | 63.3% | 77.7% |
| RRF(trgm,bge) | 56.1% | 64.0% | 76.0% |

**script=greek** (n=252)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 83.3% | 84.5% | 84.5% |
| e5-small | 84.9% | 88.5% | 92.1% |
| bge-m3 | 82.9% | 87.7% | 90.1% |
| RRF(trgm,e5) | 84.1% | 85.3% | 90.9% |
| RRF(trgm,bge) | 83.7% | 85.7% | 89.3% |

**script=korean_hangul** (n=135)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 63.0% | 64.4% | 65.2% |
| e5-small | 63.7% | 65.9% | 65.9% |
| bge-m3 | 62.2% | 66.7% | 68.1% |
| RRF(trgm,e5) | 63.0% | 65.9% | 65.9% |
| RRF(trgm,bge) | 62.2% | 66.7% | 67.4% |

**script=arabic** (n=90)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 75.6% | 75.6% | 75.6% |
| e5-small | 72.2% | 74.4% | 77.8% |
| bge-m3 | 76.7% | 83.3% | 85.6% |
| RRF(trgm,e5) | 74.4% | 76.7% | 78.9% |
| RRF(trgm,bge) | 75.6% | 82.2% | 84.4% |

**script=thai** (n=44)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 84.1% | 84.1% | 84.1% |
| e5-small | 84.1% | 84.1% | 88.6% |
| bge-m3 | 84.1% | 86.4% | 88.6% |
| RRF(trgm,e5) | 84.1% | 84.1% | 84.1% |
| RRF(trgm,bge) | 84.1% | 84.1% | 86.4% |

**script=other_non_latin** (n=32 -- thin, interpret with caution)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 34.4% | 34.4% | 34.4% |
| e5-small | 43.8% | 50.0% | 53.1% |
| bge-m3 | 62.5% | 68.8% | 81.2% |
| RRF(trgm,e5) | 37.5% | 50.0% | 53.1% |
| RRF(trgm,bge) | 46.9% | 68.8% | 75.0% |

**script=devanagari** (n=1 -- not meaningful, listed for completeness only)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 0.0% | 0.0% | 0.0% |
| e5-small | 100.0% | 100.0% | 100.0% |
| bge-m3 | 100.0% | 100.0% | 100.0% |
| RRF(trgm,e5) | 100.0% | 100.0% | 100.0% |
| RRF(trgm,bge) | 100.0% | 100.0% | 100.0% |

**match_class=exact** (n=2403)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 99.9% | 100.0% | 100.0% |
| e5-small | 99.6% | 99.9% | 100.0% |
| bge-m3 | 99.9% | 100.0% | 100.0% |
| RRF(trgm,e5) | 100.0% | 100.0% | 100.0% |
| RRF(trgm,bge) | 100.0% | 100.0% | 100.0% |

**match_class=diacritic_or_case_only** (n=147)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 83.0% | 98.0% | 98.0% |
| e5-small | 62.6% | 89.8% | 97.3% |
| bge-m3 | 64.6% | 91.2% | 97.3% |
| RRF(trgm,e5) | 76.2% | 99.3% | 100.0% |
| RRF(trgm,bge) | 73.5% | 98.6% | 100.0% |

**match_class=other_mismatch** (n=2450)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 5.6% | 7.1% | 7.3% |
| e5-small | 10.2% | 18.2% | 23.2% |
| bge-m3 | 11.2% | 19.3% | 24.4% |
| RRF(trgm,e5) | 6.2% | 12.7% | 22.5% |
| RRF(trgm,bge) | 6.4% | 15.2% | 22.9% |

**name_frequency=common** (n=208)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 19.7% | 31.7% | 31.7% |
| e5-small | 18.3% | 29.8% | 35.6% |
| bge-m3 | 18.3% | 29.3% | 36.5% |
| RRF(trgm,e5) | 19.7% | 32.2% | 36.5% |
| RRF(trgm,bge) | 18.3% | 33.2% | 37.0% |

**name_frequency=rare** (n=4792)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 54.7% | 55.4% | 55.5% |
| e5-small | 56.3% | 60.9% | 63.4% |
| bge-m3 | 57.0% | 61.5% | 64.0% |
| RRF(trgm,e5) | 54.8% | 58.3% | 63.1% |
| RRF(trgm,bge) | 54.9% | 59.5% | 63.3% |

### Labels (n=1,592 non-Latin queries -- every usable one available, below the 5,000 cap;
2,415,477-candidate pool = all Discogs labels)

**overall** (n=1592)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 69.7% | 73.2% | 73.7% |
| e5-small | 70.2% | 78.2% | 81.5% |
| bge-m3 | 72.5% | 80.5% | 83.2% |
| RRF(trgm,e5) | 70.2% | 77.8% | 81.2% |
| RRF(trgm,bge) | 70.9% | 80.0% | 83.0% |

**script=cyrillic** (n=672)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 87.6% | 94.8% | 95.7% |
| e5-small | 86.2% | 94.8% | 97.2% |
| bge-m3 | 88.2% | 96.0% | 96.9% |
| RRF(trgm,e5) | 88.4% | 96.3% | 98.4% |
| RRF(trgm,bge) | 89.0% | 96.6% | 98.2% |

**script=han** (n=360 -- see diagnosis below)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 51.1% | 51.9% | 52.8% |
| e5-small | 52.5% | 55.0% | 56.7% |
| bge-m3 | 53.9% | 57.5% | 61.1% |
| RRF(trgm,e5) | 51.7% | 54.7% | 56.1% |
| RRF(trgm,bge) | 52.2% | 56.9% | 60.0% |

**script=japanese_kana** (n=239)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 51.5% | 51.5% | 51.5% |
| e5-small | 59.4% | 72.0% | 77.4% |
| bge-m3 | 59.4% | 71.5% | 76.6% |
| RRF(trgm,e5) | 52.7% | 68.6% | 74.1% |
| RRF(trgm,bge) | 53.6% | 69.5% | 73.2% |

**script=hebrew** (n=175)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 53.7% | 54.9% | 54.9% |
| e5-small | 51.4% | 62.3% | 70.3% |
| bge-m3 | 58.3% | 72.6% | 77.7% |
| RRF(trgm,e5) | 53.1% | 59.4% | 69.1% |
| RRF(trgm,bge) | 54.9% | 70.9% | 77.1% |

**script=greek** (n=68)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 85.3% | 88.2% | 88.2% |
| e5-small | 85.3% | 92.6% | 95.6% |
| bge-m3 | 86.8% | 89.7% | 92.6% |
| RRF(trgm,e5) | 83.8% | 91.2% | 95.6% |
| RRF(trgm,bge) | 83.8% | 91.2% | 94.1% |

**script=arabic** (n=28 -- thin, interpret with caution)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 92.9% | 92.9% | 92.9% |
| e5-small | 89.3% | 96.4% | 96.4% |
| bge-m3 | 96.4% | 100.0% | 100.0% |
| RRF(trgm,e5) | 92.9% | 92.9% | 96.4% |
| RRF(trgm,bge) | 92.9% | 96.4% | 100.0% |

**script=thai** (n=26 -- thin, interpret with caution)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 88.5% | 92.3% | 92.3% |
| e5-small | 88.5% | 96.2% | 100.0% |
| bge-m3 | 92.3% | 96.2% | 96.2% |
| RRF(trgm,e5) | 88.5% | 96.2% | 96.2% |
| RRF(trgm,bge) | 88.5% | 96.2% | 96.2% |

**script=korean_hangul** (n=14 -- thin, interpret with caution)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 42.9% | 42.9% | 42.9% |
| e5-small | 42.9% | 42.9% | 50.0% |
| bge-m3 | 42.9% | 64.3% | 71.4% |
| RRF(trgm,e5) | 42.9% | 42.9% | 50.0% |
| RRF(trgm,bge) | 42.9% | 57.1% | 71.4% |

**script=other_non_latin** (n=10 -- thin, interpret with caution)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 60.0% | 60.0% | 60.0% |
| e5-small | 60.0% | 80.0% | 80.0% |
| bge-m3 | 70.0% | 80.0% | 80.0% |
| RRF(trgm,e5) | 60.0% | 80.0% | 80.0% |
| RRF(trgm,bge) | 60.0% | 80.0% | 80.0% |

**match_class=exact** (n=931)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 98.6% | 100.0% | 100.0% |
| e5-small | 99.0% | 99.9% | 100.0% |
| bge-m3 | 100.0% | 100.0% | 100.0% |
| RRF(trgm,e5) | 99.6% | 100.0% | 100.0% |
| RRF(trgm,bge) | 99.6% | 100.0% | 100.0% |

**match_class=diacritic_or_case_only** (n=90)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 82.2% | 97.8% | 97.8% |
| e5-small | 74.4% | 92.2% | 98.9% |
| bge-m3 | 72.2% | 93.3% | 96.7% |
| RRF(trgm,e5) | 81.1% | 100.0% | 100.0% |
| RRF(trgm,bge) | 81.1% | 100.0% | 100.0% |

**match_class=other_mismatch** (n=571)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 20.5% | 25.6% | 27.1% |
| e5-small | 22.6% | 40.6% | 48.7% |
| bge-m3 | 27.7% | 46.6% | 53.6% |
| RRF(trgm,e5) | 20.5% | 38.2% | 47.6% |
| RRF(trgm,bge) | 22.4% | 44.3% | 52.5% |

**name_frequency=common** (n=227)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 48.9% | 61.2% | 62.1% |
| e5-small | 48.9% | 63.9% | 70.9% |
| bge-m3 | 51.1% | 66.5% | 70.9% |
| RRF(trgm,e5) | 50.2% | 65.2% | 69.6% |
| RRF(trgm,bge) | 48.9% | 67.8% | 73.6% |

**name_frequency=rare** (n=1365)
| method | recall@1 | recall@10 | recall@50 |
|---|---|---|---|
| pg_trgm | 73.1% | 75.2% | 75.7% |
| e5-small | 73.8% | 80.6% | 83.3% |
| bge-m3 | 76.0% | 82.8% | 85.2% |
| RRF(trgm,e5) | 73.5% | 79.9% | 83.2% |
| RRF(trgm,bge) | 74.5% | 82.1% | 84.5% |

### Why the Han slice is the outlier on both entity kinds: a script mismatch, not a matching-algorithm weakness

Han is the largest artist slice (1,917/5,000 = 38.3%) and the third-largest label slice
(360/1,592 = 22.6%), and its recall is far below every other script on both kinds. Diagnosed
directly against the query/result data (locally, in scratch -- no names below are committed
anywhere):

| kind | Han queries | target ALSO has Han characters | recall@10 there (trgm / RRF-bge) | target fully romanized (no Han characters) | recall@10 there (trgm / RRF-bge) |
|---|---:|---:|---|---:|---|
| artist | 1,917 | 504 (26.3%) | 98.8% / 99.2% | 1,413 (73.7%) | 0.07% / 0.50% |
| label | 360 | 195 (54.2%) | 95.9% / 98.5% | 165 (45.8%) | 0.0% / 7.9% |

When the Discogs side stores the name in Han script too, every method -- `pg_trgm` included --
is near-ceiling (95.9-99.2%), the same pattern as the `exact`/`diacritic_or_case_only`
match classes elsewhere. When Discogs stores the name fully romanized instead (Discogs'
convention for most Japanese and many Chinese artists/labels is "Given Surname" romaji/pinyin,
not the native name -- e.g. `矢野佑太` -> `Yuta Yano`, `武田真治` -> `Shinji Takeda`,
`環星音樂國際有限公司` -> `Worldstar Music International Ltd`), recall collapses to
near-zero for **every** method, including both multilingual dense embedding models. This rules
out two alternative explanations: it is not a Simplified/Traditional-variant problem (only
29/1,442 `other_mismatch` artist rows have Han characters on both sides at all -- real but rare
cases like `波音747大樂隊` -> `波音七四七大樂隊`, `陳世杰` -> `陳世傑`), and it is not a
`pg_trgm`-tokenization artifact specific to CJK text (`bge-m3`, a purpose-built multilingual
embedding model, fails just as completely on the romanized subset as `pg_trgm` does: 0.07%
recall@10 either way for artists). The flat, low aggregate Han recall (26.0% artists, 51.9%
labels at `pg_trgm`) is the population-weighted blend of "near-solved when scripts match" and
"unsolvable by name-string similarity alone when they don't" -- not evidence that trigram or
embedding retrieval handles CJK names poorly in general. The label population happens to have a
less extreme romanization skew (45.8% vs. artists' 73.7%), which is the entire reason label-Han
recall (51.9%) is noticeably higher than artist-Han recall (26.0%).

### Exact-cosine dense retrieval is an upper bound, not a production number -- attempted quantification failed

The dense recall numbers above (`e5-small`, `bge-m3`, and both RRF rows) are exact cosine
top-k over the full pool, computed via batched `numpy` matrix multiplication (see
Infrastructure) -- **not** retrieval through an ANN index. ADR 0013 adopts `pgvector`'s HNSW
index (`halfvec`, `m=16`, `ef_construction=64`, cosine) for artist embeddings in production, and
that footprint spike's own measurement found ANN recall@10 against exact search as low as
0.149-0.654 at `ef_search=100` on synthetic vectors -- so the gap between this spike's exact-cosine
numbers and what HNSW would actually retrieve is a real, and not necessarily small, open
question, not a rounding error.

A small side-check was attempted to quantify it directly: a 50,000-candidate artist subsample
(including every target for a 300-query sample), embedded with both models, loaded into
`pgvector` 0.8.6 (reusing `database-schema-postgres19-pgvector:local`, an image a sibling agent
had already built -- not rebuilt or modified here) with the ADR's exact index shape, comparing
HNSW top-10 (at `ef_search` 40 and 100) against this spike's exact-cosine top-10 on the same
subsample. It did not complete: it failed with `psycopg.errors.DiskFull: could not resize shared
memory segment ... No space left on device` while building the HNSW index. **This is the
container's `/dev/shm` limit (Docker's 64MB default), not host disk pressure** -- an HNSW build
needs shared memory scaled with `maintenance_work_mem`, which the container was never given via
`--shm-size` (the same requirement the lhp2 procedure documents for the production build). **No
HNSW-vs-exact number is reported here; this is an acknowledged, unquantified limitation**, not a
measured small gap. Re-running this check (`docs/spikes/gm-design-e0b.1/scripts/hnsw_vs_exact.py`,
already written) with `--shm-size` set on the container would fix the immediate failure, but per
the dispatcher it isn't being re-run right now. gm-analytics-engine-ieu.3 is separately measuring
HNSW-vs-exact recall on production 128-dim FastRP graph vectors with the production index
parameters -- a related data point, not a substitute: those are graph embeddings at a different
dimensionality and distribution than this spike's `e5-small`/`bge-m3` text embeddings, and HNSW
recall does not transfer across that difference. **The text-embedding HNSW-vs-exact gap this
spike would need remains unmeasured.**

## The GO/NO-GO arithmetic, stated precisely (per acceptance: fused recall@10 - trgm recall@10 >= 5pt on artists or labels)

The acceptance criterion is evaluated on the overall (aggregate, all-script) recall@10 per
entity kind, "best fused" meaning the better of RRF(trgm,e5)/RRF(trgm,bge):

| kind | n | trgm@10 | best fused@10 | delta | vs. 5pt bar |
|---|---:|---:|---|---:|---|
| artist | 5,000 | 54.44% | 58.40% (RRF-bge) | **+3.96pt** | **near-miss -- 1.04pt short** |
| label | 1,592 | 73.18% | 80.03% (RRF-bge) | **+6.85pt** | **clears** |

Per the literal acceptance wording ("on artists **or** labels"), the label result alone
satisfies it. Reported exactly, not rounded into a single verdict: the artist aggregate is 1.04
points short of the same bar, not a clear NO-GO either -- and the per-script breakdown below
shows why the two aggregates diverge, which matters more for a real decision than either
aggregate number alone.

**Per-script breakdown, both kinds, exact numbers and flags (n stated for every row; "near-miss"
= within 2 points of the 5-point bar):**

| kind | script | n | trgm@10 | best fused@10 | fused delta | best dense-alone | dense-alone delta | flag |
|---|---|---:|---:|---|---:|---|---:|---|
| artist | han | 1917 | 26.03% | RRF-bge 26.45% | +0.42pt | bge-m3 26.50% | +0.47pt | no (see Han diagnosis) |
| artist | cyrillic | 1358 | 87.63% | RRF-bge 91.83% | +4.20pt | bge-m3 94.70% | +7.07pt | **near-miss** |
| artist | japanese_kana | 588 | 48.13% | RRF-bge 60.03% | +11.90pt | e5-small 62.41% | +14.29pt | GO-eligible |
| artist | hebrew | 583 | 57.29% | RRF-bge 63.98% | +6.69pt | e5-small 72.21% | +14.92pt | GO-eligible |
| artist | greek | 252 | 84.52% | RRF-bge 85.71% | +1.19pt | e5-small 88.49% | +3.97pt | no |
| artist | korean_hangul | 135 | 64.44% | RRF-bge 66.67% | +2.22pt | bge-m3 66.67% | +2.22pt | no |
| artist | arabic | 90 | 75.56% | RRF-bge 82.22% | +6.67pt | bge-m3 83.33% | +7.78pt | GO-eligible (thin) |
| artist | thai | 44 | 84.09% | RRF-e5 84.09% | +0.00pt | bge-m3 86.36% | +2.27pt | no (thin) |
| artist | other_non_latin | 32 | 34.38% | RRF-bge 68.75% | +34.38pt | bge-m3 68.75% | +34.38pt | GO-eligible but too thin to act on |
| artist | devanagari | 1 | 0.00% | RRF-e5 100.00% | +100.00pt | e5-small 100.00% | +100.00pt | n=1, not meaningful |
| label | cyrillic | 672 | 94.79% | RRF-bge 96.58% | +1.79pt | bge-m3 95.98% | +1.19pt | no |
| label | han | 360 | 51.94% | RRF-bge 56.94% | +5.00pt | bge-m3 57.50% | +5.56pt | **at the bar exactly** (see Han diagnosis) |
| label | japanese_kana | 239 | 51.46% | RRF-bge 69.46% | +17.99pt | e5-small 71.97% | +20.50pt | GO-eligible |
| label | hebrew | 175 | 54.86% | RRF-bge 70.86% | +16.00pt | bge-m3 72.57% | +17.71pt | GO-eligible |
| label | greek | 68 | 88.24% | RRF-e5 91.18% | +2.94pt | e5-small 92.65% | +4.41pt | no |
| label | arabic | 28 | 92.86% | RRF-bge 96.43% | +3.57pt | bge-m3 100.00% | +7.14pt | **near-miss** (thin) |
| label | thai | 26 | 92.31% | RRF-e5 96.15% | +3.85pt | e5-small 96.15% | +3.85pt | **near-miss** (thin) |
| label | korean_hangul | 14 | 42.86% | RRF-bge 57.14% | +14.29pt | bge-m3 64.29% | +21.43pt | GO-eligible but too thin to act on |
| label | other_non_latin | 10 | 60.00% | RRF-e5 80.00% | +20.00pt | e5-small 80.00% | +20.00pt | GO-eligible but too thin to act on |

Two further observations that shape the Recommendation:

- **Dense-alone sometimes beats RRF fusion outright.** artist hebrew: e5-small alone +14.92pt vs.
  RRF-bge +6.69pt. label japanese_kana: e5-small alone +20.50pt vs. RRF-bge +17.99pt. artist
  cyrillic: bge-m3 alone +7.07pt vs. RRF-bge +4.20pt (a near-miss for fusion where dense-alone
  clears the bar outright). A flat RRF-fusion policy leaves recall on the table in exactly the
  scripts where fusion's headline gain is otherwise the strongest.
- **Common-name collision is still the largest single failure mode, exactly as chw.3 found.**
  `name_frequency=common` recall@1 collapses for every method on both kinds (artist: trgm 19.7%
  vs. rare 54.7%; label: trgm 48.9% vs. rare 73.1%) while recall@10 stays comparatively high --
  no name-string method, however good, resolves which of two same-named entities is correct from
  the name alone; that needs a downstream signal (release/discography overlap, active-year
  overlap, country), out of scope for a name-only candidate generator.

## Verdict

**GO, narrowly and unevenly** -- reported as exact numbers against the stated bar, not
collapsed into a single up/down call, per the acceptance criterion's own "artists or labels"
wording and the instruction to flag near-misses rather than round them away:

- The **label** aggregate clears the 5-point bar decisively: **+6.85pt** (73.18% -> 80.03%,
  n=1,592). This alone satisfies the acceptance criterion as literally written.
- The **artist** aggregate does not clear it, but only barely: **+3.96pt** (54.44% -> 58.40%,
  n=5,000), **1.04 points short** -- a genuine near-miss, not a clear NO-GO.
- At realistic pool size, both deltas are much smaller than chw.3's thin-sample numbers
  (artists +9.6pt on n=198, labels +16.7pt on n=54): the epic's hypothesis that chw.3's 20k-pool
  result was optimistically inflated by a small, easy candidate set is **confirmed** -- the
  effect is real but substantially smaller (labels) or borderline (artists) once measured against
  a pool 50-1,200x larger and a properly powered non-Latin-only query sample.
- The aggregate-level split between artists and labels is fully explained by population mix, not
  by a different underlying phenomenon: artists' non-Latin query set is 38% Han script, and Han
  is majority-unsolvable by name-similarity alone (73.7% of targets are romanized, not
  transliterated); labels' non-Latin query set is only 22.6% Han with a less severe romanization
  skew (45.8%), so the label aggregate isn't dragged down as far. Outside Han, both kinds show
  the same shape: real, often double-digit recall@10 gains from fusion or dense-alone retrieval
  on cyrillic, hebrew, japanese_kana, arabic, korean_hangul, and (thinly) other_non_latin.
- This verdict describes exact-cosine dense retrieval, an **unquantified upper bound** relative
  to the HNSW index ADR 0013 actually adopts for production (see above) -- the side-check meant
  to size that gap failed on a container `/dev/shm` limit and was not re-attempted. This gap
  remains genuinely unmeasured: gm-analytics-engine-ieu.3's HNSW-vs-exact measurement is a related
  data point, not a substitute, since it covers 128-dim FastRP graph vectors, not this spike's
  `e5-small`/`bge-m3` text embeddings. Whatever generator design follows from this verdict should
  be validated against real ANN retrieval on these text embeddings specifically before being
  treated as production-ready, not just against this spike's exact-cosine numbers.

## Recommendation

1. **Do not build a single, script-agnostic non-Latin candidate generator.** The evidence does
   not support one design covering "all non-Latin scripts" uniformly: Han-script names (the
   largest non-Latin slice on both entity kinds) are majority unsolvable by any name-similarity
   method today, dragging a script-agnostic aggregate toward a near-miss for artists, while a
   handful of other scripts show large, real, actionable gains that a blended aggregate obscures.
2. **A script-scoped generator, gated by script detection, is what the evidence actually
   supports** -- restricted to the scripts where the fused-or-dense-alone gain is decisive and
   the sample is not too thin to trust: cyrillic (artists, near-miss for fusion but bge-m3 alone
   clears +7.07pt), hebrew (both kinds, +6.69 to +17.71pt across fusion/dense-alone), and
   japanese_kana (both kinds, +11.90 to +20.50pt). Treat arabic, korean_hangul, thai, and
   other_non_latin as promising-but-unconfirmed pending a properly powered sample (all n<180 on at
   least one kind here) rather than folding them in on this evidence alone.
3. **Explicitly exclude Han script from any such generator**, or design a separate path for it.
   The diagnosis above shows this is not a retrieval problem a better matching method can solve:
   when Discogs stores a Han-script name, every method (including `pg_trgm`) already recalls it
   at 96-99%; when Discogs stores it romanized, every method -- both dense embedding models
   included -- fails almost completely (0-8% recall@10). Closing that gap needs an explicit
   transliteration/romanization bridge (e.g. pinyin/romaji generation and matching against it) or
   a non-name signal, which is a materially different and larger piece of work than a name-based
   candidate generator, and out of this spike's scope.
4. **Prefer the best single dense model over a flat RRF-fusion policy in several scripts.**
   e5-small or bge-m3 alone outperforms RRF fusion with `pg_trgm` in exactly the scripts where the
   gain is largest (artist hebrew, label japanese_kana, artist cyrillic) -- a per-script or
   per-query policy that chooses between "trust dense alone" and "fuse" would likely beat a
   single fixed RRF rule across the board. Worth a follow-up measurement before implementation,
   not assumed.
5. **Re-validate with real ANN retrieval before shipping anything.** This spike's dense numbers
   are exact-cosine, not HNSW; the attempted quantification of that gap failed on a container
   `/dev/shm` limit (fixable with `--shm-size`), not because the gap was shown to be small. Per
   the dispatcher this spike's own check isn't being re-run right now. gm-analytics-engine-ieu.3's
   HNSW-vs-exact measurement (production index parameters, production FastRP vectors) is a related
   data point, not a substitute -- it's a different vector space (128-dim graph embeddings, not
   `e5-small`/`bge-m3` text embeddings) and HNSW recall does not transfer across that difference.
   The text-embedding gap remains unmeasured and should be closed (re-run
   `hnsw_vs_exact.py` with `--shm-size` set) before treating any recall number here as a
   production estimate.
6. ~~**If a scoped generator is built**, it writes to `provider_aliases` exactly as ADR 0009
   specifies for any heuristic (`provider='discogs'`, `entity_kind='artist'|'label'`,
   `source='inference'`, `confidence` derived from the RRF/cosine score, `asserted_at=now()`), and
   never auto-promotes to `source='catalog'`.~~ **SUPERSEDED** (owner review, 2026-09-25): per ADR
   0014 sections 2-3 (`docs/adr/0014-cross-catalog-edition-candidates.md`, design `main`), a
   generator must **not** write candidates to `provider_aliases` as `source='inference'` --
   unreviewed candidates live in the `matching` schema instead (the `provider_aliases` partial
   unique index cannot hold a candidate set, and `catalog-api` reads do not filter on `source`),
   and only a human-reviewed promotion in `catalog-api` writes identity. The struck text above is
   left in place, not deleted, since it reflects this spike's own reasoning at submission time; the
   corrected design lives in ADR 0014, not here. Given the common-name-collision failure mode
   (recall@1 collapses to 19.7-48.9% for every method when a name collides in the pool), any such
   generator's output still belongs behind a confidence floor and/or human review before
   promotion, whichever schema it's staged in.
7. **Sizing the real prize, independent of the recall verdict**: 131,112 non-Latin MusicBrainz
   artists and 5,339 non-Latin MusicBrainz labels have no Discogs link today at all (2.6x and
   3.3x the number that are already linked). Whatever generator design follows from this spike,
   that unlinked population -- not the already-linked one this spike measured recall against --
   is where a working generator would actually add coverage.
8. **Ground truth sharing**: the construction method (source-of-truth relations, extraction
   scripts, script classifier) is posted as a comment on gm-design-zwy, along with this run's
   population counts, so that spike can reuse the same method if useful; per its own scope
   (release-edition matching, a different and harder identity problem), the two verdicts should
   still be read independently rather than combined.

## Appendix: reproducing this spike

Scripts live under `docs/spikes/gm-design-e0b.1/scripts/` (throwaway harness code, not product
code):

- `script_util.py` -- shared Unicode-script classifier (finer than chw.3's binary split).
- `extract_mb_nonlatin.py` -- streams a MusicBrainz JSON dump; tallies script/link status for
  every entity (source of the unlinked-non-Latin counts above) and emits ground-truth rows for
  non-Latin, Discogs-linked entities only.
- `extract_discogs_targets.py` -- unchanged from chw.3: streams a Discogs XML dump, keeps
  records matching a target-id set.
- `extract_discogs_pool.py` -- streams a Discogs XML dump, keeps every target plus a
  Bernoulli-sampled fraction of the rest, to build a realistic-scale (not 20k-capped) pool.
- `build_dataset.py` -- joins the two sides, computes match_class/name_frequency/script, and
  writes the final candidate pool and query set (no 20k cap; pool comes from
  `extract_discogs_pool.py`).
- `run_eval.py` -- loads `pg_trgm` (GiST-indexed) and embeds both sides with e5/bge, scores
  recall@1/10/50 per method via batched numpy matmul (not per-query SQL against pgvector).
- `analyze_results.py` -- unchanged from chw.3: slices results and prints the GO/NO-GO
  arithmetic.
- `hnsw_vs_exact.py` -- the HNSW-vs-exact side-check (see above): failed on the pgvector
  container's default `/dev/shm` limit before completing (needs `--shm-size` set); kept as-is,
  not re-run right now per the dispatcher. gm-analytics-engine-ieu.3's HNSW-vs-exact measurement
  (128-dim FastRP graph vectors) is a related data point but not a substitute for this spike's
  text-embedding vector space; that gap remains open.

No provider-derived data, embeddings, or model weights are committed. Raw dump downloads were
streamed straight from `curl`/`gunzip`/`tar` into the extraction scripts, never written to disk
as decompressed files. All intermediate JSONL datasets (MB ground truth, Discogs targets, the
realistic candidate pools, the query sets) and results, the Python venv, and the model cache
lived under a scratch directory outside this repository's working tree and were never staged;
nothing MusicBrainz- or Discogs-derived is present in this worktree.
