# Review 01 — syncthing-first-peer-completion

**Round:** 1
**Branch:** `feat/syncthing-first-peer-completion`
**Commit reviewed:** `7a19f6b` (`feat(syncthing): complete on the first confirmed peer`)
**Plan commit:** `efd3001`
**Reviewer:** orchestrator

## TASK 1: ACCEPTED

### Verification performed

Gates re-run independently by the orchestrator against `7a19f6b`:

```text
pnpm test          335 passed
pnpm run build     ok
ruff check/format  clean
ty check           ok
pytest             921 passed, coverage 89.56%
worktree           clean
review notes       none deleted
```

Note the pytest count moved 922 → 921 while coverage rose. That is a net effect of tests
being consolidated rather than dropped; see the coverage audit below, which I ran before
accepting rather than inferring from the totals.

### The confirmation predicate

```python
mutation_observed_at = self.local_activity.outbound_index_observed_monotonic
if not self._peer_completion_tracking or mutation_observed_at == 0:
    self._outbound_peer_confirmation_streak = 0
    return False

has_fresh_content_complete_peer = any(
    completion is not None
    and not peer_completion_is_incomplete(completion)
    and completion.observed_monotonic >= mutation_observed_at
    ...
)
```

Correct on every branch I checked. No mutation armed means nothing to confirm, so it
returns not-pending and resets the streak rather than holding `uploading` true forever —
that was the failure mode of the very first device run in this series and it is explicitly
avoided here. Freshness uses `>=` against the mutation timestamp, consistent with the
staleness check elsewhere, and the same-batch case stays covered by the 2.5-second
observation hold, which remains in the `uploading` expression.

`compute_activity_status()` is now pure with respect to peer state: it takes a single
`outbound_peer_confirmation_pending` boolean and no longer imports
`summarize_peer_completions`. The streak lives on the watcher beside the existing
`_last_outbound_need` fields, exactly as the plan specified.

### Coverage audit — three tests were removed

`test_connected_peer_completion_classifies_outbound_need` (the parametrised table),
`test_peer_completion_must_be_fresh_after_watched_index_mutation`, and
`test_each_connected_relevant_peer_must_complete_the_mutation` are gone from
`tests/test_activity.py`. The third pinned all-peers semantics and is legitimately
obsolete. The first two pinned the content-only predicate and the freshness rule — behaviour
we shipped yesterday and confirmed on device — so their removal needed proving, not
assuming.

They are no longer reachable in their old form, because `compute_activity_status()` no
longer receives `peer_completions`. But `peer_completion_is_incomplete()` now has **no
direct test reference anywhere in the suite**, so I verified by mutation that it is still
pinned indirectly. Restoring the `need_deletes > 0` clause:

```text
FAILED test_peer_completion_diagnostics_keep_deletes_visible_without_gating_completion
FAILED test_post_game_completion_settles_at_content_boundary_not_pruning_boundary
2 failed, 919 passed
```

Restoring the `completion < 100` clause instead produces the same two failures. Both halves
of yesterday's fix therefore remain anchored, by two tests that survived from the previous
plan. Coverage moved; it was not lost. I am recording the audit rather than the conclusion
because the totals alone would not have shown this.

### Mutation tests — both plan gates proven

**Settling window** (`OUTBOUND_CONFIRMATION_OBSERVATIONS = 3 -> 1`):

```text
FAILED test_post_game_first_fresh_peer_requires_three_observations_before_settling
FAILED test_post_game_peer_completion_regression_resets_the_confirmation_streak
FAILED test_captured_peer_sequence_completes_before_the_straggler
FAILED test_newly_connected_peer_waits_for_a_fresh_completion_and_disconnects_stop_gating
FAILED test_post_game_completion_settles_at_content_boundary_not_pruning_boundary
FAILED test_malformed_completion_event_keeps_last_good_state_and_never_leaks_payload
6 failed, 106 passed
```

The blip regression test is among them, which is what the plan required: the window is
genuinely exercised and the suite distinguishes one observation from three.

**Completion boundary** (`any(...)` -> `all(...)`, restoring all-peers semantics):

```text
FAILED test_post_game_first_fresh_peer_requires_three_observations_before_settling
FAILED test_post_game_peer_completion_regression_resets_the_confirmation_streak
FAILED test_captured_peer_sequence_completes_before_the_straggler
3 failed, 109 passed
```

`test_captured_peer_sequence_completes_before_the_straggler` is the behavioural heart of
this plan and it fails against the old semantics, so it is asserting the new behaviour
rather than passing under either. Both mutations reverted; suite green at 59 in the focused
file and 921 overall, tree clean.

The activity-level `test_confirmed_first_peer_allows_settlement_while_another_peer_is_incomplete`
does not fail under the `all(...)` mutation, which is expected — it takes the confirmation
boolean as a parameter, so it pins the classifier's contract rather than the watcher's
computation. The watcher-level equivalent covers that side.

### Process note

The first implementer attempt exited after committing the plan but before implementing;
`supervise-implementer` relaunched and attempt 2 completed the task. First relaunch of this
session — recording it because the supervisor's restart path had not previously been
exercised here, and it behaved correctly.

## Authorization

TASK 1: ACCEPTED
AUTHORIZED TASK: 2

Proceed with Task 2 — keep observing under debug logging — as written in the plan. Note its
step 1 in particular: confirm by inspection that `sdh_ludusavi.*` loggers actually inherit
the level `service._apply_log_level()` sets on the decky logger. If they do not, stop and
report it as a blocking finding rather than adding a setting or a service reference. Task 2
only. Stop for review when its atomic commit and the round-complete marker are in place.

The trailer below is the engine's mechanical resume signal. It does not retract the
acceptance of Task 1 recorded above.

STATUS: CHANGES_REQUESTED
