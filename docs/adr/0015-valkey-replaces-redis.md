# ADR 0015: Valkey replaces Redis

- Status: Accepted
- Transition amendment: Accepted on 2026-10-03 (`gm-design-eetv`, epic `gm-design-llt4`)

## Context

GrooveMap uses one Redis 8 instance for cache-aside JSON in `catalog-api` and
`analytics-engine`, and for security state: JWT revocation, password-change stamps,
two-factor challenges, password-reset tokens, Discogs OAuth state, and sync locks.
Losing a cache entry costs a recomputation. Losing a revocation entry can make a
revoked credential valid again. The two kinds of data cannot share an eviction
policy that treats every key as disposable.

Redis 8 offers RSALv2, SSPLv1, and AGPLv3 licensing choices. The dependency-license
policy cited in [ADR 0013](0013-pgvector-catalog-embeddings.md) excludes AGPL and
non-OSI terms, so none of these choices meets that policy. See the upstream
[Redis licenses](https://redis.io/legal/licenses/).

This decision retains the existing single-store boundary and command semantics.
It does not introduce a cluster or a second security-state service.

## Options

| Option | Assessment |
| --- | --- |
| Valkey | Adopted. BSD-3-Clause, governed under the Linux Foundation, and protocol-compatible with the commands GrooveMap uses, including conditional expiration. It preserves the existing service model. |
| Dragonfly | Rejected. Its BSL 1.1 terms do not meet the license policy. Its eviction model differs, and the throughput benefit does not justify a new engine at the existing 512 MB store size. |
| KeyDB | Rejected. Its Redis 6.x base lacks the `EXPIRE NX` operation used by `catalog-api`'s snapshot store. Low project activity adds maintenance risk without an advantage for this workload. |
| Stay on Redis 8 | Rejected. None of its three license choices satisfies the dependency-license policy. Keeping the engine would leave that conflict unresolved. |

The alternatives are evaluated for this workload, not ranked as general-purpose
datastores. The relevant upstream records are
[Valkey's project](https://valkey.io/),
[Dragonfly's license](https://github.com/dragonflydb/dragonfly/blob/main/LICENSE.md),
and [KeyDB's command reference](https://docs.keydb.dev/docs/commands/).

## Decision

### Adopt Valkey and valkey-py

Valkey replaces Redis in the shared deployment. Python consumers replace
`redis-py` with `valkey-py`, the Valkey project's fork of that client. Its matching
command API keeps the migration bounded to imports, client construction, and
names rather than rewriting every command call. Connections use `valkey://`
URLs, and the client uses the `libvalkey` response parser. See the upstream
[valkey-py client](https://github.com/valkey-io/valkey-py).

Credential-free tests use `fakeredis[valkey]` and `FakeAsyncValkey`; the fake
package's name is an upstream dependency name, not a GrooveMap-owned identifier.
See [fakeredis](https://github.com/cunla/fakeredis-py).

Keeping `redis-py` would preserve wire compatibility, but would retain the old
client identity throughout the application and instrumentation. `valkey-py`
provides the compatible API under the adopted project's ownership. Valkey GLIDE
is deferred: its different command API would require rewriting every call site
and the telemetry proxy, and it lacks the in-process fake needed by these tests.
Revisit GLIDE only when a demonstrated requirement warrants that cost and a
credential-free test strategy exists.

### Rename every GrooveMap-owned surface

The final rename is total: service and hostname, volume and secret names, `VALKEY_*`
environment variables, configuration fields, operator-facing strings, internal
identifiers and constants, instrumentation, and metric names all use Valkey.
Examples include replacing `REDIS_STATE_PREFIX`, `REDIS_SYSTEM`, and
`instrument_redis` with their Valkey equivalents. The OpenTelemetry
`db.system.name` value is `valkey`.

The existing third-party exporter is retained. The collector relabels its
`redis_*` metrics to `valkey_*`; dashboards, alerts, and other downstream
consumers use the latter names. After the bounded transition below, the only
permitted remaining operational `redis` references are:

- the third-party `oliver006/redis_exporter` image and its own `REDIS_*`
  configuration variables;
- the cutover script's source side, which must identify and read the old server.

Historical decision records and upstream dependency names such as `fakeredis`
remain accurate provenance; they do not permit old GrooveMap configuration
aliases or application identifiers outside the exact temporary exceptions below.
Stored key strings contain no `redis` and remain unchanged. Renaming a constant
must not rename its persisted key prefix.

### Bound the compatibility transition

The approved transition allows shared-library and operator-interface changes to
land before all consumers and deployment images have been promoted. It permits
exactly three temporary compatibility exceptions:

- The shared runtime may accept a deprecated `REDIS_*` environment setting only
  when its corresponding `VALKEY_*` setting is absent. Valkey settings take
  precedence; this is a fallback, not a second configuration surface to retain.
- The shared runtime may retain `_build_redis_url` solely for unmigrated consumers.
  Migrated consumers use the Valkey builder; the old helper is not a destination
  for new call sites.
- The operations console may read a legacy `data.redis` storage payload only when
  `data.valkey` is absent. Valkey payloads take precedence; the fallback does not
  permit Redis names in the operator-facing panel or its internal identifiers.

No other GrooveMap-owned Redis name is permitted by this exception. The final
total rename, unchanged persisted key prefixes, verified security-state cutover,
and `noeviction` requirements remain in force. These aliases do not authorize
attaching Redis persistence files to Valkey, skipping the writer pause, extending
security TTLs, or declaring the rollout complete.

The transition ends only after actual production consumer and deployment-image
promotions to Valkey are recorded and the following mandatory cleanup work is
separately tested, independently reviewed, merged, and pushed to each repository's
remote main:

- **`gm-python-libraries-4l6` — Remove transitional Redis URL and environment
  aliases after Valkey promotion** (epic `gm-python-libraries-o7f`): remove
  `_build_redis_url` and all `REDIS_*` settings fallbacks after all consumer and
  deployment promotions are recorded. Require Valkey-only and negative regression
  coverage, full validation, and downstream compatibility evidence.
- **`gm-operations-console-6cw` — Remove transitional Redis storage payload
  fallback after Valkey promotion** (epic `gm-operations-console-4ww`): remove
  `data.redis` fallback after the promoted catalog API emits `data.valkey`.
  Preserve the admin display and pass regression, browser, and full repository
  checks.

The migration program is complete only when both the original migration work and
these approved follow-on cleanups are complete, with actual remote-main pushes
verified. This amendment records the approved staging policy, not evidence that
any promotion or cleanup has already occurred.

### Preserve security state; let the cache start cold

The [upstream migration guide](https://valkey.io/topics/migration/) distinguishes
wire compatibility from persistence compatibility: Redis 7.4 and later data
files are incompatible with Valkey. Do not attach the Redis 8 RDB/AOF volume to
Valkey or treat a file copy as this cutover.

With application writers quiesced, copy these security and coordination prefixes
into the fresh Valkey store using `GET` and `PTTL`, preserving values and their
remaining TTL: `revoked:jti:`, `password_changed:`, `2fa_challenge:`, `reset:`,
`discogs:oauth:state:`, `sync:lock:`, and `sync:cooldown:`. Account for time elapsed
during copying, skip keys that have expired, and preserve a non-expiring key as
non-expiring. Do not extend a challenge, token, or lock's validity by restarting
its original TTL. Disposable cache entries are not copied; the cache starts cold.

The executable procedure, verification, and recovery steps belong to
[deployment's maintenance runbook](https://github.com/groovemap-music/deployment/blob/main/docs/maintenance.md),
not this record. Resume writers only after the security-state copy is verified
and consumers use the new store.

### Use noeviction

Replace `allkeys-lru` with `noeviction`. Memory pressure must never evict JWT
revocation or other security state. Expiration still removes keys at their TTL;
the policy prevents eviction before then. At capacity, writes can fail instead.
Consumers must handle that failure explicitly, and monitoring must expose memory
pressure and rejected writes rather than assuming that a successful read proves
new security state can be written.

## Consequences

GrooveMap keeps one protocol-compatible store and adopts an engine whose license
meets its dependency policy. Cache warming creates temporary extra load during
cutover. The copy and writer pause are necessary security work, not an optional
cache optimization. The total rename requires coordinated application, operator,
and telemetry changes with the bounded compatibility transition above; preserving
key strings avoids a second data migration. `noeviction` trades silent loss of
security state for visible write failure, making capacity monitoring and explicit
failure handling necessary.

Repositories affected:

- **`python-libraries`** owns the shared client, configuration, instrumentation,
  and fake-client support.
- **`catalog-api`** migrates cache and security-state call sites, constants, and
  tests while preserving their keys and TTL semantics.
- **`analytics-engine`** migrates its cache client and configuration.
- **`operations-console`** migrates operator-facing names and telemetry consumers.
- **`deployment`** owns the service, storage and secret names, eviction policy,
  exporter relabeling, and the maintenance runbook and cutover script.

Those implementation molecules cite this record as their common rationale.
