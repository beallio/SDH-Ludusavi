# Review — autosync-handoff-and-logging (round 02)

Branch: `feat/autosync-handoff-and-logging`
Reviewed against: `docs/plans/2026-06-18_autosync-handoff-and-logging.md`

## Verdict

The round-01 changes are correctly applied: `debug_logging` now defaults to ON (True) across
all backend and frontend defaults and test fixtures (`main.py`, `service.py` `__init__` and
`_load_state`, `defaultSettings`, `normalizeSettings`, `settingsMutationRuntime` fallback,
`startupHydration.test.ts`, `tests/test_service.py`), and the unused `LudusaviSettings`
interface is removed. Workstreams A and B remain correct.

One gap remains, in Workstream C's **test coverage**. The production logging behavior is
correct, but the plan's required tests for it are missing — and the existing log_buffer test
now asserts the *opposite* of the intended routing, passing only by accident.

## Gate status

Independently re-ran read-only gates on the current tree: `ruff check .` clean, `ty check`
clean, `pytest` 592 passed (85.96% coverage). Frontend gates passed under pre-commit on the
fix commit. Gates are green — the issue below is a missing-coverage / misleading-test problem,
not a failing gate.

## Required changes

The plan's Workstream C testing strategy requires (a) a test that `_decky_log_fallback`
routes `"debug"` to `logger.debug` (not `logger.info`), and (b) a test that `setup_logging`
raises `decky.logger` to `logging.DEBUG`. Neither exists, and the current test is inverted:

1. **Fix the inverted debug-routing test.** `tests/test_log_buffer.py`
   `test_decky_log_fallback_debug_has_no_prefix` asserts `logger.infos == ["refresh: hello"]`.
   This only passes because the `FakeLogger` in `tests/test_main.py` has **no `debug`
   method**, so `getattr(logger, "debug", getattr(logger, "info", None))` falls back to
   `.info`. On the real `decky.logger` (a stdlib `Logger`, which has `.debug`), debug records
   route to `logger.debug` — the intended behavior — which no test covers.
   - Give the test logger a `debug` method that captures into a `debugs` list (extend
     `FakeLogger` in `tests/test_main.py`, or use a dedicated fake in the test).
   - Update the test to assert the debug message is routed to `logger.debug` (lands in
     `debugs`) and **not** in `infos`. Rename it to reflect the real assertion
     (e.g. `test_decky_log_fallback_debug_routes_to_logger_debug`).

2. **Add a `setup_logging` level test.** Assert that `DiagnosticLogBuffer.setup_logging`
   sets `decky.logger.setLevel(logging.DEBUG)`. The `FakeLogger.setLevel` added in
   `tests/test_main.py`/`tests/test_singleton.py` currently only absorbs the call without
   asserting it. Capture the level argument (e.g. `self.levels: list[int]` in the fake) and
   assert `logging.DEBUG` is among the recorded calls after `setup_logging` runs.

3. **(Recommended) Cover `_apply_log_level` both ways.** Add a service-level test that
   `set_debug_logging(True)` results in `decky.logger.setLevel(logging.DEBUG)` and
   `set_debug_logging(False)` results in `logging.INFO`, using the level-capturing fake. This
   directly verifies the runtime toggle the feature exists for.

Follow strict TDD: update/add the tests, confirm they fail against any reverted production
change, then keep them green. Re-run all quality gates (`./run.sh` backend suite + `pnpm run
test` + `pnpm run typecheck`).

STATUS: CHANGES_REQUESTED
