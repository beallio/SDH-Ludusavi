# Fix Pre-Commit Staging Scope

## Problem Definition

The pre-commit hook used `git add -u` after Ruff formatting. That command stages every
tracked modification and deletion in the working tree, even when the user intentionally
left those changes out of the commit.

## Architecture Overview

Capture the set of already-staged added, copied, modified, or renamed paths before
running Ruff. After formatting, restage only those captured paths. Leave unstaged
tracked edits and deletions untouched.

## Core Data Structures

- `staged_paths`: shell array populated from
  `git diff --cached --name-only --diff-filter=ACMR`.

## Public Interfaces

- `scripts/pre_commit.sh`
- `.git/hooks/pre-commit`

## Dependency Requirements

No dependency changes are required.

## Testing Strategy

- Update `tests/test_protocol.py` to reject broad `git add -u` hook behavior.
- Run the focused protocol test.
- Run the live `.git/hooks/pre-commit` against a staged set while unrelated working
  tree changes exist, and confirm the hook does not stage those unrelated changes.
