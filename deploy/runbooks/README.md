# Eduvia pilot runbooks (PILOT-04)

Status: draft for the pilot staging stack (`compose.staging.yaml`, project `eduvia-staging`). Nothing here has been exercised against a live incident yet; every runbook has an **alert drill** section that must be run and recorded (date, operator, outcome) before the pilot go/no-go (`deploy/CHECKLIST-release.md`).

| Runbook | Alert check(s) in `deploy/alerts/queries.sql` |
|---|---|
| [queue-lag.md](queue-lag.md) | `queue_lag_seconds` (> 300 s), `failed_jobs_last_hour` (> 0) |
| [scoring-failures.md](scoring-failures.md) | `attempts_in_progress_past_deadline` (> 0), `grading_pending_over_10_minutes` (> 0), `failed_jobs_last_hour` for `attempt.grade` |
| [quota-and-provider-cost.md](quota-and-provider-cost.md) | `quota_exhausted_workspaces` (> 0) |
| [auth-incidents.md](auth-incidents.md) | none automated yet (log-based, see runbook) |
| [restore-drill.md](restore-drill.md) | none (scheduled drill; backup freshness is not monitored yet) |

Paging: on-call owner `—`, escalation `—`, product/school contact `—`. These must be named before the pilot (IMPLEMENTATION_PLAN section 3.5).

## Known gaps that change how these runbooks behave

1. **No Celery beat on staging.** `compose.staging.yaml` runs `celery worker` without `--beat` and has no beat service, so `app.tasks.jobs.sweep` (overdue-job re-dispatch, deadline expiry, `after_close` releases) never runs there. Until fixed, `queue_lag_seconds` and `attempts_in_progress_past_deadline` will breach as soon as a broker message is lost or a timed attempt passes its deadline. Development `compose.yaml` does run `--beat`.
2. **Staging API/worker do not boot with the current tree** unless `EMBEDDING_PROVIDER` (and `EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY`) are passed to the containers: production settings refuse the `local` embedder. The compose file does not pass these variables yet.
3. **No dashboards and no alert transport.** `deploy/alerts/check.py` prints and exits non-zero; wire it to cron + a notifier (or a monitoring agent) before relying on it.
4. **No monitoring role.** All `edu` tables use FORCE RLS; the runtime role sees nothing outside a request context. Checks run as the database administrator over the internal network (below). Recommended follow-up (not created):

   ```sql
   CREATE ROLE eduvia_monitor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS PASSWORD '...';
   GRANT CONNECT ON DATABASE eduvia TO eduvia_monitor;
   GRANT USAGE ON SCHEMA edu TO eduvia_monitor;
   GRANT SELECT ON edu.background_jobs, edu.usage_events, edu.workspace_quotas,
     edu.quiz_attempts, edu.grades TO eduvia_monitor;
   ```

   BYPASSRLS on a read-only role is still a cross-tenant read capability: restrict it to these tables, keep its credential out of the application env, and review it as part of PILOT-02.

## Common helpers (run on the staging host)

```bash
# Container of a compose service in the staging project (no compose file needed).
svc() { docker ps --filter label=com.docker.compose.project=eduvia-staging \
  --filter "label=com.docker.compose.service=$1" --format '{{.Names}}' | head -n1; }

# Administrator psql inside the db container (bypasses RLS: read-only queries only).
psql_admin() { docker exec -i "$(svc db)" psql -U postgres -d eduvia -v ON_ERROR_STOP=1 "$@"; }

# Celery inspection from inside the worker container.
celery_cmd() { docker exec -i "$(svc worker)" celery -A app.worker:celery_app "$@"; }

# Redis broker (db 1) and worker Redis (db 0); password read inside the container.
redis_broker() { docker exec -i "$(svc redis)" sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli -n 1 "$@"' sh "$@"; }
```

Run the alert checks as the administrator, from inside the API container (it is on the `data` network and has Python + psycopg). The URL is written to a mode-600 temporary env file, never placed on a command line or printed:

```bash
ENV_FILE=/home/nnh/eduvia-staging/shared/staging.env
REPO=/home/nnh/eduvia-staging/releases/$(cat /home/nnh/eduvia-staging/shared/current-release)
tmp=$(mktemp) && chmod 600 "$tmp"
python3 - "$ENV_FILE" > "$tmp" <<'PY'
import sys
values = {}
for line in open(sys.argv[1], encoding="utf-8"):
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.rstrip("\n").split("=", 1)
        values[key.strip()] = value.strip().strip("'")
print(f"DATABASE_URL=postgresql://postgres:{values['POSTGRES_PASSWORD']}@db:5432/eduvia")
PY
docker cp "$REPO/deploy/alerts/check.py" "$(svc api)":/tmp/check.py
docker cp "$REPO/deploy/alerts/queries.sql" "$(svc api)":/tmp/queries.sql
docker exec --env-file "$tmp" "$(svc api)" python /tmp/check.py --queries /tmp/queries.sql; status=$?
rm -f "$tmp"; echo "exit=$status"   # 0 ok, 1 breach, 2 error
```

Schedule it every 5 minutes (cron/systemd timer) and alert on any non-zero exit. A breach of `failed_jobs_last_hour` stays red for up to an hour after the failure; acknowledge it in the incident log rather than raising the threshold.

## Conventions

- Prefer read-only diagnosis first. Every SQL in these runbooks is `SELECT` unless the step says **WRITE** and names who must approve it.
- Never paste student names, answers or emails into chat/issue trackers. Use attempt/job UUIDs.
- Never `docker compose down -v`, drop volumes, or downgrade migrations. Schema is forward-only; recovery is restore (see [restore-drill.md](restore-drill.md)) or a forward fix.
- Record every incident and drill: start/end time (UTC), alert, impact, actions, follow-ups.
