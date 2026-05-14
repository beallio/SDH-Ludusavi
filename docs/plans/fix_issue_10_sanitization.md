# Plan - Fix Issue 10: Input Sanitization for Game Names

## Problem Definition
`SDHLudusaviService` does not sanitize game names provided by the frontend, which could lead to log spoofing or UI issues if names contain control characters or newlines.

## Architecture Overview
Implement `_sanitize_name(name: str) -> str` and apply it to all public service methods that accept a game name.

## Core Data Structures
N/A

## Public Interfaces
- `backup(game_name, ...)`
- `restore(game_name, ...)`
- `set_selected_game(game_name)`
- `_match_game(game_name)`

## Dependency Requirements
N/A

## Testing Strategy
- New test file: `tests/test_issue_10_sanitization.py`
- Test cases:
    - `Hades\n[ERROR] Spoof` should be sanitized to `Hades [ERROR] Spoof` or similar.
    - Verify that sanitized name is used in logs.

## Task List
1. Create branch `fix/issue-10-sanitization`.
2. Create `tests/test_issue_10_sanitization.py`.
3. Verify failure.
4. Apply fix to `py_modules/sdh_ludusavi/service.py`.
5. Verify fix.
6. Run full suite.
7. Commit.
