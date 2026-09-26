# ADR 0014: Ownership of cross-catalog release-edition candidates

- Status: Accepted; amended 2026-09-25

## Context

[ADR 0011](0011-catalog-identifiers-and-manufacturing-credits.md) made barcodes, catalogue
numbers, and matrix inscriptions available as `provider_aliases` rows and deferred one
question to its own record: what a matcher does with that evidence. This record settles that
deferral for release editions. It decides who produces a candidate pairing of a MusicBrainz
release with a Discogs release, where the candidate waits, who may turn it into identity, and
what an edition match means when the evidence cannot separate two pressings. It builds no
matcher.

The evidence is the [Semantica identity-matching spike](../spikes/gm-design-zwy-semantica-identity-matching.md)
(`gm-design-zwy`, [harness](../spikes/gm-design-zwy/README.md)). It scored 10,000 held-out
MusicBrainz releases that editors had already linked to Discogs, against a pool that keeps
every Discogs release sharing a barcode, catalogue-number, or title key with a query, drawn
from the full 19.4 million-release dump. Its findings, all of which this record relies on:

- **A deterministic baseline wins.** Keyed blocking on identifiers plus title and artist, and
  an additive rule score, reached 97.33% coverage and 77.14% recall@1. Semantica, reranking the
  same candidates, reached 71.00%.
- **Identifiers carry coverage, and descriptors carry separation.** Dropping barcode and
  catalogue number costs 14.5 points of coverage. Dropping year, format family, and country
  costs 7.2 points of recall@1, and those three are the only fields that tell two pressings of
  one master apart.
- **Review is bounded but not small.** At `score ≥ 10`, chosen on the dev split, the review
  queue averages 2.54 candidates per query with 35.2% queue precision.
- **Ties are the edition problem.** The top score is tied on 2,363 of 10,000 queries, and on
  1,359 of them the correct edition is inside the tie and lost an arbitrary tie-break. Counting
  only unique tops, recall@1 is 69.40%. A review of the spike's rankings found one more fact:
  in 87% to 91% of tie groups the linked target is the lowest Discogs id, so any id-order
  tie-break on linked data inflates measured recall.
- **Every number is an upper bound.** The pairs are already linked, and MusicBrainz data is
  often entered from Discogs, so field agreement is inflated: barcodes agree on 91.6% of pairs
  where both carry one. The population a matcher would serve, releases nobody has linked, was
  not measured.

What the services own today constrains the answer as much as the evidence does:

- **Catalog links attach only when the Discogs side is already loaded.** When a MusicBrainz
  release carries a Discogs release id and that Discogs release already resolves in
  `provider_aliases`, `musicbrainz-sql-loader` attaches the MusicBrainz alias to the Discogs
  release's native id rather than minting a parallel item
  (`musicbrainz-sql-loader/brainztableinator/_record_processing.py`, `_native_id`, lines
  279-304). A release without that id mints its own native item through its MusicBrainz alias,
  so every release a matcher would serve already has a native id of its own.
- **Load order splits linked items, and nothing rejoins them.** If the MusicBrainz release is
  loaded before its Discogs counterpart, `_native_id` finds no Discogs alias and mints a
  separate item through the MusicBrainz alias, even though the release names its Discogs id.
  `discogs-sql-loader` then mints the Discogs release its own item, resolving only its own
  alias (`discogs-sql-loader/tableinator/batch_writer.py`, `resolve_aliases`, around line 75).
  A later MusicBrainz reload does not repair it: the MusicBrainz alias already has a current
  row, and `attach_aliases` never overwrites. The docstring leaves the repair to "the
  reconciliation job", but no identity reconciliation exists in any repository;
  `brainztableinator/_reconciliation.py` deletes stale relationship and external-link rows
  and is unrelated. Artists, labels, and release groups share the gap, because they go
  through the same `_native_id` with `discogs_artist_id`, `discogs_label_id`, and
  `discogs_master_id` (lines 309, 338, and 486). These items are linked by catalog assertion
  but split across two native items by load order. A MusicBrainz barcode attached to the
  split item first also wins that barcode against the Discogs release.
- **Identifier aliases already collide at load time.** The same loader attaches the release's
  barcode and catalogue-number aliases through `common.identity.attach_aliases`, which never
  overwrites; a value Discogs already claims resolves to the Discogs item and is logged as a
  conflict (`_attach_identifier_aliases`, lines 420-454;
  `python-libraries/src/common/identity.py`, `attach_aliases`, line 325).
- **`provider_aliases` holds one current row per identifier, and reads do not filter on
  source.** The partial unique index on `(provider, entity_kind, external_id) WHERE valid_to
  IS NULL` (`database-schema/src/groovemap_schema/postgres.py`, lines 441-468) admits one
  currently valid native id per external id. `catalog-api` resolves identity and serves
  barcode lookup through that table without regard to `source`
  (`catalog-api/api/identity.py`, `_SELECT_NATIVE_IDS`, line 57;
  `catalog-api/api/queries/lookup_queries.py`, lines 32-66), and walks a native id back to
  both catalogs' rows through the `gm_item_id` column each releases table carries.
- **`analytics-engine` reads the catalog through `catalog-api`.** It consumes a promoted
  internal HTTP contract, writes only its own `insights` tables with snapshot-replace
  semantics, and touches PostgreSQL directly only to read the `activity` schema
  (`analytics-engine/docs/architecture.md`, lines 3 and 48;
  `analytics-engine/insights/computations.py`). The
  [ADR 0013](0013-pgvector-catalog-embeddings.md) amendment gave it a second exception: a
  dedicated least-privilege role for the embedding pipeline, because paging the whole graph
  through HTTP is impractical. That role is decided and not yet built in `database-schema`.
- **`catalog-api` is the only service with an operator surface.** Its admin routes require an
  administrator (`catalog-api/api/dependencies.py`, `require_admin`, line 242), record actions
  in `admin_audit_log` (`catalog-api/api/audit_log.py`;
  `database-schema/src/groovemap_schema/postgres.py`, line 554), and already run the one
  identity maintenance job ADR 0009 assigns it (`POST /api/admin/identity/project`,
  `catalog-api/api/routers/admin.py`, line 675).
- **The graph reaches MusicBrainz releases only through the Discogs id.** The
  `graph.mb_release` view exposes `discogs_release_id`, not a native id
  (`database-schema/src/groovemap_schema/postgres.py`, around line 1869), and
  `musicbrainz-graph-enricher` skips a release that names no Discogs id
  (`musicbrainz-graph-enricher/brainzgraphinator/_projections.py`,
  `entities_skipped_no_discogs_match`).

## Decision

### 1. Producer: an offline matcher job in `analytics-engine`

Edition candidates are produced by a scheduled batch job in `analytics-engine`. Its query
population is the MusicBrainz releases whose `discogs_release_id` is null; a release with a
catalog link is never re-matched. Its candidate pool is the loaded Discogs releases. It reads
both through a dedicated `NOLOGIN` PostgreSQL role, separate from the ADR 0013 embedding role,
defined by `database-schema` with `SELECT` on the two catalogs' release, master, and
release-group tables and on `provider_aliases`, and write access to the candidate tables in
section 2 only. The login is provisioned where credentials live, as ADR 0013's amendment
specifies for its role. The job holds no write privilege on any catalog table and none on
`provider_aliases`.

The matcher is the deterministic one `gm-design-zwy` measured: kind-aware keyed blocking on
barcode, label and catalogue number, and title with artist; a stop-key limit; an additive
rule score in which descriptors (year, format family, and country through an explicit ISO to
Discogs country map) separate pressings; and no id-order tie-break anywhere. Its rule weights,
normalization, and country map are versioned together, and every run records that version.

This is consistent with [ADR 0005](0005-source-owned-catalog-ingestion.md). Each ingestion
producer owns acquisition, parsing, and normalization of one source. A matcher reads two
sources by definition, so it belongs downstream of both producers and both loaders, not
inside either. Nothing in either producer or either loader changes; the loader's existing
attach-on-catalog-link behaviour is the catalog half of cross-catalog identity and stays
exactly as it is.

Rejected alternatives:

- **The matcher in `musicbrainz-ingestion` or `musicbrainz-sql-loader`.** Either would have to
  read the Discogs catalog, which is the cross-source coupling ADR 0005's split removed, and a
  loader would run a heuristic inside each message's transaction on the ingest write path.
- **The matcher in `catalog-api`, online or as an admin job.** `catalog-api` would then both
  generate and judge its own candidates, and a full-population scan does not belong in a
  request-serving process. Keeping producer and promoter in different services is what makes
  the promotion step a check rather than a formality.
- **`analytics-engine` reading through a paged `catalog-api` export.** Rejected for the reason
  ADR 0013's amendment rejected it for embeddings: volume. The spike's keyed pool alone was
  1.27 million records, and blocking has to see the whole corpus.
- **A job inside `database-schema`.** That repository owns DDL and initialization, not
  scheduled computation; ADR 0013 rejected the same placement for the embedding pipeline.

### 2. Storage: a `matching` schema, and nothing in the graph before promotion

Candidates live in a new `matching` schema whose DDL `database-schema` owns. It holds two
kinds of table with two different writers:

- **Runs and candidates, written by the matcher role.** A run row records the rule version,
  the two dump dates, the threshold, and counts. A candidate row names the MusicBrainz release,
  one candidate group of one or more Discogs releases, the score, the per-rule evidence that
  produced it, and whether the group is ambiguous under section 4. A later run replaces the
  previous run's open candidates, as the `insights` tables replace their snapshots.
- **Decisions, written by `catalog-api`.** A decision row records accept, reject, resolve, or
  revert for a candidate, the reviewer, the time, the evidence note, the ids of any
  `provider_aliases` rows written or closed, and the native id the MusicBrainz release held
  before promotion. Decisions are never replaced by a run. They are the audit trail, they
  suppress re-proposing a pair a reviewer rejected, and they are the labelled data a future
  threshold is recalibrated on.

Candidate and decision rows are provider-derived data and fall under ADR 0013's quarantine:
never committed, never published, recomputable or purgeable with the dumps they came from.

Candidates do not appear in the property graph ([ADR 0012](0012-postgresql-property-graph-migration.md))
or in the Neo4j graph it replaces. A graph edge is a catalog assertion that traversals such as
`/api/path` and the MCP tools serve without asking where it came from, and ADR 0012's label
mapping is a contract that an unreviewed edge label would widen for no reader that needs it.
A candidate becomes visible to the graph only after it is promoted, and even then only once the
graph's MusicBrainz views resolve releases through native ids rather than through
`discogs_release_id`; that view change is deferred below.

Rejected alternatives:

- **Candidates as `source = 'inference'` rows directly in `provider_aliases`.** The partial
  unique index admits one current row per MusicBrainz id, so a set-valued candidate cannot be
  represented, and a row there is immediately served as identity by `catalog-api`'s lookup and
  resolution reads, which do not filter on `source`.
- **Candidates in the `insights` schema.** `insights` tables are read models served by public
  endpoints and wholesale replaced on every run; decisions need history that survives a run.
- **A candidate edge label in the property graph.** Rejected as above: it would publish
  unreviewed identity through every traversal.

### 3. Promotion: human review in `catalog-api`, written as a person's assertion

Only `catalog-api` turns a candidate into identity, through an administrator-authenticated
review action recorded in both `admin_audit_log` and a `matching` decision row. There is no
deterministic auto-promotion for editions under this record. At the spike's operating point
the review queue is 35.2% precise on data that flatters every method; no rule calibrated on
that data may write identity without a person.

Accepting a candidate is a person asserting the identity on the matcher's evidence, so the rows
it writes carry `source = 'user'`, whose vocabulary definition is "a person asserted the
alias", with confidence 1.0. The matcher's score stays on the candidate and decision rows,
not in the alias table. Nothing in this path writes `source = 'catalog'`, which keeps
[ADR 0009](0009-native-identity-and-provider-aliases.md)'s rule intact, and nothing writes
`source = 'inference'` either, because this record stores unreviewed candidates outside the
alias table. A future deterministic rule, if the precondition measurement in section 6 ever
justifies one, would write `source = 'inference'` and would need an amendment to this record.

The promotion transaction does three things:

1. Closes every currently valid alias row pointing at the MusicBrainz release's own native id
   (its `musicbrainz` alias, and any barcode or catalogue-number alias that loader attached to
   it) by setting `valid_to`.
2. Inserts the same aliases against the Discogs release's native id, as `source = 'user'`.
3. Sets `gm_item_id` on that one `musicbrainz.releases` row to the Discogs release's native id.

The third step writes a column `musicbrainz-sql-loader` populates. It is justified because
`gm_item_id` is a cache of the alias table, which ADR 0009 makes the authority, and because
the loader converges on the same value: its `_native_id` resolves the MusicBrainz alias and
now finds the promoted row. The MusicBrainz release's former native id is not deleted, since
ADR 0009 defines no native-id merge or tombstone. To keep that orphan harmless, promotion is
refused when the former native id has any dependent in `artifacts`, `owned_copies`,
`observations`, `user_collections`, or `user_wantlists`
(`database-schema/src/groovemap_schema/postgres.py`, lines 220-428); such a case is left to a
native-id merge decision this record does not make. This guard applies until the ADR 0009
merge lands; see the 2026-09-25 amendment below.

A promotion is reversed by the same step in reverse: close the promoted rows, re-insert the
aliases against the former native id held on the decision row, restore `gm_item_id`, and
record a revert decision with its reason. The validity interval keeps both the promotion and
its reversal auditable, which is what ADR 0009 designed it for.

A catalog assertion outranks a reviewed promotion. If MusicBrainz later publishes a Discogs
link for a promoted release, the loader's `attach_aliases` will not overwrite the promoted
alias, so the disagreement would otherwise be silent. The catalog re-attachment in section 8
detects it, because a promoted release whose `discogs_release_id` has become non-null and names
a different Discogs release is exactly a catalog link its current alias contradicts. It closes
the promoted rows, attaches the release per the catalog link, and records a revert decision
naming the contradiction. A link that agrees with the promotion needs no action.

Rejected alternatives:

- **Deterministic auto-promotion at `score ≥ 10`, or at a unique top.** Queue precision is
  35.2%, and even the unique top is correct on at most 69.40% of queries, both upper bounds.
- **Reviewed promotions written as `source = 'inference'`.** The vocabulary defines inference
  as "evidence, not an assertion", and the reads serve it as identity anyway, so the label would
  misdescribe the row to every consumer that does filter.
- **Promotion inside the matcher job.** It would give `analytics-engine` write access to
  `provider_aliases` and collapse producer and judge into one service.

### 4. Indistinguishable pressings: no release-level assertion without a unique edition

An edition match asserts that one MusicBrainz release and one Discogs release describe the
same edition. When two or more Discogs releases are equal on every field the MusicBrainz
release carries and the matcher compares, MusicBrainz has not said which one it describes, and
GrooveMap does not say it either.

The matcher decides ambiguity by field equality, not by score equality: a candidate group is
ambiguous when its members agree on barcode, label and catalogue number, title key, artist,
year, format family, and country, as far as the MusicBrainz release carries each. Such a group
is stored as one set-valued candidate. The promotion step cannot promote an ambiguous group. A
reviewer may resolve it to a single member only by citing evidence outside the MusicBrainz
record, such as a matrix inscription, the Discogs release notes, or images, and the resolution
records that evidence; that is then a person's assertion about one edition. An unresolved
ambiguous group produces no alias, and the MusicBrainz release keeps its own native id.

Neither the matcher, a measurement harness, nor the promotion step breaks a tie by id order,
by insertion order, or by any other property unrelated to the edition. On linked data such a
tie-break selects the linked target 87% to 91% of the time and would present an artifact of
how the data was linked as matching quality.

Where every member of an ambiguous group shares one Discogs master, the same-work fact is true
even though the edition is unknown. The matcher may propose that as a separate candidate
between the MusicBrainz release group and the Discogs master, entity kind to entity kind,
through the same review path, when the release group carries no Discogs master id of its own.
That candidate is never a substitute for the edition.

Rejected alternatives:

- **Pick one member by a deterministic tie-break.** It asserts an identity MusicBrainz never
  made, and on the spike's data it is right for a reason that will not hold on unlinked data.
- **Master-level fallback in place of the edition.** Aliasing a MusicBrainz release to a
  Discogs master crosses entity kinds; the spike found entity kind load-bearing, and ADR 0009
  keys every alias by it.
- **Alias the MusicBrainz release to every member.** The unique index admits one current native
  id per MusicBrainz id, and the members are distinct native items because Discogs says they
  are distinct.
- **Merge the indistinguishable Discogs releases into one native item.** It overrides the
  source catalog's own record that they are different editions, which is not GrooveMap's
  assertion to make.

### 5. Normalization: matcher-internal keys only; ADR 0011's alias rules are unchanged

The spike extended ADR 0011's rules in two ways: a 12-digit UPC-A barcode is also compared as
its 13-digit EAN-13 form with a leading zero, and a catalogue number is also compared as a
compact key with punctuation and spaces removed. Both are adopted as blocking and comparison
keys inside the matcher, versioned with its rules, and recorded here.

Both are declined as `provider_aliases` normalization. ADR 0011's rules — barcode digits only,
catalogue number upper-cased with internal whitespace collapsed — stay the rules that produce
an `external_id`. A change there re-keys every minted barcode or catalogue-number alias, moves
the `taxonomy/identifiers/v1` vocabulary and three mappers together, and changes what
`GET /api/lookup/{provider}/{value}` returns. The compact catalogue-number key also collapses
distinct printed values, and in a table whose unique index gives one release per value, a new
collision is an alias another release silently loses. ADR 0011 carries a dated amendment
recording this. The UPC-A widening is a plausible lookup improvement in its own right, since
the two forms are the same GTIN, and is left to its own identifier-vocabulary change.

Rejected alternative:

- **Amend ADR 0011 to adopt both as alias normalization.** Rejected for the re-keying and
  collision costs above, neither of which a candidate generator needs to pay: blocking can use
  a wider key than identity without changing identity.

### 6. Precondition: measure on the unlinked population before anything is built

No part of this decision is implemented — not the `matching` schema, the role, the job, or the
review action — until the matcher's candidate quality is measured on MusicBrainz releases that
have no Discogs link, and the review threshold is recalibrated on that measurement. The spike's
numbers come from already-linked, often copied data and bound quality from above; a threshold
chosen on them is chosen on the wrong population.

That measurement is the next planning input for this program. It labels a sample of unlinked
MusicBrainz releases, by hand or through a time-split holdout of Discogs relations added after
the `20260923` MusicBrainz dump, re-runs the `gm-design-zwy` harness on it, and reports at
least coverage, unique-top precision, queue size and precision at a recalibrated threshold, the
ambiguous-group rate under section 4, and the same per-slice view the spike reported. It breaks
no tie by id. If the review queue cannot be held near the spike's bar of three candidates per
query at a precision a reviewer can sustain, the program stops at this record. This record does
not file that measurement.

The first measurement returned DEFER, and the bar is now numeric; see the
[second 2026-09-25 amendment](#2026-09-25-section-6-measured-on-newly-linked-releases-defer)
below. This section stands until a re-run clears that bar.

Rejected alternative:

- **Build the matcher now at `score ≥ 10`.** That threshold was chosen on the dev split of the
  same linked population, and its 2.54-candidate queue is the optimistic end of the range.

### 7. Extensibility: artist and label candidates join by amendment

The producer, the `matching` schema, and the promotion path are written for release editions
and keyed by entity kind so that artist and label candidates can join them by amendment rather
than by a new design. The evidence for those kinds is separate: the name-embedding spike
([`gm-design-chw.3`](../spikes/gm-design-chw.3-identity-name-embeddings.md)), whose generator
ADR 0013 did not adopt, and `gm-design-e0b`, which is evaluating non-Latin identity and has not
landed. `musicbrainz-sql-loader` already attaches artists and labels on a catalog link,
through the same `_native_id` path as releases, so their matcher would also serve only the unlinked population.

What must not carry over is the domain rule. A sibling pressing is the same work in a different
edition, so an ambiguous edition candidate is a partial truth worth keeping as a set. A namesake
artist or label is a different entity, so an ambiguous artist candidate is a hazard, and a wrong
promotion merges two people or two companies. An amendment adding those kinds must state its
own ambiguity rule, which discography, date, or country evidence resolves a namesake, its own
threshold measured on its own population, and its own rule version. Scores are not shared
across kinds.

Artist and label candidates are admitted for three scripts, with their own ambiguity rule and
numeric bar; see the
[third 2026-09-25 amendment](#2026-09-25-artist-and-label-candidates-for-three-scripts) below.
Nothing for those kinds is built until a measurement clears that bar.

Rejected alternative:

- **Decide artist and label candidates here, on edition evidence.** The spike did not measure
  them, and the two identity semantics differ in exactly the direction that makes an edition
  rule unsafe for people.

### 8. Split-linked items: catalog re-attachment, outside the matcher

The items Context describes as split by load order are not a matcher population. The
MusicBrainz record already names its Discogs counterpart, so there is nothing to infer, no
candidate to store, and nothing for a person to review. The matcher's query population stays
the releases whose `discogs_release_id` is null.

They are repaired by a deterministic catalog re-attachment job owned by `catalog-api`, beside
the identity projection job ADR 0009 already assigns it. For every MusicBrainz release,
release group, artist, or label whose Discogs id resolves to a native id different from the
one its MusicBrainz alias resolves to, it runs the same three-step transaction as section 3's
promotion, writing `source = 'catalog'`: close the aliases on the split item, re-insert them
against the Discogs item, and set that row's `gm_item_id`. `source = 'catalog'` is correct
because the assertion is the provider's own record, the same value the loader would have
written had the Discogs row arrived first; nothing inferred reaches `catalog`, so ADR 0009's
rule holds. The loaders do not change, so ADR 0005's boundary holds too:
`discogs-sql-loader` would otherwise have to read MusicBrainz tables, and the MusicBrainz
loader would have to close valid alias rows inside a message transaction.

This path is not gated by section 6. It uses no matcher and no threshold, and it needs no
`matching` schema; the job records its actions in `admin_audit_log`. It applies section 3's
dependents guard: a split item with any dependent is skipped and reported, and waits for the
native-id merge decision deferred below. This guard applies until the ADR 0009 merge lands;
see the 2026-09-25 amendment below. Once promotions exist, it is also what performs
section 3's contradiction revert, since a contradicted promotion is one more item whose alias
disagrees with its catalog link; in that case it also writes the revert decision row. Because
it acts only on explicit catalog links, section 7's namesake caution does not apply to it.

Rejected alternatives:

- **Treat split-linked items as matcher candidates.** It would send a catalog assertion
  through human review and the section 6 gate, delaying a repair nothing needs to judge.
- **Fold it into the deferred native-id merge decision.** Only the items with dependents
  need that decision; the rest are a mechanical repair that should not wait on it.
- **Repair it in the loaders.** Rejected for the ADR 0005 reasons above.

### Rejected alternatives and conditions for revisiting

- **Semantica, as a pinned dependency or a reimplementation of its rules.** Rejected on the
  `gm-design-zwy` evidence: it ranks worse in every configuration and slice (recall@1 71.00%
  against the baseline's 77.14% on 10,000 queries), no confidence threshold brings its review
  queue below 11.49 candidates per query because confidence saturates at its 1.0 cap, it
  declares `requires-python < 3.14` against GrooveMap's 3.14, and it brings 410 MB of
  dependencies for 4,634 lines of standard-library code. The rules that distinguish it —
  Jaro-Winkler on identifiers and a neutral score for missing fields — are the ones the
  evidence shows hurting. Revisit only if upstream supports Python 3.14 and a later release
  beats the harness baseline on the section 6 measurement.
- **A dedicated identity-resolution or record-linkage service.** Nothing measured needs more
  than a batch job and three tables. Revisit if a third catalog, or artist and label volume,
  makes the batch job's run time or the review load unmanageable.
- **Name embeddings as an edition signal.** Title and artist are blocking keys here, and
  identifiers and descriptors carry the result; `gm-design-chw.3` measured names only for
  artists and labels. Revisit under section 7 if an embedding generator is adopted for those
  kinds.

## Consequences

The deferral in ADR 0011 is closed without a line of matcher code. Cross-catalog edition
identity gets one producer, one holding area, one judge, and one reversal path, and the part
that is already catalog assertion — the MusicBrainz editors' own Discogs links — keeps flowing
through the loader, with a catalog re-attachment repairing the items load order split. A candidate never reaches a user until a person has accepted it,
and an ambiguous candidate never reaches one at all.

The cost is review. Every promoted edition is a person's decision, the queue is bounded only
by a threshold that does not yet exist, and ambiguous groups can only be resolved with
evidence the MusicBrainz record does not carry. Coverage of unlinked releases will therefore
grow slowly and unevenly. That is accepted: the alternative is identity asserted on evidence
that has already shown it cannot tell pressings apart.

This record accepts four frictions with ADR 0009 rather than hiding them:

- **An orphaned native id.** Promotion leaves the MusicBrainz release's former native item
  unreferenced, because ADR 0009 defines no merge. The dependents guard keeps that harmless for
  now and a native-id merge decision is deferred. That holds until the ADR 0009 merge lands;
  see the 2026-09-25 amendment below.
- **`user` covers operator review.** The `user` source was written with collectors in mind.
  Here it also covers an administrator accepting a candidate; the decision row, not the alias
  row, says which.
- **Never-overwrite hides a later catalog link.** `attach_aliases` keeps whichever alias came
  first, so a catalog link published after a promotion, or a Discogs row loaded after its
  MusicBrainz counterpart, would lose silently without the re-attachment in section 8.
- **`catalog` written outside ingestion.** The vocabulary describes `catalog` as read during
  ingestion. The re-attachment writes it from a maintenance job, carrying the provider's own
  link unchanged.

There is no tension with ADR 0005: neither producer nor either loader changes, and no
producer reads the other source.

Repositories affected. Everything except the section 8 re-attachment waits for section 6:

- **`database-schema`** owns the `matching` schema, its tables, and the matcher role with its
  guarded grants.
- **`analytics-engine`** owns the matcher job, its versioned rules, normalization keys and
  country map.
- **`catalog-api`** owns the review, resolve, promote, and revert actions, their audit, and the
  dependents guard (until the ADR 0009 merge lands; see the 2026-09-25 amendment below). Its
  catalog re-attachment job in section 8 is not gated by section 6. Any operator interface
  consumes them through the admin contract it already publishes.
- **`deployment`** and the homelab provision the matcher role's login.

### Follow-ups

These are planning inputs. None is filed by this record.

- **Unlinked-population measurement.** The section 6 measurement, and the next planning input
  for this program. Nothing else here proceeds without it.
- **Graph resolution through native ids.** `graph.mb_release` and its neighbours reach Discogs
  only through `discogs_release_id`, so a promoted edition is invisible to the property graph.
  Whether those views should join through `gm_item_id` is a `database-schema` decision under
  ADR 0012. Decided in
  [ADR 0012's 2026-09-25 amendment](0012-postgresql-property-graph-migration.md#2026-09-25-musicbrainz-graph-crossings-resolve-through-native-ids):
  the cross-catalog relations resolve through the native id's Discogs alias first and the
  Discogs id second, and the change ships with the first promotion, once section 6 returns GO.
- **Catalog re-attachment of split-linked items.** The section 8 job in `catalog-api`, for
  releases, release groups, artists, and labels. It does not wait on the section 6
  measurement, and a first run should report how many items load order has split.
- **Native-id merge.** What happens to a native item superseded by an identity decision,
  including one with dependents, whether from a promotion or a section 8 re-attachment. It is
  an ADR 0009 question, not an edition question. Decided in
  [ADR 0009's 2026-09-25 amendment](0009-native-identity-and-provider-aliases.md#2026-09-25-superseded-catalog-items-and-native-id-merge),
  which replaces the dependents guard in sections 3 and 8 with a reversible merge once
  `catalog-api` implements it.
- **UPC-A to EAN-13 in the identifier vocabulary.** A lookup improvement independent of
  matching, left to its own vocabulary change.
- **Artist and label candidates.** An amendment under section 7, once `gm-design-e0b` has
  landed and a generator for those kinds is adopted. Decided in the
  [third 2026-09-25 amendment](#2026-09-25-artist-and-label-candidates-for-three-scripts):
  candidates for Cyrillic, Hebrew, and Japanese kana names, Han excluded, gated by their own
  measurement.

## Amendments

### 2026-09-25: Dependents guard replaced by the native-id merge

[ADR 0009's amendment of the same date](0009-native-identity-and-provider-aliases.md#2026-09-25-superseded-catalog-items-and-native-id-merge)
decides the native-id merge this record deferred. The dependents guard in sections 3 and 8
stays in force exactly as written above until `catalog-api` implements the merge steps, and is
removed in that same `catalog-api` change, not before. Once removed, the merge steps run as
further steps appended inside the same transactions this record already assigns to
`catalog-api`: the section 3 promotion and revert, and the section 8 re-attachment and
contradiction revert. A superseded item's dependents move to the survivor, and the item itself
is kept, never deleted, so an orphaned native id becomes a resolvable supersession instead. The
first re-attachment run after the guard is removed picks up every item earlier runs skipped;
no separate release list is needed.

`catalog-api`'s re-attachment job (`gm-catalog-api-sv35`, `catalog-api` main `9ad0e09`)
currently implements the guard, consistent with the ADR 0009 amendment's "until the merge
lands" rule.

This does not reopen anything decided here. Sections 3, 4, 7, and 8 are unchanged, and the
guard's refuse/skip behavior remains correct until the merge lands.

### 2026-09-25: Section 6 measured on newly linked releases: DEFER

The section 6 measurement ran as
[spike `gm-design-1wd.1`](../spikes/gm-design-1wd.1-unlinked-edition-candidates.md)
([harness](../spikes/gm-design-1wd.1/README.md)). It took the MusicBrainz releases that had no
Discogs link in the `20260919` JSON dump and gained exactly one by `20260923`, used each
release's `20260919` record as the query and the new link as the label, and re-ran the
`gm-design-zwy` deterministic baseline unchanged against a pool drawn from the full
`discogs_20260901` dump. That gave 408 eligible queries (dev 90, test 318). No tie is broken by
id: every metric is a function of score groups and section 4 comparison vectors.

**Headline numbers.** These are for the test split, on the 305 queries whose target is in the
Discogs dump, with 95% intervals, against `gm-design-zwy`'s linked population:

| Metric | This measurement | `gm-design-zwy` |
| --- | ---: | ---: |
| Coverage | 89.5% (85.6–92.5) | 97.3% |
| R@1, expected under random tie order | 76.4% (71.3–80.8) | 77.1% (id-order tie-break) |
| R@1, unique top | 70.8% (65.5–75.6) | 69.4% |
| Review queue at `score ≥ 8` (chosen on dev), candidates per query | 2.74 (2.13–3.43) | 2.54 at `score ≥ 10` |
| Queue precision, candidates | 26.9% (22.4–35.7) | 35.2% at `score ≥ 10` |
| Correct edition in the queue (all 318) | 73.6% (68.5–78.1) | 89.3% at `score ≥ 10` |
| Review queue in section 4 ambiguity groups, per query | 1.38 | not reported |
| Queue precision, groups | 53.2% | not reported |
| Leading group ambiguous under section 4 | 17.9% (13.9–22.8) | not reported |
| Target is the lowest id in its tie group (diagnostic) | 45.5% (31.7–59.9) | 87–91% |

**Findings.**

- **Coverage degrades, and ranking does not.** R@1 is indistinguishable from the linked
  population's, but the coverage interval excludes zwy's figure. The cause is thin queries,
  not the matcher or the pool: only 47% of test queries carry a barcode and 52% a catalogue
  number, against zwy's 61% and 95%. Editors add identifiers when they link. Between the two
  dumps, 27.9% of the query releases gained a catalogue number and 12.3% a barcode, most likely
  copied from the Discogs release being linked. Missing identifiers are also why dev chose
  `score ≥ 8` rather than zwy's 10: at 10, fewer than half of the correct editions would reach
  the queue.
- **The lowest-id bias is a linked-data artifact.** On linked data the target was the lowest
  Discogs id in 87–91% of tie groups; on newly linked releases it is 45.5% (20 of 44), no
  better than a coin toss in a two-way tie. An id tie-break would have looked like signal on the population the
  threshold was first chosen on and been noise on the one it serves. That confirms section 4's
  refusal to break ties by id or order.

**Why DEFER rather than GO or NO-GO.** The direction is informative, but the sample cannot carry
the decision section 6 asks for:

1. The threshold is the thing section 6 recalibrates, and it rests on 87 reachable dev queries.
   One point lower than the chosen 8 moves the dev queue from 2.34 to 5.82 candidates.
2. The window is four days of edits, about 100 releases a day. The JSON dumps carry no editor
   information, so one editor's batch dominating the sample can be neither ruled out nor
   measured.
3. The pool predates both snapshots. 16 of 408 targets, mostly 2020s releases, are absent from
   the `discogs_20260901` dump.

**Re-run trigger.** Re-run the `gm-design-1wd.1` harness, with its blocking, scoring, and
normalization unchanged, on the MusicBrainz `20260919` to `20261014` time-split with a pool
built from `discogs_20261001`. The target is about 2,500 eligible releases, roughly 500 dev and
2,000 test. The `20261010` dump, about 2,100 eligible, is the earliest usable later snapshot. The
only harness addition allowed is reporting: the seeded query bootstrap the harness already uses
for the candidate queue is extended to the group queue and group precision, so that the bar
below can be read from an interval.

**The bar.** This replaces section 6's "near the spike's bar of three candidates per query at a
precision a reviewer can sustain" with a numeric bar, decided by the owner:

- **Unit.** The review queue is counted in section 4 ambiguity groups, not individual
  candidates. A reviewer decides a group once, and section 4 already forbids promoting a member
  of an ambiguous group, so groups are the load a reviewer carries.
- **Queue.** GO requires the **upper bound** of the 95% interval on the mean test queue to be at
  most **3 groups per query**.
- **Precision.** GO requires the **lower bound** of the 95% interval on test queue precision,
  the share of queued groups that contain the correct edition, to be at least **50%**. The bar
  applies to the interval bound, not the point estimate, because that is what makes a GO
  robust: a point estimate at 50% is a coin toss between a sustainable queue and an
  unsustainable one. This measurement's 53.2% passes on the point estimate only; on 305
  queries its interval cannot be expected to clear 50%, and a 2,000-query test split is sized
  to settle it.
- **Threshold.** The threshold is the lowest integer score at which the **dev** split meets both
  bars on its point estimates. It is chosen once on dev and applied to test unchanged. If no
  score meets both on dev, the result is NO-GO.
- **Ties.** No tie is broken by id or insertion order, in the threshold choice or in any metric.
- **Reported alongside, with no bar.** Coverage and the share of correct editions that reach the
  queue, both on the reachable basis with 95% intervals, plus the section 4 leading-group
  ambiguity rate. Coverage gets no bar because this measurement shows it is set by what the
  MusicBrainz record carries, not by the matcher, and because a missed candidate leaves a
  release unlinked, which is today's state, while a low-precision queue costs reviewer time on
  every query. Coverage bounds the matcher's value, not its safety.

**NO-GO.** If the re-run misses either bar, the program stops at this record: nothing in
sections 1 to 5 or 7 is built. Section 8's catalog re-attachment continues regardless; it never
waited on section 6.

**Until then, nothing is built.** Section 6 stands as written apart from the bar above: no
`matching` schema, role, job, or review action until a re-run clears it. Section 8 is
unaffected. Sections 1 to 5 and 7 are unchanged.

### 2026-09-25: Artist and label candidates for three scripts

Section 7 left artist and label candidates to an amendment that states its own population,
ambiguity rule, threshold, and rule version. The evidence is the non-Latin identity spike,
`gm-design-e0b.1` (`docs/spikes/gm-design-e0b.1-nonlatin-identity.md`),
read with [`gm-design-chw.3`](../spikes/gm-design-chw.3-identity-name-embeddings.md) and
[ADR 0013](0013-pgvector-catalog-embeddings.md)'s "Identity candidates" section. `gm-design-e0b.1`
held out MusicBrainz-to-Discogs links on 5,000 non-Latin artists against a 1,098,846-name pool
and on all 1,592 usable non-Latin labels against every Discogs label, and compared `pg_trgm`,
two multilingual embedding models (`multilingual-e5-small` and `bge-m3`), and rank fusion of
each with `pg_trgm`. The owner approved its report and gave `gm-design-e0b.2` a GO scoped as
the report recommends: a script-scoped generator for Cyrillic, Hebrew, and Japanese kana, Han
excluded, validated against real HNSW retrieval before it ships.

The findings this amendment relies on:

- **The aggregate result is split.** Best fusion raises recall@10 over `pg_trgm` by 6.85
  points for labels (73.18% to 80.03%) and by 3.96 points for artists (54.44% to 58.40%), 1.04
  points short of the 5-point bar ADR 0013 set. Both gains are far smaller than
  `gm-design-chw.3`'s thin-sample 9.6 and 16.7 points.
- **The split is population mix.** Han is 38% of the artist sample and 23% of the label sample,
  and no name method recovers Han names that Discogs stores romanized. Outside Han, both kinds
  show the same shape: large gains in a few scripts.
- **Dense retrieval alone sometimes beats fusion.** On artist Hebrew, `e5-small` alone gains
  14.92 points against fusion's 6.69, and on artist Cyrillic `bge-m3` alone gains 7.07 against
  fusion's 4.20.
- **Namesakes defeat every name method.** When the target's name collides in the pool,
  recall@1 falls to 19.7% for artists and 48.9% for labels at `pg_trgm`, against 54.7% and
  73.1% when it does not, and no method does materially better.
- **Every dense number is exact cosine.** The side-check that would have compared pgvector
  HNSW to exact search failed on a container shared-memory limit. The gap is unmeasured, not
  small.
- **Every number is on linked pairs.** As with `gm-design-zwy`, the population measured is the
  one editors already linked, which is not the one a generator would serve.

#### 1. Population: unlinked MusicBrainz artists and labels in the scoped scripts

The query population is the MusicBrainz artists whose `discogs_artist_id` is null and the
MusicBrainz labels whose `discogs_label_id` is null, whose name falls in a scoped script. As
for releases, an entity with a catalog link is never re-matched, and a split-linked entity is
section 8's, not the matcher's. In the `20260923` MusicBrainz dump, 131,112 artists and 5,339
labels are non-Latin and unlinked, about 2.6 and 3.3 times the number already linked.
`gm-design-e0b.1` did not break the unlinked counts down by script, and the linked sample's
script mix need not match them, so the scoped population is not yet sized. The measurement in
subsection 5 reports it per script.

The candidate pool is the loaded Discogs artists or labels whose native item carries no current
`musicbrainz` alias of the same kind. A Discogs entity that MusicBrainz already links to
another MusicBrainz entity is excluded: MusicBrainz asserts that the two MusicBrainz entities
are distinct, so a second link onto the same Discogs item would merge them.

Latin-script names are not admitted. `gm-design-chw.3` found `pg_trgm` near 97% recall@10 on
the linked, mostly Latin population, but that population is easy by construction, and
namesakes are densest in Latin script. They join by a further amendment with their own
measurement, if ever.

Rejected alternative:

- **All non-Latin names, script-agnostic.** The artist aggregate misses the bar because Han
  drags it down, and a single threshold would hide scripts where the method works behind one
  where it cannot.

#### 2. Script scope: Cyrillic, Hebrew, and Japanese kana; Han excluded

A name's script is its dominant Unicode block among alphabetic characters, as
`gm-design-e0b.1`'s classifier computes it. The classifier is part of the rule version.
Recall@10 gains over `pg_trgm` on `gm-design-e0b.1`'s linked pairs decide the scope:

| Cell | n | `pg_trgm` recall@10 | Best fusion gain | Best dense-alone gain |
| --- | ---: | ---: | ---: | ---: |
| Artist, Cyrillic | 1,358 | 87.63% | +4.20 | +7.07 (`bge-m3`) |
| Artist, Hebrew | 583 | 57.29% | +6.69 | +14.92 (`e5-small`) |
| Artist, Japanese kana | 588 | 48.13% | +11.90 | +14.29 (`e5-small`) |
| Label, Hebrew | 175 | 54.86% | +16.00 | +17.71 (`bge-m3`) |
| Label, Japanese kana | 239 | 51.46% | +17.99 | +20.50 (`e5-small`) |
| Label, Cyrillic | 672 | 94.79% | +1.79 | +1.19 (`bge-m3`) |

The first five cells are admitted with dense retrieval. Label Cyrillic is admitted as a
trigram-only cell: embeddings add nothing there, but `pg_trgm` already recalls 94.79%, and the
cell faces the same namesake hazard and bars as the others.

**Promising but unconfirmed.** Arabic, Korean Hangul, Thai, and the remaining non-Latin
scripts show gains, but on samples below 180 on at least one kind, down to 10. They are not
admitted on this evidence. Each joins by amendment once a sample powered to the bar in
subsection 5 clears it. Greek showed no gain above 4.41 points on either kind and is not
listed.

**Han is excluded.** It is the largest non-Latin slice, and the diagnosis is a script mismatch,
not a weak matcher. When the Discogs name is also in Han, every method, `pg_trgm` included,
recalls 95.9% to 99.2% at 10. When Discogs stores it romanized, which it does for 73.7% of Han
artist queries and 45.8% of Han label queries, following its convention of romaji or pinyin in
given-name-first order, every method recalls 0% to 7.9%, both embedding models included. Neither
Simplified and Traditional variants nor trigram tokenization explain it. No name similarity
crosses scripts that far.

A separate Han path would need a transliteration bridge: a romanized key for each Han-script
MusicBrainz name, matched against Discogs names and name variations. Its source is the open
question. MusicBrainz sort names and Latin-script aliases are editor-entered and cover part of
the population. Generated romanization needs a dependency under the license policy and cannot
recover Japanese given-name readings, which kanji do not determine. That path needs its own
spike measuring recall on the romanized subset, its own bar under subsection 5, and its own
amendment. It is not decided here.

Rejected alternative:

- **Include Han and rely on the Han-to-Han subset.** It would admit a population where most
  targets are unreachable, and a queue of Han-script namesakes where the true entity is a
  romanized record no method retrieves.

#### 3. Retrieval: per-cell policy, trigram candidates always kept

Every candidate list includes `pg_trgm`'s top candidates, as ADR 0013 requires of any adopted
embedding. In the five dense cells it also includes the dense model's top candidates, and a
per-cell policy ranks the union: dense alone, or rank fusion with `pg_trgm`. The policy and the
model are chosen per cell on the dev split of subsection 5 and versioned with the rules.

This is a planning input rather than a fixed rule, because the evidence is one measurement, on
linked pairs, with exact cosine. It suggests dense-alone ranking in artist Cyrillic, artist
Hebrew, and label Japanese kana, where fusion gives back most of dense's gain, and it does not
settle the model. `bge-m3` embeds about seven times slower than `e5-small` (195.8 against
1,483.6 names per second for artists) and leads in only some cells.

ADR 0013's "embeddings only supplement trigrams" rests on `gm-design-chw.3`'s mostly Latin
sample, where dense retrieval lost at recall@1 in every slice. In the five dense cells
`gm-design-e0b.1` shows the reverse: the better model beats `pg_trgm` at recall@1 in each. The union keeps ADR 0013's intent: no trigram candidate is
lost, and dense ranking decides only order.

Rejected alternative:

- **One RRF rule for every cell.** It halves the gain in artist Hebrew and turns artist
  Cyrillic from a pass into a near-miss.

#### 4. The namesake rule: an ambiguous artist or label is a hazard, never a set

A namesake is a different person or company. A wrong promotion merges two of them: their
aliases, their catalog rows, and through ADR 0009's merge, whatever a user owns of them. That
is the opposite of section 4's case. Two indistinguishable pressings are the same work, so an
ambiguous edition group is a partial truth worth storing as a set. Two same-named artists share
nothing but a string, so no set-valued artist or label candidate is stored, no fallback to a
broader entity exists, and an ambiguous candidate is kept only so a reviewer can reject it or
resolve it.

Name evidence never suffices, for two reasons. When two or more pool entities share the
leading candidate's normalized name, recall@1 collapses, as both spikes found. And in the
unlinked population the true counterpart is often absent from Discogs altogether, so a unique
name match can still be a namesake. The candidate row therefore carries non-name evidence, and
acceptance is bounded by it:

- **Positive evidence, which can support an accept.** Release overlap: a release credited to
  the MusicBrainz entity, or issued on the label, that resolves by catalog link or promotion to
  a Discogs release crediting the candidate. A shared external URL, such as an official site or
  a label's Bandcamp page, carried by both records.
- **Corroborating evidence, which never supports an accept alone.** Active years and country.
  Discogs records neither for artists or labels, so both are derived from the releases credited
  to the candidate. They are weaker discography evidence, not independent facts.
- **Contradicting evidence, which blocks an accept.** Person against group, non-overlapping
  active years, or release overlap that points at a different candidate. A reviewer may
  override it only by recording evidence outside both records.

A candidate is **contested** when another pool entity, or another queued candidate, shares its
normalized name after Discogs's `(2)`-style suffix is stripped. An uncontested candidate is
accepted only with at least one positive signal and no contradiction. A contested candidate is
accepted only when positive evidence singles it out from every namesake. Anything else stays
unaccepted, and the MusicBrainz entity keeps its own native id, which is today's state. Neither
the matcher, a harness, nor the review action breaks a tie by id or insertion order.

Rejected alternatives:

- **Accept an uncontested name match.** A unique name in the pool says nothing when the true
  counterpart is missing from Discogs.
- **Keep an ambiguous namesake group as a set, as section 4 does for editions.** A set of
  namesakes asserts nothing true about any member.
- **Treat country and years as sufficient.** For Discogs they are derived from releases, so
  they can only repeat what release overlap already says, less precisely.

#### 5. The bar: measured per cell on newly linked entities, through HNSW

Nothing in this amendment is built until a measurement clears this bar in at least one cell,
and only cells that clear it are built. The measurement follows section 6's time-split: the
query set is the MusicBrainz artists and labels in a scoped script that had no Discogs link in
one JSON dump and gained exactly one by a later dump. Each entity's earlier record is the query
and the new link is the label. The pool is every Discogs artist or label in a dump no older
than the earlier MusicBrainz dump, minus subsection 1's exclusion. It is not sampled, because
namesake density grows with pool size. Queries are split into dev and test once, seeded.

**Precondition: HNSW, not exact cosine.** Dense retrieval is measured through pgvector HNSW at
the index shape ADR 0013 adopts (`halfvec`, `m = 16`, `ef_construction = 64`, cosine) and one
fixed `ef_search`, never through exact cosine. The harness also reports HNSW recall@10 against
exact search on the same cell, so that gap is known. `gm-analytics-engine-ieu.3`'s HNSW
measurement on production FastRP vectors sets the procedure and informs `ef_search`, but it is
not a substitute: text-embedding recall does not transfer from 128-dimension graph vectors.

**Minimum size.** A cell is decided only with at least 100 dev and 400 test queries. A cell
below that is neither GO nor NO-GO. It waits for a longer window, and nothing is built for it.
Label cells may take many months to reach it.

**The bars, per cell, on the test split, each on a 95% interval from a seeded query
bootstrap:**

- **Gain.** In a dense cell, the lower bound of the paired interval on the chosen policy's
  recall@10 minus `pg_trgm`'s must be at least **5 points**, ADR 0013's bar applied to the
  bound. A dense cell that misses it may still pass as trigram-only, on the bars below.
- **Queue.** The upper bound on mean candidates queued per query must be at most **3**.
  Candidates are counted individually, because namesakes are distinct entities and each needs
  its own decision.
- **Precision.** The lower bound on the share of queued candidates that are the correct entity
  must be at least **50%**.
- **Namesake safety.** Of test queries where subsection 4's rule, applied mechanically to the
  harness's evidence, singles out exactly one candidate for acceptance, the upper bound on the
  share where that candidate is the wrong entity must be at most **2%**. This bars the rule, not
  the reviewer. The reviewer is a second check, not the first.

**Threshold.** The threshold is on the cell's policy score. It is the most permissive value at
which the dev split meets the queue and precision bars on point estimates, chosen once on dev
and applied to test unchanged. If no value meets both on dev, the cell is NO-GO.

**Reported alongside, with no bar.** Recall@10 of each method through HNSW, the share of test
queries whose correct entity reaches the queue, the contested-queue rate, the share of contested
queries the evidence rule can resolve, and the unlinked population per script. Also reported: a
hand-labelled random sample of currently unlinked entities in each cell, giving the share that
reaches a non-empty queue and that queue's precision. The time-split has a counterpart by
construction and the served population often does not, so this sample sizes the reject load a
reviewer will actually carry. Subsection 4's positive-evidence rule, not a bar, is what keeps an
absent counterpart from being promoted.

**Outcome.** A cell that clears every bar is GO and is built. A cell that misses one is NO-GO
and stays out until a further amendment. If no cell clears, artist and label candidates stop
at this record.

**Independence from editions.** Scores are not shared across kinds, so this gate is separate
from section 6. The second 2026-09-25 amendment's rule that an edition NO-GO leaves "sections 1
to 5 or 7" unbuilt is narrowed here: an artist or label GO builds the `matching` schema, the
matcher role, and the review action for its cells alone, whatever the edition re-run returns.

**Footprint, an open precondition.** A linear extrapolation of ADR 0013's size table puts a
full Discogs artist name index near 10 GiB at `e5-small`'s 384 dimensions and over 20 GiB at
`bge-m3`'s 1,024, beyond the artists index that ADR 0013 made the largest admitted scope. A
label index at 384 dimensions is near 2.5 GiB. The implementation plan must settle this before
the first build: narrower vectors that still clear the bar, a pool restricted without breaking
subsection 1, or an ADR 0013 amendment admitting the index. Scoring exactly inside the batch
job, as `gm-design-e0b.1` did, would avoid the index but not the owner's HNSW validation, so it
would need its own amendment.

Rejected alternatives:

- **The aggregate recall@10 gain alone, as `gm-design-e0b.1` measured it.** It measures
  retrieval on linked pairs through exact cosine, and says nothing about queue load or namesake
  harm.
- **Section 6's group unit.** Groups are sets of indistinguishable editions. Namesakes are not
  indistinguishable, and grouping them would let one decision merge several.
- **Pooled scripts for thin label cells.** Pooling would recreate the script-agnostic
  threshold subsection 1 rejects. A thin cell waits.

#### 6. Rule version

Each kind has its own rule version, recorded on every run and decision row. It fixes the script
classifier, name normalization and suffix stripping, the per-cell retrieval policy, the
embedding model and its version, the index parameters and `ef_search`, the candidate depth, the
per-cell thresholds, and subsection 4's evidence rules. Any change is a new version. A change to
retrieval, normalization, classifier, model, or evidence rules re-runs the subsection 5 harness
and must clear its bars before its candidates replace the running version's. Artist, label, and
edition versions never share a threshold or a score.

#### 7. Producer, storage, and promotion under ADR 0005 and ADR 0009

The producer is section 1's: a scheduled batch job in `analytics-engine`, under the same
reasoning from [ADR 0005](0005-source-owned-catalog-ingestion.md). A matcher reads two sources,
so it sits downstream of both producers and both loaders, and neither loader changes. The
matcher role's grants widen to `SELECT` on both catalogs' artist and label tables and on the
release and credit tables the evidence rule reads. The name embeddings are matcher-internal,
stored in the `matching` schema with the model version, written only by that role, and not in
ADR 0013's similar-item embedding tables. They are provider-derived and fall under ADR 0013's
quarantine.

Candidates live only in the `matching` schema, keyed by entity kind, as section 2 decides.
**`gm-design-e0b.1`'s recommendation 6 is superseded.** It proposed writing candidates to
`provider_aliases` as `source = 'inference'`, and ADR 0013's "Identity candidates" section says
the same. Both predate sections 2 and 3. For artist and label candidates, no unreviewed
candidate is ever written to `provider_aliases`, under any source. Only a person's reviewed
acceptance in `catalog-api` writes identity.

Promotion is section 3's transaction, applied to the kind. `catalog-api` closes the aliases on
the MusicBrainz artist's or label's native id, re-inserts them against the Discogs entity's
native id as `source = 'user'` with confidence 1.0, and sets `gm_item_id` on that one
`musicbrainz.artists` or `musicbrainz.labels` row. The decision row records the evidence the
acceptance cited under subsection 4. Revert, rejection suppression, and section 8's
contradiction revert apply unchanged: a MusicBrainz link later published to a different Discogs
entity closes the promotion.

A promotion of an artist or label is a merge of two catalog items of the same kind, so it runs
[ADR 0009's merge](0009-native-identity-and-provider-aliases.md#2026-09-25-superseded-catalog-items-and-native-id-merge)
steps inside the same transaction, and its exact reversal is what makes a wrong namesake merge
recoverable. That amendment's `cause` vocabulary is closed at `edition_promotion` and
`catalog_reattachment`, and it requires artist and label promotions to join it by amendment. A
one-value ADR 0009 amendment, proposed as `artist_label_promotion`, must land before the first
artist or label promotion. It is not made here. Until `catalog-api` implements the merge
steps, the dependents guard applies to artist and label promotions exactly as to editions.

#### 8. Not decided here

- Implementation beads, in any repository.
- The Han path of subsection 2.
- The scripts listed as promising but unconfirmed.
- Latin-script names.
- The footprint precondition of subsection 5.
- The ADR 0009 `cause` value of subsection 7.

Sections 1 to 6 and 8 are unchanged for editions. Section 7 is fulfilled for the three scripts
above.
