# Plan: Explicit Game Selection Beats Steam Auto-Selection (explicit-selection-beats-autoselect)

## Context

While a game is running, the QAM game dropdown cannot be changed. Picking a
different game visibly reverts to the running game within a few milliseconds.

Confirmed on device (v0.4.0, Steam Deck) with `Warhammer 40,000: Space Marine`
running. Pulled logs show the exact sequence:

```text
23:46:32,566  qam_closed:  selected_game="Warhammer 40,000: Space Marine"
23:46:33,303  settings_change_requested: value="Transformers: Devastation"
23:46:33,309  Selected game changed to Transformers: Devastation
23:46:33,323  qam_opened:  selected_game="Transformers: Devastation"
23:46:33,323  QAM current game selected: match=Warhammer 40,000: Space Marine
                 source=focused appID=3213262460 reason=name
23:46:33,334  settings_change_persisted: value="Transformers: Devastation"
23:46:34,104  qam_closed:  selected_game="Warhammer 40,000: Space Marine"
```

Root cause: opening the dropdown makes the QAM report itself not visible, and
choosing an option makes it visible again. That false close/open transition
re-arms `pendingCurrentGameSelection` in the first effect of
`src/components/qam/useSteamContext.ts` (`:67-77`), and the second effect
(`:92-108`) then calls `selectCurrentSteamGameIfAvailable`, which overwrites the
display with the running game.

The user's choice is not lost — `settings_change_persisted` succeeds, and the
persisted preference is correct. Only the ephemeral displayed selection is
overwritten. Because status, last-operation, Browse Backups, and the per-game
sync toggle all follow the *displayed* game, the panel becomes inconsistent with
the saved preference.

This predates the selected-game-view-state change: previously auto-selection
routed through `setSelectedGame` → `patchSettings`, which overwrote the display
the same way (and additionally clobbered the persisted value).

Intended outcome: a deliberate dropdown choice must beat Steam-context
auto-selection. A genuine QAM close and reopen must still auto-select the
running game — that behavior is wanted and must be preserved.

Relevant existing code:

- `src/components/qam/qamOpenSelection.ts` — pure decision function
  `resolveQamOpenSelection`, already unit-tested in `qamOpenSelection.test.ts`.
- `src/components/qam/useSteamContext.ts` — arms `pendingCurrentGameSelection`
  on the visibility transition (`:67-77`); consumes it and auto-selects
  (`:92-108`).
- `src/components/qam/LudusaviContent.tsx` — wires `useSteamContext` (`:154-162`)
  and passes `onGameChange` to the dropdown (`:370`, `:564`).
- `src/components/qam/GameSettingsSection.tsx:67-68` — the `DropdownItem` whose
  `selectedOption` is the displayed game and whose `onChange` is `onGameChange`.

**Slug used throughout this plan:** `explicit-selection-beats-autoselect`

---

## Orchestration Contract

**Slug:** `explicit-selection-beats-autoselect`

**Plan file:**

```text
docs/plans/2026-07-20_explicit-selection-beats-autoselect.md
```

**Implementation branch:**

```text
feat/explicit-selection-beats-autoselect
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/explicit-selection-beats-autoselect_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/explicit-selection-beats-autoselect_finalized
```

**Review notes:**

```text
docs/review/explicit-selection-beats-autoselect-review-*.md
```

Each review note ends with exactly one status trailer:

```text
STATUS: CHANGES_REQUESTED
```

or:

```text
STATUS: APPROVED
```

---

## Required Agent Protocol

1. Use the **implementer** skill.
2. Work from the repository root.
3. Branch from `dev`.
4. Commit this plan as the first commit on the implementation branch.
5. Follow TDD where behavior changes are testable.
6. Run quality gates before marking any round complete.
7. Do not write your own review.
8. Do not create files under `docs/review/`.
9. Do not delete files under `docs/review/`.
10. Review notes are durable audit records and must be committed.
11. Resolving a review note means:
    - implement the requested changes;
    - run quality gates;
    - commit the code/docs changes;
    - commit the review note itself if it is not already committed;
    - recreate the round-complete marker.
12. After finalization, stop polling and exit cleanly.

---

## Scope discipline

- Implement only the units the plan lists. Do not modify files outside the plan's scope.
- Do not change runtime behavior beyond what the plan specifies. A `refactor` or
  `cleanup` commit must preserve observable behavior.
- Never edit a test's expected value to make a behavior change pass. If a test
  legitimately must change, that change must be required by the plan or a review
  note, and you must record the rationale in the session log.
- If you spot an unrelated improvement, do not make it here — note it in the
  session log for a separate plan.

---

## Setup

Start from `dev`:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/explicit-selection-beats-autoselect
```

Commit this plan first:

```bash
git add docs/plans/2026-07-20_explicit-selection-beats-autoselect.md
git commit -m "docs(plan): add explicit-selection-beats-autoselect implementation plan"
```

---

## Implementation Tasks

Work the tasks in order. Write the failing test first for every behavior change.

The fix is a one-shot suppression signal: a deliberate dropdown choice consumes
the next auto-selection arm. Do not add timers, and do not try to measure how
long the QAM was closed — the false close/open transition is indistinguishable
from a real one by duration.

### Design (fixed — use exactly this)

`resolveQamOpenSelection` gains one input field, `explicitSelectionPending`.
When it is true the function returns `"consume"`, which clears the pending arm
without auto-selecting. Precedence is checked **after** the existing `"wait"`
guard and **before** the `operationInProgress` check.

### Task 1 — Extend the pure decision function

Tests: `src/components/qam/qamOpenSelection.test.ts`.

1. Add `explicitSelectionPending: boolean` to `QamOpenSelectionInput` in
   `src/components/qam/qamOpenSelection.ts`.
2. In `resolveQamOpenSelection`, after the existing `"wait"` guard, return
   `"consume"` when `input.explicitSelectionPending` is true.
3. Leave the rest of the ordering unchanged.

Required test cases:

- explicit selection pending while visible with games and no operation →
  `"consume"` (not `"select"`);
- explicit selection pending but not visible → still `"wait"`, so the flag is
  not consumed while the panel is hidden;
- explicit selection pending together with `operationInProgress` → `"consume"`;
- no explicit selection → every existing case behaves exactly as before.

Update the existing call site so the suite compiles; all five current tests in
this file must keep passing unchanged in meaning.

### Task 2 — Thread the signal through useSteamContext

`src/components/qam/useSteamContext.ts`.

1. Add to `UseSteamContextOptions`:
   - `explicitSelectionPending: boolean`
   - `onExplicitSelectionConsumed: () => void`
2. Pass `explicitSelectionPending` into the `resolveQamOpenSelection` call in the
   second effect.
3. When the resolved action is `"consume"` **and** `explicitSelectionPending` was
   true, call `onExplicitSelectionConsumed()` in addition to clearing
   `pendingCurrentGameSelection.current`.
4. Add both new values to that effect's dependency array.

Do not change the first effect. Do not change `selectCurrentSteamGameIfAvailable`.

Extend `src/components/qam/useSteamContext.test.ts` to prove that with
`explicitSelectionPending` true the setter is **not** called, and that
`onExplicitSelectionConsumed` fires exactly once.

### Task 3 — Set the flag on a deliberate dropdown choice

`src/components/qam/LudusaviContent.tsx`.

1. Add `const explicitSelectionRef = useRef(false);`
2. Wrap the controller's `onGameChange` so the ref is set **before** delegating:

   ```ts
   const handleGameChange = (data: Parameters<typeof onGameChange>[0]) => {
     explicitSelectionRef.current = true;
     onGameChange(data);
   };
   ```

3. Pass `handleGameChange` to `GameSettingsSection` instead of `onGameChange`
   (`:564`).
4. Wire into `useSteamContext`:
   - `explicitSelectionPending: explicitSelectionRef.current`
   - `onExplicitSelectionConsumed: () => { explicitSelectionRef.current = false; }`

Do not change `GameSettingsSection.tsx`. Its `onGameChange` prop type already
matches.

### Task 4 — Do not suppress refresh-path auto-selection

`applyCachedRefreshResult` (`:244-252`) and `applyRefreshResult` (`:270-297`)
also call `selectCurrentSteamGameIfAvailable`, but only when their caller passes
`allowSteamContextSelection = true`, which happens on initial load rather than on
a dropdown interaction. Leave both untouched.

Record in the session log that this was considered and deliberately excluded.

### Task 5 — Documentation

Update `DEVELOPMENT.md` where the selected-game invariant is described (added by
the selected-game-view-state plan), stating that a deliberate dropdown choice
suppresses exactly one subsequent Steam-context auto-selection, and that a
genuine QAM reopen still auto-selects the running game.

Record a session log under `docs/agent_conversations/` per the repo protocol.

### Known limitation — state it, do not fix it

The flag is one-shot and is only consumed when the panel is visible. If a future
Steam build stops flipping QAM visibility when the dropdown opens, the flag would
instead be consumed by the next genuine reopen, costing one missed
auto-selection. That is an acceptable failure mode. Note it in the session log;
do not add a timeout to work around it.

---

## Quality Gates

Run before marking any round complete:

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

The round is not complete unless:

1. all requested implementation work is done;
2. all relevant tests pass;
3. build/typecheck gates pass;
4. review notes have not been deleted;
5. the working tree is clean;
6. all code/docs changes are committed.

---

## Verification

Automated checks the implementer runs and must report output for:

```bash
scripts/orchestration/run-quality-gates
```

Expected: every command exits 0, with new tests present for Tasks 1 and 2.

Targeted checks before marking the round complete:

1. `git grep -n "explicitSelectionPending" -- src` shows it defined in
   `qamOpenSelection.ts`, consumed in `useSteamContext.ts`, and supplied from
   `LudusaviContent.tsx` — and nowhere else.
2. `git grep -n "selectCurrentSteamGameIfAvailable" -- src` still shows the two
   refresh-path call sites in `LudusaviContent.tsx` unchanged.
3. No backend file changed. This is frontend-only; a diff touching
   `py_modules/` means the scope was exceeded.
4. `git diff --stat` does not include `src/components/qam/GameSettingsSection.tsx`.

Deferred verification — cannot be done in this environment. State it plainly in
the session log rather than claiming it passed:

- On-device, **with a game running** (this is the condition that reproduces the
  bug): open the QAM and change the game in the dropdown. The dropdown must stay
  on the chosen game and must not revert to the running game.
- On-device: repeat several times in a row, choosing a different game each time.
- On-device: after choosing a game, fully close the QAM and reopen it while the
  same game is still running. Auto-selection must still pick the running game —
  the suppression is one-shot and must not persist across a genuine reopen.
- On-device: with no game running, confirm dropdown changes still work and still
  persist across a close/reopen.
- Confirm via pulled logs (`./run.sh uv run python scripts/pull_plugin_logs.py
  --host steamdeck-legos`) that after a dropdown change there is **no**
  `qam_context: QAM current game selected` line overwriting the chosen game, and
  that `settings_change_persisted` still reports the chosen value.

---

## Mark Round Complete

When the implementation round is complete and the working tree is clean, run:

```bash
scripts/orchestration/mark-finished explicit-selection-beats-autoselect
```

This writes:

```text
/tmp/sdh_ludusavi/explicit-selection-beats-autoselect_finished
```

Then exit cleanly. If this process exits, the orchestrator will resume you through
`scripts/orchestration/continue-implementer explicit-selection-beats-autoselect`.

---

## Review Polling Loop

After marking the round complete, check existing review notes first, then poll for new review notes if you remain active:

```text
docs/review/explicit-selection-beats-autoselect-review-*.md
```

When a review note exists or a new review note appears:

1. Read the full review note.
2. If the note ends with:

   ```text
   STATUS: CHANGES_REQUESTED
   ```

   then resume work.

3. Clear the round-complete marker:

   ```bash
   scripts/orchestration/clear-finished explicit-selection-beats-autoselect
   ```

4. Address every requested change.
5. Run quality gates:

   ```bash
   scripts/orchestration/run-quality-gates
   scripts/orchestration/check-review-notes-not-deleted
   ```

6. Commit code/docs fixes.
7. Commit the review-note file itself if it is not already committed:

   ```bash
   git add docs/review/explicit-selection-beats-autoselect-review-*.md
   git commit -m "docs(review): record explicit-selection-beats-autoselect review notes"
   ```

8. Recreate the round-complete marker:

   ```bash
   scripts/orchestration/mark-finished explicit-selection-beats-autoselect
   ```

9. Either continue polling or exit cleanly. If you exit, the orchestrator will resume you with `scripts/orchestration/continue-implementer explicit-selection-beats-autoselect` after the next review note is created.

---

## Approval Handling

If the latest review note ends with:

```text
STATUS: APPROVED
```

then:

1. Confirm every previous review item has been addressed.
2. Confirm all review notes are committed:

   ```bash
   scripts/orchestration/check-review-notes-committed explicit-selection-beats-autoselect
   ```

3. Confirm the working tree is clean:

   ```bash
   git status --short
   ```

4. Finalize:

   ```bash
   scripts/orchestration/finalize explicit-selection-beats-autoselect
   ```

5. Confirm the finalized marker exists:

   ```text
   /tmp/sdh_ludusavi/explicit-selection-beats-autoselect_finalized
   ```

6. Stop polling and exit cleanly.

---

## Review Rules

Do not write your own review.

Do not create files under:

```text
docs/review/
```

Do not delete files under:

```text
docs/review/
```

Only the orchestrator writes review notes. Your job is to read them, resolve them, commit them as audit records, and continue the loop.

---

## Finalization Rules

Only finalize after a review note with:

```text
STATUS: APPROVED
```

Finalization is performed with:

```bash
scripts/orchestration/finalize explicit-selection-beats-autoselect
```

Do not manually merge into `dev` unless the finalize script fails and the user/orchestrator explicitly instructs you to recover manually.

Leave both markers in place after finalization:

```text
/tmp/sdh_ludusavi/explicit-selection-beats-autoselect_finished
/tmp/sdh_ludusavi/explicit-selection-beats-autoselect_finalized
```

Any project-specific release step runs from the project's
`scripts/orchestration-hooks/finalize-release` hook, invoked by finalize.
