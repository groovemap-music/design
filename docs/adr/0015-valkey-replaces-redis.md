# ADR 0015: Valkey replaces Redis

- Status: Accepted

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

The rename is total: service and hostname, volume and secret names, `VALKEY_*`
environment variables, configuration fields, operator-facing strings, internal
identifiers and constants, instrumentation, and metric names all use Valkey.
Examples include replacing `REDIS_STATE_PREFIX`, `REDIS_SYSTEM`, and
`instrument_redis` with their Valkey equivalents. The OpenTelemetry
`db.system.name` value is `valkey`.

The existing third-party exporter is retained. The collector relabels its
`redis_*` metrics to `valkey_*`; dashboards, alerts, and other downstream
consumers use the latter names. The only permitted remaining operational
`redis` references are:

- the third-party `oliver006/redis_exporter` image and its own `REDIS_*`
  configuration variables;
- the cutover script's source side, which must identify and read the old server.

Historical decision records and upstream dependency names such as `fakeredis`
remain accurate provenance; they do not permit old GrooveMap configuration
aliases or application identifiers. Stored key strings contain no `redis` and
remain unchanged. Renaming a constant must not rename its persisted key prefix.

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
cache optimization. The total rename requires application, operator, and
telemetry changes to move together; preserving key strings avoids a second data
migration. `noeviction` trades silent loss of security state for visible write
failure, making capacity monitoring and explicit failure handling necessary.

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
