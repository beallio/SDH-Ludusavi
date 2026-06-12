# Update Lifecycle Resilience

Date: 2026-06-11
Planner Model: claude-fable-5
Branch: `fix/update-lifecycle-resilience` (worktree off `dev@c6a41f0`)

## Problem Definition

Steam Deck logs from a plugin self-update (2026-06-11, `/tmp/sdh_ludusavi/steamdeck-logs/`)
show three failure mechanisms around Decky Loader's install/reload sequence:

1. **Lingering old process ("ghost threads").** Decky shuts a plugin down by raising
   `SystemExit(0)` in the sandboxed process. `Plugin._executor` is a
   `concurrent.futures.ThreadPoolExecutor`, whose workers are non-daemon and joined by an
   atexit hook — an in-flight RPC (GitHub fetch, multi-second `flatpak run ludusavi`
   call) keeps the *old* process alive seconds after unload. Observed: backend update
   check still logging 3s after `Unload started (pending_update=True)`; service
   constructor logs emitted by an instance already unloaded.
2. **Concurrent backend instances racing persisted update state.** Decky's file watcher
   reload-storms during install (~8 load/unload cycles in ~1s); two service instances
   initialized 130ms apart, both reading/writing the same `settings.json`/`cache.json`
   with no inter-process exclusion. A stale instance can double-promote or resurrect the
   `pending_update_install` record, and interleaved settings/cache writes can persist a
   mismatched pair.
3. **Ghost frontend mounts.** `definePlugin`'s startup-hydration IIFE in `src/index.tsx`
   is not cancelled in `onDismount`; during the post-install double-mount the dismounted
   instance's hydration resolved late and still ran `applySettings` + logged
   `startup_settings_hydrated` (observed twice).

## Scope

In scope: backend RPC offload pool, persistence locking, updater reconcile, frontend
startup hydration. Out of scope (owned by in-flight `repo_hygiene_and_correctness` plan):
`gateway.py`, `registry.py`, `ludusavi.py`, `history.py`, `pyproject.toml` addopts,
`expand_tests.py`, `docs/agent_conversations` archival. Also out of scope: Decky's
reload-storm itself (loader behavior), update-controller RPC side effects that must
survive QAM close (handoff confirmation), README (no user-facing usage change).

## Architecture Overview

- **New module `py_modules/sdh_ludusavi/rpc_pool.py`** — `DaemonThreadPool`, a minimal
  `concurrent.futures.Executor`-compatible pool (real `concurrent.futures.Future`s, so
  `loop.run_in_executor` keeps working) whose worker threads are daemon and are *not*
  registered with the interpreter's atexit join. On `SystemExit` the old plugin process
  now exits immediately; in-flight work is abandoned (state writes stay safe because all
  persistence writes are atomic temp+`os.replace`). `main.py` swaps
  `ThreadPoolExecutor` for it; `_run_blocking` is unchanged (AST contract test
  `test_run_blocking_uses_shared_executor_without_pipes_or_threads` keeps passing).
- **Inter-process state lock in `persistence.py`** — `_InterProcessLock` (per-process
  re-entrant via `threading.RLock` + depth counter; cross-process via `fcntl.flock` on a
  lock file beside the cache file; bounded 5s acquisition that degrades to unlocked
  operation with a warning rather than hanging the plugin). `load_all`, `save_settings`,
  `save_cache` acquire it; `PersistenceManager.locked()` exposes it for compound
  read-modify-write.
- **Reconcile-as-atomic-claim** — `SDHLudusaviService.reconcile_pending_update_install`
  acquires `_state_lock` → persistence lock, re-reads the cache from disk, adopts the
  fresh updater bookkeeping (`PluginUpdater.adopt_persisted_cache`, sharing
  `load_state`'s sanitization), then reconciles and saves while still holding the lock.
  Two racing instances: exactly one promotes; the other observes the promoted state.
  Lock ordering is always `_state_lock` → persistence lock (matches `_save_state`).
- **Cancellable startup hydration** — extract the hydration IIFE into
  `src/runtime/startupHydration.ts` (`createStartupHydration` → `{ ready, dispose }`);
  after `dispose()` a late-resolving settings fetch must not call `applySettings` nor log
  `startup_settings_hydrated`. `index.tsx` wires `dispose()` into `onDismount`.

## Core Data Structures

- `DaemonThreadPool`: `SimpleQueue` of work items (`Future` + zero-arg callable), worker
  list capped at `max_workers`, `shutdown(wait, cancel_futures)` drains the queue and
  cancels queued futures; `submit` after shutdown raises `RuntimeError`.
- `_InterProcessLock`: `{path, RLock, depth, fd}`; lock file
  `<cache dir>/.sdh_ludusavi.state.lock`, mode 0600.
- No persisted schema changes.

## Public Interfaces

- `DaemonThreadPool.submit/shutdown` (Executor-compatible subset).
- `PersistenceManager.locked()` context manager, `PersistenceManager.lock_path`.
- `PluginUpdater.adopt_persisted_cache(cache)`.
- `createStartupHydration(deps)` in `src/runtime/startupHydration.ts`.

## Dependency Requirements

None added. `fcntl` is stdlib (Linux-only project).

## Testing Strategy (strict TDD; each commit RED → GREEN → gates)

1. `tests/test_rpc_pool.py`: result/exception propagation through real futures; workers
   are daemon; queued-future cancellation on `shutdown(cancel_futures=True)`; submit
   after shutdown raises; `_run_blocking` integration; **interpreter-exit regression**:
   subprocess that submits `time.sleep(30)` then exits must terminate in <5s.
   `tests/test_main.py` addition: `Plugin()._executor` is a `DaemonThreadPool`.
2. `tests/test_persistence.py` additions: `locked()` reentrancy; lock file created at
   `lock_path`; cross-holder exclusion probed with `flock(LOCK_EX|LOCK_NB)` on a second
   fd while held.
3. `tests/test_update_install_race.py`: two services sharing one settings/cache path,
   both holding the same pending install in memory; reconcile A then B → exactly one
   "Pending update promoted" across both log buffers; disk ends with no
   `pending_update_install`, promoted `installed_release_tag`; a later `_save_state`
   from the stale instance does not resurrect the pending record.
4. `src/runtime/startupHydration.test.ts`: hydrates and logs once on success; skips when
   store already populated; `dispose()` before fetch resolution → no `applySettings`, no
   hydrated log; fetch rejection logged, not thrown.

## Commit Sequence

1. `docs(plans): add update lifecycle resilience plan` — this file.
2. `fix(rpc): replace RPC executor with daemon thread pool so unload cannot linger`
3. `fix(persistence): serialize state file access with an inter-process lock`
4. `fix(updater): reconcile pending install from fresh persisted state under lock`
5. `fix(ui): cancel startup hydration on plugin dismount`
6. `docs: record session log for update lifecycle resilience`

## Verification

Per commit: `./run.sh ruff check . --fix`, `./run.sh ruff format .`,
`./run.sh ty check py_modules/sdh_ludusavi/`, `./run.sh pytest`; frontend commits add
`pnpm run test:unit` + `pnpm run typecheck`. Full suite + frontend pass at the end.
Note: tools are invoked from the shared `/tmp/sdh_ludusavi/.venv` via `run.sh`'s PATH
(no `uv run` project sync — worktree HEAD sits on a non-PEP-440 dev tag, and the venv is
shared with a concurrently running agent; runs are staggered).
