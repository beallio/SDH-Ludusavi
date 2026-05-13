# Plan: Fix Sudo Logic with UID Comparison

The logs show that the plugin runs with `uid=1000` but `getpass.getuser()` returns `root` because of `LOGNAME=root`. This causes `pyludusavi` to think it's not the `deck` user and apply `sudo`.

## Problem Definition
`getpass.getuser()` is unreliable in the Decky Loader environment because it trusts environment variables like `LOGNAME` which might be inherited from a parent process (like the systemd service running as root) even after dropping privileges or switching UIDs.

## Architecture Overview
On Unix systems, we should use `os.getuid()` and the `pwd` module to compare the actual process UID with the UID of the target user.

## Implementation Steps
1.  **Modify `py_modules/pyludusavi/discovery.py`**:
    *   Import `pwd`.
    *   Update `_should_sudo(target_user)` to:
        1. Get current UID: `os.getuid()`.
        2. Resolve `target_user` to its UID using `pwd.getpwnam(target_user).pw_uid`.
        3. Return `current_uid != target_uid`.
    *   Add a fallback for non-Unix systems or if `pwd` fails.

2.  **Verify with Tests**:
    *   Update `tests/test_sudo_logic.py` to mock `os.getuid` and `pwd.getpwnam`.

## Testing Strategy
- Mock `os.getuid()` and `pwd.getpwnam()` to simulate different users and UIDs.
- Ensure it handles the case where `target_user` is an invalid username gracefully.
