# Repowise defect-risk refresh — 2026-09-14

Status: pass

This report replaces the stale pre-migration metric baseline with current, repository-scoped
Repowise evidence for the shared runtime, its four consumers, and the recovered catalog API
remediation. The machine-readable source is
[`verification/repowise-defect-risk-v1.json`](../../verification/repowise-defect-risk-v1.json).
It retains the earlier audit files byte-for-byte and does not derive a cross-repository average.

## Reproducible index

Repowise 0.50.0 initialized each repository in deterministic, no-prose mode with onboarding,
agent-file generation, editor setup, hooks, and workspace discovery disabled. The stored
configuration uses a 500-commit window, the mock embedder, full Git history, and no generated
documentation. Native jobs completed with zero failed pages. A second index-only update returned
`ok: true`, `outcome: noop`, and no degraded phases for every repository, proving that the
indexes already matched the immutable revisions.

| Repository | Revision | Tree | Pages |
| --- | --- | --- | ---: |
| `python-libraries` | `24704f5fd48d3ef4fff29398585e9924e225b0c5` | `c5b96bdeab082057480a26784ad6065497aaae9a` | 154 |
| `catalog-api` | `8eec6ef062584e1ab0b3ea07fa16f32ab18ddbf1` | `17dd4815f8a29d859503d78c2142c5a7c073a70d` | 504 |
| `discogs-graph-enricher` | `705395fd46be625b3171061cfde747175f7f89e2` | `a63ee882da8edaa45b66adf17b623aa950cbb254` | 96 |
| `discogs-sql-loader` | `0f7b5d6ed679cf7233fe6118ab407391928a71c9` | `afdde4351abae3c6991d75b74a773d8893f744a8` | 74 |
| `musicbrainz-graph-enricher` | `fa8ad811d8989f1bf87dcffdfe24ecb8a15deb93` | `f3e9e3fd9434dd73f2c774bcb17ff4e645af0d2b` | 66 |
| `musicbrainz-sql-loader` | `224bf2809c465d638e5cc4e95e815f2b5be79d90` | `cc686c7cd0091222e86366ada4851f88d96b30de` | 66 |

The successful commands, per-repository initialization timestamps, update window, configuration
fingerprint, and sanitized native outputs are in the machine record. Host-local paths were
replaced by repository names. Repowise's update step emitted untracked VS Code recommendation
files despite the initialization flags; those generated files were removed, so no editor setup
was retained and no tracked implementation file changed.

## Production health and defect signals

The health command used `--scope production` and the default `everything` count model.
The numbers below are six separate repository populations. They are not averaged and are not
compared with the differently scoped historical monorepo population.

| Repository | Health | Hotspot health | Worst production file | Max CCN | CCN > 10 files | Duplicated files | Max duplication | Churn findings | Function hotspots |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `python-libraries` | 6.65 | 3.66 | `src/common/postgres_resilient.py` (1.62) | 28 | 4 | 10 | 41.94% | 2 | 6 |
| `catalog-api` | 5.86 | 4.31 | `api/routers/extraction_analysis.py` (2.05) | 41 | 27 | 39 | 64.54% | 4 | 58 |
| `discogs-graph-enricher` | 5.51 | 2.22 | `graphinator/graphinator.py` (1.81) | 34 | 3 | 4 | 34.04% | 2 | 10 |
| `discogs-sql-loader` | 5.37 | 3.69 | `tableinator/tableinator.py` (1.88) | 32 | 2 | 1 | 7.03% | 2 | 8 |
| `musicbrainz-graph-enricher` | 5.13 | 1.90 | `brainzgraphinator/brainzgraphinator.py` (1.90) | 16 | 1 | 1 | 1.67% | 1 | 7 |
| `musicbrainz-sql-loader` | 4.98 | 1.81 | `brainztableinator/brainztableinator.py` (1.81) | 28 | 1 | 3 | 30.56% | 1 | 9 |

The clone/mirror column is the native duplication surface: per-file duplication percentages plus
`dry_violation` biomarkers, with near-clone deduplication enabled in the index configuration.
The full biomarker counts in the machine record retain complexity, large/brain method, nesting,
coverage-gradient, churn, and hotspot findings rather than presenting the health score alone.

Repowise emitted one `untested_hotspot`: `src/common/__init__.py` in `python-libraries`,
with 15 dependents, 13 changes in the 90-day window, no paired test file, and no mapped coverage.
The other five production reads emitted no finding of that type. This is a prioritization signal,
not proof that the file is behaviorally untested.

## Coverage

All available Cobertura reports were explicitly ingested at the indexed commits. The five
runtime/consumer reports were produced by the exact-head `just check` gates retained in the
shared-delivery rollout record. `catalog-api` had no report on disk, so `just coverage` was run:
2,593 tests passed, three were deselected, and the suite reported 98.57% total coverage.

| Repository | Mapped files | Unmapped report paths | Repowise mapped lines | Repowise line coverage |
| --- | ---: | ---: | ---: | ---: |
| `python-libraries` | 24 | 0 | 2,698 / 2,883 | 93.58% |
| `catalog-api` | 52 | 5 | 4,682 / 4,745 | 98.67% |
| `discogs-graph-enricher` | 8 | 1 | 1,430 / 1,507 | 94.89% |
| `discogs-sql-loader` | 9 | 1 | 1,079 / 1,114 | 96.86% |
| `musicbrainz-graph-enricher` | 5 | 1 | 699 / 713 | 98.04% |
| `musicbrainz-sql-loader` | 5 | 1 | 764 / 801 | 95.38% |

The four consumer mapping misses are `catalog_contract.py`; the catalog API example is the
generated operations-console contract path. Repowise reports `mapping_partial: false` even when
the add command reports unresolved paths, so the record preserves both native values. Its mapped
percentage must not be substituted for the whole-report percentage when paths were excluded.
The catalog API's status timestamp also predates the coverage-file modification timestamp; both
are retained verbatim, and neither is used to infer command order.

## Dead code and removed pool surface

| Repository | Findings | Unreachable files | Unused exports | Unused internals | Zombie packages | Safe-to-delete flags |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `python-libraries` | 17 | 9 | 1 | 7 | 0 | 0 |
| `catalog-api` | 23 | 7 | 6 | 9 | 1 | 6 |
| `discogs-graph-enricher` | 4 | 4 | 0 | 0 | 0 | 0 |
| `discogs-sql-loader` | 4 | 4 | 0 | 0 | 0 | 0 |
| `musicbrainz-graph-enricher` | 4 | 4 | 0 | 0 | 0 | 0 |
| `musicbrainz-sql-loader` | 5 | 5 | 0 | 0 | 0 | 0 |

The `python-libraries` dead-code result contains no `ResilientPostgreSQLPool` match. A separate
structural symbol search at the same indexed and live commit reports `exact_match: false` and
`index_behind: false`; a repository source sweep also returns zero literal matches. The
replacement bead's zombie-pool requirement is therefore satisfied by a current index-backed
read. This does not mean the overall dead-code result is empty: `catalog-api/performance` is an
unrelated zombie-package candidate, and the other findings remain recorded for normal triage.
Repowise dead-code confidence is advisory; none of these results independently authorizes deletion.

## Current-HEAD change risk

The risk command evaluates each single `HEAD` commit against that repository's own recent-commit
baseline. It does not describe absolute repository quality.

| Repository | Percentile | Classification | Review priority | Baseline commits |
| --- | ---: | --- | --- | ---: |
| `python-libraries` | 95.2 | Elevated | High | 199 |
| `catalog-api` | 33.7 | Typical | Moderate | 199 |
| `discogs-graph-enricher` | 86.2 | Elevated | High | 200 |
| `discogs-sql-loader` | 92.8 | Elevated | High | 200 |
| `musicbrainz-graph-enricher` | 92.2 | Elevated | High | 102 |
| `musicbrainz-sql-loader` | 92.2 | Elevated | High | 103 |

The machine record preserves the corresponding diff-shape scores, line and file counts, entropy,
fix-history density, and baseline sizes. These are current immutable-commit facts, not a before/after
claim.

## Bead and label reconciliation

The evidence matrix maps both recovered replacement beads, the shared-runtime implementations,
all four migration epics, their implementation children, and the two real-engine proof beads to
the exact repository metric record. Workflow-only state-change children do not produce code and
therefore are outside this code-metric population.

The imported portfolio text said a `repowise-recheck` label marked every bead, but direct issue
reads show that neither replacement bead ever carried that label. There is consequently no label
mutation to perform. This versioned matrix satisfies the intended refresh requirement and records
the discrepancy explicitly.

## Preserved history

This audit adds a new versioned record. It does not rewrite the
[`2026-09-13 organization-wide verification`](organization-wide-verification-2026-09-13.md) or
the [`2026-09-14 shared-delivery rollout`](shared-delivery-rollout-2026-09-14.md). The Design
gate verifies the SHA-256 identity of both narratives and both machine-readable records.
