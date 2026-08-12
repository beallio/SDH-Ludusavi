# Review 03 — syncthing-settle-and-debug-gate (final)

**Round:** 3
**Branch:** `feat/syncthing-settle-and-debug-gate`
**Commit reviewed:** `1b0eae7` (`docs(syncthing): define the settle window and debug gate signals`)
**Prior review:** review 02, Task 2 accepted
**Reviewer:** orchestrator

## TASK 3: ACCEPTED — all three tasks complete

### Verification performed

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             946 passed, coverage 89.68%
worktree           clean
review notes       none deleted (3 notes present)
```

### The specs carry the evidence, not just the rule

Both spec sections record the measurement rather than asserting a number: seven captured
bursts spreading 0.051 to 0.111 seconds, roughly 30x margin, and the observation that values
below about 6.5 seconds are equivalent because first-peer confirmation binds first. Anyone
later asking "can we drop it to one second?" finds the answer already there — no, it would
change nothing and would spend the margin for free.

They also state the two things that must not be coupled: pre-game keeps its fifteen-second
launch-safety window, and the reported recency flags plus local and remote pruning keep
`DEFAULT_ACTIVE_WINDOW_SECONDS`. Both are the subject of a mutation test, so the spec and
the suite agree.

The debug-gate paragraph explains *why* logger levels are unsuitable —
`setup_logging()` pins `sdh_ludusavi` to `DEBUG` while the toggle only adjusts the
`decky.logger` sink. That is the fact that took three wrong inferences to establish, and it
is now written down where the next reader will hit it.

### README correctly untouched

No `README.md` change, and the session log records that as deliberate: the user-facing
meaning of `SYNCTHING COMPLETE` is unchanged, and Debug Logging now behaves as its
description always claimed.

### Session log

Complete against the plan, and it records the item that matters most for honesty — that
extended observation failing to run on device on 2026-08-11 despite an always-true gate
remains **unexplained**, and that this branch ships a correct gate plus a diagnostic rather
than a fix for it.

### Branch summary

```text
13 files changed, 1287 insertions(+), 18 deletions(-)

34a8c4b  Task 1  shorten the post-game settle gate
b3a1d83  Task 2  gate debug observation on the debug setting
1b0eae7  Task 3  define the settle window and debug gate signals
```

Three rounds, three tasks, no correction rounds — the second clean branch in a row. Four
mutations were run across the two behavioural tasks and each produced exactly the failures
the plan predicted.

### Expected effect, and how to falsify it

Modelled from the captures, `SYNCTHING UPLOADING` should drop from roughly 17 seconds to
roughly 8 on a normal sync, with handoff-to-complete near 19 seconds against the 27.4s
baseline of 2026-08-11 23:25. If the next device run shows completion still around 27
seconds, the settle window is not the binding constraint it was measured to be and the model
is wrong — that is the falsifiable claim.

### Deferred and explicitly not verified

- **Device verification is required for both changes.** For the settle gate, compare
  handoff-to-complete against 27.4s. For the debug gate, read the new latch diagnostic to
  establish whether extended observation was *selected*.
- **The second debug defect remains unexplained.** If the diagnostic shows extended
  observation selected and transitions still stop at completion, the cause lies past the
  gate and needs its own plan.
- **Three seconds is calibrated against one game's save** — roughly 1.4 MB across 111
  files. A substantially larger save could scan longer; no capture of that exists.
- **The timing model is validated against one capture**, which it reproduces exactly.
- **The stall window and both ceilings remain unexercised**, now across seven consecutive
  plans.

### Reviewer verdict

Complete and correct against the plan, gates green, audit trail intact.

This note is **not** an approval. Approval is a human act and no human has reviewed this
branch. Nothing has been merged, tagged, or released.

STATUS: CHANGES_REQUESTED
