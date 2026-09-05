# ADR 0008: VictoriaMetrics backend, distributed tracing, runtime metrics, and alerting

- Status: Accepted

## Context

ADR-0006 standardized push-based OpenTelemetry (OTEL) metrics, a collector owned by the
`deployment` repository, Prometheus as the storage backend, and Grafana dashboards as code.
Every service repository has since instrumented itself against that decision and the metric
catalog it references, so wave 1 of the program is in place across the organization.

Wave 1 left the program with metrics only, and with gaps that each repository would otherwise
close on its own. There is no distributed tracing, so a unit of work that crosses an HTTP API,
a RabbitMQ queue, a consumer, and a graph or relational store cannot be followed end to end;
the storage backend holds metrics only, so adding traces would mean standing up a second,
unrelated system next to it. Services report no runtime or process metrics, so a leak or a
saturated event loop is invisible until it shows up as latency. Neo4j Community edition ships
no Prometheus endpoint, so the graph store contributes nothing but client-side latency.
Nothing reports container or host resource usage. And there is no home for alert rules, so
every threshold lives in an operator's head.

Wave 2 closes those gaps in one decision. Sixteen repositories implement against the same
conventions in parallel, in Python and in Rust, so the transport, span naming, runtime metric
set, and alert home have to be recorded before the work starts, in the same public home as
ADR-0006.

## Decision

### Metrics and trace backend

VictoriaMetrics single-node replaces Prometheus as the metrics store, as a digest-pinned
`victoria-metrics` compose service with a fifteen-day retention period and a named data
volume. The collector keeps its `prometheusremotewrite` exporter and now targets
VictoriaMetrics' native remote-write endpoint, which needs no enabling flag;
`resource_to_telemetry_conversion` stays enabled, so the `service_name`, `service_namespace`,
and `deployment_environment_name` labels every dashboard already uses are unchanged. The
standalone Prometheus configuration file is deleted with the service.

The Grafana datasource stays a `prometheus`-type datasource named `Prometheus` with uid
`prometheus`, now pointed at VictoriaMetrics, which serves the Prometheus query API. Keeping
the type and the uid is deliberate: every existing dashboard and the `${DS_PROMETHEUS}` lint
rule keep working without an edit, and the third-party `victoriametrics-datasource` plugin is
not used, so the stack stays on core Grafana datasource types.

Traces are stored in VictoriaTraces single-node, a digest-pinned `victoria-traces` compose
service with a seven-day retention period and its own volume. Grafana reads it through a
`tempo`-type datasource named `Tempo` with uid `tempo`, pointed at the Tempo-compatible read
path VictoriaTraces exposes; dashboards reference it as `${DS_TEMPO}`. As with metrics, the
core datasource type means Grafana needs no plugin and dashboards port between this stack and
the operator's own.

In the production overlay both VictoriaMetrics and VictoriaTraces bind to loopback only,
exactly as Prometheus did, so neither store is reachable from outside the host. Grafana's
exposure is unchanged.

### Distributed tracing

Tracing is configured through standard OTEL environment variables only, the same contract
metrics already use: `OTEL_TRACES_EXPORTER`, `OTEL_TRACES_SAMPLER` (defaulting to
parent-based ratio sampling), and `OTEL_TRACES_SAMPLER_ARG`, which samples everything in the
development compose stack and a tenth of traces in the production overlay. Traces share
`OTEL_EXPORTER_OTLP_ENDPOINT` with metrics and are exported over OTLP/HTTP-protobuf through a
batch span processor. No GrooveMap-specific tracing variable is introduced. When tracing is
disabled the bootstrap installs a no-op tracer provider, and tracing never fails startup nor
raises into application code. One-shot processes flush and shut down the tracer provider on
exit, next to the meter provider, so the last spans land.

Context propagates as W3C TraceContext. Over HTTP it is carried by the FastAPI and HTTPX
instrumentors. Over RabbitMQ the producer span injects `traceparent` and `tracestate` into
the AMQP message headers and the consumer span extracts them, so a trace survives the queue
hop and a message can be followed from the extractor that published it to the store that
consumed it.

Span names are low-cardinality and drawn from a closed set, exactly as metric names are.
HTTP server and client spans come from the instrumentors and are route-templated. Database
spans are named for the operation and the system and carry those two attributes only, never a
statement. Messaging spans are named for the destination, with the consumer span a child of
the extracted context. Batch flushes are internal spans that link to at most sixty-four
member message spans rather than nesting under one of them. Extractors emit one internal root
span per file with download, parse, and publish children, and each remaining domain entry
point has its own named root span. Span attributes use the same closed sets as the metric
catalog: never an id, a file name, or free text. No span event carries a payload, and an
error sets the span status to ERROR with an error type and nothing else.

Span-derived metrics are produced by the collector's `spanmetrics` connector, never by a
service. Services emit spans; the call count and duration histogram derived from them are the
collector's output, so no service duplicates work the pipeline already does and the derived
series have one definition for the whole program.

### Runtime and process metrics

Python services install the OTEL system-metrics instrumentation from the shared telemetry
bootstrap, restricted to a process-scoped subset: process CPU time and utilization, resident
and virtual memory, thread count, open file descriptors, context switches, and the CPython
garbage-collection count instrument. Host-level metrics are deliberately excluded from
services, because node-exporter owns the host and duplicate host series from sixteen
containers would be both redundant and misleading. Because the exact Prometheus names depend
on the pinned instrumentor version, `python-libraries` records the names it actually observes
and `deployment` copies them into the catalog rather than either repository guessing. On top
of that subset, Python services record an event-loop lag histogram sampled once a second by a
background task started from the service's running loop, which is the one saturation signal
process metrics cannot show.

Rust services read process CPU time, resident memory, thread count, and open file descriptors
from `/proc/self` as observable instruments. That needs no new crate and is silently absent
off Linux, where the containers do not run. Three observable gauges for tokio worker count,
alive tasks, and global queue depth come from the runtime handle's stable metrics API and give
the Rust services the saturation signal the event-loop lag histogram gives the Python ones.
Neither set carries attributes.

### Neo4j metrics

Neo4j Community edition exposes no Prometheus endpoint, so there is nothing to scrape and no
exporter to run. Rather than adopt a third-party sidecar or require the enterprise edition,
the `operations-console` dashboard service emits the graph store's metrics itself, as
observable gauges refreshed at most once per export interval. Every backing query is bounded
to the count store or to a `SHOW` command, so collection cannot become an expensive scan: an
up gauge, node counts by label and relationship counts by type over the closed set
`database-schema` defines, the active transaction count, and store sizes read through the JMX
procedure when it answers, omitted rather than reported as zero when it does not. Query
latency needs no new instrument, because the client operation duration histogram from
ADR-0006 already carries it.

### Container and host metrics

cadvisor and node-exporter run as digest-pinned containers in both the development stack and
production, and the collector's Prometheus receiver scrapes them. That is the one place the
program scrapes rather than receives pushes, because neither exporter speaks OTLP and both
describe infrastructure rather than a service. Dashboards may use their container and host
series only once those series are enumerated in the dashboard lint gate's exporter allowlist.
The allowlist enumerates names and never prefix-matches, so third-party series are held to the
same catalog discipline as anything a service emits.

### Alerting

Alert rules are Grafana-managed and provisioned from a version-controlled file in the
`deployment` repository into a single folder and evaluation group, evaluated every minute.
They are code on the same terms as dashboards, and are never authored in the Grafana UI. No
contact point and no notification policy is provisioned: rules fire in Grafana's alert list
and nowhere else. That is intentional, because a routing destination is a per-operator, often
credential-bearing choice that a public repository must not carry. Every rule expression is
lint-gated against the metric catalog exactly as a dashboard panel is, so an alert cannot
depend on a series no service emits.

### Dashboards

Four dashboards join the five ADR-0006 established, which keep their uids unchanged:
`groovemap-runtime`, `groovemap-neo4j`, `groovemap-containers`, and `groovemap-traces`. One
per subject added by this decision, so a reader looking for runtime, graph-store, container,
or trace behavior has one place to look, and the existing dashboards do not grow a second
purpose.

## Relationship to ADR-0006

ADR-0006 remains Accepted and is amended, not replaced. This decision supersedes exactly one
paragraph of it: the `BACKEND (deployment repo)` paragraph in its appendix conventions block,
and within that paragraph only its first bullet, which names `prom/prometheus` started with
`--web.enable-remote-write-receiver` as the destination of the collector's remote write. That
destination is now VictoriaMetrics, and VictoriaTraces is added beside it for spans. The
second bullet of the same paragraph, which provisions Grafana from version-controlled
datasource, dashboard-provider, and dashboard JSON files and forbids editing dashboards in the
UI, is not superseded and continues to govern.

Everything else in ADR-0006 remains in force, unchanged and unqualified: the transport
decision, including OTLP/HTTP-protobuf push to the collector, standard OTEL environment
variables only, and the rule that no service exposes its own scrape endpoint for OTEL metrics;
the resource identity rules for `service.name` and `service.namespace`; the metric naming
decision, including semantic conventions first, the `groovemap.*` namespace second, and closed
low-cardinality attribute sets; dashboards as code and the catalog lint gate; and the
preserved contracts, meaning the Rust extractors' JSON `GET /metrics` endpoint governed by
ADR-0005 and `catalog-api`'s Postgres-backed metrics history. The appendix of ADR-0006 stays
the authoritative copy of the wave-1 conventions, with the single bullet named above read
through this record.

## Consequences

The program gets traces, runtime metrics, graph-store metrics, container and host metrics, and
alert rules from one decision instead of sixteen, and every repository implements against a
recorded convention rather than a local choice. Because the metrics datasource keeps its type
and uid, the backend swap is invisible to the dashboards and lint rules built for wave 1: no
existing dashboard is edited, and the migration cost lands almost entirely in the `deployment`
repository. VictoriaMetrics stores traces and metrics as one family of components, so the
stack gains tracing without gaining an unrelated second backend to operate.

The cost is a wider closed catalog. Span names, span attributes, runtime metric names, and now
alert expressions are all gated the same way metric names already were, so a repository must
publish a name before it can chart or alert on it. Traces are sampled at a tenth in
production, which means an individual request is usually not recoverable after the fact and
operators reach for the collector-derived span metrics for aggregate questions. Emitting Neo4j
gauges from `operations-console` places a monitoring responsibility inside a service, so that
repository carries a small amount of code that exists for the observability pipeline rather
than for the console.

Because the collector-derived span metrics are produced from sampled traces, their absolute
counts are sample counts and not request counts, and dashboards built on them read as rates
and ratios. Because no contact point is provisioned, alerts fire only where an operator is
looking at Grafana; wiring a destination is a deployment-time choice this decision leaves open
rather than a gap in it.

## Appendix: GrooveMap OTEL program wave-2 conventions

The following block is the durable, authoritative copy of the wave-2 conventions shared by
every molecule in the program, reproduced verbatim from the program epic. It extends, and does
not replace, the wave-1 block reproduced in the appendix of
[ADR 0006](0006-opentelemetry-metrics.md), which stays in force apart from the single bullet
identified above.

```
=== GrooveMap OTEL program — wave 2 conventions (2026-09). Extends the ADR-0006 block, which stays in force. ===

BACKEND (deployment repo)
- prom/prometheus is REPLACED by victoriametrics/victoria-metrics (single-node, digest pinned) as compose service
  `victoria-metrics`: port 8428, `-retentionPeriod=15d`, `-storageDataPath=/victoria-metrics-data`, volume
  `victoria_metrics_data`. The collector keeps its prometheusremotewrite exporter, now targeting
  http://victoria-metrics:8428/api/v1/write (VictoriaMetrics accepts remote write natively; no flag needed).
  resource_to_telemetry_conversion stays enabled so the service_name / service_namespace /
  deployment_environment_name labels every dashboard uses are unchanged. config/prometheus.yml is deleted.
- The Grafana datasource keeps `type: prometheus`, `uid: prometheus`, name `Prometheus`, url
  http://victoria-metrics:8428 (VictoriaMetrics serves the Prometheus query API). Every existing dashboard and
  the ${DS_PROMETHEUS} lint rule keep working unchanged. The victoriametrics-datasource plugin is NOT used.
- Traces: victoriametrics/victoria-traces (single-node, digest pinned, >= v0.9.4) as compose service
  `victoria-traces`: port 10428, `-retentionPeriod=7d`, volume `victoria_traces_data`. The collector gains a
  `traces` pipeline: otlp -> memory_limiter -> batch -> otlphttp/victoria_traces
  (traces_endpoint http://victoria-traces:10428/insert/opentelemetry/v1/traces). A `spanmetrics` connector on
  the traces pipeline feeds the metrics pipeline (histogram unit s, dimensions service.name, span.name,
  span.kind, status.code). Grafana datasource `type: tempo`, `uid: tempo`, name `Tempo`, url
  http://victoria-traces:10428/select/tempo. Dashboards reference it as ${DS_TEMPO}.
- Prod overlay: victoria-metrics (8428) and victoria-traces (10428) bind 127.0.0.1 only, exactly as prometheus
  did. Grafana is unchanged.
- New collector prometheus-receiver scrape jobs: cadvisor (gcr.io/cadvisor/cadvisor, :8080) and node-exporter
  (prom/node-exporter, :9100). Both digest pinned; both dev and prod.

TRACES (every service)
- Env-var-only contract, same as metrics: OTEL_TRACES_EXPORTER (otlp|none; unset with an endpoint set means
  otlp), OTEL_TRACES_SAMPLER (default parentbased_traceidratio), OTEL_TRACES_SAMPLER_ARG (compose dev 1.0,
  prod overlay 0.1). OTEL_EXPORTER_OTLP_ENDPOINT is shared with metrics; OTLP/HTTP-protobuf; BatchSpanProcessor.
  A no-op TracerProvider is installed when disabled. Tracing never fails startup or raises into application
  code. One-shot processes force_flush + shutdown the tracer provider on exit, next to the meter provider.
- W3C TraceContext propagation. Producer spans inject `traceparent` / `tracestate` into AMQP message headers;
  consumer spans extract them. HTTP propagation comes from the fastapi / httpx instrumentors.
- Span names are low-cardinality. HTTP server/client spans come from the instrumentors (route-templated).
  Database spans: `{db.operation.name} {db.system.name}`, kind CLIENT, attributes db.system.name and
  db.operation.name only (never a statement). Messaging: `publish {messaging.destination.name}` kind PRODUCER,
  `process {messaging.destination.name}` kind CONSUMER as a child of the extracted context, attributes
  messaging.system=rabbitmq, messaging.destination.name, messaging.operation.name. Batch flushes:
  `flush {store} {entity}` kind INTERNAL with span links to at most 64 member message spans.
  Extractors: one INTERNAL root span per file `extract {source} {entity}` with child spans `download`, `parse`,
  and one `publish {destination}` PRODUCER span per published batch.
  Domain root spans: `insights {computation}`, `mcp.tool {tool}`, `schema_init {store}`, `console.poll {target}`,
  `api.sync`. Span attributes use the same closed sets as the metric catalog; never ids, file names, or free
  text; no span events carrying payloads; errors set status ERROR with error.type only.
- Span metrics are produced by the collector's spanmetrics connector, never by services:
  traces.span.metrics.calls (counter) and traces.span.metrics.duration (histogram, s), Prometheus names
  traces_span_metrics_calls_total / traces_span_metrics_duration_seconds, labels service_name, span_name,
  span_kind, status_code.

RUNTIME METRICS
- Python: opentelemetry-instrumentation-system-metrics joins the `otel` extra. setup_telemetry() installs it
  with the PROCESS-scoped subset only: process.cpu.time, process.cpu.utilization, process.memory.usage,
  process.memory.virtual, process.thread.count, process.open_file_descriptor.count, process.context_switches,
  and the CPython gc count instrument, under whatever names the pinned instrumentor version emits. No system.*
  host metrics from services (node-exporter owns the host). python-libraries records the exact Prometheus names
  observed in docs/runtime.md; deployment copies them into the catalog.
  Event-loop lag: groovemap.runtime.event_loop.lag (histogram, s), sampled every 1 s by a background task
  started with common.telemetry.start_event_loop_monitor() from the service's running loop. No attributes.
- Rust: process.cpu.time {cpu.mode=user|system} (counter, s), process.memory.usage (RSS, By),
  process.thread.count, process.open_file_descriptor.count as observable instruments read from /proc/self
  (silently absent off Linux, no new crate required); groovemap.runtime.tokio.workers,
  groovemap.runtime.tokio.alive_tasks, groovemap.runtime.tokio.global_queue_depth (observable gauges) from
  tokio::runtime::Handle::metrics() stable API. No attributes.

NEO4J METRICS (emitted by operations-console `dashboard`; Neo4j Community has no Prometheus endpoint)
- Observable gauges refreshed at most once per export interval, every query bounded to the count store or a
  SHOW command: groovemap.neo4j.up (0|1); groovemap.neo4j.nodes {label} and groovemap.neo4j.relationships
  {type} for the closed label / relationship-type set that database-schema defines;
  groovemap.neo4j.transactions.active; groovemap.neo4j.store.size.bytes {store} from
  CALL dbms.queryJmx('org.neo4j:instance=kernel#0,name=Store sizes') when the procedure answers (omitted, never
  zero, when it does not). db.client.operation.duration already carries Neo4j latency.

CONTAINERS AND HOST
- cadvisor and node-exporter are scraped by the collector; dashboards may use container_* and node_* series
  once they are enumerated in the check-dashboards exporter allowlist (enumerated, never prefix-matched).

ALERTING
- Grafana-managed alert rules provisioned from config/grafana/provisioning/alerting/groovemap.yaml
  (folder GrooveMap, evaluation group groovemap, interval 1m). No contact point or notification policy is
  provisioned: rules fire in the Grafana alert list only. Every rule expression is lint-gated against the catalog
  exactly like a dashboard panel.

DASHBOARDS (new uids): groovemap-runtime, groovemap-neo4j, groovemap-containers, groovemap-traces.
The existing five stay and keep their uids.

ROLLOUT ORDER (cross-hive; not expressible as bead deps)
1. design (ADR-0008), python-libraries (tracing + runtime metrics), catalog-ingestion (Rust runtime metrics +
   tracing), deployment (backend conversion, exporters, alerting, dashboards) run in parallel.
2. After python-libraries merges, every Python service bumps its groovemap-runtime rev to that commit and adopts;
   discogs-ingestion and musicbrainz-ingestion port the catalog-ingestion telemetry module.
3. deployment end-to-end verification runs last.
```
