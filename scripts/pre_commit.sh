#!/usr/bin/env bash
set -euo pipefail

export TMPDIR="/tmp/sdh_ludusavi"
mkdir -p "$TMPDIR"

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

echo "Running Codex review..."
codex_out=$(mktemp)
codex_exit=0
npx @openai/codex review --uncommitted > "$codex_out" 2>&1 || codex_exit=$?
cat "$codex_out"


if [ $codex_exit -ne 0 ]; then
  echo "❌ Codex review command failed to run successfully! Commit aborted."
  rm -f "$codex_out"
  exit 1
fi

filtered_out=$(awk '/^exec$/ { in_block=1; next } /^(codex|user|assistant|system)$/ { in_block=0; next } !in_block { print }' "$codex_out" || true)

if grep -qE "Review comment:|\[P[0-9]\]" <<< "$filtered_out"; then
  echo "❌ Codex review found findings! Please resolve them before committing."
  rm -f "$codex_out"
  exit 1
fi
rm -f "$codex_out"

echo "Protocol checks passed. Committing..."












