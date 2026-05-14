# Plan - Fix Issue 1: Fuzzy Substring Game Matching

## Problem Definition
The fuzzy substring guard in `SDHLudusaviService._match_game` is too permissive. It uses `or` instead of `and` for length checks, allowing very short strings (like "A") to match long titles (like "A Game") if the target title length > 4.

## Architecture Overview
This is a surgical fix in `py_modules/sdh_ludusavi/service.py`.

## Core Data Structures
N/A

## Public Interfaces
N/A

## Dependency Requirements
N/A

## Testing Strategy
- New test file: `tests/test_issue_1_matching.py`
- Test cases:
    - "A" should NOT match "A Game" (substring match but "A" is too short).
    - "Portal" SHOULD match "Portal 2" (both > 4 chars).
    - "Game" should NOT match "Game of Thrones" (4 chars <= 4 chars limit).

## Task List
1. Create branch `fix/issue-1-matching`.
2. Create `tests/test_issue_1_matching.py` with failing cases.
3. Verify failure with `./run.sh uv run pytest tests/test_issue_1_matching.py`.
4. Apply fix to `py_modules/sdh_ludusavi/service.py`.
5. Verify fix with `./run.sh uv run pytest tests/test_issue_1_matching.py`.
6. Run full test suite.
7. Commit changes.
