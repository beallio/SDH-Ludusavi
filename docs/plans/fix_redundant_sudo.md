# Plan: Investigate and Fix Redundant Sudo Usage

The user reported that `pyludusavi` uses `sudo -u deck` unnecessarily when the environment already indicates the user is `deck`.

## Problem Definition
`pyludusavi`'s discovery logic in `discovery.py` unconditionally prepends `sudo -u {user}` to the Ludusavi command if a `flatpak_user` is provided. The `SDH-ludusavi` plugin always provides this user (from `DECKY_USER`). If the plugin process is already running as that user, `sudo` is redundant and potentially problematic.

## Architecture Overview
1.  **Investigation**: Log the current UID and Effective UID in `SDHLudusaviService` to confirm the actual execution context.
2.  **Logic Update**: Update `pyludusavi.discovery` to include a check that only applies `sudo` if the current process user differs from the requested `flatpak_user`.

## Implementation Steps
### Phase 1: Investigation
1.  Modify `py_modules/sdh_ludusavi/service.py` to log `os.getuid()`, `os.geteuid()`, and `getpass.getuser()`.

### Phase 2: Refinement of `pyludusavi`
1.  Modify `py_modules/pyludusavi/discovery.py`.
2.  Implement a helper `_should_sudo(target_user: Optional[str]) -> bool`.
3.  Use this helper in `find_ludusavi` and `_flatpak_prefixes` to conditionally add the `sudo` prefix.
4.  (Optional but recommended) Re-apply the improved environment logging at `DEBUG` level.

### Phase 3: Verification
1.  Run tests to ensure no regressions.
2.  Provide the user with a version that logs the UIDs so they can confirm the "WHY".

## Testing Strategy
1.  Unit tests for the new `_should_sudo` logic by mocking `getpass.getuser` or `os.getuid`.
2.  Integration tests (existing ones) to ensure discovery still works.
