# Spike: identity history for concept D's ledger, without edition candidates

Status: **DEFER**. No reachable database holds GrooveMap identity history, so no volume
is measured or estimated. Read the volumes once a GrooveMap catalog has run two Discogs
import cycles with re-attachment applied, and judge them against the bar fixed below.  
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
scoped D's first build to the identity history GrooveMap already records:

- ADR 0009 supersessions, merges, and moves;
- ADR 0014 section 8 re-attachment runs and their audit rows;
- `provider_aliases` validity windows.

Is that history rich enough for a useful ledger? It is not GO if the data would show no
more than a log table would.

## Method

### What was read

The code and the schema were read at these commits. They are local checkouts of `main`,
all dated 2026-10-19 and all clean:

| Repository | Commit | Read for |
| --- | --- | --- |
| `database-schema` | `817081d` | `provider_aliases`, `catalog_items`, `catalog_item_supersessions`, `catalog_item_moves`, `admin_audit_log`, `resolve_catalog_item` (`src/groovemap_schema/postgres.py`, lines 340-720) |
| `catalog-api` | `957fe1f` | The section 8 job (`api/reattach.py`), the merge (`api/catalog_merge.py`), the automatic trigger (`api/reattach_trigger.py`), the audit writer (`api/audit_log.py`), the admin routes (`api/routers/admin.py`, lines 685-849), and `api/contracts/operations-console/v1/routes.json` |
| `musicbrainz-sql-loader` | `6c04255` | `_native_id` (`brainztableinator/_record_processing.py`, lines 279-304) |
| `discogs-sql-loader` | `e594106` | Identifier attach and its collision handling (`tableinator/identity.py`, lines 108-140) |
| `python-libraries` | `b976f89` | `attach_aliases`, whose `source` defaults to `catalog` (`src/common/identity.py`, line 325) |
| `operations-console` | `5bf0f48` | Stack, page, proxy, contracts, Vitest, E2E, licences, and `AGENTS.md` |
| `deployment` | `4b120f4` | Post-import identity maintenance (`docs/maintenance.md`, lines 171-300) |

The concept D mockup is the local copy at
`~/.cache/groovemap-spikes/strata/groovemap-strata.html` (`CFG_D`). Its candidate-review
layer is out of scope here.

### Database access

The rule was to measure a real catalog read-only, without hunting for credentials. One
catalog database was reachable. It is the predecessor system's database on the homelab,
which an earlier session had already measured for the deployment runbook. It is reached
over SSH with key authentication and `docker exec psql`, and needs no password. That
PostgreSQL 18.6 server has no GrooveMap catalog database. Its database list holds the
predecessor catalog and other applications' databases only.

Every statement ran through `scripts/run_sql.sh`, inside a `REPEATABLE READ, READ ONLY`
transaction with a statement timeout. On the parity database, that wrapper rejects an
`INSERT` with `cannot execute INSERT in a read-only transaction`. Only aggregates left
the server. `scripts/measure.py` refuses to write any value that looks like a UUID, a bare
numeric id, or an email address.

### Definitions

`scripts/reference.py` defines every figure, and `sql/identity_history.sql` computes the
same object. On both fixture variants, `tests/test_sql_parity.py` holds the two equal on a
scratch PostgreSQL 18.6.

- An **edition** is a release-kind native item, resolved one hop through an open
  supersession, as ADR 0009's amendment section 1 defines. A **work** is a master-kind
  item: a Discogs master and a MusicBrainz release group alias as `master`.
- An edition's **work parents** come from each catalog's own release row. A Discogs
  release names its master in `data ->> 'master_id'`. A MusicBrainz release names its
  release group in `release_group_mbid`. Each is resolved through its current alias.
- An edition's **instants** are the distinct transaction times recorded about it, or about
  an item superseded into it. They are alias `valid_from` and `valid_to`, supersession
  `valid_from` and `valid_to`, and move `moved_at`. The first instant is the mint. Each
  later instant is one **identity event**. An edition's **event months** are the months its
  events fall in, so a mint never counts as a month of change.
- A **moved alias** was opened or closed at the same `now()` as a supersession of its item.
  Both ADR 0014 transactions stamp all three with one transaction instant
  (`_CLOSE_ALIASES` and `_REINSERT_ALIASES` in `api/reattach.py`, and `_OPEN` in
  `api/catalog_merge.py`). Any other alias opened after the mint was attached later.

### The GO bar, fixed before any history is read

A ledger shows more than a log table only if three things hold. Scrubbing transaction time
must change what a work looks like. More than one edition of a work must move. Something
other than the first load must have happened. Each condition is one figure from
`results/identity_history.json`:

| | Condition | Figure | Bar |
| --- | --- | --- | --- |
| G1 | The history spans at least two re-attachment cycles | `admin_audit_log_identity.apply_run_months` | ≥ 2 |
| G2 | Works with two or more evented editions whose event months, taken together, number two or more | `ledger.works_with_2plus_evented_editions_multi_month` | ≥ 1,000 |
| G3 | Repairs, not only load order | `transitions.superseded["catalog_reattachment/release"]` | ≥ 1,000 |

The 1,000 bars are this spike's proposal. A thousand works is the point where an operator
browses the ledger by work as routine. Below that, they are reading a short list of
exceptions. The decision bead `gm-design-7xo5` may change any bar, but only before the
re-run. If G1 fails, the verdict stays DEFER for another cycle. If G1 holds and G2 or G3
fails, the history shows no more than a log table, and the verdict is not GO.

## Evidence

### 1. No reachable catalog holds identity history

`results/probe.json`:

| Table | Predecessor catalog |
| --- | --- |
| `catalog_items`, `provider_aliases`, `catalog_item_supersessions`, `catalog_item_moves` | absent |
| `admin_audit_log` | present, **0 rows** (0 `identity.*` rows) |
| `releases`, `masters`, `musicbrainz.releases`, `musicbrainz.release_groups` | present |

The predecessor catalog was loaded before native identity existed. It has both catalogs'
provider tables and none of the identity tables. `results/identity_history.json` records
`DEFER` with the four missing tables. The code also bounds the time span. The alias tables
landed in `database-schema` on 2026-09-13 (`d90d666`). Supersessions, moves, and the
resolution landed on 2026-09-25 (`c2af4e2`), as did the re-attachment job, the merge, and
the trigger in `catalog-api`. No GrooveMap history can be older than those dates.

### 2. Per source: what is measured, and what the code guarantees

| Source | Rows, span, events per month | Works with ≥ 2 evented editions | What the code guarantees today |
| --- | --- | --- | --- |
| `provider_aliases` | DEFER | DEFER | `valid_from` is the first assertion. The insert is `ON CONFLICT DO NOTHING`, so a reload never reopens a row. `valid_to` is written only by the section 8 job's `_CLOSE_ALIASES`, and by `revert_supersession`, which has no caller. So every close is a re-attachment. Every row has `source = 'catalog'`, because no writer passes `user` or `inference`. Density follows the loads: one burst for the staged first load, then one per new dump. The extractors check every 5 days (Discogs) and 3 days (MusicBrainz), by `PERIODIC_CHECK_DAYS`. Discogs publishes monthly, and MusicBrainz twice a week |
| `catalog_item_supersessions` | DEFER | DEFER | Only `cause = 'catalog_reattachment'` can occur. `edition_promotion` needs the ADR 0014 section 3 action, which section 6 forbids. `valid_to` is never set. `via_id` is never set (row 9 of the transition table). Rows arrive in one burst per applying run, and an automatic run happens once per completed Discogs extraction (`api/reattach_trigger.py`) |
| `catalog_item_moves` | DEFER | DEFER | **Empty by construction.** Moves are rows of `artifacts` or `owned_copies` that point at the superseded MusicBrainz-side item. No writer creates artifacts. The sync creates owned copies only from collection rows that resolve through the Discogs release alias (`api/syncer.py`, lines 167-172), and that alias never sits on the superseded item. Erasure also deletes a user's rows (ADR 0010), so this is not durable history |
| `admin_audit_log` (`identity.*`) | DEFER (the reachable table has 0 rows) | not applicable: no item ids | Each run has one `identity.reattach.apply` row (or `.auto` for the trigger) with per-kind counts. Also written are `.started`, `.failed`, `identity.reattach.trigger`, and `identity.project.trigger`. **No per-item record exists.** Guarded and failed items appear only in structured logs (`api/reattach.py`, `logger.info` and `logger.error`). Dry-run censuses are logged, not stored, and the projection's counts are not stored |

The volumes are DEFER, and none is estimated. One fact from the link data below bounds
them from above. Every cross-catalog identity event starts from a MusicBrainz row that
names a Discogs counterpart.

### 3. Transition table

These are the identity states the history can record, without the matching schema. Each
row names the edge or rule that limits it. "Today" counts what the code can write; counts
from the predecessor link data are labelled as such.

| # | Transition | Recorded as | Limiting edge or rule | Today |
| --- | --- | --- | --- | --- |
| 1 | → `discogs_only` or `musicbrainz_only` (minted) | `catalog_items.created_at` and the item's first alias `valid_from` | ADR 0009, "Minting happens at ingest". One current row per `(provider, entity_kind, external_id)` | Every item. One burst per load |
| 2 | `discogs_only` → `linked` (linked at ingest) | The MusicBrainz alias's `valid_from` on the Discogs item | ADR 0014 Context: `_native_id` attaches only when the Discogs alias already resolves. `attach_aliases` never overwrites | Ceiling: **1,879,464** linked releases in the predecessor link data. On a staged first load, nearly all of them arrive within the one MusicBrainz load window |
| 3 | `musicbrainz_only` → `unresolved` | Nothing. Derived from the MusicBrainz row naming a Discogs id that has no alias | ADR 0014 Context. The row's `discogs_release_id` keeps no history, so past states use today's link | **6,444** releases and **2,107** release groups in the predecessor link data |
| 4 | `unresolved` → `split` | Nothing of its own. The Discogs alias opens on a new item while the MusicBrainz alias is current on another | ADR 0014 Context, "Load order splits linked items" | DEFER |
| 5 | `split` → `linked`, the former item → `superseded` (re-attached) | A `catalog_item_supersessions` row whose `decision_ref` is the run's `admin_audit_log` id. Aliases close on the split item and reopen on the Discogs item at the same instant | ADR 0014 section 8. ADR 0009 amendment section 1 (one hop; the item is kept, never deleted) and section 3 (steps 4-7 in the same transaction). One run per Discogs extraction | DEFER |
| 6 | `split` → `split` (guarded) | No per-item row. `guard_reasons` per kind, in the run's audit details | The `shared_native_id` and `non_catalog_alias` guards (`api/reattach.py`, lines 43-50). `non_catalog_alias` cannot fire, because no writer asserts `user` or `inference` aliases | DEFER, and only per run |
| 7 | Identifier alias moved, or lost to a collision, at re-attachment | Alias rows. Collisions appear only as run counts (`identifier_collisions`) | The section 8 identifier-alias rule and the partial unique index. Load-time collisions are only logged (`discogs-sql-loader`, `tableinator/identity.py`) | DEFER |
| 8 | Merged with dependents | `catalog_item_moves` | ADR 0009 amendment section 2. Erased with the user under ADR 0010 | **0 by construction** (see section 2) |
| 9 | Chain compressed | `via_id` | ADR 0009 amendment section 1. A chain needs the superseded item to be a current survivor. Survivors hold a Discogs alias, and the `shared_native_id` guard refuses any split item that holds one | **0 by construction** |
| 10 | `linked` → `split`, or the former item → itself (reverted) | Supersession `valid_to` | ADR 0009 amendment section 1 (reversal). Only the ADR 0014 section 3 revert and the section 8 contradiction revert call `revert_supersession`, and both need a promotion | **0 by construction**: no caller |
| 11 | Promoted (`edition_promotion`) | Supersession `cause` | ADR 0014 section 3, gated by section 6 (DEFER) | 0. Out of scope |
| 12 | Alias closed by a provider's own merge or split | Nothing | ADR 0009 amendment section 5: another cause joins only by amendment | 0. No writer |
| 13 | A Discogs item superseded (the mockup's "duplicate entry") | Nothing | ADR 0009 amendment: "in both the MusicBrainz side's native item is the one superseded" | **Impossible**. The mockup must change |

The acceptance names five states: merged, superseded, re-attached, reverted, and alias
opened or closed. In GrooveMap's code, superseded and re-attached are one event (row 5).
Alias opens are ingest (rows 1 and 2) or re-attachment (rows 5 and 7). Alias closes are
re-attachment only. Merged (row 8) and reverted (row 10) are zero by construction. The
history-only ledger therefore has six edition states (`not_recorded`, `discogs_only`,
`musicbrainz_only`, `unresolved`, `split`, `linked`), plus `superseded` for former items.
It has exactly **one recorded repair transition**. Nothing in this table reads or depends
on the matching schema.

### 4. The work → edition → evidence ladder on real link data

The history cannot be measured, but the link structure it grows from can be.
`sql/link_structure.sql` read the predecessor catalog's provider tables. These are the
same dumps and the same tables that GrooveMap's loaders fill. `results/link_structure.json`
holds the output, and two runs gave identical figures:

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

Works with cross-linked editions are Discogs masters with at least one linked, loaded
release. There are **784,601** of them, of 2,598,586 masters. **203,279** have two or more
linked editions. Per work, the 50th percentile is 1, the 90th is 2, the 99th is 8, and the
maximum is 200. Of 4,577,536 release groups, 350,041 (7.65%) name a Discogs master.

So the ladder does **not** hold as a tree on this data. Three planes must change:

- **Works.** A linked work is one native item that holds both aliases. A release group
  with no Discogs master is a work of its own. For 30% of cross-linked editions it is a
  second parent, and only a candidate could join it, which is out of scope. The edition
  plane is therefore a DAG under the works plane. The Strata invariant says a group's hull
  contains only its own descendants. Under that rule, a two-parent edition needs a primary
  parent: the Discogs master, because the survivor is always on the Discogs side. Its
  second parent is drawn as a cross-hull edge with an explicit `work_disagreement` state.
  A log table cannot show that, and it is the strongest case for planes here. But it is
  a current-state fact. The history records no time at which the parents diverged.
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
alias and supersession intervals. The work → edition edges have no transaction time at
all, because loaders overwrite the provider rows.

### 5. Draft admin route and payload

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

### 6. Operations-console constraints S1's engine distribution must meet

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

**DEFER** for the history-only ledger.

- **Volumes: not measurable.** The only reachable catalog has none of the identity tables,
  and no GrooveMap catalog database exists on that server. Every per-source volume, and the
  count of works with two or more evented editions, is DEFER. None is estimated.
- **The code sets a low ceiling.** Of the five states the acceptance names, today's code
  can record alias opens at ingest, links at ingest, and one repair: a re-attachment, which
  is also the supersession. Merges with dependents, reverts, chains, and promotions are
  zero by construction. A run's guarded and failed items leave no per-item trace. So the
  history-only state machine has one repair transition, recorded in monthly bursts.
  Whether that is more than a log table depends on G2 and G3. The structure alone does
  not answer it in either direction.
- **The link data shows a real work-level split.** 566,661 cross-linked editions (30.15%)
  would have two work parents, and 203,279 works have two or more linked editions. A log
  table cannot show either fact. Both are current state, though, not history. The history
  shows them only where those editions' events fall in more than one month. A staged first
  load puts the links at ingest into one MusicBrainz load window, so G2 depends on the
  re-attachments and later attaches of the cycles after it.

## Recommendation

1. **Access needed from the maintainer: a read-only role on a GrooveMap catalog.**
   `pg_read_all_data` is enough, or `SELECT` on the tables the README lists. The database
   must have run the staged first load, Discogs and then MusicBrainz. It must also have run
   at least **two** Discogs import cycles with an applying re-attachment after each, either
   manual or with `IDENTITY_AUTO_REATTACH_ENABLED=true`. One cycle cannot meet G1. Then run
   `scripts/measure.py` without changing code, and read G1 to G3. No such database exists
   on the reachable server today.
2. **Decision bead `gm-design-7xo5`: confirm or change G1 to G3 before the re-run.** If
   G1 holds and G2 or G3 fails, D's first build should not be a Strata view. It would be
   an audit-style table over supersessions and runs. The Strata ledger would then wait for
   the candidate layer.
3. **If GO, M6 carries these from this spike.**
   - The route is PostgreSQL, not Neo4j. Record that in ADR 0016.
   - Use the state vocabulary in section 3.
   - `work_disagreement` becomes an edge state, and the layout follows the primary-parent
     rule.
   - Drop the lateral identifier edges.
   - Drop the mockup's Discogs-side `superseded` state.
   - Add the three operations to the contract, then re-promote it in `operations-console`.
4. **Catalog-api changes that would deepen the history without candidates.** These are
   planning inputs and are not filed:
   - persist per-item guard and failure outcomes, so that `guarded` becomes a recorded
     state;
   - persist the census of each dry run;
   - record the projection's counts.

   None of these carries user data, so they need not live in `admin_audit_log`, which
   outlives erasure.
5. **S1 (`gm-design-on0x`)**: meet the seven constraints in section 6.

## Missing evidence and failure modes

- **The link data is the predecessor's, not GrooveMap's.** It is the same dumps, tables,
  and column semantics, but it reflects that system's load dates. GrooveMap's first load
  would see its own dump dates.
- **Past states use today's links.** `discogs_release_id`, `release_group_mbid`, and
  `master_id` keep no history, so `unresolved` and `split` at a past `as_of` use today's
  link.
- **Instant equality is assumed.** It holds because each loader writes an item's aliases
  in one transaction: the Discogs batch and the MusicBrainz message, per the code read. A
  loader that split those writes would turn one mint into extra "events".
- **Erasure removes moves.** `catalog_item_moves` loses a user's rows on erasure. Audit
  counts survive.
- **The audit route shows 90 days by default.** No retention purge exists, so the ledger
  route must not rely on that window.
- **Not measured: identity history on artists and labels.** Section 8 also splits them,
  and `identity_history.sql` counts their supersessions and links. The ledger shape here is
  release and master only, which is concept D's scope.

Only aggregates were read: no row, id, or audit entry was copied. No product code changed
in any repository, and no bead was filed.

## Sources

- [ADR 0009](../adr/0009-native-identity-and-provider-aliases.md), 2026-09-25 amendment,
  sections 1 to 5
- [ADR 0014](../adr/0014-cross-catalog-edition-candidates.md): Context, sections 3, 6, and
  8, and the 2026-09-25 amendments
- Prior spike: [gm-design-1wd.1](gm-design-1wd.1-unlinked-edition-candidates.md)
- Harness, SQL, and aggregate results: [gm-design-loj9/](gm-design-loj9/README.md)
