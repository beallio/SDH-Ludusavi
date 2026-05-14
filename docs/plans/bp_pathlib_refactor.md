# Plan - Best Practice: Pathlib Refactor

## Problem Definition
`pyludusavi/discovery.py` uses legacy `os.path` and string concatenation for path management. Refactoring to `pathlib.Path` improves readability and maintainability.

## Architecture Overview
Replace `os.path` calls with `pathlib.Path` methods in `discovery.py`.

## Core Data Structures
N/A

## Public Interfaces
N/A

## Dependency Requirements
N/A

## Testing Strategy
- Existing test file: `tests/test_ludusavi_discovery.py`
- Run all tests to ensure no regressions in discovery logic.

## Task List
1. Create branch `refactor/pathlib`.
2. Apply refactor to `py_modules/pyludusavi/discovery.py`.
3. Verify with `tests/test_ludusavi_discovery.py`.
4. Run full suite.
5. Commit.
