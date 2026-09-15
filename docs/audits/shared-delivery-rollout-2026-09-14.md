# Shared-delivery rollout verification — 2026-09-14

Status: pass

This report attests the landed `common.delivery` and `common.batch` rollout across the shared
runtime and its four catalog consumers. The machine-readable source is
[`verification/shared-delivery-rollout-v1.json`](../../verification/shared-delivery-rollout-v1.json).
The reviewed revisions and trees below were clean, exact Git objects rather than branch-name
proxies.

## Reviewed trees and gates

| Repository | Revision | Tree | `just check` | `just image` | Delivery model |
| --- | --- | --- | --- | --- | --- |
| `python-libraries` | `24704f5fd48d3ef4fff29398585e9924e225b0c5` | `c5b96bdeab082057480a26784ad6065497aaae9a` | Pass | Not applicable | Shared runtime |
| `discogs-graph-enricher` | `705395fd46be625b3171061cfde747175f7f89e2` | `a63ee882da8edaa45b66adf17b623aa950cbb254` | Pass | Pass | Batch |
| `discogs-sql-loader` | `0f7b5d6ed679cf7233fe6118ab407391928a71c9` | `afdde4351abae3c6991d75b74a773d8893f744a8` | Pass | Pass | Batch and single-delivery |
| `musicbrainz-graph-enricher` | `fa8ad811d8989f1bf87dcffdfe24ecb8a15deb93` | `f3e9e3fd9434dd73f2c774bcb17ff4e645af0d2b` | Pass | Pass | Single-delivery |
| `musicbrainz-sql-loader` | `224bf2809c465d638e5cc4e95e815f2b5be79d90` | `cc686c7cd0091222e86366ada4851f88d96b30de` | Pass | Pass | Single-delivery |

The four image gates built the staged runtime wheel from the pinned source, imported each service
from the resulting local image, and verified the runtime UID and GID as `1000:1000`. The runtime
repository has no image gate.

## Pin and dependency evidence

All four consumers record the same full 40-character runtime revision,
`24704f5fd48d3ef4fff29398585e9924e225b0c5`, in both `pyproject.toml` and `uv.lock`. The lock
sources resolve the requested revision and the checked-out commit to that same value.

Static source review found `common.batch` imports only in the two Discogs consumers. Their queued
delivery lifecycle is owned by `common.batch.AsyncBatchEngine`; the Discogs SQL non-batch path is
owned by `common.delivery.run_delivery`. Both MusicBrainz consumers remain one transaction per
delivery, import no `common.batch`, and use `common.delivery.run_delivery` for their terminal
settlement. No consumer contains a second broker-settlement retry loop in place of those shared
authorities. Service-owned completion markers and ingress validation may still make a direct,
single terminal decision; they do not implement a competing retry lifecycle.

The shared `src/common/delivery.py` and `src/common/batch.py` modules import no `aio-pika`, Neo4j,
Psycopg, or consumer service code. Their protocols remain transport- and storage-neutral.

## Ownership boundary

`common.delivery` owns transport-neutral terminal settlement and cancellation semantics.
`common.batch` owns the Discogs keyed queues, backpressure, concurrency, retry accounting, poison
isolation, cancellation restoration, bounded drain, and post-submit settlement.

Each consumer continues to own serialization and validation; database transactions and concrete
exception classification; telemetry policy; RabbitMQ QoS; control and completion state; and purge
or maintenance policy. Fix transport-neutral settlement, retry, queue, concurrency, cancellation,
or drain defects once in `common.delivery` or `common.batch`, then advance each consumer to the
reviewed immutable runtime pin. Do not grow another consumer-local lifecycle implementation.

## Preserved history

This audit is a new versioned record. It does not rewrite the
[`2026-09-13 organization-wide verification`](organization-wide-verification-2026-09-13.md) or
its machine-readable source. At this audit's input tree, those files retain SHA-256 digests
`8a02d82194ac6cfdb69bb010c29a6ef21cb6f801a6a851305198fdf4875bb06b` and
`7c042ba9d044f3fd582a1dd93e1af9b83d75d6cb5f6a3d8e551d3a022f70e514`, respectively. The Design
gate recomputes both digests so a later in-place rewrite fails closed.
