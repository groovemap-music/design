# ADR 0014: Ownership of cross-catalog release-edition candidates

- Status: Accepted

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
native-id merge decision this record does not make.

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
native-id merge decision deferred below. Once promotions exist, it is also what performs
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
  now and a native-id merge decision is deferred.
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
  dependents guard. Its catalog re-attachment job in section 8 is not gated by section 6. Any operator interface consumes them through the admin contract it already
  publishes.
- **`deployment`** and the homelab provision the matcher role's login.

### Follow-ups

These are planning inputs. None is filed by this record.

- **Unlinked-population measurement.** The section 6 measurement, and the next planning input
  for this program. Nothing else here proceeds without it.
- **Graph resolution through native ids.** `graph.mb_release` and its neighbours reach Discogs
  only through `discogs_release_id`, so a promoted edition is invisible to the property graph.
  Whether those views should join through `gm_item_id` is a `database-schema` decision under
  ADR 0012.
- **Catalog re-attachment of split-linked items.** The section 8 job in `catalog-api`, for
  releases, release groups, artists, and labels. It does not wait on the section 6
  measurement, and a first run should report how many items load order has split.
- **Native-id merge.** What happens to a native item superseded by an identity decision,
  including one with dependents, whether from a promotion or a section 8 re-attachment. It is
  an ADR 0009 question, not an edition question.
- **UPC-A to EAN-13 in the identifier vocabulary.** A lookup improvement independent of
  matching, left to its own vocabulary change.
- **Artist and label candidates.** An amendment under section 7, once `gm-design-e0b` has
  landed and a generator for those kinds is adopted.
