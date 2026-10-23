# Runbook: authentication and session incidents

No automated alert yet. Triggers: users cannot sign in, mass "Phiên đã hết hạn" / 401, `identity_unavailable` 503s, a suspected account takeover, a leaked secret, or an unexpected cross-workspace access report.
Page: `—` (operations); for suspected compromise or cross-tenant exposure also `—` (security/privacy owner) immediately.

## Components

- Auth0 tenant (hosted login, refresh tokens, post-login Action adding namespaced `email`/`email_verified`: `deploy/auth0/post-login.js`, setup in `deploy/auth0/README.md`).
- Next.js BFF: server-side session in the `sessions` Redis (AES-256-GCM, absolute 24 h, idle 2 h, cookie `eduvia_session`), CSRF on every mutation (`frontend/src/lib/server/auth.ts`).
- API: verifies RS256 access tokens against the fixed issuer/audience/JWKS (`backend/app/core/auth.py`), then `edu.bootstrap_identity` / `edu.actor_id()` map `(issuer, subject)` to a user. Disabled users (`users.is_active = false`) are refused in the database.

## Symptoms and first checks

| Symptom | Check |
|---|---|
| Everyone gets 503 `identity_unavailable` | API cannot fetch JWKS: `docker logs --since 15m "$(svc api)" \| grep -i jwks`; Auth0 status page; outbound network from the `app` network |
| Everyone gets 503 `auth_unavailable` | `AUTH_ISSUER/AUTH_AUDIENCE/AUTH_JWKS_URL` missing in the deployed env |
| Everyone redirected to /login repeatedly | Session Redis down or wrong `SESSION_REDIS_URL`/`SESSION_ENCRYPTION_KEY` (rotating the key invalidates all sessions — expected) |
| 503 `service_unavailable` from `/api/session` | `sessions` container health: `docker inspect -f '{{.State.Health.Status}}' "$(svc sessions)"` |
| Callback errors (`/login?error=callback`) | Frontend logs `auth_callback_failed` with `code`/`oauthError` only (no tokens): `docker logs --since 15m "$(svc frontend)" \| grep auth_` ; check Auth0 application callback/logout URLs vs `APP_BASE_URL` |
| 403 `email_unverified` for a verified user | Post-login Action not deployed or claim namespace mismatch |
| 401 `invalid_token` spikes | Clock skew (> 30 s leeway), audience mismatch after config change, or Auth0 signing key rotation (JWKS cache 5 min) |
| One user sees another workspace / student sees other students | **Treat as a security incident** — go to "Suspected compromise / data exposure" |

Useful read-only SQL (administrator):

```sql
-- account state for one identity (use the subject from Auth0 logs, not the email, in tickets)
SELECT id, provider_issuer, is_active, created_at, updated_at FROM edu.users
WHERE provider_sub = '<auth0 subject>';

-- memberships of that user
SELECT workspace_id, role, status, updated_at FROM edu.workspace_members WHERE user_id = '<user uuid>';
```

## Mitigate

**Auth0 outage:** nothing to restart. Existing BFF sessions keep working until their access token needs a refresh; new logins fail. Communicate to teachers; postpone scheduled class tests (students cannot sign in).

**JWKS/config error after a deploy:** application-only rollback to the previous release (`deploy/deploy.sh <previous SHA>`), keep the env file unchanged.

**Suspected account takeover (one user):**
1. Block the user in Auth0 (Dashboard → User → Block) and revoke their refresh tokens / sessions there.
2. Remove their BFF sessions: sessions are keyed by an opaque id, so the safe broad action is to rotate nothing and instead disable the account in the database (**WRITE**, approval `—`):
   ```sql
   UPDATE edu.users SET is_active = false, updated_at = clock_timestamp() WHERE id = '<user uuid>';
   ```
   `edu.actor_id()` then returns NULL for every request of that identity (API 401/404 on next call); `bootstrap_identity` refuses re-login.
3. Review what the account did: audit log lines (`docker logs "$(svc api)" | grep '"audit"'`) for the time window; mutations of grades/releases/memberships.
4. Re-enable only after the user has reset credentials in Auth0.

**Leaked secret:**
- `AUTH0_CLIENT_SECRET` / management secret: rotate in Auth0, update the shared env file (`deploy/generate-env.py` never prints values; edit with care), redeploy.
- `SESSION_ENCRYPTION_KEY` / `AUTH0_SECRET`: replace, redeploy; all users must sign in again.
- Database/Redis passwords: changing the env file does **not** rotate an initialized database role (deploy/README). Perform a planned `ALTER ROLE ... PASSWORD` as administrator, then redeploy with the new env.

**Suspected compromise / cross-tenant data exposure:**
1. Preserve evidence first: copy API/frontend/worker logs for the window (`docker logs --since <time> ... > incident-<id>-api.log`, stored mode 600 outside the release directory).
2. Contain: if exposure is ongoing and not explained by a single account, put the stack in maintenance (`docker stop "$(svc frontend)"`) — this stops all browser traffic; database and jobs remain intact.
3. Escalate to `—`. Personal-data incidents may carry legal notification duties (see `tasks/decisions/0008-privacy-consent-retention.md`); do not contact affected users before the owner decides.
4. Reproduce with test accounts only; add a failing regression test (`backend/tests/*_integration.py` or `frontend/tests/e2e`) before the fix ships.

## Verify

A test teacher and a test student can sign in, load the dashboard and `/api/session` shows `authenticated: true`; a logged-out cookie replay is rejected (`frontend/tests/auth/login.spec.ts` scenario run against staging if possible).

## Alert drill

Until log-based alerting exists, drill the procedure:
1. **Disable/enable drill:** with a staff test account, run the `is_active = false` step (approved), confirm the next BFF call fails and re-login is refused, then set it back to `true` and confirm sign-in works. Record timings.
2. **Session store drill:** `docker restart "$(svc sessions)"` outside teaching hours; all sessions disappear (no persistence) and users are sent to /login; sign in again works.
3. **JWKS drill (staging only):** deploy with a wrong `AUTH_JWKS_URL` host in a test env → API returns 503 `identity_unavailable`; redeploy the correct env.
