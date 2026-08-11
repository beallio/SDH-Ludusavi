# Review 03 — syncthing-content-only-completion

**Round:** 3
**Branch:** `feat/syncthing-content-only-completion`
**Commit reviewed:** `196cc73` (`fix(syncthing): track content progress for upload stalls`)
**Prior review:** `1852528` (review 02, Task 2 changes requested)
**Reviewer:** orchestrator

## TASK 2: ACCEPTED

### Review 02 finding 1 — resolved

```python
@property
def aggregate_outstanding_need(self) -> int:
    # Stall progress must track the content that gates completion. Deletes are
    # diagnostic-only, so their progress cannot mask a stalled upload.
    return self.needed_bytes + self.needed_items
```

The comment states the reason rather than the change, which is what stops the deletes term
being added back by someone who reads the field name and assumes all three counters belong
in a total.

### Verification performed

Gates re-run independently by the orchestrator against `196cc73`:

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             922 passed (was 921), coverage 89.54%
worktree           clean
review notes       none deleted
```

### The test exercises the masking path

`test_post_game_content_stall_is_not_masked_by_other_peer_deletes` builds the exact
scenario from the finding: `DEV-A` content-stalled at `need_bytes=1000` while `DEV-B` is
content-complete and drains `need_deletes` 50 → 49. It asserts no stop on the first tick
and a terminal stop on the second, under a stall window patched to 10 seconds so the test
stays deterministic without sleeping.

Under the old three-term aggregate the total falls 1050 → 1049 purely on `DEV-B`'s pruning,
the decrease timestamp resets, and the stall never fires. Under the content-only aggregate
it holds at 1000 and the window elapses. The test therefore distinguishes the two
definitions rather than merely asserting the stall works.

### Mutation test — the gate is real

Restored the three-term aggregate:

```text
FAILED tests/test_watcher.py::test_post_game_content_stall_is_not_masked_by_other_peer_deletes
1 failed, 53 passed
```

Restored; tree clean and the full suite green at 922. Exactly one test fails, and it is the
one written for this defect — the masking path had no prior coverage, which is why the
regression survived review 01 and reached me only through reasoning about the plan.

### Scope

Two files, 25 insertions, 1 deletion. The stall window value, both ceilings, and every other
behaviour were left alone as instructed.

## Authorization

TASK 2: ACCEPTED
AUTHORIZED TASK: 3

Proceed with Task 3 — document the contract and record verification — as written in the
plan. Two additions to the session log beyond what the plan lists:

1. Record the review 02 plan defect: the plan's Task 2 step 4 instructed that
   `aggregate_outstanding_need` be left unchanged, on reasoning that Task 2 step 3
   invalidated by broadening `needed_deletes` to all peers. Caught in review, fixed in
   `196cc73`. Log it as a plan defect, not an implementation error.
2. Record the authorized classification-table row changes from Task 1 with their rationale,
   as the plan already requires.

Task 3 only. This is the final implementation task: mark the round complete and stop for
review. Do not author an approval note, finalize, merge, tag, or release. Approval is a
human act and the human approver has not yet reviewed this work.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 2 recorded above.

STATUS: CHANGES_REQUESTED
