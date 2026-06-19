#!/usr/bin/env bash
set -euo pipefail

export TMPDIR="/tmp/sdh_ludusavi"
mkdir -p "$TMPDIR"

cd "$(git rev-parse --show-toplevel)"


echo "Running protocol checks..."

mapfile -t staged_paths < <(git diff --cached --name-only --diff-filter=ACMR)

./run.sh bash scripts/quality_gates.sh fix || exit 1

if ((${#staged_paths[@]} > 0)); then
  git add -- "${staged_paths[@]}"
fi

./run.sh bash scripts/check_tdd.sh || {
  echo "TDD check failed."
  exit 1
}

echo "Protocol checks passed. Committing..."
