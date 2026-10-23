# Spike: the credit, master, release ladder and a strata route on Neo4j

Status: **GO, with conditions**. The catalog fits the ladder if masterless releases and
undated releases get lanes of their own. Collector state is observed from Discogs only,
so the view displays it and cannot change it. Latency was measured read-only on the
predecessor's full graph: a strata read costs about twice Explore's for roots under
10,000 releases. Above that it needs a cache or a summary, and the two placeholder
roots were not measured at GrooveMap's size.  
Evidence date: 2026-10-23  
Spike: `gm-design-1h2l` (epic `gm-design-uq8t`, concept A, "S2")  
Harness: [gm-design-1h2l/](gm-design-1h2l/README.md)  
Related: [ADR 0009](../adr/0009-native-identity-and-provider-aliases.md),
[ADR 0010](../adr/0010-first-party-events-consent-and-deletion.md),
[ADR 0012](../adr/0012-postgresql-property-graph-migration.md),
[ADR 0014](../adr/0014-cross-catalog-edition-candidates.md)

## Question

Concept A draws an artist's discography as three planes: credits on top, masters in
the middle, and releases at the bottom. X is the release year, and color is the
collector's state. This spike asks three things:

1. Does GrooveMap's catalog fit that ladder well enough to draw it honestly?
2. Which collector state changes can GrooveMap author, and which can it only observe?
3. Can catalog-api serve the ladder from Neo4j within Explore's latency, including for
   the largest discographies?

## Method

| Input | What was read |
| --- | --- |
| Discogs releases | `discogs_20261001_releases.xml.gz`, streamed whole and never written: 19,492,392 releases |
| Discogs masters | `discogs_20261001_masters.xml.gz` from the shared cache: 2,598,586 masters |
| MusicBrainz releases | `json-dumps/20261021-001001/release.tar.xz`, streamed whole: 5,867,935 releases |
| MusicBrainz release groups | `json-dumps/20261021-001001/release-group.tar.xz` from the shared cache: 4,591,825 groups |
| Predecessor graph | The predecessor system's full Neo4j (2026.09.0 community, 19,506,762 Release nodes), read-only through a wrapper that runs cypher-shell in READ mode. Latency and the collector edges were measured there. Host, user, and container names are left out here |
| Predecessor PostgreSQL | The predecessor's `user_collections` and `user_wantlists`, read-only, inside `begin transaction read only` with a statement timeout |
| Code | `catalog-api` `957fe1f`, `database-schema` `817081d`, and the current `main` of `discogs-ingestion`, `discogs-graph-enricher`, `musicbrainz-ingestion`, `musicbrainz-graph-enricher`, and `python-libraries` |

The counts follow the graph's own projection rules, restated in the harness rather
than approximated:

- **An artist's releases** are its release-level `BY` edges: the `<artists>` list of
  each release, not track artists (`discogs-ingestion` `normalize_release`,
  `discogs-graph-enricher` `batch_projection.py`).
- **A release's master** is its `DERIVED_FROM` edge, from `<master_id>`. Discogs writes
  `0` for "no master", and GrooveMap's rule treats it as no entity
  (`database-schema` `_usable_id`, `discogs-sql-loader` `_entity_id`). Finding 1.4
  covers what that means for Neo4j.
- **A credit** is a release-level `<extraartists>` entry with a name and a role, which
  becomes `(:Person {name})-[:CREDITED_ON {role}]->(:Release)`. Track-level credits are
  not projected, so they are not counted. Roles are counted two ways: the raw role
  string the edge stores, and the bare roles inside it. "Mixed By [Assistant],
  Producer" is one raw string holding two bare roles.
- **Release year** is the first four characters of `<released>`, kept only inside
  [1860, dump year + 1] (`python-libraries` `data_normalizer._parse_year_int`).
- **A MusicBrainz release's Discogs link** is the first `discogs` URL relation that
  parses as `https://www.discogs.com/release/<id>`. A release group's master link works
  the same way (`musicbrainz-ingestion` `find_discogs_id`). Those are the values in
  `musicbrainz.releases.discogs_release_id` and
  `musicbrainz.release_groups.discogs_master_id`.

Percentiles are nearest-rank, so every reported value is one that some artist or
master actually has. Size bands are by an artist's release count: 1-9, 10-99, 100-999,
1,000-9,999, and 10,000+.

The transition table comes from reading the code that writes collector state, not from
the mockup. That covers every route in `catalog-api/api/contracts/*/v1/routes.json`, the
Discogs sync (`api/syncer.py`), the activity recorder and the outcome route
(`api/activity.py`, `api/routers/activity.py`), the observation routes
(`api/routers/observations.py`), and the event vocabulary in
`taxonomy/events/v1/event-types.json`.

## Evidence

### 1. How the catalog fits the ladder

#### 1.1 Releases with no master, and with no year

| Releases (Discogs 20261001) | Count | Share |
| --- | ---: | ---: |
| All releases | 19,492,392 | |
| **No master** | **8,108,112** | **41.60%** |
| No release year | 2,593,700 | 13.31% |
| No year, even after falling back to the master's year | 1,524,526 | 7.82% |
| No `BY` artist | 23 | |

Of the 1,477,749 releases that have a master but no year, 1,069,174 (72.35%) can take
the master's year. Masterless releases have no such fallback: 1,115,951 of them
(13.76%) have no year at all. Separately, 173,720 masters (6.69%) have no year of their
own.

#### 1.2 Per artist

Over the 2,882,133 artists with at least one release:

| Per artist | p50 | p99 | max | mean |
| --- | ---: | ---: | ---: | ---: |
| Share of releases with no master | 1.0 | 1.0 | 1.0 | 0.797 |
| Masters | 0 | 16 | 174,943 | 1.16 |
| Releases | 2 | 86 | 1,356,055 | 8.19 |

2,061,842 artists (71.54%) have no master at all. That is the long tail: most artists
with a handful of releases have never had a master created. The picture changes with
size, so the bands matter more than the overall median:

| Band (releases) | Artists | Releases | Pooled no-master share | No-master share per artist, p50 / p99 / max | Masters per artist, p50 / p99 / max | Releases per artist, p50 / p99 / max |
| --- | ---: | ---: | ---: | --- | --- | --- |
| 1-9 | 2,569,433 | 5,693,758 | 72.31% | 1.0 / 1.0 / 1.0 | 0 / 2 / 8 | 1 / 9 / 9 |
| 10-99 | 288,359 | 7,099,710 | 41.82% | 0.407 / 1.0 / 1.0 | 3 / 20 / 50 | 18 / 91 / 99 |
| 100-999 | 22,843 | 5,417,411 | 21.98% | 0.176 / 0.979 / 1.0 | 29 / 140 / 384 | 171 / 889 / 999 |
| 1,000-9,999 | 1,454 | 3,163,488 | 13.77% | 0.112 / 0.582 / 1.0 | 169 / 947 / 1,573 | 1,581 / 8,513 / 9,959 |
| 10,000+ | 44 | 2,241,976 | 47.11% | 0.162 / 0.770 / 0.770 | 1,661 / 174,943 / 174,943 | 14,616 / 1,356,055 / 1,356,055 |

The ten largest artists (the harness keeps no names):

| Rank | Releases | Masters | No-master share | No year |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1,356,055 | 174,943 | 0.612 | 176,818 |
| 2 | 87,683 | 9,362 | 0.770 | 42,591 |
| 3 | 58,801 | 7,343 | 0.218 | 19,216 |
| 4 | 54,065 | 8,062 | 0.254 | 16,729 |
| 5 | 44,659 | 7,007 | 0.285 | 13,447 |
| 6 | 36,434 | 1,627 | 0.116 | 9,656 |
| 7 | 30,448 | 1,996 | 0.148 | 6,554 |
| 8 | 29,871 | 3,731 | 0.201 | 10,137 |
| 9 | 26,074 | 1,324 | 0.162 | 5,333 |
| 10 | 25,237 | 3,367 | 0.264 | 7,214 |

Rank 1 has 15 times the releases of rank 2, which fits a placeholder credit for
compilations better than any performer. The harness keeps no names, so it does not
confirm which artist it is. Either way, the route has to serve a root of that size.

#### 1.3 Per master, and credit fan-out

| Per master (2,598,573 masters with a release) | p50 | p99 | max | mean |
| --- | ---: | ---: | ---: | ---: |
| Releases | 2 | 32 | 1,542 | 4.38 |
| `BY` artists across its releases | 1 | 5 | 31 | 1.29 |
| Artists on the master record itself | 1 | 4 | 26 | 1.22 |
| Credited people (`CREDITED_ON`) across its releases | 3 | 37 | 531 | 5.30 |
| Raw role strings | 2 | 41 | 561 | 5.40 |
| Bare roles | 3 | 29 | 128 | 5.17 |
| `CREDITED_ON` edges | 4 | 271 | 16,727 | 21.21 |

- **Multi-parent masters:** 433,410 masters (16.68%) have releases credited to more
  than one `BY` artist, and 361,318 (13.90%) list more than one artist on the master
  record. So a master often belongs under more than one credit. The draft rule below
  gives it one parent, the credit of its main release, and lets the other credits
  reach it by lateral edge.
- **No personnel:** 717,786 masters (27.62%) have no release-level credit at all, so
  "shared personnel" edges cannot connect them.
- **Roles:** 71,574,944 credit rows name 6,235,586 distinct people. The raw role strings
  number 2,656,801, because Discogs puts free-text qualifiers in brackets. Only 9,187
  bare roles remain once the brackets are removed. Personnel edges should key on bare
  roles, or on `CREDITED_ON.category`.
- 10,387,326 releases (53.29%) carry any release-level credit.

#### 1.4 The `0` master sentinel is in the graph

In the 20261001 dump, every one of the 8,108,112 masterless releases writes
`<master_id>0</master_id>`; none simply omits the element. `discogs-ingestion` passes
`master_id` through as the string `"0"` (`normalize.rs`, and the `test_release_master_id_*`
tests show it stays a string). `discogs-graph-enricher` keeps a master when
`if master_id:` is true, and the string `"0"` is truthy (`batch_projection.py` around
line 731, `entity_projection.py` around line 337). The SQL loader drops the sentinel and
says so in a comment (`discogs-sql-loader` `graph_derivation._entity_id`).
`database-schema`'s `_usable_id` assumes the enricher drops it too.

**Measured on the predecessor graph, which this enricher lineage loaded: one
`(:Master {id: '0'})` holds 8,156,478 `DERIVED_FROM` edges.** A strata query would draw
41.8% of all releases under one fake master. Explore's artist and release views do not
traverse `DERIVED_FROM`, so nothing visible today shows it.

### 2. MusicBrainz-only releases

Neo4j holds no MusicBrainz-only release. `musicbrainz-graph-enricher` merges MusicBrainz
data onto the Discogs node that its Discogs id names, and skips any record without one
(`_projections.py` `enrich_release` and `enrich_release_group`). Such a release lives only
in PostgreSQL `musicbrainz.releases`.

| MusicBrainz releases (20261021) | Count | Share |
| --- | ---: | ---: |
| All releases | 5,867,935 | |
| Linked to a Discogs release | 1,890,540 | 32.22% |
| Linked to more than one (ingestion keeps the first) | 12,791 | |
| Linked, but the Discogs release is not in the 20261001 dump | 6,670 | |
| **MusicBrainz-only** | **3,977,395** | 67.78% |

How a MusicBrainz-only release reaches a master, with each path tried in order:

| Path | Releases | Share of MB-only |
| --- | ---: | ---: |
| **Native id**: its release group carries `discogs_master_id`, the alias that ADR 0009 and ADR 0014 section 8 put on one native item | **319,386** | 8.03% |
| Native id, but that master is missing from the Discogs dump | 1,313 | 0.03% |
| **Release group**: no master link on the group, but linked sibling releases derive from exactly one master | **142,725** | 3.59% |
| Release group, but linked siblings derive from two or more masters (ambiguous, not attached) | 894 | 0.02% |
| Release group, but the linked siblings are themselves masterless | 80,904 | 2.03% |
| No path | 3,432,173 | 86.29% |
| **Attached to a master** (native id + release group) | **462,111** | **11.62%** |

No MusicBrainz-only release carries a release-level Discogs master link.

The two paths agree. Of the 315,579 release groups that have both a master link and
linked siblings with a master, 4,790 (1.52%) disagree, either because the siblings name
another master or because they name more than one.

The release-group path reads PostgreSQL: `musicbrainz.releases.release_group_mbid`
joined to `musicbrainz.release_groups.discogs_master_id`. `database-schema` indexes
`release_groups (discogs_master_id)` but not `releases (release_group_mbid)`, so the
sibling path has no index to use today.

### 3. Collection and wantlist time: what is recorded where

GrooveMap has never been deployed, so there is no GrooveMap data to count. The
predecessor holds one user's synced collection and wantlist. On the predecessor schema,
measured read-only with
[`collector_time_predecessor.sql`](gm-design-1h2l/scripts/collector_time_predecessor.sql)
and [`predecessor_checks.cypher`](gm-design-1h2l/scripts/predecessor_checks.cypher):

| Predecessor (1 user, 4 syncs between 2026-05-25 and 2026-06-08) | Rows | With `date_added` | `date_added` on or before `created_at` |
| --- | ---: | ---: | ---: |
| `user_collections` | 3,081 | 3,081 | 3,081 |
| `user_wantlists` | 737 | 737 | 737 |
| Neo4j `COLLECTED` edges | 3,075 | 3,075 | |
| Neo4j `WANTS` edges | 737 | 737 | |

Every synced row carries the Discogs `date_added`, for both lists. With one user, that
shows the Discogs API supplies the field on collection items and wants. It is not a
coverage rate for a population. The 6 collection rows without an edge are releases
missing from that graph, because the sync's Neo4j write is `MATCH (r:Release ...)` and
skips a release the graph lacks.

[`collector_time.sql`](gm-design-1h2l/scripts/collector_time.sql) is the same check
against GrooveMap's schema, for the first deployment to run. What the code does with
the field:

| Recorded time | Where | Usable as transaction time? |
| --- | --- | --- |
| `date_added` | `user_collections`, `user_wantlists`, and the Neo4j `COLLECTED` and `WANTS` edges, copied from the Discogs API on every sync (`syncer.py`, `item.get("date_added")`) | Yes, as the collector's own recorded time, kept by Discogs. `owned_copies.acquired_at` is the same value |
| `created_at` | `user_collections`, `user_wantlists` (`NOT NULL DEFAULT NOW()`) | Yes, as GrooveMap's first sight of the row: the first sync after the collector acted |
| `updated_at`, `synced_at` | Rows and edges, overwritten with the sync clock on every run | No |
| `activity.events.occurred_at` | `collection.item_added`, `collection.item_removed`, `collection.item_updated`, `wantlist.item_added`, `wantlist.item_removed`, emitted by the sync | Yes, GrooveMap's transaction time for each observed change. **A removal is recorded nowhere else**, because the row is deleted |
| `collection_snapshots.taken_at` + `copy_ids` | One row per successful sync | Yes, for "owned as of" replay of the collection. There is no wantlist snapshot |

When Discogs omits `date_added`, the row stores NULL, the owned copy's `acquired_at`
is NULL, and the Neo4j `SET c.date_added = null` removes the property. The upsert
overwrites `date_added` with the new value instead of keeping the old one (no
`COALESCE`, unlike `formats` and `metadata`), so a later sync without the field erases a
recorded time. A `collection.item_updated` event names `date_added` when it changes.
The predecessor schema has none of `owned_copies`, `collection_snapshots`, or
`activity.events`, so the replay sources above could not be checked there.

So a "recorded as of" control can replay ownership from snapshots and wants from events.
Before the event recorder existed, a current row has a start time and no end time, and
a removed row has neither.

### 4. Collector state changes: authored, observed, or not possible

| # | Change on a release node | Who can cause it | Code |
| ---: | --- | --- | --- |
| 1 | none -> wanted | **Observed** from Discogs sync, after the collector adds a want on Discogs | `sync_wantlist` upsert, `WANTS` edge, `wantlist.item_added` |
| 2 | wanted -> none | **Observed** from Discogs sync | `_reconcile_stale_wantlist` deletes the row and the edge, `wantlist.item_removed` |
| 3 | none -> owned | **Observed** from Discogs sync | `sync_collection` upsert, owned copy minted, `COLLECTED` edge, `collection.item_added`, snapshot |
| 4 | owned -> owned + another copy | **Observed** (a new Discogs `instance_id`) | one row and one owned copy per instance |
| 5 | owned -> none | **Observed** from Discogs sync. The owned copy and its observations survive with `collection_row_id = NULL` | `_reconcile_stale_collection`, `collection.item_removed` |
| 6 | owned, folder, rating, or `date_added` changed | **Observed**. Not a color change | `collection.item_updated` |
| 7 | wanted -> owned in one step | **Not a transition GrooveMap ever sees.** Discogs does not clear a want on purchase, so it arrives as #3, perhaps followed by #2 at the same or a later sync. A release can be wanted and owned at once | `sync_collection` and `sync_wantlist` run independently |
| 8 | any -> wanted, or any -> owned, from GrooveMap | **Not possible today.** No route writes `user_collections` or `user_wantlists`. The sync is their only writer, and catalog-api never writes to Discogs. The graph-explorer contract has no such route | `routes.json` (all three consumers), `syncer.py` module docstring |
| 9 | A MusicBrainz-only release -> wanted or owned | **Not possible today.** The sync resolves Discogs release ids only, and owned copies are minted only from collection rows | `_alias_refs`, `_MINT_OWNED_COPIES` |
| 10 | Record an observation on an owned copy (matrix, grading, price) | **Authored** by GrooveMap: `POST /api/user/copies/{copy_id}/observations`. It annotates the copy and does not change its state. It needs a copy the sync minted, and it also works on a copy whose collection row is gone | `observations.py` |
| 11 | Recommendation or fit outcome: opened, saved, dismissed, hidden | **Authored**: `POST /api/activity/events`, but only against an `impression_id` that the recommendation or fit surface recorded. `taxonomy/events/v1` has no strata surface, so a strata node cannot carry these today. This is concept C's machine, not the collector's | `ActivityOutcomeRequest`, `CLIENT_REPORTABLE_OUTCOMES` |
| 12 | Request a sync | **Authored**: `POST /api/sync`. It asks GrooveMap to observe and changes nothing on its own | `routers/sync.py` |
| 13 | Stop observing | **Authored**: `DELETE /api/oauth/revoke/discogs` deletes the token and keeps every row, so state stays as last observed | `api.py` `revoke_discogs` |

Derived at read time, never stored or written:

- A master's and a credit's state roll up from their releases (the mockup's rule).
- "Redundant want" means wanted while another release of the same master is owned. It
  can be derived from `COLLECTED` and `WANTS` plus `DERIVED_FROM`, as the gaps queries
  already do.

The honest collector machine for concept A therefore has states `none`, `wanted`,
`owned`, and `wanted + owned` on a release. Every edge between them is labelled
"observed at sync", and none of them is a control. The only GrooveMap-authored actions
a release node can offer are "record an observation" (owned copies only) and "sync
now". The mockup's "Add to wantlist" and "Mark as collected" buttons are not real
transitions. A MusicBrainz-only release node shows no collector state.

### 5. Latency on Neo4j, measured on the predecessor graph

GrooveMap has never been deployed, so the measurement ran read-only on the predecessor
system's full graph. It ran inside one cypher-shell session per band, in READ mode,
through a wrapper that never exposes a credential
([`latency_shell.py`](gm-design-1h2l/scripts/latency_shell.py)). Each statement times
itself on the server: `datetime.realtime()` is read before the query and again after
every row has been produced. The artists are the first 30 of each band's seeded sample
from the dump (all 10 for the largest), each run once (run 0) and then 5 more times.
Ids are Discogs ids, so the dump sample addresses the same artists in that graph.

**Measured on the predecessor schema.** It matches GrooveMap's shape where these
queries read it:

| | Predecessor | GrooveMap (`database-schema` `neo4j.py`) |
| --- | --- | --- |
| Neo4j | 2026.09.0 community | 2026.09.0 community (deployment pin) |
| Uniqueness constraints | `artist_id`, `label_id`, `master_id`, `release_id`, `genre_name`, `style_name`, `user_id`, `person_name` | The same eight, plus `medium_id`, `media_family_name`, `company_id` |
| Range indexes | `*_sha256` (4), `*_mbid` (4), `artist_name`, `label_name`, `person_name`, `release_year_index`, `master_year_index`, `genre_first_year_index`, `style_first_year_index`, `person_credit_count` | The same, plus `artist_gm_id`, `label_gm_id`, `master_gm_id`, `release_gm_id`, `release_media_families_index`, `release_country` |
| Full-text indexes | artist, label, genre, style, person, release title | The same six |
| Labels and relationship types the five queries read | `Artist`, `Release`, `Master`, `Label`, `User`; `BY`, `DERIVED_FROM`, `ON`, `ALIAS_OF`, `MEMBER_OF`, `COLLECTED`, `WANTS` | The same |

None of the missing pieces is read by the measured queries. They seek `Artist.id` or
`Artist.name` and `User.id`, and then expand relationships. Differences that can move
the numbers:

- **Three placeholder-sized roots are about a tenth as large in the predecessor graph.**
  The dump's rank 1 has 1,356,055 `BY` releases; the predecessor has 134,051. Rank 2 has
  87,683 against 6,915, and one more root has 19,766 against 1,659. For the other 41
  sampled roots of 10,000+ releases, the predecessor's `BY` degree is a median of 1.10
  times the dump's (range 1.04-1.17). The predecessor's largest root is 134,051
  (`top_by_degrees` in `predecessor_checks.cypher`). So no root above 134,051 releases
  was measured, and nothing here is extrapolated to 1,356,055.
- The predecessor's rank 1 has no `name`, so Explore, which addresses artists by name,
  cannot open it. That is why the `explore` and `expand` rows below have fewer runs in
  the two largest bands. The strata route addresses artists by id.
- The `0` master hub (section 1.4) is present, so `strata_ladder` groups the masterless
  releases under one more row than it would on a clean graph.
- **Hardware:** 14 CPUs, 56 GiB RAM, a 24 GiB heap, and a 24 GiB page cache, on a shared
  host whose other load was not controlled. The page cache was not flushed. "Run 0" is
  the first execution for that artist (cold plan, and its pages unless another query
  had touched them), not a cold-cache start.
- **Server time only.** Bolt transfer and route serialization are not included. For the
  largest root, `strata_ladder` returned 31,526 rows, each carrying up to 50 release
  samples, so transfer can be larger than the query.

Warm runs (runs 1-5), server-side milliseconds, p50 / p95:

| Band | Artists | `explore` | `expand` page (50) | `expand` count | `strata_ladder` | `strata_credits` |
| --- | ---: | --- | --- | --- | --- | --- |
| 1-9 | 30 | 0.2 / 0.3 | 0.1 / 0.2 | 0.1 / 0.1 | 0.2 / 0.3 | 0.2 / 0.4 |
| 10-99 | 30 | 0.2 / 0.4 | 0.1 / 0.3 | 0.1 / 0.1 | 0.3 / 0.5 | 0.2 / 0.4 |
| 100-999 | 30 | 0.7 / 2.6 | 0.5 / 1.7 | 0.2 / 0.8 | 1.1 / 3.5 | 0.7 / 2.7 |
| 1,000-9,999 | 30 | 5.0 / 17.8 | 2.9 / 10.8 | 1.6 / 5.2 | 8.3 / 35.2 | 4.9 / 14.5 |
| 10,000+ | 30 of 44 | 46.0 / 99.7 | 24.9 / 49.4 | 11.4 / 26.3 | 87.8 / 328.3 | 41.8 / 213.4 |
| Largest 10 | 10 | 92.0 / 171.0 | 43.8 / 73.8 | 21.1 / 40.9 | 184.3 / 779.5 | 101.6 / 218.4 |

Run 0, server-side milliseconds, p50 / max:

| Band | `explore` | `expand` page | `strata_ladder` | `strata_credits` |
| --- | --- | --- | --- | --- |
| 1-9 | 0.8 / 3.4 | 0.9 / 2.6 | 0.2 / 0.3 | 0.2 / 0.5 |
| 10-99 | 1.4 / 2.1 | 2.3 / 9.7 | 0.3 / 2.8 | 0.3 / 3.1 |
| 100-999 | 1.8 / 4.0 | 15.9 / 85.3 | 5.4 / 65.2 | 1.5 / 9.8 |
| 1,000-9,999 | 6.7 / 25.6 | 98.6 / 297.6 | 42.9 / 381.3 | 7.3 / 77.4 |
| 10,000+ | 48.1 / 161.5 | 265.4 / 1,376.3 | 345.7 / 2,455.2 | 62.3 / 375.9 |
| Largest 10 | 91.9 / 170.4 | 41.0 / 337.8 | 181.4 / 1,561.6 | 104.7 / 259.9 |

The largest-10 sample overlaps the 10,000+ sample, so its run 0 was partly warm. The
full numbers, including run counts and maxima, are in
[`results/latency_predecessor.json`](gm-design-1h2l/results/latency_predecessor.json).

What this shows:

- **Under 10,000 releases** (2,882,089 of 2,882,133 artists), the two strata queries
  together take 0.7-50 ms warm at p95. That is about 1.5 times what Explore spends
  opening the same artist (`explore` plus an `expand` page plus its count: up to 34 ms),
  and 2-3 times the `explore` query alone. Run 0 stays under 400 ms, close to Explore's
  own first `expand` page (up to 298 ms).
- **From 10,000 releases**, the two strata queries take 541 ms warm at p95, against 175
  ms for Explore's open, and `strata_ladder` reaches 2.5 s on run 0. The cost grows with
  the root's `BY` degree, because the query visits every release before it aggregates.
  Explore already caches its `explore` answer in Valkey; the strata answer needs the
  same, or a precomputed per-artist master summary.
- The same cypher was checked for correctness against a throwaway, empty Neo4j
  2026.07.1 loaded with an invented graph
  ([`tests/test_cypher.py`](gm-design-1h2l/tests/test_cypher.py)). It returns one row per
  master plus one for masterless releases, and the caller's `COLLECTED` and `WANTS`
  marks with `date_added`.

### 6. Draft route and payload

```text
GET /api/strata/artist/{artist_id}?budget=3/12/16&focus=&before_year=&as_of=
```

- **Graph read:** Neo4j, `strata_ladder` and `strata_credits`, as Explore's `expand`
  reads today (ADR 0012's amendment keeps Neo4j authoritative).
- **Optional caller:** for a signed-in caller, the same Neo4j read returns the
  caller's `COLLECTED` and `WANTS` edges with `date_added`, which are the edges
  `/api/user/collection` already reads. `as_of` filters them, and
  `collection_snapshots` and the change events answer it for times before the current
  rows.
- **MusicBrainz-only releases:** a second, PostgreSQL read for the masters on the
  plane, by native id (`release_groups.discogs_master_id`) and by release group
  sibling. These nodes carry `"provider": "musicbrainz"` and no collector state (#9).
- **Budget:** per plane, as `credits/masters/releases`. S1 (`gm-design-on0x`,
  `results/layout.json` at `44a5f00`) measured 3/12/16 as the most a view can draw
  legibly, with 6/12/16 as its other passing point. Every aggregate's `id` is a
  `focus` the client can request next to page into it, which keeps each response
  within the same budget.
- **Aggregation rule** (`payload_model.build_payload`): every plane holds at most its
  budget of entries, nodes plus aggregates.
  - Credits: one node per distinct artist credit (the sorted `BY` set of a release).
    The root's own credit comes first, then the rest by release count, and the tail
    folds into one `other credits` aggregate.
  - Masters: each master's parent is the credit of its main release. Masterless
    releases get one `no master` aggregate per credit, because they still need a band
    of their own. Past the budget, the masters with the fewest releases fold into
    per-credit, per-decade aggregates, and masters that hold collector state are kept.
    If that still does not fit, they fold into per-credit aggregates, and last into one
    aggregate per credit. The masters shown are also capped so that the release plane
    can hold one aggregate per shown master and per `no master` band.
  - Releases: one node each, if they fit. If not, each master keeps its main release and
    its stateful releases, and the rest become one count aggregate per master. Past
    that, every master becomes one count aggregate, and masterless releases fold by
    decade.
  - Every entry names a parent on the plane above, so hulls nest. Release and master
    counts are conserved across nodes and aggregates. Both properties are pinned by
    [`tests/test_payload.py`](gm-design-1h2l/tests/test_payload.py).

An example with invented ids and placeholder strings, trimmed: masters 502 to 504 and
their release aggregates are left out. `states` and `state` are present only for a
signed-in caller:

```json
{
  "root": {"type": "artist", "id": 1, "name": "xxxxxxxxxx"},
  "budget": {"credits": 5, "masters": 5, "releases": 5},
  "totals": {"credits": 2, "masters": 4, "releases": 8, "masterless_releases": 1,
             "releases_only_in_master_aggregates": 0},
  "planes": [
    {"level": 0, "kind": "credit", "nodes": [
      {"id": "c:1", "artists": [{"id": 1, "name": "xxxxxxxxxx"}], "releases": 7},
      {"id": "c:1+2", "artists": [{"id": 1, "name": "xxxxxxxxxx"}, {"id": 2, "name": "xxxxxxxxxxxxx"}], "releases": 1}],
     "aggregates": []},
    {"level": 1, "kind": "master", "nodes": [
      {"id": "m:501", "parent": "c:1+2", "title": "xxxxxxxxxxx", "year": 1971, "releases": 4,
       "y0": 1971, "y1": 2016, "state": "owned"}],
     "aggregates": [
      {"id": "nm:c:1", "parent": "c:1", "kind": "no_master", "masters": 0, "releases": 1,
       "y0": null, "y1": null, "states": {"none": 1}}]},
    {"level": 2, "kind": "release", "nodes": [],
     "aggregates": [
      {"id": "ra:m:501", "parent": "m:501", "releases": 4, "y0": 1971, "y1": 2016,
       "states": {"owned": 1, "wanted": 1, "none": 2}},
      {"id": "ra:nm:c:1:unknown", "parent": "nm:c:1", "releases": 1, "y0": null, "y1": null,
       "states": {"none": 1}}]}
  ]
}
```

Payload size per band, as compact JSON bytes. Each row covers 300 artists sampled per
band (seeded, all 44 for 10,000+), plus the ten largest. Strings are padded to the real
byte lengths of titles and names. "Signed in" adds the `state` and `recorded_at` fields
to every node. "Entries" is nodes plus aggregates across all three planes.

| Band | Budget | Anonymous p50 / p95 / max | Signed in p50 / p95 / max | Entries p50 / p95 / max |
| --- | --- | --- | --- | --- |
| 1-9 | none | 706 B / 1.7 KB / 5.8 KB | 793 B / 1.9 KB / 6.2 KB | 4 / 11 / 25 |
| 1-9 | 3/12/16 | 742 B / 1.5 KB / 2.3 KB | 829 B / 1.7 KB / 2.7 KB | 4 / 10 / 16 |
| 10-99 | none | 3.1 KB / 9.2 KB / 18 KB | 3.9 KB / 12 KB / 21 KB | 27 / 88 / 144 |
| 10-99 | 3/12/16 | 2.2 KB / 3.2 KB / 3.6 KB | 2.7 KB / 3.7 KB / 4.1 KB | 19 / 28 / 31 |
| 100-999 | none | 26 KB / 81 KB / 252 KB | 33 KB / 104 KB / 284 KB | 247 / 766 / 1,405 |
| 100-999 | 3/12/16 | 3.1 KB / 3.6 KB / 3.9 KB | 3.6 KB / 4.1 KB / 4.5 KB | 27 / 31 / 31 |
| 1,000-9,999 | none | 198 KB / 720 KB / 2.7 MB | 268 KB / 906 KB / 3.1 MB | 1,999 / 6,882 / 17,366 |
| 1,000-9,999 | 3/12/16 | 2.8 KB / 3.3 KB / 3.9 KB | 3.2 KB / 3.8 KB / 4.5 KB | 24 / 29 / 31 |
| 10,000+ | none | 2.9 MB / 11.5 MB / 148 MB | 3.4 MB / 13.8 MB / 197 MB | 20,660 / 84,247 / 1,542,312 |
| 10,000+ | 500 | 110 KB / 124 KB / 125 KB | 127 KB / 142 KB / 144 KB | 1,030 / 1,047 / 1,048 |
| 10,000+ | 3/12/16 | 2.9 KB / 3.2 KB / 3.3 KB | 3.3 KB / 3.6 KB / 3.7 KB | 24 / 24 / 25 |
| 10,000+ | 6/12/16 | 3.3 KB / 3.6 KB / 3.9 KB | 3.7 KB / 4.0 KB / 4.4 KB | 24 / 25 / 34 |
| Largest 10 | 3/12/16 | 2.9 KB / 3.1 KB / 3.1 KB | 3.3 KB / 3.6 KB / 3.6 KB | 24 / 25 / 25 |

Every band and budget, including 500, 2,000, and 6/12/16 throughout, is in
[`results/payload.json`](gm-design-1h2l/results/payload.json). At S1's budget, every
artist's payload is under 4.5 KB, rank 1's included, against 148 MB with no budget. The
payload is bounded by the budget, not by the artist. The cost moves to the query, which
still reads every release of the root before it folds them (section 5).

## Verdict

**GO, with conditions.**

- **Ladder fit: GO, with three conditions.** For artists with 100 to 9,999 releases,
  masters cover 78-86% of releases (pooled), and a master holds a median of 2 releases
  (p99 32, max 1,542). That is a ladder worth drawing. It holds only if:
  1. Masterless releases are a first-class lane, not an edge case. They are 41.6% of
     all releases, and 71.5% of artists have no master at all.
  2. Undated releases get their own lane on the year axis. That is 7.8% of releases
     after the master-year fallback.
  3. The `0` master sentinel is removed from the graph before any strata query reads
     `DERIVED_FROM`. It holds 8,156,478 releases on the predecessor graph (section 1.4).
- **MusicBrainz-only releases: GO for 11.6%.** 462,111 of the 3,977,395 attach to a
  master, mostly through the release group's native-id alias (319,386). They come from
  PostgreSQL, not Neo4j, and they never carry collector state.
- **Transitions: observed only.** GrooveMap authors no collector state change. Every
  want and own transition is observed from Discogs sync. The state machine holds
  `none`, `wanted`, `owned`, and `wanted + owned`, connected only by observed edges.
  GrooveMap's authored actions are an observation on an owned copy and a sync request.
  The view must not imply that GrooveMap can write a wantlist or a collection.
  `date_added` was present on every synced row the predecessor holds (3,081 collection,
  737 wantlist, one user).
- **Latency: GO under 10,000 releases; GO with a cache from 10,000 releases; DEFER for
  roots above 134,051.** Measured on the predecessor graph, server-side.
  - Under 10,000 releases (all but 44 artists), a strata read costs at most 50 ms warm
    at p95, about 1.5 times Explore's open.
  - From 10,000 releases, a strata read costs 541 ms warm at p95 and up to 2.5 s cold,
    so it needs Explore's Valkey caching or a precomputed summary.
  - The two placeholder roots, at 1,356,055 and 87,683 releases, exist at that size only
    in GrooveMap's graph. They were measured at a tenth of their size and are not
    extrapolated.
- **Payload: GO.** At S1's 3/12/16 budget, every payload is under 4.5 KB.

## Recommendation

1. **Fix the `0` master at its source first.** `discogs-graph-enricher` should drop the
   `"0"` sentinel the way `discogs-sql-loader` already does, and a one-off cleanup
   should delete the `Master {id: '0'}` node and its edges. A filter in the strata
   query would only hide the problem, and every other `DERIVED_FROM` reader would still
   see 8.1 million fake siblings.
2. **M2 (catalog-api)** builds the route above.
   - `budget` defaults to S1's 3/12/16, and aggregates carry the `focus` id for paging.
   - Masterless and undated lanes are part of the contract, not fallbacks.
   - Collector state comes from the `COLLECTED` and `WANTS` edges `/api/user/collection`
     already reads, and `date_added` is shown as the collector's recorded time.
   - The strata answer is cached like `explore`. For roots of 10,000 releases or more,
     either the master plane comes from a precomputed per-artist summary, or the
     placeholder artists are refused or capped. That decision belongs to M2.
   - MusicBrainz-only releases join through the native-id path first. The
     release-group path needs an index on `musicbrainz.releases (release_group_mbid)`
     in `database-schema`.
   - Personnel edges key on bare roles or `CREDITED_ON.category`, never on raw role
     strings.
   - M2 repeats [`latency.py`](gm-design-1h2l/scripts/latency.py) on the first deployed
     environment, which will hold the placeholder roots at full size, and runs
     [`collector_time.sql`](gm-design-1h2l/scripts/collector_time.sql) there once real
     users have synced.
   - The upsert should keep a recorded `date_added` when a sync arrives without one
     (`COALESCE`, as it does for `formats`). Today it erases the value.
3. **M1 (ADR 0016)** records the collector machine as display-only with observed
   transitions. If GrooveMap is ever to author wants or owns, that takes its own
   decision: either a Discogs write integration, or a first-party wantlist outside
   Discogs. Strata cannot carry it.
4. **M3 (graph-explorer)** replaces the mockup's "Add to wantlist" and "Mark as
   collected" with "Open on Discogs", "Sync now", and, for an owned copy, "Record an
   observation".
