#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "Building Decky frontend bundle..."
if command -v pnpm >/dev/null 2>&1; then
  pnpm run build
elif [ -x ./node_modules/.bin/rollup ]; then
  ./node_modules/.bin/rollup -c
else
  echo "Neither pnpm nor ./node_modules/.bin/rollup is available. Run pnpm install before packaging."
  exit 1
fi

echo "Creating Decky plugin package..."
./run.sh uv run python scripts/package_plugin.py
