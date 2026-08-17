# Review — pre-game-content-only-launch-gate (round 02)

Branch: `feat/pre-game-content-only-launch-gate`
Reviewed against: `docs/plans/2026-08-13_pre-game-content-only-launch-gate.md`
Commit reviewed: `431bece test(syncthing): strengthen content need parsing coverage`

## Verdict

Both round-01 findings are resolved. **Task 1 is accepted.** Proceed to Task 2.

Finding 1 is fixed and I verified the gate independently rather than reading the session
log. With the three `int_field` calls deleted from `parse_folder_runtime`, the full suite
now reports:

```text
1 failed, 947 passed in 22.33s
AssertionError: assert 0 == 2
  where 0 = FolderRuntime(..., need_files=0, ...).need_files
```

That is the same failure the session log records, and it replaces the 948-passed result the
same mutation produced last round. The parsing is now pinned to the payload.

The fixture uses three distinct values (2/3/5) and asserts each field individually as well
as the sum, so a transposed mapping between `needFiles`, `needDirectories` and
`needSymlinks` fails too. That is stronger than the review asked for.

Finding 2 is fixed: `mutation_proof` now carries `local_index_update` and
`content_counter_parsing` as separate entries, and the parsing entry records the real
assertion failure rather than an `AttributeError`.

## Gate status

Working tree clean, no review notes deleted, review note 01 committed as an audit record.
Full suite green at 948 passed when unmutated.

## Required changes

Implement **Task 2 only** — make `receive_needed` content-only — exactly as the plan
specifies. Do not start Task 3 in this round.

The plan gives the full instructions; these are the points I will be checking, so treat
them as the acceptance criteria:

1. `receive_needed` tests `runtime.need_bytes > 0 or runtime.need_content_items > 0`, with
   `need_total_items` and `need_deletes` both gone from the expression.
2. The comment records *why* `need_total_items` cannot be used: Syncthing's
   `Counts.TotalItems()` includes `Deleted`, so it would reintroduce delete gating.
3. All three red tests from the plan exist, including the safety case — `need_bytes=0` with
   `need_files=1` must still produce `receive_needed is True`. That case is the one that
   protects against releasing the gate on an unfinished temp file, and it must fail before
   your change lands and pass after.
4. The post-game regression test is present and shows post-game behaviour is unchanged.
5. The mutation proof isolates *this* change: revert only the `receive_needed` expression,
   show which tests go red with their actual assertion output, restore, show green.

Record red-before and green-after output verbatim in the session log, as you did this round.

## Note on status

This note is `CHANGES_REQUESTED` because the plan as a whole is incomplete — four more
tasks remain after Task 2 — not because anything in Task 1 is outstanding. Task 1 needs no
further work.

STATUS: CHANGES_REQUESTED
