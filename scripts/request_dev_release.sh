#!/usr/bin/env bash
set -euo pipefail

# Helper to request a dev prerelease via GitHub Action workflow run.
# Usage: ./scripts/request_dev_release.sh <base_version> [commit]

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: $0 <base_version> [commit]" >&2
    echo "Example: $0 0.2.1" >&2
    exit 1
fi

BASE_VERSION="$1"
COMMIT="${2:-HEAD}"

# Validate stable base version matches X.Y.Z
if [[ ! "$BASE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Base version '$BASE_VERSION' is not a stable semantic version (X.Y.Z)." >&2
    exit 1
fi

# Check gh auth status
if ! gh auth status >/dev/null 2>&1; then
    echo "Error: You must be authenticated with the GitHub CLI (gh)." >&2
    exit 1
fi

# Resolve commit to full SHA
if ! FULL_SHA=$(git rev-parse --verify "$COMMIT" 2>/dev/null); then
    echo "Error: Cannot resolve commit '$COMMIT' to a valid git commit SHA." >&2
    exit 1
fi

# Refuse if the base version already shipped as a stable tag. A dev prerelease
# vX.Y.Z-dev.SHA targets the upcoming X.Y.Z, so X.Y.Z must not be released yet.
# Uses local tags (best-effort fast feedback); the workflow re-checks against
# origin authoritatively. Run after a fetch/pull for freshness (finalize does).
if [ -n "$(git tag --list "v${BASE_VERSION}" 2>/dev/null)" ]; then
    echo "Error: v${BASE_VERSION} is already a released stable tag. A dev release must target the next unreleased version; bump package.json/plugin.json first." >&2
    exit 1
fi

# Ensure the dev base version is strictly ahead of the highest released stable tag
if ! ./run.sh uv run python scripts/version_guard.py check-base "$BASE_VERSION"; then
    exit 1
fi

echo "Requesting dev release for base version: $BASE_VERSION at commit: $FULL_SHA"
gh workflow run dev-release.yml \
  -f commit="$FULL_SHA" \
  -f base_version="$BASE_VERSION"
