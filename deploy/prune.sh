#!/usr/bin/env bash
# Remove old staging releases, their image tags and uploaded archives.
# Dry-run by default. Never removes the release named in shared/current-release.
# Scope: only this project's release directory and images labelled by this project.
set -Eeuo pipefail
umask 077

keep=${1:-3}
mode=${2:-}
[[ $keep =~ ^[1-9][0-9]?$ ]] || {
  echo 'Usage: bash deploy/prune.sh [keep-count=3] [--apply]' >&2
  exit 2
}
[[ -z $mode || $mode == --apply ]] || {
  echo "Unknown option: $mode (expected --apply or nothing)" >&2
  exit 2
}

root=${EDUVIA_ROOT:-$HOME/eduvia-staging}
releases=$root/releases
incoming=$root/incoming
[[ -d $releases ]] || { echo "No releases directory at $releases" >&2; exit 2; }

active=''
[[ -f $root/shared/current-release ]] && active=$(<"$root/shared/current-release")
active=${active//[[:space:]]/}

# Newest first by directory mtime; the active release is always protected.
mapfile -t all < <(ls -1t -- "$releases")
protected=()
removable=()
count=0
for sha in "${all[@]}"; do
  [[ $sha =~ ^[0-9a-f]{40}$ ]] || continue
  [[ -d $releases/$sha ]] || continue
  if [[ -n $active && $sha == "$active" ]]; then
    protected+=("$sha")
    continue
  fi
  count=$((count + 1))
  if (( count < keep )); then
    protected+=("$sha")
  else
    removable+=("$sha")
  fi
done

if (( ${#removable[@]} == 0 )); then
  echo "Nothing to prune: keeping ${#protected[@]} release(s), limit $keep (active ${active:-none})."
  exit 0
fi

echo "Keeping ${#protected[@]} release(s); active: ${active:-none}"
for sha in "${removable[@]}"; do
  echo "remove release $sha"
  echo "  rm -rf releases/$sha"
  [[ -f $incoming/$sha.tar.gz ]] && echo "  rm -f incoming/$sha.tar.gz"
  echo "  docker image rm eduvia-staging-backend:$sha eduvia-staging-frontend:$sha"
done

if [[ $mode != --apply ]]; then
  echo 'Dry run only. Re-run with --apply to delete the items above.'
  exit 0
fi

for sha in "${removable[@]}"; do
  # Refuse to delete an image still referenced by a running container.
  if docker ps -q --filter "ancestor=eduvia-staging-backend:$sha" | grep -q .; then
    echo "skip $sha: still in use by a running container" >&2
    continue
  fi
  rm -rf -- "${releases:?}/$sha"
  rm -f -- "$incoming/$sha.tar.gz"
  docker image rm --no-prune "eduvia-staging-backend:$sha" "eduvia-staging-frontend:$sha" >/dev/null 2>&1 || true
  echo "removed $sha"
done

echo 'Done. Build cache is separate: docker builder prune --filter until=168h (affects all projects on this host).'
