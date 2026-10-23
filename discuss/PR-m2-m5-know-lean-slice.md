## Task and scope

- Task ID(s): CLASS-01..04, JOB-01/02/04/05, COST-01/02, STORE-01..04, AUDIT-01, KNOW-01..05 (lean cut per IMPLEMENTATION_PLAN 3.4), BE-05 shared helper; draft review of the M1 slice (912c0d2) in `discuss/REVIEW.md`.
- Owner / reviewer: Hao (implemented with agents) / Duc.
- Problem and resulting behavior: after M1 (Auth0 identity, 912c0d2) the next MVP tracks are classes, durable jobs/storage and knowledge ingestion. This PR adds:
  - `app/api/workspace_access.py`: `workspace_transaction` = membership check + RLS context for every tenant route.
  - Migration `0008_classes`: classes, class_teachers, students, enrollments, class_invitations (sha256 token hash, single-use atomic accept via SECURITY DEFINER), FORCE RLS.
  - Migration `0009_jobs_storage`: `background_jobs` (idempotency key + request hash, lease, sweeper), append-only `usage_events`, `workspace_quotas` hard monthly cap, `documents` with server-derived object keys; MinIO added to `compose.yaml`.
  - Migration `0010_knowledge`: curriculum seed (Toán/Văn/Anh, 15 Toán units marked `seed:pilot-draft`), immutable `document_versions` with one active version, versioned `document_chunks`, curriculum tags.
  - Routers `/v1` classes, documents (raw-body upload ≤25 MiB, pdf/docx/txt, rights attestation header), jobs (list/get/cancel/retry), knowledge (curriculum, versions, chunks, reingest, tags). Celery `app.tasks.jobs` with `acks_late`, PostgreSQL leases, 60s sweeper. Structured audit log with redaction.
  - Frontend: `/dashboard/classes`, `/dashboard/classes/[classId]`, `/dashboard/documents`, `/join/[token]` through the existing BFF; `backend()` extended for JSON/raw bodies, CSRF unchanged.
- Out of scope: embeddings/retrieval/citations (KNOW-06..10, provider decision pending), assignments (ASSIGN-*), full outbox/fencing, signed upload URLs, Redis-backed rate limiting, PDF parsing dependency (`pypdf` recommended, not added to locks).

## Evidence

- Source commit and evidence path/link: e144a4a; `tasks/CORE.md` execution record 2026-10-23; `discuss/HAO.md`.
- Environment, exact commands, exit codes and results (Windows 11, Python 3.12, Node 24, no Docker):
  - `backend`: `python -m ruff check .` 0, `python -m ruff format --check .` 0, `python -m pytest -q` → 333 passed, 23 skipped.
  - `python backend/scripts/export_openapi.py contracts/openapi.json` + `npm run api:generate` → no drift.
  - `frontend`: `npm run lint` 0, `npm run typecheck` 0, `npm run build` 0, `npm run test:unit` 11/11, `npm run test:workspace` pass.
- Real integrations versus mocks; skips/blockers: all 23 skips are PostgreSQL integration tests gated on `AUTH_TEST_DATABASE_URL` (`test_classes_integration`, `test_jobs_integration`, `test_knowledge_integration`, plus Duc's identity/bootstrap tests). **None of the SQL in 0005–0007 has run on a real database yet**; MinIO image/healthcheck, streamed upload Next→FastAPI and browser UI are unverified. CI `backend` job runs `alembic upgrade head` and is the first real check.
- Second-machine reproduction (when required): not done.

## Migration and contract impact

- Migration / upgrade / rollback or forward-fix impact: three new revisions `0004 → 0008_classes → 0009_jobs_storage → 0010_knowledge`. 0005 has a real downgrade; 0006 and 0007 are forward-only (raise). 0006 adds a trigger on `edu.workspaces` to provision quota rows and backfills existing workspaces with a temporary `NO FORCE`. 0007 alters `edu.documents` (new columns + deferred composite FK).
- Public API / OpenAPI / generated types: many new `/v1` routes; `contracts/openapi.json` and `frontend/src/lib/api/generated.ts` regenerated and committed.
- Permission, tenant isolation and secret/PII handling: every tenant table FORCE RLS with `workspace_id = current_setting('edu.current_workspace_id') AND edu.can_read_workspace(workspace_id)`; runtime role gets explicit grants only (usage_events insert-only, chunks insert-only); invitation tokens stored hashed and returned once; object keys never client-chosen; audit redacts token/secret/email. Students joining a class do not become workspace members.
- Dependency/lock changes and reviewed reason (or none): none in Python (pypdf deliberately not added; needs uv to regenerate locks). No new npm packages. `compose.yaml` adds `minio` and `minio-init` images by tag (not digest).

## Review

- [ ] Acceptance verified against the tracker
- [x] Evidence excludes secrets and student records
- [ ] Reviewer approval recorded; product/teacher approvals linked where required
- [ ] Task status updated only after its acceptance is met (rows are `review`, not `done`)

Reviewer focus: `workspace_access.py`, the RLS/grant blocks in 0005–0007, `bootstrap`-style SECURITY DEFINER functions (`accept_class_invitation`, `job_actor`, `overdue_job_ids`), and the extended `backend()` BFF helper. The five P2 findings on the M1 slice are listed in `discuss/REVIEW.md` for Duc's response.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
