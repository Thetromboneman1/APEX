#!/usr/bin/env bash
set -euo pipefail

require_sha() {
  local name=$1 value=$2
  if [[ ! "$value" =~ ^[0-9a-f]{40}$ ]]; then
    echo "::error::${name} is not a full lowercase commit ID"
    exit 1
  fi
}

require_sha BASE_SHA "$BASE_SHA"
require_sha UPSTREAM_SHA "$UPSTREAM_SHA"
require_sha EXPECTED_TREE "$EXPECTED_TREE"

branch="automation/upstream-sync-${BASE_SHA:0:12}-${UPSTREAM_SHA:0:12}"
remote_head=""

load_and_verify_remote_candidate() {
  git fetch --no-tags origin "refs/heads/$branch"
  remote_head=$(git rev-parse FETCH_HEAD)
  test "$(git rev-parse "$remote_head^{tree}")" = "$EXPECTED_TREE"
  if [[ "$remote_head" == "$UPSTREAM_SHA" ]]; then
    git merge-base --is-ancestor "$BASE_SHA" "$remote_head"
  else
    test "$(git rev-parse "$remote_head^1")" = "$BASE_SHA"
    test "$(git rev-parse "$remote_head^2")" = "$UPSTREAM_SHA"
    if git rev-parse --verify --quiet "$remote_head^3" >/dev/null; then
      echo "::error::Existing sync candidate has unexpected additional parents"
      exit 1
    fi
  fi
}

find_open_pr() {
  gh pr list --head "$branch" --base "$DOWNSTREAM_BRANCH" --state open \
    --json url,baseRefOid,headRefOid \
    --jq '.[0] // empty | [.url, .baseRefOid, .headRefOid] | @tsv'
}

verify_pr_record() {
  local record=$1 url pr_base pr_head
  IFS=$'\t' read -r url pr_base pr_head <<< "$record"
  if [[ -z "$url" || "$pr_base" != "$BASE_SHA" || "$pr_head" != "$remote_head" ]]; then
    echo "::error::Existing sync pull request does not match the validated candidate"
    return 1
  fi
  printf '%s\n' "$url"
}

if git ls-remote --exit-code origin "refs/heads/$branch" >/dev/null 2>&1; then
  load_and_verify_remote_candidate
else
  if ! git push --set-upstream origin "HEAD:refs/heads/$branch"; then
    # A serialized rerun or another publisher may have won the branch race.
    if ! git ls-remote --exit-code origin "refs/heads/$branch" >/dev/null 2>&1; then
      echo "::error::Failed to publish the validated sync candidate"
      exit 1
    fi
  fi
  load_and_verify_remote_candidate
fi

record=$(find_open_pr)
if [[ -n "$record" ]]; then
  if ! verify_pr_record "$record"; then
    exit 1
  fi
  exit 0
fi

if ! url=$(gh pr create --head "$branch" --base "$DOWNSTREAM_BRANCH" \
  --title "chore: sync lowiqentity/APEX main" \
  --body "Merges \`${UPSTREAM_REPOSITORY}@${UPSTREAM_SHA}\` through the downstream validation contract. Validated base: \`${BASE_SHA}\`."); then
  # Treat only discovery of an exact concurrently-created PR as recovery.
  record=$(find_open_pr)
  if [[ -z "$record" ]]; then
    echo "::error::Failed to create or discover the sync pull request"
    exit 1
  fi
  if ! verify_pr_record "$record"; then
    exit 1
  fi
  exit 0
fi

record=$(gh pr view "$url" --json url,baseRefOid,headRefOid \
  --jq '[.url, .baseRefOid, .headRefOid] | @tsv')
if ! verify_pr_record "$record"; then
  gh pr close "$url" --comment \
    "Closed automatically because the pull request no longer matches the validated base and candidate head."
  exit 1
fi
