# Plan: Integrate Codex Review into the Tracked Pre-Commit Hook

## Problem Definition
The user wants to integrate the Codex review step (`npx @openai/codex review --uncommitted`) into the repository's pre-commit hook process. 
Although the local untracked `.git/hooks/pre-commit` file already contains this step, the repository-tracked hook source `scripts/pre_commit.sh` does not, resulting in divergence and test failures when the tests assert hook contents.

## Architecture Overview
- Update the repository-tracked script `scripts/pre_commit.sh` to execute the Codex review check (`npx @openai/codex review --uncommitted`) as part of the validation flow.
- Capture Codex review output and fail the hook/commit if any findings (such as "Review comment:" or "[P1]", "[P2]") are detected, ensuring a success status if no findings are found.
- Update the live pre-commit hook `.git/hooks/pre-commit` to delegate to the tracked script.

## Core Data Structures
No runtime data structures are affected.

## Public Interfaces
No public plugin APIs or RPC signatures are affected.

## Dependency Requirements
No new dependencies are required. `npx` and `@openai/codex` must be available on the user system.

## Testing Strategy
- Update `tests/test_protocol.py` to assert that the tracked pre-commit hook `scripts/pre_commit.sh` contains the Codex review step and its findings check.
- Verify the test suite passes locally by running `./run.sh uv run pytest`.

