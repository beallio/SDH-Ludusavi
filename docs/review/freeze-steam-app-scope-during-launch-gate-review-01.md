# Review — freeze-steam-app-scope-during-launch-gate (round 01)

Branch: `feat/freeze-steam-app-scope-during-launch-gate`
Reviewed against: `docs/plans/2026-07-14_freeze-steam-app-scope-during-launch-gate.md`

## Verdict

The systemd scope discovery and transition boundary is substantially correct, and the
implementation covers the plan's exact hierarchy, symlink, device/inode, argv, timeout,
freezer-state, analyzer, documentation, and public-RPC requirements. Changes are still
required because two lifecycle paths weaken the lease safety invariant, and malformed
freezer bytes can escape the bounded failure/cleanup contract.

## Gate status

- `git status --short`: clean at reviewed HEAD `a31501ec44fe5e3ce9fdc75fe04df2a88bf0333c`.
- `git diff --check dev...HEAD`: passed.
- Exact plan-listed focused suite: 192 passed.
- `scripts/orchestration/run-quality-gates`: passed; 31 Vitest files / 286 frontend tests,
  TypeScript, production build, Ruff, formatting, `ty`, and 725 Python tests at 87.97%
  coverage all passed.
- Semantic review: changes requested below; green gates do not cover these invariants yet.

## Required changes

1. Preserve the original absolute-ceiling origin when rotating a same-scope lease.
   `ProcessWatchdog.pause()` currently verifies an existing identical scope and avoids a
   thaw window, but then replaces the lease with `paused_at=now`. Repeated idempotent pause
   calls can therefore postpone `WATCHDOG_ABSOLUTE_RESUME_SECONDS` forever, contradicting
   the unconditional absolute ceiling. Keep the original `paused_at` for a same-scope
   rotation while issuing a new lease ID/deadline. Add a deterministic test that advances
   the injected monotonic clock, rotates the same scope, and proves the absolute-ceiling
   calculation still uses the first freeze time. A genuinely different scope identity may
   start a new absolute-ceiling interval.

2. Do not strand a frozen scope after a retryable thaw failure during `stop()`/plugin
   unload. `stop()` currently sets the stop event, joins the watchdog, calls `resume_all()`
   once, and returns even when a failed thaw deliberately leaves a lease in
   `_paused_pids`. At that point the only retry mechanism has been stopped, so the retained
   lease cannot satisfy the plan's unload guarantee or bounded-TTL recovery. Implement a
   bounded shutdown retry strategy (without an unbounded unload wait) that retries retained
   leases and returns only after confirmed thaw/disappearance or an explicitly logged final
   failure. Update the stop test so a first retryable thaw failure followed by success leaves
   no frozen lease; also cover the bounded exhausted-failure result/logging behavior.

3. Keep malformed freezer-state failures bounded and ensure partial freezes are cleaned up.
   `Path.read_text()` can raise `UnicodeDecodeError`, but `wait_for_frozen()` only converts
   `OSError` and `ValueError` to a failure result. If the freeze command has succeeded and a
   state file then contains invalid bytes, that exception bypasses `freeze()`'s best-effort
   thaw and can leave an untracked frozen scope while the RPC raises. Convert Unicode decode
   failures (and path-resolution `RuntimeError` where applicable) into bounded discovery or
   transition failures, preserving best-effort thaw after a partial freeze. Add synthetic
   tests for invalid freezer bytes and a resolution failure/loop so these cases cannot escape
   the controller API.

After addressing all three items, rerun the exact focused suite, full orchestration quality
gates, local package build/ZIP validation, deleted-review-note check, and confirm a clean
working tree before marking the next round complete. Update the durable session record with
the correction-round results.

STATUS: CHANGES_REQUESTED
