# Decky Plugin Zip Plan

## Problem Definition

Create a post-commit packaging step that writes a Decky plugin zip named after the
project and includes only runtime files required by Decky Loader.

## Architecture Overview

- `scripts/package_plugin.py` owns the exact allowlist of plugin runtime files and
  generated runtime directories.
- `scripts/post_commit.sh` rebuilds the frontend bundle and calls the packager.
- The local `.git/hooks/post-commit` delegates to `scripts/post_commit.sh`.
- The generated archive is written to ignored path `out/SDH-ludusavi.zip` and contains a top-level `SDH-ludusavi/` plugin directory.
- The generated `dist/` directory is packaged as a runtime directory so
  `dist/index.js`, its source map, and any future built assets stay together.

## Core Data Structures

- `REQUIRED_FILES`: root files required by Decky runtime.
- `REQUIRED_RUNTIME_FILES`: required files that prove a generated runtime directory
  is usable, such as `dist/index.js`.
- `REQUIRED_DIRECTORIES`: generated frontend output, Python backend, and vendored
  runtime dependency folders.

## Public Interfaces

No plugin RPC or UI interfaces change.

## Dependency Requirements

No new dependencies. The packager uses Python's standard `zipfile` module.

## Testing Strategy

- Add tests that run the packager into a temporary output directory.
- Assert the archive filename is `SDH-ludusavi.zip`.
- Assert the archive contents exactly match the allowlist and exclude docs, tests,
  TypeScript source files, and node modules.
- Assert `dist/index.js.map` is included when `dist/index.js` references it.
- Run the post-commit packaging script before committing.
