# Review 03 — syncthing-peer-completion-upload-status

**Round:** 3
**Branch:** `feat/syncthing-peer-completion-upload-status`
**Commit reviewed:** `a3e717f` (`fix(autosync): preserve uploading through backup handoff`)
**Prior review:** `ac9f830` (review 02, Task 2 accepted)
**Reviewer:** orchestrator

## TASK 3: ACCEPTED

### Scope

The four files Task 3 lists, plus two files this reviewer required in review 02 finding 1:
`tests/test_watcher.py` (the companion regression) and
`docs/agent_conversations/2026-08-09_syncthing-peer-completion-upload-status.json` (the
test-input rationale). Nothing outside the plan or this reviewer's instructions.
283 insertions, 8 deletions.

### Verification performed

Quality gates re-run independently by the orchestrator against `a3e717f`:

```text
pnpm test          334 passed (was 331)
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             907 passed (was 906)
worktree           clean
review notes       none deleted
```

### The production change

Six lines, in exactly the place plan item 6 specifies:

```ts
} else if (
  nextState.mutationObserved &&
  sample.settled &&
  (state.phase !== "post_game" || state.handoffActivated)
) {
```

Two details make this correct rather than merely passing:

- The trailing `else` branch already resets `settledCount = 0`, so a post-game settled
  sample arriving *before* the handoff does not accumulate — it clears the counter. The
  three post-handoff samples are therefore genuinely new, which is what plan item 2 means
  by "three new distinct settled samples" and what makes the dwell visible to the user
  rather than satisfied by already-consumed history.
- The guard reads `state.handoffActivated`, not `nextState.handoffActivated`. If a
  `handoff_confirmed` event and a settled sample were ever folded into one transition, the
  sample would not count toward the quorum. That is the conservative direction and it
  matches the plan's intent.

No RPC types or status-surface code were touched, as plan item 6 requires.

### Plan conformance

1. **Pre-handoff buffering.** The pure-machine test asserts `latestStatus="uploading"`,
   `settledCount=0`, `completionObserved=false`, `step="watching"`, and
   `handoffOutcome(state)="uploading"` after settled samples precede the handoff.
   `stopWatch` is asserted false.
2. **Post-handoff quorum.** The first two post-handoff settled samples retain uploading
   with `stopWatch=false`; the third sets `latestStatus="complete"`,
   `completionObserved=true`, publishes `{status: "syncthing_complete", source:
   "context"}`, and stops the watch. The `SyncthingMonitor` fake-timer test walks the same
   path through the real polling loop, and `gameLifecycleDecision.test.ts` pins that a
   buffered upload handoff publishes `syncthing_uploading` with
   `handoffTransferred: true`. No new BrowserView timer was added.
3. **Fast-sync case.** `keeps a mutation without caught outbound evidence pending until
   the handoff` covers the parallel path: `mutationObserved=true`,
   `completionObserved=false`, `handoffOutcome="pending"` before the handoff, completing
   only after the post-handoff quorum. The detection-grace fallback is untouched.
4. **Regressions.** 334 frontend tests pass, up from 331, with the pre-game, duplicate
   timestamp, rank monotonicity, direction, cancellation, failure mapping, and generation
   ownership suites unchanged.

### Modified existing tests — checked, and correct

Two existing tests changed. Both are required by the plan rather than bent to fit it:

- `buffered completion returns complete` → `preserves buffered uploading until three
  settled samples arrive after handoff`. The old title asserted the exact behavior this
  plan exists to eliminate — a handoff returning `complete` because settled samples landed
  before it. Its replacement is strictly stronger: it additionally asserts that
  pre-handoff settled samples neither complete nor stop the watch.
- `completes on settledCount >= 3` → `completes on settledCount >= 3 after the post-game
  handoff`, with `handoffActivated: true` added to the seeded state. The assertion is
  unchanged; only the precondition the plan introduces was added.

### Review 02 findings — both resolved

1. **Resolved, and well.** `test_watched_folder_mutation_beats_unscoped_peer_completion`
   restores the combination Task 2 removed: the watched folder's sequence advances 5→6
   while the same relevant peer emits a `FolderCompletion` for an unrelated folder. It
   asserts `uploading` is true, `status="ACTIVE_TRANSFER"`, and — the part that matters —
   `watch.peer_completions == {}`, proving the uploading verdict comes from the local
   mutation and not from the unscoped event. The session log records the rationale naming
   the test, the old and new values, and the reason, as required.
2. **Deferred as agreed.** The diagnostics dedupe was raised as non-blocking and no change
   was made. Correct handling; reconsider only if Task 4's device verification shows the
   log volume is noisy.

### Note carried forward (no action)

A post-game watch that never receives `handoff_confirmed` can no longer self-complete on
settled samples. That is the intended point of the change, and the backup handoff is the
normal path, with watch TTL and cancellation as the existing backstops. Recording it
because it narrows one previously available exit from the watching state.

## Authorization

TASK 3: ACCEPTED
AUTHORIZED TASK: 4

Proceed with Task 4 — document the contract and record verification — as written in the
plan. Task 4 only. This is the final implementation task: mark the round complete and stop
for review as usual. Do **not** author an approval note, finalize, merge, tag, or release.
Approval is a human act and the human approver has not yet reviewed this work.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 3 recorded above.

STATUS: CHANGES_REQUESTED
