# Domain boundaries

The base exposes health endpoints only. Add each module as a vertical slice with
`router.py` (HTTP DTOs), `service.py` (use cases/authorization), `repository.py`
(queries), `models.py` (persistence), and focused tests when it is implemented.
Do not generate empty CRUD endpoints for this catalog.

| Planned module | Authority and implementation order |
| --- | --- |
| identity | Verify provider sessions; never trust client user or workspace headers. |
| workspaces | Personal/school membership, explicit switching, transaction-local RLS context. |
| knowledge | Separate licensed shared catalog from workspace private source material. |
| content | AI drafts, review, immutable publication, citation provenance. |
| teaching | Classes, students, active enrollments, assignments. |
| assessment | Frozen questions/keys, deadlines, idempotent submit, deterministic grades. |
| scanning | Sheet identity, OMR detection, human review, revisioned grading. |
| billing | Entitlements, reservations, metering, deduplicated webhooks. |
| operations | Transactional outbox, durable jobs, retries, audit, retention. |

Before exposing any tenant data: implement verified identity, least-privilege runtime
roles, `FORCE ROW LEVEL SECURITY`, non-null workspace IDs, composite foreign keys,
transaction-local actor/workspace context, policy tests, and DTO allowlists. The
infrastructure session dependency is not an authorization mechanism. Never add a
header-based development authentication bypass. Keep answer keys server-only.

Read the root `ARCHITECTURE.md` and `DATABASE.md` for requirements. Joining a school
must preserve the teacher's personal workspace and content ownership. Domain tasks
must carry durable job IDs, reauthorize at execution, and be idempotent; broker
delivery alone must never be used as the source of truth.

