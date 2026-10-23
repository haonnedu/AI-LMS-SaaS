# Runbook: workspace quota and AI/embedding provider cost

Alert: `quota_exhausted_workspaces` > 0. Related: `failed_jobs_last_hour` with `quota_exceeded`, `provider_unavailable` or `provider_rate_limited`.
Page: `—` (operations) and `—` (budget owner) when spend approaches the approved monthly AI budget (not yet defined; IMPLEMENTATION_PLAN section 10).

## How metering works

- `edu.workspace_quotas` holds one row per workspace (`month_cap_units`, default 1000; created by trigger `edu.provision_workspace_quota`).
- `edu.usage_events` is an append-only ledger (runtime role: SELECT/INSERT only). `backend/app/services/usage.py` reserves units by locking the quota row (`SELECT ... FOR UPDATE`), summing this UTC month and inserting a `reservation` event; over the cap the API returns `429 quota_exceeded` and the worker fails the job with `quota_exceeded` **before** calling the provider.
- Units: uploads 1 per started MiB; LLM requests `LLM_UNITS_PER_REQUEST` (default 10); embeddings per batch. `provider_cost_minor` and `generation_jobs.input_tokens/output_tokens` record actual provider usage when the adapter reports it.
- Production refuses the fake LLM and the local hashing embedder (`backend/app/core/config.py`, `backend/app/services/llm.py`).

## Symptoms

- Teachers see "Không gian làm việc đã dùng hết hạn mức tháng này." on upload, embedding or AI draft.
- AI drafts fail with `provider_unavailable` (outage/rate limit) while manual authoring keeps working.
- Unexpected provider invoice growth.

## Diagnose (administrator, read-only)

```sql
-- usage vs cap this UTC month, top workspaces (identifiers stay in the ops console)
SELECT q.workspace_id, q.month_cap_units,
       coalesce(sum(u.units), 0) AS used_units,
       coalesce(sum(u.provider_cost_minor), 0) AS provider_cost_minor
FROM edu.workspace_quotas q
LEFT JOIN edu.usage_events u
  ON u.workspace_id = q.workspace_id AND u.created_at >= date_trunc('month', now(), 'UTC')
GROUP BY q.workspace_id, q.month_cap_units
ORDER BY used_units DESC LIMIT 20;

-- what consumed it (by unit type and kind) for one workspace
SELECT unit_type, kind, count(*), sum(units), sum(provider_cost_minor)
FROM edu.usage_events
WHERE workspace_id = '<workspace uuid>' AND created_at >= date_trunc('month', now(), 'UTC')
GROUP BY unit_type, kind ORDER BY sum(units) DESC;

-- AI generation volume, tokens and outcome in the last 24 h (no prompt text is stored)
SELECT provider, model, validation_status, count(*), sum(input_tokens), sum(output_tokens),
       sum(cost_minor)
FROM edu.generation_jobs WHERE created_at > now() - interval '24 hours'
GROUP BY provider, model, validation_status;

-- provider failures
SELECT kind, error_code, count(*) FROM edu.background_jobs
WHERE finished_at > now() - interval '1 hour'
  AND error_code IN ('provider_unavailable','provider_rate_limited','quota_exceeded')
GROUP BY kind, error_code;
```

Compare with the provider's own usage console for the same period. The ledger is authoritative for caps; the provider console is authoritative for money.

## Decide

| Finding | Action |
|---|---|
| One workspace legitimately at cap (normal pilot use) | Product owner `—` decides whether to raise its cap |
| One workspace far above peers in a short time | Possible abuse/automation: contact the teacher before raising anything |
| Many workspaces failing with `provider_unavailable` | Provider outage: announce "AI tạm thời không khả dụng; soạn thủ công vẫn hoạt động"; do not raise retries |
| Spend rising faster than units | Check model/config drift (`LLM_MODEL`, `LLM_MAX_OUTPUT_TOKENS`) in the deployed env |

## Mitigate

- **Raise one workspace cap** (**WRITE**, approval by `—`, record in the incident log). Runtime cannot change caps by design; use the administrator:

  ```sql
  BEGIN;
  UPDATE edu.workspace_quotas SET month_cap_units = <new cap>, updated_at = clock_timestamp()
  WHERE workspace_id = '<workspace uuid>';
  -- verify exactly one row changed, then
  COMMIT;
  ```

  Never delete or edit `usage_events`; corrections are new ledger events.
- **Provider outage:** nothing to restart; failed AI jobs stay `failed` and teachers retry later. If the outage is long, set `LLM_PROVIDER` unchanged but tell teachers to use manual authoring. Do not switch to the fake provider in production (refused anyway).
- **Runaway cost:** rotate the provider API key at the provider (cuts all calls), then redeploy with the new key once the cause is understood. Lowering `LLM_MAX_OUTPUT_TOKENS` / `LLM_UNITS_PER_REQUEST` requires a redeploy.

**Rollback.** Configuration changes roll back by redeploying the previous env + release; caps changed by SQL are reverted by another approved UPDATE.

## Verify

The affected teacher can upload/generate again; `quota_exhausted_workspaces` reflects only workspaces the owner agreed to leave capped; provider console shows the expected rate.

## Alert drill

1. **Wiring drill:** `ALERT_THRESHOLD_QUOTA_EXHAUSTED_WORKSPACES=-1` → breach/exit 1 and notification; remove → exit 0.
2. **Real drill (staging test workspace only):** with approval, set that workspace's `month_cap_units` to 1, upload a 2 MiB text file → API returns 429 `quota_exceeded`; `check.py` shows `quota_exhausted_workspaces` ≥ 1 once one unit has been used. Restore the cap with the same approved UPDATE; the alert clears.
3. **Provider outage drill:** on staging with a real provider configured, set an invalid `LLM_API_KEY` in a test env and redeploy, request one AI draft → job `failed` with `provider_unavailable`/auth error, manual authoring unaffected; restore the key.
