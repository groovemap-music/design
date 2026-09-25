# Spike: deterministic edition candidates on newly linked releases

Status: **DEFER**. The four-day holdout is too small to settle ADR 0014 section 6.
Re-run the harness on the `20260919` to `20261014` split with the Discogs `20261001`
pool.  
Evidence date: 2026-09-25  
Spike: `gm-design-1wd.1` (epic `gm-design-1wd`)  
Harness: [gm-design-1wd.1/](gm-design-1wd.1/README.md)  
Related: [ADR 0014](../adr/0014-cross-catalog-edition-candidates.md),
[gm-design-zwy](gm-design-zwy-semantica-identity-matching.md)

## Question

ADR 0014 section 6 blocks every part of the edition matcher until its candidate quality
is measured on MusicBrainz releases that have no Discogs link, with the review
threshold recalibrated on that measurement. The program stops at ADR 0014 "if the
review queue cannot be held near the spike's bar of three candidates per query at a
precision a reviewer can sustain."

The zwy numbers are an upper bound: they come from releases editors had already
linked, whose fields were often copied from Discogs. This spike re-runs zwy's
deterministic baseline, unchanged, on the closest honest proxy for the unlinked
population: releases that were unlinked in one MusicBrainz dump and gained a Discogs
link by the next.

## Method

### The time-split

| | |
| --- | --- |
| Earlier snapshot | `json-dumps/20260919-001001/release.tar.xz`, streamed whole: 5,786,985 releases |
| Later snapshot | `json-dumps/20260923-001002/release.tar.xz`, streamed whole: 5,797,718 releases |
| Newer dumps | None. On 2026-09-25 the json-dumps index lists only these two |
| Candidate pool | `discogs_20260901_releases.xml.gz`, streamed whole (19,417,067 releases, 62.4 GB decompressed), plus the masters dump from the shared cache |

**Newly linked** means that the release exists in both snapshots, carries no
`discogs.com/release/` relation in 0919, and carries at least one in 0923. The query is
the **0919 record**, which is what a matcher would have seen while the release was
unlinked. The 0923 relation is the held-out label. The 0923 record is used only for the
edit census below.

| Population | Count |
| --- | ---: |
| Releases in 0919 | 5,786,985 |
| Linked to a Discogs release in 0919 | 1,875,371 |
| **Unlinked in 0919** (the matcher's population) | **3,911,614** |
| Unlinked in 0919 and gained a Discogs release link by 0923 | **414** |
| Excluded: gained more than one link (no single correct edition) | 6 |
| **Eligible queries** | **408** (dev 90, test 318) |
| Excluded from the population: linked in 0923 but absent from 0919 (created between the dumps) | 1,501 |
| Unlinked in 0919 and gone by 0923 (deleted or merged) | 139 |
| Linked in 0919 and unlinked or gone by 0923 | 33 |
| Newly linked releases that had a Discogs master link in 0919 | 0 |
| Targets shared by two queries | 0 |
| **Targets absent from the Discogs 20260901 dump** | 16 of 408 (dev 3, test 13) |

The net increase in linked releases between the dumps (1,882) is mostly releases
**created** between them and linked at creation. They were never unlinked releases a
matcher could serve, and they are the releases most likely to have been imported from
Discogs, so they are excluded by design rather than counted.

Dev and test are split 1 in 5 by a SHA-256 hash of the MBID. No query was sampled
away. Headline metrics are reported twice: on all queries (missing targets count as
misses, as in zwy) and on the **reachable** queries whose target is in the 0901 dump.
The reachable basis is the fairer one, because a production matcher would run against a
current Discogs dump. zwy lost only 33 of 10,000 targets that way, so its reachable
figures differ from its published ones by at most 0.3 points.

### The matcher, unchanged

zwy's normalization, kind-aware keyed blocking (barcode, catalogue number, and title with
artist), stop-key limit, and additive score are copied unchanged. `tests/test_matching.py`
pins the scores. The pool is built the same way: every Discogs release in the full
19.4M corpus that shares a barcode, catalogue-number, or title key with any query,
plus the targets and those releases' masters. That comes to 74,410 releases and 10,212
masters. zwy's 1% background sample is dropped, because the keyed baseline never
reaches an unkeyed record.

### No tie-breaks

zwy ranked equal scores by Discogs id, and the linked target is the lowest id in 87% to
91% of zwy's tie groups. Here the runner writes each query's candidates as an unordered
set with their score and ADR 0014 section 4 comparison vector, and every metric is a
function of score groups:

- **Unique-top R@1:** the target is the only candidate at the top score.
- **Expected R@k:** the target's chance of being in the first *k* under a uniformly
  random order within its score group. This is what any tie-break unrelated to the
  edition would score on average.
- **Guaranteed R@k:** the target is in the first *k* under every order.

`test_no_tie_is_broken_by_id_or_insertion_order` asserts that neither swapping which
tied candidate holds the lower id nor shuffling candidate order changes any metric.
The id-order figures appear only as a labelled diagnostic, so they can be set against
zwy's published numbers.

### Ambiguity under ADR 0014 section 4

Section 4 defines an ambiguous group by field equality, not by score. Two candidates
are in one group when their **comparison vectors** are equal, meaning they agree with
the query at the same level on barcode, label and catalogue number, title key, artist,
year, format family, and country, as far as the query carries each field. A stricter
variant also requires equal normalized **values** on every field the query carries.
The test suite pins that equal scores with different evidence do not form a group.

### Threshold and intervals

zwy's rule is applied to this population's dev split: choose the lowest integer score
whose dev mean queue is at most 3.0, then apply it to test unchanged. Dev picked
**score ≥ 8** (dev mean 2.34). Score ≥ 7 gave 5.82. The intervals are 95%: Wilson for
per-query rates, and a seeded percentile bootstrap over queries (2,000 resamples) for
the queue mean and queue precision. Queue members cluster by query, so a Wilson
interval on members would be too narrow.

## Evidence

All figures are for the **test split** unless marked. Intervals are on the reachable
queries (n = 305).

### Against zwy

| Metric | zwy (linked, 10k) | This spike: all (n = 318) | This spike: reachable (n = 305) | 95% interval (reachable) |
| --- | ---: | ---: | ---: | --- |
| Coverage | 97.33% | 85.85% | **89.51%** | 85.6–92.5 |
| R@1, id-order tie-break (diagnostic) | 77.14% | — | 75.41% | — |
| R@1, expected under random tie order | not reported | 73.27% | **76.39%** | 71.3–80.8 |
| R@1, unique top | 69.40% | 67.92% | **70.82%** | 65.5–75.6 |
| Top-group recall (target at the top score) | 90.73% | 81.76% | 85.25% | — |
| R@5, expected / guaranteed | 95.34% (id-order) | 84.30% / 83.02% | 87.89% / 86.56% | guaranteed 82.3–89.9 |
| R@10, expected / guaranteed | 96.81% (id-order) | 85.43% / 84.28% | 89.07% / 87.87% | expected 85.1–92.1 |
| Unique-top precision (the unique top is the target) | not reported | 92.70% (216/233) | 93.51% (216/231) | 89.6–96.0 |
| Candidates per query, mean / median / p95 | 21.8 / 5 / 83 | 13.7 / 2 / 66 | — | — |
| Queries with no candidate | 165 (1.65%) | 33 (10.4%) | — | — |
| Top score tied | 23.63% | 16.35% (52) | — | 12.7–20.8 (all) |
| Target inside a tied top | 13.59% | 13.84% (44) | — | — |
| Target is the lowest id in its tie group (diagnostic) | 87–91% | 45.5% (20/44) | — | 31.7–59.9 |

**Review queue at the dev-chosen threshold.** zwy chose 10 on its dev split, and dev
chose 8 here.

| Operating point | Queue mean / median / p95 | Queue precision | Target in queue | Groups per query (section 4) | Group precision | FP per query |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| zwy, `score ≥ 10` (its choice) | 2.54 / 1 / 8 | 35.2% | 89.25% | — | — | 1.65 |
| zwy, `score ≥ 8` | 5.87 / 2 / 22 | 16.5% | 96.59% | — | — | 4.91 |
| **This spike, `score ≥ 8` (dev choice)** | **2.74 / 1 / 10** | **26.9%** | **73.58%** | **1.38** | **53.2%** | 2.00 |
| 95% interval | mean 2.13–3.43 | 22.4–35.7 | 68.5–78.1 (all) | | | |
| This spike, `score ≥ 10` (zwy's threshold) | 1.18 / 0 / 4 | 40.5% | 47.80% | 0.75 | 63.6% | 0.70 |
| This spike, `score ≥ 7` | 6.33 / 2 / 27 | 12.5% | 79.25% | 1.89 | 42.0% | — |
| Dev, `score ≥ 8` | 2.34 / 1 / 10 | 33.2% | 77.78% | 1.26 | 62.0% | 1.57 |

Confusion at `score ≥ 8` on test: the unique top is correct on 195 queries, the target
is in a tied top on 32, it is in the queue below the top on 7, the queue holds only
wrong candidates on 14, and the queue is empty on 70.

**Ambiguity (ADR 0014 section 4), test.** These rates are over the 285 queries with at
least one candidate.

| | Comparison vector (section 4) | Strict (equal values too) |
| --- | ---: | ---: |
| Leading group is ambiguous (two or more indistinguishable members at the top) | **17.89%** (51), 13.9–22.8 | 13.68% (39), 10.2–18.2 |
| Target sits in an ambiguous top group (share of all 318) | 12.58% (40), 9.4–16.7 | 10.06% (32) |
| Share of queue groups at `score ≥ 8` that are set-valued | 25.91% | — |

zwy did not report section 4 ambiguity; its closest figure is the 23.63% score-tie rate.
Here, 51 of the 52 tied tops are genuinely indistinguishable on the compared fields.
Ties at the top are therefore almost all field-equal pressings rather than
coincidences of the additive score.

### Copy bias

**Field agreement** is measured between the query (the 0919 record) and its target,
where both carry the field. The zwy column uses zwy's definitions.

| Field | zwy (linked) | This spike (test) | 95% interval |
| --- | ---: | ---: | --- |
| Barcode | 91.6% (5,513/6,018) | **95.65%** (110/115) | 90.2–98.1 |
| Catalogue-number key | 92.5% | 81.65% (129/158) | 74.9–86.9 |
| Title key | 85.7% | 83.28% (254/305) | 78.7–87.0 |
| Year | 94.0% | 86.56% (219/253) | 81.8–90.2 |
| Country | 89.6% | 75.85% (179/236) | 70.0–80.9 |
| Format family | not reported | 95.51% (234/245) | |
| Artist key | not reported | 95.74% (292/305) | |

**Edit census.** This counts what editors changed on the 408 query releases between
0919 and 0923, meaning while they added the link:

| Field | Added | Changed | Removed | Releases touched |
| --- | ---: | ---: | ---: | ---: |
| Catalogue number | 107 | 7 | 0 | **27.9%** |
| Format family | 56 | 4 | 0 | 14.7% |
| Barcode | 47 | 3 | 0 | **12.3%** |
| Year | 40 | 2 | 0 | 10.3% |
| Country | 36 | 3 | 1 | 9.8% |
| Title key | 0 | 5 | 0 | 1.2% |

What this shows:

- **Identifiers are added at link time.** More than a quarter of these releases gained a
  catalogue number, and one in eight gained a barcode, in the same window as the link.
  Those values were most likely copied from the Discogs release being linked. Measuring
  on the post-link record would have handed the matcher its answer; the time-split's
  earlier record withholds it.
- **The queries are thin.** Only 47.2% of test queries carry a barcode and 51.6% a
  catalogue number, against zwy's 60.7% and 94.7%. That, not a changed score, is why
  the threshold moved from 10 to 8. It is also why 10.4% of queries produce no
  candidate at all.
- **Residual copy bias remains wherever an identifier is present.** Barcode agreement is
  95.65%, no lower than zwy's 91.6%. The descriptors are less copied: country agrees
  13.8 points less often and year 7.4 points less. Those descriptors are the fields
  that separate pressings.

### Per-slice view (test)

| Slice | n | Coverage | Unique-top R@1 | Expected R@1 | Expected R@10 | zwy R@1 / R@10 (id-order) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Barcode on query | 150 | 91.33% | 78.00% | 82.40% | 91.33% | 80.56% / 98.90% |
| No barcode on query | 168 | 80.95% | 58.93% | 65.11% | 80.16% | 71.85% / 93.59% |
| Catalogue number on query | 164 | 93.29% | 80.49% | 84.66% | 93.29% | 78.15% / 98.09% |
| No catalogue number on query | 154 | 77.92% | 54.55% | 61.13% | 77.06% | 59.13% / 74.01% |
| CD | 180 | 93.33% | 78.33% | 83.16% | 93.13% | — |
| Digital | 54 | 74.07% | 66.67% | 69.14% | 74.07% | — |
| No format | 61 | 73.77% | 37.70% | 47.70% | 72.18% | — |
| Vinyl | 15 (thin) | 86.67% | 66.67% | 72.50% | 86.67% | — |
| Release year 2020s | 38 | 68.42% | 63.16% | 64.47% | 68.42% | — |
| No release date | 49 | 81.63% | 55.10% | 64.00% | 80.82% | — |
| Non-Latin title | 11 (thin) | 90.91% | 90.91% | 90.91% | 90.91% | 81.80% / 96.70% (extra slice) |
| Dev split | 90 | 91.11% | 70.00% | 74.92% | 88.94% | 76.70% / 97.00% |

Of the 13 test targets missing from the Discogs 0901 dump, 11 belong to 2020s releases.
Recent Discogs submissions are exactly what a 0901 pool cannot hold.

**Hard negatives, test.** These count queries where a class member outranks the target,
ties it, or sits in the top group.

| Class | Queries with class in pool | Outranks target | Ties target | In top group |
| --- | ---: | ---: | ---: | ---: |
| Same master, same format (another pressing) | 132 | 16 | 45 | 52 |
| Same master, different format | 124 | 4 | 18 | 17 |
| Shared barcode | 53 | 2 | 22 | 20 |
| Near-identical title, different master | 122 | 0 | 3 | 2 |
| Namesake artist | 1 | 0 | 0 | 0 |

As in zwy, the edition problem is same-master pressings. They almost never outrank the
target; they tie it.

### Examples (no ids)

On 18 test queries, the release gained a catalogue number between the snapshots
while its 0919 record left the target in a field-equal top tie. Two of them:

1. **A catalogue number added with the link.** A 2005 CD has title, artist, year,
   format, and country in 0919, with no barcode and no catalogue number. The target ties
   one other Discogs release at score 8, and both match on title, artist, format, and
   country and differ from the query's year. Being equal on every compared field makes
   them a section 4 ambiguous group. The 0923 record gained the target's
   catalogue number, which would make the target a unique top at 12.
2. **Title and artist only.** A release with no format, date, barcode, or catalogue
   number in 0919 ties 13 same-titled Discogs releases at score 6, below the
   `score ≥ 8` queue, so its correct edition is never proposed. Its 0923 record, with
   identifiers added alongside the link, would score the target 21.

## Verdict: DEFER

ADR 0014 section 6 asks whether the review queue can be held **near three candidates
per query at a precision a reviewer can sustain**. On this sample:

| Part of the bar | Result | Reading |
| --- | --- | --- |
| Queue held near 3 | Yes. **2.74** per query at dev-chosen `score ≥ 8` (95% 2.13–3.43; median 1, p95 10). Counted in section 4 groups, it is 1.38 per query. | Met on the point estimate. The upper bound of 3.43 is a **near-miss** above the bar, flagged rather than rounded. |
| Precision a reviewer can sustain | **26.9%** of queue members are correct (95% 22.4–35.7), against zwy's 35.2%. By group it is 53.2%. | ADR 0014 sets no numeric precision bar. zwy's 35.2%, which the ADR already calls "not small", is inside the interval only at its top edge (35.7). That makes it a **near-miss** of the linked-population figure, not a match. |
| Correct edition reaches the queue | **73.6%** (68.5–78.1), against zwy's 89.3% at its threshold | A quarter of the correct editions never enter the queue. At zwy's own threshold of 10, only 47.8% would. |
| Coverage | **89.5%** reachable (85.6–92.5), against zwy's 97.3% | Clearly worse. The interval excludes zwy, and the cause is thin queries, not the pool. |
| Unique-top R@1 | **70.8%** (65.5–75.6), against zwy's 69.4% | Not distinguishable from zwy. |
| Ambiguity (section 4) | 17.9% of queries have an indistinguishable leading group (13.9–22.8) | These can only ever be resolved with outside evidence. |

Why DEFER rather than GO or NO-GO:

1. **The sample is too small for the threshold, which is the thing section 6 asks to
   recalibrate.** Dev has 87 reachable queries. The rule lands on 8, where the queue is
   2.34 on dev, and one point lower gives 5.82. The test interval on precision spans 13
   points (22.4–35.7), which covers both "worse than zwy" and "as good as zwy".
2. **The population is four days of edits.** That is 408 releases out of 3.9 million
   unlinked, about 100 a day. The JSON dumps carry no editor information, so a single
   editor's batch dominating the window can be neither ruled out nor measured.
3. **The pool is older than both snapshots.** 4.1% of test targets (mostly 2020s
   releases) are absent from Discogs 0901. A 20261001 pool removes that artifact.

The direction is already informative, and the decision bead should read it: queue size
is not the problem, but precision and coverage on releases nobody has linked are below
the linked upper bound, and the gap comes from missing identifiers on the MusicBrainz
side.

## Recommendation

1. **Re-run this harness on a wider split, with no code changes.** At about 100
   eligible releases a day (408 in four days), the sample needs about **2,500 eligible**
   (roughly 500 dev and 2,000 test). That narrows the precision interval to about ±3
   points and puts about 450 reachable queries behind the threshold choice. Use the
   `20260919-001001` snapshot as the earlier dump and the **`20261014`** dump (25 days,
   about 2,500 expected) as the later one. MusicBrainz publishes JSON dumps on
   Wednesdays and Saturdays, so the 20261010 dump (about 2,100) is the earliest usable
   one. Build the pool from **`discogs_20261001`** so September's Discogs submissions are
   reachable. The README gives the exact commands, and the run takes about 1.5 hours of
   wall time on this host.
2. **Fix the precision bar before re-running.** ADR 0014 section 6 says "a precision a
   reviewer can sustain" but gives no number. The re-run can only settle GO or NO-GO
   against a stated bar: a member precision (zwy measured 35.2%), a group precision, or
   a reviewer-minutes budget per accepted edition. That is for the decision bead
   `gm-design-1wd.2`, not this spike.
3. **Report queues in section 4 groups.** Counted as groups, the queue is half the
   member count (1.38 against 2.74) at twice the precision (53.2% against 26.9%). That is
   what a reviewer would actually face under ADR 0014's set-valued candidates.
4. **Expect the threshold to move down, and the queue to lose correct editions.** On
   unlinked releases the scores are lower because identifiers are missing, so zwy's
   `score ≥ 10` would admit fewer than half of the correct editions. Any build should
   take its threshold from the wider split, never from zwy.

## Missing evidence and failure modes

- **Sample size.** There are 318 test and 90 dev queries. Every interval is wide, and
  slices under 50 (vinyl, non-Latin, decades before the 1990s) are not rates.
- **Proxy bias.** Newly linked releases are the ones an editor chose to link in a
  four-day window, which favours releases that are easy to find on Discogs. The truly
  unlinked population is probably harder. These numbers are still an upper bound, only
  a lower one than zwy's.
- **Residual copy bias.** Barcode agreement is 95.65% where both sides carry one.
  Entries created by copying from Discogs before 0919 still look copied.
- **Pool date.** 16 of 408 targets are missing from the 0901 dump. They are reported on
  both bases.
- **Editor concentration** cannot be checked from the JSON dumps.
- **The first Discogs pass was truncated** by a dropped download (1.8M of 19.4M
  releases). lxml's `recover=True` parsed it as a clean, short pool. The extractor now
  fails unless the raw stream ends in `</releases>`, and the stream script retries the
  whole stream. The reported pool is the complete second pass: 19,417,067 releases, and
  every pipe stage exited 0.
- **Not repeated from zwy:** the Semantica runs (already NO-GO), field ablations, and the
  bounded-pool runs. Only the deterministic baseline was in scope.

No MusicBrainz or Discogs data, ids, pairs, or id-linked scores are committed. The
`results/` files hold counts and rates only. No product code was changed, and no bead
was filed.

## Sources

- MusicBrainz JSON dumps: [data.metabrainz.org json-dumps](https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/)
  (`20260919-001001`, `20260923-001002`)
- Discogs data dumps: [data.discogs.com](https://data.discogs.com/) (`discogs_20260901_releases.xml.gz`,
  `discogs_20260901_masters.xml.gz`)
- [ADR 0014](../adr/0014-cross-catalog-edition-candidates.md), sections 4 and 6
- Prior spike: [gm-design-zwy](gm-design-zwy-semantica-identity-matching.md) and its
  [harness](gm-design-zwy/README.md)
- Harness and aggregate results: [gm-design-1wd.1/](gm-design-1wd.1/README.md)
