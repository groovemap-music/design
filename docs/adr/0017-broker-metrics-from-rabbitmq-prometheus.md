# ADR 0017: Broker metrics come from rabbitmq_prometheus

- Status: Accepted

## Context

`deployment` starts RabbitMQ with `-rabbitmq_management disable_management_stats false`.
The override exists only so that `operations-console`, `catalog-api`'s history
collector, and `operations-toolkit` can read `message_stats` from
`GET :15672/api/queues`. Without it the broker's management metrics collector is
off and that payload is empty.

The collector is the `management_metrics_collection` deprecated feature. RabbitMQ's
4.0 deprecation announcements retire metrics delivery through the management API
and name the Prometheus plugin as its replacement. See the upstream
[deprecated features list](https://www.rabbitmq.com/docs/deprecated-features) and
[Prometheus guide](https://www.rabbitmq.com/docs/prometheus). GrooveMap therefore
forces on a feature the broker is removing, to feed consumers that have a supported
alternative.

That alternative already runs. The broker exposes `rabbitmq_prometheus` on `:15692`,
and `otel-collector` scrapes it into VictoriaMetrics under
[ADR 0008](0008-victoriametrics-tracing-runtime-alerting.md). Dashboards and alerts
already read the `rabbitmq_*` series there.

This decision changes where queue statistics are read. It does not change queue
topology, the dead-letter policy, or the management plugin's presence.

## Options

| Option | Assessment |
| --- | --- |
| Read `GET :15692/metrics/detailed` directly | Adopted. It is the supported source, needs no management stats, returns per-queue values from the broker at request time, and does not depend on the metrics stack. |
| VictoriaMetrics PromQL as the console's live source | Rejected for live views. Scrape granularity is 15 s, and the console would go blind whenever the metrics stack is down. It remains the source for history and alerts. |
| AMQP passive declare | Rejected. It returns only message and consumer counts, with no unacked count and no publish or ack rates. |
| `management.enable_queue_totals` | Rejected. It is still the deprecated management API and does not provide the per-queue rates the consumers need. |
| Keep `disable_management_stats false` | Rejected. It holds the deployment on a feature the broker is retiring, and the next upgrade that removes it breaks every consumer at once. |

## Decision

### Turn management metrics collection off

Set `management_agent.disable_metrics_collector = true` and remove the
`disable_management_stats` override. The `management_metrics_collection` feature is
no longer in use, so the broker can drop it without affecting GrooveMap.

### Read queue statistics from /metrics/detailed

Applications request `GET :15692/metrics/detailed` with the `family` query
parameter naming exactly the families below, and filter the result to the contract
queue prefixes. Rates are computed from counter deltas between samples, not read
from the broker.

| Family | Metric | Replaces |
| --- | --- | --- |
| `queue_coarse_metrics` | `rabbitmq_detailed_queue_messages` | `messages` |
| `queue_coarse_metrics` | `rabbitmq_detailed_queue_messages_ready` | `messages_ready` |
| `queue_coarse_metrics` | `rabbitmq_detailed_queue_messages_unacked` | `messages_unacknowledged` |
| `queue_consumer_count` | `rabbitmq_detailed_queue_consumers` | `consumers` |
| `queue_delivery_metrics` | `rabbitmq_detailed_queue_messages_acked_total` | `message_stats.ack` |
| `queue_exchange_metrics` | `rabbitmq_detailed_queue_exchange_messages_published_total` | `message_stats.publish` |

A counter reset, such as a broker restart, yields a negative delta. Consumers treat
it as a reset and skip that interval's rate rather than reporting a negative value.
Dashboards and alerts keep reading the `rabbitmq_*` series in VictoriaMetrics.

### Keep the management plugin for the UI and control calls

The management plugin stays enabled for the operator UI and control-plane calls.
`catalog-api`'s dead-letter purge, `DELETE /api/queues/%2F/{queue}/contents` in
`api/routers/admin.py`, does not depend on stats and is unchanged.

### Consumers that move

- **`operations-console`**: the live view, `dashboard/dashboard.py` `get_queue_info`.
- **`catalog-api`**: the history collector, `api/metrics_collector.py`
  `collect_queue_metrics`.
- **`operations-toolkit`**: the `check_queues`, `monitor_queues`, and
  `system_monitor` utilities.

### Order of rollout

`deployment` flips the broker last. Consumers ship first and read the detailed
endpoint while stats are still enabled, so each can be verified against both
sources. The broker setting changes only after every consumer is promoted. Flipping
it earlier would leave unmigrated consumers reading empty `message_stats`.

## Consequences

GrooveMap stops depending on a deprecated broker feature and reads queue data
from the source the broker documents as its replacement. The broker no longer
spends work on management stats. Rates become the consumer's responsibility, so
each consumer needs counter-delta and reset handling, and its first sample after
start has no rate. The console's live view depends on the broker's `:15692`
endpoint, not on the metrics stack. Metric names change from management JSON
fields to `rabbitmq_detailed_queue_*` names, so any consumer parsing the old
payload must be found and moved before the flip.

Repositories affected:

- **`operations-console`** moves its live queue view.
- **`catalog-api`** moves the history collector and keeps the DLQ purge.
- **`operations-toolkit`** moves its three CLIs.
- **`deployment`** sets `management_agent.disable_metrics_collector`, removes the
  stats override, and flips last.

Those implementation molecules cite this record as their common rationale.
