# ADR 0006: OpenTelemetry metrics and Grafana dashboards

- Status: Accepted

## Context

GrooveMap runs sixteen service repositories across Python and Rust, spanning HTTP APIs,
message-driven extractors and consumers, one-shot schema jobs, and operator-facing consoles.
Without a recorded decision, each repository would independently choose a metrics transport,
a naming scheme, and a home for dashboards, and the organization would end up with
incompatible exporters, colliding metric names, and dashboards that live in whichever repo
happened to draw them first. A shared decision is needed before any repository instruments
itself so that every service reports through one pipeline and against one metric catalog.

Two existing, unrelated metrics surfaces already exist and must not be disturbed by this
decision: the Rust extractors' `GET /metrics` JSON endpoint, which is part of the ADR-0005
HTTP contract that `operations-console` polls for health, and `catalog-api`'s
Postgres-backed metrics history, which serves historical query needs a push-based metrics
pipeline does not replace.

## Decision

### Transport

Every service pushes metrics over OTLP/HTTP-protobuf to a collector owned by the
`deployment` repository. No service exposes its own Prometheus scrape endpoint for OpenTelemetry
(OTEL) metrics. Configuration uses standard OTEL SDK environment variables only
(`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`,
`OTEL_METRICS_EXPORTER`, `OTEL_METRIC_EXPORT_INTERVAL`); no GrooveMap-specific telemetry
environment variables are introduced. Telemetry is additive and must never fail startup,
block application logic, or raise into application code.

### Resource identity

`service.name` is set to the service's docker-compose service key (for example `api`,
`extractor-discogs`, `graphinator`, `dashboard`). `service.namespace` is `groovemap` for
every service, so every metric series is attributable to the program regardless of which
repository or language produced it.

### Metric naming

Instrumentation follows OTEL semantic conventions first: HTTP server and client request
duration, database client operation duration, and messaging client metrics are emitted under
their standard OTEL names and attribute sets wherever the corresponding conventions exist.
Metrics with no applicable semantic convention are emitted second, under the `groovemap.*`
namespace, using the closed catalog of names and attribute sets defined in the program
conventions reproduced in the appendix below. Attribute sets are closed: a service emits only
the attributes listed for a given metric, and attribute values are always low-cardinality
(never an id, a file name, or free text).

### Dashboards

Grafana dashboards are defined as code in the `deployment` repository and provisioned from
version-controlled datasource, dashboard-provider, and dashboard JSON files. Dashboards are
never edited directly in the Grafana UI. A lint gate rejects a dashboard that references a
metric or attribute outside the canonical catalog, so a dashboard cannot silently depend on
an unpublished or renamed series.

### Preserved contracts

This decision does not change the Rust extractors' existing JSON `GET /metrics` endpoint;
that contract remains governed by ADR-0005 and continues to serve
`operations-console`'s health polling unchanged. `catalog-api`'s Postgres-backed metrics
history is likewise retained as-is: it answers historical and query use cases the push-based
OTEL pipeline does not address, and this decision neither replaces nor duplicates it.

## Consequences

Every service in the program reports through one push-based pipeline and against one metric
catalog, so dashboards, alerts, and cross-service correlation can be built once instead of
sixteen times. New metrics must be added to the canonical catalog before a dashboard can use
them, which adds a small amount of process overhead in exchange for dashboards that never
drift out of sync with what services actually emit. Because the two pre-existing metrics
surfaces are explicitly out of scope, operators keep their current health-check and
historical-query workflows unchanged while the new OTEL pipeline is adopted alongside them.

## Appendix: GrooveMap OpenTelemetry metrics conventions

The following block is the durable, authoritative copy of the conventions shared by every
molecule in the OTEL-metrics program, reproduced verbatim from the program epic.

```
=== GrooveMap OpenTelemetry metrics conventions (shared by every molecule in the OTEL-metrics program) ===

TRANSPORT
- Every service PUSHES metrics over OTLP/HTTP-protobuf to the collector: OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318.
  HTTP/protobuf, not gRPC: no grpcio/tonic native dependency, works for one-shot jobs and stdio processes.
- No service exposes a Prometheus /metrics scrape endpoint for its own OTEL metrics. (Existing JSON /metrics on the Rust
  extractors stays as-is: it is part of the ADR-0005 HTTP contract and operations-console reads it.)
- Standard env vars only, read by the SDK: OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME, OTEL_RESOURCE_ATTRIBUTES,
  OTEL_METRICS_EXPORTER (otlp|none), OTEL_METRIC_EXPORT_INTERVAL (default 15000 ms). No GrooveMap-specific telemetry env vars.
- When OTEL_EXPORTER_OTLP_ENDPOINT is unset or OTEL_METRICS_EXPORTER=none the bootstrap installs a no-op MeterProvider.
  Telemetry must NEVER fail startup, block the event loop, or raise into application code; exporter errors are logged once at WARNING.
- Cumulative temporality (Prometheus-compatible). Explicit-bucket histograms in seconds.
- One-shot processes (database-schema, CLIs) must force_flush + shutdown the provider on exit so the last export lands.

RESOURCE ATTRIBUTES
- service.name = the docker-compose service key (api, extractor-discogs, extractor-musicbrainz, graphinator, brainzgraphinator,
  tableinator, brainztableinator, dashboard, explore, insights, schema-init, mcp-server). Set via OTEL_SERVICE_NAME in compose;
  the code default is the package's canonical name.
- service.namespace=groovemap and deployment.environment.name=<dev|prod> via OTEL_RESOURCE_ATTRIBUTES in compose.
- service.version = the package version (importlib.metadata / CARGO_PKG_VERSION) set by the bootstrap.

METRIC NAMING (OTEL dot-names; Prometheus sees dots as underscores plus unit suffixes, e.g. groovemap.pipeline.messages ->
groovemap_pipeline_messages_total, http.server.request.duration -> http_server_request_duration_seconds_bucket)
- Use OTEL semantic conventions wherever one exists:
  http.server.request.duration {http.request.method, http.route, http.response.status_code}
  http.client.request.duration {http.request.method, server.address, http.response.status_code}
  db.client.operation.duration {db.system.name=postgresql|neo4j|redis, db.operation.name, error.type?}
  messaging.client.consumed.messages / messaging.client.sent.messages / messaging.client.operation.duration
    {messaging.system=rabbitmq, messaging.destination.name, messaging.operation.name, error.type?}
- Domain metrics live under groovemap.* and are shared across services with the same shape (attribute sets are closed):
  groovemap.pipeline.messages (counter) {source=discogs|musicbrainz, entity, outcome=processed|skipped|failed}
  groovemap.pipeline.message.duration (histogram, s) {source, entity}
  groovemap.pipeline.batch.size (histogram, {items}) {store=neo4j|postgresql, entity}
  groovemap.pipeline.batch.flush.duration (histogram, s) {store, entity, outcome}
  groovemap.pipeline.consumers.active (up-down counter) {source}
  groovemap.pipeline.reconnects (counter) {system=rabbitmq|neo4j|postgresql|redis}
  groovemap.pipeline.circuit_breaker.state (gauge; 0 closed, 1 half-open, 2 open) {system}
  groovemap.extraction.records (counter) {source, entity}
  groovemap.extraction.files (counter) {source, outcome=completed|skipped|failed}
  groovemap.extraction.file.progress (gauge, ratio 0..1) {source, entity}
  groovemap.extraction.download.bytes (counter, By) {source}
  groovemap.extraction.publish.confirm.duration (histogram, s) {source}
  groovemap.extraction.errors (counter) {source, stage=download|parse|publish}
  groovemap.api.sync.duration (histogram, s) {outcome}; groovemap.api.cache (counter) {outcome=hit|miss, cache}
  groovemap.api.nlq.requests (counter) {outcome}
  groovemap.insights.computation.duration (histogram, s) {computation, outcome}; groovemap.insights.last_success (gauge, unix s) {computation}
  groovemap.schema_init.duration (histogram, s) {store, outcome}
  groovemap.console.websocket.connections (up-down counter); groovemap.console.poll.duration (histogram, s) {target, outcome}
  groovemap.mcp.tool.calls (counter) {tool, outcome}; groovemap.mcp.tool.duration (histogram, s) {tool}
- Attribute values are low-cardinality only. Never put ids, file names, or free text in attributes.
- The canonical metric catalog is deployment/docs/observability.md; dashboards may only reference metrics in that catalog.

BACKEND (deployment repo)
- otel-collector (otel/opentelemetry-collector-contrib, digest pinned) receives OTLP, scrapes infra exporters via its prometheus
  receiver, and remote-writes to prometheus (prom/prometheus, digest pinned, --web.enable-remote-write-receiver).
- grafana (grafana/grafana, digest pinned) is provisioned from deployment/config/grafana/ (datasource + dashboard provider +
  dashboard JSON). Dashboards are code; they are never edited in the Grafana UI.

ROLLOUT ORDER (cross-hive; not expressible as bead deps)
1. python-libraries (common.telemetry) and deployment (collector/prometheus/grafana + env wiring) and design (ADR) and
   catalog-ingestion (Rust telemetry module) run in parallel.
2. After python-libraries merges, every Python service bumps its groovemap-runtime rev to that commit and adopts common.telemetry.
   discogs-ingestion and musicbrainz-ingestion port the catalog-ingestion module.
3. deployment dashboards + end-to-end verification run last against released images.
```
