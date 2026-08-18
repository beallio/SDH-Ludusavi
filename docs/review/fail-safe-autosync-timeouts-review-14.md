# Review — fail-safe-autosync-timeouts (round 14)

Branch: `feat/fail-safe-autosync-timeouts`
Reviewed against: `docs/plans/2026-08-18_fail-safe-autosync-timeouts.md`

## Verdict

Task 8 and its contention-visibility correction are accepted. Proceed with Task 9 only: documentation, session evidence, and final reconciliation. Do not finalize the orchestration run yet.

## Gate status

- The round-complete marker names `597e1c31ad5d35a6366d03a2dab422c51a936067`, which is `HEAD`, and the worktree is clean.
- `92fc803` provides the bounded automatic-operation acquisition and fail-fast action policy; `597e1c3` completes the user-visible contention behavior.
- Independent focused backend verification passed: 133 tests across the coordinator, service, and status-flow diagram suites.
- Independent focused frontend verification passed: 108 tests across lifecycle decisions, the lifecycle controller, and the status surface.
- `./run.sh pnpm run typecheck` and `git diff --check a5d254d..597e1c3` passed.
- Start-check, start-restore, and both conflict-resolution branches now clear pre-game watch retention on `operation_running`; the controller test confirms that cleanup stops the watch.
- `operation_running` now publishes the error surface instead of falling through to an unknown result, while still completing and notifying once.
- The review submission gate exposed a real test-helper race in `tests/test_ludusavi_executor.py`: `_is_running()` handles `FileNotFoundError` when `/proc/<pid>/stat` vanishes, but `Path.read_text()` can instead raise `ProcessLookupError` for the same disappearance. The full run therefore ended at 1 failed and 1025 passed. Twelve immediate isolated reruns passed, confirming the timing-sensitive failure rather than a production cancellation failure.

## Required changes

Complete Task 9 from the accepted plan, with no unrelated implementation work:

1. Reconcile every timeout, launch-gate, shutdown-gate, and `operation_running` reference across `README.md`, `DEVELOPMENT.md`, `docs/specs/sdh_ludusavi_launcher.md`, and any other affected specifications or diagrams. Use repository-wide searches so stale values and promises are not missed.
2. Keep the distinct bounds explicit and consistent: 180 seconds for a Ludusavi operation and preview, 210 seconds for the frontend running-status ceiling, 240 seconds for the launch watchdog, and 30 seconds for automatic lifecycle contention. Do not alter or conflate the separate 900-second Syncthing transfer timeout.
3. Keep README wording player-facing. Put internal concurrency, executor, cancellation, and gate details in developer/specification documents.
4. Replace the stale launcher claim that `keep_local` needs no launch gate. Document that every start-side mutation is launch-gated, timed-out work is canceled before the gate can be released, loss of a gate remains fail-closed, action calls fail fast on contention, and automatic checks/actions use the bounded contention wait.
5. Create `docs/agent_conversations/2026-08-18_fail_safe_autosync_timeouts.json` with the date, objective, files modified, RED tests, mutation checks, design decisions, validation results, and deferred Steam Deck/device verification.
6. Make the executor process-disappearance test helper deterministic for both observed disappearance exceptions. Add or extend the focused helper regression test so `ProcessLookupError` is covered explicitly; keep the change limited to test infrastructure unless new evidence identifies a production defect.
7. Run the complete project quality gates through `./run.sh`, including Ruff check/format, `ty`, pytest, frontend tests, frontend typecheck, and the repository's TDD/pre-commit enforcement. Inspect for vendored dependencies, repository-local caches, or unrelated changes afterward.
8. Commit the Task 9 documentation/session reconciliation and narrowly scoped test-reliability fix with Conventional Commit(s), publish a fresh round-complete marker, and wait for review. Do not write a finalized marker.

STATUS: CHANGES_REQUESTED
