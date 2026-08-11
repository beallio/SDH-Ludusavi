# Review 01 — syncthing-content-only-completion

**Round:** 1
**Branch:** `feat/syncthing-content-only-completion`
**Commit reviewed:** `874a62a` (`fix(syncthing): gate peer completeness on missing content only`)
**Plan commit:** `6b90f2e`
**Reviewer:** orchestrator

## TASK 1: ACCEPTED

### Scope

Exactly the two files Task 1 lists. 7 insertions, 8 deletions — the smallest possible
change for the behaviour. `summarize_peer_completions()` was left untouched as instructed,
even though it calls the changed predicate; that is Task 2's subject and keeping hands off
it this round is correct.

### Verification performed

Gates re-run independently by the orchestrator against `874a62a`:

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             919 passed (was 917), coverage 89.53%
worktree           clean
review notes       none deleted
```

### The production change

```python
# Syncthing's completion percentage is reduced by pending deletes, so retaining
# it would re-introduce delete gating through the back door.
return completion is not None and (completion.need_bytes > 0 or completion.need_items > 0)
```

Both clauses removed, and the comment records the non-obvious half — that dropping
`need_deletes` alone would have been useless while `completion < 100` remained, because the
percentage is itself reduced by pending deletes. That is the detail most likely to be
"simplified" back in by someone who reads the Syncthing docs and concludes the percentage
is a reasonable proxy for completeness.

### Table changes — authorized, and confined to what was authorized

The two rows the plan authorized are flipped and no others moved:

```text
(93.56119493792454, 0, 0, 0)   True -> False    authorized
(100.0,             0, 0, 19)  True -> False    authorized
(95.0,              0, 0, 12)  new,  False      the 2026-08-09 captured peer
(100.0,             1, 0, 99)  new,  True       content gates despite healthy percentage
```

The three rows the plan said must not move are unchanged: `(100.0, 8_942_011, 0, 0, True)`,
`(100.0, 0, 32, 0, True)`, and `(100.0, 0, 0, 0, False)`. This matters because the standing
scope rule forbids editing expected values, and the failure mode here would have been
flipping whatever went red rather than only the two rows with a stated rationale.

### Mutation test — both halves proven independently

Plan verification step 2 requires each clause to be pinned separately. I restored them one
at a time.

Restoring `need_deletes > 0`:

```text
FAILED …classifies_outbound_need[100.0-0-0-19-False]
FAILED …classifies_outbound_need[95.0-0-0-12-False]
2 failed, 57 passed
```

Restoring `completion < 100` instead:

```text
FAILED …classifies_outbound_need[93.56119493792454-0-0-0-False]
FAILED …classifies_outbound_need[95.0-0-0-12-False]
2 failed, 57 passed
```

Two different failure sets, so the two clauses are independently anchored — neither is
riding on the other, which was the specific risk the plan called out. The new
`(95.0, 0, 0, 12, False)` row is the dual anchor, failing under either restoration; that is
the captured device state and it is now the row that would catch a partial revert.

Predicate restored after each; 59 passed and the tree is clean.

### Process note (orchestrator, not implementer)

During mutation A my abort guard printed a warning but did not actually exit, so the edit
ran while the implementer's tmux session was still alive. No damage occurred — the tree is
clean, `HEAD` is still `874a62a`, and the session has since exited — but the window existed.
Mutation B used a real `exit 1` guard. Recording it because a silent near-miss is worth more
in the audit trail than an unrecorded one.

### Note carried forward (no action)

`summarize_peer_completions()` still accumulates all three counters only for peers the
predicate calls incomplete. As of this commit a deletes-only peer is no longer incomplete,
so its pending deletes have **already** stopped appearing in the diagnostics. That
regression is live on this branch right now and is exactly what Task 2 exists to fix. It is
not a defect in this round — the plan sequenced it deliberately — but the branch should not
be merged between rounds in this state.

## Authorization

TASK 1: ACCEPTED
AUTHORIZED TASK: 2

Proceed with Task 2 — keep deletes and completion visible in diagnostics — as written in the
plan. Task 2 only. Stop for review when its atomic commit and the round-complete marker are
in place. Do not begin Task 3 while waiting.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 1 recorded above.

STATUS: CHANGES_REQUESTED
