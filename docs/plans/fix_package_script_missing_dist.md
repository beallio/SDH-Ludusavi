# Fix Package Script Missing Dist

## Problem Definition

`scripts/package_plugin.py` fails when `dist/index.js` is absent. This can happen
during validation if a frontend build is running at the same time as pytest, because
Rollup can clear `dist/` before recreating the bundle.

## Architecture Overview

Keep `dist/index.js` as a required runtime artifact, but make the packaging script
able to rebuild the frontend bundle when a required runtime file is missing. Static
metadata files should still fail fast if absent.

## Core Data Structures

- `REQUIRED_RUNTIME_FILES`: runtime bundle files that may be regenerated.
- `ensure_required_files`: validates static files first, rebuilds the frontend only
  when runtime files are missing, then validates again.

## Public Interfaces

No package CLI argument changes. `scripts/package_plugin.py` continues to create the
same Decky zip, but it can recover from a missing frontend bundle.

## Dependency Requirements

No dependency changes. The script uses the existing `pnpm run build` command.

## Testing Strategy

1. Add a failing test that removes `dist/index.js` in a temporary project and expects
   the package script to call the frontend build helper.
2. Implement the rebuild helper and validation flow.
3. Run targeted package tests and the full validation suite.
