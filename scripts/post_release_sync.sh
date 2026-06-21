#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root so stdlib-only helper scripts (and the `scripts`
# namespace package) resolve regardless of where this script is invoked from.
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$ROOT" ] && cd "$ROOT"

# Pure-Python helpers below (version_guard, set_release_version) are stdlib-only and
# are invoked with `python3` directly, NOT via `./run.sh`: `./run.sh` prints an
# environment preamble to stdout that would pollute command substitutions like NEXT.
# Only the quality gates (which need the project venv) go through `./run.sh`.

# 1. Determine stable version and next patch
if [ $# -ge 1 ]; then
    RELEASED_TAG="$1"
    if [[ ! "$RELEASED_TAG" =~ ^v ]]; then
        RELEASED_TAG="v$RELEASED_TAG"
    fi
else
    RELEASED_TAG=$(git tag -l 'v*' | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n1 || true)
    if [ -z "$RELEASED_TAG" ]; then
        echo "Error: No stable release tags found." >&2
        exit 1
    fi
fi

NEXT=$(python3 scripts/version_guard.py next-patch "${RELEASED_TAG#v}")

# 2. Require a clean working tree
if ! git diff-index --quiet HEAD --; then
    echo "Error: Working tree is dirty. Please commit or stash changes." >&2
    exit 1
fi

git checkout dev
git pull --ff-only origin dev
git fetch origin main:main || true

# Check if dev already contains main
CONTAINS_MAIN=false
if git merge-base --is-ancestor origin/main dev; then
    CONTAINS_MAIN=true
fi

# Get current dev version
DEV_VER=$(grep -o '"version": "[^"]*"' package.json | head -n1 | cut -d'"' -f4)
IS_AHEAD_OR_EQUAL=$(python3 -c "from scripts.version_guard import parse_semver; print('true' if parse_semver('$DEV_VER') >= parse_semver('$NEXT') else 'false')")

# 4. No-op guard
if [ "$CONTAINS_MAIN" = "true" ] && [ "$IS_AHEAD_OR_EQUAL" = "true" ]; then
    echo "already synced"
    exit 0
fi

# 3. Merge main if needed
if [ "$CONTAINS_MAIN" = "false" ]; then
    echo "Merging origin/main into dev..."
    if ! GIT_EDITOR=true git merge --no-ff origin/main -m "chore(release): merge main into dev for post-release sync"; then
        echo "Error: Merge conflict detected." >&2
        echo "Please resolve conflicts manually, commit, and re-run this script." >&2
        exit 1
    fi
fi

# 5. Bump dev to the next patch
echo "Bumping dev to $NEXT..."
python3 scripts/set_release_version.py "$NEXT"

# 6. Run quality gates
echo "Running quality gates..."
if ! ./run.sh bash scripts/quality_gates.sh check; then
    echo "Error: Quality gates failed." >&2
    exit 1
fi

# 7. Commit
git add package.json plugin.json
if ! git diff --cached --quiet; then
    git commit -m "chore(release): bump dev to $NEXT after $RELEASED_TAG"
fi

# 8. Push dev
echo "Pushing dev..."
git push origin dev

echo "Sync complete."
