#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "Verifying Decky frontend supply chain and bundle..."
if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm 10.23.0 is required on PATH before packaging."
  exit 1
fi
pnpm run verify

echo "Creating Decky plugin package..."
./run.sh uv run python scripts/package_plugin.py

if ping -c 1 -W 2 10.168.168.20 >/dev/null 2>&1; then
  echo "Pushing plugin to Steam Deck..."
  scp ./out/SDH-ludusavi.zip deck@10.168.168.20:/home/deck/Downloads/
else
  echo "Steam Deck (10.168.168.20) not reachable, skipping push."
fi
