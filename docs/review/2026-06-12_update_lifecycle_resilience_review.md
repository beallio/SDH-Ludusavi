# Review — update_lifecycle_resilience — PASS

Reviewed branch: `fix/update-lifecycle-resilience` at commit df228fb (6 commits off `dev@c6a41f0`), merged into dev.

**Verdict: PASS — no findings.**

## What was reviewed

Plan: `docs/plans/update_lifecycle_resilience.md` — three failure mechanisms observed in real Steam Deck self-update logs (lingering old process via non-daemon RPC executor threads, concurrent backend instances racing persisted update state during Decky's reload storm, ghost frontend mounts re-running startup hydration).

1. **`py_modules/sdh_ludusavi/rpc_pool.py` (`DaemonThreadPool`)** — Executor-compatible pool with daemon workers and no atexit join. Verified: real `concurrent.futures.Future`s (works with `loop.run_in_executor`); `set_running_or_notify_cancel` guard; `BaseException` delivered via the future; `shutdown(cancel_futures=True)` drains and cancels queued items; submit-after-shutdown raises under the same lock that sets the flag (no race); worker count capped. `main.py` swaps the executor and widens `_run_blocking`'s type to `Executor`; the AST contract test still passes.
2. **`persistence.py` `_InterProcessLock`** — sidecar flock file (never the data file, so `os.replace` cannot invalidate the lock), per-process re-entrancy via RLock + depth, bounded 5s acquisition degrading to unlocked operation with a warning. Two managers in one process still exclude each other (flock conflicts across separate open file descriptions). `load_all`/`save_settings`/`save_cache` acquire it; `locked()` exposes compound RMW.
3. **`service.reconcile_pending_update_install` + `updater.adopt_persisted_cache`** — atomic claim: state lock → persistence lock → re-read disk → adopt fresh bookkeeping → reconcile+save under the same locks. Verified the updater's `_state_lock` IS the service's RLock (passed in the constructor), so there is a single lock ordering (state → persistence) everywhere and no ABBA deadlock is possible. `adopt_persisted_cache` reuses `load_state`'s `_adopt_cache` body — no divergent sanitization.
4. **`src/runtime/startupHydration.ts`** — faithful extraction of the index.tsx hydration IIFE with a `disposed` flag checked after the await; `dispose()` wired first in `onDismount`. Late-resolving fetch after dismount neither applies settings nor logs `startup_settings_hydrated`.

## Verification (at df228fb, detached checkout)

- pytest: 532/532 passed (13 new: rpc_pool 7 incl. interpreter-exit subprocess regression, persistence lock 3, update-install race 2, main executor 1), TOTAL coverage 85%
- ruff check / format: clean; ty: clean
- vitest: 156/156 (5 new hydration tests); tsc --noEmit clean; rollup build success
- Frozen contract tests untouched; scope respected the concurrently-developed hygiene plan's files (zero overlapping paths → clean merge into dev)
- Note: gates on the branch run via `./run.sh pytest` (shared venv PATH) because the detached worktree HEAD carries a non-PEP-440 dev version that breaks `uv run`'s project sync — documented in the branch's plan.

## Endgame

Merged into dev with `--no-ff`; this review committed on dev; full gates re-run on dev post-merge; dev pushed; dev release dispatched via `./scripts/request_dev_release.sh 0.3.0`. The branch remains checked out in the `/tmp/sdh_ludusavi-update-lifecycle` worktree (owned by another session) — cleanup deferred.
