# Performance roadmap — 2026-11-09

Bead `gm-design-t5n9`. This rolls the 2026-11-04 query performance audit into one ranked list across repositories.
It reads the audit beads (label `perf-audit`) in `deployment`, `catalog-api`, `database-schema`, `analytics-engine`,
`discogs-sql-loader`, `musicbrainz-sql-loader`, `discogs-graph-enricher`, `musicbrainz-graph-enricher` and
`python-libraries`; the `deployment` baseline of 2026-11-07; and what was landed and measured on the reference host
on 2026-11-08 and 2026-11-09. It proposes work and targets. It changes no code, setting or data.

## How to read the evidence

| Tag | Meaning |
| --- | --- |
| **measured** | Taken on the reference host against the full catalog (Discogs 20261101, MusicBrainz 20261104-001002). |
| **statement stats** | Read from `pg_stat_statements` on 2026-11-09. Cumulative since the extension was created; calls cannot be split by code version. |
| **synthetic** | Taken on a disposable database with generated rows. Ratios hold, absolute times do not. |
| **estimate** | Extrapolated or reasoned, not run. Every estimate is marked. |

Two limits apply to the whole document:

1. **No route p95 exists.** The baseline could not run the API journeys, so every route figure below is a query or
   statement time, not a route percentile. Item 4 closes this and is the gate for the route targets.
2. **Reference-host counters are young.** The server restarted on 2026-11-07 (about 20:54 UTC), so index-scan counters
   cover roughly 1.5 days, most of it load and measurement, not read traffic.

## What has landed and been measured

| Change (bead) | Before | After | Tag |
| --- | --- | --- | --- |
| Ledger works window, per-day rollup (`catalog-api` tn5r, `database-schema` 9dcd, nbvh) | 2.73 s for the 2026-11 window; budget 2 s | 0.28 s; rollup filled, 4.1M rows | measured |
| `credited_on` DISTINCT release-id estimate (`database-schema` bynr, 50jj) | 1.93M planned vs 9.71M actual, 1.04 GB temp | 10.41M planned; `track_credited_on` 561k to 6.78M | measured (estimate); the spill itself was not re-run |
| Master search ranked from `master_search` (nu0c, 2jka) | `love` 140 ms | 39 ms | measured |
| Search facets and filters from `release_search` (1sle, 4asm) | facets 3 to 5x slower; filtered `love` + Jazz + 1970 + vinyl 10.4 s | 0.67 s | measured; 4asm is under review |
| Release search rewrite and no-sort totals (6tjq, onma, ysh9, fi4a) | route `love` 8.79 s at 20% of the data, about 43 s extrapolated | audit rewrite 0.98 s; the baseline's release branch alone was still 4.3 s warm and 12.8 s first, before the search vector landed | audit: synthetic and measured; no route re-measure yet |
| Neighbour ranking for `/api/network/cluster` (575h) | 29.6 s, 37.5M hits (Bowie) | 79 ms, 290,786 hits | measured |
| Label similar candidates (j4ml) | 54.7M hits, 28.3 s | 743,731 hits, 0.4 s; label DNA 30% fewer hits, bead asked 40% | measured; DNA target missed |
| `credit_role_category` per row (uz24) | 110 µs per call | plpgsql twin about 76x faster | audit synthetic |
| Credit hash key, drop `person_name` hash indexes (bfuh) | 42.4 s per 1M rows | 31.9 s (-24%); 30.6 GB to 14.7 GB (-52%) | synthetic (track key an estimate) |
| Credit edge queries in the embedding load (wf4h, 50jj) | 25.9 s for 14.6M rows (partial) | 64 s for 57.9M and 51 s for 90.0M rows, no temp | measured |
| Incremental ledger refresh (xen5) | 45 s for 4 rows, 3 to 6 min estimated at scale | steady-state time not yet measured; see item 4 | open measurement |
| Neo4j timeouts, bounded collaborators and explore, genre-tree and node reads (jpyk, p85n, zazs, somq, vus1, 88cu, i6l1) | collaborators 15.2M hits, 6.1 s; `/api/node` Rock 39.8 s, 112M hits; graph stats 34.9M hits | bounded; node and stats from stored values (audit: 3 hits, 8 ms and 6 hits, 1 ms) | audit; not re-timed since |
| Rarity fill and API memory (usmt, jlyv, tz5x, lh7b, vvb6, a8xk) | rarity table never filled; API process held 23 GB | table filled page by page; memory bounded | closed; see each bead for runs |
| Write path: set-based graph rows, hashed relationship key, round trips (n15x, ymm9, pf94, 1twk, u2qf, 943) | Discogs about 2M releases an hour, about 10 h (audit estimate from a partial load) | audit synthetic: 5.6x for credit function, set-based writes and batch size together | synthetic; no full-load re-measure |

## Ranked roadmap

Ranking weighs user-visible latency, load or maintenance duration, operational risk (timeouts, stalls, disk), and effort.
Items 1 to 5 are the proposed order. "Bead" is the existing bead, or a proposed one marked **new**.

| Rank | Item | Evidence | Expected gain | Effort | Risk | Bead |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | **Stop reloads rewriting unchanged rows.** Seen list in shadow mode, schema table first. | A reload touches `updated_at` on every unchanged row: 196 µs and 6.5 KB WAL per row, 0 HOT, about 35M rows a month. **Estimate:** about 64 min and 127 GB of WAL for `releases` alone per reload. | Monthly reload writes close to nothing for unchanged rows; target in the next section. | L | Medium: purge logic changes. Shadow mode compares the old and new purge sets before anything switches; a crash may leave a month of stale rows by operator decision. | `database-schema` uw6d (in progress), then `discogs-sql-loader` g77f |
| 2 | **MusicBrainz write path.** Finish the child-row design, and replace the per-record `issued_on` delete. | Statement stats, `groovemap` database: `DELETE FROM graph.issued_on WHERE release_id AND source` is the top statement by total time, 1.90M calls, 5,846 s, 3.1 ms each. `INSERT musicbrainz.relationships` is second, 33.7M calls, 5,618 s. A rerun of 2,000 unchanged records still does 28,055 relationship updates (synthetic). **Not known:** whether that load ran with the round-trip cut (u2qf). | **Estimate:** the two statements are about 3.2 h of server time per full MusicBrainz load; unchanged reloads should approach zero. | L | Medium: 3osm is on operator hold (option C, one marker write per row per extraction) until a per-record child replace is designed. | 3osm (in progress); **new** bead for the `issued_on` delete in `musicbrainz-sql-loader` |
| 3 | **Precompute genre and style trends.** | Trends for Rock: 20.7M hits, 3.8 s with a warm page cache, 17.5 s on first touch (measured). Label 1818: 2.29M hits, 0.9 s. Cached in Valkey, so the cost is every first visit and every evicted key. Explore for genres and labels dropped from about 200M hits to 3 the same way. | First-visit trends in tens of milliseconds, from stored per-year counts. | M | Low: stale until the next maintenance run. The stats step is already heavy (see conflict C3). | **new** (`catalog-api` read, enricher or loader maintenance) |
| 4 | **Re-baseline routes and maintenance durations now that statement stats exist.** | No route p95 has been measured. Statement stats show maintenance statements the baseline could not time: `identity_ledger_refresh` 5 calls, mean 283 s, max 732 s; `identity_ledger_rebuild` 4 calls, mean 399 s; `graph.refresh_vertex_degree` 228 s; `genre_stats` and `style_stats` rebuilds 2,098 s and 2,106 s; the completeness count 3 calls, mean 188 s, max 406 s. Some of these may be first-run or pre-fix calls. | Turns the targets below from proposals into numbers. May show that "incremental" and the completeness fix hold or do not. | S | Low: read-only for the statements; the API journeys need operator approval and a reachable origin. | **new** (`deployment`, continues `gm-deployment-5pxz`) |
| 5 | **Rate limits and path bounds for expensive graph routes.** | `/api/explore`, `/api/expand`, `/api/trends`, `/api/path` have no rate limit, and path allows up to 120 s. Rock to Trance: 2.3 s, 7.2M hits (measured). Server timeouts (jpyk) now cap the worst case, but nothing limits how many run at once. | Removes the way a few requests tie up Neo4j for everyone. | M | Low to medium: legitimate heavy users could see 429s. | `catalog-api` 8fou, **operator-DEFERRED 2026-11-04** |
| 6 | Drop unread indexes. | 147 of 270 indexes unread, 27 GB of 105 GB (counters since 2026-11-07, so mostly load, not reads). Largest: `idx_releases_identifiers` 2.9 GB, `track_by_artist_reverse` 2.6 GB, `idx_releases_hash` 2.3 GB, `idx_release_rarity_gem` 1.5 GB. Audit estimate: 36 indexes, about 23 GB at full size. | Up to 27 GB and faster loads (hash insert 906 µs against 6.7 µs for btree in the audit). | S per index | Medium: see conflict C1. | `database-schema` zd7u (open) |
| 7 | Refresh `artist_member_of` and `vertex_degree` after a MusicBrainz load. | After a MusicBrainz load, 61.6% of that edge class (the MusicBrainz share) and the path functions stay stale until the next Discogs refresh. Correctness more than speed; the refresh itself took 228 s once. | Right paths and degrees after a MusicBrainz load. | M | Medium: two loaders must not refresh the same truncate-and-insert table at once. | `database-schema` gqs2, then `musicbrainz-sql-loader` dikx |
| 8 | Finish facets on `release_search` and record the facet cap decision. | Filtered `love` + Jazz + 1970 + vinyl 10.4 s to 0.67 s (measured). Facets used to count only the first 10,000 matches in no defined order. | Correct facet counts if counting every match fits. | S | Low; operator decision on the cap. | `catalog-api` 4asm (under review) |
| 9 | Re-run the embedding edge and release-id queries once. | The release-id DISTINCT spilled 1.04 GB on a 5x estimate miss; the estimate is fixed, the spill not re-run. | Confirms no temp spill; both edge queries stay near 1 min. | S | Low | folded into item 4 |
| 10 | Label DNA gap. | 27.86M hits against a 40% reduction target (30% achieved); four statements still walk every release of a label. Peak 39.6 MB, under the 60 MB bar. | About 1.4 s to well under 1 s for the largest labels, cold only. | M | Low | no open bead; **new** only if item 4 shows it matters |
| 11 | Person-led reads of `graph.credited_on`. | No `person_name` index; a person-led read plans as a seq scan over 71.8M rows (planner cost 935,117; `EXPLAIN` only). Statement stats show **no statement** reading either credit table by `person_name`. | None. See conflict C2. | none | none | none; do not add the index |
| 12 | `pg_stat_statements` `track_utility` off. | Utility statements fill the statement table. | Cleaner ranking. | S | Low | `deployment` ki6g (open); needs a planned restart |

Also reviewed and accepted as is: the reference host's Postgres settings (shared buffers, `work_mem`, JIT, planner costs),
because the audit found no evidence for a change; and Neo4j page cache sizing, which stays a "measure first" question
(store size could not be read through the read-only wrappers). Neither is a roadmap item until a number says otherwise.

## Proposed targets

Targets are proposals for the operator. Route targets are set against **statement** measurements and must be re-based
on route percentiles once item 4 runs.

### Route p95

| Route | Measured now | Proposed p95 | Basis |
| --- | --- | --- | --- |
| Release search, heavy term (`love`), with facets and filters, first uncached request | 0.67 s for the filtered case; release branch alone 4.3 s warm before the search vector (baseline) | **1 s** | measured pieces; route not timed |
| Master search | 39 ms | **100 ms** | measured |
| Ledger works window (one month) | 0.28 s | **2 s** (existing budget, already met) | measured |
| Genre or style trends, first visit | Rock 3.8 s warm, 17.5 s first | **1 s** after item 3 | measured |
| Label trends, first visit (label 1818) | 0.9 s | **1 s** (already met) | measured |
| Explore and expand, first visit, hub artist | Bowie explore 59 to 105 ms, label 1818 expand 285 ms | **1 s** | measured |
| Path search | 48 to 241 ms for artists; Rock to Trance 2.3 s | **5 s hard cap** with hub guard after item 5 | measured; cap is a proposal |
| Authentication and other cheap routes under concurrent cold searches | pool starvation reproduced at 8 concurrent cold searches (synthetic, 2026-11-04) | **no degradation** with the concurrency gate (u61r) | to confirm in item 4 |

### Load and maintenance duration

| Stage | Baseline | Proposed target | Basis |
| --- | --- | --- | --- |
| Discogs first load, SQL time | about 10 h (**estimate** from about 2M releases an hour at 20% load; the 2026-11 load's actual duration was not read for this document) | **at most 5 h**, the load before the changes recorded alongside | audit ratios are synthetic; confirm on the next load |
| Discogs monthly reload of unchanged rows | about 64 min and 127 GB of WAL for `releases` (**estimate**) | **at most 10 min**, WAL under 10 GB, measured in shadow mode | item 1 |
| MusicBrainz reload of unchanged rows | one write per relationship and link row per extraction (rerun of 2,000 records: 28,055 and 7,324 updates, synthetic) | **under 10% of first-load write time** | item 2 |
| `identity_ledger_refresh`, steady state | mean 283 s, max 732 s (statement stats, composition unknown) | **under 60 s** for a day of changes; before-and-after in item 4 | item 4 |
| Genre and style stats rebuild | 2,098 s and 2,106 s | **no longer than today** after trends are added | conflict C3 |
| Embedding load, credit edge queries | 64 s, 51 s, 29.7 s (measured) | **no temp spill**; stay under 2 min each | item 9 |

## Conflicts and decisions for the operator

**C1. Dropping unread indexes against readers that run monthly (zd7u).** Several of the largest "unread" indexes serve
monthly jobs. The embedding load reads `track_by_artist` three times, so `track_by_artist_reverse` (2.6 GB) looks unread
until that load runs. Unique and primary key indexes (`provider_aliases_pkey`, 2.4 GB) enforce constraints whatever
their scan count. Counters cover 1.5 days. Recommendation: do not drop on a one-week window. Drop an index only when
(a) the counters span at least one full monthly cycle, or (b) the owning repository confirms by plan that no statement
uses it. `pg_stat_statements` makes (b) cheaper than before: sample the plans of the top read statements. **Decision:** accept the monthly
window, or accept a plan-based review sooner.

**C2. A `person_name` index on the credit tables against the load.** An index would turn a 71.8M-row seq scan into a
seek, but no statement in `pg_stat_statements` reads the credit tables by `person_name`, every person route is on
Neo4j, and the audit measured the old hash indexes at 24% slower loads and 52% more disk (synthetic). Recommendation:
do not add one. If a person-led SQL read is ever needed, add it with that read. **Resolved unless the operator wants it
revisited.**

**C3. Precomputing trends against the stats rebuild (item 3).** `genre_stats` and `style_stats` each rebuild in about
35 min in one statement. Adding per-year counts as separate traversals would lengthen maintenance. Recommendation: fold
the yearly counts into the same pass, and measure the rebuild before and after. If the PostgreSQL graph direction
(ADR 0012) moves trends off Neo4j, build the stored counts in Postgres first. **Decision:** which store holds them.

**C4. Seen list for Discogs, nothing yet for MusicBrainz (items 1 and 2).** The seen list fits Discogs because rows are
visited once. MusicBrainz relationship rows are seen from both endpoints, so a seen list does not cover them, and
record messages carry no extraction id. Operator decision of 2026-11-04 stands: Discogs seen list, shadow mode first;
MusicBrainz stays at one marker write per row per extraction until a per-record child replacement is designed.
**Decision:** commission that design now, before the next MusicBrainz reload, or accept option C for the next cycle.

**C5. Rate limits deferred against bounded-but-unlimited routes (item 5).** The operator deferred 8fou. Timeouts landed
under jpyk, so one request can no longer hold Neo4j for ten minutes, but concurrency is unlimited. Recommendation:
the bead says these routes are reachable from the public site, so set a date to revisit rather than leaving the deferral open-ended. **Decision:** keep
deferred, or promote only the path hub guard.

**C6. Facet counts, cap or all matches (item 8).** 4asm records the choice with numbers. This roadmap does not
pre-empt it. Counting every match gives correct facets; a cap needs a deterministic sample.

## Accounting for every audit bead

"Landed" means closed with merged work. Items I could not verify beyond the bead's status say so.

### `deployment` (10 beads)

- Landed: 0x54 (audit and baseline procedure), 5pxz (this baseline), l4gf (guide and overlay corrected), wia0 (statement stats enabled), t52v (catalog caches off the auth cache), 1d5o (API memory limit), bohz (explore baseline case), wv27 (fewer psql calls).
- Open: ki6g (item 12), p9ql (image digest pin, in progress; not a query-performance item, carried by the label).
- **Dropped on purpose:** Postgres planner settings changes; Neo4j page cache change before store size is known.

### `catalog-api` (45 beads)

- Landed and measured above: tn5r, 1crp, 2jka, 575h, j4ml (partly). 6tjq, onma and ysh9 have audit numbers but no route re-measure.
- Landed, not re-timed since the audit: 9d8z, jpyk, p85n, zazs, somq, vus1, 88cu, i6l1, 2f58, nhux, og3t, a01i, 4wgh, q1h7, pk6n, 6td2, 1xps, orhn, wl47 (re-time with the completeness statement, item 4), usmt and jlyv (rarity and memory), sflm, jey8, 0n2z, 6zq4, k0rl, 57d6, dcwo, kj2d, u61r (concurrency gate, no re-test under load), 87pz.
- Open: 8fou (item 5, deferred), 4asm (item 8, in progress).
- **Dropped on purpose in the audit:** a `CALL` barrier for expand (took 261,614 hits against the plain form), flattening the strata ladder (raised memory from 393 KB to 5.2 MB), size-of-pattern rewrites (same cost as `COUNT {}`). Checked and cleared: `get_year_range`, role leaderboard, `get_release_context`, `/api/path` for ordinary artists, `similar.candidates`.
- **Not profiled in the audit and still not profiled:** taste reads, analytics batch reads (`label-longevity`, `genre-trends`, `artist-centrality`, `anniversaries` lack a time budget), sync and projection writes, erasure. Item 4's statement ranking will show whether any matters.

### `database-schema` (25 beads)

- Landed: bfuh, uz24, xen5, nbvh, 9dcd, 1sle, nu0c, fi4a, bynr, 50jj, a8xk, woex, vvb6, 0exy, anui, m6jp, ngw9, 00ke, wclt, v8qk, nadu, 3g99, 5e8f.
- Open: uw6d (item 1, in progress), zd7u (item 6), gqs2 (item 7).
- **Dropped on purpose:** a deferred-index load mode ("not worth a separate load mode"); a BRIN index alone as the reload fix (full pages block HOT updates, 7%).

### `analytics-engine` (7 beads)

- Landed: afek, tz5x, lh7b, wf4h, b1us, ehf8, v9ak. Edge queries measured (64 s, 51 s). The `release_id` spill is not re-run (item 9).
- The audit's heavy computations live in `catalog-api` and were audited there (b78b and 2x1z are closed).

### `discogs-sql-loader` (8 beads)

- Landed: 7qar, n15x, ymm9, pf94, 4n7r, 2njb, njgk.
- Open: g77f (item 1). Not started until the first load finished, which it has.
- **Dropped on purpose:** `synchronous_commit=off`, rejected as unsafe with ack-after-commit (1.18x). Index deferral and WAL settings for the first load were assigned to ymm9; its closed outcome is not restated here, and the database-schema audit judged deferral not worth a separate load mode.

### `musicbrainz-sql-loader` (6 beads)

- Landed: 5wwo, 1twk, u2qf, 1l9i, f7t5.
- Open: 3osm (item 2, in progress), dikx (item 7, blocked on gqs2).
- **Dropped on purpose:** batching commits alone (measured no change); the `old` CTE and link-event insert in the entity upsert (cost too small); dropping `idx_mb_rels_type` (the audit called it probably not worth its cost but left the decision to `database-schema`; it is a candidate under item 6).

### `discogs-graph-enricher` (8 beads) and `musicbrainz-graph-enricher` (6 beads)

- Landed: all fourteen (hho, ssbj, 2v9k, 9ji9, qhp0, fi76, jfbk, yz1u; 545, 943, 3e2, 84c, 0o4, egqo).
- The enricher audit's proposal 7, timing the first real paged maintenance with writes, is covered by item 4. The genre and style stats rebuild times above come from it.
- Finding not turned into a bead: the genre and style *trends* traversal (item 3).

### `python-libraries` (4 beads)

- Landed: 7lfm, adqd, cpco, ct7c. The audit's other proposals landed under their owning repositories: `system_monitor` full node scan (`operations-toolkit` ao0), idle console load (`operations-console` wxwf), shared client and tidy-ups (small, not worth a bead by the audit).

### Findings that no bead tracks

1. The `issued_on` per-record delete in the MusicBrainz loader (item 2).
2. Genre and style trends precompute (item 3).
3. Measured maintenance durations not yet reconciled with the incremental ledger claim (item 4).
4. The baseline's "no `loader_derived_refresh_job` row for MusicBrainz" is item 7.
5. `scripts/perf-baseline.sh` drift (the explore case counts releases by traversal though a stored count exists; neo4j mode needs an adapter). Carried by item 4.

## Next steps

1. Operator: approve the API journey run (item 4) and decide C3 and C4.
2. Planner: file the three **new** beads (items 2 delete, 3, 4) and link them to this document.
3. Revisit zd7u after one full monthly cycle, not one week (C1).
