# Spike: identity history for concept D's ledger, without edition candidates

Status: **DEFER**. GrooveMap has never been deployed, so its history was predicted by
replaying the identity jobs over real dumps. One cycle after the first load, the replay
gives 1,204 release re-attachments. It gives only **743** works whose evented editions
change in more than one month, against a bar of 1,000. On this data, the history shows
no more than a log table would. The two MusicBrainz dumps still online are only 4 days
apart. Re-run the replay on one true monthly cycle once `discogs_20261101` is published.  
Superseded 2026-10-24: [gm-design-6b8u](gm-design-6b8u-strata-ledger-months.md) records the GO
on the history-only ledger, decided by ADR 0016's
[2026-10-24 amendment](../adr/0016-strata-graph-view.md#2026-10-24-concept-ds-backfill-branch-and-m6).  
Evidence date: 2026-10-23 (UTC)  
Spike: `gm-design-loj9` (epic `gm-design-uq8t`, concept D)  
Harness: [gm-design-loj9/](gm-design-loj9/README.md)  
Related: [ADR 0009](../adr/0009-native-identity-and-provider-aliases.md) and its
2026-09-25 amendment, [ADR 0014](../adr/0014-cross-catalog-edition-candidates.md)
sections 3, 6, and 8 and its amendments,
[gm-design-1wd.1](gm-design-1wd.1-unlinked-edition-candidates.md)

## Question

Concept D draws an identity ledger in `operations-console`. It has three planes: works,
then editions, then evidence. Discogs is on one side and MusicBrainz on the other, and node
color shows identity state over transaction time. ADR 0014 section 6 is at DEFER, so no
matching schema, candidate store, or review action may exist. The maintainer therefore
scoped D's first build to the identity history GrooveMap records without candidates:

- ADR 0009 supersessions, merges, and moves;
- ADR 0014 section 8 re-attachment runs and their audit rows;
- `provider_aliases` validity windows.

Would that history support a useful ledger? It is not GO if the data would show no more
than a log table would.

## Method

### What was read

The code and the schema were read at these commits. They are local checkouts of `main`,
all dated 2026-10-19 and all clean:

| Repository | Commit | Read for |
| --- | --- | --- |
| `database-schema` | `817081d` | `provider_aliases`, `catalog_items`, `catalog_item_supersessions`, `catalog_item_moves`, `admin_audit_log`, `resolve_catalog_item` (`src/groovemap_schema/postgres.py`, lines 340-720) |
| `catalog-api` | `957fe1f` | The section 8 job (`api/reattach.py`), the merge (`api/catalog_merge.py`), the automatic trigger (`api/reattach_trigger.py`), the audit writer (`api/audit_log.py`), the admin routes (`api/routers/admin.py`, lines 685-849), and `api/contracts/operations-console/v1/routes.json` |
| `musicbrainz-sql-loader` | `6c04255` | `_native_id` (`brainztableinator/_record_processing.py`, lines 279-304) |
| `musicbrainz-ingestion` | `6c6c284` | The Discogs id each MusicBrainz row carries (`src/musicbrainz/jsonl_parser.rs`, lines 45-60 and 216-228) |
| `discogs-sql-loader` | `e594106` | Minting in the batch writer (`tableinator/batch_writer.py`, lines 76-82), and identifier attach with its collision handling (`tableinator/identity.py`, lines 108-140) |
| `discogs-ingestion` | `ac08d5e` | Which dump records reach the loader (`src/discogs/mod.rs`, lines 658-662, and `extraction-rules.yaml`, lines 11-19) |
| `python-libraries` | `b976f89` | `resolve_aliases` and `attach_aliases`, whose `source` defaults to `catalog` (`src/common/identity.py`, lines 256 and 325) |
| `operations-console` | `5bf0f48` | Stack, page, proxy, contracts, Vitest, E2E, licences, and `AGENTS.md` |
| `deployment` | `4b120f4` | Post-import identity maintenance (`docs/maintenance.md`, lines 171-300) |

The concept D mockup is the local copy at
`~/.cache/groovemap-spikes/strata/groovemap-strata.html` (`CFG_D`). Its candidate-review
layer is out of scope here.

### No catalog exists, so the history is replayed

The maintainer confirmed that GrooveMap has never been deployed. `catalog_item_moves`,
the re-attachment audit rows, and `admin_audit_log` are therefore empty everywhere. A
read-only probe of the one catalog database reachable from this host agrees (section 1).
That database belongs to the predecessor system.

`scripts/replay.py` predicts the history instead. It replays the rules that decide each
identity write over two consecutive real dumps of each catalog, and counts what each step
would write. The modelled deployment follows the runbook's order: Discogs finishes before
MusicBrainz starts, and the re-attachment runs after both.

| Instant | Modelled month | Step | Dump |
| --- | --- | --- | --- |
| t1 | 1 | Discogs load | `discogs_20260901` (releases, masters, artists, labels) |
| t2 | 1 | MusicBrainz load | JSON dump `20261017-001001` (release, release-group, artist, label) |
| t3 | 1 | Re-attachment run R1 | |
| t4 | 2 | Discogs load | `discogs_20261001` |
| t5 | 2 | MusicBrainz load | JSON dump `20261021-001001` |
| t6 | 2 | Re-attachment run R2 | |

These are the only two MusicBrainz JSON dumps the server still lists. Older ones are
deleted, so the MusicBrainz interval is 4 days, not a month. The Discogs dumps are a month
apart. The calendar order is not real, because MusicBrainz `20261017` is newer than
Discogs `20261001`. The counts are well defined anyway: each one is what the code would
write given these dumps in this order.

Each rule replayed, and its source:

| Rule | Code |
| --- | --- |
| Every Discogs record mints an item under its `discogs` alias. A record already aliased mints nothing. A record missing from a later dump closes nothing | `discogs-sql-loader` `tableinator/batch_writer.py`, lines 76-82 (`resolve_aliases`); no code closes a `discogs` alias |
| Records that reach the loader: all of them, except artists and labels whose `profile` contains "DO NOT USE" | `discogs-ingestion` `src/discogs/mod.rs`, lines 658-662; `extraction-rules.yaml`, lines 11-19; `src/discogs/rules.rs`, lines 361-372 |
| A MusicBrainz row's Discogs id is the first `discogs` URL relation that parses as `https://www.discogs.com/<entity>/<id>[-slug]` | `musicbrainz-ingestion` `src/musicbrainz/jsonl_parser.rs`, lines 45-51, 58-60, and 216-228; entity per kind at lines 242, 288, 328, and 379 |
| A row whose Discogs id already resolves attaches its `musicbrainz` alias to that item. Otherwise it mints its own item | `musicbrainz-sql-loader` `_native_id`, lines 279-304 |
| A row already aliased keeps its item on every later load, whatever it now names | `attach_aliases` never overwrites (`python-libraries` `src/common/identity.py`, line 325; `ON CONFLICT DO NOTHING` at line 93) |
| Rows missing from a later dump stay in the table with their earlier values | The loader upserts; `brainztableinator/_reconciliation.py` deletes only relationship and external-link rows |
| Re-attachment candidates: the row's Discogs id resolves to item D, and its `musicbrainz` alias resolves to another item M | `catalog-api` `api/reattach.py`, `_LINKED` and `_CANDIDATE`, lines 166-192 |
| `shared_native_id` guard: M holds an alias that is not an identifier and not this row's. That is exactly the case where M is a Discogs item, because the row attached at ingest and later named another id. `non_catalog_alias` cannot hold | `_GUARDS`, lines 216-224; every writer uses `source = 'catalog'` |
| An eligible row's aliases close on M and reopen on D at one instant, and one supersession M → D opens. No merge conflict can arise, and no dependent moves | `reattach_item`, lines 480-553; `api/catalog_merge.py` `merge_items` |
| Kinds: release → Discogs release, release group → Discogs master, artist, and label | `KINDS`, lines 141-146 |

Not replayed:

- **Identifier aliases.** They open and close at the same instant as the alias they travel
  with, so they change no edition's instants. Counting them would mean replaying ADR
  0011's normalization of both catalogs' identifiers.
- **The stale `gm_item_id` race** that `api/reattach.py` heals. It needs concurrent
  writers.

`extract_mb.py` and `extract_discogs.py` copy the parsing rules, and do not import them.
The 20261001 releases came from gm-design-4804's stream of the same dump, an `.npz` with
`id` and `master` per release, to save a second request to the rate-limited Discogs
server. Its count, 19,492,392, matches the predecessor catalog's `public.releases`.
Every other input was streamed by this harness, and no dump was written to disk.

### Definitions

`scripts/reference.py` defines every ledger figure, and `sql/identity_history.sql`
computes the same object on a real catalog. `tests/test_sql_parity.py` holds the two equal
on a scratch PostgreSQL 18.6. `tests/test_replay.py` holds the replay's ledger equal to
`reference.py` applied to the rows the replay says the jobs would write.

- An **edition** is a release-kind native item, resolved one hop through an open
  supersession, as ADR 0009's amendment section 1 defines. A **work** is a master-kind
  item: a Discogs master and a MusicBrainz release group alias as `master`.
- An edition's **work parents** come from each catalog's own release row. A Discogs
  release names its master in `data ->> 'master_id'`. A MusicBrainz release names its
  release group in `release_group_mbid`. Each is resolved through its current alias.
- An edition's **instants** are the distinct transaction times recorded about it, or about
  an item superseded into it. The first instant is the mint. Each later instant is one
  **identity event**. An edition's **event months** are the months its events fall in, so
  a mint never counts as a month of change.
- A **moved alias** was opened or closed at the same `now()` as a supersession of its item.
  Both ADR 0014 transactions stamp all three with one instant (`_CLOSE_ALIASES` and
  `_REINSERT_ALIASES` in `api/reattach.py`, and `_OPEN` in `api/catalog_merge.py`).

### The GO bar, fixed before any history was read

A ledger shows more than a log table only if three things hold. Scrubbing transaction time
must change what a work looks like. More than one edition of a work must move. Something
other than the first load must have happened. The bar was fixed in this spike's first
submission (`5a37f19`), before the replay existed:

| | Condition | Figure | Bar |
| --- | --- | --- | --- |
| G1 | The history spans at least two re-attachment cycles | apply runs in distinct months | ≥ 2 |
| G2 | Works with two or more evented editions whose event months, taken together, number two or more | `ledger.works_with_2plus_evented_editions_multi_month` | ≥ 1,000 |
| G3 | Repairs, not only load order | release supersessions (`catalog_reattachment/release`) | ≥ 1,000 |

The 1,000 bars are this spike's proposal. A thousand works is the point where an operator
browses the ledger by work as routine. Below that, they are reading a short list of
exceptions. If G1 holds and G2 or G3 fails, the history shows no more than a log table,
and the verdict is not GO.

## Evidence

All counts in sections 2 to 4 are **predictions replayed from real dumps**
(`results/replay.json`), not measurements of a catalog.

### 1. No GrooveMap catalog exists

`results/probe.json` holds the read-only probe of the predecessor catalog, which is the
only one reachable. It has both catalogs' provider tables, and none of `catalog_items`,
`provider_aliases`, `catalog_item_supersessions`, or `catalog_item_moves`. Its
`admin_audit_log` has 0 rows. Its server has no GrooveMap database. Its Discogs data is
`discogs_20261001`: both its 19,492,392 releases and its 2,598,586 masters equal that
dump's counts. `results/identity_history.json` records `DEFER` for the direct measurement.
`sql/identity_history.sql` stays ready for the first real catalog.

### 2. What each run would write

| Kind | t2: linked at ingest | t2: own items minted | R1 | t4: new Discogs records | t5: linked at ingest | t5: own items minted | **R2: re-attached** (Discogs arrived / link added / link changed) | R2: guarded | Unresolved after R2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Release | 1,881,444 | 3,976,654 | 0 | 78,951 | 1,315 | 8,678 | **1,204** (682 / 522 / 0) | 5 | 6,607 |
| Release group | 348,399 | 4,235,510 | 0 | 9,639 | 38 | 8,057 | **337** (97 / 240 / 0) | 1 | 2,125 |
| Artist | 1,263,156 | 1,752,530 | 0 | 46,171 | 723 | 3,159 | **621** (203 / 416 / 2) | 19 | 13,100 |
| Label | 163,539 | 189,825 | 0 | 11,974 | 75 | 319 | **44** (11 / 33 / 0) | 4 | 1,570 |

- **R1 writes nothing.** After a staged first load, every row whose Discogs id resolves
  attached to it at ingest. The replay computes this rather than assuming it.
- **R2 writes 2,206 supersessions.** That is one `identity.reattach.apply` (or `.auto`)
  audit row with per-kind counts, and 0 moves, because a fresh deployment has no
  dependents.
- **"Discogs arrived"** means the row named a Discogs id missing from dump A and present
  in dump B. **"Link added"** means the row named no Discogs id in MusicBrainz `20261017`
  and named one in `20261021`. That is 4 days of MusicBrainz editing. The 1wd.1 spike
  measured 414 newly linked releases over a different 4 days (`20260919` to
  `20260923`).

### 3. Per source: rows, span, events per month

The modelled span is two months, one per cycle.

| Source | Month 1 (first load and R1) | Month 2 (second cycle and R2) |
| --- | ---: | ---: |
| `provider_aliases` opened (`discogs` and `musicbrainz` only) | 48,416,897 | 171,305 (including 2,206 re-opened by R2) |
| … releases | 25,275,165 | 90,148 |
| … release groups, artists, labels | 7,173,258 / 13,204,726 / 2,763,748 | 18,071 / 50,674 / 12,412 |
| `provider_aliases` closed | 0 | 2,206, all by re-attachment |
| `catalog_item_supersessions` opened | 0 | 2,206 (release 1,204, release group 337, artist 621, label 44) |
| `catalog_item_moves` | 0 | 0, by construction (no dependents) |
| `admin_audit_log` `identity.*` apply rows | 1 (R1, all zeros) | 1 (R2) |

Release events by month. These are the state changes the ledger would color:

| | Month 1 | Month 2 |
| --- | ---: | ---: |
| Linked at ingest | 1,881,444 | 1,315 |
| Re-attached (split → linked) | 0 | 1,204 |
| Own MusicBrainz items minted (a mint, not an event) | 3,976,654 | 8,678 |

The release ledger, from `results/replay.json` `ledger`:

| | Count |
| --- | ---: |
| Editions | 23,480,146 |
| … with at least one event | 1,867,008 |
| … repaired (a supersession) | 1,202 |
| … with events in both months | 542 |
| Works | 6,839,569 |
| **Works with two or more evented editions** | **259,935** |
| … whose events span both months (**G2**) | **743** |
| … with two or more repaired editions | 66 |
| Evented editions per work (50th, 90th, 99th percentile, max) | 1, 2, 5, 200 |
| Editions with no work parent / one / two or more | 7,453,079 / 15,462,400 / 564,667 |
| Split after R2 (guarded) / unresolved after R2 | 5 / 6,607 |

So 259,935 works do have two or more evented editions. But every event in nearly all of
them is a link at ingest from the first load. Scrubbing transaction time on such a work
shows one change, which a current-state view shows as well. After the first load, one
cycle adds about 2,500 release events, and only 743 works see their editions change in
both months.

### 4. Transition table

These are the identity states the history can record, without the matching schema. Each
row names the edge or rule that limits it. The last column gives the replayed count for
releases, or what the code allows.

| # | Transition | Recorded as | Limiting edge or rule | Releases, replayed |
| --- | --- | --- | --- | --- |
| 1 | → `discogs_only` or `musicbrainz_only` (minted) | `catalog_items.created_at` and the item's first alias `valid_from` | ADR 0009, "Minting happens at ingest". One current row per `(provider, entity_kind, external_id)` | Month 1: 19,417,067 Discogs, 3,976,654 MusicBrainz. Month 2: 78,951 and 8,678 |
| 2 | `discogs_only` → `linked` (linked at ingest) | The MusicBrainz alias's `valid_from` on the Discogs item | ADR 0014 Context: `_native_id` attaches only when the Discogs alias already resolves. `attach_aliases` never overwrites | Month 1: 1,881,444. Month 2: 1,315 |
| 3 | `musicbrainz_only` → `unresolved` | Nothing. Derived from the MusicBrainz row naming a Discogs id that has no alias | ADR 0014 Context. The row's `discogs_release_id` keeps no history, so past states use today's link | 6,607 after R2 |
| 4 | `unresolved` → `split` | Nothing of its own. The Discogs alias opens on a new item while the MusicBrainz alias is current on another | ADR 0014 Context, "Load order splits linked items" | 682 at t4 (then re-attached), plus 522 rows that gained a link |
| 5 | `split` → `linked`, the former item → `superseded` (re-attached) | A `catalog_item_supersessions` row whose `decision_ref` is the run's `admin_audit_log` id. Aliases close on the split item and reopen on the Discogs item at the same instant | ADR 0014 section 8. ADR 0009 amendment section 1 (one hop; the item is kept, never deleted) and section 3 (steps 4-7 in the same transaction). One run per Discogs extraction | R1: 0. R2: 1,204 |
| 6 | `split` → `split` (guarded) | No per-item row. `guard_reasons` per kind, in the run's audit details | The `shared_native_id` and `non_catalog_alias` guards (`api/reattach.py`, lines 43-50). `non_catalog_alias` cannot fire, because no writer asserts `user` or `inference` aliases | 5, and only as a per-run count |
| 7 | Identifier alias moved, or lost to a collision, at re-attachment | Alias rows. Collisions appear only as run counts (`identifier_collisions`) | The section 8 identifier-alias rule and the partial unique index. Load-time collisions are only logged (`discogs-sql-loader`, `tableinator/identity.py`) | Not replayed. These rows move at the row-5 instant |
| 8 | Merged with dependents | `catalog_item_moves` | ADR 0009 amendment section 2. Erased with the user under ADR 0010 | **0 by construction.** No writer creates artifacts. Owned copies follow the Discogs release alias (`api/syncer.py`, lines 167-172), which never sits on a superseded item |
| 9 | Chain compressed | `via_id` | ADR 0009 amendment section 1. A chain needs the superseded item to be a current survivor. Survivors hold a Discogs alias, and the `shared_native_id` guard refuses any split item that holds one | **0 by construction** |
| 10 | `linked` → `split`, or the former item → itself (reverted) | Supersession `valid_to` | ADR 0009 amendment section 1 (reversal). Only the ADR 0014 section 3 revert and the section 8 contradiction revert call `revert_supersession`, and both need a promotion | **0 by construction**: no caller |
| 11 | Promoted (`edition_promotion`) | Supersession `cause` | ADR 0014 section 3, gated by section 6 (DEFER) | 0. Out of scope |
| 12 | Alias closed by a provider's own merge or split | Nothing. 3,626 Discogs releases in dump A are missing from dump B, and their aliases stay open | ADR 0009 amendment section 5: another cause joins only by amendment | 0. No writer |
| 13 | A Discogs item superseded (the mockup's "duplicate entry") | Nothing | ADR 0009 amendment: "in both the MusicBrainz side's native item is the one superseded" | **Impossible**. The mockup must change |

The acceptance names five states: merged, superseded, re-attached, reverted, and alias
opened or closed. In GrooveMap's code, superseded and re-attached are one event (row 5).
Alias opens are ingest (rows 1 and 2) or re-attachment (row 5). Alias closes are
re-attachment only. Merged (row 8) and reverted (row 10) are zero by construction. The
history-only ledger therefore has six edition states (`not_recorded`, `discogs_only`,
`musicbrainz_only`, `unresolved`, `split`, `linked`), plus `superseded` for former items.
It has exactly **one recorded repair transition**. Nothing in this table reads or depends
on the matching schema.

### 5. The work → edition → evidence ladder

The replay gives 564,667 editions two or more work parents. The predecessor catalog's own
links, read by `sql/link_structure.sql` (`results/link_structure.json`), give the same
picture. That is the same `discogs_20261001` data with that system's MusicBrainz snapshot.
Two runs gave identical figures:

| | Count | Share |
| --- | ---: | ---: |
| MusicBrainz releases | 5,846,849 | |
| … naming a Discogs release | 1,885,908 | 32.26% |
| … whose Discogs release is loaded (would link at ingest) | 1,879,464 | |
| … whose Discogs release is missing (would be `unresolved`, then split) | 6,444 | 0.34% of named |
| Discogs releases named by two or more MusicBrainz releases (one edition, two MusicBrainz rows) | 17,085 | 0.92% of 1,861,852 |

How each linked, loaded edition's two work parents relate (n = 1,879,464):

| Discogs release's master vs. MusicBrainz release group's Discogs master | Count | Share |
| --- | ---: | ---: |
| Same master: one work parent | 653,532 | 34.77% |
| The release group names no master, but the release has one: **two work parents** | 558,092 | 29.69% |
| Different masters: **two work parents** | 8,583 | 0.46% |
| The release has no master, but the release group names one | 2,653 | 0.14% |
| Neither has a master: one work parent (the release group's own item) | 656,604 | 34.94% |
| **Two work parents** (the master is loaded and the two parents differ) | **566,661** | **30.15%** |

So the ladder does **not** hold as a tree. Three planes must change:

- **Works.** A linked work is one native item that holds both aliases. A release group
  with no Discogs master is a work of its own. For 30% of cross-linked editions it is a
  second parent, and only a candidate could join it, which is out of scope. The edition
  plane is therefore a DAG under the works plane. The Strata invariant says a group's hull
  contains only its own descendants. Under that rule, a two-parent edition needs a primary
  parent: the Discogs master, because the survivor is always on the Discogs side. Its
  second parent is drawn as a cross-hull edge with an explicit `work_disagreement` state.
  A log table cannot show that, but it is a current-state fact. The history records no
  time at which the parents diverged.
- **Editions.** A linked edition is one native item with two provider rows, not two nodes
  joined by an edge. The two-sided layout stays, with provider rows as the two halves of
  one node. A re-attached edition gains a former item on the MusicBrainz side, with a
  "superseded by" edge. The mockup's Discogs-side `superseded` node (row 13) goes.
- **Evidence.** An item's alias rows, with their validity windows. The partial unique
  index means one identifier value is held by one item at a time. A collision at load is
  logged, not stored. So the mockup's lateral "same identifier" edges cannot come from
  history. They could only be computed from the provider records, as a current-state
  overlay with no transaction time.

Valid time (release year) comes from the provider records. Transaction time comes from
alias and supersession intervals. The work → edition edges have no transaction time,
because loaders overwrite the provider rows.

### 6. Draft admin route and payload

Three operations would be added to `catalog-api`'s `api/contracts/operations-console/v1/routes.json`.
Additions are compatible within v1:

| Operation | Method and path | Returns |
| --- | --- | --- |
| `admin_identity_ledger_works` | `GET /api/admin/identity/ledger/works?event=&since=&until=&page=&page_size=` | Works that have evented editions, paged like `admin_audit_log` (`page_size` ≤ 100). Each row: `gm_id`, `providers`, `editions`, `evented_editions`, `repaired_editions`, `work_disagreements`, `first_event`, `last_event` |
| `admin_identity_ledger_work` | `GET /api/admin/identity/ledger/works/{work_id}?as_of=&edition_limit=` | One work's three planes at `as_of` (transaction time, RFC 3339; omitted means now) |
| `admin_identity_ledger_density` | `GET /api/admin/identity/ledger/density?kind=` | Events per month by type, the scale of the transaction-time axis. It is the `identity_history.sql` aggregate |

`scripts/payload.py` builds `admin_identity_ledger_work` from history-only rows, and
`results/example_payload_work.json` shows it for an invented work. It has this shape:

```text
work:     gm_id, [requested_id], state, providers[{provider, external_id, valid_from, valid_to}]
as_of, edition_count, truncated
editions[]:
  gm_id, state, works[], work_disagreement
  provider_rows[{provider, external_id, [names_discogs_release]}]
  former_items[{gm_id, superseded_at, cause, decision_ref}]
  evidence[{provider, external_id, source, held_by, valid_from, valid_to,
            opened_by: mint|later|supersession, closed_by: null|supersession|other}]
  events[{at, type, rule, ...}]
    type: minted | linked_at_ingest | reattached | evidence_attached | promoted | reverted | alias_closed
```

`tests/test_payload.py` fixes the rules the route must keep:

- **Admin only.** `require_admin`, like every admin route.
- **PostgreSQL, read-only.** The identity authority is PostgreSQL (ADR 0009: the alias
  table "remains the authority"). Neo4j holds only the current `gm_id` projection, with no
  history. This departs from the epic's rule that Strata routes are Neo4j queries. The
  decision bead and ADR 0016 should record that the departure is deliberate.
- **One-hop resolution.** ADR 0009 amendment section 4 applies: a superseded `work_id`
  answers `200` as the survivor, with `requested_id`. An unknown id is `404`, and there are
  no redirects.
- **No user data.** Moves appear only as per-table counts on each supersession. No user id,
  owned-copy id, artifact id, or admin id is emitted. `decision_ref` names the audit entry.
- **States move with `as_of`.** The re-attached edition reads `unresolved`, then `split`,
  then `linked` (`test_reattached_edition_walks_unresolved_split_linked`).
- **Bounded.** `edition_limit` caps the editions, and `truncated` reports it. The largest
  work in the link data has 200 linked editions.

`operations-console` also needs a re-promotion. Its pinned copy of the contract
(`contracts/catalog-api/operations-console/v1/source.json`, producer `bc684e9`) predates
`admin_identity_project`, and holds 22 operations to the producer's 23. Its proxy
(`dashboard/admin_proxy.py`) forwards each route explicitly. Its path-segment allowlist
`^[a-zA-Z0-9._-]+$` accepts a UUID. `as_of` must be forwarded as a query parameter.

### 7. Operations-console constraints S1's engine distribution must meet

S1 is `gm-design-on0x`. Whatever it recommends for graph-explorer must also land here:

1. **No cross-repository source.** `AGENTS.md` forbids a relative import or a Docker
   build-context dependency on another GrooveMap repository. The engine must arrive as an
   artifact the console pins itself. That can be a vendored file with commit and digest
   provenance, as brand assets come in through `scripts/promote-brand.sh` and contracts
   through `source.json` digests. It can be an npm dependency in `package-lock.json`. Or it
   can be a CDN URL with SRI, as Chart.js, Luxon, and the Luxon adapter are today
   (`dashboard/static/admin.html`, lines 8-10).
2. **Static, unbundled, classic scripts.** FastAPI `StaticFiles` serves `dashboard/static/`
   from the wheel (`dashboard/dashboard.py`, line 793). npm runs only the Tailwind build and
   Vitest. The
   page loads `admin.js` as a classic `<script>` (line 1057). There is no ES module, import
   map, or worker today. An ES-module engine needs `type="module"` plus relative imports or
   an import map. A worker must be a same-origin file.
3. **CSP-ready, though there is no CSP yet.** No header middleware, meta tag, or
   deployment proxy sets a Content-Security-Policy. The engine must still run under
   `script-src 'self'`, plus the pinned CDN host if it uses one, with no `eval`, no
   `new Function`, and no inline script. Then a later CSP will not break it. The
   jsdelivr scripts already in use would need allow-listing too.
4. **Licence recorded.** The console is `AGPL-3.0-only`. `THIRD_PARTY_NOTICES.md` records
   its dependencies, but does not list the three CDN libraries today, which is a gap. The
   engine needs a compatible permissive licence and an entry there. `just license-check`
   covers Python only.
5. **Testable without WebGL.** Vitest 5 runs in jsdom (`vitest.config.mjs`), and jsdom has
   no WebGL. The layout and state modules must import and test without a GL context.
   Coverage includes `dashboard/static/**/*.js`, so a vendored engine under `static/` must
   be excluded, or it will dominate the 80% patch target.
6. **Five browser projects.** `scripts/run-e2e-matrix.sh` runs chromium, firefox, webkit,
   iphone, and ipad. The engine must render in all five, or fall back to the accessible
   table. E2E coverage instruments only `admin.js` and `dashboard.js`
   (`scripts/e2e-coverage-sources.mjs`, line 9), so new modules must be added there.
7. **Hidden-tab mount.** `admin.html` is one page whose tabs start `display:none`. The
   engine must size itself when its tab is first shown, not at load.

## Verdict

**DEFER** for the history-only ledger. On the replayed data it is not GO.

| | Figure | Replayed | Bar | |
| --- | --- | ---: | ---: | --- |
| G1 | Apply runs in distinct months, with a run that writes something | 2 (R2 writes 2,206) | ≥ 2 | holds |
| G2 | Works with two or more evented editions spanning both months | **743** | ≥ 1,000 | **fails** |
| G3 | Release re-attachments | 1,204 | ≥ 1,000 | holds |

- **The history is one burst and then a trickle.** The first load opens 48.4 million alias
  rows and links 1.88 million releases at ingest, all in one month. After that, one cycle
  adds 171,305 alias rows. Nearly all of them mint new records that nothing else touches.
  The cycle adds 2,206 supersessions across the four kinds, and about 2,500 release events.
  Of the 259,935 works with two or more evented editions, only 743 show any change after
  the first load. The ledger's transaction-time axis would therefore show almost every work
  as a snapshot. A table of supersessions and runs carries that history as well.
- **The code sets a low ceiling.** The state machine has one repair transition (row 5).
  Merges, reverts, chains, and promotions are zero by construction. Guarded and failed
  items leave no per-item trace.
- **What planes would show is current state, not history.** 564,667 editions have two
  work parents. That is the strongest thing a layered view would show that a table would
  not, but the history records no time for it.
- **Why DEFER and not a final answer.** The MusicBrainz side of the replayed cycle covers 4
  days, not a month, because MusicBrainz deletes older JSON dumps. Every "link added"
  re-attachment comes from that interval: 522 for releases. A true monthly cycle would
  add more. This replay cannot say how many, and it does not estimate it. G2 missed by 257
  works.

## Recommendation

1. **Re-run the replay on one true monthly cycle, with no code changes.** Use Discogs
   `20261001` with MusicBrainz `20261021` as cycle A. Their compact TSVs are kept in
   `~/.cache/groovemap-spikes/gm-design-loj9/data/`. Use `discogs_20261101`, with the first
   MusicBrainz JSON dump after it, as cycle B. MusicBrainz deletes old dumps, so stream the
   B dump within days of its publication. The README gives the commands. If G2 still falls
   below 1,000, the history shows no more than a log table. The decision bead
   `gm-design-7xo5` should then plan D's first build as an audit-style table over
   supersessions and runs, and leave the Strata ledger to wait for the candidate layer.
2. **If the re-run is GO, M6 carries these from this spike.**
   - The route is PostgreSQL, not Neo4j. Record that in ADR 0016.
   - Use the state vocabulary in section 4.
   - `work_disagreement` becomes an edge state, and the layout follows the primary-parent
     rule.
   - Drop the lateral identifier edges.
   - Drop the mockup's Discogs-side `superseded` state.
   - Add the three operations to the contract, then re-promote it in `operations-console`.
3. **Catalog-api changes that would deepen the history without candidates.** These are
   planning inputs and are not filed:
   - persist per-item guard and failure outcomes, so that `guarded` becomes a recorded
     state;
   - persist each dry run's census, so that `unresolved` and `split` counts gain
     transaction time;
   - record the projection's counts.

   None of these carries user data, so they need not live in `admin_audit_log`, which
   outlives erasure.
4. **When a GrooveMap catalog exists,** run `scripts/measure.py` against it read-only.
   That replaces this prediction with a measurement.
5. **S1 (`gm-design-on0x`)**: meet the seven constraints in section 7.

## Missing evidence and failure modes

- **These counts are predictions.** They are the rules replayed over dumps, not a catalog.
  The replay's ledger figures equal `reference.py` on the rows it implies
  (`tests/test_replay.py`). Each rule's outcome on hand-built dumps is pinned in the same
  file. The rules themselves are restated from the cited code, not executed.
- **The calendar is not real.** MusicBrainz `20261017` postdates Discogs `20261001`. So
  links that a calendar-true deployment would see as "link added" in month 2 appear here as
  links at ingest in month 1.
- **One instant per step.** A real load writes over many transactions. Months are
  unaffected, but an edition's event count can only be undercounted, and only where two
  writes to it share a step.
- **Not replayed:** identifier aliases (they move at the same instant as their row) and
  the stale `gm_item_id` race.
- **Past states use today's links.** `discogs_release_id`, `release_group_mbid`, and
  `master_id` keep no history.
- **Erasure removes moves.** `catalog_item_moves` loses a user's rows on erasure. Audit
  counts survive.
- **The audit route shows 90 days by default.** No retention purge exists, so the ledger
  route must not rely on that window.

No id from either catalog, no row, and no audit entry is committed. The `results/`
files hold counts, and payloads built from invented data. No product code changed in any
repository, and no bead was filed.

## Sources

- [ADR 0009](../adr/0009-native-identity-and-provider-aliases.md), 2026-09-25 amendment,
  sections 1 to 5
- [ADR 0014](../adr/0014-cross-catalog-edition-candidates.md): Context, sections 3, 6, and
  8, and the 2026-09-25 amendments
- Discogs data dumps: [data.discogs.com](https://data.discogs.com/) (`discogs_20260901_*`,
  `discogs_20261001_*`)
- MusicBrainz JSON dumps: [data.metabrainz.org json-dumps](https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/)
  (`20261017-001001`, `20261021-001001`)
- Prior spike: [gm-design-1wd.1](gm-design-1wd.1-unlinked-edition-candidates.md)
- Harness, SQL, and aggregate results: [gm-design-loj9/](gm-design-loj9/README.md)
