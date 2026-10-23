# Isolated staging deployment

Use only `compose.staging.yaml`, never merge it with the development Compose file.
The project is always `eduvia-staging`; its app/data networks and volumes are project-scoped, not external/shared. PostgreSQL and authenticated Redis have no published ports and only join an internal network. Only the frontend publishes `127.0.0.1:3100`. API/worker also join the app network for outbound integrations. Each service has a 1 GiB memory limit, one CPU, PID limit 256, and rotated Docker logs (3 x 10 MiB); tune against actual workload and available host capacity. Redis has AOF persistence; durable job semantics still need the application's planned database outbox.

## First deployment (Linux, Docker Compose v2+, Bash, flock, Python 3, curl)

No sudo required when the deploy user already has Docker access. Docker group membership is effectively root access. Provision a directory owned by the deploy user outside source control:

```sh
mkdir -p /home/nnh/eduvia-staging/shared
chmod 700 /home/nnh/eduvia-staging/shared
python3 deploy/generate-env.py /home/nnh/eduvia-staging/shared/staging.env --tunnel
# Or replace --tunnel with the exact HTTPS origin (no trailing slash).
bash deploy/deploy.sh /home/nnh/eduvia-staging/releases/<40-character-sha> /home/nnh/eduvia-staging/shared/staging.env
```

The generator exclusively creates a mode-600 file, uses four independent 32-byte random hex credentials, and never prints them. Existing env files are not overwritten. Do not source the env file, commit it, or log resolved `docker compose config` output. Passwords have no Compose defaults and must remain distinct lowercase 64-character hex values (safe for URL interpolation and Redis configuration). Single-quoted dotenv values are used. Tunnel mode sets `CORS_ORIGINS='[]'`, disabling cross-origin browser access without inventing a domain; same-origin frontend proxy calls remain available. APP_ENV is `production`, because backend settings do not accept a staging literal.

Object storage is **unconfigured and unavailable** by default. No S3 service is added. Empty S3 endpoint deliberately avoids the development localhost endpoint and causes the storage factory to fail if invoked; metadata credential discovery is disabled. Existing scaffold exposes no upload/download routes. Configure S3_ENDPOINT_URL, S3_REGION, S3_BUCKET and both S3 credential fields before enabling storage features. Readiness does not prove object storage works.

Use an SSH tunnel to port 3100, or a separately managed host HTTPS reverse proxy. Do not attach this stack to existing shared networks or expose its database/Redis ports. Authentication and tenant isolation need separate review before internet exposure.

## Release and migration guarantees

The release directory basename must be the complete lowercase commit SHA. Git checkouts are verified clean and HEAD-matching. For archive releases, authenticated CI must create the archive from that exact SHA and upload to a fresh directory; a directory name alone cannot prove content provenance. Never modify a release directory in place. Local images are SHA-tagged but are not registry-digest-attested/reproducible builds. The script builds before stopping existing application services.

The shared env directory's flock serializes the entire deployment and Alembic migration. All deploy actors must use the same shared path on this one host; manual Alembic commands and a second host are not protected. The script starts healthy data services, stops old frontend/API/worker, runs migrations as a one-shot container, then waits for API readiness, targeted Celery ping, frontend HTTP, and checks host loopback HTTP. This causes a maintenance window and prevents old application writers during migration. Failed deployments exit without automatic rollback, dropping data, deleting volumes/images, pruning, or touching other projects. Diagnose schema/application compatibility before retrying an old release. Backups and restore drills remain operator responsibilities; take a database backup before risky migrations. No destructive down/downgrade/cleanup is automated.

Postgres bootstrap runs only on an **empty** project volume. It installs pgvector using the administrator because the existing first migration requests an untrusted extension. Non-superuser `eduvia_migrator` owns the `edu` schema and migration-created tables and can create the current public Alembic version table. `eduvia_runtime` has only CONNECT/schema USAGE and default DML/sequence privileges on migrator-created edu objects, not ownership/schema CREATE/BYPASSRLS. Future migrations adding extensions or schema objects outside edu require explicit review. Runtime grants are not tenant isolation: **RLS is not implemented by these files**. Changing dotenv passwords does not rotate an initialized database's roles; perform a planned SQL role-password rotation and application restart. Do not delete a volume to repair credentials. Existing volumes without these bootstrap roles require a reviewed manual upgrade, not automatic adoption.

## Disk retention

Source releases are tiny (about 2 MB each). The real growth is Docker: every deploy tags two images (`backend` ~400 MB, `frontend` ~320 MB, sharing most layers across releases) and adds build cache. Nothing is pruned automatically, so an unreviewed pile of releases accumulates.

`deploy/prune.sh` keeps the newest releases and deletes older release directories, their uploaded archives and their image tags. It is dry-run by default, always protects the release in `shared/current-release`, and skips any image still used by a running container:

```sh
bash deploy/prune.sh          # show what would go, keep newest 3
bash deploy/prune.sh 2        # show plan for keeping newest 2
bash deploy/prune.sh 2 --apply
```

Build cache is host-wide and shared with other stacks on this machine, so it is **not** pruned by that script. Reclaim it deliberately with `docker builder prune --filter until=168h` after checking `docker system df`. Deleting an old release also gives up the ability to redeploy it without a rebuild.

## Validation

Offline checks: `python3 deploy/test-staging.py` (PyYAML), `bash -n deploy/deploy.sh deploy/postgres/10-bootstrap.sh`. Deployment itself validates the resolved Compose JSON without printing secrets, including internal network/no-external-network restrictions, role credential shape, exact origin settings, and loopback-only publishing. Local Windows development environment had no Docker CLI, so real Compose rendering/builds, bootstrap SQL, migration permissions, network reachability and container health require a Docker-enabled integration smoke test. Offline checks are not evidence of a successful deployment.


## Identity/session configuration

The authenticated flow now requires [Auth0 setup](auth0/README.md). The staging frontend joins `app` and an internal `session` network; its dedicated `sessions` Redis uses SESSION_REDIS_PASSWORD, distinct from worker Redis, and has no published port or persistence volume. Frontend still cannot reach the database `data` network. The env generator creates distinct session/auth encryption secrets; tenant/client settings must be supplied separately. Existing env files need the new session secret before Compose validation passes. Existing databases also need the NOLOGIN identity function owner prepared by an administrator before migration 0004.
