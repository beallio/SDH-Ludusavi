# Review 01 — syncthing-settle-and-debug-gate

**Round:** 1
**Branch:** `feat/syncthing-settle-and-debug-gate`
**Commit reviewed:** `34a8c4b` (`feat(syncthing): shorten the post-game settle gate`)
**Plan commit:** `c7149d5`
**Reviewer:** orchestrator

## TASK 1: ACCEPTED

### Work verified by diff first

```text
py_modules/sdh_ludusavi/syncthing/_types.py      new constant
py_modules/sdh_ludusavi/syncthing/activity.py    36 +-
py_modules/sdh_ludusavi/syncthing/watcher.py      5 +
tests/test_activity.py                          103 ++
tests/test_watcher.py                            67 ++
```

Real work, first attempt, exactly the five files Task 1 scopes plus the plan.

### Verification performed

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             944 passed (was 933), coverage 89.67%
worktree           clean
review notes       none deleted
```

### The implementation

`POST_GAME_SETTLE_QUIET_WINDOW_SECONDS = 3.0` carries the measurement in its comment —
seven captures spreading 0.051s to 0.111s, roughly 30x margin, and the note that values
below ~6.5s are equivalent because first-peer confirmation binds first. A future reader
asking "why three?" gets the evidence rather than a number.

`compute_activity_status()` takes `settle_quiet_window_seconds: float | None = None` and
falls back to `active_window_seconds` when unset, so every existing caller keeps today's
behaviour. Four short-window recency variants feed a `settle_update_in_progress` that
mirrors `update_in_progress` term for term, and only `settled` consumes it. The reported
`local_change_recent`, `local_index_recent`, `sequence_change_recent` and
`scan_progress_recent` fields, and `update_in_progress` itself, remain on the long window.

The watcher passes the short window only when `self.phase == "post_game"`.

### One term I checked rather than assumed

`settle_update_in_progress` includes `item_finished_recent`, which is **not** recomputed
with the short window. That looked like an oversight that would leave `settled` blocked on
a long window through a back door, so I traced it: `item_finished_recent` uses its own
hardcoded `2.0` second threshold, not `active_window_seconds`. It is already shorter than
the new settle window, so leaving it unchanged is correct and consistent rather than an
omission.

### Mutation tests — both couplings proven

**Applying the short window to pre-game as well** (plan verification step 2):

```text
FAILED test_watch_uses_short_settle_window_only_for_post_game[pre-game-keeps-fifteen-second-launch-gate]
1 failed, 134 passed
```

Exactly one failure, and it is the pre-game guard. This is the most consequential test in
the plan: pre-game `settled` releases the launch hold, and releasing early risks starting a
game before a newer incoming save has landed. Everything else here is cosmetic timing; this
is the only path where a mistake costs data. It is genuinely pinned, and the parametrised id
names what it protects.

**Coupling a reported flag to the settle window** (plan verification step 3):

```text
FAILED test_settle_window_is_shorter_than_reported_activity_window
1 failed, 134 passed
```

The diagnostic surface and the settle decision cannot drift into each other silently.

Both mutations reverted; 135 passed in the focused files, tree clean.

### Scope

The completion rule, the confirmation window, the stall detector, both ceilings, the RPC
sample key set, pruning, and every frontend file are untouched.

## Authorization

TASK 1: ACCEPTED
AUTHORIZED TASK: 2

Proceed with Task 2 — gate debug observation on the debug setting — as written in the plan.
Note the test that matters most: the `debug_logging=False` case must be asserted **with the
`sdh_ludusavi` logger explicitly set to `DEBUG`**, because that is its real runtime state
after `setup_logging()`. Without that, a reintroduced `isEnabledFor` check passes every
other test, which is exactly how the current defect survived review. Task 2 only. Stop for
review when its atomic commit and the round-complete marker are in place.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 1 recorded above.

STATUS: CHANGES_REQUESTED
