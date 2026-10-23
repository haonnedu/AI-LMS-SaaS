-- Eduvia pilot alert checks (PILOT-04). Read-only. Run by deploy/alerts/check.py.
--
-- Format: each check starts with "-- name: <identifier>" and "-- threshold: > <number>",
-- followed by ONE statement that returns exactly one row whose first column is the metric.
-- A check is in breach when metric > threshold. Thresholds can be overridden per run with
-- ALERT_THRESHOLD_<NAME_UPPERCASE>=<number>.
--
-- Every edu table uses FORCE ROW LEVEL SECURITY. These queries only see tenant rows when run
-- by a role that bypasses RLS (the staging administrator, or a future dedicated read-only
-- monitoring role with BYPASSRLS). check.py refuses to run as a role that cannot bypass RLS,
-- because the runtime role would see zero rows and report a false "all green".
--
-- Results are aggregate numbers only: no student, user or workspace identifiers leave the
-- database through these checks. Use the runbooks' drill-down queries for details.

-- name: queue_lag_seconds
-- threshold: > 300
-- Age of the oldest queued job. The sweeper (Celery beat, every 60 s) re-dispatches queued
-- jobs older than the dispatch timeout; a growing value means no worker is consuming, beat is
-- not running, or the broker is down. Runbook: deploy/runbooks/queue-lag.md
SELECT coalesce(max(extract(epoch FROM (now() - j.created_at))), 0)::bigint
FROM edu.background_jobs j
WHERE j.status = 'queued';

-- name: failed_jobs_last_hour
-- threshold: > 0
-- Jobs that reached the terminal 'failed' state in the last hour (all kinds).
-- Runbook: deploy/runbooks/queue-lag.md (ingestion/generation/export) and
-- deploy/runbooks/scoring-failures.md (kind = 'attempt.grade').
SELECT count(*)::bigint
FROM edu.background_jobs j
WHERE j.status = 'failed'
  AND j.finished_at >= now() - interval '1 hour';

-- name: quota_exhausted_workspaces
-- threshold: > 0
-- Workspaces whose usage this UTC month has reached the hard monthly cap (uploads, embeddings
-- and AI drafts all fail with 429 quota_exceeded). Runbook: deploy/runbooks/quota-and-provider-cost.md
SELECT count(*)::bigint
FROM edu.workspace_quotas q
WHERE q.month_cap_units <= (
  SELECT coalesce(sum(u.units), 0)
  FROM edu.usage_events u
  WHERE u.workspace_id = q.workspace_id
    AND u.created_at >= date_trunc('month', now(), 'UTC')
);

-- name: attempts_in_progress_past_deadline
-- threshold: > 0
-- In-progress attempts more than 2 minutes past their deadline. edu.expire_attempts finalizes
-- them (5 s grace) on every sweep; anything older means the sweep is not running or failing.
-- Runbook: deploy/runbooks/scoring-failures.md
SELECT count(*)::bigint
FROM edu.quiz_attempts q
WHERE q.status = 'in_progress'
  AND q.deadline_at IS NOT NULL
  AND q.deadline_at < now() - interval '2 minutes';

-- name: grading_pending_over_10_minutes
-- threshold: > 0
-- Submitted attempts without a current grade 10 minutes after the submission was recorded.
-- Runbook: deploy/runbooks/scoring-failures.md
SELECT count(*)::bigint
FROM edu.quiz_attempts q
WHERE q.status = 'submitted'
  AND q.submission_recorded_at < now() - interval '10 minutes'
  AND NOT EXISTS (
    SELECT 1 FROM edu.grades g WHERE g.attempt_id = q.id AND g.is_current
  );
