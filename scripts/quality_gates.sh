#!/usr/bin/env bash
set -euo pipefail

export TMPDIR="/tmp/sdh_ludusavi"
mkdir -p "$TMPDIR"

cd "$(git rev-parse --show-toplevel)"

MODE="${1:-check}"

if [ "$MODE" = "fix" ]; then
    echo "Running protocol checks (fix mode)..."
    ./run.sh uv run ruff check . --fix || { echo "Ruff linting failed. Fix your code."; exit 1; }
    echo "Formatting code..."
    ./run.sh uv run ruff format .
else
    echo "Running protocol checks (check mode)..."
    ./run.sh uv run ruff check . || { echo "Ruff linting failed."; exit 1; }
    echo "Checking formatting..."
    ./run.sh uv run ruff format --check . || { echo "Ruff formatting check failed."; exit 1; }
fi

echo "Checking types..."
./run.sh uv run ty check py_modules/sdh_ludusavi/ || { echo "Type check failed."; exit 1; }

echo "Running tests..."
./run.sh uv run pytest || { echo "Pytest failed."; exit 1; }

echo "Running frontend supply-chain checks..."
./run.sh pnpm run verify || { echo "Frontend supply-chain checks failed."; exit 1; }

echo "Protocol checks passed."
