# Review 03 — syncthing-completion-stop-race (final)

**Round:** 3
**Branch:** `feat/syncthing-completion-stop-race`
**Commit reviewed:** `c5ab982` (`docs(syncthing): define completion stop ownership`)
**Prior review:** review 02, Task 2 accepted
**Reviewer:** orchestrator

## TASK 3: ACCEPTED — all three tasks complete

### Verification performed

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             933 passed, coverage 89.63%
worktree           clean
review notes       none deleted (3 notes present)
```

### The ownership rule is documented as a contract, not a description

The new spec section states the rule, the mechanism, and the consequence together:

> Peer completion only latches the backend's settled state; it never stops an owned
> post-game watch. … A stopped watcher freezes `latest_sample`; while it is still
> registered, `poll_watch()` returns that frozen sample and therefore repeats its
> timestamp. A backend-side stop before the frontend's quorum would silently prevent
> completion and incorrectly let the frontend's no-evidence ceiling publish the incomplete
> outcome.

That last sentence is the valuable one. It names the failure this branch fixed in terms a
future reader can act on, rather than leaving them to rediscover why the ordering matters.
Someone considering a backend-side stop will hit this paragraph first.

### README correctly untouched

The plan expected no `README.md` change, because the user-facing meaning of
`SYNCTHING COMPLETE` is unchanged by this fix — the guarantee was already "at least one
connected device", and this branch only makes it actually publish. No README change was
made, and the session log records that the no-change decision was deliberate rather than an
omission.

### Session log

Complete against the plan: per-task RED proofs, Task 1-2 hashes with a `task_3_subject`
rather than a self-referential hash, review-note paths, validation results, and four
deferred items. It records the wrong-test-shape pattern and that Task 2's harness exists to
close it.

The deferred entries are honest about what the captured failure did and did not prove —
"the captured 2026-08-11 failure proves only that the frontend ceiling fires as designed
after a backend-side premature stop" — rather than claiming the boundary values are now
validated.

### Branch summary

```text
8 files changed, 1034 insertions(+), 42 deletions(-)

b349da3  Task 1  let the frontend own the completion stop
3ee4389  Task 2  cover the manager poll sequence after completion
c5ab982  Task 3  define completion stop ownership
```

Three rounds, three tasks, no correction rounds — the first branch in this sequence to run
clean. Every gate was mutation-tested before being trusted, and Task 1's mutation was
verified in **both** parametrised modes because normal mode is the one most users run and
was the worse of the two on hardware.

### The control worth remembering

Reapplying the original defect makes the new harness fail with the production symptom
reproduced exactly:

```text
E       assert [4.0, 4.0, 4.0] == [4.0, 5.0, 6.0]
```

Frozen timestamps, three identical polls, no quorum. That defect passed 930 tests on the
predecessor branch. It now fails one.

### Deferred — this is not fixed until a device run says so

- **A post-game device run is required**, not optional. Expected signature:
  `SYNCTHING COMPLETE` within roughly twenty seconds of handoff while a transition line
  still reports non-zero `needed_deletes`, and **no** `SYNCTHING UPLOAD INCOMPLETE` at the
  300-second mark. The regression this branch fixes is live in `dev` at `7a0d570` and in
  the published prerelease `v0.4.4-dev.g7a0d570`.
- **Debug extended observation has no device evidence after this fix.** It failed once on
  hardware in a way unit tests did not predict; the next device run is its first real test.
- **The stall window and both ceilings remain unexercised** across five consecutive plans.
- **The accepted `stop_watch()` race** from the predecessor branch is unchanged.

### Reviewer verdict

Complete and correct against the plan, gates green, audit trail intact.

This note is **not** an approval. Approval is a human act and no human has reviewed this
branch. Nothing has been merged, tagged, or released.

STATUS: CHANGES_REQUESTED
