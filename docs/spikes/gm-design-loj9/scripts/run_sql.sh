#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Run one sql/*.sql file read-only and print its single JSON line.
#
# PSQL is the psql invocation to use, without a database argument when DATABASE is set, for
# example `psql -h <host> -U <read-only role>` or `ssh <host> docker exec -i <container> psql
# -U <role>`. Connection secrets come from the usual libpq sources (~/.pgpass, PGPASSWORD),
# never from this repository. The statement runs inside a REPEATABLE READ, READ ONLY
# transaction, so the server rejects any write, and under STATEMENT_TIMEOUT (default 30min).
set -euo pipefail

sql_file="$1"
: "${PSQL:?set PSQL to a psql invocation}"
timeout="${STATEMENT_TIMEOUT:-30min}"

# shellcheck disable=SC2086 # PSQL is a command line by design
{
  echo "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY;"
  echo "SET LOCAL statement_timeout = '${timeout}';"
  cat "$sql_file"
  echo "COMMIT;"
} | $PSQL -X -q -A -t -v ON_ERROR_STOP=1 ${DATABASE:+-d "$DATABASE"} | sed '/^$/d' | tail -n 1
