# Runbook: backup, restore and the restore drill (PILOT-06)

Script: [`deploy/restore-drill.sh`](../restore-drill.sh) (dry-run by default).
Page: `—` (operations) for any real restore; a real restore of production also needs the go decision of `—` because it can lose writes made after the backup.

## Current state (be honest about it)

- **No automated backups exist** for staging: no scheduled `pg_dump`, no WAL archiving/PITR, no off-host copy, no backup-freshness alert. The only dumps are the ones this drill writes to `--backup-dir` (default `~/eduvia-staging/backups`, mode 700, files mode 600 — they contain all personal data; treat them like the database).
- Object storage is not configured on staging (deploy/README); the object section of the drill is skipped until a bucket exists.
- There is no deletion tombstone table yet (`tasks/decisions/0008-privacy-consent-retention.md` section 4.2). After a restore, erasures performed after the backup cannot be replayed automatically.
- Targets are **TO BE APPROVED** by the pilot owner: database RPO ≤ 15 minutes and RTO ≤ 4 hours (ARCHITECTURE.md section 13). A 15-minute RPO is impossible with periodic `pg_dump` alone; it needs WAL archiving or a managed database with PITR.

## Symptoms that lead here

Database volume lost or corrupted, a destructive operator mistake, a failed host, or a bad data migration that cannot be fixed forward.

## Decide before restoring

1. Can it be fixed forward (new migration / application fix)? Prefer that: the schema is forward-only and restoring loses every submission, grade and upload made after the backup.
2. What is the newest good backup, and what will be lost (time window)? Tell the owner `—` and the pilot teachers before restoring if students may lose submitted work.
3. Freeze writes: stop `frontend`, `api`, `worker` (`docker stop "$(svc frontend)" "$(svc api)" "$(svc worker)"`). Keep `db` running.

## Real restore (outline, not automated)

1. Restore the chosen dump into a **new** database (same procedure as drill steps 3–7: `createdb` + `pg_restore --exit-on-error`), verify head, counts and security posture.
2. Swap: rename databases as administrator during the write freeze (`ALTER DATABASE eduvia RENAME TO eduvia_broken_<date>; ALTER DATABASE <restored> RENAME TO eduvia;`). Never drop the broken database until the incident is closed.
3. Re-grant database-level privileges that `pg_dump` does not carry (`GRANT CONNECT ON DATABASE eduvia TO eduvia_migrator, eduvia_runtime;` — see `deploy/postgres/bootstrap.sql`).
4. Reconcile (report-only queries in drill step 8):
   - Documents soft-deleted after the backup: their chunks/objects reappear → re-run `document.delete` (idempotent `edu.purge_document_chunks`).
   - Erasure requests handled after the backup: replay manually from the incident/erasure log until a tombstone table exists.
   - Objects uploaded after the backup exist in the bucket but not in the DB (orphans, harmless; list them for cleanup). Objects referenced by the DB but missing from the bucket are a data-loss finding.
   - Redis (broker) is rebuilt: `queued` jobs are re-dispatched by the sweep (run it once by hand; staging has no beat).
   - Usage ledger: provider calls made after the backup are not in `usage_events`; compare with the provider console before restoring caps.
5. Start `api`, `worker`, `frontend` with the **same release** that wrote the backup's schema (`alembic_version` must equal the release head; never downgrade).
6. Run `deploy/alerts/check.py` and the smoke checks from `deploy/CHECKLIST-release.md`.

## The drill

```bash
cd /home/nnh/eduvia-staging/releases/$(cat /home/nnh/eduvia-staging/shared/current-release)
bash deploy/restore-drill.sh                       # dry run: prints the plan only
bash deploy/restore-drill.sh --execute \
  --env-file /home/nnh/eduvia-staging/shared/staging.env   # adds the `alembic current` check
# once a bucket exists (mc alias configured with a read-only key for the live bucket):
bash deploy/restore-drill.sh --execute --mc-alias staging \
  --bucket eduvia-staging --scratch-bucket eduvia-staging-restore-drill
```

What it does: measures the age of the newest previous dump (the RPO you would have had), counts key tables, dumps the live database, restores into a disposable `eduvia_restore` database in the same container, checks `alembic_version` (and `alembic current` through the api container) equals this release's head, compares row counts, checks every `edu` table still has FORCE RLS, counts SECURITY DEFINER functions owned by `eduvia_identity_owner` (25 at migration 0011) and none executable by PUBLIC, reports chunks of deleted documents that a real restore would have to purge again, optionally mirrors the bucket into a scratch bucket and checks every DB-referenced object exists there, then drops the disposable database (`--keep` to inspect) and prints RPO/RTO.

What it never does: write to the live database or bucket, run `alembic upgrade/downgrade`, drop anything other than the disposable `*_restore` database it created.

## Drill log

| Date (UTC) | Operator | Release SHA | Dump size | RPO before drill | RTO measured | Objects checked | Failures | Notes |
|---|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | not yet run |

## Alert drill

There is no backup-freshness alert yet. Until one exists, add to the weekly ops checklist: newest file in `--backup-dir` younger than the approved RPO; otherwise page `—`. When scheduled backups are added, add a `backup_age_seconds` check fed by a small metadata table or file timestamp and drill it by pausing the backup job for one interval.
