# Review 06 — syncthing-first-peer-completion (final)

**Round:** 6
**Branch:** `feat/syncthing-first-peer-completion`
**Commit reviewed:** `466f496` (`docs(syncthing): define completion as first confirmed peer`)
**Prior review:** review 05, Task 2 accepted
**Reviewer:** orchestrator

## TASK 3: ACCEPTED — all three tasks complete

### Verification performed

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             930 passed, coverage 89.61%
worktree           clean
review notes       none deleted (6 notes present)
```

### The README does not soften the weaker guarantee

This was the part most likely to be quietly hedged, so it was the first thing I checked:

> **Syncthing Complete**: After a backup, the watched folder has settled on the Steam Deck
> and **at least one** currently connected device that shares it has reported the backup as
> received in three consecutive checks. **Other connected devices may still be catching
> up when this status appears**; the plugin does not wait for them to finish deleting older
> snapshots. This also does not guarantee the save has reached a configured device that is
> disconnected or offline.

It states the weaker guarantee plainly, names the settling window in user terms, and keeps
both prior caveats. A user reading only this line would not be misled about what COMPLETE
now means.

### Specs and session log

Both specs describe the first-confirmed-peer rule with the three-observation window, record
that other peers' counts remain diagnostics rather than gates, and document that debug
logging extends observation without changing the published status.

The session log carries all three items review 05 required, verified by content rather than
by the implementer's assurance: the plan defect and its no-reporting-channel deadlock, the
note that neither `status` nor `recover` could detect it, the unreachability finding, the
`stop_all` leak, and the accepted race.

### Branch summary

```text
15 files changed, 1710 insertions(+), 239 deletions(-)

7a19f6b  Task 1  complete on the first confirmed peer
b0f64b1  Task 2  keep observing peers under debug logging
133a2e0  Task 2  preserve debug peer observation        (review 03 fix)
0eee3b3  Task 2  stop debug observation on teardown     (review 04 fix)
466f496  Task 3  define completion as first confirmed peer
```

Six review rounds, four of them on Task 2. Every behaviour change was mutation-tested by the
orchestrator before being trusted, and both gate directions were pinned where a gate
existed.

### What this branch cost, and why

Recording this because the pattern is more useful than the fixes.

Two rounds were lost to a defect in my own plan: Task 2 step 1 told an agent with no
reporting channel to "stop and report", so halting and completing became the same action.
The round-complete marker was written twice with no code produced, and neither `status` nor
`recover` could tell — a marker at a valid HEAD with a clean tree is indistinguishable from
a finished round. Only diffing the branch against the marker caught it.

Two further rounds were lost to tests whose **setup** modelled a sequence the system never
performs — extended observation tested against `SyncthingWatch` directly while the frontend
stops the watch through the RPC, then `stop_all` tested on a watch that `stop_watch` had
never popped. In both cases the assertions were correct and the arrangement was wrong, which
is harder to catch than a wrong assertion because everything reads as green and sensible.
Both were found by running the production sequence by hand rather than by reading tests.

### Deferred and explicitly not verified

- **No device run has exercised this branch.** The expected signature on a prerelease is
  `SYNCTHING COMPLETE` published while a transition line still reports `incomplete_peers`
  greater than zero, and a handoff-to-complete time near +18s against the +39.4s baseline
  measured on 2026-08-11.
- **Extended debug observation has never run on device.** Its unit coverage is real; its
  behaviour against a live slow peer is untested, and it is the feature most affected by the
  RPC-path gap found in review 03.
- **The stall window and both ceilings remain unchanged and unexercised**, now across four
  consecutive plans.
- **The accepted race in `stop_watch()`** is recorded in the session log and left open.
- **The weaker guarantee is not verifiable by test.** Whether "at least one connected device
  has the save" suits how these machines are actually used is the user's judgement.

### Reviewer verdict

Complete and correct against the plan, gates green, audit trail intact across six review
notes including two rounds that corrected defects in the plan itself.

This note is **not** an approval. Approval is a human act and no human has reviewed this
branch. Nothing has been merged, tagged, or released.

STATUS: CHANGES_REQUESTED
