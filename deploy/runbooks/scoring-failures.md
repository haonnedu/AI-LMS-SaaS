# Runbook: submission, deadline and grading failures

Alerts: `attempts_in_progress_past_deadline` > 0, `grading_pending_over_10_minutes` > 0, `failed_jobs_last_hour` > 0 where `kind = 'attempt.grade'`.
Page: `—` immediately during a scheduled class test (lost work or wrong scores block the pilot); otherwise `—`.

## How submission and grading work

- Students start, autosave and submit only through SECURITY DEFINER functions (`edu.student_start_attempt`, `edu.student_save_answer`, `edu.student_submit`, migration 0015). Writes after `deadline_at` + 5 s are rejected (`EV010`).
- Submit and the deadline sweeper share `edu.finalize_attempt`: it freezes the answer snapshot (sha256) and enqueues exactly one `attempt.grade` job (idempotency key `system:attempt.grade:<attempt id>`), requested by the **assignment author** so the worker runs with a verified teacher context.
- The worker scores deterministically from `edu.exam_keys_for_scoring` (no AI). Results are append-only (`grading_results`, `grading_result_items`); `grades` gets a new current revision.
- `edu.expire_attempts` (deadline) and `edu.apply_due_releases` (`after_close` score/solution release) run inside the beat sweep every 60 s. **Staging has no beat** (see README): timed attempts are not finalized and `after_close` releases never happen there until it is added.
- Score release and solution release are separate teacher actions (`release-scores`, `release-solutions`).

## Symptoms

- Students report "Đã hết giờ" / cannot save, or a submitted attempt shows "Đang chấm" for a long time.
- Teacher results page shows `pending` rows after the class ended.
- Alert breaches above.

## Diagnose (administrator, read-only)

```sql
-- in-progress attempts past deadline (should be finalized by the sweeper)
SELECT q.id, q.assignment_id, q.deadline_at, now() - q.deadline_at AS overdue
FROM edu.quiz_attempts q
WHERE q.status = 'in_progress' AND q.deadline_at < now() - interval '2 minutes'
ORDER BY q.deadline_at LIMIT 50;

-- submitted but not graded: is there a grading job, and what state is it in?
SELECT q.id AS attempt_id, q.submission_recorded_at, j.id AS job_id, j.status, j.attempt,
       j.error_code, j.updated_at
FROM edu.quiz_attempts q
LEFT JOIN edu.background_jobs j
  ON j.workspace_id = q.workspace_id AND j.idempotency_key = 'system:attempt.grade:' || q.id::text
WHERE q.status = 'submitted' AND q.submission_recorded_at < now() - interval '10 minutes'
  AND NOT EXISTS (SELECT 1 FROM edu.grades g WHERE g.attempt_id = q.id AND g.is_current)
ORDER BY q.submission_recorded_at LIMIT 50;

-- grading failures by code in the last day
SELECT error_code, count(*) FROM edu.background_jobs
WHERE kind = 'attempt.grade' AND status = 'failed' AND finished_at > now() - interval '1 day'
GROUP BY error_code;

-- is the grading actor (assignment author) still an active member?
SELECT a.id AS assignment_id, m.status AS member_status, u.is_active
FROM edu.assignments a
JOIN edu.workspace_members m ON m.workspace_id = a.workspace_id AND m.user_id = a.created_by_user_id
JOIN edu.users u ON u.id = a.created_by_user_id
WHERE a.id = '<assignment uuid>';
```

Grading `error_code` meanings (`backend/app/services/scoring.py`): `attempt_not_found`, `attempt_not_submitted`, `assignment_not_found`, `snapshot_mismatch` (answers changed after the snapshot — treat as a **data-integrity incident**), `answer_key_invalid` (published exam without a valid key — should be impossible after publication validation), `invalid_job_input`. `lease_expired` / `max_attempts_exceeded` mean the worker crashed or timed out.

Also check the worker side as in [queue-lag.md](queue-lag.md) (`celery_cmd inspect active`, broker list `default`).

## Decide

| Finding | Action |
|---|---|
| No grading job row for a submitted attempt | Should not happen (same transaction). Escalate as data-integrity incident; do not insert jobs by hand. |
| Job `queued` long, broker `default` empty | Lost message + no sweeper → run one sweep (below) |
| Job `failed`, code `lease_expired`/`max_attempts_exceeded` | Fix worker cause, then teacher retries the job |
| Grading actor membership revoked/disabled | Restore the author's membership, or have another teacher grade manually via override; then retry |
| `snapshot_mismatch` / `answer_key_invalid` | Stop: freeze releases for that assignment (do not release scores), escalate to `—`, preserve evidence |
| Attempts past deadline, still `in_progress` | Run one sweep (finalizes with reason `deadline`, keeps saved answers) |

## Mitigate

```bash
# One sweep: expire overdue attempts (submits what was saved), apply due releases, re-dispatch jobs.
docker exec -i "$(svc worker)" python -c "from app.tasks.jobs import sweep; print(sweep())"
```

- Retry a failed grading job: teacher (or owner) calls `POST /v1/workspaces/{id}/jobs/{jobId}/retry`; retries are idempotent (`grading_results` unique per attempt/run key).
- Manual grade when automation cannot recover in time: teacher uses `POST /v1/workspaces/{id}/assignments/{aid}/attempts/{attemptId}/override` with a reason (creates a new grade revision; audited). Do not release scores until the class's pending count is zero or the teacher accepts partial release.
- Wrong scores already released: releases cannot be recalled (`grade_guard`). Correct with an override (new current revision) and inform the teacher; never update `grades` rows directly.
- Students who lost time because of an outage: teacher extends the window (`POST .../extend`, closing time can only move later). Individual attempt deadlines can only be extended, never shortened.

**Rollback.** Application-only rollback via `deploy/deploy.sh <previous SHA>` is safe for scoring code. **Never** roll back the schema once submissions exist; never delete or void attempts to "re-run" a test.

## Verify recovery

Both alerts back to 0; the teacher results page shows no `pending` rows older than 10 minutes; one student result viewed through `/v1/student/attempts/{id}/results` shows the released score and no solution unless solutions were released.

## Alert drill

Staff-only test class with two test student accounts; staging only.

1. **Wiring drill:** `ALERT_THRESHOLD_GRADING_PENDING_OVER_10_MINUTES=-1` → expect breach/exit 1 and a notification; remove → exit 0.
2. **Deadline drill:** publish a test assignment with `timeLimitSeconds = 60`; student starts and saves one answer, then closes the tab. After 3 minutes `check.py` reports `attempts_in_progress_past_deadline` = 1 (expected today because staging lacks beat). Run one sweep; the attempt becomes `submitted` with reason `deadline` and the saved answer, then `graded`; the alert clears.
3. **Grading-worker drill:** `docker stop "$(svc worker)"`; student submits; wait 11 minutes → `grading_pending_over_10_minutes` = 1. Start the worker (and sweep if the message was lost); the grade appears; the alert clears.
4. Record durations: submit→graded, outage→detected, detected→recovered.
