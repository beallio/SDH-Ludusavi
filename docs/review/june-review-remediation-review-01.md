# Review — june-review-remediation (round 01)

Branch: `feat/june-review-remediation`
Reviewed commit: `2cb29d8`
Reviewed against: `docs/plans/2026-06-19_june-review-remediation.md`

## Verdict

The implementation is **semantically strong**. All nine work units (WU-A … WU-J)
are implemented and correct against the plan. One commit-hygiene change is required
before approval; two minor observations are optional.

I verified each unit against the plan:

- **WU-A** (persistence fail-closed): `StateLockTimeoutError` raised on both the
  `os.open` failure and the timeout branch; `__enter__` correctly rolls back
  `_depth`/`_thread_lock` on the acquisition exception. Non-RPC callers audited —
  `service._load_state` and the pending-install reconcile both catch the timeout and
  degrade gracefully. ✔
- **WU-B** (process identity): dead `service: Any` removed (and the `service.py`
  construction site updated); identity = `/proc/<pid>` `st_uid` + stat field 22; pause
  rejects on unreadable identity or `uid != geteuid()`; resume rejects on
  not-tracked or identity mismatch (PID reuse) and drops the stale entry; tree signal
  re-validates the root identity. ✔
- **WU-C** (fuzzy match): backend collects all candidates and returns a match only
  when exactly one qualifies, else `None`; frontend `isTracked` mirrors the
  unique-candidate rule. ✔
- **WU-D** (backup-browser bounds): inspection budgeted, returns nullable size/count
  when exceeded. ✔
- **WU-E** (Syncthing lock): credential discovery, probes, and thread joins all moved
  outside the manager lock; short locked commit phase; `stop_watch`/`stop_all` join
  outside the lock. ✔ (see Observation 1)
- **WU-F** (install abort + `_call`): all four update RPCs retyped
  `RpcResult<UpdateCheckContext>`; `install()`, handoff confirm, pending clear, and
  hydration now inspect status and abort before the installer on failure;
  `main._call` re-raises `SystemExit`/`KeyboardInterrupt`. ✔
- **WU-G** (settings single source): all setters route through `patchSettings`;
  duplicate snapshot fields are now single-writer derivations of `settings` via
  `applySettings`; `syncSelectedGameCache` removed (notification normalization still
  applied through `normalizeSettings`). ✔
- **WU-H** (late-response guard): runtime-wide `mutationGeneration`; a response does a
  full `applySettings` only when it is still the latest generation, otherwise merges
  only its owned field via `patchSettings`; `MutateOptions` `any` fields replaced with
  `V`. ✔
- **WU-I** (lifecycle executor): `_execute_operation` reproduces all seven call sites
  exactly — record/refresh/log ordering, `Same` handling, `after_log` for
  `restore_game_on_start`, `OperationLockedError` no-history via `skip_locked_history`,
  and `backup_id` in both responses. ✔
- **WU-J** (quality gates + `setup-uv` pin): `scripts/quality_gates.sh` (check/fix)
  routes all tooling through `./run.sh`; CI, release, and dev-release call it; pre/post
  commit hooks call it; `setup-uv` pinned to `0.11.19`. Dependent hook-content tests
  updated. ✔

## Gate status

Local gates pass on the branch — `621 passed` (pytest), `202 passed` (vitest), ruff,
ty, and frontend verify all green. Working tree clean. No review notes deleted.

## Required changes

1. **Split commit `2cb29d8` so WU-J is its own atomic commit (plan Constraints:
   "One coherent commit per work unit").**
   Commit `2cb29d8 refactor(lifecycle): centralize backup/restore bookkeeping`
   currently bundles two unrelated work units:
   - WU-I: `py_modules/sdh_ludusavi/lifecycle.py` (+ `tests/test_lifecycle.py`,
     `tests/test_history_integration.py`, `tests/test_backup_browser.py` changes that
     belong to WU-I).
   - WU-J: `scripts/quality_gates.sh`, `scripts/pre_commit.sh`,
     `scripts/post_commit.sh`, `.github/workflows/ci.yml`,
     `.github/workflows/release.yml`, `.github/workflows/dev-release.yml`,
     `.github/actions/setup-toolchain/action.yml`, and the WU-J test updates
     `tests/test_release_workflows.py`, `tests/test_npm_supply_chain.py`,
     `tests/test_protocol.py`.

   Rewrite the branch so WU-I and WU-J are separate commits (e.g. soft-reset `2cb29d8`
   and re-commit: one `refactor(lifecycle): …` with only the lifecycle/test-of-lifecycle
   changes, then one `build(ci): define quality gates once and pin setup-uv` with the
   scripts/workflows/setup-toolchain and WU-J test changes). Keep the other eight
   commits as-is. Re-run the gates and re-mark finished.

## Optional observations (not required for approval)

1. **WU-E transient orphan watch on concurrent identical-signature starts.** Because
   `watch.start()` now runs outside the lock, two concurrent `start_watch` calls with
   the same `(phase, game_name, app_id)` can interleave so the winner stops the loser's
   watch before the loser calls `start()`, leaving a started-but-unregistered thread
   until its TTL expires. The registration outcome is still deterministic (exactly one
   registered watch) and the orphan self-heals, so this is not a correctness blocker.
   If cheap, re-check registration under the lock (or a superseded flag) before
   `watch.start()`.
2. **Dead branch** `if record_order == "after_log": pass` in `_execute_operation`
   (`lifecycle.py`) is a harmless no-op left from the extraction; remove if convenient.

STATUS: CHANGES_REQUESTED
