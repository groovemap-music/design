# Spike: concept D's ledger bar on real months, from the MusicBrainz full export

Status: **pre-registered**. This commit fixes the method, the proxy's validation bar, and
the monthly model before any of the data is read. The evidence and the verdict follow in
later commits.  
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
  dump B. Per gm-design-loj9, E holds 522 releases.
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
