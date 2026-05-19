#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "Running protocol checks..."

mapfile -t staged_paths < <(git diff --cached --name-only --diff-filter=ACMR)

./run.sh uv run ruff check . --fix || {
  echo "Ruff linting failed. Fix your code."
  exit 1
}

echo "Formatting code..."
./run.sh uv run ruff format .

if ((${#staged_paths[@]} > 0)); then
  git add -- "${staged_paths[@]}"
fi

echo "Checking types..."
./run.sh uv run ty check py_modules/sdh_ludusavi/ || {
  echo "Type check failed."
  exit 1
}

echo "Running tests..."
./run.sh uv run pytest || {
  echo "Pytest failed. Commit aborted."
  exit 1
}

echo "Running frontend supply-chain checks..."
pnpm run verify || {
  echo "Frontend supply-chain checks failed."
  exit 1
}

./run.sh bash scripts/check_tdd.sh || {
  echo "TDD check failed."
  exit 1
}

echo "Protocol checks passed. Committing..."
