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
| assessment | Versioned blueprints, validated frozen questions/keys, deadlines, idempotent submit, deterministic grades; core remains scoring authority for future standalone learner assessment. |
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

## Student-learning boundary (planned)

See the root [implementation plan](../../../IMPLEMENTATION_PLAN.md),
[student-learning design](../../../STUDENT_LEARNING.md) and
[exam blueprint specification](../../../EXAM_BLUEPRINTS.md). Student-led learning
is distinct from the assigned-work student portal. It may begin as an isolated
module, then deploy as a microservice with its own database and credentials.
It owns personal goals, plans, evidence receipts and mastery projections; core owns
curriculum/content rights, blueprints/publication and authoritative scoring.
Do not import core repositories into that bounded context, read core tables from
another service, duplicate answer keys, or turn teacher workspace membership into
permission to inspect personal self-study. Use authenticated scoped application
ports/APIs and versioned outbox/inbox events. A standalone learner-owned core
assessment schema is required before independent practice; do not create fake
classes or weaken existing tenant constraints. This is a design boundary only;
no learner module or service is currently implemented.

