# Runbook: job queue lag and failed jobs

Alerts: `queue_lag_seconds` > 300, `failed_jobs_last_hour` > 0 (`deploy/alerts/queries.sql`).
Page: `—` (on-call), escalate to `—` after 30 minutes without mitigation.

## How jobs move

`edu.background_jobs` is the source of truth; Celery messages carry only the job id. The API inserts a `queued` row, commits, then sends `app.tasks.jobs.run` to a queue chosen by kind (`backend/app/services/jobs.py` `QUEUE_BY_KIND`):

| Kind | Queue | Failure handler |
|---|---|---|
| `document.ingest`, `document.reingest`, `document.delete`, `document.embed` | `ingestion` | quarantine / record failure |
| `content.generate`, `questions.generate` | `generation` | `generation.mark_failed` |
| `export.render` | `export` | `exports.mark_failed` |
| `attempt.grade` | `default` | see [scoring-failures.md](scoring-failures.md) |

A worker claims the row with a 5-minute lease (`running`), retries transient errors up to `max_attempts` (3) and marks permanent errors `failed` with an `error_code`. The beat task `app.tasks.jobs.sweep` (every 60 s) re-dispatches `queued` jobs untouched for 10 minutes and re-queues/fails `running` jobs whose lease expired. **Staging currently has no beat process** (see README), so a lost message is never re-dispatched there.

## Symptoms

- Teachers see uploads stuck at "Đang xử lý", AI drafts or exports never finishing; job chips stay `queued`.
- `queue_lag_seconds` grows steadily; `failed_jobs_last_hour` > 0.
- Worker container unhealthy (`celery inspect ping` failing) or restarting.

## Diagnose

1. Shape of the backlog (administrator, read-only):

   ```sql
   SELECT kind, status, count(*), min(created_at) AS oldest, max(attempt) AS max_attempt
   FROM edu.background_jobs
   WHERE status IN ('queued','running') OR finished_at > now() - interval '1 hour'
   GROUP BY kind, status ORDER BY kind, status;

   -- running jobs whose lease already expired (sweeper should have handled them)
   SELECT id, kind, attempt, lease_expires_at FROM edu.background_jobs
   WHERE status = 'running' AND lease_expires_at < now() ORDER BY lease_expires_at LIMIT 20;

   -- failures in the last hour by code
   SELECT kind, error_code, count(*) FROM edu.background_jobs
   WHERE status = 'failed' AND finished_at > now() - interval '1 hour'
   GROUP BY kind, error_code ORDER BY count(*) DESC;
   ```

2. Worker and broker:

   ```bash
   docker ps --filter label=com.docker.compose.project=eduvia-staging --format '{{.Names}}\t{{.Status}}'
   celery_cmd inspect ping --timeout 5
   celery_cmd inspect active --timeout 5        # tasks currently executing
   celery_cmd inspect reserved --timeout 5      # prefetched, not started
   celery_cmd inspect active_queues --timeout 5 # must list default, ingestion, generation, export, omr
   for q in default ingestion generation export; do printf '%s ' "$q"; redis_broker llen "$q"; done
   docker logs --since 30m "$(svc worker)" 2>&1 | grep -E 'job_|ERROR|WorkerLostError|SoftTimeLimit' | tail -50
   ```

   Logs are structured JSON and never contain prompts, source text or student data; do not add them while debugging.

3. Classify:

   | Observation | Likely cause | Go to |
   |---|---|---|
   | Broker list length > 0, `inspect active` empty | Worker down / not consuming that queue | Mitigation A |
   | Broker list length 0, DB rows `queued` | Message lost (Redis restart, dispatch failure) and no sweeper | Mitigation B |
   | Rows `running` with expired lease | Worker killed mid-job; sweeper not running | Mitigation B |
   | `failed` with `provider_unavailable` / `provider_rate_limited` | LLM/embedding outage | [quota-and-provider-cost.md](quota-and-provider-cost.md) |
   | `failed` with `quota_exceeded` | Workspace cap reached | [quota-and-provider-cost.md](quota-and-provider-cost.md) |
   | `failed` with `max_attempts_exceeded` / `lease_expired` | Repeated crash or time limit (parser 30 s, task hard limit 360 s) | Mitigation C |
   | `failed` with `object_missing`, `malformed_document`, `archive_too_large`, `empty_document`, `no_text_layer`, `too_many_pages`, `document_too_long`, `encrypted_document` | Bad input (expected, per document) | Inform teacher; no action |
   | `failed` with `pdf_parser_unavailable` on every PDF | `pypdf` is not a backend dependency, so PDF text extraction is unavailable | Known gap; tell teachers to upload DOCX/TXT until a dependency decision is made |

## Mitigate

**A. Worker not consuming.** Restart only the worker (it drains gracefully; `acks_late` re-delivers unacknowledged messages):

```bash
docker restart "$(svc worker)"
celery_cmd inspect ping --timeout 10
```

If it crash-loops, check memory (`docker stats --no-stream`, 1 GiB limit) and the last traceback. Do not raise concurrency on the single-CPU staging host.

**B. Lost messages / no sweeper.** Run one sweep by hand (safe and idempotent: it only re-dispatches overdue rows and expires leases under the DB rules):

```bash
docker exec -i "$(svc worker)" python -c "from app.tasks.jobs import sweep; print(sweep())"
```

Then fix the root cause: add a beat process to staging (one instance only, e.g. a `beat` service running `celery -A app.worker:celery_app beat`), redeploy, and confirm `jobs_swept` log lines every minute.

**C. Repeated crash on one job.** Leave it `failed` (no automatic retry loop). Ask the teacher to retry from the UI or `POST /v1/workspaces/{id}/jobs/{jobId}/retry` once the cause is fixed. Never edit `background_jobs` rows by hand to "unstick" them; if a manual state change is unavoidable it is a **WRITE** that needs the owner's approval and an incident note.

**Rollback.** If the backlog started with a release, redeploy the previous release SHA with `deploy/deploy.sh` (application-only rollback; never downgrade the schema). Jobs written by the newer code must still be readable by the older code — check the release notes for new job kinds first.

## Verify recovery

`queue_lag_seconds` back under 300, broker lists draining, oldest `queued` row younger than 5 minutes, and a fresh test upload on a staff test workspace reaching `succeeded`.

## Alert drill

Run on staging, outside teaching hours, with a staff-only test workspace. Record date, operator and results.

1. **Wiring drill (no data change):** `ALERT_THRESHOLD_QUEUE_LAG_SECONDS=-1` in the temporary env file, run `check.py`; expect `BREACH queue_lag_seconds` and exit 1, and confirm the notification arrives. Remove the override; expect exit 0.
2. **Real drill:** `docker stop "$(svc worker)"`; upload a small `.txt` document in the test workspace; wait 6 minutes; run `check.py` → expect `BREACH queue_lag_seconds` (> 300). `docker start "$(svc worker)"`; the queued message is consumed; within 2 minutes `check.py` exits 0 and the document is `uploaded`.
3. **Lost-message drill:** with the worker stopped, upload a document, then `redis_broker del ingestion` (staging only, test workspace only, nothing else queued — check `llen` first). Start the worker; the job stays `queued` until a sweep runs (Mitigation B). Expected today: it stays queued because staging has no beat — this documents the gap.
