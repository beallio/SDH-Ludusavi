# Review 02 — syncthing-content-only-completion

**Round:** 2
**Branch:** `feat/syncthing-content-only-completion`
**Commit reviewed:** `83045bc` (`feat(syncthing): report pending deletes without gating completion`)
**Prior review:** `df1232a` (review 01, Task 1 accepted)
**Reviewer:** orchestrator

## TASK 2: CHANGES REQUESTED

The diagnostics work is correct and the tests are strong. But broadening `needed_deletes`
to all peers silently changed the meaning of a value the stall detector consumes, and the
plan's own instruction to leave that detector alone is unsound as a result. This is my
error in the plan, not a deviation by you.

### Verification performed

Gates re-run independently by the orchestrator against `83045bc`:

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             921 passed (was 919), coverage 89.54%
worktree           clean
review notes       none deleted
```

### What is correct

`summarize_peer_completions()` now accumulates `needed_deletes` for every connected
relevant peer with a completion record, while `needed_bytes` and `needed_items` stay scoped
to content-incomplete peers. `peers_pending_deletes` is added, the dataclass carries it, and
the transition log line reports it. The review 01 regression — deletes vanishing from
diagnostics the moment Task 1 landed — is closed.

The two tests are well chosen. The diagnostics test pins all seven counters at once with a
three-peer fixture where the counts genuinely differ (`incomplete_peers=1`,
`peers_pending_deletes=2`, `needed_deletes=16`), so a change to any one accumulation rule
fails it. And `test_post_game_completion_settles_at_content_boundary_not_pruning_boundary`
is the plan's verification step 4 negative control implemented as a permanent test: it
asserts `uploading` while content is outstanding, then `settled` once
`needed_bytes`/`needed_items` reach zero **with deletes still pending**, then still settled
as deletes drain. Under the pre-Task-1 predicate the middle assertion fails, which is what
makes it a control rather than decoration.

### Finding

1. **Scope `aggregate_outstanding_need` to content.** It is still:

   ```python
   return self.needed_bytes + self.needed_items + self.needed_deletes
   ```

   Before this round `needed_deletes` only counted peers that were themselves incomplete,
   so the plan's instruction to leave this property alone was safe. Now it counts deletes
   across **all** connected relevant peers, including peers that are fully content-complete.
   The stall detector consumes this value as its progress signal, and the combination
   defeats it.

   Concretely: peer A is content-stalled with `needBytes` frozen at 1000, while peer B is
   content-complete and draining `needDeletes` 50 → 49 → 48. `incomplete_peers` is 1, so
   `_stop_if_post_game_upload_incomplete()` runs. The aggregate falls on every tick because
   of B's pruning, so `_last_outbound_need_decrease_monotonic` resets continuously and the
   90-second stall window never elapses — while nothing about A's stalled upload has
   improved. The watch then runs to the frontend ceiling instead of being caught by stall
   detection.

   Fix: make the property `self.needed_bytes + self.needed_items`. The detector should
   measure progress on exactly what gates completion, which after Task 1 is content. Add a
   comment saying so, because the omission of deletes will otherwise look like an oversight.

   Add a test that fails against the current definition: a content-stalled peer alongside a
   peer whose deletes are draining must still trip the stall window. Verify it fails before
   the fix — if it passes with the current three-term property, it is not exercising the
   masking path.

   Files for this round remain Task 2's: `_types.py` and `tests/test_watcher.py`. Do not
   touch the stall window value, the ceilings, or any other behaviour.

### Note on the plan

The plan's Task 2 step 4 told you to leave `aggregate_outstanding_need` alone, with reasoning
that assumed `needed_deletes` stayed scoped to incomplete peers. Step 3 of the same task
invalidated that assumption. You followed the plan correctly; the plan was wrong. Record
this in the Task 3 session log as a plan defect caught in review, not as an implementation
error.

## Authorization

TASK 2: CHANGES REQUESTED

Fix finding 1 only. Do not begin Task 3, do not revisit Task 1, and do not author an
approval note, finalize, merge, tag, or release.

STATUS: CHANGES_REQUESTED
