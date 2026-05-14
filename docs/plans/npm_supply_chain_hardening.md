# NPM Supply Chain Hardening

## Problem Definition

The frontend dependency setup has duplicate `dependencies`, semver ranges, a large vulnerable
dev graph, and no enforced frontend audit gate. The project uses `pnpm-lock.yaml`, so hardening
must keep pnpm as the canonical lockfile while translating npm-specific requested checks to pnpm
equivalents.

## Architecture Overview

Keep `package.json` and `pnpm-lock.yaml` as the tracked dependency contract. Add project-level
npm/pnpm policy files, add a supply-chain verification script, and keep local `node_modules`
outside Dropbox under `/tmp/sdh_ludusavi`.

## Core Data Structures

- `package.json`: exact direct dependency pins and frontend verification scripts.
- `.npmrc`: npm-compatible security defaults such as `save-exact`, `audit`, and `ignore-scripts`.
- `pnpm-workspace.yaml`: pnpm-specific install policy, minimum release age, cache/module paths,
  and transitive overrides.
- `pnpm-lock.yaml`: canonical lockfile inspected for build-script requirements.

## Public Interfaces

- `pnpm run verify`: runs frontend supply-chain checks, typecheck, build, and test.
- `scripts/check_frontend_supply_chain.sh`: shell entrypoint for CI/local verification.
- `scripts/check_pnpm_install_scripts.py`: fails when the lockfile contains non-allowlisted
  packages with `requiresBuild: true`.

## Dependency Requirements

No new Python runtime dependency is required. The frontend remains pnpm-based. `osv-scanner` and
`socket-npm-package-analyzer` are optional external scanners: the verification script reports when
they are unavailable instead of downloading them implicitly.

## Testing Strategy

Add Python tests that validate the package manifest, `.npmrc`, pnpm workspace settings, supply-chain
scripts, and lockfile build-script detection. Then regenerate the lockfile and run the existing
Python and frontend validation gates.
