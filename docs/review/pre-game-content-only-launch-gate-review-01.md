# Review — pre-game-content-only-launch-gate (round 01)

Branch: `feat/pre-game-content-only-launch-gate`
Reviewed against: `docs/plans/2026-08-13_pre-game-content-only-launch-gate.md`
Commit reviewed: `2952a48 feat(syncthing): preserve content need counters`

## Verdict

Task 1's production change is correct and complete. Every item the plan asked for is
present: the three counters are parsed with `int_field`, `need_content_items` sums them,
`need_total_items` is untouched, and nothing in `py_modules/` or `src/` reads the new
property yet (verified by grep — the only production occurrence is the definition itself).

The `dataclasses.replace` fix for the frozen-dataclass trap is correct, and its test is
genuinely load-bearing. I verified that independently rather than taking the session log's
word for it: reverting `activity.py` to the field-by-field reconstruction makes
`test_local_index_update_preserves_content_need_counts` fail with
`need_files` reset from 3 to 0. That is exactly the failure the plan predicted.

One blocking problem: the other new test cannot fail.

## Gate status

Reported by the session log and consistent with what I re-ran: quality gates exit 0,
948 pytest passed, coverage 89.68% against 83% required, ruff clean, `ty` clean, frontend
33 files / 335 tests, typecheck and build pass. Working tree clean, no review notes deleted.

## Required changes

### 1. BLOCKING — `test_parse_folder_runtime_keeps_content_need_separate_from_deletes` passes against an implementation that does nothing

The fixture sets every content counter to zero:

```python
"needFiles": 0,
"needDirectories": 0,
"needSymlinks": 0,
"needDeletes": 46,
"needTotalItems": 46,
```

and then asserts `need_content_items == 0`. Because the `FolderRuntime` fields already
default to `0`, that assertion holds whether or not `parse_folder_runtime` reads the
payload at all. The `parse_folder_runtime({})` assertions have the same shape and are also
satisfied by the defaults.

I confirmed this by deleting the three new `int_field` lines from `parse_folder_runtime`
and running the **full** suite:

```text
948 passed in 22.37s
```

The entire test suite is green with the parsing removed. The counters are currently
unparsed as far as any test is concerned.

This is not pedantic. Task 2 makes `receive_needed` depend on `need_content_items`. If the
parsing silently returned zero, `receive_needed` would be `False` whenever `needBytes` is
zero — and per the plan's Context, `needBytes` reaches zero while a file is still an
unfinished temp file. That is the launch gate releasing while content is genuinely missing:
the safety-critical direction, and the one failure this whole plan exists to prevent.

Change the fixture to use distinct non-zero content counters so the assertion pins the
parsing to the payload, for example `needFiles=2`, `needDirectories=1`, `needSymlinks=1`,
`needDeletes=46`, `needTotalItems=50`, asserting `need_content_items == 4` and
`need_total_items == 50`. Use three different values so a copy/paste error mapping
`needSymlinks` onto `needFiles` also shows up.

Keep the `parse_folder_runtime({})` defaults assertion — it documents the omitted-field
case — but it does not count as coverage of the parsing.

Then re-run the mutation to prove the gate: delete the three `int_field` lines, confirm
this test now fails, restore, and record both outputs.

### 2. Non-blocking — the session log's `mutation_proof` overstates what was tested

The recorded mutation removed `need_content_items` *and* the parsing together, which fails
with `AttributeError` on the missing property rather than on wrong parsed values. That does
not isolate the parsing, which is why the gap above survived it.

Record the parsing mutation as its own entry, with the actual assertion failure rather than
an `AttributeError`, once finding 1 is fixed.

## Not required, recorded for accuracy

No other plan item for Task 1 is outstanding. Do not start Task 2 in this round — the plan
is one task per round, and Task 2 begins only after this round is reviewed again.

STATUS: CHANGES_REQUESTED
