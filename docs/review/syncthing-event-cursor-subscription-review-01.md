# Review 01 — syncthing-event-cursor-subscription

**Round:** 1
**Branch:** `feat/syncthing-event-cursor-subscription`
**Commit reviewed:** `52eaf87` (`fix(syncthing): seed event cursor from the filtered subscription`)
**Plan commit:** `73d6e4c`
**Reviewer:** orchestrator

## TASK 1: ACCEPTED

### Scope

Exactly the two files Task 1 lists: `py_modules/sdh_ludusavi/syncthing/activity.py` and
`tests/test_activity.py`. 36 insertions, 1 deletion — the deletion is the substituted
`params=` line. Nothing outside scope, and no existing assertion was touched.

### Verification performed

Gates re-run independently by the orchestrator against `52eaf87`:

```text
pnpm test          334 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             909 passed (was 907), coverage 89.42% (gate 83%)
worktree           clean
review notes       none deleted
```

### The production change

`get_event_cursor()` now sends `"events": EVENT_TYPES` alongside its existing `since`,
`limit`, and `timeout` parameters, so it is served by the same subscription
`get_events()` polls. The existing non-list guard and its test are untouched.

The required comment is present and states the mechanism rather than the symptom: `id` is
scoped to the subscription selected by `events=`, `since` matches that scoped `id`, and
`globalID` is process-wide. That is the detail that makes the parameter look redundant to a
future reader, and it is now recorded at the call site.

### Mutation test — the gate is real

Plan verification step 2 requires proving the Task 1 test can actually fail. I ran it
rather than taking it on trust: removed `"events": EVENT_TYPES` from `get_event_cursor()`,
then ran the focused suite.

```text
>       assert cursor_params["events"] == event_params["events"]
E       KeyError: 'events'
FAILED tests/test_activity.py::test_get_event_cursor_uses_same_subscription_filter_as_event_reads
1 failed, 56 passed
```

Restored the file; 57 passed and `git status` is clean. The gate catches the exact
regression it exists for.

### Test quality

`test_get_event_cursor_uses_same_subscription_filter_as_event_reads` does the thing the
plan insisted on and that most implementations get wrong: it records both calls through a
mock and compares `cursor_params["events"]` to `event_params["events"]`. It never mentions
`EVENT_TYPES`. A hardcoded copy of that constant would keep passing while the two call
sites drifted apart, which is precisely the defect being fixed here — this version cannot.

It also fails correctly in the both-sites-broken case, since the missing key raises rather
than comparing two absent values. The only scenario it would not catch is both call sites
carrying the same *wrong* filter, which is a different defect class and out of scope.

`test_get_event_cursor_uses_subscription_scoped_id_not_global_id` seeds `id=247/248`
against `globalID=1597/1598` and asserts the cursor is `248`. Using visibly divergent
values from the real device capture makes the intent legible: a reader immediately sees
which field is being selected and why it matters.

### Note carried forward (no action)

The unit suite cannot demonstrate that events now reach the watcher — it was green
throughout the entire period the stream was dead. Only the live probe in plan verification
step 4 proves the defect is fixed, and it must run after the Task 2 and 3 mutation tests.
`steamdeck-legos` was unreachable at 09:24 today; if it is still down when Task 5 completes,
that step is a blocked verification and must be reported as such, never recorded as passed.

## Authorization

TASK 1: ACCEPTED
AUTHORIZED TASK: 2

Proceed with Task 2 — guard against subscription resets — as written in the plan. Task 2
only. Stop for review when its atomic commit and the round-complete marker are in place. Do
not begin Task 3 or prepare its tests while waiting.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 1 recorded above.

STATUS: CHANGES_REQUESTED
