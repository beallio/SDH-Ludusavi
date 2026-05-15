# Plan: Fix post-commit pnpm fallback

## Problem Definition
The post-commit hook aborts after a successful commit when `pnpm` is not
installed directly on `PATH`, even though `npm exec -- pnpm run verify` works in
this environment and successfully runs the existing frontend verification flow.

## Architecture Overview
The tracked `scripts/post_commit.sh` is the source script for local post-commit
behavior, while the currently installed `.git/hooks/post-commit` contains the
same logic. Both should run the same frontend verification command selection:
prefer `pnpm run verify` when `pnpm` is available, otherwise use
`npm exec -- pnpm run verify` when `npm` is available.

## Core Data Structures
No application data structures change. The hook adds a shell helper function
for selecting the frontend verification command.

## Public Interfaces
No runtime plugin API changes. The local hook behavior changes from requiring
`pnpm` directly on `PATH` to accepting npm's package-runner fallback.

## Dependency Requirements
The hook still requires the pinned package manager from `package.json`
(`pnpm@10.23.0`). The fallback uses `npm exec` to resolve pnpm when the direct
binary is absent.

## Testing Strategy
- Update hook tests to assert that post-commit uses an `npm exec -- pnpm`
  fallback and does not contain the old hard failure text.
- Run the focused hook/package tests.
- Run the required project validation commands before commit.

