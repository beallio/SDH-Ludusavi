# Fix CI Dev Tag Version

## Problem Definition

After publishing a development prerelease tag such as `v0.2.4-dev.gfcd1780` on the same commit as `main`, the CI workflow can fail during `uv sync` because `hatch-vcs`/`setuptools-scm` attempts to derive the Python package version from a non-PEP-440 tag.

## Architecture Overview

The dev-release workflow already avoids this by setting `SETUPTOOLS_SCM_PRETEND_VERSION` during `uv sync`. The regular CI workflow should do the same, deriving the pretend version from `package.json` so dry-run validation stays aligned with project metadata and does not depend on the nearest VCS tag.

## Core Data Structures

- `package.json` version: source for the CI pretend package version.
- `SETUPTOOLS_SCM_PRETEND_VERSION`: environment override consumed by `setuptools-scm`/`hatch-vcs` during dependency sync.

## Public Interfaces

- `.github/workflows/ci.yml` `Prepare Virtual Environment and Sync Dependencies` step.

## Dependency Requirements

No dependency changes.

## Testing Strategy

- Add a workflow static test requiring CI to run `uv sync` with `SETUPTOOLS_SCM_PRETEND_VERSION` derived from `package.json`.
- Run the focused workflow test, then the standard validation subset for this metadata-only fix.
