# Harness for spike gm-design-loj9

This is throwaway code for
[Identity history for concept D's ledger, without edition candidates](../gm-design-loj9-strata-ledger.md).
It is not a product package, and no GrooveMap service depends on it. The measurement is
plain SQL run read-only through `psql`. Python defines the same figures over in-memory rows,
builds the draft ledger payload, and tests both on an invented catalog. The committed
outputs in `results/` are aggregates (counts, months, days) and payloads built from the
invented catalog. They contain no catalog ids, user data, or audit rows.

## Files

| File | Role |
| --- | --- |
| `sql/probe.sql` | Which identity tables exist, and how many audit rows and identity audit rows there are. Runs on any PostgreSQL database |
| `sql/identity_history.sql` | The identity-history measurement: per-source volumes and monthly density, the transition counts, and the ledger shape (editions, works, events). Never reads `catalog_item_moves.user_id` or `row_id`, or `admin_audit_log.admin_id` or `target` |
| `sql/link_structure.sql` | The catalogs' own links, read from the provider-keyed tables only. It gives the ceiling of the cross-catalog history and shows where the work level splits |
| `sql/schema_subset.sql` | The tables `identity_history.sql` reads, copied from `database-schema` at `817081d`, for the parity test's scratch database only |
| `scripts/run_sql.sh` | Runs one SQL file inside a `REPEATABLE READ, READ ONLY` transaction with a statement timeout, and prints its JSON line |
| `scripts/measure.py` | Runs the probe, then `identity_history.sql` only if every table it needs exists (otherwise it records `DEFER`), then `link_structure.sql`. It refuses to write anything that looks like an id |
| `scripts/reference.py` | The same figures as `identity_history.sql`, in Python. The docstring defines instants, events, and alias classes |
| `scripts/payload.py` | Builds the draft `admin_identity_ledger_work` payload from history-only rows |
| `tests/synthetic.py`, `tests/fixtures/synthetic_catalog.json` | The invented catalog. It covers every identity path the code allows today, plus a variant with the writers that do not exist yet (promotion, revert, chain, move) |
| `tests/test_reference.py` | Every figure on the invented catalog |
| `tests/test_payload.py` | Payload states over transaction time, one-hop resolution, closed vocabularies, and no user data |
| `tests/test_privacy.py` | The id guard, and the check that committed results pass it |
| `tests/test_sql_parity.py` | `identity_history.sql` equals `reference.py` on both fixture variants, on a scratch PostgreSQL 18. Skipped unless `LEDGER_PARITY_PSQL` is set |
| `results/probe.json` | The probe of the one catalog database reachable on 2026-10-23 (UTC) |
| `results/identity_history.json` | `DEFER`, with the tables that database lacks |
| `results/link_structure.json` | The link structure of that database |
| `results/example_payload_work*.json` | The draft payload for one invented work, now and as of 2026-09-01 12:00 UTC |

## Reproducing

```bash
cd docs/spikes/gm-design-loj9
export UV_PROJECT_ENVIRONMENT=~/.cache/groovemap-spikes/gm-design-loj9/.venv
uv sync
uv run pytest                    # parity test skipped

# The parity test, on a throwaway local PostgreSQL 18 with trust auth (no password):
docker run -d --rm --name ledger-parity -e POSTGRES_HOST_AUTH_METHOD=trust postgres:18-alpine
LEDGER_PARITY_PSQL="docker exec -i ledger-parity psql -U postgres" uv run pytest tests/test_sql_parity.py
docker stop ledger-parity

# The example payloads:
(cd scripts && uv run python payload.py ../tests/fixtures/synthetic_catalog.json \
   00000000-0000-4000-8000-000000000101 > ../results/example_payload_work.json)
(cd scripts && uv run python payload.py ../tests/fixtures/synthetic_catalog.json \
   00000000-0000-4000-8000-000000000101 2026-09-01T12:00:00Z > ../results/example_payload_work_as_of.json)
```

### Measuring a catalog

`PSQL` is a psql invocation for a read-only role, without a database argument. `DATABASE`
names the database. The credentials come from the usual libpq sources (`~/.pgpass`,
`PGPASSWORD`), never from this repository. `LABEL` is committed, so it must not name a
host, user, or connection string.

```bash
PSQL='psql -h <host> -U <read-only role>' DATABASE=<catalog> \
  LABEL='GrooveMap catalog, <environment>' STATEMENT_TIMEOUT=30min \
  uv run python scripts/measure.py results/
```

The committed `results/probe.json`, `identity_history.json`, and `link_structure.json` came
from this command against the predecessor database (host, container, role, and database
names withheld). Two runs gave identical figures.

```bash
PSQL='ssh -o BatchMode=yes <host> docker exec -i <container> psql -U <role>' DATABASE=<database> \
  LABEL='predecessor catalog: both dumps loaded, no native identity' STATEMENT_TIMEOUT=20min \
  uv run python scripts/measure.py results/
```

A role with `pg_read_all_data`, or `SELECT` on the tables in `sql/schema_subset.sql` plus
`public.masters` and `musicbrainz.release_groups`, is enough. On 2026-10-23 (UTC) the only
reachable catalog was the predecessor system's database on the homelab. It is reached over
SSH with `docker exec -i <container> psql` and needs no password. `link_structure.sql` took
269 seconds there. `identity_history.sql` has not run against a real catalog, because none
has its tables yet. On a full GrooveMap catalog, expect it to take longer than
`link_structure.sql`. It makes one pass over `provider_aliases`, which is tens of millions of
rows, with a window over `native_id`.
