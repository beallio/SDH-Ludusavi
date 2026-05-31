# Fix Updater Timing Logs And Stable Install Button Height

## Summary

Fix the two remaining implementation-plan gaps on `fix/updater-logging-spinner-handoff`: update logs must include elapsed timing, and the install button must use a stable content row so loading text/spinner cannot change button height. Preserve the existing update RPCs, Decky handoff behavior, SHA privacy, and validation flow.

## Implementation Changes

### Frontend Updater Logs

- Add elapsed timing to frontend updater logs in `PluginUpdateSection`.
- Use `performance.now()` for frontend timing.
- Include `elapsed_ms` on completion, failure, and pending logs for:
  - update check;
  - revalidation;
  - pending-install save;
  - Decky handoff pending;
  - Decky handoff resolved;
  - Decky handoff rejected.
- Keep `updateTraceId` unchanged.
- Continue logging only SHA-256 prefixes.
- Keep in-flight check reuse logging. Use `elapsed_ms=0` for immediate reuse, or omit `elapsed_ms` only when no timed operation started.

### Decky Installer Adapter Logs

- Add elapsed timing to Decky installer adapter logs in `src/utils/deckyInstaller.ts`.
- Log installer API selection with:
  - `installer_api`;
  - `trace_id`;
  - version;
  - SHA-256 prefix;
  - `elapsed_ms`.
- Do not log full artifact URLs or full SHA-256 values.
- Do not change installer argument order or public adapter behavior.

### Backend Updater Logs

- Add elapsed timing to backend updater logs.
- Use `time.monotonic()` for backend elapsed timing.
- In `main.py::check_for_plugin_update`, include elapsed ms for:
  - cache hit;
  - rate-limit block;
  - returned result.
- In updater backend functions, include elapsed ms for:
  - GitHub fetch result;
  - candidate parsing and selection;
  - failed, current, and available results;
  - revalidation fetch;
  - validation failures;
  - mismatch failures;
  - rate-limit responses;
  - success.
- Preserve the current `_state_lock` split. Do not perform GitHub fetches or manifest validation while holding the lock.
- Keep full SHA-256 values out of all logs.

### Stable Install Button Height

- Define shared inline style constants near `PluginUpdateSection`:
  - install button row: `display: flex`, centered alignment, `gap: "8px"`, `minHeight: "20px"`, `lineHeight: "20px"`;
  - spinner slot: `width: "16px"`, `height: "16px"`, `flex: "0 0 16px"`, `overflow: "hidden"`, centered flex layout.
- Render both loading and non-loading button content through the same stable row wrapper.
- Loading state shows the fixed spinner slot plus `Preparing...` or `Waiting for Decky...`.
- Non-loading state shows the action text in the same stable row wrapper.
- Keep the button disabled while `isChecking || isInstalling`.

## Test Plan

### Frontend Static Tests

Update `tests/test_frontend_static.py` to assert:

- `elapsed_ms` appears in frontend update log details;
- `performance.now()` or equivalent frontend timing is used;
- install button content uses a stable row wrapper with `minHeight` and `lineHeight`;
- loading and non-loading install button states both use the shared content wrapper;
- existing fixed spinner slot, handoff timeout, installer API path logging, and SHA prefix behavior still pass.

### Backend Tests

Update `tests/test_updater_service.py` and/or `tests/test_main.py` to assert:

- backend update-check logs include `elapsed_ms`;
- backend revalidation logs include `elapsed_ms` for success and failure paths;
- cache-hit logs include `elapsed_ms`;
- rate-limit logs include `elapsed_ms`;
- no full SHA-256 value is present in any captured log message.

### Validation Commands

Run:

```bash
./run.sh uv run pytest tests/test_updater.py tests/test_updater_service.py tests/test_main.py tests/test_frontend_static.py
./run.sh uv run pytest
./run.sh uv run ruff check .
./run.sh uv run ruff format --check .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh bash scripts/check_tdd.sh
./run.sh pnpm run verify
git diff --check
```

If `./run.sh pnpm run verify` fails only because sandboxed DNS cannot reach the npm registry for the audit step, rerun it with appropriate network escalation and record that reason in the final report.

## Assumptions

- The existing Decky handoff race behavior is otherwise acceptable and should not be redesigned.
- `elapsed_ms` is the canonical timing field name in both frontend and backend logs.
- A shared row wrapper with explicit `minHeight` and `lineHeight` is sufficient for the static regression guard.
- Final visual confirmation on Deck is still recommended because static tests cannot fully prove Decky UI button height.
