# Shared delivery and batch-processing contract spike

Status: GO, with a split delivery/batch boundary  
Evidence date: 2026-09-13  
Spike: `gm-design-erl.1`  
Decision: `gm-design-erl.2`  
Portfolio tracker: `gm-design-dg-7oi3`

## Question

Can the two Discogs batch processors and the two MusicBrainz single-delivery
consumers share a narrow, stable delivery lifecycle without moving database,
serialization, telemetry policy, or control-message ownership out of their service
repositories?

The earlier proposal treated all four consumers as batch-processor clones. The
question here is deliberately narrower: which lifecycle decisions are actually the
same, and which similarities disappear when the current implementations and tests are
compared?

## Method

The review compared production code and contract tests at these clean revisions:

| Repository | Reviewed revision | Primary evidence |
| --- | --- | --- |
| `python-libraries` | `66b65dc322c7a6b742f7a84e55a598802ecb55f5` | [`common.rabbitmq_resilient`](https://github.com/groovemap-music/python-libraries/blob/66b65dc322c7a6b742f7a84e55a598802ecb55f5/src/common/rabbitmq_resilient.py#L416-L500) |
| `discogs-graph-enricher` | `906561a33282d598fffd490b7713d578e03e1bd5` | [`graphinator.batch_processor`](https://github.com/groovemap-music/discogs-graph-enricher/blob/906561a33282d598fffd490b7713d578e03e1bd5/graphinator/batch_processor.py#L31-L705), [`make_message_handler`](https://github.com/groovemap-music/discogs-graph-enricher/blob/906561a33282d598fffd490b7713d578e03e1bd5/graphinator/graphinator.py#L1225-L1401) |
| `discogs-sql-loader` | `b85259dc432be46f16b32521f39a521cf851abd3` | [`tableinator.batch_processor`](https://github.com/groovemap-music/discogs-sql-loader/blob/b85259dc432be46f16b32521f39a521cf851abd3/tableinator/batch_processor.py#L32-L751), [`_process_data_message`](https://github.com/groovemap-music/discogs-sql-loader/blob/b85259dc432be46f16b32521f39a521cf851abd3/tableinator/tableinator.py#L630-L906) |
| `musicbrainz-graph-enricher` | `d5026c448810f2b7c1ed1b1e276868e5abdbef96` | [`make_message_handler`](https://github.com/groovemap-music/musicbrainz-graph-enricher/blob/d5026c448810f2b7c1ed1b1e276868e5abdbef96/brainzgraphinator/brainzgraphinator.py#L625-L801) |
| `musicbrainz-sql-loader` | `0c301978800a8cc0de2d96ecd42b4374bf59aca7` | [`on_data_message`](https://github.com/groovemap-music/musicbrainz-sql-loader/blob/0c301978800a8cc0de2d96ecd42b4374bf59aca7/brainztableinator/brainztableinator.py#L793-L998), [`MusicBrainzRecordProcessor`](https://github.com/groovemap-music/musicbrainz-sql-loader/blob/0c301978800a8cc0de2d96ecd42b4374bf59aca7/brainztableinator/_record_processing.py#L12-L170) |

The method was a static contract review rather than a performance experiment. It
traced every terminal and non-terminal path for settlement, cancellation, control
messages, exception classification, telemetry, QoS, serialization, in-flight state,
and poison/give-up behavior. Existing tests were used as executable statements of the
intended behavior. No product repository was changed.

The design repository baseline was clean at
`0fdf99241625a278025d10d7db3fcb1f5c04e952`; `just check` passed all 99 tests before
this artifact was written. The spike molecule contained only the inventory and decision
beads plus closed lifecycle events; no implementation child had been filed.

## Evidence

### Contract comparison

| Concern | Discogs graph enricher | Discogs SQL loader | MusicBrainz graph enricher | MusicBrainz SQL loader | Shared conclusion |
| --- | --- | --- | --- | --- | --- |
| Settlement | The batch processor is the sole batch ack/nack authority. Successful members are acked; invalid or poison members are nacked without requeue; transient failures remain unsettled in the in-memory queue. | Same authority model, plus per-record `processed`, `skipped`, and `media_backfilled` outcomes and a DLQ flag that prevents unsafe stale-row purges. | The handler directly acks success/control messages, rejects invalid input, and requeues storage or generic failures. | The handler directly acks success/control messages, rejects invalid input and deterministic PostgreSQL data errors, and requeues transient or unknown failures. | A shared runner can own the exactly-once terminal operation. Domain handlers must return a disposition rather than settling the broker delivery themselves. |
| Cancellation | Cancellation while waiting for or holding the flush semaphore puts the popped batch back at the head of its queue and re-raises. Shutdown before enqueue leaves the broker delivery unsettled. | Same queue-preservation rule. | Shutdown leaves the delivery unsettled so connection close requeues it once. | Same shutdown rule. | `CancelledError` must never become a failure classification or settlement. `DEFER` means leave unsettled. |
| Control messages | `file_complete` and `extraction_complete` first drain the relevant queue. An incomplete drain requeues the control delivery; completion state and maintenance happen only after a successful drain. | Same drain gate, with stale-row purge guarded by whether any current-dump record was rejected. | No batch drain exists. Both control messages mutate service completion/cancellation state and ack. | No outer batch drain exists. Both control messages mutate service completion/cancellation state and ack. | Control-message meaning remains service-owned. A shared runner may execute and settle the returned disposition, but it must not own completion, purge, or maintenance state. |
| Exception classification | `ServiceUnavailable`, `SessionExpired`, `TransientError`, and `DatabaseUnavailableError` are transient. Other batch exceptions are deterministic/poison. | `InterfaceError`, `OperationalError`, and `DatabaseUnavailableError` are transient. Other batch exceptions are deterministic/poison; single-message data/integrity errors are permanent. | Named Neo4j availability failures are transient; the current generic path also requeues. | PostgreSQL interface/operational/unavailable errors are transient; data/integrity errors are permanent; the generic path requeues. | The common vocabulary is stable, but concrete exception membership is an owner-hive adapter decision. Unknown-error defaults must be explicit per consumer, not global. |
| Telemetry | Consumer and flush spans link queued deliveries; graph-specific metrics map write outcomes and errors. | Same span shape, but SQL records hash-unchanged and media-backfill outcomes and terminal messaging metrics. | One consumer span encloses one write; a size-one flush span is recorded locally. | One consumer span encloses one transaction; relationship/link sub-batches use an existing private `BatchObserver` port. | Share lifecycle event shapes and bounded trace-link handling. Each service retains metric names, entity mapping, and outcome translation in its observer adapter. |
| QoS | Per-consumer prefetch is `max(200, batch_size * 2)` in batch mode; it is not coupled to a small fixed connection pool. | Batch mode uses per-consumer `max(200, batch_size * 2)`. Non-batch mode uses channel-global prefetch equal to the PostgreSQL pool maximum. | Fixed per-consumer prefetch of 200. | Channel-global prefetch equals the PostgreSQL pool maximum. | QoS is resource- and mode-specific. It is not part of the shared delivery or batch API. Each owner hive keeps and tests it. |
| Serialization and validation | The service decodes JSON; the batch processor checks `id` and applies Discogs normalization before enqueue. | The service decodes JSON; the processor checks `id`, hashes, and normalization before enqueue. | The handler decodes JSON and validates missing/empty IDs. | The handler decodes JSON and validates missing, empty, and non-UUID IDs. | Serialization, validation, and normalization remain handler callbacks. Their result is a prepared payload or a terminal disposition; the shared code does not know catalog schemas. |
| In-flight tracking | Per-key deque, lazy lock, global flush semaphore, popped-batch counter, backoff deadline, adaptive size, and two independent failure counters. | Same lifecycle state, plus SQL-specific outcome and DLQ/purge state. | Broker prefetch and handler-local transaction only; no application batch queue. | Broker prefetch and handler-local transaction only; no application batch queue. | Application queue/in-flight machinery is reusable only by the two Discogs batch consumers. MusicBrainz must not be routed through it. |
| Poison and give-up | Deterministic failures shrink and retry a serialized batch, then permanently reject after the configured threshold. Transient failures only back off and never pre-charge poison state. Public drain gives up without nacking and leaves messages for periodic retry. | Same poison and drain invariants. | No local poison loop; broker redelivery is the retry budget. Invalid data is permanently rejected, while current generic failures requeue. | No local poison loop; deterministic validation/data failures reject and transient/generic failures requeue after outage throttling. | Poison counters and bounded drain belong to the Discogs batch engine. Single-delivery consumers use only shared disposition/classification vocabulary. |

### What is duplicated and what is not

The two Discogs batch processor files are 705 and 751 lines. A direct diff changes 620
lines (333 additions and 287 deletions), but their queue lifecycle is recognizably the
same: keyed deques, lazy per-key locks, one global flush semaphore, popped-batch
tracking, adaptive batch size, separate transient and deterministic counters, bounded
poison handling, periodic flush, and a non-destructive public drain. That lifecycle is
the reusable capability. Database writers, validation, telemetry, and result accounting
are adapters.

The two MusicBrainz files are not batch-processor twins. They perform one transaction
per broker delivery and rely on broker prefetch rather than an application queue. Their
shared seam is limited to delivery disposition, cancellation preservation, error
classification vocabulary, and lifecycle observation. Forcing them through the
Discogs batch engine would replace a working concurrency model and expand the test
closure without eliminating meaningful duplication.

`python-libraries` already has `process_message_with_retry`, but its current contract
retries an operation in-process and owns a single `requeue_on_error` boolean. It cannot
express permanent validation failures, service-specific classifiers, `DEFER` on
shutdown/cancellation, batch-member outcomes, or service observer adapters. The new API
should supersede that function through a compatibility wrapper rather than grow another
parallel settlement helper.

### Port scoring

Scores use 0 (poor), 1 (mixed), or 2 (strong). A zero in port narrowness or dependency
direction is a hard stop. Cross-consumer stability scores whether the contract remains
meaningful across all four consumers; a batch-only port can still be viable when its
applicability is explicit.

| Candidate | Cohesion | Port narrowness | Dependency direction | Cross-consumer stability | Test-closure reduction | Total | Finding |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `BatchSink` | 2 | 2 | 2 | 1 | 2 | 9/10 | GO for the two Discogs consumers. It accepts prepared payloads and returns one outcome per member; it never sees broker deliveries or calls ack/nack. MusicBrainz does not implement it. |
| `FailureClassifier` | 2 | 2 | 2 | 2 | 2 | 10/10 | GO for all four. The shared enum is stable while each owner maps its own storage exceptions and chooses its unknown-error default. |
| `BatchObserver` | 2 | 1 | 2 | 1 | 2 | 8/10 | GO as a lifecycle event port with a small batch extension. Metric instruments, entity labels, span types, and outcome mapping remain in service adapters. |
| One engine for all four consumers | 2 | 0 | 1 | 0 | 1 | 4/10 | NO-GO. It would make single-message services depend on irrelevant queue state and would pull control, QoS, or storage policy across the boundary. |

## Verdict

**GO**, but only for a two-layer public runtime contract:

1. A transport-neutral delivery runner owns terminal settlement and cancellation
   preservation for all four consumers.
2. An optional async batch engine owns queueing, flush serialization, in-flight state,
   transient backoff, adaptive sizing, bounded poison handling, and non-destructive
   drain for the two Discogs consumers.

This is explicitly **not** a GO for a universal batch processor. MusicBrainz stays
single-delivery. Serialization, catalog validation, control-message effects, QoS,
database transactions, persistence results, and concrete telemetry instruments remain
in their owner hives.

### Required `python-libraries` API

The implementation replan must preserve these names and semantic shapes. Type parameters
and import organization may be refined without changing ownership or outcomes.

```python
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Generic, Protocol, TypeVar

PayloadT = TypeVar("PayloadT")
KeyT = TypeVar("KeyT")


class Settlement(StrEnum):
    ACK = "ack"
    REQUEUE = "requeue"
    REJECT = "reject"
    DEFER = "defer"


class FailureKind(StrEnum):
    TRANSIENT = "transient"
    DETERMINISTIC = "deterministic"


class Delivery(Protocol):
    async def ack(self) -> None: ...
    async def nack(self, *, requeue: bool) -> None: ...


@dataclass(frozen=True)
class DeliveryResult:
    settlement: Settlement
    outcome: str
    error_type: str | None = None


class FailureClassifier(Protocol):
    def __call__(self, error: BaseException) -> FailureKind: ...


class DeliveryObserver(Protocol):
    def consume(self, destination: str, headers: object | None) -> AbstractContextManager[Any]: ...
    def settled(self, *, entity: str, result: DeliveryResult, duration_s: float, span: Any) -> None: ...


async def run_delivery(
    delivery: Delivery,
    operation: Callable[[], Awaitable[DeliveryResult]],
    *,
    classifier: FailureClassifier,
    observer: DeliveryObserver,
    destination: str,
    entity: str,
    headers: object | None = None,
    wait_before_requeue: Callable[[], Awaitable[None]] | None = None,
) -> DeliveryResult: ...


@dataclass(frozen=True)
class BatchItemResult:
    settlement: Settlement  # ACK or REJECT
    outcome: str  # service-owned, closed by each observer adapter


@dataclass(frozen=True)
class BatchPolicy:
    batch_size: int
    flush_interval_s: float
    max_pending: int
    max_concurrent_flushes: int
    min_batch_size: int
    backoff_initial_s: float
    backoff_max_s: float
    backoff_multiplier: float
    max_drain_retries: int
    max_poison_retries: int


class BatchSink(Protocol[KeyT, PayloadT]):
    async def write(self, key: KeyT, payloads: Sequence[PayloadT]) -> Sequence[BatchItemResult]: ...


class BatchObserver(DeliveryObserver, Protocol[KeyT]):
    def flush(self, key: KeyT, size: int, links: Sequence[object]) -> AbstractContextManager[Any]: ...
    def retry(self, *, key: KeyT, kind: FailureKind, attempt: int, delay_s: float, span: Any) -> None: ...


class AsyncBatchEngine(Generic[KeyT, PayloadT]):
    def __init__(
        self,
        keys: Sequence[KeyT],
        *,
        policy: BatchPolicy,
        sink: BatchSink[KeyT, PayloadT],
        classifier: FailureClassifier,
        observer: BatchObserver[KeyT],
    ) -> None: ...
    async def submit(
        self,
        key: KeyT,
        payload: PayloadT,
        delivery: Delivery,
        *,
        span_context: object | None = None,
    ) -> None: ...
    async def flush(self, key: KeyT) -> bool: ...
    async def flush_all(self) -> bool: ...
    async def run_periodic(self) -> None: ...
    def shutdown(self) -> None: ...
    def snapshot(self) -> object: ...
```

Binding semantics:

- `run_delivery` is the only caller of `Delivery.ack`/`nack` in single-delivery
  consumers. `DEFER` performs no settlement. `CancelledError` is re-raised without
  classification, waiting, observation as failure, or settlement.
- A normal operation result maps `ACK`, `REQUEUE`, and `REJECT` to one broker call.
  An operation exception classified transient optionally waits and then requeues;
  a deterministic exception rejects without requeue. `run_delivery` does not add an
  in-process retry loop. A batch ingress operation returns `DEFER` after `submit`,
  transferring later settlement authority to the engine.
- `AsyncBatchEngine` is the only caller of `Delivery.ack`/`nack` after submission.
  `BatchSink` returns exactly one `BatchItemResult` per payload or raises. The result
  preserves owner-specific outcomes such as `media_backfilled` without teaching the
  runtime their meaning.
- A transient batch exception requeues the popped members in original order, advances
  only transient backoff/adaptive state, and performs no broker settlement.
- A deterministic batch exception requeues and shrinks until the configured poison
  threshold, then rejects the affected members without requeue. It never inherits
  transient attempt count.
- `flush` returns `False` after bounded no-progress retries while retaining unsettled
  members for `run_periodic`; it never converts a give-up into a broker nack.
- Cancellation while acquiring or holding concurrency capacity restores every popped
  member in original order and re-raises.
- `DeliveryObserver` and `BatchObserver` are injected. Observer failures are isolated
  from settlement. Trace links remain capped at 64.
- `process_message_with_retry` remains temporarily as a compatibility wrapper over
  `run_delivery`, with deprecation documented. No second independent retry loop remains.
- `python-libraries` stays dependency-light: the protocol layer must not import
  `aio-pika`, Neo4j, Psycopg, or any service module.

### Four owner-hive migration scopes

The implementation must be filed as a cross-hive molecule after this GO decision is
reviewed and merged. The shared-runtime bead lands first because every consumer pins an
immutable `python-libraries` revision.

1. **`discogs-graph-enricher`.** Replace `Neo4jBatchProcessor` lifecycle code with
   `AsyncBatchEngine`; retain Discogs normalization and `Neo4jBatchProjector` behind a
   `BatchSink`; map Neo4j availability/deadlock errors with a local
   `FailureClassifier`; map existing `gm_telemetry` with a local `BatchObserver`; keep
   control-message persistence/maintenance and QoS local. Port all existing batch tests,
   especially cancellation restoration, transient/poison counter separation,
   concurrent poison serialization, bounded drain, and member settlement.
2. **`discogs-sql-loader`.** Replace `PostgreSQLBatchProcessor` lifecycle code with
   `AsyncBatchEngine`; retain normalization, `PostgreSQLBatchWriter`, hash/media outcome
   accounting, and the purge-protection DLQ latch in the service adapter; map Psycopg
   errors locally; keep batch/non-batch QoS and stale-row purge local. Batch mode uses
   the engine; non-batch mode uses `run_delivery`. Preserve the poison, give-up,
   cancellation, media-backfill, and purge-safety tests.
3. **`musicbrainz-graph-enricher`.** Keep one Neo4j transaction per delivery. Convert the
   handler body to return `DeliveryResult` and run it through `run_delivery`; map named
   Neo4j availability errors to transient and make the current generic-requeue default
   explicit. Keep JSON validation, local counters, transaction retry behavior,
   completion/cancellation state, size-one flush metrics, and fixed prefetch local.
   Contract tests must prove `DEFER` on shutdown, permanent invalid-ID rejection,
   throttled transient requeue, and exactly one terminal settlement.
4. **`musicbrainz-sql-loader`.** Keep one PostgreSQL transaction per delivery and retain
   `MusicBrainzRecordProcessor` and its private child-row batching. Convert the outer
   handler to `run_delivery`; map interface/operational/unavailable errors to transient
   and data/integrity errors to deterministic. Keep UUID validation, completion state,
   pool-coupled global QoS, record metrics, and child-row `BatchObserver` adapter local.
   Contract tests must prove shutdown deferral, permanent invalid/data rejection,
   throttled transient requeue, and exactly one terminal settlement.

Cross-hive dependency order:

```text
design GO decision
        |
        v
python-libraries API + contract tests + compatibility wrapper
        |
        +----------------+----------------+----------------+
        v                v                v                v
Discogs graph      Discogs SQL      MusicBrainz graph  MusicBrainz SQL
        +----------------+----------------+----------------+
                         |
                         v
organization validation, docs update, and Repowise reindex
```

The final integration bead must run the four owner-hive validation gates, update the
fix-one-fix-all guidance to name `common.delivery` and `common.batch`, verify immutable
runtime pins, and record refreshed defect scores after a Repowise reindex. The prior
standalone `gm-python-libraries-dg-7oi3-1` should be superseded only when this molecule is
filed, preserving its discovery notes as provenance.

## Recommendation

After review and merge of this spike, re-enter planning on `gm-design-erl` and file the
cross-hive implementation molecule exactly in the dependency order above. Do not create
implementation beads before the GO artifact is accepted. Treat any proposal to share
QoS, control-message state, serialization, catalog normalization, or database exception
types as a scope change requiring a new decision.

The success measure is not fewer files. It is one tested settlement policy for all four
consumers, one tested queue/poison/drain implementation for the two real batch
consumers, service-owned adapters with one-way dependencies, and no product behavior
change during migration.
