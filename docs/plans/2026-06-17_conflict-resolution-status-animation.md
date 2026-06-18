# Plan: Animate Status Bar During Conflict Resolution

- **TITLE:** Animate Status Bar During Conflict Resolution
- **SLUG:** `conflict-resolution-status-animation`
- **PLAN_PATH:** `docs/plans/2026-06-17_conflict-resolution-status-animation.md`
- **Implementation branch:** `feat/conflict-resolution-status-animation`

---

## Context

When a game launches and the plugin detects a save conflict (both local and backup
changed, recency ambiguous), it shows the **Conflict Detected** modal and pauses the
game. After the user picks **Keep Local Save** (backup) or **Restore Backup Save**
(restore), the backend runs the operation — but the status strip does **not** show the
animated "BACKING UP LOCAL SAVE" / "RESTORING BACKUP SAVE" icon during that operation.

Cause: the normal auto paths publish an in-progress animated status before the RPC
(`"restoring"` in the needed-restore start path at `gameLifecycleController.tsx:278-283`;
`"backing_up"` in the exit-backup path at `:419-425`). The **conflict-resolution branch
does not**. It publishes the static amber `"conflict"` status, then jumps straight from
`resolveGameStartConflictCall(...)` to `completeAutoSyncStatus(result)`. So the strip
stays on the static "SAVE CONFLICT" icon during the operation and then flips to the final
result with no animation in between. (Worse: `"conflict"` is not a "running" status, so the
strip auto-hides after `RESULT_HIDE_DELAY_MS` = 2000ms — see Known Risks.)

Intended outcome: when the user resolves a conflict, the status strip shows the matching
animated in-progress icon while the backup/restore runs, exactly like the non-conflict
auto paths.

The animation infrastructure already exists and must be reused unchanged — no renderer,
surface, or modal edits are required.

---

## Root Cause (exact location)

File: `src/controllers/gameLifecycleController.tsx`, inside `handleAppStart`, the
`if (checkResult.status === "conflict")` branch (currently ~lines 296-337).

Current sequence after the user chooses a resolution:

```tsx
if (autoSyncEnabled && tracked) {
  activeMonitorEpoch = epoch;
  preGameWatch = syncthingMonitor.start("pre_game", name, appID);
}
const result = await resolveGameStartConflictCall(
  checkResult.game ?? name,
  appID,
  resolution,
);
completeAutoSyncStatus(result, { gameName: name, appID, tracked });
```

There is no `publishAutoSyncStatus("backing_up" | "restoring", ...)` between choosing the
resolution and running the operation.

### Why this is the only site
`resolveGameStartConflictCall` (frontend) → `resolve_game_start_conflict` (backend,
`py_modules/sdh_ludusavi/lifecycle.py:191`) is invoked **only** from this branch.
`keep_local` runs a backup; `restore_backup` runs a restore. There is no exit-time
conflict path. The fix is localized to this one branch.

### Why no renderer/surface change is needed
- `src/surfaces/autoSyncStatusRenderer.tsx`:
  - `autoSyncStatusText`: `backing_up` → "BACKING UP LOCAL SAVE", `restoring` →
    "RESTORING BACKUP SAVE".
  - `iconSvgForAutoSyncStatus`: `backing_up`/`restoring` return the arrow SVG containing
    `<rect class="backup-arrow-fill" ...>` (and `restoring` adds a 180° rotation).
  - CSS `.backup-arrow-fill { animation: backup-arrow-fill-up 1.6s ease-out infinite; }`
    is always applied, so simply publishing these statuses animates the icon.
- `src/surfaces/autoSyncStatusSurface.tsx`: `isLudusaviRunningStatus` already includes
  `backing_up`/`restoring`, so `publish` resets the timed-out flag and schedules the long
  running-hide ceiling. `complete()` then maps `backed_up`/`restored` → `has_backup`.
  No change required.

---

## The Fix

Edit **only** `src/controllers/gameLifecycleController.tsx`. In the conflict branch,
insert an in-progress publish immediately before `resolveGameStartConflictCall`, after the
`syncthingMonitor.start("pre_game", ...)` block:

```tsx
        if (autoSyncEnabled && tracked) {
          activeMonitorEpoch = epoch;
          preGameWatch = syncthingMonitor.start("pre_game", name, appID);
        }
        // Mirror the non-conflict auto paths: show the in-progress animation that
        // matches the chosen resolution. keep_local runs a backup; restore_backup
        // runs a restore. Without this the strip stays on the static "conflict"
        // icon until the result and never animates.
        publishAutoSyncStatus(
          resolution === "restore_backup" ? "restoring" : "backing_up",
          {
            source: "lifecycle_start",
            gameName: name,
            appID,
            tracked,
          },
        );
        const result = await resolveGameStartConflictCall(
          checkResult.game ?? name,
          appID,
          resolution,
        );
        completeAutoSyncStatus(result, { gameName: name, appID, tracked });
```

Notes:
- `resolution` is typed `ConflictResolution` (`"keep_local" | "restore_backup"`), so the
  ternary is exhaustive. Map `restore_backup` → `"restoring"`, everything else
  (`keep_local`) → `"backing_up"`. The two labels exactly describe the two operations.
- Use `source: "lifecycle_start"` to match the existing needed-restore publish.
- Do **not** change ordering of the syncthing monitor start, the `paused` guard, the
  `!resolution` early-return, or the `completeAutoSyncStatus`/`notifyFailure` tail.
- Do **not** add `restoring`/`backing_up` publishes anywhere else.

---

## Combine vs. Separate

- **Combine into one atomic commit:** the production edit in
  `gameLifecycleController.tsx` **and** the new unit tests in
  `gameLifecycleController.test.ts`. They are a single behavior change verified by its
  tests. Write the tests first (red), then apply the fix (green).
  - Suggested message: `fix(autosync): animate status strip during conflict resolution`
- **Separate / first commit:** the plan doc `docs/plans/2026-06-17_conflict-resolution-status-animation.md`.
- **Separate (optional, last):** the session log under `docs/agent_conversations/`
  (see Definition of Done). It may also be folded into the fix commit.
- **Do not modify** `autoSyncStatusRenderer.tsx`, `autoSyncStatusSurface.tsx`,
  `ConflictResolutionModal.tsx`, or any backend file. If a gate failure seems to demand
  it, stop and re-check — that would indicate scope creep or a wrong diagnosis.

---

## Files

Inspect (read) before editing:
- `src/controllers/gameLifecycleController.tsx` — the conflict branch (target) and the
  needed-restore branch (`:278-293`) as the pattern to mirror.
- `src/surfaces/autoSyncStatusRenderer.tsx` — confirm `backing_up`/`restoring` text +
  animated SVG (no edit).
- `src/surfaces/autoSyncStatusSurface.tsx` — confirm `publish`/`complete` semantics
  (no edit).
- `src/controllers/gameLifecycleController.test.ts` — existing harness + the conflict test
  at `:639` ("conflict start cancels the pre-game watch while resolving conflict").
- `src/types/index.ts` — confirm `ConflictResolution` and `AutoSyncStatusKind` members.

Modify:
- `src/controllers/gameLifecycleController.tsx` (the fix).
- `src/controllers/gameLifecycleController.test.ts` (new tests).

---

## Tests (write first — RED, then GREEN)

Add two tests to `src/controllers/gameLifecycleController.test.ts`, modeled on the existing
conflict test at line 639. Key harness facts:
- Use `nInstanceID: 2` (not the `triggerStart` helper, which uses `nInstanceID: 1`) so
  `shouldPauseLaunch` is true and `paused` becomes true — otherwise the conflict branch
  bails at the `if (!paused)` guard.
- `mockResolveConflict.mockResolvedValue(...)` returns the chosen resolution string.
- `mockRpc.resolveGameStartConflict` has no default; set `.mockResolvedValue(...)`.
- The session resolves to name `"Hades"`, appID `"1145300"` (from the mocked
  `Router.RunningApps`).

Test 1 — keep_local animates backing up:

```ts
it("conflict resolved with keep_local publishes the backing-up animation", async () => {
  const controller = createGameLifecycleController({
    store: mockStore,
    rpc: mockRpc,
    statusSurface: mockStatusSurface,
    resolveConflict: mockResolveConflict,
    notifyFailure: mockNotifyFailure,
    syncGlobalHistory: mockSyncGlobalHistory,
  });
  controller.start();

  mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });
  mockResolveConflict.mockResolvedValue("keep_local");
  mockRpc.resolveGameStartConflict.mockResolvedValue({ status: "backed_up" });

  lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
  await vi.runAllTimersAsync();

  expect(mockRpc.resolveGameStartConflict).toHaveBeenCalledWith(
    "Hades",
    "1145300",
    "keep_local",
  );
  expect(mockStatusSurface.publish).toHaveBeenCalledWith(
    "backing_up",
    expect.objectContaining({ source: "lifecycle_start" }),
  );
  expect(mockStatusSurface.publish).not.toHaveBeenCalledWith(
    "restoring",
    expect.anything(),
  );
});
```

Test 2 — restore_backup animates restoring:

```ts
it("conflict resolved with restore_backup publishes the restoring animation", async () => {
  const controller = createGameLifecycleController({
    store: mockStore,
    rpc: mockRpc,
    statusSurface: mockStatusSurface,
    resolveConflict: mockResolveConflict,
    notifyFailure: mockNotifyFailure,
    syncGlobalHistory: mockSyncGlobalHistory,
  });
  controller.start();

  mockRpc.checkGameStart.mockResolvedValue({ status: "conflict" });
  mockResolveConflict.mockResolvedValue("restore_backup");
  mockRpc.resolveGameStartConflict.mockResolvedValue({ status: "restored" });

  lifecycleCallback({ unAppID: 1145300, nInstanceID: 2, bRunning: true });
  await vi.runAllTimersAsync();

  expect(mockStatusSurface.publish).toHaveBeenCalledWith(
    "restoring",
    expect.objectContaining({ source: "lifecycle_start" }),
  );
  expect(mockStatusSurface.publish).not.toHaveBeenCalledWith(
    "backing_up",
    expect.anything(),
  );
});
```

Expected before the fix: both new tests FAIL (the `backing_up`/`restoring` publish never
happens). After the fix: both PASS. Confirm no existing test regresses — the conflict test
at `:639` and the needed-restore/exit tests must stay green.

---

## Quality Gates (must all pass before marking finished)

Run the canonical gate wrapper from the repo root:

```bash
scripts/orchestration/run-quality-gates
```

It runs (and you may run individually while iterating):

```bash
pnpm test            # vitest run + tsc --noEmit
pnpm run build       # rollup -c
./run.sh uv run ruff check . --fix
./run.sh uv run ruff format .
./run.sh uv run ty check py_modules/sdh_ludusavi/
./run.sh uv run pytest
```

No Python changes are expected, but the Python gates must still pass. All caches stay
under `/tmp/sdh_ludusavi` via `./run.sh`. The working tree must be clean before
`mark-finished` (it calls `require_clean_worktree`).

---

## Verification

- **Automated (authoritative for this round):** the two new vitest tests pass; full
  `pnpm test` and `pnpm run build` pass; Python gates pass.
- **Code-trace verification:** confirm the only diff in production code is the single
  inserted `publishAutoSyncStatus(...)` block in the conflict branch; renderer/surface/
  modal are untouched.
- **Manual UI verification is DEFERRED** to Steam Deck after the dev push (see
  Orchestration / finalize). On device: launch a tracked game with an ambiguous-recency
  conflict, pick each option, and confirm the strip shows the animated
  "BACKING UP LOCAL SAVE" / "RESTORING BACKUP SAVE" icon during the operation, then
  "GAME SAVE UP TO DATE".

---

## Known Risks / Notes

- **Out of scope but related:** `"conflict"` is not a running status, so the strip
  auto-hides ~2s into a long modal read (`RESULT_HIDE_DELAY_MS`). This fix re-shows the
  strip when the operation begins, but does **not** keep "SAVE CONFLICT" visible during a
  long modal wait. Do not change that behavior here; flag it if observed.
- **Epoch guard:** publishes route through `createEpochGuardedSurface`; the new publish is
  dropped if a newer lifecycle event superseded this start. That is correct — do not
  bypass the guard.
- **Skipped/failed resolution results:** if `resolveGameStartConflictCall` returns
  `skipped`/`failed`, the briefly-shown animation is immediately replaced by
  `completeAutoSyncStatus` (error/unknown/has_backup). This matches the existing
  needed-restore behavior; acceptable, no special handling.
- **Do not** introduce a new `AutoSyncStatusKind`; reuse `backing_up`/`restoring`.

---

## Definition of Done

- [ ] Plan doc saved to `docs/plans/2026-06-17_conflict-resolution-status-animation.md` and committed.
- [ ] Two new tests added and passing; no regressions.
- [ ] Production change limited to the single conflict-branch insertion.
- [ ] `scripts/orchestration/run-quality-gates` passes; working tree clean.
- [ ] README unchanged (no user-facing usage/behavior surface change beyond the animation;
      do not bump `cacheBuster` — no release-image change here).
- [ ] Session log recorded under `docs/agent_conversations/` (date, objective, files
      modified, tests added, design decisions, results).
- [ ] Conventional Commits used; atomic commits as described in "Combine vs. Separate".

---

## Orchestration Contract

You are the implementing agent. Use the `implementer` skill. Develop on
`feat/conflict-resolution-status-animation`, branched from `dev`. Do not write your own
review and do not create or delete anything under `docs/review/`. Review notes are durable
audit records written by the reviewer; when one is present in your tree, commit it.

Paths:

- Plan path:
  ```text
  docs/plans/2026-06-17_conflict-resolution-status-animation.md
  ```
- Implementation branch:
  ```text
  feat/conflict-resolution-status-animation
  ```
- Round-complete marker:
  ```text
  /tmp/sdh_ludusavi/conflict-resolution-status-animation_finished
  ```
- Finalized marker:
  ```text
  /tmp/sdh_ludusavi/conflict-resolution-status-animation_finalized
  ```
- Review notes (poll these):
  ```text
  docs/review/conflict-resolution-status-animation-review-*.md
  ```

Each review note ends with exactly one of:

```text
STATUS: CHANGES_REQUESTED
```
or:
```text
STATUS: APPROVED
```

### On completing an implementation or review round
1. Run the quality gates (`scripts/orchestration/run-quality-gates`).
2. Ensure the working tree is clean.
3. Commit all relevant changes.
4. Write the round-complete marker:
   ```bash
   scripts/orchestration/mark-finished conflict-resolution-status-animation
   ```
Then either keep polling the review-notes glob, or exit cleanly. If you exit, you will be
resumed with `agy -c -p` via `scripts/orchestration/continue-implementer conflict-resolution-status-animation`.
**On every resume, scan existing review notes first** — do not wait for a future
file-creation event.

### When a review note says `STATUS: CHANGES_REQUESTED`
1. Clear the marker:
   ```bash
   scripts/orchestration/clear-finished conflict-resolution-status-animation
   ```
2. Read the review note.
3. Implement every requested change.
4. Run the quality gates.
5. Commit the implementation fixes.
6. Commit the review note itself if not already committed.
7. Recreate the marker:
   ```bash
   scripts/orchestration/mark-finished conflict-resolution-status-animation
   ```
8. Continue polling or exit cleanly for resume.

### When a review note says `STATUS: APPROVED`
1. Confirm all review notes are committed.
2. Confirm the working tree is clean.
3. Finalize:
   ```bash
   scripts/orchestration/finalize conflict-resolution-status-animation
   ```
4. Confirm the finalized marker exists:
   ```text
   /tmp/sdh_ludusavi/conflict-resolution-status-animation_finalized
   ```
5. Stop polling and exit cleanly.

Finalization performs: commit any uncommitted review note; merge
`feat/conflict-resolution-status-animation` into `dev`; delete the working branch; push
`dev` to GitHub; request/push a new dev release via the project release script
(`./scripts/request_dev_release.sh`). Steam Deck / user testing is deferred until after the
dev push.
