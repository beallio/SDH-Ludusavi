# Review 02 — syncthing-debug-observation-exit (final)

**Round:** 2
**Branch:** `feat/syncthing-debug-observation-exit`
**Commit reviewed:** `16ef01c` (`docs(syncthing): define the debug observation exit contract`)
**Prior review:** review 01, Task 1 accepted
**Reviewer:** orchestrator

## TASK 2: ACCEPTED — both tasks complete

### Verification performed

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             946 passed, coverage 89.69%
worktree           clean
review notes       none deleted (2 notes present)
```

### The spec replaces the ambiguity that permitted the defect

Before:

> self-terminates when every peer finishes or an existing terminal boundary is reached

After:

> only after that release, while connected relevant peers still have pending deletes; it
> self-terminates cleanly when those deletes drain or at the post-game hard ceiling.
> `incomplete_peers` is already zero at this released diagnostic boundary and therefore
> cannot safely decide the exit.

"Every peer finishes" was true of the broken code as much as the fixed code — under the
content-only rule every peer *had* finished, which is why the condition fired instantly. The
replacement names the actual quantity, the actual boundary, and the trap. That last sentence
is the durable part: it tells the next reader why the obvious exit test is the wrong one.

### Session log

Complete against the plan. It records that this defect also explains the 2026-08-11 23:25
result previously logged as unexplained, and keeps the distinction that the debug-gate fix
shipped for that was a real but separate defect — so the audit trail neither buries the
earlier misdiagnosis nor overstates it.

No `README.md` change, recorded as deliberate: extended observation is an opt-in diagnostic
that never alters published status.

### Branch summary

```text
6 files changed, 791 insertions(+), 8 deletions(-)

a46c7a9  Task 1  observe until pending deletes drain
16ef01c  Task 2  define the debug observation exit contract
```

Two rounds, two tasks, no correction rounds — third clean branch in a row. Three mutations
on the behavioural task, each producing a distinct predicted failure set.

### Risk profile — why this one is different

Every other branch in this sequence changed user-visible behaviour and needed device
verification before it could be trusted. This one does not. Extended observation runs only
under Debug Logging and never alters the published sample; the plan required and the tests
assert that the sample is identical in both modes. A wrong result here costs a diagnostic
tail, not a status a user acts on.

That is the reason this branch does not gate the stable promotion.

### Deferred and explicitly not verified

- **No device run has exercised this.** Expected signature on a Debug Logging run:
  transition lines continuing **after** `SYNCTHING COMPLETE`, tailing off as
  `needed_deletes` reaches zero. On 2026-08-12 11:26 they stopped dead at completion with 27
  deletes outstanding.
- **The ceiling path becomes reachable for the first time** with this change and has never
  been hit on device. Its unit coverage is real; its on-device behaviour is not.
- **A released watch can now live up to the hard ceiling** — a longer-lived background
  thread than anything previously shipped, though only with Debug Logging enabled.
- **The stall window remains unexercised**, now across eight consecutive plans, and this
  change does not make it reachable for released watches.

### Reviewer verdict

Complete and correct against the plan, gates green, audit trail intact.

This note is **not** an approval. Approval is a human act and no human has reviewed this
branch. Nothing has been merged, tagged, or released.

STATUS: CHANGES_REQUESTED
