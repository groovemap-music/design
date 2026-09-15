# Controlled third targeted defect audit — 2026-09-14

Status: pass

The third audit found zero P2-or-higher root causes and zero manifestations in the three
frozen causal classes. All three are published as zero-result classes, all required disposable
mutations were killed, and no multi-site cause remains to identify. The machine-readable source
is [`verification/targeted-defect-audit-v1.json`](../../verification/targeted-defect-audit-v1.json).

## Frozen protocol and comparison boundary

The protocol was frozen and committed before implementation inspection. It fixed eight exact
commit/tree pairs, the three causal classes and their surfaces, a P2 counting threshold, a
150-minute execution budget, a 30-minute reviewer budget, and the classification/counting rules.
The audit used 34 minutes and did not expand scope.

The historical comparator is the `gm-design-dg-7oi3` portfolio analysis: 114 July 2026 bug-hunt
beads, 118 August 2026 beads, about 40% mirrored-service findings in both hunts, and two P0
Rust-to-Python contract failures. This targeted audit compares yield within those same causal
classes. It does not treat the eight-repository controlled population as an organization-wide
defect-rate sample.

| Causal class | Unique root causes | Manifestations | Multi-site causes | Result |
| --- | ---: | ---: | ---: | --- |
| Multi-site implementation drift | 0 | 0 | 0 | Zero-result class |
| Permissive-mock blindness | 0 | 0 | 0 | Zero-result class |
| Cross-language contract drift | 0 | 0 | 0 | Zero-result class |

This is materially lower targeted-class yield than the July/August baseline: the prior cohorts
contained repeated multi-site findings and two P0 cross-language failures, while the frozen
controls passed and every injected representative defect was detected.

## Mutation evidence

The source-mutation harness materialized each exact Git revision into a temporary archive, changed
one invariant, ran the owner test, and discarded the archive. It proved that:

- changing shared `REJECT` settlement into requeue was killed by `tests/test_delivery.py`;
- bypassing the shared revocation state at the NLQ sibling was killed by
  `tests/test_nlq_token_revocation.py`;
- removing integer-to-string Discogs identity coercion was killed by the MusicBrainz graph test;
- weakening the 90% purge veto from `>=` to `>` was killed at the exact boundary.

The command was:

```text
python3 scripts/audit-disposable-mutations.py --python-libraries $WORKSPACE/python-libraries --catalog-api $WORKSPACE/catalog-api --musicbrainz-graph-enricher $WORKSPACE/musicbrainz-graph-enricher --discogs-sql-loader $WORKSPACE/discogs-sql-loader
```

It returned four killed mutations and zero survivors. The unmutated controls returned 28 shared
runtime tests, 11 catalog revocation tests, 14 Discogs graph settlement tests, 34 Discogs SQL
settlement/purge tests, 10 MusicBrainz graph delivery tests, and 31 MusicBrainz SQL
delivery/identity tests, all passing.

## Real database boundaries

`just test-integration` passed in all four consumers. The SQL lanes ran against
`postgres:18-alpine@sha256:d3e1620b530c944afa6e887d22eb899824da68e19c52024bf98f5220c88a65b2`
and returned 11 Discogs plus three MusicBrainz tests. The graph lanes ran against
`neo4j:2026-community@sha256:dbc377fb9cd8fe8dabc19d3041b197d5ca0ef8bae514cea175b8df265e5b7a76`
and returned six Discogs plus three MusicBrainz tests. Every container was disposable and bound
only to loopback.

The explicit real-engine harness then sent malformed PostgreSQL query and UUID parameter probes,
and malformed Neo4j query and multi-row strict-result probes. Both pinned engines rejected every
mutation. This closes the query, parameter, and result-shape seams that permissive mocks cannot
exercise.

```text
uv run python $DESIGN/scripts/audit-real-database-mutations.py postgresql
uv run python $DESIGN/scripts/audit-real-database-mutations.py neo4j
```

## Producer, Python, and image boundaries

Both generated producer contracts were current. Discogs' media fixture and complete tiny-dump
event-stream golden tests passed; MusicBrainz's media fixture parity test passed. Each producer's
six versioned JSON fixtures then passed JSON Schema 2020-12 validation with `jsonschema 4.26.0`
from both matching Python consumer environments. Replacing a string identity with an integer and
malforming `started_at` were rejected in every environment.

```text
PYTHONDONTWRITEBYTECODE=1 uv run python $DESIGN/scripts/audit-catalog-fixtures.py $PRODUCER/contracts/catalog-events/v1 $SOURCE
```

`just image` passed for both producers and all four consumers. The two producer images executed
their CLI smoke path; the Discogs image also retained its embedded extractor-smoke manifest. Each
consumer image imported its production package and proved the `1000:1000` runtime identity. Exact
local image digests are retained in the machine record. These are local, content-addressed audit
artifacts and were not pushed or published.

## Exact repository revisions

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

## Preserved history

This report adds a new versioned protocol and result record. It does not rewrite the 2026-09-13
organization verification, the shared-delivery rollout, or the Repowise defect-risk refresh. The
Design gate verifies all six historical file digests before accepting this audit.
