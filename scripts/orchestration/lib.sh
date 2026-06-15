#!/usr/bin/env bash

set -euo pipefail

die() {
  echo "error: $*" >&2
  exit 1
}

repo_root() {
  git rev-parse --show-toplevel 2>/dev/null || die "not inside a git repository"
}

require_slug() {
  local slug="${1:-}"

  [[ -n "$slug" ]] || die "missing slug"
  [[ "$slug" =~ ^[a-z0-9][a-z0-9._-]*$ ]] || die "invalid slug: $slug"
}

tmp_root() {
  echo "${ORCH_TMP_ROOT:-/tmp/sdh_ludusavi}"
}

finished_marker() {
  local slug="$1"

  require_slug "$slug"
  echo "$(tmp_root)/${slug}_finished"
}

finalized_marker() {
  local slug="$1"

  require_slug "$slug"
  echo "$(tmp_root)/${slug}_finalized"
}

current_branch() {
  git branch --show-current
}

ensure_dirs() {
  local root

  root="$(repo_root)"

  mkdir -p \
    "$root/docs/plans" \
    "$root/docs/review" \
    "$root/docs/agent_conversations" \
    "$(tmp_root)"
}

worktree_clean() {
  [[ -z "$(git status --porcelain)" ]]
}

require_clean_worktree() {
  if ! worktree_clean; then
    git status --short >&2
    die "working tree is not clean"
  fi
}

latest_review_file() {
  local slug="$1"

  require_slug "$slug"

  shopt -s nullglob
  local files=(docs/review/"${slug}"-review-*.md)
  shopt -u nullglob

  if (( ${#files[@]} == 0 )); then
    return 1
  fi

  printf '%s\n' "${files[@]}" | sort | tail -n 1
}

latest_plan_file() {
  local slug="$1"

  require_slug "$slug"

  shopt -s nullglob
  local files=(docs/plans/*_"${slug}".md docs/plans/"${slug}".md)
  shopt -u nullglob

  if (( ${#files[@]} == 0 )); then
    return 1
  fi

  printf '%s\n' "${files[@]}" | sort | tail -n 1
}

tmux_session_name() {
  local slug="${1:-}"
  local root
  local repo_name

  root="$(repo_root)"
  repo_name="$(basename "$root")"

  if [[ -n "$slug" ]]; then
    require_slug "$slug"
    echo "${ORCH_TMUX_SESSION:-implementer-${slug}}"
  else
    echo "${ORCH_TMUX_SESSION:-implementer-${repo_name}}"
  fi
}
