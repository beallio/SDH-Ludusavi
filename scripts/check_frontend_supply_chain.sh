#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm is required on PATH. Install pnpm 10.23.0 before running frontend checks."
  exit 1
fi

python - <<'PY'
from __future__ import annotations

import json
from pathlib import Path


def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise SystemExit(f"duplicate key in package.json: {key}")
        data[key] = value
    return data


package = json.loads(Path("package.json").read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)
for section in ("dependencies", "devDependencies"):
    for name, specifier in package.get(section, {}).items():
        if not isinstance(specifier, str) or specifier.startswith(("^", "~", ">", "<", "*")):
            raise SystemExit(f"{section}.{name} must use an exact version, got {specifier!r}")
PY

echo "Running pre-install pnpm audit..."
pnpm audit --audit-level high

python scripts/check_pnpm_install_scripts.py pnpm-lock.yaml

echo "Installing frontend dependencies with frozen lockfile and scripts disabled..."
pnpm install --frozen-lockfile --ignore-scripts

echo "Running post-install pnpm audit..."
pnpm audit --audit-level high

if command -v npm >/dev/null 2>&1 && [ -f package-lock.json ]; then
  npm audit signatures
else
  echo "Skipping npm audit signatures: this repo uses pnpm-lock.yaml, not package-lock.json."
fi

if command -v osv-scanner >/dev/null 2>&1; then
  osv-scanner --lockfile pnpm-lock.yaml
else
  echo "Skipping OSV scan: osv-scanner is not installed."
fi

if command -v socket-npm-package-analyzer >/dev/null 2>&1; then
  socket-npm-package-analyzer
else
  echo "Skipping Socket package analyzer: socket-npm-package-analyzer is not installed."
fi

pnpm run typecheck
pnpm run build
pnpm test
