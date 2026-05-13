# Plan: Fix Redundant Sudo and Refine Logging

## Problem Definition
1.  **Redundant Sudo**: `pyludusavi` uses `sudo -u {user}` even if the current process is already running as that user.
2.  **Double Logging**: Logs are appearing twice in Decky Loader because of propagation.
3.  **Noisy Logs**: Environment logging is too verbose (all variables) and at `INFO` level.

## Architecture Overview
- **Identity Check**: Introduce a helper in `pyludusavi.discovery` to determine if `sudo` is necessary based on the current user.
- **Log Propagation**: Disable propagation for plugin loggers in the Decky environment.
- **Environment Logging**: Refine load-time logging to be `DEBUG` level and filtered.

## Phased Approach
### Phase 1: Infrastructure & Identity Logging
- Task: Add diagnostic logging to `sdh_ludusavi/service.py` to show current UID/EUID and user name.
- Verification: Check logs in Decky Loader.

### Phase 2: Core Logic (pyludusavi)
- Task: Implement `_should_sudo(target_user)` in `pyludusavi/discovery.py`.
- Task: Update `find_ludusavi` and `_flatpak_prefixes` to use `_should_sudo`.
- Verification: Unit tests mocking `getpass.getuser` or `os.getuid`.

### Phase 3: Logging Refinement
- Task: Update `pyludusavi/__init__.py` to use `DEBUG` level and filtered environment keys.
- Task: Update `sdh_ludusavi/service.py` to conditionally disable propagation.
- Verification: Check logs for conciseness and lack of duplicates.

### Phase 4: Final Validation
- Task: Run full test suite.
- Task: Run ruff/ty checks.

## Git Strategy
- Branch: `fix/redundant-sudo-and-logging`
- Commits: Atomic commits for each phase.

## Testing Strategy
- Mocking process identity in `tests/test_ludusavi_discovery.py` or new `tests/test_sudo_logic.py`.
- verifying log levels and content in `tests/test_pyludusavi_logging.py`.
