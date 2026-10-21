#!/usr/bin/env bash
# Runs the DB-05 RLS smoke test against the live staging database container.
# The SQL is transaction-scoped and rolls back, so nothing persists.
set -Eeuo pipefail
root=${EDUVIA_ROOT:-$HOME/eduvia-staging}
sql=$root/validation/deploy/test/rls-smoke.sql
[[ -f $sql ]] || { echo "Missing $sql" >&2; exit 2; }
container=$(docker ps --filter label=com.docker.compose.project=eduvia-staging --filter label=com.docker.compose.service=db --format '{{.Names}}')
[[ -n $container ]] || { echo 'Staging db container not running' >&2; exit 2; }
exec docker exec -i "$container" psql -U postgres -d eduvia -v ON_ERROR_STOP=1 -f - < "$sql"
