# Bug-supply remediation effectiveness verdict — 2026-09-14

Status: close portfolio

Every material-improvement threshold passed. The controlled third audit found zero unique root
causes, zero manifestations, zero multi-site causes, zero P0/P1 findings, and zero surviving
mutations in the three causal classes. The relevant owner-hive, replacement, shared-runtime, and
consumer-migration molecules are closed. The final disposition is therefore to append this
evidence to `gm-design-dg-7oi3` and close that portfolio tracker, without filing remediation.

The machine-readable source is
[`verification/portfolio-effectiveness-v1.json`](../../verification/portfolio-effectiveness-v1.json).
It preserves every earlier audit snapshot by SHA-256 and does not replace their raw evidence.

## Before and after

| Measure | Historical evidence | Controlled result | Threshold | Verdict |
| --- | --- | --- | --- | --- |
| Duplicate/mirror manifestations | About 40% of findings in each 114-bead July and 118-bead August hunt; exact raw duplicate counts were not retained | 0 root causes, 0 manifestations, 0 multi-site causes; normalized 0% under the declared zero-yield convention | At most 20%, and at least 50% below about 40% | Pass: 0%, 100% relative reduction |
| Shared delivery, JWT, and pool recurrence | Repeated cloned settlement/validation defects and a live sync/async pool twin | 0 shared-delivery recurrence, 0 JWT recurrence, 0 removed-pool recurrence | Exactly 0 | Pass |
| Defects concealed by permissive database mocks | Concealment existed; seven August tests pinned buggy behavior across the historical classes, but an exact database-only finding count was not retained | 0 concealed defects; 23 real-database tests passed and four malformed real-engine mutations were killed | Exactly 0 | Pass |
| Rust-to-Python contract mismatch | Two P0 findings: identity type and `started_at` semantics | 0 mismatches and 0 P0/P1; 24 fixture validations and eight before-persistence schema mutation rejections | Exactly 0 | Pass |

The current raw result is intentionally explicit: 0 unique root causes, 0 manifestations, 0
multi-site causes, 0 P0, 0 P1, 0 P2, 0 P3, and 0 mutation survivors. The normalized mirror share
uses numerator 0 and denominator 0. For the agreed threshold only, a zero-finding audit reports
that share as 0%; the raw 0/0 denominator is retained so the value cannot be mistaken for a
population estimate.

## Method

The primary evidence is the protocol-frozen audit in
[`targeted-defect-audit-2026-09-14.md`](targeted-defect-audit-2026-09-14.md). It fixed eight
repository revisions, the three causal classes, a P2 counting threshold, the finding and
manifestation rules, and the execution/reviewer budgets before inspection. Unmutated owner tests,
one-variable disposable source and schema mutations, pinned PostgreSQL and Neo4j boundaries,
producer golden fixtures, Python validation, and six released-image paths then tested the
remediated invariants.

The shared-rollout record proves that `common.delivery` and `common.batch` own the agreed
settlement surfaces. All four consumers pin the same 40-character runtime revision in their
manifest and lock, pass `just check`, pass their image gate, and retain no independent settlement
loop. The targeted audit killed a settlement divergence and a catalog NLQ revocation-state bypass.
The current Repowise evidence also finds no `ResilientPostgreSQLPool` symbol, literal, or dead-code
surface at its exact indexed head.

The database proof combines three layers:

- owner-hive interface-faithful PostgreSQL and Neo4j doubles;
- 23 integration tests against digest-pinned real engines, plus malformed query, UUID parameter,
  Cypher query, and strict result-shape mutations;
- the digest-pinned released-stack fixture path covering extractor, broker, consumers, and
  databases.

The Rust-to-Python proof keeps each producer's generated contract current, passes both golden
paths, validates six fixtures from each producer in both matching Python consumer environments,
and passes all six image gates. Integer-for-string identity and malformed `started_at` are rejected
by schema validation before persistence in all four consumer environments. The additional artist
identity-normalization and exact purge-boundary mutations are also killed.

Repowise 0.50.0 is supporting evidence only. It supplies exact-head repository-scoped health,
complexity, clones, coverage, churn, hotspots, dead code, and risk. No health score or aggregate
determines this verdict.

## Exact effectiveness revisions

| Repository | Revision | Tree |
| --- | --- | --- |
| `python-libraries` | `24704f5fd48d3ef4fff29398585e9924e225b0c5` | `c5b96bdeab082057480a26784ad6065497aaae9a` |
| `catalog-api` | `7e6f21f01cd645f552cdf7ac54ccdecdfb2554df` | `3538e664444d5bb9e078155e0d08886c1434d2bb` |
| `discogs-ingestion` | `8df3b3d05b0e4424874e0104c1f45c5d0c674a7b` | `91e9cb47c525d9f7b70893a8bc3c8c6bf4f45cdb` |
| `discogs-graph-enricher` | `705395fd46be625b3171061cfde747175f7f89e2` | `a63ee882da8edaa45b66adf17b623aa950cbb254` |
| `discogs-sql-loader` | `0f7b5d6ed679cf7233fe6118ab407391928a71c9` | `afdde4351abae3c6991d75b74a773d8893f744a8` |
| `musicbrainz-ingestion` | `c649e5defc6e14e2322554bac24363a1ce1f3a57` | `b1235fc29c7a0a6824be58c5d63bd1c700ed25f7` |
| `musicbrainz-graph-enricher` | `fa8ad811d8989f1bf87dcffdfe24ecb8a15deb93` | `f3e9e3fd9434dd73f2c774bcb17ff4e645af0d2b` |
| `musicbrainz-sql-loader` | `224bf2809c465d638e5cc4e95e815f2b5be79d90` | `cc686c7cd0091222e86366ada4851f88d96b30de` |

The supporting Repowise index uses the same heads for five runtime/consumer repositories and the
earlier `catalog-api` merge head `8eec6ef062584e1ab0b3ea07fa16f32ab18ddbf1` with tree
`17dd4815f8a29d859503d78c2142c5a7c073a70d`. The effectiveness audit's catalog revision is its
later release commit and is the functional verdict input; the index remains supporting context.

## Owner-hive and released-stack assertions

The preserved organization matrix contains 21 passing exact-revision repository verdicts. The
later rollout adds passing `just check` evidence for the shared runtime and all four consumers,
eight matching manifest/lock runtime pins, four passing consumer image gates, and zero independent
consumer settlement loops. The controlled audit adds two digest-pinned database engines and six
content-addressed released-image gates. The deployment-owned live disposable released-stack run
used the reviewed Discogs ingestion image
`ghcr.io/groovemap-music/discogs-ingestion@sha256:db418bfc97d2d364ac0e64045b492ad8492b500c84f8ce105a04cadd400ee17c`;
the packaged fixture traversed RabbitMQ and both consumers, all 7 assertions passed in PostgreSQL
and Neo4j, and teardown removed the isolated stack. The Design policy gate verifies immutable
external action pins and all historical evidence identities.

Every routed molecule or replacement relevant to the three causal classes is closed:

- Fixture realism and enforcement: `gm-analytics-engine-fpd`, `gm-automation-6ab`,
  `gm-catalog-api-e2w`, `gm-discogs-graph-enricher-8ue`, `gm-discogs-sql-loader-4fh`,
  `gm-musicbrainz-graph-enricher-w2y`, `gm-musicbrainz-sql-loader-55p`, and
  `gm-operations-console-aho`.
- Coverage, real-engine, producer, and released-stack proof: `gm-database-schema-ot0`,
  `gm-deployment-0ak`, `gm-discogs-ingestion-dmu`, `gm-musicbrainz-ingestion-hdl`,
  `gm-operations-toolkit-8im`, and `gm-python-libraries-1hq`.
- Recovered causal remediations: `gm-catalog-api-dg-7oi3-2` for shared JWT validation and
  `gm-python-libraries-dg-7oi3-3` for the deleted zero-caller pool.
- Shared runtime and migration: the closed GO spike `gm-design-erl`, runtime
  `gm-python-libraries-0ek`, and consumers `gm-discogs-graph-enricher-9l7`,
  `gm-discogs-sql-loader-8gm`, `gm-musicbrainz-graph-enricher-20q`, and
  `gm-musicbrainz-sql-loader-5zt`.

Their full bead URIs, titles, closed states, and exact landed commits are retained in the machine
record. The five imported cross-hive tasks are also closed with explicit supersession mappings to
these owner-hive molecules; their original acceptance was not silently discarded.

## Explicit descopes

- `gm-deployment-dg-64dn`, the operator-gated live Resend account check, remains in progress. It is
  unrelated to the three defect-supply classes and is not represented as portfolio completion.
- Generic AMQP, Redis, and HTTP mock replacement is outside the database-boundary class.
- Unrelated Repowise health and dead-code candidates remain advisory maintenance inputs, not
  behavioral defect findings.
- No organization-wide defect rate is inferred from the controlled eight-repository population.
- No live credentials, publication, organization state, or production deployment was required;
  released-stack assertions used local content-addressed artifacts.

## Limitations and disposition

The historical about-40% share is approximate and lacks an exact raw duplicate count, so this
report does not reconstruct one. A zero-yield audit cannot estimate a population proportion. The
historical Repowise baseline was monorepo-scoped and the current metrics are repository-scoped, so
their averages are not directly compared. Local image evidence does not claim a live production
deployment.

Within those limits, every agreed threshold passes and all scoped remediation is closed or
explicitly descoped. The portfolio tracker should be closed after receiving this final evidence;
no focused remediation bead is warranted.
