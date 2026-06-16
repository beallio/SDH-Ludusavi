# Fix QAM Toggle Flicker and Enlarge Status Icons — Implementation Plan

## Context

Two QAM issues, both surfaced after the over-engineering cleanup shipped:

1. **The QAM flickers every time any toggle is changed.** Other plugins don't —
   their toggles update instantly. Root cause: a settings write is reported as a
   transient "busy" state that disables every interactive control for the
   duration of the (fast) RPC, so each toggle disables→re-enables all controls.
2. **The status-strip icons could be slightly larger.** No regression — they are
   18px and the user would like them a touch bigger.

Outcome: toggling a setting updates instantly with no flicker (matching other
plugins), and the status-strip icons render slightly larger and uniformly.

The two issues are independent (different files, different risk). Do them as
**separate units / separate commits**. Within Unit 1 the two files must change
together to keep `tsc` green, so Unit 1 is one coherent commit.

---

## Unit 1 — Eliminate the QAM toggle flicker

### Root cause (read first)

- `src/components/qam/LudusaviContent.tsx:167`:
  `const isBusy = operation.is_running || busyLabel !== null || backgroundRefreshBusy || queueBusy;`
- `isBusy` is passed to `AutoSyncSettingsSection`, `GameSettingsSection`, and
  `NotificationSettingsSection`, each of which sets `disabled={isBusy}` on its
  `ToggleField` / `DropdownItem` / buttons.
- A settings write goes through `src/settings/settingsMutationRuntime.ts`, whose
  `markBusy()` sets `busyLabel = "Updating settings"` and whose queue drives
  `queueBusy`. Both flip `isBusy` true for the brief RPC window, then false —
  disabling then re-enabling every control. That flip is the visible flicker.
- The settings runtime already serializes writes (the queue) and guards against
  out-of-order results (per-setting sequence counters) and rolls back on failure,
  so disabling controls during a write is unnecessary as well as harmful.

### Required change

Make settings writes stop signaling a control-disabling "busy" state. Keep the
serial queue itself (it prevents racing RPCs) — remove only the busy *reporting*.

- `src/settings/settingsMutationRuntime.ts`:
  - Remove the `markBusy()` calls / the code that sets `busyLabel = "Updating
    settings"`. Settings writes must never set a disabling busy label.
  - Remove the queue busy-reporting surface (`getQueueBusy`, `subscribeQueue`,
    `queueListeners`, `notifyQueueListeners`) and the `setBusyLabel` controller
    option **only if** they are unused after the change — `grep -rn` each symbol
    across `src/` first. **Keep** the actual serialization (`settingsQueue`,
    `processSettingsQueue`, `enqueueSettingsUpdate`) and the per-setting sequence
    / rollback logic unchanged.
- `src/components/qam/LudusaviContent.tsx`:
  - Remove the `queueBusy` state (`useState(... getQueueBusy())`, ~line 125) and
    the `subscribeQueue` effect (~lines 144-153).
  - Redefine `isBusy` (line 167) to exclude the settings-write transient:
    `const isBusy = operation.is_running || busyLabel !== null || backgroundRefreshBusy;`
    (no `queueBusy`). Because "Updating settings" is no longer set, `busyLabel`
    now only ever reflects real operations — "Loading", "Refreshing games",
    "Backup running", "Restore running" — which legitimately disable controls.
  - Leave the `setBusyLabel` uses that set those real-operation labels (load,
    refresh, force backup/restore) exactly as they are.
- Run `tsc` (via `pnpm test`) and remove any now-unused locals/imports it flags.

Do NOT change the optimistic-update path (`ludusaviStore.setAutoSyncEnabled`
etc.) — the toggle's `checked` already updates instantly from the store; that is
correct and not the flicker.

### TDD

In `src/settings/settingsMutationRuntime.test.ts` add a regression test FIRST
(must fail before the change):

- Construct the controller with a spy `setBusyLabel`. Invoke `toggleAutoSync(true)`
  and a notification toggle, let the queue drain. Assert `setBusyLabel` is never
  called with `"Updating settings"` (after the change it is not called at all for
  settings writes). This fails today and passes after removing `markBusy()`.
- Keep/extend the existing tests proving sequencing, supersede, and rollback are
  unchanged; the full `settingsMutationRuntime.test.ts` suite must stay green.

Commit: `fix(qam): stop settings writes from disabling controls (toggle flicker)`

---

## Unit 2 — Enlarge the status-strip icons (separate commit)

### File

`src/surfaces/autoSyncStatusRenderer.tsx` — the `renderAutoSyncStatusHtml` `<style>`
block. `iconSvgForAutoSyncStatus` is consumed only here, so this is the only file.

### Required change

- In the CSS, make the inline SVG fill its container so one knob resizes every
  icon regardless of each SVG's hardcoded `width="18"`/`height="18"` (this also
  normalizes the Unit-E inlined `syncthing_complete` icon):
  add `.icon svg { width: 100%; height: 100%; display: block; }`.
- Bump the icon box: `.icon { width: 18px; height: 18px; ... }` → `width: 22px;
  height: 22px;` (slightly larger; this single value is the tunable — 20-24 is the
  sensible range, default 22). Do not edit the per-icon SVG `width`/`height`
  attributes.
- Verify the strip does not clip a 22px icon: the `.bar` is `height: 100vh` of the
  BrowserView surface whose size comes from `getAutoSyncStatusBounds()` in
  `src/surfaces/autoSyncStatusBrowserView.ts`. If 22px clips vertically, bump that
  bounds height by the same few px; otherwise leave bounds unchanged.

### TDD

In `src/surfaces/autoSyncStatusSurface.test.ts` add an assertion FIRST that
`renderAutoSyncStatusHtml(...)` output contains the new icon CSS (e.g.
`.icon { width: 22px` and `.icon svg { width: 100%`). Fails before, passes after.

Commit: `style(status): enlarge status-strip icons`

---

## Quality gates (run before marking any round complete)

```bash
scripts/orchestration/run-quality-gates
scripts/orchestration/check-review-notes-not-deleted
git status --short
```

If run directly: `./run.sh uv run pytest` (unchanged backend should stay green),
and `./run.sh pnpm run verify` (vitest + `tsc --noEmit` + build + supply chain).
Format only files you changed; do not reformat unrelated files.

## Verification

- `pnpm test` green incl. the two new tests; `tsc --noEmit` clean; `pnpm run
  build` succeeds.
- Reason through the flicker fix: confirm no remaining control reads the
  settings-write transient — `grep -rn "Updating settings\|queueBusy\|subscribeQueue\|getQueueBusy"`
  returns nothing live after the change.
- On-device (Steam Deck) testing is DEFERRED until after the dev push: then
  confirm (a) toggling auto-sync / each notification toggle / update-channel /
  automatic-checks no longer flickers and rapid toggling settles on the last tap;
  (b) controls still disable during a real backup/restore/refresh; (c) the
  status-strip icons render slightly larger and the SYNCTHING COMPLETE icon
  matches its siblings.

## Risks and edge cases

- **Unit 1:** ensure the serial queue and sequence/rollback logic are untouched —
  only the busy *reporting* is removed. Verify controls STILL disable during an
  actual operation (`operation.is_running`) and during load/refresh.
- **Unit 1:** `tsc` may flag newly-unused symbols (`queueBusy`, `setBusyLabel`,
  queue-listener helpers) — remove them; do not silence with `// @ts-ignore`.
- **Unit 2:** confirm the larger icon does not clip in the strip; adjust the
  BrowserView bounds height only if needed.
- Magnitude of the icon bump is subjective; 22px is a starting point a reviewer
  may tune in one line.

## Definition of done

- Both units committed on `feat/qam-flicker-and-icon-size` as separate commits.
- `pytest`, `pnpm run verify` (vitest + tsc + build) pass; tree clean.
- Caches under `/tmp/sdh_ludusavi`; session log recorded under
  `docs/agent_conversations/`.
- Review notes committed; finalized via the orchestration script after approval.

---

## Scope discipline

- Implement only Units 1 and 2. Do not modify files outside their scope.
- Preserve all observable behavior except the two intended changes (no flicker;
  larger icons). Do not change settings persistence, sequencing, or rollback.
- Never edit a test's expected value to mask a behavior change. If a test must
  change, justify it in the session log.
- Note any unrelated improvement in the session log for a separate plan; do not
  make it here.

---

## Orchestration contract

**Slug:** `qam-flicker-and-icon-size`

**Plan file:**

```text
docs/plans/2026-06-15_qam-flicker-and-icon-size.md
```

**Implementation branch:**

```text
feat/qam-flicker-and-icon-size
```

**Round-complete marker:**

```text
/tmp/sdh_ludusavi/qam-flicker-and-icon-size_finished
```

**Finalized marker:**

```text
/tmp/sdh_ludusavi/qam-flicker-and-icon-size_finalized
```

**Review notes:**

```text
docs/review/qam-flicker-and-icon-size-review-*.md
```

Each review note ends with exactly one trailer: `STATUS: CHANGES_REQUESTED` or
`STATUS: APPROVED`.

### Required agent protocol

1. Use the **implementer** skill. Work from the repository root.
2. Branch from `dev`: `git checkout dev && git pull --ff-only origin dev &&
   git checkout -b feat/qam-flicker-and-icon-size`.
3. Commit this plan as the first commit on the branch
   (`docs(plan): add qam-flicker-and-icon-size implementation plan`).
4. Follow TDD for both units (write the failing test first).
5. Run quality gates before marking any round complete.
6. Do not write your own review. Do not create or delete files under
   `docs/review/`. Review notes are durable audit records and must be committed.

### Round complete

When a round's work is done and the tree is clean:

```bash
scripts/orchestration/mark-finished qam-flicker-and-icon-size
```

Then either keep polling `docs/review/qam-flicker-and-icon-size-review-*.md`, or
exit cleanly — the orchestrator will resume you with
`scripts/orchestration/continue-implementer qam-flicker-and-icon-size` (`agy -c -p`)
after the next review note is written. On every resume, scan existing review
notes before waiting for new file events.

### CHANGES_REQUESTED

```bash
scripts/orchestration/clear-finished qam-flicker-and-icon-size
# implement every requested change; run quality gates; commit fixes
git add docs/review/qam-flicker-and-icon-size-review-*.md
git commit -m "docs(review): record qam-flicker-and-icon-size review notes"
scripts/orchestration/mark-finished qam-flicker-and-icon-size
```

### APPROVED

```bash
scripts/orchestration/check-review-notes-committed qam-flicker-and-icon-size
git status --short
scripts/orchestration/finalize qam-flicker-and-icon-size
# confirm /tmp/sdh_ludusavi/qam-flicker-and-icon-size_finalized exists, then exit
```

Finalization (via the script) commits any outstanding review note, merges the
branch into `dev`, deletes the working branch, pushes `dev`, and requests a dev
release. Steam Deck / user testing is deferred until after `dev` is pushed.

## Out of scope (do not change)

- The optimistic store update path in `ludusaviState.tsx` / the toggle `checked`
  binding — it already updates instantly and is not the flicker.
- The settings serialization queue and the per-setting sequence/rollback logic —
  keep them; only the busy *reporting* is removed.
- `PluginUpdateSection` busy wiring (`isChecking`/`isInstalling`) — unrelated.
