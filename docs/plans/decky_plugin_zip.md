# Decky Plugin Zip Plan

## Problem Definition

Create a post-commit packaging step that writes a Decky plugin zip named after the
project and includes only runtime files required by Decky Loader.

## Architecture Overview

- `scripts/package_plugin.py` owns the exact allowlist of plugin runtime files.
- `scripts/post_commit.sh` rebuilds the frontend bundle and calls the packager.
- The local `.git/hooks/post-commit` delegates to `scripts/post_commit.sh`.
- The generated archive is written to ignored path `out/SDH-ludusavi.zip`.

## Core Data Structures

- `REQUIRED_FILES`: root files required by Decky runtime.
- `REQUIRED_DIRECTORIES`: Python backend and vendored runtime dependency folders.

## Public Interfaces

No plugin RPC or UI interfaces change.

## Dependency Requirements

No new dependencies. The packager uses Python's standard `zipfile` module.

## Testing Strategy

- Add tests that run the packager into a temporary output directory.
- Assert the archive filename is `SDH-ludusavi.zip`.
- Assert the archive contents exactly match the allowlist and exclude docs, tests,
  source files, node modules, and source maps.
- Run the post-commit packaging script before committing.
