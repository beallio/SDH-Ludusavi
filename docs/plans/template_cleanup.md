# Template Cleanup Plan

## Problem Definition

Remove template-only files from the SDH-ludusavi repository and align the backend
Python package location with Decky Loader runtime import behavior.

## Architecture Overview

- Keep Decky-required root files: `plugin.json`, `package.json`, `main.py`,
  `LICENSE`, Rollup/TypeScript config, and frontend source.
- Keep generated `dist/` ignored and produced by `pnpm run build`.
- Move backend runtime modules from `src/sdh_ludusavi` to `py_modules/sdh_ludusavi`
  because Decky Loader appends plugin `py_modules` to Python import paths.
- Vendor the pure-Python `pyludusavi` runtime dependency into `py_modules/pyludusavi`
  so the installed plugin does not depend on `uv sync`.
- Keep Python project tooling for local tests and type checks, but point it at
  the first-party backend package.

## Core Data Structures

No runtime data structures change. This is a repository layout cleanup only.

## Public Interfaces

No Decky RPC method names change.

## Dependency Requirements

No new dependencies. Existing Python dependency metadata continues to declare
`pyludusavi`.

## Testing Strategy

- Add static tests for Decky-required files and runtime backend import location.
- Add static tests for vendored Python runtime dependency availability.
- Add static tests proving removed template-only directories are absent.
- Run Python checks and frontend build after cleanup.
