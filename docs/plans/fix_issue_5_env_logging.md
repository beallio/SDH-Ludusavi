# Plan - Fix Issue 5: Environment Variable Logging Security

## Problem Definition
`SDHLudusaviService` logs too many environment variables, potentially disclosing sensitive information.

## Architecture Overview
Implement an allowlist of environment variables to log and redact values that are likely to be paths or secrets.

## Core Data Structures
`_allowed_env_keys = {"LANG", "DECKY_VERSION", "DECKY_PLUGIN_RUNTIME_DIR", "DECKY_PLUGIN_SETTINGS_DIR", "FLATPAK_ID"}`

## Public Interfaces
N/A

## Dependency Requirements
N/A

## Testing Strategy
- New test file: `tests/test_issue_5_env_logging.py`
- Test cases:
    - `os.environ` has `DECKY_SECRET=123`. Verify it's NOT in the log.
    - `os.environ` has `HOME=/home/user`. Verify it's NOT in the log (not in allowlist).
    - `os.environ` has `DECKY_PLUGIN_RUNTIME_DIR=/path`. Verify it is logged as `<set>` or similar redaction.

## Task List
1. Create branch `fix/issue-5-env-logging`.
2. Create `tests/test_issue_5_env_logging.py`.
3. Verify failure (sensitive info logged).
4. Apply fix to `py_modules/sdh_ludusavi/service.py`.
5. Verify fix.
6. Run full suite.
7. Commit.
