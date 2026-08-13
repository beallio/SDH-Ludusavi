# Plan: Release Pre-Game Launch Gate On Content, Not Deletes (pre-game-content-only-launch-gate)

## Context

### The user-visible problem

When a tracked game launches, the plugin holds the game process with a SIGSTOP launch
gate and shows `SYNCTHING DOWNLOADING` until it believes the backup folder has gone
quiet. On `steamdeck-legos` on 2026-08-12 that hold lasted **52.3 seconds** (launch gate
23:28:49.728, quiescence 23:29:42.119, restore finished 23:29:46.956 — 57.2s of total
hold), and **none of it was spent waiting for the save**.

Syncthing's own log proves it. Content creation on that folder finished at 23:26 — 143
directory/file creates in that minute, then zero in 23:27, 23:28 and 23:29. Ludusavi
successfully read the backup it was about to restore at 23:28:50, before the wait had
really begun. Between 23:28:49 and the last delete at 23:29:24 the folder did nothing but
delete old Ludusavi snapshot directories. Quiescence was then declared 18.1s after that
last delete.

v0.4.4 already established that pending deletes must not gate status: they are snapshot
pruning, not the save. That fix was applied only to the **post-game** peer-completion
predicate. The pre-game path still gates on deletes, and pre-game is worse, because the
game is frozen for the duration.

The intended outcome: the pre-game launch gate releases as soon as the *content* the
device needs is present, and remains blocked while content is genuinely missing.

### The five mechanisms that keep `settled` false during a delete tail

All of these were confirmed against Syncthing v2.1.2 source and the device capture. Do not
assume any one of them is the whole story; each needs its own change.

1. **`settled` requires `folder_state == "idle"`.** During a pure-deletion pull iteration
   Syncthing reports **`sync-preparing`**, not `syncing`. The pull loop sets
   `FolderSyncPreparing` at the top of every iteration; `setState(FolderSyncing)` is only
   reached from the block copier/puller routines, which deletions never enter (deletions
   go through `processDeletions` → `deleteFile`/`deleteDir`). `sync-preparing` is in
   `PREPARING_STATES`, so `preparing` is true, so `settle_update_in_progress` is true.

2. **`need_total_items` is delete-contaminated.** `receive_needed` in
   `py_modules/sdh_ludusavi/syncthing/activity.py` is
   `need_bytes > 0 or need_total_items > 0 or need_deletes > 0`. Syncthing computes
   `needTotalItems` as `Counts.TotalItems()`, which is
   `Files + Directories + Symlinks + **Deleted**`. Dropping only the `need_deletes` term
   therefore changes nothing — the deletes come straight back through `need_total_items`.

   This is the single most important research finding, because the post-game path looks
   like a precedent and is not one. `/rest/db/completion` computes
   `NeedItems = Files + Directories + Symlinks` and **excludes** deletes, which is why the
   post-game predicate is correct as written. The two endpoints genuinely differ. The
   device log shows the completion-side behaviour directly: `needed_items=0` on the same
   line as `needed_deletes=31`.

   `/rest/db/status` does expose `needFiles`, `needDirectories` and `needSymlinks`
   separately. A content-only item count must be built from those three, mirroring
   Syncthing's own `NeedItems`.

3. **Delete items populate `active_items`.** Syncthing emits `ItemStarted`/`ItemFinished`
   for deletions as well as content, distinguished only by an `"action"` field that is
   `"delete"` or `"update"`. `process_event` ignores `action`, so deleted items land in
   `active_items`. That makes `downloading` true (`downloading` includes
   `bool(active_items)`), which is why the status strip read `SYNCTHING DOWNLOADING` for
   all 52 seconds even though nothing was downloading.

4. **`item_finished_recent` (2s) re-arms on every delete's `ItemFinished`.**

5. **The settle quiet windows re-arm on every delete's `LocalIndexUpdated`.** Applying a
   delete batch updates the local index, which arms `last_local_index_monotonic` and
   `last_sequence_change_monotonic`. Pre-game those are measured against
   `DEFAULT_ACTIVE_WINDOW_SECONDS` (15.0s), because `_tick_sample` in
   `py_modules/sdh_ludusavi/syncthing/watcher.py` passes
   `POST_GAME_SETTLE_QUIET_WINDOW_SECONDS` only when `self.phase == "post_game"` and `None`
   otherwise, and `None` falls back to the active window. This is the measured 18.1s tail.

   `LocalIndexUpdated` carries no action field, so it **cannot** be filtered the way
   `ItemStarted`/`ItemFinished` can. Any fix that depends on filtering it is wrong.

### The safety invariant

Pre-game exists to stop a restore from running against a half-downloaded backup. That
invariant must survive this change, and it is the reason the plan gates on content rather
than simply removing gates.

Gating on missing content preserves it: a tombstone removes a whole old snapshot directory,
and Ludusavi restores the newest snapshot while pruning removes the oldest, so a pending
delete cannot make a *present* snapshot incomplete.

One hazard to respect while implementing: **`needBytes` alone is not a sufficient
completeness signal.** Syncthing's folder summary subtracts in-flight progress
(`need.Bytes -= FolderProgressBytesCompleted(folder)`), so `needBytes` can reach zero while
a file is still an unfinished temp file. `needFiles`/`needDirectories`/`needSymlinks` only
drop when the item is committed to the database, so the content-item count is the reliable
term. Keep `active_download_files` in the predicate for the same reason.

### Relevant files

```text
py_modules/sdh_ludusavi/syncthing/_types.py      FolderRuntime, parse_folder_runtime, state sets, constants
py_modules/sdh_ludusavi/syncthing/activity.py    compute_activity_status, process_event
py_modules/sdh_ludusavi/syncthing/watcher.py     _tick_sample, _log_peer_completion_transition, _peer_completion_tracking
tests/test_activity.py                           compute_activity_status and process_event tests
tests/test_watcher.py                            watch tick and poll-sequence tests
```

Two existing tests encode the current pre-game behaviour and will need to change as the
plan requires:
`tests/test_watcher.py::test_watch_uses_short_settle_window_only_for_post_game` (its
`pre-game-keeps-fifteen-second-launch-gate` parameter) and
`tests/test_watcher.py::test_watcher_keeps_activity_pruning_on_the_fifteen_second_window`
(pruning stays on the 15s window; that is deliberate and must not be changed by this plan).

### Practical notes

- The plugin is diagnostically blind pre-game: `_peer_completion_tracking` returns
  `self.phase == "post_game"`, so the whole 52-second window produced no plugin log lines.
  The decomposition above came from Syncthing's log, not the plugin's. Task 6 fixes that.
- If a commit fails because a dependency is newer than the machine's uv cutoff, retry with
  `UV_FROZEN=1` in the environment.

**Slug used throughout this plan:** `pre-game-content-only-launch-gate`

---

## Orchestration Contract

**Slug:** `pre-game-content-only-launch-gate`

**Plan file:**

```text
docs/plans/2026-08-13_pre-game-content-only-launch-gate.md
```

**Implementation branch:**

```text
feat/pre-game-content-only-launch-gate
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/pre-game-content-only-launch-gate_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/pre-game-content-only-launch-gate_finalized
```

**Review notes:**

```text
docs/review/pre-game-content-only-launch-gate-review-*.md
```

Each review note ends with exactly one status trailer:

```text
STATUS: CHANGES_REQUESTED
```

or:

```text
STATUS: APPROVED
```

---

## Required Agent Protocol

1. Use the **implementer** skill.
2. Work from the repository root.
3. Branch from `dev`.
4. Commit this plan as the first commit on the implementation branch.
5. Follow TDD where behavior changes are testable.
6. Run quality gates before marking any round complete.
7. Do not write your own review.
8. Do not create files under `docs/review/`.
9. Do not delete files under `docs/review/`.
10. Review notes are durable audit records and must be committed.
11. Resolving a review note means:
    - implement the requested changes;
    - run quality gates;
    - commit the code/docs changes;
    - commit the review note itself if it is not already committed;
    - recreate the round-complete marker.
12. After finalization, stop polling and exit cleanly.

---

## Scope discipline

- Implement only the units the plan lists. Do not modify files outside the plan's scope.
- Do not change runtime behavior beyond what the plan specifies. A `refactor` or
  `cleanup` commit must preserve observable behavior.
- Never edit a test's expected value to make a behavior change pass. If a test
  legitimately must change, that change must be required by the plan or a review
  note, and you must record the rationale in the session log.
- If you spot an unrelated improvement, do not make it here — note it in the
  session log for a separate plan.

---

## Setup

Start from `dev`:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/pre-game-content-only-launch-gate
```

Commit this plan first:

```bash
git add docs/plans/2026-08-13_pre-game-content-only-launch-gate.md
git commit -m "docs(plan): add pre-game-content-only-launch-gate implementation plan"
```

---

## Implementation Tasks

There are six tasks. **Implement exactly one task per round.** Finish a task, run the
quality gates, commit, run `mark-finished`, and exit. Do not start the next task in the
same round — each one is reviewed before the next begins.

Every task is red-first: write the failing test, run it, record the failure output in the
session log, then implement.

There is no halt-and-report instruction anywhere in this plan.

---

### Task 1 — Parse content-only need counters from folder status

Behaviour must not change in this task. This only makes the missing data available.

In `py_modules/sdh_ludusavi/syncthing/_types.py`:

- add `need_files`, `need_directories` and `need_symlinks` fields to `FolderRuntime`,
  defaulting to `0`;
- populate them in `parse_folder_runtime` from `needFiles`, `needDirectories` and
  `needSymlinks` using the existing `int_field` helper;
- add a `need_content_items` property to `FolderRuntime` returning
  `need_files + need_directories + need_symlinks`.

Keep `need_total_items` exactly as it is. Nothing may start reading `need_content_items`
yet.

**There is a trap here that must be fixed in this same task.** `FolderRuntime` is
`@dataclass(frozen=True)`, and `process_event` rebuilds it field by field in the
`LocalIndexUpdated` branch at `py_modules/sdh_ludusavi/syncthing/activity.py:492` — it
lists every field explicitly in order to change only `sequence`. Adding three new fields
with defaults means that reconstruction silently resets them to `0` on **every**
`LocalIndexUpdated` event. During a delete tail those events arrive constantly, so
`need_content_items` would read as zero, content would look present, and the launch gate
would release early. That is the exact failure this plan exists to prevent, in the more
dangerous direction.

Replace that field-by-field reconstruction with `dataclasses.replace(runtime, sequence=...)`
so it cannot drift again when fields are added.

Red test for the trap, in `tests/test_activity.py`: build a `FolderRuntime` with
`need_files=3`, feed a `LocalIndexUpdated` event for the watched folder through
`process_event`, and assert the returned runtime still reports `need_files == 3` and
`need_content_items == 3`. Write this test against the field-by-field version first and
watch it fail, then apply `dataclasses.replace`.

Red test in `tests/test_activity.py`: parse a folder-status payload carrying
`needBytes=0, needFiles=0, needDirectories=0, needSymlinks=0, needDeletes=46,
needTotalItems=46` and assert `need_content_items == 0` while `need_total_items == 46`.
That payload is the shape Syncthing produces during a pure-delete tail; the assertion
documents that the two counters diverge and is the thing every later task depends on.

Also assert `parse_folder_runtime({})` leaves all three new fields at `0`, so a status
response that omits them cannot make content look present.

---

### Task 2 — Make `receive_needed` content-only

In `compute_activity_status` in `py_modules/sdh_ludusavi/syncthing/activity.py`, change:

```python
receive_needed = (
    runtime.need_bytes > 0 or runtime.need_total_items > 0 or runtime.need_deletes > 0
)
```

to test `runtime.need_bytes > 0 or runtime.need_content_items > 0`.

Add a comment recording why `need_total_items` cannot be used: Syncthing's
`Counts.TotalItems()` includes `Deleted`, so it would reintroduce delete gating.

Red tests in `tests/test_activity.py`:

1. With `need_bytes=0`, `need_content_items=0`, `need_deletes=46`, `need_total_items=46`:
   `receive_needed` is `False` and `status` is not `UPDATE_NEEDED`.
2. **The safety case, which must stay blocking:** with `need_bytes=0` but `need_files=1`
   (the in-flight temp-file situation described in Context), `receive_needed` is `True`.
3. With `need_bytes>0` and all content item counts zero, `receive_needed` is `True`.

Post-game must be unaffected. Add a regression test asserting a post-game sample with a
fresh content-complete peer and non-zero `need_deletes` still settles exactly as it does
today.

---

### Task 3 — Stop delete item events from registering as activity

In `process_event` in `py_modules/sdh_ludusavi/syncthing/activity.py`, read
`data.get("action")` for `ItemStarted` and `ItemFinished`.

- `ItemStarted` with `action == "delete"`: do not add the item to `active_items`.
- `ItemFinished` with `action == "delete"`: do not arm `last_item_finished_monotonic`.
  Still `pop` the item key from `active_items`, so a mismatched pair can never strand an
  entry there.
- Any other `action` value, including a missing one, keeps today's behaviour. Treat a
  missing `action` as content — an unknown event must fail towards blocking the gate, not
  towards releasing it.

Red tests in `tests/test_activity.py`: feed an `ItemStarted`/`ItemFinished` pair with
`action="delete"` and assert `active_items` stays empty and
`last_item_finished_monotonic` stays `0`; feed the same pair with `action="update"` and
with `action` absent, and assert both still populate `active_items` and arm the timestamp.

---

### Task 4 — Add a content-only pre-game settle predicate

This is the task that releases the gate. It addresses mechanisms 1 and 5 from Context.

Add to `compute_activity_status` a notion of *content* settledness used for the `settled`
field, replacing the current `folder_state == "idle"` requirement with one that also
accepts a delete-only folder state:

- content is present when `not receive_needed` (now content-only after Task 2) **and**
  `local_activity.active_download_files == 0` **and** `not remote_progress` **and** no
  content items are active;
- when content is present, a folder state in `PREPARING_STATES` is acceptable, because
  Syncthing reports `sync-preparing` while applying deletions;
- a folder state in `SCANNING_STATES`, `ERROR_STATES` or `PAUSED_STATES`, a non-zero
  `runtime.pull_errors`, or a non-empty `runtime.watch_error` must still block, exactly as
  today;
- `syncing` must still block. Deletions never reach that state, so a `syncing` folder is
  moving content.

The settle quiet windows must no longer be armed by delete-driven index churn.
`LocalIndexUpdated` carries no action field and cannot be filtered, so do not attempt to.
Instead, drop `settle_local_index_recent` and `settle_sequence_change_recent` from the
settle predicate and rely on the content terms above, which are authoritative for whether
content is missing. Keep `settle_local_change_recent` and `settle_scan_progress_recent`:
those signal genuine local mutation and scanning.

Leave `update_in_progress` and the `status` string alone. They drive diagnostics and the
post-game path, and changing them is out of scope.

Red tests:

1. In `tests/test_activity.py`: folder state `sync-preparing`, zero content need, non-zero
   `need_deletes`, `active_items` empty, `last_local_index_monotonic` set to *now* →
   `settled is True`. This is the exact 2026-08-12 legos state and fails before the change.
2. **Negative control, and it must stay blocking:** folder state `sync-preparing` with
   `need_files=1` → `settled is False`.
3. Folder state `syncing` with zero content need → `settled is False`.
4. Folder state `scanning` with zero content need → `settled is False`.
5. `pull_errors=1` with zero content need and state `sync-preparing` → `settled is False`.

---

### Task 5 — Give pre-game its own settle window

Add `PRE_GAME_SETTLE_QUIET_WINDOW_SECONDS = 3.0` to
`py_modules/sdh_ludusavi/syncthing/_types.py`, alongside the existing post-game constant.

In `_tick_sample` in `py_modules/sdh_ludusavi/syncthing/watcher.py`, select it for the
pre-game phase instead of passing `None`. Both phases now pass an explicit window and the
`None` fallback becomes unreachable from the watcher; leave the `None` handling in
`compute_activity_status` in place for direct callers and tests.

Do **not** touch the pruning windows. `prune_remote_progress` and `prune_local_activity`
must stay on `DEFAULT_ACTIVE_WINDOW_SECONDS`;
`tests/test_watcher.py::test_watcher_keeps_activity_pruning_on_the_fifteen_second_window`
must still pass unmodified.

Update `tests/test_watcher.py::test_watch_uses_short_settle_window_only_for_post_game`:
rename it to reflect that both phases now use a short window, and change the
`pre-game-keeps-fifteen-second-launch-gate` parameter to assert pre-game settles after 4
seconds of quiet and does not settle after 2. Record the rename and the changed expectation
in the session log with the reason.

---

### Task 6 — Log pre-game quiescence transitions

The pre-game phase currently logs nothing between the watch starting and the status
flipping, which is why the 52-second stall had to be diagnosed from Syncthing's log
instead of the plugin's.

Add a transition-only pre-game diagnostic in
`py_modules/sdh_ludusavi/syncthing/watcher.py`, modelled on
`_log_peer_completion_transition`:

- emit at `INFO` only when the tuple of reported values changes, never on a timer;
- report `phase`, `folder_state`, `need_bytes`, `need_content_items`, `need_deletes`,
  `active_download_files`, `active_items` count, and `settled`;
- never log device IDs, file names, folder paths or raw API payloads.

Red tests in `tests/test_watcher.py`, using `caplog`:

1. Two consecutive ticks with identical state produce exactly one line.
2. A tick that changes `need_content_items` produces a second line.
3. Assert the emitted records contain no folder path, no device ID and no file name, by
   seeding the watch with a folder path and device IDs and asserting those literal strings
   are absent from `caplog.text`. Follow the existing privacy assertions in
   `test_peer_completion_diagnostics_are_transition_only_and_privacy_safe`.

---

## Quality Gates

Run before marking any round complete:

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

The round is not complete unless:

1. all requested implementation work is done;
2. all relevant tests pass;
3. build/typecheck gates pass;
4. review notes have not been deleted;
5. the working tree is clean;
6. all code/docs changes are committed.

---

## Verification

Every step below must be able to fail. When you record a result, paste the command's actual
output — pass/fail tallies, assertion text, exit codes — not a conclusion that it passed.

### Per-task mutation check

Do this in the round that implements each task, before marking it complete. It proves the
new test is actually load-bearing rather than passing for an unrelated reason.

Revert only the production change for that task (keep the new tests), run the suite, and
record which tests fail and with what message. Then restore the change and record the suite
going green again.

```bash
scripts/orchestration/run-quality-gates
```

Expected on the mutated build: the specific test named in that task fails. If the suite is
green with the production change reverted, the test is not testing anything — fix the test
before continuing.

Per task, the test that must go red when the change is reverted:

```text
Task 1  the LocalIndexUpdated round-trip test asserting need_files survives at 3
Task 1  the parse test asserting need_content_items == 0 while need_total_items == 46
Task 2  the receive_needed content-only test
Task 3  the delete-action ItemStarted/ItemFinished test
Task 4  the sync-preparing-with-pending-deletes settles test
Task 5  the pre-game short-window parameter of the settle-window test
Task 6  the "two identical ticks produce one line" test
```

### End-to-end replay (do this in the Task 6 round, after everything else is in)

Add `tests/test_watcher.py::test_pre_game_launch_gate_releases_during_delete_only_tail`,
driving `manager.poll_watch()` through a poll sequence rather than calling `_tick_sample`
directly, following the existing poll-sequence helpers in that file.

Replay the measured 2026-08-12 `steamdeck-legos` sequence:

1. folder state `sync-preparing`; `needBytes=0`, `needFiles=0`, `needDirectories=0`,
   `needSymlinks=0`, `needDeletes=46`, `needTotalItems=46`;
2. a trickle of `ItemStarted`/`ItemFinished` pairs with `action="delete"`, roughly two
   seconds apart;
3. a `LocalIndexUpdated` after each delete batch, advancing the sequence number.

Assert the watch publishes three distinct settled samples, and assert the monotonic time
between the first poll and the third settled sample is **under 10 seconds**. Against
today's code this sequence never settles at all, so the test fails before the change and
can only pass once every one of the five mechanisms is addressed. This is the negative
control for the whole plan and it must run after the per-task checks above.

Then extend the same replay with a variant where `needFiles=1` throughout and assert the
watch **never** publishes a settled sample across the whole sequence. A change that simply
stopped blocking would pass the first assertion and fail this one.

### Full gates

```bash
scripts/orchestration/run-quality-gates
git status --short
```

Record the pytest pass/fail/skip tallies and the ruff and `ty` results verbatim.

### Deferred — on-device verification

**This cannot be run from CI or from the repo, and it is not done as part of this plan.**
It needs a Steam Deck or Legion Go S with the built plugin installed, Syncthing running
with peers connected, and a folder carrying a pending delete backlog. Record it as
outstanding in the session log.

When it is run, the pass signature is:

- confirm the installed build first via
  `grep '"version"' /home/deck/homebrew/plugins/SDH-Ludusavi/plugin.json`;
- launch a tracked game while `needDeletes` is non-zero on the backup folder;
- `SYNCTHING DOWNLOADING` clears in a few seconds rather than tens of seconds, and the
  launch gate releases with it;
- the new pre-game diagnostic lines from Task 6 appear and show `need_content_items=0`
  alongside a non-zero `need_deletes`;
- the restored save is correct — verify the game loads the expected save, not an older one.

The failure to watch for is the opposite of the stall: a launch gate that releases while
content is still arriving, producing a restore from an incomplete snapshot. If the restore
is ever wrong, that is a correctness regression and outranks the latency win.

### Explicitly not verified by this plan

- Real device behaviour. Everything above is unit and replay coverage against recorded API
  shapes; no step in this plan runs against a live Syncthing.
- Syncthing versions other than v2.1.2. The state-machine claim in Context — that deletions
  report `sync-preparing` and never `syncing` — was read from v2.1.2 source. If a future
  version routes deletions through the puller, Task 4's state handling would need revisiting.
- The `needBytes`-reaches-zero-before-commit hazard described in Context is *mitigated* by
  gating on content item counts, but no test here reproduces a real in-flight temp file.
- Whether 3.0s is the right pre-game window. It matches the post-game value and is a
  starting point, not a measured optimum; the Task 6 diagnostics are what would let it be
  measured on device later.
- The stall window and the frontend and backend ceilings are untouched by this plan and
  remain unproven on hardware.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished pre-game-content-only-launch-gate
```

This writes:

```text
/tmp/sdh_ludusavi/pre-game-content-only-launch-gate_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer pre-game-content-only-launch-gate`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/pre-game-content-only-launch-gate-review-*.md
```

When a review note exists or a new review note appears:

1. Read the full review note.
2. If the note ends with:

   ```text
   STATUS: CHANGES_REQUESTED
   ```

   then resume work.

3. Clear the round-complete marker:

   ```bash
   scripts/orchestration/clear-finished pre-game-content-only-launch-gate
   ```

4. Address every requested change.
5. Run quality gates:

   ```bash
   scripts/orchestration/run-quality-gates
   scripts/orchestration/check-review-notes-not-deleted
   ```

6. Commit code/docs fixes.
7. Commit the review-note file itself if it is not already committed:

   ```bash
   git add docs/review/pre-game-content-only-launch-gate-review-*.md
   git commit -m "docs(review): record pre-game-content-only-launch-gate review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished pre-game-content-only-launch-gate
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer pre-game-content-only-launch-gate` after the next review note is created.

---

## Approval Handling

If the latest review note ends with:

```text
STATUS: APPROVED
```

then:

1. Confirm every previous review item has been addressed.
2. Confirm all review notes are committed:

   ```bash
   scripts/orchestration/check-review-notes-committed pre-game-content-only-launch-gate
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize pre-game-content-only-launch-gate
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/pre-game-content-only-launch-gate_finalized
   ```

6. Stop polling and exit cleanly.

---

## Review Rules

Do not write your own review.

Do not create files under:

```text
docs/review/
```

Do not delete files under:

```text
docs/review/
```

Only the orchestrator writes review notes. Your job is to read them, resolve them, commit them as audit records, and continue the loop.

---

## Finalization Rules

Only finalize after a review note with:

```text
STATUS: APPROVED
```

Finalization is performed with:

```bash
scripts/orchestration/finalize pre-game-content-only-launch-gate
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/pre-game-content-only-launch-gate_finished
/tmp/sdh_ludusavi/pre-game-content-only-launch-gate_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
