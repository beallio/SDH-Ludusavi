# Restore Button Width + "Last Operation" After Restore

## Context

The Backup Browser cards (shipped via `dev` @ `1dd49f5`) look much better, but the
user found two follow-ups on the Deck:

1. **The Restore button is too wide.** In each snapshot card it stretches to ~half
   the card width instead of hugging its "Restore" label. (Screenshot confirms.)
   Steam `DialogButton` defaults to full width; inside the card's
   `justify-content: space-between` flex row it expands.
2. **"Last Operation" still says "Backup complete" after a point-in-time restore.**
   It should read "Restore complete". Root cause is NOT the backend or the text
   formatter (both already handle restore) — it's that the QAM **never re-fetches
   game history after a manual operation**, so `last_operation` stays stale.

Both fixes are **frontend-only**. This runs through the same
**plan → implement → review** loop. **On-device / user testing is deferred until the
dev release is pushed to GitHub** — the review loop is code-review + gates only.

### Diagnosis details (so the implementer doesn't re-derive)

- **Backend is correct.** `restore_backup_version` in
  `py_modules/sdh_ludusavi/lifecycle.py:444` calls
  `record_history(game.name, "restore", "point_in_time_restore", "restored")` on
  success. `_update_last_operation` (`history.py:152`) picks the newest entry by
  timestamp, so the persisted `last_operation` becomes the restore.
- **Formatter is correct.** `getLastOperationText` in
  `src/formatting/operationText.ts` returns `"Restore complete"` for
  `status === "restored"`. "Last Operation" is rendered from
  `selectedHistory.status` in `src/components/qam/GameSettingsSection.tsx:122`,
  where `selectedHistory = gameHistory[selectedGame]?.last_operation`
  (`LudusaviContent.tsx:161`).
- **The gap:** `getGameHistoryCall()` / `ludusaviStore.setGameHistory(...)` are only
  invoked at QAM load (`LudusaviContent.tsx:373/386`, `index.tsx:45`). After a manual
  op, `runSnapshotRestore` (`LudusaviContent.tsx:702`) and `runForceOperation`
  (`LudusaviContent.tsx:624`) refresh games (`applyRefreshResult`), operation status,
  and logs — but **never history**. So the displayed "Last Operation" is whatever was
  loaded when the QAM opened (the prior backup).

---

## Canonical tokens (use these EXACT strings everywhere)

| Thing | Value |
|---|---|
| `plan_name` | `restore_button_and_op_status` |
| Working branch | `fix/restore-button-and-op-status` (branched from **`dev`**, NOT `main`) |
| This plan doc | `docs/plans/restore_button_and_op_status.md` |
| **Completion marker** (implementer → reviewer) | `/tmp/sdh_ludusavi/restore_button_and_op_status_finished` |
| **Review notes** (reviewer → implementer) | `docs/review/restore_button_and_op_status_review_<n>.md` (`<n>` = 1, 2, 3…) |
| Approval signal | a review note whose body contains the literal token `PASS` |
| Dev-release base version | `0.3.0` → `./scripts/request_dev_release.sh 0.3.0` |

> **Branch from `dev`, not `main`** (`main` lacks this code, 116+ commits behind).
> Override the implementer skill's "branch from main" default.

## How to run this

This plan doc is delivered untracked in the working tree by the reviewer. Hand it to a
**fresh session** and tell it to **use the `implementer` skill**. That session is "the
implementer"; the reviewer does the code review. They communicate only through the
marker file and the review-note files above.

---

# PART A — Technical work (for the implementer)

Files in scope:
- `src/components/modals/BackupBrowserModal.tsx` (issue 1)
- `src/components/qam/LudusaviContent.tsx` (issue 2)

Out of scope: backend (already correct), the `operationText` formatter (already
correct), other QAM sections, version bumps.

## A1. Issue 1 — make the Restore button hug its label

In `BackupBrowserModal.tsx`, the card is a flex row
(`display:flex; align-items:center; justify-content:space-between`) with two children:
the text column `<div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>`
and the `<DialogButton …>Restore</DialogButton>`.

Change so the text column flexes and the button is a fixed, compact size:

1. Text column: add `flex: 1` and `minWidth: 0` to its style (so it takes the
   available width and lets long text wrap/ellipsize instead of pushing the button):
   ```tsx
   <div style={{ display: "flex", flexDirection: "column", gap: "4px", flex: 1, minWidth: 0 }}>
   ```
2. Restore button: give it an explicit width and stop it from growing. Inline `style`
   overrides Steam's default full-width class:
   ```tsx
   <DialogButton
     preferredFocus={idx === 0}
     onClick={() => onRestore(b.id, timestampStr)}
     style={{ width: "120px", flexShrink: 0, marginLeft: "12px" }}
   >
     Restore
   </DialogButton>
   ```
   `120px` is a sensible compact width (tunable — the user may refine via review).
   `flexShrink: 0` keeps it from collapsing; `marginLeft` preserves spacing from the
   text. Do NOT remove `preferredFocus`/`onClick`.

Keep everything else (the bounded `scrollRef` div, card background/border, open-at-top
effect) exactly as-is.

## A2. Issue 2 — refresh game history after a manual operation

After a manual op completes, re-fetch history so `last_operation` (and thus "Last
Operation") reflects the just-finished operation. `getGameHistoryCall` is already
imported in `LudusaviContent.tsx`; `ludusaviStore.setGameHistory` and `isRpcStatus`
are already in scope (used in `fetchInitialState`).

Apply to BOTH manual-op handlers, which share the same post-op refresh block:
- `runSnapshotRestore` (`~LudusaviContent.tsx:744`) — **the reported case**.
- `runForceOperation` (`~LudusaviContent.tsx:670`) — same latent staleness; fix for
  consistency (force backup/restore should also update "Last Operation").

In each, alongside the existing
`refreshGamesCall` / `getOperationStatus` / `getRecentLogs` block, add a history
re-fetch and apply it under the existing `isMounted.current` guard. Pattern:

```tsx
const refreshed = await refreshGamesCall(false);
const operationStatus = await getOperationStatus();
const recentLogs = await getRecentLogs();
const refreshedHistory = await getGameHistoryCall();   // NEW

applyRefreshResult(refreshed);
if (isMounted.current) {
  setOperation(operationStatus);
  setLogs(recentLogs);
  if (!isRpcStatus(refreshedHistory)) {                // NEW
    ludusaviStore.setGameHistory(refreshedHistory);    // NEW
  }
}
```

Result: after a point-in-time restore, the recorded `"restored"` entry becomes
`last_operation`, and "Last Operation" renders **"Restore complete"** via the existing
`getLastOperationText`. After a force backup/restore it likewise updates.

> Do NOT change the displayed wording — "Restore complete" is the existing string for
> `status === "restored"` and matches the user's "or something similar".

## A3. Tests (TDD where extractable; CLAUDE.md §9)

- `operationText.ts` already maps `"restored" → "Restore complete"`; if there is an
  existing test file for it, add/confirm a case. The history-refresh wiring lives
  inside the large `LudusaviContent` component with no React rig, so it is verified by
  `tsc` + the deferred on-device test rather than a new component test. Do not invent a
  brittle component harness.

## A4. Gates (run before EACH commit)

```
pnpm run typecheck      # tsc --noEmit
pnpm run test:unit      # vitest run
```
The pre-commit hook also runs the backend suite + `pnpm run verify` + `check_tdd.sh`.
If a commit/merge fails with "requirements are unsatisfiable" (vendored dep newer than
the machine's global 7-day `uv` cutoff), prefix git with `UV_FROZEN=1`. Do not edit
hook scripts. **No on-device testing during the loop** (see §B6).

---

# PART B — Coordination protocol (for the implementer)

## B1. Setup
1. `git status` — this plan doc (`docs/plans/restore_button_and_op_status.md`) is
   delivered untracked by the reviewer; expected. Run the implementer skill's
   discovery + emit `AGENT_PROTOCOL_HANDSHAKE`.
2. `git checkout dev && git pull`, then
   `git checkout -b fix/restore-button-and-op-status dev`.
3. Commit the plan doc: `docs(plans): add restore button + op status plan`.

## B2. Implement (atomic conventional commits)
- `fix(backup-browser): constrain Restore button width` (A1)
- `fix(qam): refresh game history after manual operations` (A2)

Run the A4 gates before each commit. **Commit ALL work before signaling** (last round
the marker was touched with an uncommitted file — do not repeat that; ensure
`git status` is clean except the marker before B3).

## B3. Signal completion (how the implementer tells the reviewer it's done)
After the round is committed and gates pass:
```
mkdir -p /tmp/sdh_ludusavi
touch /tmp/sdh_ludusavi/restore_button_and_op_status_finished
```
Empty file; existence + fresh mtime is the signal. **Re-`touch` it at the end of EVERY
round** so the reviewer's mtime-based watcher re-fires.

## B4. Wait for review notes (how the implementer knows the review is done)
Reviewer writes findings to `docs/review/restore_button_and_op_status_review_<n>.md`.
**Own the wait loop yourself** with the `Monitor` tool (never delegate to a background
subagent). After touching the marker for round `N`, poll ~60s for the next-numbered
note:
```
test -f docs/review/restore_button_and_op_status_review_<N>.md
```
(`<N>` = 1, then 2, …). When it appears, read it.

## B5. Process each review round, then loop
1. Address EVERY item in the note as atomic commits; run A4 gates each time.
2. Commit the review-note file if not already
   (`docs(review): record restore button + op status review round <n>`).
3. Re-`touch /tmp/sdh_ludusavi/restore_button_and_op_status_finished`.
4. Return to B4 and wait for the next-numbered note.

Repeat until a review note's body contains the literal token **`PASS`** → go to B6.

## B6. Endgame (only after a review note contains `PASS`)
> **On-device / user testing is deferred to AFTER this step.** PASS is granted on code
> review + green gates alone; do NOT wait for Steam Deck confirmation. The user
> verifies on the Deck once the dev release is on GitHub.

In order:
1. Ensure the approving review note (and all prior) are committed on the branch.
2. Record session log at
   `docs/agent_conversations/<YYYY-MM-DD>_restore_button_and_op_status.json`; commit it.
3. Merge into `dev`:
   ```
   git checkout dev
   git pull --ff-only
   git merge --no-ff fix/restore-button-and-op-status
   ```
   (`UV_FROZEN=1 git merge …` if hook re-resolution fails.)
4. Clean up:
   ```
   git branch -d fix/restore-button-and-op-status
   rm -f /tmp/sdh_ludusavi/restore_button_and_op_status_finished
   ```
5. Push: `git push origin dev`.
6. Dev release (workflow dispatch — NOT a stable tag/release):
   `./scripts/request_dev_release.sh 0.3.0` (needs `gh` auth; surface failures).
7. Report the merge SHA + dev-release dispatch. The `v0.3.0-dev.*` build is what the
   user will test the two fixes on.

---

## Reviewer side (for reference — implementer does not do these)
- Watch `/tmp/sdh_ludusavi/restore_button_and_op_status_finished` (`Monitor`, ~60s,
  mtime cutoff). On fire, code-review the branch diff + run gates, then write
  `docs/review/restore_button_and_op_status_review_<n>.md`. When satisfied (code +
  gates only — no Deck check), write a note containing `PASS`.

## Definition of Done
- [ ] Restore button is a compact fixed width (hugs its label), text column flexes.
- [ ] After a point-in-time restore, "Last Operation" shows "Restore complete"
      (history re-fetched after manual ops; force backup/restore also refresh).
- [ ] `pnpm run typecheck` + `pnpm run test:unit` pass; backend gates pass via hook.
- [ ] Session log recorded; review notes committed.
- [ ] Branch merged to `dev`, branch deleted, marker removed; `dev` pushed;
      dev release dispatched. On-device testing deferred to the published build.
