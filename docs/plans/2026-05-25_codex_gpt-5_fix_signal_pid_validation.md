# Validate Process Signaling PIDs

Date: 2026-05-25
Planner Model: codex_gpt-5

## Summary

Fix the RPC-exposed process signaling boundary so unsafe PID values never reach
`os.kill`. The current backend coerces with `int(pid)` and then calls
`_send_signal_tree`, which allows special Unix values like `0`, `-1`, and
negative process-group IDs to reach signaling code. The implementation will add
strict backend validation before both pause and resume signaling.

This is a backend hardening fix only. It will not change the public RPC method
names, TypeScript callable definitions, `ProcessSignalResult` type,
process-tree traversal behavior, frontend lifecycle flow, or third-party
dependencies.

## Problem Definition

`SDHLudusaviService.pause_game_process()` and `resume_game_process()` are
reachable through Decky RPC. They currently accept a caller-provided PID, coerce
it with `int()`, and call `_send_signal_tree()`.

Unsafe PID values must be rejected before `_send_signal_tree()`:

- `0`: signals the current process group.
- `-1`: signals all permitted processes.
- Any negative PID: can target a process group.
- `1`: should not be treated as a valid game process root.
- Non-integral or malformed values: must not be truncated or accepted
  accidentally.

The minimum accepted PID is an integer greater than `1`.

## Architecture Overview

Add one module-level helper in `py_modules/sdh_ludusavi/service.py` near the
existing process-signal helpers:

```python
def _coerce_signal_pid(value: object) -> int:
    ...
```

Behavior:

- Accept only integral PID inputs:
  - `int` values, excluding `bool`.
  - String values that parse as integers after whitespace stripping, such as
    `"123"`, `" 123 "`, or `"+123"`.
- Reject:
  - `bool`.
  - floats, including `123.0`, to avoid truncation/coercion ambiguity.
  - strings that are empty or not parseable by `int(cleaned)`.
  - any parsed integer `<= 1`.
  - any parsed integer above `2_147_483_647`, so oversized Python integers do
    not reach `os.kill` and trigger C `pid_t` conversion overflow.
- Raise `ValueError` with a concise user/log-safe message when invalid.
- Return the parsed `int` when valid.

String parsing must use `int(cleaned)` inside `try...except ValueError`, not
`.isdigit()` or `.isdecimal()`. This ensures signed integer strings such as
`"-5"` and `"+1"` are parsed first, then rejected by the same unsafe-PID lower
bound logic as numeric inputs.

Apply the helper at the start of both service methods:

- `pause_game_process(pid)`
  - Validate first.
  - On invalid PID: log a warning under `launch_gate`, return
    `{"status": "failed", "message": "..."}`
  - Do not call `_send_signal_tree`.
  - Do not add anything to `_paused_pids`.
  - Preserve existing behavior for valid PIDs, including the existing
    `"Unable to pause game process"` failure path when `_send_signal_tree`
    returns `False`.
  - Catch `ValueError` locally instead of letting it bubble to `Plugin._call`,
    so invalid caller input is logged as a launch-gate warning without a backend
    exception stack trace.

- `resume_game_process(pid)`
  - Validate first.
  - On invalid PID: log a warning under `launch_gate`, return
    `{"status": "failed", "message": "..."}`
  - Do not call `_send_signal_tree`.
  - Do not mutate `_paused_pids`.
  - Preserve existing best-effort valid-PID behavior: send `SIGCONT`, pop the
    PID from `_paused_pids`, log, and return `{"status": "resumed", "pid": pid}`.
  - Catch `ValueError` locally for the same structured validation response and
    warning-only logging behavior as pause.

Keep `_send_signal_tree()` unchanged for this scoped fix; the reviewed risk is
the RPC-exposed service boundary.

## Core Data Structures

No new persistent data structures are required.

Existing runtime state remains unchanged:

- `_paused_pids: dict[int, float]`
- `_paused_pids_lock`
- watchdog state and cleanup flow

## Public Interfaces

No public API changes.

Existing interfaces remain:

- `Plugin.pause_game_process(pid: int) -> dict[str, object]`
- `Plugin.resume_game_process(pid: int) -> dict[str, object]`
- `SDHLudusaviService.pause_game_process(pid: int) -> dict[str, object]`
- `SDHLudusaviService.resume_game_process(pid: int) -> dict[str, object]`
- frontend `ProcessSignalResult` already permits `"failed"` with optional
  `message`.

Invalid PID responses should use the existing failure-status pattern:

```python
{"status": "failed", "message": "Invalid process PID: must be an integer greater than 1"}
```

Do not include a `pid` key for invalid input because the input may not be a valid
number.

## Dependency Requirements

No new dependencies.

## Implementation Steps

1. Re-check `git status --short --branch`; proceed on the current branch unless
   new unrelated user changes appear.
2. Add failing tests first in `tests/test_service.py`, near the existing process
   signaling tests.
3. Implement `_coerce_signal_pid(value: object) -> int`.
4. Apply it in `pause_game_process()` and `resume_game_process()` before
   `_send_signal_tree()`, catching `ValueError` locally and returning the
   structured failure response.
5. Run targeted tests until green.
6. Run required validation through `./run.sh`.
7. Record a session log in
   `docs/agent_conversations/2026-05-25_fix_signal_pid_validation.json`.
8. Commit with: `fix(backend): reject unsafe process signal pids`

## Testing Strategy

Add red tests before production edits:

- `test_pause_game_process_rejects_invalid_signal_pids`
  - Parametrize `pid` over `0`, `-1`, and `1`.
  - Monkeypatch `_send_signal_tree` to record calls.
  - Assert result status is `"failed"`.
  - Assert `_send_signal_tree` was not called.
  - Assert `_paused_pids` remains empty.

- `test_resume_game_process_rejects_invalid_signal_pids`
  - Parametrize `pid` over `0`, `-1`, and `1`.
  - Monkeypatch `_send_signal_tree` to record calls.
  - Assert result status is `"failed"`.
  - Assert `_send_signal_tree` was not called.
  - Assert `_paused_pids` was not mutated.

- `test_coerce_signal_pid_rejects_non_integral_values`
  - Cover representative malformed inputs: `True`, `False`, `2.5`, `"2.5"`,
    `""`, `"   "`, `"abc"`, `"-5"`, `"+1"`, and `2_147_483_648`.
  - Assert `ValueError`.

- `test_coerce_signal_pid_accepts_valid_integer_strings`
  - Cover representative valid inputs: `2`, `"2"`, `" 2 "`, `"+2"`, and
    `2_147_483_647`.
  - Assert the helper returns the parsed integer.

- `test_signal_process_methods_reject_pid_above_os_signal_range`
  - Call both pause and resume with `"2147483648"`.
  - Assert both return failure status and do not call `_send_signal_tree`.

Existing tests must still prove valid behavior:

- `pause_game_process(100)` still signals the process tree with `SIGSTOP`.
- `resume_game_process(100)` still signals the process tree with `SIGCONT`.
- watchdog and `resume_all_paused_processes()` behavior remains unchanged for
  valid stored PIDs.

Validation commands:

```bash
./run.sh uv run pytest tests/test_service.py::test_pause_game_process_rejects_invalid_signal_pids
./run.sh uv run pytest tests/test_service.py::test_resume_game_process_rejects_invalid_signal_pids
./run.sh uv run pytest tests/test_service.py
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```

If unrelated uncommitted user changes appear before formatting, pause before
broad formatting rather than rewriting user-owned files.

## Acceptance Criteria

- PIDs `0`, `-1`, and `1` return failure status from both pause and resume
  methods.
- PIDs greater than `2_147_483_647` return failure status before signaling.
- Invalid PIDs never call `_send_signal_tree()` or `os.kill()`.
- Valid PID behavior remains unchanged.
- No public RPC/type/API shape changes.
- No new dependencies.
- README unchanged because this is internal safety hardening, not user-facing
  usage behavior.
- Session log recorded after implementation.
- Required validation passes through `./run.sh`.

## Assumptions

- This fix intentionally addresses unsafe special/non-positive PID values at the
  backend RPC boundary.
- This fix does not attempt to prove that every positive PID belongs to the
  launched game; that would require a broader provenance/ownership design.
- The implementation should remain in first-party `SDH-ludusavi` code and tests
  only; do not modify vendored/upstream packages.
