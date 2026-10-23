# Release checklist: staging → production (PILOT-07)

Copy this file into the release record (issue/PR) for every production release and tick each line with evidence (link, command output excerpt, or screenshot). A line that cannot be ticked is a **no-go** unless the go/no-go signers record an explicit, dated exception.

Release SHA: `________________________________________` (full 40 characters)
Previous production SHA (rollback target): `________________________________________`
Migrations in this release (from → to): `________ → ________`

## 0. Known blockers on the current tree (2026-10-23)

Resolve or explicitly accept before the first production release:

- [ ] `compose.staging.yaml` passes `EMBEDDING_PROVIDER`/`EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY` (and `LLM_*`) to `api`/`worker`. Today production settings reject the default `local` embedder, so the API does not start.
- [ ] A single Celery **beat** process runs in staging/production (sweeper: lost-message re-dispatch, deadline expiry, `after_close` releases). Today staging has none.
- [ ] Invitation-accept rate limit works behind the BFF (shared store, trusted client IP); today it is per-process and keyed on the frontend container IP (`tasks/decisions/0007-threat-model-pilot.md` F3).
- [ ] CI `auth-integration` job runs **all** `backend/tests/*_integration.py` (today: only `test_bootstrap.py`, `test_identity_integration.py`, `test_auth.py`).
- [ ] `deploy/test-staging.py` updated for the `sessions` service (today it fails its own service-set assertion).
- [ ] Automated database backups exist (see `deploy/runbooks/restore-drill.md`).

## 1. Build and test gates

- [ ] CI "Foundation checks" green on the release SHA: `scripts`, `backend` (ruff, format, pytest, OpenAPI diff, `alembic upgrade head`, readiness), `frontend` (generate, lint, typecheck, workspace tests, build), `containers` (staging config validation, `verify-m0.py`), **`auth-integration` with `AUTH_TEST_DATABASE_URL`** (PostgreSQL identity/RLS + Playwright OIDC).
- [ ] Locally or in CI, the full PostgreSQL integration suite passed against a disposable `*_test` database (until CI covers it):
      ```sh
      cd backend && AUTH_TEST_DATABASE_URL=postgresql+psycopg://postgres:...@127.0.0.1:5434/eduvia_auth_test \
        python -m pytest -q tests/test_*_integration.py tests/test_bootstrap.py tests/test_auth.py
      ```
      Record: passed / skipped counts (skips must be 0 here).
- [ ] Static QA gates passed (part of `pytest`): `backend/tests/test_qa_gates.py` (key leak, 401/404, FORCE RLS, no runtime DELETE on key/ledger/grading tables, forward-only, single head), `test_privacy_inventory.py`, `test_alert_checks.py`. Any `xfail` listed and accepted by signers.
- [ ] Pilot E2E journey (`frontend/tests/e2e/pilot-journey.spec.ts`, `EDUVIA_E2E=1`) passed against staging-like test stack; core failures block release (PILOT-01).
- [ ] Dependency and secret scan reviewed (no tooling in CI yet: record the manual method used).

## 2. Migration gates

- [ ] **Forward-only check**: every new migration's `downgrade()` only raises (`test_qa_gates.py::test_migrations_after_0005_are_forward_only`). Single Alembic head (`test_alembic_has_exactly_one_head`).
- [ ] **Dry-run SQL** reviewed by a second person (offline mode; start from the revision currently in production, not from base — 0004 needs a live connection and cannot render offline):
      ```sh
      cd backend && alembic upgrade --sql <production_revision>:head > /tmp/release-<sha>.sql
      ```
      Check: no `DROP TABLE`/`DROP COLUMN`/`TRUNCATE`/`DELETE FROM edu.` on tables with student data; new tables have `ENABLE` + `FORCE ROW LEVEL SECURITY`; runtime grants are `REVOKE ALL` then the exact set; new SECURITY DEFINER functions set `search_path`, are owned by `eduvia_identity_owner` and revoked from PUBLIC.
- [ ] Migration rehearsed on a restored copy of production data (`deploy/restore-drill.sh --execute --keep`, then `alembic upgrade head` as `eduvia_migrator` against the `*_restore` database) and timed: `____ s` (fits the maintenance window).
- [ ] Lock impact reviewed for large tables (`ALTER TABLE` on `student_answers`, `document_chunks`, `usage_events`).

## 3. Backup gate

- [ ] Fresh backup taken **immediately before** the deploy and verified restorable (`deploy/restore-drill.sh --execute` within the last 24 h, or the managed-DB snapshot id): `________________`
- [ ] Object storage versioning/backup state recorded (or "no object store in use").
- [ ] Restore drill log in `deploy/runbooks/restore-drill.md` has an entry not older than 30 days; RPO/RTO targets approved by: `—`

## 4. Environment and secret isolation

- [ ] Production uses its own env file, database, Redis instances, bucket, Auth0 application/tenant and provider keys; none shared with staging/dev (ARCHITECTURE section 13). Compare names, not values.
- [ ] `docker compose ... config --format json | python3 deploy/validate-config.py` passes (run by `deploy/deploy.sh`; prints no secrets): distinct 64-hex passwords, internal data/session networks, loopback-only frontend port, exact HTTPS CORS origins.
- [ ] `APP_ENV=production`; `LLM_PROVIDER` is not `fake`; `EMBEDDING_PROVIDER` is not `local`; dimension 1024.
- [ ] Env file mode 600, owned by the deploy user, outside the release directory; no secret in git history (scan), CI logs or `docker compose config` output pasted anywhere.
- [ ] Database roles verified on the target: `eduvia_runtime` NOBYPASSRLS, not owner; `deploy/test/run-rls-smoke.sh` passes on the target database.
- [ ] Monitoring/alert credentials (administrator or future `eduvia_monitor`) stored separately from the application env.

## 5. Deploy

- [ ] Maintenance window announced to pilot teachers (no class test scheduled during it).
- [ ] `bash deploy/deploy.sh /…/releases/<sha> /…/shared/<env>` completed: lock acquired, images built, app services stopped, `alembic upgrade head` ran once, API ready, worker ping, frontend HTTP OK.

## 6. Smoke after deploy

- [ ] `deploy/test-staging.py` (offline structural check of the compose file; not a runtime smoke) passes on the release.
- [ ] `curl -fsS http://127.0.0.1:3100/` and API `GET /health/ready` (from inside the api container) return 200.
- [ ] `celery -A app.worker:celery_app inspect ping` and beat log line `jobs_swept` within 2 minutes.
- [ ] `deploy/alerts/check.py` exits 0 (see `deploy/runbooks/README.md` for the safe invocation).
- [ ] Manual journey with staff test accounts: sign in → upload a small DOCX/TXT → job succeeds → create class + invitation → test student joins → assignment (published exam) → start/autosave/submit → graded → release scores → student sees score and no solution before solution release.
- [ ] Logs for the window contain no tracebacks with request bodies, no tokens, no signed URLs.

## 7. Rollback plan

- **Application-only rollback**: redeploy the previous SHA with `deploy/deploy.sh` (same env file). Allowed only if the previous code is compatible with the current schema (additive migrations). Write the compatibility verdict here: `________________`
- **Schema is never rolled back** once the release has accepted writes. Migrations after 0005 refuse `downgrade`; once any submission, grade, upload or usage event exists on the new schema, recovery is a forward fix. Restoring a backup is a data-loss decision (`deploy/runbooks/restore-drill.md`), signed by the owner, never an automatic rollback step.
- Never `docker compose down -v`, delete volumes, or prune images of the current/previous release during an incident.
- Rollback trigger: any of — sign-in broken, submissions failing (`EV*` errors not explained by policy), grading pending > 10 min, cross-tenant or key exposure suspicion, alert check exit ≠ 0 not explained within 30 min.

## 8. Go / no-go

No blocking issue may remain for: tenant isolation, answer-key leakage, lost submissions, wrong scores (PILOT-08).

| Role | Name | Decision (go / no-go) | Date (UTC) | Notes / accepted exceptions |
|---|---|---|---|---|
| Release owner | — | | | |
| Second reviewer (code + migration SQL) | — | | | |
| Security/privacy owner | — | | | |
| Pilot/product owner | — | | | |
| Operations on-call for the window | — | | | |
