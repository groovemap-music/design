#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Read-only cost evidence from the predecessor deployment's PostgreSQL (an earlier
# version of GrooveMap's schema; maintainer-authorized, read-only). Aggregates only:
# the duration of every logged insights computation, and the size of the stored
# genre-trends snapshot. Each statement runs in a read-only transaction with a timeout.
# Usage: PRED_HOST=<host> PRED_CONTAINER=<container> PRED_USER=<user> PRED_DB=<db> \
#        predecessor_costs.sh > results/predecessor_costs.json
#   or   predecessor_costs.sh --genre-trends > $W/data/predecessor_genre_trends.csv
#        (genre x decade counts for crosscheck_predecessor.py; kept in the cache)
set -euo pipefail
: "${PRED_HOST:?}" "${PRED_CONTAINER:?}" "${PRED_USER:?}" "${PRED_DB:?}"
if [[ ${1:-} == --genre-trends ]]; then
  cat <<'SQL' | ssh -o BatchMode=yes "$PRED_HOST" "docker exec -i $PRED_CONTAINER psql -U $PRED_USER -d $PRED_DB --csv -t -v ON_ERROR_STOP=1 -q"
begin transaction read only;
set statement_timeout = 60000;
select genre, decade, release_count, computed_at::date from insights.genre_trends order by 1, 2;
commit;
SQL
  exit 0
fi
cat <<'SQL' | ssh -o BatchMode=yes "$PRED_HOST" "docker exec -i $PRED_CONTAINER psql -U $PRED_USER -d $PRED_DB -At -v ON_ERROR_STOP=1 -q"
begin transaction read only;
set statement_timeout = 60000;
select json_build_object(
  'computations', (
    select json_object_agg(insight_type, stats) from (
      select insight_type, json_build_object(
        'completed', count(*) filter (where status = 'completed'),
        'failed', count(*) filter (where status = 'failed'),
        'first_day', min(started_at)::date, 'last_day', max(started_at)::date,
        'p50_s', round((percentile_cont(0.5) within group (order by duration_ms) filter (where status = 'completed') / 1000.0)::numeric, 1),
        'p90_s', round((percentile_cont(0.9) within group (order by duration_ms) filter (where status = 'completed') / 1000.0)::numeric, 1),
        'max_s', round((max(duration_ms) filter (where status = 'completed') / 1000.0)::numeric, 1)
      ) as stats
      from insights.computation_log group by insight_type
    ) t),
  'genre_trends_rows', (select count(*) from insights.genre_trends),
  'releases_est_rows', (select reltuples::bigint from pg_class where oid = 'public.releases'::regclass),
  'masters_est_rows', (select reltuples::bigint from pg_class where oid = 'public.masters'::regclass)
);
commit;
SQL
