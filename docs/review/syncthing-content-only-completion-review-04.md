# Review 04 — syncthing-content-only-completion (final)

**Round:** 4
**Branch:** `feat/syncthing-content-only-completion`
**Commit reviewed:** `faa9044` (`docs(syncthing): define completion as content received`)
**Prior review:** `6132c13` (review 03, Task 2 accepted)
**Reviewer:** orchestrator

## TASK 3: ACCEPTED — all three tasks complete

### Verification performed

Gates re-run independently by the orchestrator against `faa9044`:

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             922 passed, coverage 89.54%
worktree           clean
review notes       none deleted (4 notes present)
```

### Documentation

The `README.md` change is the one users will actually read, and it says the right thing:
every connected device that shares the folder has **received the backup**, and "The plugin
does **not** wait for those devices to finish deleting older snapshots." The disconnected
and offline caveat is preserved. One line changed; the surrounding status list is untouched.

Both specs now state that the gate is content-only, that `needDeletes` and the completion
percentage are reported but never gate, and — importantly — *why* the percentage had to go,
citing the `completion=95 need=0/0/12` capture. The stall-window language was updated from
"aggregate peer need" to "aggregate content need", which matters because the old phrasing
would now describe the code incorrectly.

The specs also record that the stall window and both ceilings are deliberately unchanged,
with the reason and an explicit statement that their suitability for the content-only
workload is unverified and awaits a run that reaches a boundary. That is the honest framing:
they were calibrated against a workload that no longer exists.

### Session log

Complete against the plan, and it records both things review 03 required:

- **The plan defect**, described as such: Task 2 step 3 broadened `needed_deletes` to all
  peers while step 4 of the same task said to leave `aggregate_outstanding_need` alone.
  Caught in review, corrected in `196cc73`. Logged as a plan defect rather than an
  implementation error, which is what it was.
- **The authorized table changes** with per-row rationale, and the rows that had to stay
  `True` named explicitly.

RED proofs cite the durable mutation evidence from reviews 01 and 03 with exact failing
parametrised ids and tallies, rather than asserting that tests were written first. Task 1-2
commit hashes are present with a `task_3_subject` instead of a self-referential hash.

### Branch summary

```text
12 files changed, 1117 insertions(+), 40 deletions(-)

874a62a  Task 1  gate peer completeness on missing content only
83045bc  Task 2  report pending deletes without gating completion
196cc73  Task 2  track content progress for upload stalls   (review 02 fix)
faa9044  Task 3  define completion as content received
```

Every round held to its authorized file list. Each behaviour change was mutation-tested by
the orchestrator — the gate broken deliberately and observed to fail before being trusted,
then reverted with a clean tree confirmed. Task 1's two clauses were mutated independently
and produced different failure sets, so neither is riding on the other.

### What this changes in practice

On the captured 2026-08-10 21:29 device run, `SYNCTHING COMPLETE` would have published at
roughly 21:29:32 — about 24 seconds after handoff, when content reached all three peers —
instead of running four and a half more minutes through snapshot pruning and ending at the
300-second ceiling on `LOCAL BACKUP SAVED - SYNCTHING UPLOAD INCOMPLETE` with four deletes
left.

### Deferred and explicitly not verified

- **No device run has exercised this branch.** The 21:29 capture was produced by
  `0.4.4-dev.gccb9ef7`, which predates every commit here. The expected sequence to confirm
  on a new prerelease is `SYNCTHING UPLOADING` while `needed_bytes`/`needed_items` fall,
  then `SYNCTHING COMPLETE` once they reach zero, with `needed_deletes` still non-zero in
  the final transition line and no `SYNCTHING UPLOAD INCOMPLETE`.
- **The stall window and both ceilings are unchanged and unexercised.** Their suitability
  for the content-only workload is unknown.
- **`peers_pending_deletes` has never appeared in a real device log**, only in tests.
- **No frontend change was made.** `syncthing_upload_incomplete` still exists and can still
  fire; this plan only makes it far less likely.

### Reviewer verdict

Complete and correct against the plan, gates green, audit trail intact across four review
notes including one round that corrected a defect in the plan itself.

This note is **not** an approval. Approval is a human act and no human has reviewed this
branch. Nothing has been merged, tagged, or released.

STATUS: CHANGES_REQUESTED
