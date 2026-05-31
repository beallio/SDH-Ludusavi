# Fix Updater Logging, Decky Handoff Visibility, And Install Button Spinner Layout

## Problem Summary

During a GitHub-based plugin upgrade, the update flow is hard to diagnose:

- The plugin logs do not clearly show update check, revalidation, pending install save, Decky installer handoff, startup reconciliation, or unload context.
- After the user selects an available update, the button changes to `Preparing...`, but the spinner is large enough to expand the button height.
- During the update, Decky/plugin UI can appear to hang. The available runtime log shows repeated Decky unload/reload cycles and Decky-owned pending-task warnings, but the plugin does not emit enough updater breadcrumbs to identify whether the pause is plugin-owned or Decky-owned.

Evidence log:

```text
/tmp/sdh_ludusavi/2026-05-31 11.57.05.log
```

Treat Decky Loader lines such as `Task was destroyed but it is pending` as likely Decky shutdown/reload artifacts unless new plugin logs prove otherwise. The plugin's responsibility is to make its update path observable and prevent the frontend from looking stuck while Decky owns the installer prompt.

## Implementation Requirements

### Frontend Update Flow

Update `src/components/PluginUpdateSection.tsx` and `src/utils/deckyInstaller.ts`.

- Add a per-install `updateTraceId`, generated when the user starts an install action.
- Add concise frontend logs through the existing `log(level, message, operation)` RPC path with operation name `update`.
- Log these stages:
  - update check start, in-flight reuse, result, and failure;
  - install clicked;
  - revalidation start, success, and failure;
  - pending install record start, success, and failure;
  - Decky installer handoff start;
  - installer API path selected: `callable` or `call`;
  - installer promise resolved, rejected, or still pending after a short timeout.
- Keep logged data non-sensitive:
  - version;
  - tag;
  - channel;
  - action;
  - status;
  - elapsed milliseconds;
  - installer API path;
  - SHA-256 prefix only, never the full hash.
- Race the Decky installer promise against a short handoff timer, around 3 seconds.
  - If the timer wins, log `installer_handoff_pending`.
  - Change UI copy from `Preparing...` to `Waiting for Decky...` or `Decky prompt opened`.
  - Do not treat this as a failure.
  - If the promise later rejects, log and toast the failure.
- Do not clear pending install metadata from the frontend after Decky handoff starts. Startup reconciliation remains the source of truth.
- Preserve existing update RPC names and return shapes.

### Button Spinner Layout

- Replace the raw update-button `<Spinner size="small" />` with a fixed-size wrapper.
- The wrapper must constrain layout:
  - width and height around `16px`;
  - `flex: 0 0 16px`;
  - `overflow: hidden`;
  - centered content.
- Keep the update button content row at a stable height so the button does not resize between normal and installing states.
- The button must remain disabled while install preparation or Decky handoff is active.

### Backend Logging

Update `main.py`, `py_modules/sdh_ludusavi/updater.py`, and directly related service methods.

- Log update check:
  - start;
  - cache hit;
  - rate-limit cooldown block;
  - GitHub fetch result;
  - candidate count;
  - selected candidate;
  - current/no-update result;
  - failed result.
- Log revalidation:
  - start;
  - cooldown block;
  - release fetch status;
  - validation failure reason;
  - SHA/version/artifact mismatch;
  - success.
- Log pending install save with version, tag, channel, action, and trace id when available.
- Log startup reconciliation in `_main`:
  - no pending update;
  - pending promoted;
  - pending cleared because loaded version did not match.
- Log `_unload` start/end and whether pending update metadata exists.
- Keep network work off the Decky event loop and preserve `_call(...)` offload behavior.
- Do not hold `_state_lock` across GitHub fetches or manifest validation.
- Do not log full SHA-256 values.

### Diagnostic Helpers

- Prefer small local helper functions instead of duplicating formatting:
  - frontend helper such as `logUpdate(traceId, stage, details)`;
  - backend helper for formatting candidate/update context safely.
- Backend helpers must tolerate malformed or missing candidate fields without throwing.
- The frontend `updateTraceId` is diagnostic-only. Backend code must never trust it for validation or release identity.

## Testing Requirements

Follow strict Red-Green-Refactor for behavior-changing work.

### Frontend Static Tests

Update `tests/test_frontend_static.py` to assert:

- update install flow logs major stages;
- update check in-flight reuse is logged;
- Decky installer handoff has bounded pending behavior;
- install button spinner is wrapped in fixed dimensions and cannot resize the button;
- Decky installer adapter reports whether it used `DeckyBackend.callable` or `DeckyBackend.call`;
- full SHA-256 values are not logged.

### Backend Tests

Update `tests/test_updater.py`, `tests/test_updater_service.py`, and `tests/test_main.py` as appropriate to assert:

- update check logs cache hit, rate-limit block, failed fetch, current, and available candidate;
- revalidation logs rate-limit block, fetch failure, validation failure, mismatch failures, and success;
- pending install save logs candidate metadata;
- startup reconciliation logs no-pending, promoted, and cleared states;
- `_unload` logs pending-update context;
- no full SHA-256 is written to logs;
- `_state_lock` is not held across GitHub fetches or manifest validation.

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

## Acceptance Criteria

- Logs are sufficient to reconstruct:
  - update check;
  - revalidation;
  - pending install save;
  - Decky installer handoff;
  - startup reconciliation;
  - unload during pending update.
- Install button height does not change when showing install-progress copy.
- The UI no longer remains indefinitely on `Preparing...` after Decky installer handoff.
- Decky installer handoff failures are logged and surfaced with a toast.
- Full SHA-256 values are never logged.
- All required validation commands pass.
- Required session log and documentation updates from `AGENTS.md` are completed.

## Explicit Non-Goals

- Do not publish releases, push tags, or run release dispatch commands.
- Do not change Decky Loader internals.
- Do not attempt to suppress Decky Loader shutdown warnings unless there is direct evidence they are caused by this plugin.
- Do not add third-party libraries.
- Do not change public update RPC names or return types unless a test proves it is unavoidable.
