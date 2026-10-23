#!/usr/bin/env bash
# PILOT-06 restore drill for the isolated staging stack (project eduvia-staging).
#
# Dumps the live staging database, restores it into a DISPOSABLE database whose name must end in
# "_restore" inside the same PostgreSQL container, verifies the Alembic head, row counts of key
# tables, FORCE RLS and the SECURITY DEFINER inventory, then prints RPO/RTO measurements.
# Optionally mirrors the object-storage bucket into a scratch bucket with `mc mirror`.
#
# Default is --dry-run: nothing is executed, the plan is printed. Use --execute to run.
# The drill never writes to the live database or bucket, never runs migrations or downgrades,
# and only ever drops the disposable *_restore database it created (unless --keep).
#
# Usage:
#   bash deploy/restore-drill.sh [--execute] [--keep] [--project eduvia-staging]
#        [--restore-db eduvia_restore] [--backup-dir DIR] [--env-file /abs/shared/staging.env]
#        [--mc-alias ALIAS --bucket NAME --scratch-bucket NAME-restore-drill]
#
# --env-file is only needed for the optional `alembic current` check (it reads
# POSTGRES_PASSWORD without printing it). Requires: bash, docker, python3; `mc` for objects.
#
# Targets (TO BE APPROVED by the pilot owner, not commitments): database RPO <= 15 min and
# RTO <= 4 h (ARCHITECTURE.md section 13). Staging has no automated backups or WAL archiving yet,
# so the RPO this drill can demonstrate is "age of the newest dump in --backup-dir".
set -Eeuo pipefail
umask 077

project=eduvia-staging
source_db=eduvia
restore_db=eduvia_restore
backup_dir="${HOME}/eduvia-staging/backups"
env_file=""
execute=0
keep=0
mc_alias=""
bucket=""
scratch_bucket=""

die() { echo "restore-drill: $*" >&2; exit 2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute) execute=1 ;;
    --dry-run) execute=0 ;;
    --keep) keep=1 ;;
    --project) project=${2:?}; shift ;;
    --restore-db) restore_db=${2:?}; shift ;;
    --backup-dir) backup_dir=${2:?}; shift ;;
    --env-file) env_file=${2:?}; shift ;;
    --mc-alias) mc_alias=${2:?}; shift ;;
    --bucket) bucket=${2:?}; shift ;;
    --scratch-bucket) scratch_bucket=${2:?}; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

[[ $restore_db =~ ^[a-z][a-z0-9_]*_restore$ ]] || die "restore database must match ^[a-z][a-z0-9_]*_restore\$"
[[ $restore_db != "$source_db" ]] || die "restore database must differ from the source"
[[ $project =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "invalid compose project name"
if [[ -n $mc_alias || -n $bucket || -n $scratch_bucket ]]; then
  [[ -n $mc_alias && -n $bucket && -n $scratch_bucket ]] || die "--mc-alias, --bucket and --scratch-bucket go together"
  [[ $scratch_bucket =~ -restore-drill$ ]] || die "scratch bucket name must end in -restore-drill"
  [[ $scratch_bucket != "$bucket" ]] || die "scratch bucket must differ from the live bucket"
fi
[[ -z $env_file || -f $env_file ]] || die "env file not found"

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
latest_migration=$(ls -1 "$repo_root"/backend/migrations/versions/[0-9][0-9][0-9][0-9]_*.py | tail -n1)
expected_head=$(tr -d '\r' < "$latest_migration" | grep -m1 '^revision = "' | cut -d'"' -f2)
[[ $expected_head =~ ^[0-9]{4}_[a-z0-9_]+$ ]] || die "cannot read the Alembic head from $latest_migration"
key_tables=(users workspaces workspace_members classes students enrollments documents
  document_versions document_chunks questions question_keys exams exam_versions exam_items
  exam_answer_keys assignments quiz_attempts student_answers grading_results grades
  usage_events background_jobs)

step() { printf '\n== %s\n' "$*"; }
plan() { printf '   $ %s\n' "$*"; }
# run CMD...: print in dry-run, execute otherwise.
run() { if (( execute )); then "$@"; else plan "$*"; fi; }

svc() {
  docker ps --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=$1" --format '{{.Names}}' | head -n1
}

now() { date -u +%s; }
iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }

if (( ! execute )); then
  echo "DRY RUN (default). Nothing will be executed. Re-run with --execute on the staging host."
fi

step "0. Preconditions"
db_container="<db container>"
api_container="<api container>"
if (( execute )); then
  command -v docker >/dev/null || die "docker not found"
  db_container=$(svc db); [[ -n $db_container ]] || die "db container of project $project is not running"
  api_container=$(svc api)
  exists=$(docker exec "$db_container" psql -U postgres -d postgres -Atc \
    "SELECT count(*) FROM pg_database WHERE datname = '$restore_db'")
  [[ $exists == 0 ]] || die "$restore_db already exists; inspect and drop it manually (it is never reused)"
  mkdir -p -- "$backup_dir"; chmod 700 -- "$backup_dir"
else
  plan "docker ps --filter label=com.docker.compose.project=$project --filter label=com.docker.compose.service=db"
  plan "refuse if database $restore_db already exists"
fi
echo "   expected Alembic head from this release: $expected_head"

psql_src() { docker exec -i "$db_container" psql -U postgres -d "$source_db" -v ON_ERROR_STOP=1 -At "$@"; }
psql_dst() { docker exec -i "$db_container" psql -U postgres -d "$restore_db" -v ON_ERROR_STOP=1 -At "$@"; }

count_sql() {
  local sep="" t
  for t in "${key_tables[@]}"; do
    printf "%sSELECT '%s', (SELECT count(*) FROM edu.%s)" "$sep" "$t" "$t"
    sep=" UNION ALL "
  done
  echo ";"
}

step "1. RPO: age of the newest previous dump"
previous_epoch=""
if (( execute )); then
  newest=$(ls -1t -- "$backup_dir"/eduvia-*.dump 2>/dev/null | head -n1 || true)
  if [[ -n $newest ]]; then
    previous_epoch=$(stat -c %Y -- "$newest")
    echo "   newest previous dump: $(basename -- "$newest") at $(iso "$previous_epoch")"
  else
    echo "   no previous dump in $backup_dir: RPO for an incident right now would be UNBOUNDED"
  fi
else
  plan "ls -1t $backup_dir/eduvia-*.dump | head -n1"
fi

step "2. Source row counts (administrator, read-only; bypasses RLS)"
declare -A src_counts=()
if (( execute )); then
  while IFS='|' read -r table n; do src_counts[$table]=$n; done < <(count_sql | psql_src)
  src_head=$(psql_src -c "SELECT version_num FROM public.alembic_version")
  echo "   source alembic_version: $src_head"
else
  plan "psql -U postgres -d $source_db -c '<count(*) of ${#key_tables[@]} key edu tables>'"
fi

step "3. Dump (custom format, consistent snapshot)"
dump_start=$(now)
dump_file="$backup_dir/eduvia-$(date -u -d "@$dump_start" +%Y%m%dT%H%M%SZ).dump"
if (( execute )); then
  docker exec "$db_container" pg_dump -U postgres -d "$source_db" -Fc --no-password > "$dump_file"
  [[ -s $dump_file ]] || die "dump is empty"
  echo "   wrote $(basename -- "$dump_file") ($(du -h -- "$dump_file" | cut -f1)) in $(( $(now) - dump_start )) s"
else
  plan "docker exec <db> pg_dump -U postgres -d $source_db -Fc > $dump_file   (mode 600)"
fi

step "4. Restore into disposable database $restore_db"
restore_start=$(now)
run docker exec "$db_container" createdb -U postgres -T template0 "$restore_db"
cleanup() {
  if (( execute && ! keep )); then
    docker exec "$db_container" dropdb -U postgres --if-exists "$restore_db" >/dev/null 2>&1 || true
    echo "   dropped disposable database $restore_db"
  fi
}
(( execute )) && trap cleanup EXIT
if (( execute )); then
  docker exec -i "$db_container" pg_restore -U postgres -d "$restore_db" --exit-on-error --no-password < "$dump_file"
else
  plan "docker exec -i <db> pg_restore -U postgres -d $restore_db --exit-on-error < $dump_file"
fi

failures=0
fail() { echo "   FAIL: $*"; failures=$((failures + 1)); }

step "5. Verify schema version"
if (( execute )); then
  dst_head=$(psql_dst -c "SELECT version_num FROM public.alembic_version")
  echo "   restored alembic_version: $dst_head"
  [[ $dst_head == "$src_head" ]] || fail "restored head differs from source"
  [[ $dst_head == "$expected_head" ]] || fail "restored head is not this release's head ($expected_head)"
  if [[ -n $env_file && -n $api_container ]]; then
    tmp_env=$(mktemp); chmod 600 "$tmp_env"
    python3 - "$env_file" "$restore_db" > "$tmp_env" <<'PY'
import sys
values = {}
for line in open(sys.argv[1], encoding="utf-8"):
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.rstrip("\n").split("=", 1)
        values[key.strip()] = value.strip().strip("'")
print(f"DATABASE_URL=postgresql+psycopg://postgres:{values['POSTGRES_PASSWORD']}@db:5432/{sys.argv[2]}")
PY
    # `alembic current` only reads the version table; no upgrade/downgrade is ever run here.
    current=$(docker exec --env-file "$tmp_env" "$api_container" alembic current 2>/dev/null | tail -n1 || true)
    rm -f -- "$tmp_env"
    echo "   alembic current (restore): ${current:-<unavailable>}"
    [[ $current == "$expected_head (head)" ]] || fail "alembic current is not '$expected_head (head)'"
  else
    echo "   (alembic current skipped: pass --env-file to run it through the api container)"
  fi
else
  plan "psql -d $restore_db -c 'SELECT version_num FROM public.alembic_version'  == $expected_head"
  plan "docker exec --env-file <600 tmp: DATABASE_URL=...@db/$restore_db> <api> alembic current  == '$expected_head (head)'"
fi

step "6. Verify row counts"
if (( execute )); then
  printf '   %-20s %10s %10s\n' table source restore
  while IFS='|' read -r table n; do
    marker=""
    [[ ${src_counts[$table]:-?} == "$n" ]] || marker="  (differs: writes during the dump window or a restore problem)"
    printf '   %-20s %10s %10s%s\n' "$table" "${src_counts[$table]:-?}" "$n" "$marker"
    (( n >= 0 )) || fail "$table unreadable"
  done < <(count_sql | psql_dst)
else
  plan "same count(*) query on $restore_db; print source vs restore per table"
fi

step "7. Verify security posture survived the restore"
if (( execute )); then
  not_forced=$(psql_dst -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'edu' AND c.relkind = 'r' AND NOT c.relforcerowsecurity")
  definers=$(psql_dst -c "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'edu' AND p.prosecdef AND pg_get_userbyid(p.proowner) = 'eduvia_identity_owner'")
  public_exec=$(psql_dst -c "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'edu' AND p.prosecdef AND has_function_privilege('public', p.oid, 'EXECUTE')")
  echo "   edu tables without FORCE RLS: $not_forced (expected 0)"
  echo "   SECURITY DEFINER functions owned by eduvia_identity_owner: $definers (expected 25 at 0011)"
  echo "   SECURITY DEFINER functions executable by PUBLIC: $public_exec (expected 0)"
  [[ $not_forced == 0 ]] || fail "tables lost FORCE ROW LEVEL SECURITY"
  [[ $public_exec == 0 ]] || fail "definer functions executable by PUBLIC"
else
  plan "check relforcerowsecurity on every edu table, definer ownership and PUBLIC EXECUTE on $restore_db"
fi

step "8. Deletions that must be re-applied after a real restore (report only)"
# No tombstone table exists yet (tasks/decisions/0008 section 4.2). Until it does, the only
# recoverable signal is soft-deleted documents whose chunks/objects were purged after the dump.
if (( execute )); then
  pending=$(psql_dst -c "SELECT count(*) FROM edu.document_chunks c
    JOIN edu.document_versions v ON v.id = c.document_version_id
    JOIN edu.documents d ON d.id = v.document_id WHERE d.status = 'deleted'")
  echo "   chunks of deleted documents present in the restore: $pending"
  echo "   In a real restore: re-dispatch document.delete for those documents (edu.purge_document_chunks is"
  echo "   idempotent) and replay any erasure recorded after the backup. Nothing is changed by this drill."
else
  plan "count chunks of documents with status='deleted' in $restore_db (report only)"
fi
restore_end=$(now)

if [[ -n $mc_alias ]]; then
  step "9. Object storage: mirror $mc_alias/$bucket -> $mc_alias/$scratch_bucket"
  if (( execute )); then
    command -v mc >/dev/null || die "mc (MinIO client) not installed on this host"
    obj_start=$(now)
    mc mb --ignore-existing "$mc_alias/$scratch_bucket"
    mc mirror --preserve --overwrite "$mc_alias/$bucket" "$mc_alias/$scratch_bucket"
    src_objects=$(mc ls --recursive "$mc_alias/$bucket" | wc -l)
    dst_objects=$(mc ls --recursive "$mc_alias/$scratch_bucket" | wc -l)
    echo "   objects: live=$src_objects scratch=$dst_objects in $(( $(now) - obj_start )) s"
    (( dst_objects >= src_objects )) || fail "scratch bucket has fewer objects than the live bucket"
    missing=0
    while IFS= read -r key; do
      [[ -z $key ]] && continue
      mc stat "$mc_alias/$scratch_bucket/$key" >/dev/null 2>&1 || missing=$((missing + 1))
    done < <(psql_dst -c "SELECT object_key FROM edu.documents WHERE status = 'uploaded'
      UNION ALL SELECT object_key FROM edu.export_jobs WHERE status = 'succeeded'")
    echo "   DB-referenced objects missing from the scratch copy: $missing"
    (( missing == 0 )) || fail "database references objects that the restored bucket does not have"
    echo "   scratch bucket $scratch_bucket kept for inspection; remove it deliberately with mc rb --force"
  else
    plan "mc mb --ignore-existing $mc_alias/$scratch_bucket"
    plan "mc mirror --preserve --overwrite $mc_alias/$bucket $mc_alias/$scratch_bucket"
    plan "compare object counts; mc stat every documents/export_jobs object_key from $restore_db"
  fi
else
  step "9. Object storage: skipped (no --mc-alias). Staging has no object store configured yet."
fi

step "10. Measurements (targets TO BE APPROVED: RPO <= 15 min, RTO <= 4 h)"
if (( execute )); then
  echo "   dump taken at:              $(iso "$dump_start")"
  if [[ -n $previous_epoch ]]; then
    echo "   RPO before this drill:      $(( (dump_start - previous_epoch) / 60 )) min (age of newest previous dump)"
  else
    echo "   RPO before this drill:      unbounded (no previous dump)"
  fi
  echo "   RTO (database, measured):   $(( restore_end - restore_start )) s from createdb to verified"
  echo "   checks failed:              $failures"
  echo "   Record these numbers, operator and date in the drill log (deploy/runbooks/restore-drill.md)."
  (( failures == 0 )) || exit 1
else
  echo "   (measured only with --execute)"
fi
