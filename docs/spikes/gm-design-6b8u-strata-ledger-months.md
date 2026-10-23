# Spike: concept D's ledger bar on real months, from the MusicBrainz full export

Status: **DEFER**, pending one binding check.

- **Proxy 1 fails its bar.** It was pre-registered at `9e9440a`, before any data was
  read. Its precision is 0.8223 against 0.90, because edits to older links date them into
  the window. So it is not used.
- **Proxy 2 clears every bar, but is not yet validated.** It was registered at `8f7a5ed`,
  after proxy 1 failed, and it has no free parameter. On 12 real months it clears G1, G2,
  and G3 by wide margins: 12 months, 35,434 works, and 35,467 re-attachments. Its
  validation on the same window passes (precision 0.9868, recall 0.9239), but that window
  is in-sample, so the result is only a diagnostic.
- **What decides it.** Proxy 2's binding validation is the unseen 20261021 → 20261024
  window, which can run once the 20261024 dumps are published. If it passes, the verdict
  is GO. If it fails, the verdict stays DEFER.

Spike: `gm-design-6b8u` (epic `gm-design-cgh9`)  
Prior spike: gm-design-loj9 (`docs/spikes/gm-design-loj9-strata-ledger.md` on the Strata
epic branch `wt/bead/epic/gm-design-uq8t`, merged at `3fdb051`). That spike holds the
definitions and the bar G1-G3, both used unchanged here.

## Question

gm-design-loj9 predicted concept D's history-only ledger from two MusicBrainz JSON dumps
4 days apart, and the result was DEFER. Its bar is G1 (two or more months with an
applying run that writes something), G2 (at least 1,000 works whose evented editions
change in two or more distinct months), and G3 (at least 1,000 release re-attachments).
What does the bar give when measured on real months instead?

## Method (fixed before reading data)

### Source

- MusicBrainz full export `20261021-002201`. `mbdump.tar.bz2` (7 GB) and
  `mbdump-derived.tar.bz2` (0.5 GB) are streamed, never written to disk.
- From the full export:
  - `l_release_url` rows of the `discogs` release-URL link type, kept when their URL
    parses as a Discogs release (the `musicbrainz-ingestion` rule, copied from loj9's
    `extract_mb.py`), each with its `last_updated`;
  - `release.gid` and the release group's `gid`;
  - `release_meta.date_added`.
- The two JSON-dump extracts gm-design-loj9 already made (`20261017-001001`,
  `20261021-001001`; release `mbid`, Discogs id, release group) are used for validation.
  The `20261021` release-group extract, and the Discogs `20261001` releases and masters
  (release → master), are used for work parents.

### The proxy

A release's **link time** L is the earliest `last_updated` over its current Discogs
links. Its **creation** C is `release_meta.date_added`. A NULL creation counts as before
every window.

MusicBrainz publishes dumps on Wednesdays and Saturdays at 00:10 UTC, and GrooveMap loads
each one. A release is first loaded at the first dump instant after C, written D(C). The
link is on the row at first load when L < D(C). Otherwise the release was loaded unlinked
and gained its link later, at D(L). That makes it a **re-attachment** at the first monthly
run after D(L). The run is modelled on the 1st of each month, UTC: the Discogs dump date,
after which catalog-api's automatic trigger runs once per extraction.

### Validation against the exact diff, and its bar

The window W is (2026-10-17 00:10:01, 2026-10-21 00:10:01] UTC, the instants of the two
JSON dumps.

- **Exact set E.** Releases present in JSON dump A with no Discogs id that carry one in
  dump B. gm-design-loj9's 522 "link added" re-attachments are the subset of E whose
  Discogs target is loaded. E itself holds 565.
- **Proxy set P.** Releases with C ≤ T_A whose L falls in W.
- **Precision** is |P ∩ E| / |P|. Its misses are links the proxy dates into the window
  but the diff does not add, such as an older link edited during the window.
- **Recall** is |P ∩ E| / |E|. Its misses are diff additions the proxy dates elsewhere,
  such as a link added in the window and edited after it, or a release whose C is wrong.

**Bar: precision ≥ 0.90 and recall ≥ 0.90.** A proxy that fails either is not used, and
the verdict stays DEFER. As a secondary check, reported but not barred, releases new in
dump B that carry a link (link at ingest) are compared with the proxy's C in W and
L ≤ T_B.

### Edits to a link

`last_updated` moves on any edit to the relationship, not only on creation. The core
tables cannot tell an edit from a creation. Only the edit history (`mbdump-edit`, 16 GB)
could, and it is not used. Edits are therefore bounded, not told apart:

- an older link edited inside a month pulls it into that month, which counts against
  precision;
- a new link edited in a later month pushes it out of its month, which counts against
  recall.

The window measures both rates on 4 days of real edits. The monthly figures are reported
raw, and are not corrected by those rates. That means no scaling. The window's error is
stated beside every monthly figure as the measured bound, under the assumption that edit
rates do not differ by month. The window cannot test that assumption.

Removed links are absent from the full export. Every month's count is therefore a lower
bound for links added then and later removed, and the shortfall grows with age.

### Monthly model, 12 runs

The modelled deployment does its first load in October 2025: Discogs `20251001`, then the
next MusicBrainz dump. Every release created before that load and linked by then is
linked at ingest in month 0. Then come 12 monthly runs, November 2025 to October 2026.
For each month the model reports:

- re-attachments: releases whose D(L) falls after their first load, assigned to the run
  that follows D(L);
- links at ingest of releases first loaded that month;
- G1: whether the run writes at least one supersession;
- G3: release re-attachments.

G2 uses gm-design-loj9's definition, over all 13 months. An edition's event months are
the months of its links at ingest and its re-attachment runs. Mints are left out, because
the full export does not say when a Discogs item was minted. That makes G2 a **lower
bound**. A second figure also counts the month the MusicBrainz item was minted, for a
re-attached release created after the first load.

### Known gaps, stated before the data

- **Discogs arrivals are not in the monthly series.** A link whose Discogs target missed
  that month's Discogs dump is a separate source of re-attachments. It needs the Discogs
  dump for every month, and only `20260901` and `20261001` are at hand. gm-design-loj9
  measured that rate for one cycle only (682). The monthly G3 here is therefore a lower
  bound.
- **Work parents are as of `20261021`.**
- **The verdict applies gm-design-loj9's bar unchanged.** If G2 misses it, the history
  shows no more than a log table, and D's first build is a table.

## Proxy 2, registered after proxy 1 failed and before it is computed

Proxy 1 failed in one way only: edits to older links. This section is committed before
proxy 2 is computed.

**Definition.** `l_release_url.id` is a sequence, so a row's id orders it by creation. An
edit changes `last_updated` but keeps the id, if MusicBrainz edits relationships in place.
Take every release-URL row k, of any link type. Its creation is bounded by c(k), the
minimum `last_updated` over rows j ≥ k. A row that was never edited has c(k) equal to its
true creation, because every later row was created after it. An edited row gets the
creation of the next unedited row, so the edit cannot push it later. Proxy 2's L is the
earliest c(k) over the release's current Discogs links. Everything else in the method is
unchanged: C, D(C), the runs, the monthly model, and G1-G3. Proxy 2 has no free
parameter. If MusicBrainz instead edits a relationship by deleting it and inserting a new
row, those edits look like new links, as they do under proxy 1, and the validation will
show it.

**Validation.** The bar is unchanged: precision ≥ 0.90 and recall ≥ 0.90.

- **Binding: the out-of-sample window.** Proxy 2 was designed after proxy 1's errors in
  the 20261017 → 20261021 window were seen. So its binding validation is the next window
  neither proxy has seen: JSON dumps 20261021 → 20261024, against the 20261024 full
  export.
- **Diagnostic only: the in-sample window.** Proxy 2 is also scored on the 20261017 →
  20261021 window, but that score cannot pass or fail it.

## Evidence

Everything below is **predicted from the MusicBrainz full export `20261021`**. It is
not recorded history. `results/months.json` holds every figure.

### Validation on 2026-10-17 00:10:01 → 2026-10-21 00:10:01 UTC

| | Proxy 1 (binding) | Proxy 2 (in-sample diagnostic) |
| --- | ---: | ---: |
| Exact diff additions (E) | 565 | 565 |
| Proxy-dated additions (P) | 647 | 529 |
| Both | 532 | 522 |
| **Precision** | **0.8223** ✗ | 0.9868 |
| **Recall** | 0.9416 | 0.9239 |
| False positives: the release was already linked in dump A (an older link, edited) | 115 | 7 |
| False negatives: no Discogs link in the full export | 33 | 33 |
| False negatives: link dated before the window | 0 | 10 |
| Secondary check: new releases linked at creation (exact / proxy / both) | 1,369 / 1,380 / 1,358 | the same |

How edits are told apart or bounded:

- **Proxy 1** cannot tell an edit from a creation. Its false positives are exactly the
  case the method predicted: 115 releases already linked in dump A whose link's
  `last_updated` moved during the window.
- **Proxy 2** dates a link by the creation bound of its row id, so an edit moves it only
  if MusicBrainz replaced the row. 7 such false positives remain. Its 10 new false
  negatives are links whose row ids are older than the window but which the diff adds,
  such as a link re-added by an edit that kept an old row.
- **The 33 links in the diff but absent from the full export** affect both proxies
  equally. They are links present in JSON `20261021` and missing from the
  `20261021-002201` full export. Removal or timing between the two exports is the likely
  cause, but the core tables cannot tell which.

### Proxy 2 on 12 real months (conditional on its binding validation)

The modelled first load is October 2025. The table gives each monthly run's release
re-attachments, links at ingest of new releases, and rows left `unresolved` because their
Discogs release is missing from `discogs_20260901`, the only full Discogs release list at
hand.

| Run month | Re-attachments (G3) | G1: the run writes | Linked at ingest | Unresolved (target not in the dump) |
| --- | ---: | :---: | ---: | ---: |
| 2025-11 | 2,508 | yes | 12,307 | 26 |
| 2025-12 | 2,975 | yes | 12,029 | 11 |
| 2026-01 | 2,980 | yes | 12,029 | 20 |
| 2026-02 | 2,892 | yes | 10,064 | 7 |
| 2026-03 | 2,559 | yes | 10,410 | 12 |
| 2026-04 | 2,764 | yes | 11,104 | 22 |
| 2026-05 | 3,418 | yes | 10,379 | 8 |
| 2026-06 | 3,292 | yes | 9,619 | 8 |
| 2026-07 | 2,522 | yes | 11,575 | 17 |
| 2026-08 | 3,287 | yes | 10,958 | 5 |
| 2026-09 | 3,159 | yes | 11,756 | 502 |
| 2026-10 | 3,111 | yes | 7,169 | 599 |
| **12 runs** | **35,467** | **12 of 12** | 129,399 | 1,237 |

The first load (2025-10) links 1,715,875 releases at ingest. 2,482 links appear after the
October 2026 run and fall to the November run.

The September and October 2026 unresolved counts are high only because the target list is
`discogs_20260901`. That list cannot contain Discogs releases created during September,
so for those two months the re-attachment and ingest counts are lower bounds.

| Bar (gm-design-loj9, unchanged) | Figure | Bar | |
| --- | ---: | ---: | --- |
| G1: months with a writing run | 12 | ≥ 2 | clears |
| G2 lower bound: works with ≥ 2 evented editions whose events span ≥ 2 months, MusicBrainz mints excluded | **35,434** | ≥ 1,000 | clears |
| G2 counting MusicBrainz mint months | 35,548 | ≥ 1,000 | clears |
| G2 counting only events after the first load (extra check) | 5,980 | ≥ 1,000 | clears |
| G3: release re-attachments over 12 runs | 35,467 | ≥ 1,000 | clears |

- **Works.** 1,927,335 works have evented editions, and 259,329 have two or more.
  Evented editions per work: 50th percentile 1, 90th 2, 99th 5, maximum 200.
- **Edition parents.** Of the 1,863,889 editions with events, 562,721 have two or more
  work parents. That matches gm-design-loj9's link-structure finding.
- **Where parents come from.** Discogs master parents come from `discogs_20260901`, the
  release-to-master list at hand. MusicBrainz parents come from the `20261021`
  release-group extract.

**No four-day rate is scaled.** Every monthly figure counts links the full export dates
into that month, under the edit bound above. Links added in a month and removed later are
missing, so older months are lower bounds.

## Verdict

**DEFER.** Proxy 1, the one registered before any data was read, failed its bar, so it is
not used.

Proxy 2 clears G1, G2, and G3 by wide margins on 12 real months. G2 is 35 times its bar
at the lower bound, and 6 times its bar when the first load is left out. But proxy 2 was
designed after proxy 1's errors were seen, so its only validation so far is in-sample.
The pre-registered rule makes the unseen 20261021 → 20261024 window binding:

- if proxy 2 passes it (precision ≥ 0.90 and recall ≥ 0.90), the verdict is **GO** for the
  history-only ledger;
- if it fails, the verdict stays **DEFER**.

For gm-design-loj9: its four-day replay found G2 = 743. That figure measured one
hypothetical cycle, not a shortage of history. On real months the history shows change
across months for tens of thousands of works.

## Recommendation

1. **Run proxy 2's binding validation once the 20261024 dumps are out.** The full export
   is expected around 05:00 UTC on 2026-10-24, and the JSON `release` member around 15:00
   UTC. It needs about 30 GB streamed and about an hour, with no code change. The
   README gives the commands. Then commit `results/oos_validation.json` and set the
   verdict by the rule above. The JSON dumps that window needs are deleted within a week,
   so it has to run soon after they appear.
2. **If it passes, the decision bead `gm-design-7xo5` takes concept D as GO** for a
   history-only ledger. Use the shape gm-design-loj9 drafted: the PostgreSQL route, the
   state vocabulary, `work_disagreement` with a primary parent, and no lateral identifier
   edges.
3. **If it fails, D's first build waits.** It is not a table yet, because neither proxy
   would then have shown that the history is too sparse. Re-measure once a GrooveMap
   catalog exists.

## Missing evidence and failure modes

- **One validation window.** Both proxies are scored on 4 days of real edits. The
  out-of-sample window is a second 3 days.
- **Row-id order is assumed to be creation order.** Proxy 2 relies on MusicBrainz
  assigning `l_release_url` ids from a sequence. Its precision on the window is
  consistent with that assumption.
- **Links removed since they were added** are missing, so older months are undercounted.
- **Discogs arrivals are not modelled.** A row whose Discogs target missed a dump is
  re-attached when the target arrives. That would add re-attachments, so G3 is a lower
  bound.
- **Work parents are current.** Discogs masters come from `discogs_20260901`, and
  MusicBrainz release groups from `20261021`.
- **The first-load month is a modelling choice.** October 2025 gives exactly 12 runs.

No catalog id, user data, or audit row is committed. No product code changed, and no
bead was filed.

## Corrections to gm-design-loj9

gm-design-loj9 is merged and its document cannot change, so two corrections are recorded
here.

### 1. G1 and G2 from its two-cycle replay are DEFER, not "holds"

gm-design-loj9's verdict table reported G1 as "holds" (2 runs, R2 writing 2,206) and G2
as 743. Both rest on two **hypothetical** cycles: Discogs dumps a month apart, paired
with MusicBrainz dumps 4 days apart. G1 and G2 are statements about distinct real months,
so on that evidence both are **DEFER**, and neither holds nor fails. G3 (1,204 release
re-attachments in one cycle) does not depend on the calendar, and it cleared its bar per
cycle. This spike's month figures above replace both, subject to proxy 2's binding
validation.

### 2. Its link-structure numbers are predecessor-schema measurements

gm-design-loj9's `results/link_structure.json` was measured on the predecessor system's
catalog database, with read-only queries. The maintainer has since
approved those queries. That schema is an earlier version of GrooveMap's, so every figure
in loj9's section 5 is a **predecessor-schema measurement**.

A read-only check (`gm-design-6b8u/sql/predecessor_schema.sql`, run 2026-10-23 UTC)
compared the four tables the query reads with `database-schema` at `817081d`:

| Table | Columns the query reads | Same in both | Only in database-schema | Only in the predecessor | Affects the query? |
| --- | --- | --- | --- | --- | --- |
| `musicbrainz.releases` | `discogs_release_id`, `release_group_mbid` | `mbid` UUID, `discogs_release_id` BIGINT, `release_group_mbid` UUID, `data` JSONB | `gm_item_id`, `media`, and their indexes | nothing | No |
| `musicbrainz.release_groups` | `mbid`, `discogs_master_id` | `discogs_master_id` BIGINT | `gm_item_id` and its index | nothing | No |
| `public.releases` | `data_id`, `data ->> 'master_id'` | `data_id` VARCHAR, `data` JSONB | `gm_item_id`, `media`, and their indexes | title, year, country, genres, labels, and full-text indexes | No. In a 1% sample (195,850 rows), `master_id` is a JSON string in every row, as database-schema's `derived_from` reads it |
| `public.masters` | `data_id` | `data_id` VARCHAR | `gm_item_id` and its index | title, year, and full-text indexes | No |

What else differs, and whether it affects the numbers:

- **The Discogs-id rule.** The predecessor's extractor, its repository at `3a49d2c`
  (`extractor/src/jsonl_parser.rs`) lines 33-39 and 130-142, applies the same rule as
  `musicbrainz-ingestion` `6c6c284` (lines 45-51 and 216-228): the first `discogs` URL
  relation, then the id before the first `-`, parsed as `i64`. `release_group_mbid` comes
  from `release-group.id` in both (line 235 there).
- **Snapshot dates.** The predecessor's Discogs tables hold `discogs_20261001`, last
  written on 2026-10-03, with release and master counts equal to that dump's. Its
  MusicBrainz tables were last written on 2026-10-13, so they hold a MusicBrainz dump
  from about 2026-10-10. gm-design-loj9's replay used MusicBrainz `20261017` and
  `20261021`. The figures differ slightly for that reason, for example two work parents
  for 566,661 editions there against 564,667 in loj9's replay.
- **Identity tables.** The predecessor has no native-identity tables. That is why
  link-structure figures are all it can give: links, not history.

## Sources

- gm-design-loj9: definitions, the bar G1-G3, and the harness this copies (epic branch
  `wt/bead/epic/gm-design-uq8t`, `docs/spikes/gm-design-loj9/`)
- MusicBrainz full export `20261021-002201` and JSON dumps `20261017-001001` and
  `20261021-001001`: [data.metabrainz.org](https://data.metabrainz.org/pub/musicbrainz/data/)
- Discogs `discogs_20260901` releases and `discogs_20261001` masters, as extracted for
  gm-design-loj9
- Harness: [gm-design-6b8u/](gm-design-6b8u/README.md)
