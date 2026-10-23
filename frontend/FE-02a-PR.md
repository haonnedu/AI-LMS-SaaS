# feat(frontend): add mock personal workspace onboarding

## Task and scope

- Task ID: FE-02a, frontend preparation after FE-01 mock merged in PR #5.
- Owner: Duc. Proposed reviewer: Hao; approval not yet recorded.
- Previously mock login went straight to `/`. It now opens `/onboarding`, where
  users prepare/reuse a sample personal workspace or continue browsing previews.
  The shell shows that workspace, and dashboard greeting uses the current user.
- Workspace state resets by auth generation, even when the same mock user logs
  in again. Operation guards discard stale results after leaving, logout or expiry.
  Dev fixtures cover success, existing record and first-failure/retry.
- Out of scope: real identity provider, HTTP integration, protected routes,
  workspace selector, school provisioning, backend/database and workflow changes.

## Evidence

- Base: `2379a6e5e70b5c65645880202cae6bab5b11ac8b`; implementation is currently
  uncommitted on `feat/fe-02-workspace-mock`. Add the new source commit after commit.
- [Handoff, review findings, manual checklist and file manifest](FE-02a.md).
  Raw diagnostic captures and DOM geometry: `evidence/fe-02a/`.
- Windows PowerShell, Node v24.14.1, npm 11.11.0. Existing implementation baseline:
  `npm run lint`, `npm run typecheck`, `npm run test:workspace` (4/4), and
  `npm run build` including standalone preparation all exited 0 in `frontend`.
  Build ran outside the filesystem sandbox. MCP backlog parser command
  `.\.venv\Scripts\python.exe -m pytest tests/test_backlog.py -q` exited 0 (14/14)
  in `tools/eduvia-mcp`.
- Browser baseline covered success/existing/error-retry, pending action locking,
  pending navigation/logout/expiry, same-user re-login, reload and keyboard use.
  Standalone production completed login → onboarding → dashboard → logout, with
  both scenario selectors absent and empty captured warning/error lists.
- Review pass changed docs only, so the implementation checks above were not
  rerun and must not be presented as new executions.
- Mocks: all auth/workspace data is React-memory sample data; backend/provider
  integration is not exercised. Four automated tests cover the adapter; lifecycle
  and navigation checks are manual browser checks, not an automated E2E suite.
- Blocker: capture raster does not match DOM rectangles at 375×812/1440×900.
  DOM showed no horizontal overflow, but visual acceptance remains pending.
- CI gap: frontend job does not yet call `npm run test:workspace`. Coordinate
  the shared workflow change with Hao separately; reviewer must run it manually
  until that step exists. This PR does not modify CI.
- Second-machine reproduction: pending Hao's run; record result before signoff.

## Migration and contract impact

- No migration, schema, data conversion or rollback/forward-fix requirement.
- No HTTP/public API, OpenAPI or generated type changes. `WorkspaceSummary` and
  `WorkspaceAdapter` are internal frontend interfaces; `sessionVersion` is internal
  auth-context state and is not an authorization credential.
- Permission/tenant behavior remains preview-only. No secrets, real users or
  student records are added to evidence; mock state grants no backend access.
- No dependency or lockfile changes. A `test:workspace` npm script uses Node's
  existing test runner and TypeScript support on the configured Node 24 runtime.

## Review

- [ ] Acceptance verified against the tracker — visual gate remains open
- [x] Evidence excludes secrets and student records
- [ ] Reviewer approval recorded; product/teacher approvals linked where required
- [x] Task status updated only after its acceptance is met — FE-02a/FE-01 remain
  `in_progress`, FE-02 remains `todo`; no completion claimed

Local review found no additional confirmed functional defects within the mock
scope. Visual/reviewer signoff is still missing; this is not a merge-ready claim.
This is a local draft only: no commit, push, remote PR, message or deployment.
