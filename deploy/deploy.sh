#!/usr/bin/env bash
# Ubuntu/Linux deployment; invoke with bash, no sudo required.
set -Eeuo pipefail
umask 077
[[ $# == 2 ]] || { echo 'Usage: bash deploy/deploy.sh /absolute/releases/<full-sha> /absolute/shared/staging.env' >&2; exit 2; }
release=$(realpath -e -- "$1")
env_file=$(realpath -e -- "$2")
sha=$(basename -- "$release")
[[ $sha =~ ^[0-9a-f]{40}$ ]] || { echo 'Release directory must be named with the full 40-character commit SHA' >&2; exit 2; }
[[ -d $release && -f $env_file && $env_file != "$release/"* ]] || { echo 'Use an existing release and an external shared env file' >&2; exit 2; }
[[ $(stat -c '%a' "$env_file") == 600 && -O $env_file ]] || { echo 'Env file must be owned by the deploy user, mode 600' >&2; exit 2; }
for tool in docker flock python3 curl; do command -v "$tool" >/dev/null; done
# Every release shares this lock; all deployment actors must use this script/env path.
exec 9>"$(dirname "$env_file")/deploy.lock"
flock -x -w 900 9 || { echo 'Another staging deployment holds the lock' >&2; exit 1; }
cd -- "$release"
# For git worktrees verify both provenance and cleanliness. Tar releases rely on
# authenticated CI transport of a git archive for this exact SHA; never edit in place.
if [[ -e .git ]]; then
  [[ $(git rev-parse HEAD) == "$sha" && -z $(git status --porcelain) ]] || { echo 'Release checkout must be clean and match its SHA' >&2; exit 2; }
fi
compose() {
  # Do not let shell variables or an ambient .env override the explicit env file.
  env -i PATH="$PATH" HOME="$HOME" RELEASE_SHA="$sha" \
    docker compose --project-name eduvia-staging --project-directory "$release" \
    --env-file "$env_file" -f "$release/compose.staging.yaml" "$@"
}
# Configuration validation emits neither resolved secrets nor connection URLs.
compose config --format json | python3 "$release/deploy/validate-config.py"
compose build api frontend
compose up -d --wait --wait-timeout 180 db redis
# Serialize the full rollout, not just migrations. Stop old application consumers
# before schema changes; this is deliberately a maintenance-window deployment.
compose stop frontend api worker
trap 'echo "Deployment failed; no volumes or images were deleted. Inspect staging logs and schema before retrying; no automatic rollback was attempted." >&2' ERR
compose run --rm --no-deps migrate
compose up -d --no-build --wait --wait-timeout 240 api worker frontend
curl --fail --silent --show-error --max-time 15 http://127.0.0.1:3100/ >/dev/null
printf 'Staging release %s is healthy on http://127.0.0.1:3100\n' "$sha"
# No down, prune, volume removal, schema downgrade, or cleanup of other projects.
