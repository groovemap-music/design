# ADR 0018: The operations console is one authenticated, data-driven shell

- Status: Accepted on 2026-10-24 (`gm-design-3qbr`, epic `gm-design-x0mf`)
- Pipeline visualization: pending the operations-console spike verdict

## Context

The operations console serves two pages. `/` is a live landing page with no
authentication. `/admin` is a separate page gated by `catalog-api` bearer tokens.
The landing page, its `/api/metrics`, `/api/services`, `/api/queues`,
`/api/databases` and `/api/queue-prefixes` routes, and its `/ws` WebSocket are
reachable by anyone who can reach the console port. They expose queue names,
datastore sizes, and service health.

Two further problems share this boundary:

- **Duplicated history store.** The Queue Trends and System Health tabs read
  `catalog-api` `/api/admin/queues/history` and `/api/admin/health/history`. Those
  routes are backed by the PostgreSQL tables `queue_metrics` and
  `service_health_metrics`, which `database-schema` owns and a collector samples
  every 300 seconds. The same signals already reach VictoriaMetrics through the
  OpenTelemetry collector, so the platform keeps two copies at different
  resolutions. VictoriaMetrics runs with `-retentionPeriod=15d`, while the tabs
  offer ranges up to 90 days, so the range selector would silently show half the
  window if history moved there unchanged.
- **Hand-written per-queue markup.** The landing page is about 1,000 lines of
  per-queue and per-entity element ids: service cards, a queue-size bar chart, and
  16 publish and acknowledge rate dials per pipeline. A new entity type or consumer
  needs hand edits to HTML and JavaScript. The dials do not show where a pipeline
  is stuck or when an extraction will finish.

ADR 0017 (broker metrics from `rabbitmq_prometheus`) changes where the
console reads live broker numbers. This decision covers who may see them, where
history comes from, and how the layout is produced.

## Options

| Option | Assessment |
| --- | --- |
| One authenticated shell at `/`, sessions owned by `catalog-api` | Adopted. One login, no public data, and no second credential store. |
| Keep the public landing page and trim what it shows | Rejected. Any retained queue, size, or health data is still exposure, and two pages keep two code paths and two auth models. |
| Console verifies JWTs itself | Rejected. It would copy the signing secret and revocation checks out of `catalog-api`, the owner of authentication. |
| Network-level restriction only | Rejected. It is outside the application's control and does not give per-operator identity. |
| Keep PostgreSQL history tables | Rejected. It keeps a second, coarser copy of data VictoriaMetrics already holds. |

## Decision

### One shell, one login

`/` serves the console shell. An unauthenticated visitor sees only the login form.
After login, the live Overview is the first tab, followed by the existing admin
tabs. `/admin` and `/admin.html` redirect to `/`.

### Auth boundary

`catalog-api` owns sessions. The console holds no JWT secret and validates a
bearer by calling a `catalog-api` route, `GET /api/admin/auth/session`, which sits
behind the existing admin dependency and returns the admin identity and expiry.
The console promotes that route through its producer contract. It may cache a
positive result for at most 30 seconds, keyed by a hash of the token, so a revoked
session stops working within that window.

Only `/health` stays public. Every data route and the WebSocket require a valid
admin session: HTTP routes answer 401, and the WebSocket closes with code 4401.

Browsers cannot set `Authorization` on a WebSocket. The shell first makes an
authenticated `POST /api/ws-ticket`, receives a single-use ticket valid for 30
seconds, and opens `/ws?ticket=...`. A reused or expired ticket is rejected, and
the ticket never appears in logs. Logout, token expiry mid-session, and
`catalog-api` being unreachable each return the user to the login form with a
visible reason.

### Data-driven layout

The Overview renders from an authenticated `/api/topology` plus live metrics. The
topology lists pipelines with their producer, per-entity queues, consumers, dead
letter queues, and target datastores. It derives from the pipeline configuration
and the promoted catalog-event contracts. Page markup carries no per-queue or
per-entity element ids, so adding an entity type or consumer changes data, not
HTML or JavaScript.

### History from VictoriaMetrics

Console backend routes query VictoriaMetrics `/api/v1/query_range`, with a step
chosen per range from one hour to 90 days:

- queue trends from the `rabbitmq_queue_*` series;
- service availability and response time from
  `groovemap_console_poll_duration_seconds`, labeled by target and outcome;
- endpoint latency from `http_server_request_duration_seconds`.

No PostgreSQL history reads remain in the console.

**Retention requirement.** VictoriaMetrics `-retentionPeriod` must be at least 90
days in every deployed environment before the console's history tabs read from it.
The 15-day setting does not meet the tabs' range. `deployment` owns the setting,
its disk sizing, and the observability documentation that states the reason.

### Retire the PostgreSQL metrics tables

`catalog-api` removes the queue and service-health history collector and the two
history routes. `database-schema` drops `queue_metrics` and
`service_health_metrics` after the console no longer reads them. The history data
is not migrated: it covers only the interval since collection began, at five-minute
resolution, and VictoriaMetrics holds the same signals. Operators lose that older
sampled history at cutover, which this record accepts.

### Pipeline visualization

Pending. The console's primary Overview visualization is chosen by the
operations-console spike from three candidates: a left-to-right flow diagram with
throughput, health, backlog, and drain estimate; an entity by consumer matrix of
backlog and lag; and per-extraction-run progress with percent loaded and
estimated completion. The spike's decision bead files a design-hive bead that
amends this section with the verdict. Until then, the shell and topology work do
not depend on the choice.

## Consequences

Anonymous access to pipeline, queue, and datastore information ends, at the cost
of one login for operators who used the landing page without one. The console
depends on `catalog-api` for every request that is not cached, and its login form
reports when `catalog-api` is unreachable. The 30-second cache bounds both load and
revocation delay. The layout no longer needs hand edits per entity, which lets the
topology feed any later view.

History depends on the metrics stack and on longer retention, which increases
VictoriaMetrics storage. The live Overview does not: it reads the broker directly
per ADR 0017. Removing the PostgreSQL copy deletes a collector, two routes, and two
tables, and discards the sampled history already stored.

Repositories affected:

- **`operations-console`** owns the shell, session validation, WebSocket ticket,
  `/api/topology`, and VictoriaMetrics history routes.
- **`catalog-api`** owns the session route and retires the history collector and
  routes.
- **`deployment`** owns VictoriaMetrics retention and its documentation.
- **`database-schema`** drops `queue_metrics` and `service_health_metrics`.

Those implementation molecules cite this record as their common rationale.
