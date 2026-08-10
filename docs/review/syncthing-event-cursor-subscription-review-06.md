# Review 06 — syncthing-event-cursor-subscription (final)

**Round:** 6
**Branch:** `feat/syncthing-event-cursor-subscription`
**Commit reviewed:** `623caea` (`docs(syncthing): restore Ludusavi timeout status details`)
**Prior review:** `44cf46e` (review 05, Task 5 changes requested)
**Reviewer:** orchestrator

## TASK 5: ACCEPTED — all five tasks complete

### Review 05 finding 1 — resolved exactly

The three clauses are back, verbatim, alongside the retained Syncthing sentence: the
5-minute status-check limit, failed-rather-than-hanging, and automatic paused-game resume.
Only `README.md` and the session log changed; nothing else in the repository was touched
while fixing it. The session log records the round-trip explicitly, so the removal and
restoration are visible in the audit trail rather than looking like they never happened.

### Verification performed

Gates re-run independently by the orchestrator against `623caea`:

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             917 passed, coverage 89.53%
worktree           clean
review notes       none deleted (6 notes present)
```

### Plan verification step 4 — live device evidence

This was blocked in reviews 01-05 because `steamdeck-legos` was unreachable. It is now
substantially satisfied. I ran an A/B on the device against live Syncthing v2.1.2: the
installed `0.4.4+cd50ab9` build as control, then this branch's modules copied to the
device's `/tmp` via `git archive`. Same folder, same 350 KB mutation, minutes apart.

```text
[control] get_event_cursor()=1261   RESULT cursor=1261  events=NONE  peer_completions=0
[branch]  get_event_cursor()=324    RESULT cursor=347
          events={StateChanged: 6, FolderScanProgress: 1, LocalIndexUpdated: 2,
                  LocalChangeDetected: 2, FolderSummary: 3, FolderCompletion: 9}
          peer_completions=3  all three peers at (100.0, 0, 0, 0)
```

The two cursor values are the defect stated in two numbers — 1261 from the unfiltered
subscription against 324 from the filtered one, at the same instant against the same
Syncthing. The control sat at 1261 receiving nothing, reproducing the original bug on
demand; the branch walked 324 → 347 and tracked all three peers.

Pass conditions from the plan: `FolderCompletion` count above zero — met, 9 events.
`len(peer_completions)` equal to the connected relevant peer count — met, 3 of 3.

The third condition, a peer observed with need counters above zero and *then* at 100 with
all counters zero, is **not evidenced by this run**. The probe printed only the final state
per peer, so the intermediate values inside those 9 events were not captured. The same code
path did produce it directly at 08:55 today — `WQ6UZOR (99.78%, 300000, 1, 0)` progressing
to `(100.0, 0, 0, 0)` — but that observation predates this branch's Task 3 and Task 4
commits. Treat the third condition as supported by prior observation rather than proven by
this run.

Device cleanup verified: `/tmp/branchprobe` removed, zero probe files remaining in
`/home/deck/ludusavi-backup`.

### Still deferred — do not read the above as full device acceptance

- **The packaged build was never installed.** The probe ran modules via `PYTHONPATH`, not
  the plugin ZIP under Decky. Packaging, loader startup, and the frontend are unexercised.
- **No post-game lifecycle run.** `handoff_confirmed`, the three-settled-sample quorum, the
  status strip, and the count-only diagnostics moving in a real log have not been observed.
  This still requires a game played and exited on device, deferred to a prerelease.
- **The new terminal status has never appeared on device.** Reaching it needs a genuinely
  stalled peer, which cannot be produced on demand.
- **The 90-second stall window and both ceilings remain single-observation judgement
  calls**, calibrated from the 2026-08-09 capture alone.

### Branch summary

```text
21 files changed, 2000 insertions(+), 89 deletions(-)

52eaf87  Task 1  seed event cursor from the filtered subscription
86ac8f8  Task 2  re-seed the cursor when a subscription resets
3a6e4c8  Task 3  stop a stalled post-game watch with a truthful reason
4920826  Task 4  split watch caps and surface incomplete upload status
ca86ac2  Task 5  correct event subscription and upload status contract
623caea  Task 5  restore Ludusavi timeout status details
```

Every round held to its authorized task's file list. Each of Tasks 1-4 was mutation-tested
by the orchestrator — the gate was broken deliberately and observed to fail before being
trusted — and each mutation was reverted with a clean tree confirmed afterwards.

### Reviewer verdict

The work is complete and correct against the plan, the gates are green, the audit trail is
intact across six review notes, and the central defect is now demonstrated fixed on real
hardware against a reproduced control.

This note is **not** an approval. Approval is a human act and no human has reviewed this
branch. Nothing has been merged, tagged, or released.

STATUS: CHANGES_REQUESTED
