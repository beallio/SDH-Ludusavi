# Release Notes Pipeline

## Problem Definition

`.github/workflows/release.yml` publishes with `softprops/action-gh-release@v3`
without passing `name` or `body`, so GitHub falls back to the bare tag name and
an empty body. Every stable release to date (v0.4.0, v0.4.1, v0.4.2) published
with no notes; v0.4.2 was corrected by hand after the fact.

Release notes should be authored in the repository, reviewed with the change
that motivates them, and published automatically — with a sane fallback so a
release never blocks or publishes blank when notes were not written.

## Architecture Overview

Notes live at `docs/releases/vX.Y.Z.md`, authored during release prep alongside
the version bump. The file's first line is an H1 used as the GitHub release
title; everything after it is the body.

A stdlib-only helper, `scripts/release_notes.py`, resolves the file for a tag
and emits GitHub Actions step outputs:

- notes file present → `title`, `body_path` (a copy staged in the output
  directory), `generate=false`;
- notes file absent → empty `title` and `body_path`, `generate=true`.

`release.yml` gains a "Resolve Release Notes" step before publishing and wires
the outputs into the publish step. `softprops/action-gh-release@v3` treats an
empty `body_path` and empty `name` as unset, so the same step definition covers
both paths: authored notes when present, GitHub's auto-generated notes from
commits and PRs when not. An empty `name` leaves GitHub's tag-name default.

The helper is a Python script rather than inline YAML shell so the behavior is
unit-testable without running the workflow.

## Core Data Structures

None beyond the resolved output mapping:

```
{"title": str, "body_path": str, "generate": "true" | "false"}
```

## Public Interfaces

```
python3 scripts/release_notes.py resolve <tag> [--repo-root DIR] [--out-dir DIR]
```

Writes `key=value` lines to `$GITHUB_OUTPUT` when set, and always echoes them to
stdout for local inspection. Exit codes: `0` resolved (either path), `2` for a
malformed tag.

Tag shape is validated as `vX.Y.Z` before it is used to build a path, so the tag
cannot be used to reach outside `docs/releases/`.

## Dependency Requirements

None. Python standard library only, matching `version_guard.py` and
`set_release_version.py`, so the helper runs before `uv sync` if needed.

## Testing Strategy

`tests/test_release_notes.py` covers the helper:

- present notes file → title from the H1, body file staged without the H1,
  `generate=false`;
- absent notes file → `generate=true`, empty `title`/`body_path`;
- notes file with no H1 → whole file as body, empty title (tag-name default);
- outputs are appended to `$GITHUB_OUTPUT` when the variable is set;
- malformed tags (`0.4.2`, `v1.2`, `v1.2.3-dev.abc`, `../../etc/passwd`) exit
  non-zero and resolve nothing.

`tests/test_release_workflows.py` gains assertions that `release.yml` runs the
resolver before publishing and passes `body_path`, `name`, and
`generate_release_notes` through from its outputs.

Backfilled notes for v0.4.0 and v0.4.1 are committed under `docs/releases/` and
pushed to the existing GitHub releases with `gh release edit`; the tags and
assets are not touched.
