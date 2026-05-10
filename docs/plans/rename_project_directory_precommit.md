# Rename Project Directory And Pre-Commit Hook Plan

## Problem Definition

Rename the local checkout directory from `decky-plugin-template` to the project
name `SDH-ludusavi`, then update the local pre-commit hook before committing.

## Architecture Overview

- Keep the repository contents unchanged by the filesystem directory rename.
- Store the pre-commit check body in `scripts/pre_commit.sh` so the hook behavior is
  tracked.
- Make `.git/hooks/pre-commit` delegate to the tracked script.

## Core Data Structures

No runtime data structures change.

## Public Interfaces

No plugin RPC or frontend interface changes.

## Dependency Requirements

No dependency changes.

## Testing Strategy

- Run the updated `.git/hooks/pre-commit`.
- Verify Git status from `/home/beallio/Dropbox/Scripts/SDH-ludusavi`.
