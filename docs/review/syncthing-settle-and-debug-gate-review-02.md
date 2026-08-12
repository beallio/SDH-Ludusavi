# Review 02 — syncthing-settle-and-debug-gate

**Round:** 2
**Branch:** `feat/syncthing-settle-and-debug-gate`
**Commit reviewed:** `b3a1d83` (`fix(syncthing): gate debug observation on the debug setting`)
**Prior review:** review 01, Task 1 accepted
**Reviewer:** orchestrator

## TASK 2: ACCEPTED

### Verification performed

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             946 passed (was 944), coverage 89.68%
worktree           clean
review notes       none deleted
```

### The implementation

```python
-  self._debug_outbound_completion_observation = logger.isEnabledFor(logging.DEBUG)
+  self._debug_outbound_completion_observation = self._debug_logging
```

`isEnabledFor` no longer appears anywhere in `watcher.py`. `debug_logging: bool = False` is
threaded through `SyncthingWatchManager.start_watch()` into `SyncthingWatch`, and
`service.py` passes `self._debug_logging` at the call site. The default is `False`, so a
caller that forgets the argument fails closed rather than silently giving every user
extended watches.

The diagnostic line is at INFO with phase, selection, and connected relevant peer count, and
carries no device IDs, folder paths, or raw payloads. It will be what explains the next
device run rather than another round of inference.

### The test that matters

`test_debug_logging_false_stops_at_first_peer_even_when_plugin_logger_is_debug` does the
thing the plan and review 01 both insisted on:

```python
plugin_logger = logging.getLogger("sdh_ludusavi")
prior_level = plugin_logger.level
try:
    plugin_logger.setLevel(logging.DEBUG)
    ...
finally:
    plugin_logger.setLevel(prior_level)
```

It reproduces the real runtime state — `setup_logging()` pins that logger to `DEBUG`
permanently — and restores it in a `finally` so it cannot leak into other tests. The test
name says what it is defending. A test that left the logger at its pytest default would pass
against both the correct and the broken implementation, which is exactly how this defect
survived its original review.

### Mutation tests — both plan gates proven

**Restoring `logger.isEnabledFor(logging.DEBUG)`** (plan verification step 4):

```text
FAILED test_debug_logging_false_stops_at_first_peer_even_when_plugin_logger_is_debug
FAILED test_debug_logging_true_extends_then_self_terminates_with_latch_diagnostic
2 failed, 179 passed
```

The false case fails, as required — the restored check returns true because the plugin
logger really is at `DEBUG`.

**Flipping the default to `True`** (plan verification step 5):

```text
FAILED test_watch_manager - assert True is False
FAILED test_manager_stops_normal_completed_watch
2 failed, 179 passed
```

A fail-open default is caught by pre-existing manager tests, not only by the new ones, which
is better coverage than the plan asked for.

Both mutations reverted; tree clean, full suite green at 946.

### Process note

My first attempt to run these mutations was blocked by my own guard — the implementer's
tmux session was still alive and the script exited rather than editing files underneath it.
That guard was added after an earlier round where the equivalent check printed a warning and
carried on anyway. It behaved correctly here; I waited for the session to exit and then ran
the mutations.

## Authorization

TASK 2: ACCEPTED
AUTHORIZED TASK: 3

Proceed with Task 3 — document both changes and record verification — as written in the
plan. Two things to get right: no `README.md` change is expected, so confirm that and record
it in the session log rather than editing the file to no purpose; and record explicitly that
extended observation not running on device on 2026-08-11 despite an always-true gate remains
**unexplained**, and that this branch ships a correct gate plus a diagnostic rather than a
fix for it.

Task 3 only. This is the final implementation task: mark the round complete and stop for
review. Do not author an approval note, finalize, merge, tag, or release. Approval is a
human act and the human approver has not yet reviewed this work.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 2 recorded above.

STATUS: CHANGES_REQUESTED
