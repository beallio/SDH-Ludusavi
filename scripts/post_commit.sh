#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

run_frontend_verify() {
  if command -v pnpm >/dev/null 2>&1; then
    pnpm run verify
    return
  fi

  if command -v npm >/dev/null 2>&1; then
    npm exec -- pnpm run verify
    return
  fi

  echo "pnpm or npm is required before packaging."
  exit 1
}

echo "Verifying Decky frontend supply chain and bundle..."
run_frontend_verify

echo "Creating Decky plugin package..."
./run.sh uv run python scripts/package_plugin.py

if ssh -q -o BatchMode=yes -o ConnectTimeout=2 steamdeck exit >/dev/null 2>&1; then
  echo "Pushing plugin to Steam Deck..."
  scp ./out/SDH-Ludusavi.zip steamdeck:/home/deck/Downloads/
else
  echo "Steam Deck not reachable, skipping push."
fi
